"""SPDX-License-Identifier: Apache-2.0. Accounting and admission contract tests."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
try:
    from access_book.engine import Authority, Clearing, Denied, Offer, canonical
except ModuleNotFoundError as exc:
    if exc.name != "jwt":
        raise
    Authority = None


@unittest.skipIf(Authority is None, "install the interop extra")
class AccessBookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "ledger.sqlite")
        self.now = 1000
        self.authority = Authority()
        self.store = Clearing(self.path, self.authority, clock=lambda: self.now)
        self.store.seed_simulated_balance("buyer", 100)
        for resource in ("a", "b"):
            self.store.set_offer(
                Offer("publisher", resource, "a" * 64, "b" * 64, 10, 2000)
            )

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def issue(self, **changes):
        args = dict(
            buyer="buyer",
            publisher="publisher",
            resources=["a", "b"],
            max_units=20,
            request_id="issue-1",
            ttl=100,
        )
        args.update(changes)
        return self.store.issue(**args)

    def activate(self, book, token, **changes):
        args = dict(buyer="buyer", publisher="publisher")
        args.update(changes)
        return self.store.activate(book, token, **args)

    def redeem(self, book, resource="a", **changes):
        args = dict(
            buyer="buyer",
            publisher="publisher",
            content_sha256="a" * 64,
            terms_sha256="b" * 64,
            request_id="redeem-1",
        )
        args.update(changes)
        return self.store.redeem(book, resource, **args)

    def test_reserved_once_redeemed_once_and_unused_released(self):
        book, token = self.issue()
        self.assertEqual(self.issue(), (book, token))
        self.activate(book, token)
        self.activate(book, token)
        first = self.redeem(book)
        self.assertEqual(first, self.redeem(book))
        self.assertEqual(self.store.release(book, buyer="buyer"), 10)
        self.assertEqual(self.store.release(book, buyer="buyer"), 0)
        audit = self.store.audit()
        self.assertEqual(
            audit["accounts"][0],
            dict(buyer="buyer", initial=100, available=90, reserved=0, redeemed=10),
        )
        self.assertEqual(audit["publishers"][0]["accrued"], 10)
        self.assertEqual(
            (self.authority.signatures, self.authority.verifications), (1, 1)
        )

    def test_budget_and_authoritative_price(self):
        before = self.store.audit()
        for changes in (
            {"max_units": 19},
            {"max_units": True},
            {"resources": ["a", "a"]},
            {"resources": ["missing"]},
            {"ttl": 301},
        ):
            with self.assertRaises(Denied):
                self.issue(**changes)
            self.assertEqual(self.store.audit(), before)
        self.store.set_offer(Offer("publisher", "a", "a" * 64, "b" * 64, 101, 2000))
        with self.assertRaises(Denied):
            self.issue(max_units=200)
        self.assertEqual(self.store.audit()["accounts"], before["accounts"])

    def test_wrong_scope_identity_and_unadmitted_book_fail_without_debit(self):
        book, token = self.issue()
        with self.assertRaises(Denied):
            self.redeem(book)
        for changes in ({"buyer": "other"}, {"publisher": "other"}):
            with self.assertRaises(Denied):
                self.activate(book, token, **changes)
        with self.assertRaises(Denied):
            self.activate(book, token[:-1] + "x")
        self.activate(book, token)
        before = self.store.audit()
        for changes in (
            {"buyer": "other"},
            {"publisher": "other"},
            {"content_sha256": "c" * 64},
            {"terms_sha256": "c" * 64},
        ):
            with self.assertRaises(Denied):
                self.redeem(book, **changes)
        with self.assertRaises(Denied):
            self.redeem(book, "missing")
        self.assertEqual(self.store.audit(), before)

    def test_consumer_pin_and_signed_manifest(self):
        book, token = self.issue()
        row = self.store.db.execute(
            "SELECT payload FROM books WHERE id=?", (book,)
        ).fetchone()
        import json

        claims = json.loads(row["payload"])
        for consumer in (Authority(), Authority(public=self.authority.public)):
            if consumer.public is self.authority.public:
                consumer.verify(token, claims, self.now)
            else:
                with self.assertRaises(Denied):
                    consumer.verify(token, claims, self.now)
        claims["reserved_micro_usd"] = 1
        wrong = self.authority.sign(canonical(claims))
        with self.assertRaises(Denied):
            self.authority.verify(wrong, json.loads(row["payload"]), self.now)

    def test_expiry_clock_rollback_and_receipt_recovery(self):
        book, token = self.issue()
        self.activate(book, token)
        first = self.redeem(book)
        for now in (999, 1100):
            self.now = now
            with self.assertRaises(Denied):
                self.redeem(book, "b", request_id="r2")
            with self.assertRaises(Denied):
                self.activate(book, token)
        # Historic receipts can be recovered after expiry, but confer no new access.
        self.assertEqual(first, self.redeem(book))
        self.assertEqual(self.store.release(book, buyer="buyer"), 10)
        self.assertEqual(self.store.audit()["redemptions"], 1)

    def test_revocation_overrides_cached_admission(self):
        book, token = self.issue()
        self.activate(book, token)
        self.store.revoke_key()
        for action in (
            lambda: self.activate(book, token),
            lambda: self.redeem(book),
            self.issue,
        ):
            with self.assertRaises(Denied):
                action()
        self.assertEqual(self.store.release(book, buyer="buyer"), 20)
        self.assertEqual(self.store.audit()["redemptions"], 0)

    def test_idempotency_conflicts(self):
        book, token = self.issue()
        with self.assertRaises(Denied):
            self.issue(resources=["a"])
        self.activate(book, token)
        self.redeem(book)
        for resource, rid in (("b", "redeem-1"), ("a", "different-id")):
            with self.assertRaises(Denied):
                self.redeem(book, resource, request_id=rid)
        self.assertEqual(self.store.audit()["redemptions"], 1)

    def test_statement_failure_rolls_back_and_restart_recovers_receipt(self):
        book, token = self.issue()
        self.activate(book, token)
        before = self.store.audit()
        self.store.db.execute(
            "CREATE TRIGGER fail_receipt BEFORE INSERT ON redemptions BEGIN SELECT RAISE(ABORT,'injected write failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.redeem(book)
        self.assertEqual(self.store.audit(), before)
        self.store.db.execute("DROP TRIGGER fail_receipt")
        first = self.redeem(book)
        self.store.close()
        self.store = Clearing(self.path, self.authority, clock=lambda: self.now)
        self.assertEqual(first, self.redeem(book))
        self.assertEqual(self.store.audit()["redemptions"], 1)

    def test_concurrent_retries_and_double_spend(self):
        book, token = self.issue()
        self.activate(book, token)

        def spend(rid):
            store = Clearing(self.path, self.authority, clock=lambda: self.now)
            try:
                return store.redeem(
                    book,
                    "a",
                    buyer="buyer",
                    publisher="publisher",
                    content_sha256="a" * 64,
                    terms_sha256="b" * 64,
                    request_id=rid,
                )
            except Denied:
                return None
            finally:
                store.close()

        with ThreadPoolExecutor(4) as pool:
            receipts = list(pool.map(spend, ["same"] * 4))
            denied = list(pool.map(spend, ["other-1", "other-2"]))
        self.assertTrue(all(x == receipts[0] for x in receipts))
        self.assertEqual(denied, [None, None])
        self.assertEqual(self.store.audit()["accounts"][0]["redeemed"], 10)

    def test_signing_failure_does_not_reserve(self):
        before = self.store.audit()

        def fail(_):
            raise RuntimeError("injected signer failure")

        self.authority.sign = fail
        with self.assertRaises(RuntimeError):
            self.issue()
        self.assertEqual(self.store.audit(), before)

    def test_atomic_purchase_commits_once_and_recovers_after_expiry(self):
        transactions = []
        self.store.db.set_trace_callback(
            lambda sql: transactions.append(sql) if sql == "BEGIN IMMEDIATE" else None
        )
        args = dict(
            buyer="buyer",
            publisher="publisher",
            content_sha256="a" * 64,
            terms_sha256="b" * 64,
            max_units=10,
            request_id="purchase-1",
        )
        first = self.store.purchase("a", **args)
        self.assertEqual(len(transactions), 1)
        self.store.db.set_trace_callback(None)
        self.now += 400
        self.assertEqual(first, self.store.purchase("a", **args))
        self.assertEqual(self.store.audit()["accounts"][0]["redeemed"], 10)
        self.assertEqual(
            (self.authority.signatures, self.authority.verifications), (1, 1)
        )

    def test_atomic_purchase_scope_failure_rolls_back_admission_and_reservation(self):
        before = self.store.audit()
        with self.assertRaises(Denied):
            self.store.purchase(
                "a",
                buyer="buyer",
                publisher="publisher",
                content_sha256="c" * 64,
                terms_sha256="b" * 64,
                max_units=10,
                request_id="purchase-1",
            )
        self.assertEqual(self.store.audit(), before)


if __name__ == "__main__":
    unittest.main()
