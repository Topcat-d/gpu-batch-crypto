"""SPDX-License-Identifier: Apache-2.0. Predeclared durable access comparison."""

import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time

import cryptography
from cryptography.hazmat.backends.openssl.backend import backend
import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
from access_book.engine import Authority, Clearing, Offer  # noqa: E402

SOURCES = [
    "examples/access_book/engine.py",
    "python/batchcrypto/jws.py",
    "python/batchcrypto/__init__.py",
    "benchmarks/run_access_book.py",
    "benchmarks/ACCESS_BOOK_CAMPAIGN.md",
    "benchmarks/ACCESS_BOOK_ATOMIC_CONTROL.md",
]
PLANNED = 2048


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def measure(book_size, consumed_percent, planned=PLANNED, *, fused=False):
    with tempfile.TemporaryDirectory(prefix="access-book-") as temp:
        authority = Authority()
        store = Clearing(Path(temp) / "ledger.sqlite", authority)
        try:
            store.seed_simulated_balance("buyer", planned * 1000)
            for i in range(256):
                store.set_offer(
                    Offer(
                        "publisher",
                        f"resource-{i}",
                        "a" * 64,
                        "b" * 64,
                        1000,
                        int(time.time()) + 3600,
                    )
                )
            completion_ms, redemption_ms, first_ms = [], [], []
            tokens_bytes = 0
            transactions = 0
            issued = 0

            def trace(sql):
                nonlocal transactions
                if sql == "BEGIN IMMEDIATE":
                    transactions += 1

            store.db.set_trace_callback(trace)
            start_cpu, start = time.process_time(), time.perf_counter()
            group_size = book_size or 1
            for offset in range(0, planned, group_size):
                group = list(range(offset, offset + group_size))
                consumed = [i for i in group if consumed_percent == 100 or i % 4 == 0]
                if book_size in (0, 1) and not consumed:
                    continue
                ready = time.perf_counter()
                if book_size == 1:
                    _, token, _ = store.purchase(
                        f"resource-{offset % 256}",
                        buyer="buyer",
                        publisher="publisher",
                        content_sha256="a" * 64,
                        terms_sha256="b" * 64,
                        max_units=1000,
                        request_id=f"purchase-{offset}",
                    )
                    elapsed_ms = (time.perf_counter() - ready) * 1000
                    completion_ms.append(elapsed_ms)
                    redemption_ms.append(elapsed_ms)
                    first_ms.append(elapsed_ms)
                    issued += 1
                    tokens_bytes += len(token)
                    continue
                with store.transaction() if fused else nullcontext():
                    book, token = store.issue(
                        buyer="buyer",
                        publisher="publisher",
                        resources=[f"resource-{i % 256}" for i in group],
                        max_units=len(group) * 1000,
                        request_id=f"issue-{offset}",
                    )
                    store.activate(book, token, buyer="buyer", publisher="publisher")
                issued += 1
                tokens_bytes += len(token)
                for index, i in enumerate(consumed):
                    redemption_start = time.perf_counter()
                    store.redeem(
                        book,
                        f"resource-{i % 256}",
                        buyer="buyer",
                        publisher="publisher",
                        content_sha256="a" * 64,
                        terms_sha256="b" * 64,
                        request_id=f"redeem-{i}",
                    )
                    end = time.perf_counter()
                    completion_ms.append((end - ready) * 1000)
                    redemption_ms.append((end - redemption_start) * 1000)
                    if index == 0:
                        first_ms.append((end - ready) * 1000)
                if len(consumed) != len(group):
                    store.release(book, buyer="buyer")
            elapsed = time.perf_counter() - start
            cpu_seconds = time.process_time() - start_cpu
            store.db.set_trace_callback(None)
            audit = store.audit()
            return {
                "book_size": book_size,
                "fused": fused,
                "consumed_percent": consumed_percent,
                "planned": planned,
                "completed": len(completion_ms),
                "elapsed_seconds": elapsed,
                "process_cpu_seconds": cpu_seconds,
                "issued": issued,
                "signatures": authority.signatures,
                "verifications": authority.verifications,
                "transactions": transactions,
                "token_bytes": tokens_bytes,
                "completion_ms": completion_ms,
                "redemption_ms": redemption_ms,
                "first_access_ms": first_ms,
                "audit": audit,
            }
        finally:
            store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--campaign", choices=("books", "atomic-control"), default="books"
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve captures; output already exists")
    if git("status", "--porcelain", "--untracked-files=normal"):
        parser.error("commit the experiment before measurement")
    result = {
        "schema": 1,
        "campaign": args.campaign,
        "commit": git("rev-parse", "HEAD"),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {
            p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES
        },
        "environment": {
            "platform": platform.platform(),
            "cpu": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "python": platform.python_version(),
            "cryptography": cryptography.__version__,
            "pyjwt": jwt.__version__,
            "openssl": backend.openssl_version_text(),
            "sqlite": sqlite3.sqlite_version,
            "journal": "WAL",
            "synchronous": "FULL",
            "conditions": "shared local host; one process/thread; local temporary storage",
        },
        "complete": False,
        "rows": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    matrix = [(size, used) for used in (100, 25) for size in (0, 8, 32, 128, 256)]
    if args.campaign == "atomic-control":
        matrix = [(size, used) for used in (100, 25) for size in (1, 32)]
    save()
    try:
        for repeat in (1, 2):
            for size, used in matrix if repeat == 1 else reversed(matrix):
                fused = args.campaign == "atomic-control"
                measure(size, used, 256, fused=fused)  # Separate warmup.
                row = measure(size, used, fused=fused)
                row["repeat"] = repeat
                result["rows"].append(row)
                save()
                print(
                    f"repeat={repeat} book={size or 'on-demand'} used={used}% completed={row['completed']} rate={row['completed'] / row['elapsed_seconds']:.1f}/s",
                    flush=True,
                )
        result["complete"] = True
    except BaseException as exc:
        result["failure"] = type(exc).__name__
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
