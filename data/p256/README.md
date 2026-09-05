# Public P-256 fixed-base tables

These are actual inputs to the native signing and public-key engine. They contain public multiples of the NIST P-256 generator G, with no keys, nonces or user data.

| Binary | Points | Bytes including header | Metadata | Fingerprint |
|---|---:|---:|---|---|
| [comb_w8.bin](comb_w8.bin) | 255 | 16,352 | [layout](comb_w8.json) | [SHA-256](comb_w8.sha256) |
| [full_window_w8.bin](full_window_w8.bin) | 4,224 | 270,368 | [layout](full_window_w8.json) | [SHA-256](full_window_w8.sha256) |

See [P-256 backends](../../docs/P256.md) for the typed header, point layout, multiplication methods, API selection and correctness evidence. The full-window data has 33 windows, including the final carry window.

From the repository root, `python tools/generate_p256_tables.py --check` independently regenerates and verifies all points against OpenSSL, then compares the checked-in files. CMake checks the binary fingerprints and embeds the constants in the native library. No runtime data-file lookup is required.

Apache-2.0. Generator and arithmetic provenance are recorded in [EXTRACTION.json](../../EXTRACTION.json) and [NOTICE](../../NOTICE).
