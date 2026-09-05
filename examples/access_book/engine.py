"""SPDX-License-Identifier: Apache-2.0.

Local evaluation of scoped prepaid access, not a payment or network service.
Authenticated buyer/publisher identities and the catalog are trusted inputs.
One SQLite database is the authoritative clearing boundary. No offline spend.
Amounts are integer simulated micro-USD; no actual funds are accepted here.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import re
import secrets
import sqlite3
import time

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from batchcrypto import ORDER
from batchcrypto.jws import sign_es256

MAX_ITEMS = 256
MAX_UNITS = 10**12
MAX_TTL = 300
ISSUER = "access-book.example"
KEY_ID = "evaluation-key-1"
PROFILE = "funded-access-book-v1"


class Denied(ValueError):
    """Fail closed, without changing balances."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[a-zA-Z0-9._:/-]{1,128}", value
    ):
        raise Denied("invalid bounded identifier")
    return value


def integer(value, minimum=0, maximum=MAX_UNITS):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Denied("invalid bounded integer")
    return value


def sha256(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise Denied("invalid SHA-256 commitment")
    return value


@dataclass(frozen=True)
class Offer:
    publisher: str
    resource: str
    content_sha256: str
    terms_sha256: str
    units: int
    valid_until: int

    def validate(self):
        identifier(self.publisher)
        identifier(self.resource)
        sha256(self.content_sha256)
        sha256(self.terms_sha256)
        integer(self.units, 1)
        integer(self.valid_until, 1)


class Authority:
    """Cached CPU signing key, plus an independently configured consumer pin.

    A new instance represents process restart; callers retain their own key.
    The benchmark uses ordinary randomized OpenSSL ECDSA, not a slow key import
    per access. A future GPU issuer must use VerifiedSigner before this consumer.
    """

    def __init__(self, private=None, *, public=None):
        self.private = private or ec.generate_private_key(ec.SECP256R1())
        self.public = public or self.private.public_key()
        self.signatures = 0
        self.verifications = 0

    def sign(self, payload):
        def sign_digests(digests):
            result = []
            for digest in digests:
                der = self.private.sign(
                    digest, ec.ECDSA(utils.Prehashed(hashes.SHA256()))
                )
                r, s = utils.decode_dss_signature(der)
                result.append(
                    r.to_bytes(32, "big") + min(s, ORDER - s).to_bytes(32, "big")
                )
            return result

        token = sign_es256([payload], key_id=KEY_ID, sign_digests=sign_digests)[0]
        self.signatures += 1
        return token

    def verify(self, token, expected, now):
        if not isinstance(token, str) or len(token) > 4096:
            raise Denied("invalid bounded token")
        try:
            claims = jwt.decode(
                token,
                self.public,
                algorithms=["ES256"],
                issuer=ISSUER,
                audience=expected["aud"],
                options={
                    "require": ["iss", "aud", "sub", "iat", "exp", "jti"],
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            if jwt.get_unverified_header(token) != {"alg": "ES256", "kid": KEY_ID}:
                raise Denied("untrusted header")
            # Exact canonical claims equality pins types, profile and the stored
            # commitment. Server time is injected for reproducible expiry tests.
            if (
                canonical(claims) != canonical(expected)
                or not expected["iat"] <= now < expected["exp"]
            ):
                raise Denied("wrong claims or expired book")
        except (jwt.PyJWTError, TypeError, ValueError) as exc:
            raise Denied("signature or claim policy failed") from exc
        self.verifications += 1


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
 buyer TEXT PRIMARY KEY, initial INTEGER NOT NULL, available INTEGER NOT NULL CHECK(available>=0),
 reserved INTEGER NOT NULL CHECK(reserved>=0), redeemed INTEGER NOT NULL CHECK(redeemed>=0),
 CHECK(initial=available+reserved+redeemed));
CREATE TABLE IF NOT EXISTS offers (
 publisher TEXT, resource TEXT, content_sha256 TEXT NOT NULL, terms_sha256 TEXT NOT NULL,
 units INTEGER NOT NULL, valid_until INTEGER NOT NULL, PRIMARY KEY(publisher,resource));
CREATE TABLE IF NOT EXISTS books (
 id TEXT PRIMARY KEY, buyer TEXT NOT NULL REFERENCES accounts(buyer), publisher TEXT NOT NULL,
 request_id TEXT NOT NULL, request_hash TEXT NOT NULL, payload TEXT NOT NULL, token TEXT NOT NULL,
 issued INTEGER NOT NULL, expires INTEGER NOT NULL, remaining INTEGER NOT NULL CHECK(remaining>=0),
 active INTEGER NOT NULL DEFAULT 0, closed INTEGER NOT NULL DEFAULT 0,
 UNIQUE(buyer,request_id));
CREATE TABLE IF NOT EXISTS items (
 book TEXT REFERENCES books(id), resource TEXT, content_sha256 TEXT NOT NULL,
 terms_sha256 TEXT NOT NULL, units INTEGER NOT NULL, PRIMARY KEY(book,resource));
CREATE TABLE IF NOT EXISTS redemptions (
 buyer TEXT, request_id TEXT, request_hash TEXT NOT NULL, book TEXT REFERENCES books(id),
 resource TEXT NOT NULL, publisher TEXT NOT NULL, units INTEGER NOT NULL,
 receipt TEXT NOT NULL, PRIMARY KEY(buyer,request_id), UNIQUE(book,resource));
CREATE TABLE IF NOT EXISTS publishers (id TEXT PRIMARY KEY, accrued INTEGER NOT NULL CHECK(accrued>=0));
CREATE TABLE IF NOT EXISTS revoked_keys (id TEXT PRIMARY KEY);
"""


class Clearing:
    """One connection per caller/thread; SQLite serializes spending transactions.

    Methods take authenticated identities, not claims decoded from untrusted
    requests. A returned receipt records committed access entitlement; it does
    not prove delivery, consumption or cash settlement.
    """

    def __init__(self, path, authority, *, clock=time.time):
        self.authority = authority
        self.clock = clock
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        if self.db.in_transaction:
            # Compose application steps under one durable commit. A nested
            # failure rolls back that step even if its caller catches it.
            self.db.execute("SAVEPOINT access_book_step")
            try:
                yield
                self.db.execute("RELEASE access_book_step")
            except BaseException:
                self.db.execute("ROLLBACK TO access_book_step")
                self.db.execute("RELEASE access_book_step")
                raise
            return
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()

    def now(self):
        return integer(int(self.clock()), 1)

    def seed_simulated_balance(self, buyer, units):
        """Fixture setup only. A production adapter needs settled, deduplicated funding."""
        identifier(buyer)
        integer(units, 1)
        self.db.execute("INSERT INTO accounts VALUES(?,?,?,0,0)", (buyer, units, units))

    def set_offer(self, offer):
        """Trusted publisher catalog, not a buyer-supplied price."""
        offer.validate()
        with self.transaction():
            self.db.execute(
                "INSERT OR REPLACE INTO offers VALUES(?,?,?,?,?,?)",
                tuple(asdict(offer).values()),
            )
            self.db.execute(
                "INSERT OR IGNORE INTO publishers VALUES(?,0)", (offer.publisher,)
            )

    def _key_ok(self):
        if self.db.execute(
            "SELECT 1 FROM revoked_keys WHERE id=?", (KEY_ID,)
        ).fetchone():
            raise Denied("issuer key revoked")

    def issue(self, *, buyer, publisher, resources, max_units, request_id, ttl=MAX_TTL):
        identifier(buyer)
        identifier(publisher)
        identifier(request_id)
        integer(max_units, 1)
        integer(ttl, 1, MAX_TTL)
        if (
            not isinstance(resources, (list, tuple))
            or not 1 <= len(resources) <= MAX_ITEMS
        ):
            raise Denied("invalid book size")
        resources = sorted(identifier(x) for x in resources)
        if len(set(resources)) != len(resources):
            raise Denied("duplicate resource")
        request_hash = fingerprint([buyer, publisher, resources, max_units, ttl])
        with self.transaction():
            self._key_ok()
            prior = self.db.execute(
                "SELECT * FROM books WHERE buyer=? AND request_id=?",
                (buyer, request_id),
            ).fetchone()
            if prior:
                if prior["request_hash"] != request_hash:
                    raise Denied("issuance retry conflict")
                return prior["id"], prior["token"]
            now = self.now()
            offers = []
            for resource in resources:
                row = self.db.execute(
                    "SELECT * FROM offers WHERE publisher=? AND resource=?",
                    (publisher, resource),
                ).fetchone()
                if not row or row["valid_until"] <= now:
                    raise Denied("missing or expired authoritative offer")
                offers.append(dict(row))
            total = sum(x["units"] for x in offers)
            if total > max_units:
                raise Denied("buyer budget exceeded")
            changed = self.db.execute(
                "UPDATE accounts SET available=available-?,reserved=reserved+? WHERE buyer=? AND available>=?",
                (total, total, buyer, total),
            ).rowcount
            if changed != 1:
                raise Denied("insufficient prepaid balance")
            book_id = secrets.token_hex(16)
            expires = min(now + ttl, *(x["valid_until"] for x in offers))
            claims = {
                "iss": ISSUER,
                "aud": publisher,
                "sub": buyer,
                "iat": now,
                "exp": expires,
                "jti": book_id,
                "profile": PROFILE,
                "scope": "content:read",
                "manifest_sha256": fingerprint(offers),
                "count": len(offers),
                "reserved_micro_usd": total,
            }
            payload = canonical(claims).decode("ascii")
            token = self.authority.sign(payload.encode("ascii"))
            self.db.execute(
                "INSERT INTO books(id,buyer,publisher,request_id,request_hash,payload,token,issued,expires,remaining) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    book_id,
                    buyer,
                    publisher,
                    request_id,
                    request_hash,
                    payload,
                    token,
                    now,
                    expires,
                    total,
                ),
            )
            self.db.executemany(
                "INSERT INTO items VALUES(?,?,?,?,?)",
                [
                    (
                        book_id,
                        x["resource"],
                        x["content_sha256"],
                        x["terms_sha256"],
                        x["units"],
                    )
                    for x in offers
                ],
            )
            return book_id, token

    def activate(self, book_id, token, *, buyer, publisher):
        """Verify once, persist admission. Handle alone never authenticates a caller."""
        for x in (book_id, buyer, publisher):
            identifier(x)
        if not isinstance(token, str) or len(token) > 4096:
            raise Denied("invalid bounded token")
        with self.transaction():
            self._key_ok()
            row = self.db.execute(
                "SELECT * FROM books WHERE id=? AND buyer=? AND publisher=?",
                (book_id, buyer, publisher),
            ).fetchone()
            if (
                not row
                or row["closed"]
                or not row["issued"] <= self.now() < row["expires"]
            ):
                raise Denied("book unavailable")
            if token != row["token"]:
                raise Denied("wrong immutable token")
            if not row["active"]:
                self.authority.verify(token, json.loads(row["payload"]), self.now())
                self.db.execute("UPDATE books SET active=1 WHERE id=?", (book_id,))
        return book_id

    def redeem(
        self,
        book_id,
        resource,
        *,
        buyer,
        publisher,
        content_sha256,
        terms_sha256,
        request_id,
    ):
        for x in (book_id, resource, buyer, publisher, request_id):
            identifier(x)
        sha256(content_sha256)
        sha256(terms_sha256)
        request_hash = fingerprint(
            [book_id, resource, buyer, publisher, content_sha256, terms_sha256]
        )
        with self.transaction():
            prior = self.db.execute(
                "SELECT * FROM redemptions WHERE buyer=? AND request_id=?",
                (buyer, request_id),
            ).fetchone()
            if prior:
                if prior["request_hash"] != request_hash:
                    raise Denied("redemption retry conflict")
                # Returning an old receipt is recovery, not a new authorization.
                return json.loads(prior["receipt"])
            self._key_ok()
            row = self.db.execute(
                "SELECT * FROM books WHERE id=? AND buyer=? AND publisher=?",
                (book_id, buyer, publisher),
            ).fetchone()
            now = self.now()
            if (
                not row
                or not row["active"]
                or row["closed"]
                or not row["issued"] <= now < row["expires"]
            ):
                raise Denied("book unavailable")
            item = self.db.execute(
                "SELECT * FROM items WHERE book=? AND resource=?", (book_id, resource)
            ).fetchone()
            if (
                not item
                or item["content_sha256"] != content_sha256
                or item["terms_sha256"] != terms_sha256
            ):
                raise Denied("resource or terms mismatch")
            if self.db.execute(
                "SELECT 1 FROM redemptions WHERE book=? AND resource=?",
                (book_id, resource),
            ).fetchone():
                raise Denied("resource already redeemed")
            units = item["units"]
            receipt = {
                "receipt_id": secrets.token_hex(16),
                "book": book_id,
                "resource": resource,
                "buyer": buyer,
                "publisher": publisher,
                "content_sha256": content_sha256,
                "terms_sha256": terms_sha256,
                "units": units,
                "committed_at": now,
            }
            self.db.execute(
                "UPDATE accounts SET reserved=reserved-?,redeemed=redeemed+? WHERE buyer=?",
                (units, units, buyer),
            )
            self.db.execute(
                "UPDATE books SET remaining=remaining-? WHERE id=?", (units, book_id)
            )
            self.db.execute(
                "UPDATE publishers SET accrued=accrued+? WHERE id=?", (units, publisher)
            )
            self.db.execute(
                "INSERT INTO redemptions VALUES(?,?,?,?,?,?,?,?)",
                (
                    buyer,
                    request_id,
                    request_hash,
                    book_id,
                    resource,
                    publisher,
                    units,
                    canonical(receipt).decode("ascii"),
                ),
            )
            return receipt

    def release(self, book_id, *, buyer):
        """Buyer cancellation or trusted expiry worker: release only unused units."""
        identifier(book_id)
        identifier(buyer)
        with self.transaction():
            row = self.db.execute(
                "SELECT * FROM books WHERE id=? AND buyer=?", (book_id, buyer)
            ).fetchone()
            if not row:
                raise Denied("unknown book")
            if row["closed"]:
                return 0
            remaining = row["remaining"]
            self.db.execute(
                "UPDATE accounts SET reserved=reserved-?,available=available+? WHERE buyer=?",
                (remaining, remaining, buyer),
            )
            self.db.execute(
                "UPDATE books SET closed=1,remaining=0 WHERE id=?", (book_id,)
            )
            return remaining

    def revoke_key(self):
        """Trusted operator action; cached admission cannot bypass revocation."""
        self.db.execute("INSERT OR IGNORE INTO revoked_keys VALUES(?)", (KEY_ID,))

    def purchase(
        self,
        resource,
        *,
        buyer,
        publisher,
        content_sha256,
        terms_sha256,
        max_units,
        request_id,
    ):
        """Co-located, on-demand baseline: issue, verify and spend in one commit.

        Retains the same signature, budget, exact-scope and receipt checks. No
        intermediate reservation survives failure. Useful when an independent
        issuer/consumer round trip or future delegation is unnecessary.
        """
        with self.transaction():
            book, token = self.issue(
                buyer=buyer,
                publisher=publisher,
                resources=[resource],
                max_units=max_units,
                request_id=request_id,
            )
            # An expired committed purchase can recover its receipt without
            # new admission. Issuance retry policy still requires a live key;
            # direct redeem can recover historical receipts after revocation.
            prior = self.db.execute(
                "SELECT 1 FROM redemptions WHERE buyer=? AND request_id=?",
                (buyer, request_id),
            ).fetchone()
            if not prior:
                self.activate(book, token, buyer=buyer, publisher=publisher)
            receipt = self.redeem(
                book,
                resource,
                buyer=buyer,
                publisher=publisher,
                content_sha256=content_sha256,
                terms_sha256=terms_sha256,
                request_id=request_id,
            )
            return book, token, receipt

    def audit(self):
        """Consistent snapshot; conservation across balances, books and receipts."""
        with self.transaction():
            accounts = [
                dict(x)
                for x in self.db.execute("SELECT * FROM accounts ORDER BY buyer")
            ]
            for a in accounts:
                reserved = self.db.execute(
                    "SELECT COALESCE(SUM(remaining),0) FROM books WHERE buyer=?",
                    (a["buyer"],),
                ).fetchone()[0]
                redeemed = self.db.execute(
                    "SELECT COALESCE(SUM(units),0) FROM redemptions WHERE buyer=?",
                    (a["buyer"],),
                ).fetchone()[0]
                if (
                    a["initial"] != a["available"] + reserved + redeemed
                    or a["reserved"] != reserved
                    or a["redeemed"] != redeemed
                ):
                    raise RuntimeError("buyer conservation failed")
            publishers = [
                dict(x) for x in self.db.execute("SELECT * FROM publishers ORDER BY id")
            ]
            for p in publishers:
                expected = self.db.execute(
                    "SELECT COALESCE(SUM(units),0) FROM redemptions WHERE publisher=?",
                    (p["id"],),
                ).fetchone()[0]
                if p["accrued"] != expected:
                    raise RuntimeError("publisher conservation failed")
            return {
                "accounts": accounts,
                "publishers": publishers,
                "books": self.db.execute("SELECT COUNT(*) FROM books").fetchone()[0],
                "redemptions": self.db.execute(
                    "SELECT COUNT(*) FROM redemptions"
                ).fetchone()[0],
            }
