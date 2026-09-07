# Choose a component and run it

You can use one capability without adopting the publisher application. The
[component contracts](COMPONENTS.md) map dependencies, interfaces, failure
behavior, ownership, evidence and maturity. All commands below start in this
repository's root unless stated otherwise. Install from this checkout; these
instructions do not assume a package has been published to PyPI.

| I want to… | Start here | Needs a GPU? |
|---|---|---|
| Hash, encrypt or sign on CPU | [Use CPU only](#use-cpu-only) | No |
| Add independently checked GPU signatures | [Add GPU signing](#add-gpu-signing) | Yes |
| Produce standard ES256 tokens | [Generate ES256 tokens](#generate-es256-tokens) | Optional |
| Try budgeted content permissions and accounting | [Evaluate access books](#evaluate-access-books) | No |
| Consume the native engine from C/C++ | [Use the installed C ABI](#use-the-installed-c-abi) | Yes at runtime |
| Reuse public tables or calculate economics | [Use data and analysis tools](#use-data-and-analysis-tools) | No |

## Use CPU only

**Install:** Python 3.10+ and the package's `cryptography>=46,<51` dependency.
There is no native library build, CUDA, PyJWT or database requirement.

```sh
python -m pip install .
python examples/cpu_only.py
```

Expected: `PASS: CPU SHA-256, AES-GCM with tag rejection, and P-256 signing/verification`.
The [complete example](../examples/cpu_only.py) uses fresh synthetic keys and
checks every result. For just hashing:

```python
from batchcrypto import Cpu
digests = Cpu().sha256([b"record one", b"record two"])
```

`Cpu`, `Record`, `generate_p256_key`, `public_key` and `verify_p256` are the
public entry points. The application owns persistent keys, AES nonce uniqueness,
authorization and the meaning of a signed record. The package wheel contains
`batchcrypto` Python modules; the example files stay in the source checkout.

## Add GPU signing

**Install:** the base Python package above, plus a separately built native v0.3
library and an NVIDIA GPU/compatible driver. Building that library needs CMake
3.24+, a compatible C++ compiler and CUDA toolkit. The native engine itself has
no Python or OpenSSL dependency.

For an RTX 3060 (architecture 86), from the repository root:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=86
cmake --build build --config Release
```

Choose the architecture and toolchain for your hardware. The documented local
toolchain is CUDA 13.0 / Visual Studio 2022 on Windows; architecture 89 is used
for RTX 4070 Ti. See the [validation boundaries](VALIDATION.md) for what was run.

Windows:

```powershell
python examples/gpu_signing.py --library build/Release/batchcrypto.dll --device 0 --count 256
```

Linux, with a compatible CUDA build and runtime loader configuration:

```sh
python examples/gpu_signing.py --library build/libbatchcrypto.so --device 0 --count 256
```

Expected: `PASS: 256 GPU P-256 signatures independently verified; key retired`.
Use the ordinal of the device you intend to evaluate; the local two-card test
host uses ordinal 1 for its RTX 3060. No automatic CPU fallback occurs.

The [complete example](../examples/gpu_signing.py) owns a `VerifiedSigner`, loads
a fresh synthetic key, passes its exact epoch on the sign call and retires it.
Every signature is independently verified before return. CUDA/backend faults
fail the operation; do not treat missing output as a successful authorization.
Key isolation and secret-dependent execution remain [preview limitations](PRODUCTION_READINESS.md).
The example is a correctness path, not a throughput benchmark.

## Generate ES256 tokens

**Install:** the Python core. The encoder itself does not require PyJWT; the
interoperability example installs PyJWT to verify the tokens independently.

```sh
python -m pip install '.[interop]'
python examples/jws_grant.py --count 8
```

Expected: eight CPU ES256 grants accepted by the pinned PyJWT consumer, with
synthetic permissions and no funding or redemption ledger. The smallest encoder
integration uses your own signing callback:

```python
from batchcrypto import Cpu, generate_p256_key
from batchcrypto.jws import sign_es256

key = generate_p256_key()  # Synthetic example; your issuer manages real keys.
cpu = Cpu()
tokens = sign_es256(
    [b'{"example":true}'],
    key_id="issuer-epoch-1",
    sign_digests=lambda digests: cpu.sign(key, digests),
)
```

This constructs a signed message; it does not authorize a request. The
[full interoperability example](../examples/jws_grant.py) adds issuer, audience,
expiry and content commitments and verifies them against a trusted key. The
consumer owns claim policy and replay protection. An existing Ed25519 or HTTP
signature profile requires its own protocol adapter; a JWS is not that adapter.

To use the guarded GPU callback after building the native library:

```powershell
python examples/jws_grant.py --library build/Release/batchcrypto.dll --device 0 --count 256
```

Use `build/libbatchcrypto.so` on Linux. [Compatibility evidence](COMPATIBILITY.md)
and the [verification-cost control](VERIFICATION_CONTROL_RESULTS.md) apply.

## Evaluate access books

**Install:** the Python core with the `interop` extra, and Python's standard
SQLite module. Keep `examples/access_book/` beside the demo, or copy that example
directory into your own evaluation workspace. It is deliberately outside the
installed library package.

```sh
python -m pip install '.[interop]'
python examples/access_book_demo.py
python -m unittest discover -s tests -p 'test_access_book.py' -v
```

Expected: the JSON audit shows `simulated_funds_only: true`, 1,000 units released,
one redemption, zero remaining reservation and 1,000 units of publisher accrual.
The demo creates and removes its own temporary local database.

Entry points are `Authority`, `Offer` and `Clearing` in the
[example engine](../examples/access_book/engine.py). `issue` reserves a book,
`activate` checks its signature, `redeem` commits one resource and `release`
returns unused reservations. `purchase` combines an immediate purchase into
one commit. The embedding application authenticates callers and controls the
catalog, time source, funding and payout adapters. [Design and limits](ACCESS_BOOK_DESIGN.md).

The [measured comparison](ACCESS_BOOK_RESULTS.md) includes an optimized atomic
CPU baseline. Its 17.3% full-use throughput improvement is specific to a local
workload and has a first-access latency tradeoff; it is not a GPU result.

## Use the installed C ABI

**Producer:** build the native library as above, then install its SDK:

```sh
cmake --install build --config Release --prefix ./dist/native-sdk
```

The installed SDK contains the shared library, public header, Windows import
library where applicable, `batchcrypto::batchcrypto` CMake target, license
notices and security scope. The
producer build requires CUDA; a C-only consumer can use that SDK without
enabling the CUDA language or importing the repository's private source headers.
The consumer still needs the compatible GPU, driver, CUDA runtime and platform
runtime libraries when executing.

Copy [examples/native_consumer](../examples/native_consumer) into your own
project, or configure it directly to try the installed package:

```sh
cmake -S examples/native_consumer -B build-consumer -DCMAKE_PREFIX_PATH=/absolute/path/to/native-sdk -DBC_CONSUMER_DEVICE=0
cmake --build build-consumer --config Release
ctest --test-dir build-consumer -C Release --output-on-failure
```

Replace the SDK path with an absolute path; quote paths containing spaces.
The Windows sample copies the SDK DLL next to its executable. Other runtime
dependencies must be available to the OS loader. Linux can use its loader/RPATH
configuration or `LD_LIBRARY_PATH` for the required shared libraries.

Expected: `installed_consumer` passes a GPU SHA-256 known-answer check. Its
minimal [CMake project](../examples/native_consumer/CMakeLists.txt) uses only:

```cmake
find_package(batchcrypto 0.3 CONFIG REQUIRED)
target_link_libraries(your_target PRIVATE batchcrypto::batchcrypto)
```

Include `batchcrypto.h`. The native package exposes one combined library;
individual operation calls do not require adopting the Python or publisher
application. There are no per-algorithm native build packages. The header's
call-level/per-item error and buffer rules are the [native contract](COMPONENTS.md#native-gpu-engine-and-c-abi).

## Use data and analysis tools

The [P-256 data directory](../data/p256) contains the two public table binaries,
their layout metadata and fingerprints. It is outside the Python wheel; copy
the matching data and metadata together if your implementation consumes them.
Point representation and the final carry window matter. The generator requires
`cryptography` and its bundled `tools/imported/p256_table_math.py` helper:

```sh
python tools/generate_p256_tables.py --check
```

The economic calculators use only the Python standard library. They can be
copied as individual files and run without installing this package:

```sh
python benchmarks/economics.py --scope primitive --hourly 1 --rate 100000
python benchmarks/access_business_model.py --rate 528.917110
```

The first command is hypothetical unit arithmetic; the second evaluates
editable assumptions using a measured local rate. Neither accesses accounts,
rents GPUs or transfers money. [Cost boundaries](ECONOMICS.md).

## Run an HTTP access transaction

The separate loopback reference connects a synthetic buyer, issuer and
publisher, including a lost delivery response and recovery of the same receipt:

```sh
python -m pip install '.[interop]'
python examples/http_access_demo.py
```

It requires no GPU, external account or real funds. The [HTTP reference](HTTP_REFERENCE.md)
defines endpoints, key/accounting ownership, limits and optional GPU use. The
[measured campaign](HTTP_RESULTS.md) compares direct CPU purchases, CPU books
and guarded GPU books with complete delivery and cleanup costs.

## Verify your chosen integration

CPU tests run by default; GPU checks require `BC_LIBRARY` and `BC_DEVICE` as
documented in the [README](../README.md#check-correctness-and-benchmark).
The [component catalog](COMPONENTS.md) maps each capability to its tests and
appropriate measurements. Archive verifiers require the referenced Git history;
use a full Git clone for provenance verification. A source ZIP can run examples
and builds but does not contain that history.

For a wheel consumer, build and install without installing the example app:

```sh
python -m pip install build
python -m build --outdir dist/release-python
python tools/check_distributions.py --python-dist dist/release-python
```

This builds the Python source distribution and then its wheel. The Python
source distribution is distinct from the full native source ZIP. See
[release and rollback instructions](RELEASING.md) for artifact scope and evidence.
Install the resulting `.whl` into your application's Python environment. Run
[check_python_install.py](../tools/check_python_install.py) with that environment
and `python -I` before adding PyJWT to verify CPU/JWS construction independently
of CUDA and the source checkout. CI exercises this path in isolated environments.
