# Building, verifying and updating a preview

This repository is a technical preview. The current evaluation target is the
v0.3 code line; there is no LTS branch, guaranteed response time, independent
cryptographic audit or production approval. A change on `main` is not an
immutable versioned release. Until publishing a numbered release, identify an
evaluation by its full Git commit and the SHA-256 of each artifact you use.

The release maintainer owns versioning, artifact checks, release evidence and
security triage. The integrator owns dependency selection, deployment approval,
keys/nonces, authorization, state recovery and rollback. See
[component contracts](COMPONENTS.md) and [security scope](../SECURITY.md).

## Choose the artifact

| Artifact | Contains | How it is checked |
|---|---|---|
| Full Git clone | Native/Python sources, public tables, examples, tests, docs, evidence and Git history | CPU CI, extraction/table checks, archive provenance checks; separate GPU acceptance |
| Git source ZIP | Tracked public files at one commit; no Git history | Build and run examples; use a full clone for historical provenance checks |
| Python `.tar.gz` source distribution | Python core, build metadata, package documentation and notices | Build a wheel from it, compare its scope/source bytes and install outside the checkout |
| Python `.whl` | `batchcrypto` modules and distribution/license metadata | No CUDA load or PyJWT in the base-install check; independent optional consumer checks |
| Installed native SDK | Shared library, C header, import library where applicable, CMake package, `LICENSE`, `NOTICE`, `SECURITY.md` | Artifact check and an external C-only consumer on the target GPU |

The Python source distribution is not the full native source archive. Examples
and tests depend on other repository files and are intentionally absent from
Python distributions. Package documentation links to their full source.

## Prepare a candidate

Use a clean checkout of the intended public commit. Review `git status --short`
and `git diff`; record `git rev-parse HEAD`. A release must not silently include
uncommitted edits or local native artifacts. Use new build/output directories
for each candidate so earlier wheels or DLLs cannot be mistaken for new ones.

For a numbered release, update `project.version` in `pyproject.toml` and the
project version in `CMakeLists.txt` together. Never replace different bytes
under an already published artifact/version. Record the source commit, release
changes, test results, toolchain, dependencies, target GPU architectures and
artifact hashes. A checksum establishes byte identity; it does not establish
publisher authenticity or prove a build is reproducible.

The native ABI remains version 1 across additive v0.1–v0.3 entry points.
`bc_abi_version() == 1` alone does not prove the v0.3 epoch-bound symbols exist.
Pair Python/native artifacts from the evaluated commit and exercise the guarded
signer against that actual library. Do not rely on a CMake version match alone
for API, security or behavior compatibility. No future 0.x Python API
compatibility promise is made.

Dependency bounds express intended compatibility, not a test of every allowed
version. CPU CI exercises Python 3.10 and 3.12 package adoption; the recorded
local GPU toolchain is Windows, CUDA 13.0 and MSVC 19.44. Hosted CI does not build
or execute CUDA. Record `python -m pip freeze` in the candidate evidence and
re-run affected acceptance checks when dependencies or toolchains change.

## Build and check Python artifacts

From the full checkout, with build tooling installed:

```sh
python -m pip install build
python -m build --outdir dist/release-python
python tools/check_distributions.py --python-dist dist/release-python
```

With neither `--wheel` nor `--sdist` selected, this builds the source
distribution and then builds the wheel from it. The artifact check requires
exactly one of each in its input directory; it compares the core source bytes,
version, license notices and expected file inventory against this checkout.
It prints their SHA-256 hashes. No application code or native binary belongs
in either Python artifact. The scope check intentionally fails if a future
package adds files outside the declared layout; review the boundary and update
the check as part of that change.

Create a fresh virtual environment outside the checkout, install that wheel,
and run `python -I /absolute/path/to/tools/check_python_install.py` before
installing PyJWT. Then run the CPU example, install the wheel's `interop` extra
and run the token/access-book examples with synthetic keys and funds.
The [CI package job](../.github/workflows/ci.yml) provides executable commands
for both supported test interpreters. It covers the source-to-wheel path and
actual consumer imports; archive inspection alone does not prove usability.

