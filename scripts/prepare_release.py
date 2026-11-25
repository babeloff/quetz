# tag::prepare-release[]
"""Validate a release's platform packages and assemble source and checksums."""

import argparse
import hashlib
import json
import runpy
import subprocess
import tarfile
import zipfile
from pathlib import Path

import zstandard


def package_index(path):
    index = None
    paths = []
    with zipfile.ZipFile(path) as archive:
        info = next(n for n in archive.namelist() if n.startswith("info-"))
        with archive.open(info) as compressed:
            with zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
                with tarfile.open(fileobj=stream, mode="r|") as contents:
                    for member in contents:
                        if member.name == "info/index.json":
                            index = json.load(contents.extractfile(member))
                        elif member.name == "info/paths.json":
                            paths = [
                                p["_path"]
                                for p in json.load(contents.extractfile(member))[
                                    "paths"
                                ]
                            ]
    if not index:
        raise ValueError(f"Missing package index: {path}")
    if any("__editable__" in p for p in paths) or not any(
        p.endswith("site-packages/quetz/authentication/oidc.py") for p in paths
    ):
        raise ValueError(f"Package must contain installed Quetz sources: {path}")
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("dist/release"))
    parser.add_argument("--platform", action="append", dest="platforms")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    version = runpy.run_path(str(root / "quetz/_version.py"))["__version__"]
    platforms = set(args.platforms or ["linux-64", "osx-64"])
    packages = sorted(args.directory.glob("*.conda"))
    found = []
    for path in packages:
        index = package_index(path)
        if index["name"] != "quetz-server" or index["version"] != version:
            raise ValueError(f"Unexpected package/version: {path}")
        found.append(index["subdir"])
    if set(found) != platforms or len(found) != len(platforms):
        raise ValueError(f"Expected one package per {sorted(platforms)}; found {found}")
    source = args.directory / f"quetz-{version}.tar.gz"
    subprocess.run(
        [
            "git",
            "archive",
            "--format=tar.gz",
            f"--prefix=quetz-{version}/",
            "-o",
            str(source.resolve()),
            "HEAD",
        ],
        cwd=root,
        check=True,
    )
    with tarfile.open(source) as archive:
        archived = archive.extractfile(f"quetz-{version}/quetz/_version.py").read()
    if archived != (root / "quetz/_version.py").read_bytes():
        raise ValueError("Commit the version bump before preparing the release")
    artifacts = [source, *packages]
    (args.directory / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
            for p in artifacts
        )
    )
    print(f"Validated {len(packages)} platform packages and source for {version}")


if __name__ == "__main__":
    main()
# end::prepare-release[]
