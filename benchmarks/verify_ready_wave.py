"""SPDX-License-Identifier: Apache-2.0. Verify ready-wave evidence and JOSE samples."""

import hashlib
import json
import math
import subprocess
import sys

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from run_pipeline import ROOT, quiet_gpus
from verify_pipeline import verify_telemetry


def check_row(row, *, separate=False):
    for key, value in row.items():
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError(f"non-finite {key}")
    wave, keys, workers = row["wave"], row["keys"], row["workers"]
    assert (wave, keys) in [
        (1, 1),
        (8, 1),
        (64, 1),
        (256, 1),
        (1024, 1),
        (4096, 1),
        (4096, 16),
    ]
    assert workers in (4, 8) and row["active_workers"] == min(workers, wave)
    assert row["mode"] in ("cpu-es256", "cpu-eddsa", "hybrid-es256")
    assert row["repeat"] in (1, 2) and row["duration_s"] == 3
    times = row["wave_latencies_ms"]
    assert (
        times
        and times == sorted(times)
        and all(math.isfinite(t) and t > 0 for t in times)
    )
    assert row["waves"] == len(times) and row["verified"] == wave * len(times)
    expected_gpu = (
        row["verified"] if row["mode"] == "hybrid-es256" and wave // keys >= 64 else 0
    )
    assert row["gpu_items"] == expected_gpu
    if separate:
        assert row["verification_profile"] == "separate"
        assert row["gpu_guard_checks"] == expected_gpu
    else:
        assert row.get("verification_profile", "acceptance") == "acceptance"
        assert row.get("gpu_guard_checks", 0) == 0
    assert row["within_10ms"] == wave * sum(t <= 10 for t in times)
    assert row["within_50ms"] == wave * sum(t <= 50 for t in times)
    assert row["elapsed_s"] >= 3 and row["process_cpu_s"] >= 0
    assert 0 < sum(times) / 1000 <= row["elapsed_s"] + 1e-6
    assert math.isclose(
        sum(row[k] for k in ("prepare_s", "sign_s", "finish_s")),
        sum(times) / 1000,
        abs_tol=1e-5,
    )
    for key, fraction in [
        ("p50_ms", 0.5),
        ("p95_ms", 0.95),
        ("p99_ms", 0.99),
        ("max_ms", 1),
    ]:
        assert math.isclose(
            row[key], times[math.ceil(len(times) * fraction) - 1], abs_tol=1e-7
        )
    for name, count in [
        ("throughput_rps", row["verified"]),
        ("goodput_50ms", row["within_50ms"]),
    ]:
        assert math.isclose(row[name], count / row["elapsed_s"], rel_tol=1e-8)
    assert row["preflight_quiet"] is True
    assert quiet_gpus(row["preflight_telemetry"][-3:], row["device"])
    verify_telemetry(row["preflight_telemetry"])
    verify_telemetry(row["telemetry"])
    assert len(row["samples"]) == keys
    ed = row["mode"] == "cpu-eddsa"
    for k, sample in enumerate(row["samples"]):
        raw = bytes.fromhex(sample["public_hex"])
        public = (
            ed25519.Ed25519PublicKey.from_public_bytes(raw)
            if ed
            else ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
        )
        algorithm = "EdDSA" if ed else "ES256"
        assert jwt.get_unverified_header(sample["token"]) == {
            "alg": algorithm,
            "kid": f"wave-{k}",
            "typ": "JWT",
        }
        # Preserve cryptographic and issuer/audience checks. Wall-clock freshness
        # of an archived fixture is irrelevant; its issuance window is checked below.
        claims = jwt.decode(
            sample["token"],
            public,
            algorithms=[algorithm],
            issuer="issuer.example",
            audience="publisher.example",
            options={
                "verify_exp": False,
                "verify_iat": False,
                "require": ["exp", "iat", "jti", "sub"],
            },
        )
        assert claims == {
            "iss": "issuer.example",
            "aud": "publisher.example",
            "sub": "buyer-1",
            "iat": claims["iat"],
            "exp": claims["iat"] + 3600,
            "jti": f"wave-{row['waves'] + 2}-item-{k}",
            "scope": "content:read",
            "quote": f"quote-{k}",
            "content_sha256": "a" * 64,
            "terms_sha256": "b" * 64,
            "units": 1,
        }


def verify(path, *, sources=True):
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["complete"] is True and data["failure"] is None
    meta = data["metadata"]
    if sources:
        for file, expected in meta["source_sha256"].items():
            blob = subprocess.check_output(
                ["git", "show", f"{meta['commit']}:{file}"], cwd=ROOT
            )
            assert hashlib.sha256(blob).hexdigest() == expected, file
    build = json.loads(
        (ROOT / "benchmarks/ready_wave_build.json").read_text(encoding="utf-8")
    )
    allowed = [build["binaries"]] + [
        entry["binaries"] for entry in build.get("additional_builds", [])
    ]
    assert meta["binaries"] in allowed
    campaign = meta.get("campaign", "ready-waves")
    assert campaign in ("ready-waves", "separate-consumer")
    separate = campaign == "separate-consumer"
    expected = {
        (r, m, n, k, w)
        for r in (1, 2)
        for m in ("cpu-es256", "cpu-eddsa", "hybrid-es256")
        for n, k in [
            (1, 1),
            (8, 1),
            (64, 1),
            (256, 1),
            (1024, 1),
            (4096, 1),
            (4096, 16),
        ]
        for w in (4, 8)
    }
    if separate:
        expected = {
            cell
            for cell in expected
            if cell[1] != "cpu-eddsa" and (cell[2], cell[3]) in ((256, 1), (1024, 1))
        }
    actual = set()
    for row in data["rows"]:
        cell = tuple(row[k] for k in ("repeat", "mode", "wave", "keys", "workers"))
        assert cell not in actual
        actual.add(cell)
        assert row["device"] == meta["selected_device"]
        check_row(row, separate=separate)
    assert actual == expected
    return data


def main():
    directory = ROOT / "benchmarks/ready_wave_results"
    checksums = dict(
        line.split("  ", 1)[::-1]
        for line in (directory / "SHA256SUMS").read_text().splitlines()
    )
    paths = sorted(directory.glob("*.json"))
    assert set(checksums) == {p.name for p in paths} and paths
    total = 0
    for path in paths:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == checksums[path.name]
        data = verify(path)
        total += sum(row["verified"] for row in data["rows"])
    print(
        f"PASS: {len(paths)} complete ready-wave captures; {total:,} verified tokens; source/build hashes, telemetry, latency accounting and PyJWT samples checked."
    )


if __name__ == "__main__":
    if "--no-assertions" in sys.argv:
        raise SystemExit("assertions must remain enabled")
    if not __debug__:
        raise SystemExit("run without Python -O")
    main()
