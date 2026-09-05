"""SPDX-License-Identifier: Apache-2.0. Run with pip install '.[interop]'."""

import json
from pathlib import Path
import tempfile
import time

from access_book.engine import Authority, Clearing, Offer


def main():
    with tempfile.TemporaryDirectory() as temp:
        store = Clearing(Path(temp) / "synthetic.sqlite", Authority())
        try:
            store.seed_simulated_balance("buyer", 1_000_000)
            for resource in ("article-1", "article-2"):
                store.set_offer(
                    Offer(
                        "publisher",
                        resource,
                        "a" * 64,
                        "b" * 64,
                        1000,
                        int(time.time()) + 300,
                    )
                )
            book, token = store.issue(
                buyer="buyer",
                publisher="publisher",
                resources=["article-1", "article-2"],
                max_units=2000,
                request_id="plan-1",
            )
            store.activate(book, token, buyer="buyer", publisher="publisher")
            args = dict(
                buyer="buyer",
                publisher="publisher",
                content_sha256="a" * 64,
                terms_sha256="b" * 64,
                request_id="access-1",
            )
            receipt = store.redeem(book, "article-1", **args)
            if store.redeem(book, "article-1", **args) != receipt:
                raise RuntimeError("retry did not recover the original receipt")
            released = store.release(book, buyer="buyer")
            print(
                json.dumps(
                    {
                        "simulated_funds_only": True,
                        "unused_units_released": released,
                        "audit": store.audit(),
                    },
                    indent=2,
                )
            )
        finally:
            store.close()


if __name__ == "__main__":
    main()
