"""SPDX-License-Identifier: Apache-2.0. HTTP recovery and authorization contracts."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
try:
    from http_access.ledger import Ledger
    from http_access.service import Fixture, RemoteError, rpc
except ModuleNotFoundError as exc:
    if exc.name != "jwt":
        raise
    Fixture = None


@unittest.skipIf(Fixture is None, "install the interop extra")
class HTTPAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 1000
        self.app = Fixture(self.temp.name, clock=lambda: self.now, balance=100000)

    def tearDown(self):
        self.app.__exit__()
        self.temp.cleanup()

    def assertDenied(self, fn, status=400):
        with self.assertRaises(RemoteError) as ctx:
            fn()
        self.assertEqual(ctx.exception.status, status)

    def test_network_recovery_for_lost_issue_spend_and_delivery(self):
        self.app.drop_next("issuer", "/issue")
        books = self.app.issue([["r0", "r1"], ["r2"]])
        self.assertEqual(books, self.app.issue([["r0", "r1"], ["r2"]]))
        self.app.drop_next("issuer", "/spend")
        self.app.drop_next("publisher", "/access")
        first = self.app.access("r0", "r", books[0])
        self.assertEqual(first, self.app.access("r0", "r", books[0]))
        self.assertEqual(self.app.ledger.audit()["receipts"], 1)
        self.assertEqual(self.app.counts["dropped_responses"], 3)
        self.assertEqual(self.app.keys.signatures, 2)

    def test_exact_recovery_after_expiry_revocation_and_restart(self):
        book = self.app.issue([["r0", "r1"]], ttl=2)[0]
        first = self.app.access("r0", "one", book)
        self.now += 3
        self.assertDenied(lambda: self.app.access("r1", "two", book))
        self.app.ledger.revoke(self.app.keys.kid)
        self.app.ledger = Ledger(self.app.ledger.path, self.app.keys, self.app.catalog, clock=lambda: self.now)
        self.assertEqual(first, self.app.access("r0", "one", book))
        self.assertEqual(rpc(self.app.issuer_port, "/cancel", {"book": book["book"]}, self.app.buyer_secret), {"released": 1000})
        self.assertEqual(rpc(self.app.issuer_port, "/cancel", {"book": book["book"]}, self.app.buyer_secret), {"released": 0})
        self.assertEqual(self.app.ledger.audit()["accounts"][0]["reserved"], 0)

    def test_rotation_retains_pins_and_revocation_blocks_cached_admission(self):
        old = self.app.issue([["r0", "r1"]])[0]
        self.app.access("r0", "old-0", old)
        kid = self.app.keys.kid
        self.app.keys.rotate()
        new = self.app.issue([["r0"]], request_id="new")[0]
        self.app.ledger.revoke(kid)
        self.assertDenied(lambda: self.app.access("r1", "old-1", old))
        self.app.access("r0", "new-0", new)
        self.assertEqual(self.app.ledger.audit()["receipts"], 2)

    def test_authentication_roles_and_payload_cannot_choose_buyer(self):
        p = self.app.access_payload("r0", "x")
        self.assertDenied(lambda: rpc(self.app.publisher_port, "/access", p, "wrong"), 401)
        self.assertDenied(lambda: rpc(self.app.issuer_port, "/spend", {**p, "buyer": "buyer"}, self.app.buyer_secret), 403)
        self.assertDenied(lambda: rpc(self.app.publisher_port, "/access", {**p, "buyer": "other"}, self.app.buyer_secret))
        book = self.app.issue([["r0"]])[0]
        self.assertDenied(lambda: rpc(self.app.publisher_port, "/access", self.app.access_payload("r0", "y", book), self.app.other_secret))
        self.assertEqual(self.app.ledger.audit()["receipts"], 0)

    def test_scope_terms_signature_and_retry_conflicts_do_not_charge(self):
        book = self.app.issue([["r0"]])[0]
        self.assertDenied(lambda: self.app.access("r1", "bad", book))
        p = self.app.access_payload("r0", "bad", book)
        self.assertDenied(lambda: rpc(self.app.publisher_port, "/access", {**p, "terms": "0" * 64}, self.app.buyer_secret))
        # Change signed payload, preserving syntactically plausible token framing.
        parts = book["token"].split(".")
        parts[1] = "e30"
        self.assertDenied(lambda: self.app.access("r0", "bad", {**book, "token": ".".join(parts)}))
        self.app.access("r0", "ok", book)
        self.assertDenied(lambda: self.app.access("r0", "different", book))
        self.assertDenied(lambda: self.app.access("r1", "ok"))
        self.assertDenied(lambda: self.app.issue([["r1"]]))
        self.assertEqual(self.app.ledger.audit()["receipts"], 1)

    def test_concurrent_retry_spends_once_on_both_paths(self):
        book = self.app.issue([["r0"]])[0]
        for credential in (None, book):
            request_id = "book" if credential else "direct"
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: self.app.access("r0", request_id, credential), range(4)))
            self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(self.app.ledger.audit()["receipts"], 2)

    def test_signing_and_receipt_failure_roll_back(self):
        original = self.app.keys.sign
        def fail(claims):
            raise RuntimeError("synthetic signer failure")
        self.app.keys.sign = fail
        self.assertDenied(lambda: self.app.issue([["r0"]]), 503)
        self.app.keys.sign = original
        self.assertEqual(self.app.ledger.audit()["books"], 0)
        with self.app.ledger.connection(write=True) as db:
            db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON receipts BEGIN SELECT RAISE(ABORT,'test'); END")
        self.assertDenied(lambda: self.app.access("r0", "fail"), 503)
        self.assertEqual(self.app.ledger.audit()["publisher_accrued"], 0)
        with self.app.ledger.connection(write=True) as db:
            db.execute("DROP TRIGGER fail_receipt")
        self.app.access("r0", "fail")
        self.assertEqual(self.app.ledger.audit()["receipts"], 1)

    def test_expiry_during_preparation_and_budget_are_atomic(self):
        original = self.app.keys.sign
        def delayed(claims):
            result = original(claims)
            self.now += 5
            return result
        self.app.keys.sign = delayed
        self.assertDenied(lambda: self.app.issue([["r0"]], ttl=1))
        self.app.keys.sign = original
        self.assertDenied(lambda: rpc(self.app.issuer_port, "/issue", {"request_id": "budget", "books": [["r0"]], "max_units": 999}, self.app.buyer_secret))
        self.assertEqual(self.app.ledger.audit()["books"], 0)

    @unittest.skipUnless(os.environ.get("BC_LIBRARY"), "set BC_LIBRARY for guarded GPU HTTP integration")
    def test_guarded_gpu_ready_batch_and_key_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            with Fixture(directory, mode="gpu", library=os.environ["BC_LIBRARY"],
                         device=int(os.environ.get("BC_DEVICE", "0"))) as app:
                books = app.issue([["r0"]] * 64)
                self.assertEqual(app.keys.batches, [64])
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(pool.map(lambda pair: app.access("r0", f"gpu-{pair[0]}", pair[1]), enumerate(books)))
                self.assertEqual(len({r["receipt"]["id"] for r in results}), 64)
                kid = app.keys.kid
                app.keys.rotate()
                app.ledger.revoke(kid)
                fresh = app.issue([["r1"]], request_id="rotated")[0]
                app.access("r1", "fresh", fresh)
                self.assertEqual(app.consumer.verifications, 65)
                self.assertEqual(app.ledger.audit()["receipts"], 65)


if __name__ == "__main__":
    unittest.main()
