"""SPDX-License-Identifier: Apache-2.0. Two loopback HTTP roles and synthetic buyer.

Python's development HTTP server is deliberately loopback-only. There is no
production transport, real identity provider, funding endpoint or settlement.
"""

from contextlib import AbstractContextManager
import hashlib
import hmac
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import threading
import time

from .ledger import Denied, Ledger, canonical, digest
from .signing import Consumer, Keys
from .timings import Timings

MAX_BODY = 1024 * 1024


class RemoteError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"HTTP {status}")


def rpc(port, path, payload, secret, *, attempts=3):
    """Bounded exact retries. The same request ID and serialized body are reused."""
    body = canonical(payload).encode()
    for attempt in range(attempts):
        conn = HTTPConnection("127.0.0.1", port, timeout=15)
        try:
            conn.request("POST", path, body, {"Authorization": "Bearer " + secret,
                         "Content-Type": "application/json", "Connection": "close"})
            response = conn.getresponse()
            raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise RuntimeError("oversized response")
            if response.status == 503 and attempt + 1 < attempts:
                continue
            if response.status != 200:
                raise RemoteError(response.status)
            return json.loads(raw)
        except (OSError, HTTPException):
            if attempt + 1 == attempts:
                raise
        finally:
            conn.close()
    raise RuntimeError("retry exhausted")


def fields(payload, required, optional=()):
    if not isinstance(payload, dict) or not set(required) <= payload.keys() or payload.keys() - set(required) - set(optional):
        raise Denied("unexpected request shape")


