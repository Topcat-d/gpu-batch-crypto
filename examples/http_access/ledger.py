"""SPDX-License-Identifier: Apache-2.0. Authoritative online simulation ledger.

No real funding or settlement. A committed receipt buys a recoverable content
entitlement, not evidence that a client received or read bytes.
"""

from contextlib import contextmanager
import hashlib
import json
import re
import secrets
import sqlite3
import time


class Denied(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,96}", value):
        raise Denied("invalid identifier")
    return value


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise Denied("invalid integer")
    return value


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts(
 buyer TEXT PRIMARY KEY, initial INTEGER NOT NULL, available INTEGER NOT NULL,
 reserved INTEGER NOT NULL, spent INTEGER NOT NULL,
 CHECK(initial=available+reserved+spent), CHECK(available>=0 AND reserved>=0 AND spent>=0));
CREATE TABLE IF NOT EXISTS books(
 id TEXT PRIMARY KEY, buyer TEXT NOT NULL REFERENCES accounts(buyer), kid TEXT NOT NULL,
 token TEXT NOT NULL, issued INTEGER NOT NULL, expires INTEGER NOT NULL,
 remaining INTEGER NOT NULL CHECK(remaining>=0), closed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS items(
 book TEXT NOT NULL REFERENCES books(id), resource TEXT NOT NULL, content TEXT NOT NULL,
 terms TEXT NOT NULL, units INTEGER NOT NULL, PRIMARY KEY(book,resource));
CREATE TABLE IF NOT EXISTS issues(
 buyer TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
 response TEXT NOT NULL, PRIMARY KEY(buyer,request_id));
CREATE TABLE IF NOT EXISTS receipts(
 buyer TEXT NOT NULL REFERENCES accounts(buyer), request_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL, book TEXT, resource TEXT NOT NULL, units INTEGER NOT NULL,
 response TEXT NOT NULL, PRIMARY KEY(buyer,request_id), UNIQUE(book,resource));
CREATE TABLE IF NOT EXISTS revoked(kid TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS publisher(id TEXT PRIMARY KEY, accrued INTEGER NOT NULL CHECK(accrued>=0));
INSERT OR IGNORE INTO publisher VALUES('publisher',0);
"""


class Ledger:
    def __init__(self, path, keys, catalog, *, clock=time.time):
        self.path, self.keys, self.catalog, self.clock = str(path), keys, catalog, clock
        db = sqlite3.connect(self.path, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
        finally:
            db.close()

    @contextmanager
    def connection(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            if db.in_transaction:
                db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def seed(self, buyer, units):
        identifier(buyer)
        integer(units, 1, 10**12)
        with self.connection(write=True) as db:
            db.execute("INSERT INTO accounts VALUES(?,?,?,0,0)", (buyer, units, units))

    def offer(self, resource):
        identifier(resource)
        if resource not in self.catalog:
            raise Denied("unknown content")
        return self.catalog[resource]

    @staticmethod
    def prior(db, table, buyer, request_id, fingerprint):
        # table is only one of two internal literals, never HTTP input.
        row = db.execute(f"SELECT * FROM {table} WHERE buyer=? AND request_id=?",
                         (buyer, request_id)).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                raise Denied("retry conflict")
            return json.loads(row["response"])
        return None

    def issue(self, buyer, request_id, books, max_units, ttl=60):
        identifier(buyer)
        identifier(request_id)
        integer(max_units, 1, 10**12)
        integer(ttl, 1, 300)
        if not isinstance(books, list) or not 1 <= len(books) <= 256:
            raise Denied("invalid ready batch")
        manifests = []
        item_count = 0
        for group in books:
            if not isinstance(group, list) or not 1 <= len(group) <= 32:
                raise Denied("invalid book")
            item_count += len(group)
            if item_count > 2048:
                raise Denied("ready batch has too many manifest items")
            names = sorted(identifier(r) for r in group)
            if len(set(names)) != len(names):
                raise Denied("duplicate resource")
            manifests.append([{"resource": r, **self.offer(r)} for r in names])
        fp = digest(canonical([books, max_units, ttl]))
        with self.connection() as db:
            prior = self.prior(db, "issues", buyer, request_id, fp)
            if prior is not None:
                return prior
        total = sum(x["units"] for m in manifests for x in m)
        if total > max_units:
            raise Denied("budget exceeded")
        now = int(self.clock())
        ids = [secrets.token_hex(16) for _ in books]
        claims = [{"iss": "local-reference", "aud": "publisher", "sub": buyer,
                   "iat": now, "exp": now + ttl, "jti": bid, "scope": "content:read",
                   "profile": "local-http-v1", "manifest_sha256": digest(canonical(m))}
                  for bid, m in zip(ids, manifests)]
        # No database write lock is held while signing. Failed signatures reserve
        # nothing; commit rechecks key revocation, time and available funds.
        kid, tokens = self.keys.sign(claims)
        response = [{"book": bid, "token": token, "manifest": manifest}
                    for bid, token, manifest in zip(ids, tokens, manifests)]
        with self.connection(write=True) as db:
            prior = self.prior(db, "issues", buyer, request_id, fp)
            if prior is not None:
                return prior
            if not now <= int(self.clock()) < now + ttl:
                raise Denied("expired during preparation")
            if db.execute("SELECT 1 FROM revoked WHERE kid=?", (kid,)).fetchone():
                raise Denied("key revoked during preparation")
            if db.execute("UPDATE accounts SET available=available-?,reserved=reserved+? "
                          "WHERE buyer=? AND available>=?", (total, total, buyer, total)).rowcount != 1:
                raise Denied("insufficient simulated balance")
            for bid, token, manifest in zip(ids, tokens, manifests):
                units = sum(x["units"] for x in manifest)
                db.execute("INSERT INTO books VALUES(?,?,?,?,?,?,?,0)",
                           (bid, buyer, kid, token, now, now + ttl, units))
                db.executemany("INSERT INTO items VALUES(?,?,?,?,?)",
                               [(bid, x["resource"], x["content"], x["terms"], x["units"]) for x in manifest])
            db.execute("INSERT INTO issues VALUES(?,?,?,?)", (buyer, request_id, fp, canonical(response)))
        return response

    def spend(self, *, buyer, request_id, resource, content, terms, max_units,
              book=None, token=None):
        for value in (buyer, request_id, resource):
            identifier(value)
        integer(max_units, 1, 10**12)
        if book is not None:
            identifier(book)
        offer = self.offer(resource)
        if content != offer["content"] or terms != offer["terms"]:
            raise Denied("content or terms mismatch")
        fp = digest(canonical([book, resource, content, terms, max_units]))
        with self.connection(write=True) as db:
            # Exact receipt recovery remains valid after expiry/revocation. It
            # conveys the same immutable entitlement, never a fresh purchase.
            prior = self.prior(db, "receipts", buyer, request_id, fp)
            if prior is not None:
                return prior
            units = offer["units"]
            if units > max_units:
                raise Denied("budget exceeded")
            if book is not None:
                row = db.execute("SELECT * FROM books WHERE id=? AND buyer=?", (book, buyer)).fetchone()
                if not row or row["token"] != token or row["closed"]:
                    raise Denied("book unavailable")
                if not row["issued"] <= int(self.clock()) < row["expires"]:
                    raise Denied("book expired")
                if db.execute("SELECT 1 FROM revoked WHERE kid=?", (row["kid"],)).fetchone():
                    raise Denied("key revoked")
                item = db.execute("SELECT * FROM items WHERE book=? AND resource=?", (book, resource)).fetchone()
                if not item or (item["content"], item["terms"], item["units"]) != (content, terms, units):
                    raise Denied("wrong book scope")
                if db.execute("SELECT 1 FROM receipts WHERE book=? AND resource=?", (book, resource)).fetchone():
                    raise Denied("already redeemed")
                db.execute("UPDATE books SET remaining=remaining-? WHERE id=?", (units, book))
                db.execute("UPDATE accounts SET reserved=reserved-?,spent=spent+? WHERE buyer=?", (units, units, buyer))
            else:
                if db.execute("UPDATE accounts SET available=available-?,spent=spent+? "
                              "WHERE buyer=? AND available>=?", (units, units, buyer, units)).rowcount != 1:
                    raise Denied("insufficient simulated balance")
            receipt = {"id": secrets.token_hex(16), "buyer": buyer, "publisher": "publisher",
                       "book": book, "resource": resource, "content": content, "terms": terms,
                       "units": units, "committed_at": int(self.clock())}
            db.execute("INSERT INTO receipts VALUES(?,?,?,?,?,?,?)",
                       (buyer, request_id, fp, book, resource, units, canonical(receipt)))
            db.execute("UPDATE publisher SET accrued=accrued+? WHERE id='publisher'", (units,))
            return receipt

    def cancel(self, buyer, book):
        identifier(book)
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM books WHERE id=? AND buyer=?", (book, buyer)).fetchone()
            if not row:
                raise Denied("unknown book")
            units = row["remaining"]
            db.execute("UPDATE accounts SET reserved=reserved-?,available=available+? WHERE buyer=?", (units, units, buyer))
            db.execute("UPDATE books SET remaining=0,closed=1 WHERE id=?", (book,))
            return {"released": units}

    def revoke(self, kid):
        with self.connection(write=True) as db:
            db.execute("INSERT OR IGNORE INTO revoked VALUES(?)", (kid,))

    def audit(self):
        with self.connection() as db:
            accounts = [dict(r) for r in db.execute("SELECT * FROM accounts ORDER BY buyer")]
            count, spent = db.execute("SELECT COUNT(*),COALESCE(SUM(units),0) FROM receipts").fetchone()
            accrued = db.execute("SELECT accrued FROM publisher").fetchone()[0]
            for a in accounts:
                reserved = db.execute("SELECT COALESCE(SUM(remaining),0) FROM books WHERE buyer=?", (a["buyer"],)).fetchone()[0]
                redeemed = db.execute("SELECT COALESCE(SUM(units),0) FROM receipts WHERE buyer=?", (a["buyer"],)).fetchone()[0]
                if a["reserved"] != reserved or a["spent"] != redeemed or a["initial"] != a["available"] + reserved + redeemed:
                    raise RuntimeError("buyer conservation failed")
            if accrued != spent or sum(a["spent"] for a in accounts) != spent:
                raise RuntimeError("publisher conservation failed")
            return {"accounts": accounts, "receipts": count, "publisher_accrued": accrued,
                    "books": db.execute("SELECT COUNT(*) FROM books").fetchone()[0]}
