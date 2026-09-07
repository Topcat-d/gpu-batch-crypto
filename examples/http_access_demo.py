"""SPDX-License-Identifier: Apache-2.0. Run a complete local synthetic transaction."""

import json
import tempfile

from http_access.service import Fixture


def main():
    with tempfile.TemporaryDirectory(prefix="http-access-") as directory:
        with Fixture(directory) as app:
            books = app.issue([["r0", "r1"], ["r2", "r3"]])
            book = books[0]
            # Simulate committed access whose HTTP delivery response is lost.
            app.drop_next("publisher", "/access")
            first = app.access("r0", "access-0", book)
            retry = app.access("r0", "access-0", book)
            if first != retry:
                raise RuntimeError("recovery changed entitlement")
            app.access("r2", "access-2", books[1])
            app.drop_next("issuer", "/cancel-many")
            cleanup = app.cancel_books(books, request_id="cancel-unused")
            if app.cancel_books(books, request_id="cancel-unused") != cleanup:
                raise RuntimeError("cancellation recovery changed its result")
            print(json.dumps({"simulation": True, "same_receipt_after_retry": True,
                              "atomic_cleanup": cleanup,
                              "audit": app.ledger.audit(), "http": app.counts}, indent=2))


if __name__ == "__main__":
    main()