class Server(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 32


class Fixture(AbstractContextManager):
    """Own synthetic catalog, keys, two HTTP listeners and one durable ledger.

    The publisher has only a pinned public-key consumer and an authenticated
    clearing client. It does not access the database through its request path.
    Both listeners run in one process; this is not a distributed deployment.
    """

    def __init__(self, directory, *, mode="cpu", workers=4, library=None, device=0,
                 clock=time.time, balance=10**9, profile=False, ledger_pool_size=0):
        self.timings = Timings(profile)
        self.keys = Keys(mode, workers=workers, library=library, device=device)
        self.consumer = Consumer(self.keys.pins)
        self.data = {f"r{i}": (f"Synthetic licensed document {i}. " * 40) for i in range(32)}
        self.catalog = {r: {"content": digest(body), "terms": digest("local simulated terms v1"), "units": 1000}
                        for r, body in self.data.items()}
        self.ledger = Ledger(Path(directory) / "reference.sqlite", self.keys, self.catalog, clock=clock,
                             timings=self.timings, pool_size=ledger_pool_size)
        self.ledger.seed("buyer", balance)
        self.ledger.seed("other", balance)
        self.buyer_secret, self.other_secret, self.publisher_secret = [secrets.token_hex(32) for _ in range(3)]
        self.lock = threading.Lock()
        self.drops = set()
        self.errors = []
        self.counts = {"requests": 0, "request_body_bytes": 0, "response_body_bytes": 0, "dropped_responses": 0}
        self.servers, self.threads = [], []
        for role in ("issuer", "publisher"):
            server = Server(("127.0.0.1", 0), self.handler(role))
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            self.servers.append(server)
            self.threads.append(thread)
            thread.start()
        self.issuer_port, self.publisher_port = [s.server_port for s in self.servers]

    def handler(self, role):
        app = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.connection.settimeout(15)

            def log_message(self, *args):
                pass

            def do_POST(self):
                status, result = 200, None
                try:
                    auths = self.headers.get_all("Authorization", [])
                    if len(auths) != 1:
                        raise RemoteError(401)
                    auth = auths[0]
                    identity = None
                    for name, secret in (("buyer", app.buyer_secret), ("other", app.other_secret), ("publisher", app.publisher_secret)):
                        if hmac.compare_digest(auth.encode(), ("Bearer " + secret).encode()):
                            identity = name
                    if identity is None:
                        raise RemoteError(401)
                    lengths = self.headers.get_all("Content-Length", [])
                    if len(lengths) != 1 or self.headers.get("Transfer-Encoding") is not None:
                        raise Denied("invalid framing")
                    length = int(lengths[0])
                    if not 0 < length <= MAX_BODY or self.headers.get("Content-Type") != "application/json":
                        raise Denied("invalid body")
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise Denied("incomplete body")
                    payload = json.loads(raw)
                    with app.lock:
                        app.counts["requests"] += 1
                        app.counts["request_body_bytes"] += length
                    result = app.dispatch(role, self.path, identity, payload)
                    with app.lock:
                        drop = (role, self.path) in app.drops
                        if drop:
                            app.drops.remove((role, self.path))
                            app.counts["dropped_responses"] += 1
                    if drop:
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        return
                except RemoteError as exc:
                    status = exc.status
                except (Denied, ValueError, TypeError, KeyError):
                    status = 400
                except Exception as exc:
                    status = 503
                    with app.lock:
                        app.errors.append(type(exc).__name__)
                body = canonical(result if status == 200 else {"error": "request denied"}).encode()
                with app.lock:
                    app.counts["response_body_bytes"] += len(body)
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                except (OSError, HTTPException):
                    pass
                self.close_connection = True

        return Handler

    def dispatch(self, role, path, identity, payload):
        if role == "issuer":
            if path == "/issue" and identity in ("buyer", "other"):
                fields(payload, ("request_id", "books", "max_units"), ("ttl",))
                return self.ledger.issue(identity, **payload)
            if path == "/cancel" and identity in ("buyer", "other"):
                fields(payload, ("book",))
                return self.ledger.cancel(identity, payload["book"])
            if path == "/cancel-many" and identity in ("buyer", "other"):
                fields(payload, ("request_id", "books"))
                return self.ledger.cancel_many(identity, **payload)
            if path == "/spend" and identity == "publisher":
                fields(payload, ("buyer", "request_id", "resource", "content", "terms", "max_units"), ("book", "token"))
                return self.ledger.spend(**payload)
        elif path == "/access" and identity in ("buyer", "other"):
            fields(payload, ("request_id", "resource", "content", "terms", "max_units"), ("book", "token"))
            if ("book" in payload) != ("token" in payload):
                raise Denied("incomplete credential")
            if "book" in payload:
                with self.timings.phase("publisher.verify"):
                    self.consumer.verify(payload["token"], buyer=identity, book=payload["book"])
            with self.timings.phase("publisher.spend_rpc"):
                receipt = rpc(self.issuer_port, "/spend", {**payload, "buyer": identity}, self.publisher_secret)
            body = self.data[receipt["resource"]]
            if digest(body) != receipt["content"]:
                raise RuntimeError("entitled content version unavailable")
            return {"receipt": receipt, "body": body}
        raise RemoteError(403)

    def issue(self, books, *, request_id="issue", ttl=60):
        return rpc(self.issuer_port, "/issue", {"request_id": request_id, "books": books,
                   "max_units": sum(len(b) for b in books) * 1000, "ttl": ttl}, self.buyer_secret)

    def access_payload(self, resource, request_id, book=None):
        payload = {"resource": resource, "request_id": request_id,
                   "content": self.catalog[resource]["content"], "terms": self.catalog[resource]["terms"], "max_units": 1000}
        if book:
            payload.update({"book": book["book"], "token": book["token"]})
        return payload

    def access(self, resource, request_id, book=None):
        payload = self.access_payload(resource, request_id, book)
        with self.timings.phase("buyer.access_rpc"):
            result = rpc(self.publisher_port, "/access", payload, self.buyer_secret)
        if hashlib.sha256(result["body"].encode()).hexdigest() != payload["content"]:
            raise RuntimeError("buyer content check failed")
        receipt = result["receipt"]
        expected = {"buyer": "buyer", "publisher": "publisher", "book": book["book"] if book else None,
                    "resource": resource, "content": payload["content"], "terms": payload["terms"], "units": 1000}
        if any(receipt.get(k) != v for k, v in expected.items()):
            raise RuntimeError("buyer receipt check failed")
        return result

    def drop_next(self, role, path):
        with self.lock:
            self.drops.add((role, path))

    def cancel_books(self, books, *, request_id):
        return rpc(self.issuer_port, "/cancel-many", {"request_id": request_id,
                   "books": [book["book"] for book in books]}, self.buyer_secret)

    def __exit__(self, *args):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join()
        self.ledger.close()
        self.keys.close()
