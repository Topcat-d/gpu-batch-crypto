# GPU Batch Crypto

A general-purpose Apache-2.0 GPU cryptography engine for batch hashing, authenticated encryption, and digital signatures. It provides a native C ABI, Python bindings, device runtimes, reusable buffers, key slots, and selectable P-256 fixed-base implementations.

**Technical preview, v0.2.** The library builds independently from its selected Smoke origins. Applications own their protocols and policies. Publishers, CDNs, storage systems and other infrastructure can build on the same engine; machine-authorized content is one reference application.

## Start with the code

| Component | Source | Responsibility |
|---|---|---|
| Cryptographic execution engine | [crypto_engine.cu](src/engine/crypto_engine.cu) | Validate and pack batches, dispatch CUDA work, return checked results |
| Device runtime and buffers | [runtime.hpp](src/engine/runtime.hpp) | Device selection, stream ownership, reused buffers, clearing, resident public tables |
| Native ABI implementation | [batchcrypto_abi.cpp](src/abi/batchcrypto_abi.cpp) | Opaque contexts, keys/epochs, status handling and C entry points |
| Public C ABI | [batchcrypto.h](include/batchcrypto.h) | Versioned interface for C, C++ and language bindings |
| CUDA kernels | [crypto_kernels.cuh](src/kernels/crypto_kernels.cuh) | AES-GCM, SHA-256, P-256 signing and public-key export |
| P-256 table-backed multiplication | [fixed_base.cuh](src/p256/fixed_base.cuh) | Reference, fixed-window comb and full-window execution |
| Public comb/full-window tables | [data/p256](data/p256) | Checked-in point data, typed layouts, metadata and SHA-256 fingerprints |
| Table generator and verifier | [generate_p256_tables.py](tools/generate_p256_tables.py) | Rebuild and independently check all 4,479 public points against OpenSSL |
| Python runtime | [batchcrypto](python/batchcrypto/__init__.py) | Thin bindings to the same C ABI |

The runtime is reusable across calls; the current execution model launches bounded CUDA batches. The historical persistent queue/scheduler is a different implementation and is not part of this native library. See [architecture](docs/ARCHITECTURE.md) and [P-256 tables and backends](docs/P256.md) for the exact boundary.

## Measurements

[Current P-256 results](docs/P256_RESULTS.md) · [Historical A100 and GPU benchmarks](docs/HISTORICAL_BENCHMARKS.md) · [Batch sizes and latency](docs/BATCHING.md) · [Engineering note](docs/ENGINEERING.md)

The public v0.2 full-window signer at batch **256** recorded **224,742–229,039 signatures/s at 1.12–1.14 ms** mean batch completion on RTX 4070 Ti, and **177,810–194,276/s at 1.32–1.44 ms** on RTX 3060. Ranges span two runs, each with seven timed calls. Full-window first beats the single-thread CPU baseline at sampled batch 64 on both cards; batches 1 and 8 favor CPU. These are synchronous Python API measurements with warmed buffers and tables, including copies and clearing.

Larger batches varied substantially between repeats. The [full comparison](docs/P256_RESULTS.md) publishes both runs, all three GPU backends, CPU baselines, latency and source/binary provenance. Batch 256 is a useful sampled starting point; there is no established universal optimum, request p99 or optimized multi-core CPU comparison.

The project also publishes the earlier engine evidence that motivated this extraction: A100 at **110,200 P-256 signatures/s** and **399,446 AES-GCM seals/s** on 16-byte plaintext; experimental full-window signing at **260,998/s on RTX 4070 Ti** and **120,150/s on RTX 3060**; and L40S throughput and measured p50/p95/p99 latency. Each historical capture identifies its execution path, settings, completion accounting and sampled correctness. Those implementations differ from the current public library.

The [initial v0.1 matrix](docs/RESULTS.md) is retained, including AES-GCM and SHA-256 results where CPU won every sampled cell. [The batching guide](docs/BATCHING.md) explains per-card observations, payload-dependent limits, and why batch wait time must be added to measured call time.

## Included

| Operation | CUDA | CPU/Python |
|---|---|---|
| AES-256-GCM seal/open, 96-bit nonce, 128-bit tag | Yes | cryptography/OpenSSL |
| Associated data and payloads up to 1 MiB | Yes | Yes |
| SHA-256 variable-length batch hashing | Yes | hashlib |
| P-256 ECDSA signing of SHA-256 digests | Reference, comb_w8 and full_window_w8; deterministic nonces and low-s | Yes |
| P-256 public-key export | Yes | Yes |
| P-256 verification and key generation | — | Yes |

P-256 names the curve; ECDSA is the signing algorithm used with it. AES-GCM protects content and authenticates associated metadata. ECDSA can authenticate a publisher's content manifest or an authorization receipt. Neither primitive implements billing, settles payments, or prevents copying by a recipient who has plaintext.

RSA is not required for this combination and is not included. An RSA signature would be an alternative for a protocol that requires it. This release does not implement TLS, WebAuthn, or a complete paid-access protocol.

## Build the native library

Requirements: CMake 3.24+, a compatible C++ compiler, NVIDIA CUDA toolkit, and a supported NVIDIA GPU/driver. The native build has no Python, PyTorch, Go, or OpenSSL dependency.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=89
cmake --build build --config Release
cmake --install build --config Release --prefix ./dist
```

Choose the architecture for your GPU (for example, 86 for RTX 3060 or 89 for RTX 4070 Ti). Windows output is `build/Release/batchcrypto.dll`; Linux output is `build/libbatchcrypto.so`. Use a CUDA version compatible with your compiler. The local Windows validation uses CUDA 13.0 and Visual Studio 2022.

Include [`batchcrypto.h`](include/batchcrypto.h) and link the library from C or C++. All public native functions accept **host memory**, execute synchronously, and report call-level plus per-item status. Decryption checks the authentication tag before writing plaintext; an invalid item returns `BC_AUTH_FAILED` with its output zeroed.

## Python quick start

For repeated work, use the owned runtime. Its stream, buffers and key slots persist across calls. Table-backed signing is explicitly selectable with the v0.2 native library:

```python
import os
from batchcrypto import Runtime, Record, generate_p256_key

