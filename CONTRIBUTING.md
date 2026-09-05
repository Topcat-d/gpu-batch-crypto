# Contributing

Start with the [component catalog](docs/COMPONENTS.md). Changes should preserve
the ability to use the CPU core, native SDK, token encoder and standalone
examples independently. This public repository contains selected Apache-2.0
extracts and original integration code; contribute only material you have the
right to submit under that license. Preserve `LICENSE`, `NOTICE` and attribution.

For ordinary bugs, open a repository issue with the component, full source
commit, OS/toolchain, expected/actual behavior and a small synthetic example.
For GPU failures, include the selected GPU ordinal/model, driver/CUDA versions,
native artifact hash, operation/batch size and returned statuses. Avoid real
keys or private workloads. Security-sensitive reports belong in the
[private reporting channel](SECURITY.md).

## Make a focused change

- Explain the concrete behavior being changed and which public interface it
  affects. Include a meaningful regression test for correctness/failure changes.
- Keep authorization, accounting and payment policy outside the cryptographic
  core. New optional features must not silently add application or GPU
  requirements to CPU-only imports.
- Preserve call-level/per-item errors, all-or-nothing guarded output, key epoch
  binding and caller buffer rules. The public header is the native contract.
- Imported implementation changes need an explicit modification notice and an
  updated extraction record. Do not update a hash merely to hide an unexplained
  source change. Read [EXTRACTION.json](EXTRACTION.json) and the boundary verifier.
- Update relevant component contracts/examples when changing inputs, outputs,
  failure behavior or dependencies. Follow [release instructions](docs/RELEASING.md)
  for artifact/version changes.

## Run checks that match the change

From a full clone, install the Python core and optional example verifier:

```sh
python -m pip install '.[interop]'
python -m unittest discover -s tests -v
python tools/verify_extraction.py
python tools/generate_p256_tables.py --check
```

Without `BC_LIBRARY`, CUDA-specific tests skip. To change native code, run with
the newly built library and the intended device via `BC_LIBRARY`/`BC_DEVICE`,
plus the C consumer and affected differential tests. Report skips as skips;
hosted CPU CI does not establish GPU correctness. Native sanitizer coverage and
platform gaps are listed in [VALIDATION.md](docs/VALIDATION.md).

For packaging changes, build the source distribution and wheel and run
`tools/check_distributions.py`, then the isolated installed-package checks from
[RELEASING.md](docs/RELEASING.md). CMake install changes additionally require a
fresh SDK install and external C consumer. Do not add a remote service or
unreviewed scanner to verify local artifacts.

The [CI workflow](.github/workflows/ci.yml) also runs the evidence verifiers,
generated-report checks and native OpenSSL CPU harness. Use a full clone:
archived source fingerprints require historical commits. Tests or generated
reports failing against an existing capture should be investigated before
editing data.

## Contribute benchmark evidence

Predeclare the question, comparable CPU baseline, batch/key distribution,
deadline, timing boundary, repetitions, run order and stop conditions. Include
whole-system verification work when it exists in the intended integration.
Keep unsuccessful, expired, late and unused work visible in its correct
denominator. Record hardware, driver/toolchain, source/binary fingerprints and
competing-load conditions with raw outputs.

Add a new capture instead of rewriting historical measurements. Changes to
measurement code do not change the source hash of an earlier run. A primitive
speedup is not proof of a service cost advantage; funding, utilization,
unconsumed reservations and external fees need explicit assumptions. Start
with [benchmark methodology](docs/BENCHMARKS.md) and the applicable campaign file.
