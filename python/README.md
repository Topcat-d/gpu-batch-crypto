# GPU Batch Crypto — Python package

An Apache-2.0 technical preview with CPU cryptography, explicit bindings to a
separately built CUDA library, and ES256 message construction. Adopt the Python
core without a publisher application or GPU. The experimental
`batchcrypto.receipts` module adds signed batch roots and offline record
inclusion verification with the same base dependencies. See the
[receipt quick start](https://github.com/Topcat-d/gpu-batch-crypto/blob/main/docs/RECORD_RECEIPTS.md).

## Install and use CPU only

Requires Python 3.10+ and `cryptography>=46,<51`. Install from a checkout or a
locally built wheel/source distribution; these instructions do not assume a
PyPI release.

```sh
python -m pip install .
```

```python
from batchcrypto import Cpu, generate_p256_key, public_key, verify_p256

cpu = Cpu()
digest = cpu.sha256([b"example record"])[0]
key = generate_p256_key()  # Fresh synthetic key for this example.
signature = cpu.sign(key, [digest])[0]
assert verify_p256(public_key(key), digest, signature)
```

The core also exposes AES-GCM and `batchcrypto.jws.sign_es256`. The application
owns keys, durable AES nonce uniqueness, authorization, claim validation,
retries and accounting. Installing the optional `interop` extra adds PyJWT for
the independently verifying examples; ES256 construction itself does not need it.

## Add GPU operations

Build the native v0.3 SDK from the full source repository and give its explicit
library path to `Runtime`, `Cuda` or `batchcrypto.verified.VerifiedSigner`.
The guarded signer verifies every signature on CPU before returning it. Loading
the Python package or using CPU operations does not load CUDA. There is no
automatic CPU fallback.

The wheel and Python source distribution contain the Python core, packaging
metadata and notices. They do not contain the native SDK, CUDA sources, public
table files, example applications, tests or benchmark captures. Get those from
the [full source repository](https://github.com/Topcat-d/gpu-batch-crypto).

[Quick starts](https://github.com/Topcat-d/gpu-batch-crypto/blob/main/docs/GETTING_STARTED.md)
and [component contracts](https://github.com/Topcat-d/gpu-batch-crypto/blob/main/docs/COMPONENTS.md)
describe each interface, dependency, failure behavior and its evidence.

## Maturity and security

This is a public preview, with no production certification or support SLA.
GPU arithmetic and table access depend on secrets. Host/device key isolation,
constant-time execution and secure erasure are not established; output
verification does not provide those properties. Read the
[security scope and private reporting route](https://github.com/Topcat-d/gpu-batch-crypto/blob/main/SECURITY.md)
before evaluating it. [Release instructions](https://github.com/Topcat-d/gpu-batch-crypto/blob/main/docs/RELEASING.md)
explain artifact checks, version pinning and update/rollback responsibilities.