with Runtime("build/Release/batchcrypto.dll", device=0, p256_backend="full_window_w8") as engine:
    epoch = engine.load_key(0, os.urandom(32), kind="aes")
    engine.load_key(1, generate_p256_key(), kind="p256")
    digest = engine.sha256([b"content"])[0]
    sealed = engine.seal(0, [Record(os.urandom(12), b"content", digest)])[0]
    signature = engine.sign(1, [digest])[0]
    public_key, signing_epoch = engine.public_key(1)
    next_epoch = engine.load_key(0, os.urandom(32), expected_epoch=epoch)
    print(engine.stats())
```

`reference` remains the default for existing callers. `comb_w8` and `full_window_w8` use the included public tables for both signing and public-key export. `engine.set_p256_backend(...)` changes the implementation without changing keys or epochs. The C equivalents are `bc_set_p256_backend` and `bc_get_p256_backend`; [`examples/c_api.c`](examples/c_api.c) exercises all three through the ABI.

AES nonces remain the caller's responsibility. Retiring a key makes its slot unusable and retains an epoch tombstone so a stale update cannot silently recreate it. Key replacement waits for that context's active batch to finish. Reports include the key epoch used.

```sh
python -m pip install .
```

This installs Python bindings and their CPU dependency. Build the CUDA library separately and pass its path explicitly:

```python
import hashlib
import os
from batchcrypto import Cuda, Record, generate_p256_key, public_key, verify_p256

crypto = Cuda("build/Release/batchcrypto.dll", device=0)
key = os.urandom(32)                  # fresh content key for this example
nonce = os.urandom(12)                # never reuse a nonce with the same key
aad = b"publisher=example.test;article=1;version=1"
ciphertext = crypto.seal(key, [Record(nonce, b"article content", aad)])[0]
plaintext = crypto.open(key, [Record(nonce, ciphertext, aad)])[0]
assert plaintext == b"article content"

signing_key = generate_p256_key()
digest = hashlib.sha256(b"publisher manifest").digest()
signature = crypto.sign(signing_key, [digest])[0]
assert verify_p256(public_key(signing_key), digest, signature)
```

Use `Cpu()` for the explicit CPU backend. `Cuda()` never silently falls back to CPU. Python `open()` returns `None` for an item whose authentication fails. Invalid shapes and native execution errors raise exceptions. Signatures are fixed-width big-endian `r || s`, not DER.

Run the [machine-authorized content example](examples/content_grant.py) and [signed batch records](examples/signed_batch_records.py):

```sh
python examples/content_grant.py --library build/Release/batchcrypto.dll
python examples/signed_batch_records.py --library build/Release/batchcrypto.dll
```

## Check correctness and benchmark

CPU reference tests:

```sh
python -m unittest discover -s tests -v
```

For actual CUDA tests, set `BC_LIBRARY` and optionally `BC_DEVICE`:

```powershell
$env:BC_LIBRARY = (Resolve-Path build/Release/batchcrypto.dll).Path
$env:BC_DEVICE = "0"
python -m unittest discover -s tests -v
```

Linux: `BC_LIBRARY="$PWD/build/libbatchcrypto.so" BC_DEVICE=0 python -m unittest discover -s tests -v`.

For the reproducible three-primitive runtime matrix, commit the source and run:

```sh
python benchmarks/run_matrix.py --library build/Release/batchcrypto.dll --build-dir build --device 0 --iterations 3 --output benchmarks/results/device0.json
```

The matrix also measures authenticated decryption. It records the source commit/hashes, compiler, CUDA toolkit, driver, GPU, CPU, full samples, accounting, and correctness. See [benchmark methodology](docs/BENCHMARKS.md).

Benchmark timings cover the synchronous library call, including packing, allocation, transfers, GPU execution and cleanup. Every measured result is compared with the CPU implementation outside the timed interval. Old Smoke throughput numbers are not performance claims for this new library.

## Limits and ownership

Maximum 4,096 items per call, 1 MiB plaintext per item, 64 KiB associated data per item, and 64 MiB aggregate input/output/AAD working data. One key is used per batch. Calls within a runtime serialize; independent runtimes have separate streams, buffers and keys, and can select different devices. There is no implicit GPU scheduler or automatic batch formation. The caller owns authorization, persistent key storage, rotation policy, and unique AES nonces across calls, processes and restarts; the library rejects duplicate nonces within a seal batch only.

Private keys are present in host and GPU memory. Cleanup attempts to overwrite library-owned buffers, but is not a secure-erasure or hardware-isolation guarantee. Python immutable objects cannot be reliably scrubbed. The inherited arithmetic includes secret-dependent control flow and memory access; no constant-time, side-channel resistance, FIPS validation, HSM equivalence, or independent security-audit claim is made. See [SECURITY.md](SECURITY.md).

## License and origin

[Apache-2.0](LICENSE). [`EXTRACTION.json`](EXTRACTION.json) records source paths and hashes for selected files; [`NOTICE`](NOTICE) preserves attribution. Modified extracts are identified in their headers. Only selected source code is carried over; public examples use synthetic content and generated test keys.

Read [architecture and the public/private boundary](docs/ARCHITECTURE.md), [machine-authorized content](docs/MACHINE_AUTHORIZED_CONTENT.md), and [security scope](SECURITY.md).
