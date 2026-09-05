"""SPDX-License-Identifier: Apache-2.0. Check our locally built release artifacts.

Uses only the standard library; reads archives without extracting or executing
them. Compare artifacts to the checkout that built them. This is a packaging
gate, not a security audit, signature verifier or reproducible-build claim.
"""

import argparse
from email.parser import BytesParser
import hashlib
from pathlib import Path
import re
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_metadata(data, version):
    metadata = BytesParser().parsebytes(data)
    require(metadata["Name"] == "gpu-batch-crypto", "wrong package name")
    require(metadata["Version"] == version, "package/source version mismatch")
    require(metadata["License-Expression"] == "Apache-2.0", "wrong license metadata")
    require(
        set(metadata.get_all("License-File", [])) == {"LICENSE", "NOTICE"},
        "license metadata must name LICENSE and NOTICE",
    )


def check_python(directory, version):
    wheels = list(directory.glob("*.whl"))
    sdists = list(directory.glob("*.tar.gz"))
    require(
        len(wheels) == len(sdists) == 1,
        "use one wheel and one sdist in a fresh directory",
    )
    sources = {
        p.relative_to(ROOT / "python").as_posix(): p.read_bytes()
        for p in (ROOT / "python/batchcrypto").rglob("*.py")
    }
    info = f"gpu_batch_crypto-{version}.dist-info"
    metadata_names = {"METADATA", "WHEEL", "top_level.txt", "RECORD"}
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        expected = set(sources) | {f"{info}/{n}" for n in metadata_names}
        expected |= {f"{info}/licenses/{n}" for n in ("LICENSE", "NOTICE")}
        require(
            len(names) == len(set(names)) and set(names) == expected,
            "wheel has missing or unexpected files",
        )
        for name, data in sources.items():
            require(archive.read(name) == data, f"wheel/source mismatch: {name}")
        for name in ("LICENSE", "NOTICE"):
            require(
                archive.read(f"{info}/licenses/{name}") == (ROOT / name).read_bytes(),
                f"wheel notice mismatch: {name}",
            )
        check_metadata(archive.read(f"{info}/METADATA"), version)
        wheel = BytesParser().parsebytes(archive.read(f"{info}/WHEEL"))
        require(
            wheel["Root-Is-Purelib"] == "true"
            and wheel.get_all("Tag") == ["py3-none-any"],
            "Python wheel must remain platform-independent",
        )

    prefix = f"gpu_batch_crypto-{version}/"
    egg = "python/gpu_batch_crypto.egg-info/"
    egg_names = {
        "PKG-INFO",
        "SOURCES.txt",
        "dependency_links.txt",
        "requires.txt",
        "top_level.txt",
    }
    copied = {
        "LICENSE",
        "NOTICE",
        "SECURITY.md",
        "README.md",
        "python/README.md",
        "pyproject.toml",
        "MANIFEST.in",
    }
    expected = copied | {"PKG-INFO", "setup.cfg"}
    expected |= {f"python/{n}" for n in sources} | {egg + n for n in egg_names}
    with tarfile.open(sdists[0]) as archive:
        members = [m for m in archive.getmembers() if not m.isdir()]
        names = [m.name for m in members]
        require(all(m.isfile() for m in members), "sdist has a non-regular file")
        require(
            len(names) == len(set(names))
            and set(names) == {prefix + n for n in expected},
            "sdist has missing or unexpected files",
        )
        for name in copied | {f"python/{n}" for n in sources}:
            require(
                archive.extractfile(prefix + name).read() == (ROOT / name).read_bytes(),
                f"sdist/source mismatch: {name}",
            )
        check_metadata(archive.extractfile(prefix + "PKG-INFO").read(), version)
    for artifact in sdists + wheels:
        print(f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}")
    print("PASS: Python sdist/wheel scope, source bytes, version and license notices")


def check_sdk(directory):
    for name in ("LICENSE", "NOTICE"):
        candidates = list(directory.glob(f"**/licenses/batchcrypto/{name}"))
        require(
            len(candidates) == 1
            and candidates[0].read_bytes() == (ROOT / name).read_bytes(),
            f"SDK missing or changed {name}",
        )
    candidates = list(directory.glob("**/doc/batchcrypto/SECURITY.md"))
    require(
        len(candidates) == 1
        and candidates[0].read_bytes() == (ROOT / "SECURITY.md").read_bytes(),
        "SDK missing or changed security scope",
    )
    require(
        (directory / "include/batchcrypto.h").read_bytes()
        == (ROOT / "include/batchcrypto.h").read_bytes(),
        "SDK header/source mismatch",
    )
    require(
        len(list(directory.glob("**/cmake/batchcrypto/batchcryptoConfig.cmake"))) == 1,
        "SDK missing or ambiguous CMake package",
    )
    libraries = list(directory.glob("bin/batchcrypto.dll")) + list(
        directory.glob("lib*/libbatchcrypto.so")
    )
    require(len(libraries) == 1, "SDK missing or ambiguous shared library")
    print(
        f"{hashlib.sha256(libraries[0].read_bytes()).hexdigest()}  {libraries[0].relative_to(directory)}"
    )
    print(
        "PASS: native SDK header, library, CMake entry point, notices and security scope"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-dist", type=Path)
    parser.add_argument(
        "--sdk", type=Path, help="SDK installed with default GNUInstallDirs layout"
    )
    args = parser.parse_args()
    require(
        args.python_dist is not None or args.sdk is not None,
        "select --python-dist and/or --sdk",
    )
    version = re.search(
        r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M
    ).group(1)
    require(
        f"project(batchcrypto VERSION {version} "
        in (ROOT / "CMakeLists.txt").read_text(),
        "Python/native project version mismatch",
    )
    if args.python_dist is not None:
        check_python(args.python_dist.resolve(), version)
    if args.sdk is not None:
        check_sdk(args.sdk.resolve())


if __name__ == "__main__":
    main()
