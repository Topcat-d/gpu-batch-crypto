"""SPDX-License-Identifier: Apache-2.0. Run a complete local synthetic transaction."""

import json
import tempfile

from http_access.service import Fixture, rpc


def main():
    with tempfile.TemporaryDirectory(prefix="http-access-") as directory:
        with Fixture(directory) as app:
            book = app.issue([["r0", "r1"]])[0]
            # Simulate committed access whose HTTP delivery response is lost.
            app.drop_next("publisher", "/access")
            first = app.access("r0", "access-0", book)
            retry = app.access("r0", "access-0", book)
            if first != retry:
                raise RuntimeError("recovery changed entitlement")
            rpc(app.issuer_port, "/cancel", {"book": book["book"]}, app.buyer_secret)
            print(json.dumps({"simulation": True, "same_receipt_after_retry": True,
                              "audit": app.ledger.audit(), "http": app.counts}, indent=2))


if __name__ == "__main__":
    main()
