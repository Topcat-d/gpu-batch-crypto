# GPU Batch Crypto

An independent Apache-2.0 GPU cryptography engine for batch content hashing, authenticated encryption, and digital signatures. Extracted CUDA primitives have a versioned C ABI, thin Python bindings, device runtimes, reusable buffers, and generic key slots.

**Technical preview.** This is a new source repository, not a public copy of Smoke. It has no Smoke runtime dependency, submodule, daemon, account system, or inherited Git history.

## Included

| Operation | CUDA | CPU/Python |
|---|---|---|
| AES-256-GCM seal/open, 96-bit nonce, 128-bit tag | Yes | cryptography/OpenSSL |
| Associated data and payloads up to 1 MiB | Yes | Yes |
| SHA-256 variable-length batch hashing | Yes | hashlib |
| P-256 ECDSA signing of SHA-256 digests | Yes, deterministic nonces and low-s output | Yes |
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

For repeated work, use the owned runtime. Its stream, buffers and key slots persist across calls:

```python
import os
from batchcrypto import Runtime, Record, generate_p256_key

with Runtime("build/Release/batchcrypto.dll", device=0) as engine:
    epoch = engine.load_key(0, os.urandom(32), kind="aes")
    engine.load_key(1, generate_p256_key(), kind="p256")
    digest = engine.sha256([b"content"])[0]
    sealed = engine.seal(0, [Record(os.urandom(12), b"content", digest)])[0]
    signature = engine.sign(1, [digest])[0]
    public_key, signing_epoch = engine.public_key(1)
    next_epoch = engine.load_key(0, os.urandom(32), expected_epoch=epoch)
    print(engine.stats())
```

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