## Build and check a native SDK

From a CUDA-capable checkout, choose the architecture(s) for the target GPU.
This example targets RTX 3060:

```sh
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=86
cmake --build build-release --config Release
cmake --install build-release --config Release --prefix ./dist/release-sdk
python tools/check_distributions.py --sdk dist/release-sdk
```

The SDK checker expects the default GNUInstallDirs layout. The notices are in
`share/licenses/batchcrypto`; the security scope is in
`share/doc/batchcrypto`. Keep these files with SDK distributions. The check
confirms packaging and prints the library hash; GPU execution is a separate gate.
The SDK does not bundle the NVIDIA driver or other platform runtime installers.

Run the full GPU test suite with `BC_LIBRARY` pointing to this build and
`BC_DEVICE` set to the intended device. Run the minimal guarded signer and the
external [C-only SDK consumer](GETTING_STARTED.md#use-the-installed-c-abi).
Use synthetic keys. Record the selected GPU and toolchain; do not silently
substitute a busy device. A successful Windows build does not establish Linux
CUDA acceptance. An unsupported/unexecuted platform must remain labeled that way.

Publish the exact source commit and artifact hashes alongside the CI link and
GPU acceptance results. Keep historical benchmarks bound to their original
source/binary fingerprints; a new SDK has no inherited performance result merely
because the package version or GPU model matches.

## Updates, rollback and incident ownership

1. Pin the candidate commit, Python environment and native-library hash together.
   Keep the last accepted pair and its dependency record available in a separate
   deployment directory. Evaluate updates with synthetic workload fixtures first.
2. Before switching a service, stop admission, drain/join in-flight callers and
   destroy owned contexts. A native context must not be destroyed while other
   threads still use it. Start fresh processes/contexts with the selected pair.
3. Restore keys only through the application's key-management policy. Native
   slot epochs are process/context-local, not durable key identities. A restart
   or downgrade must never reset AES nonce allocation or make an old key/nonce
   pair eligible for reuse. Rebuild public-key pins and bind new work to newly
   loaded epochs; do not carry queued requests across incompatible contexts.
4. If acceptance fails, stop that rollout and restore the previous evaluated
   code/dependency pair. Keep durable nonce, revocation and accounting state
   current. Code rollback is not permission to rewind state, replay a payment
   or erase a completed redemption. Do not automatically downgrade across a
   security fix; the security owner must select an acceptable recovery version.
5. The access-book example has no production migration/backup manager. Do not
   upgrade a live ledger or restore an older database to undo application code.
   An operator adopting that example must design and test consistent backup,
   schema compatibility, recovery and reconciliation before actual funds.
6. On suspected key exposure, the operator owns containment, revocation and
   replacement; restoring binaries does not revoke an exposed key. Send library
   issues through the [private reporting channel](../SECURITY.md) with synthetic
   reproduction data. Never attach real keys, private content or payment records.

## Release-readiness review, September 5, 2026

ECC `production-audit` was applied to the public library's packaging/release
surface. The scope is a **technical-preview evaluation**, not approval for a
live payment service. The review found missing native SDK notices, source
packages carrying tests without their repository dependencies, and no explicit
release/rollback procedure. Those findings are addressed by the install rules,
Python distribution boundary, artifact gate and this runbook.

The completed evidence supports a scoped technical-preview evaluation.
Source/wheel reconstruction and isolated adoption, native SDK installation and
external consumption, public CI, and the [validation record](VALIDATION.md)
provide the basis for that decision. This was a maintainer review using an
assisted workflow, not an independent audit or security certification.
Linux CUDA acceptance, independent cryptographic review, constant-time/key
isolation requirements and production workload recovery remain outside the
completed evidence. [Production readiness](PRODUCTION_READINESS.md) identifies
the owners and required evidence for those decisions.
