import hashlib
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
import zstandard

from quetz._version import __version__

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "pixi-scripts/prepare_release.py"


def package(directory, platform):
    path = directory / f"quetz-server-{__version__}-{platform}.conda"
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w") as archive:
        for name, data in {
            "info/index.json": {
                "name": "quetz-server",
                "version": __version__,
                "subdir": platform,
            },
            "info/paths.json": {
                "paths": [
                    {
                        "_path": "lib/python3.11/site-packages/quetz/authentication/oidc.py"
                    }
                ]
            },
        }.items():
            body = json.dumps(data).encode()
            entry = tarfile.TarInfo(name)
            entry.size = len(body)
            archive.addfile(entry, io.BytesIO(body))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("info-test.tar.zst", zstandard.compress(content.getvalue()))
    return path


def prepare(directory, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--directory", str(directory), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_default_release_defers_apple_silicon(tmp_path):
    package(tmp_path, "linux-64")
    package(tmp_path, "osx-64")
    result = prepare(tmp_path)
    assert result.returncode == 0, result.stderr
    entries = (tmp_path / "SHA256SUMS").read_text().splitlines()
    assert len(entries) == 3
    for entry in entries:
        checksum, filename = entry.split("  ")
        assert (
            hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest() == checksum
        )


@pytest.mark.parametrize("platform", ["linux-64", "osx-64"])
def test_default_release_requires_both_platforms(tmp_path, platform):
    package(tmp_path, platform)
    result = prepare(tmp_path)
    assert result.returncode != 0
    assert "Expected one package per" in result.stderr
    assert not (tmp_path / "SHA256SUMS").exists()


def test_optional_apple_silicon_must_be_explicit(tmp_path):
    for platform in ["linux-64", "osx-64", "osx-arm64"]:
        package(tmp_path, platform)
    assert prepare(tmp_path).returncode != 0
    result = prepare(
        tmp_path,
        "--platform",
        "linux-64",
        "--platform",
        "osx-64",
        "--platform",
        "osx-arm64",
    )
    assert result.returncode == 0, result.stderr


def helm_chart(directory, version=__version__):
    path = directory / f"quetz-{__version__}.tgz"
    with tarfile.open(path, "w:gz") as archive:
        for filename, body in {
            "quetz/Chart.yaml": f'name: quetz\nversion: {version}\nappVersion: "{version}"\n'.encode(),
            "quetz/values.yaml": b"mode: migrate\n",
            "quetz/values.schema.json": b"{}\n",
            "quetz/templates/workload.yaml": b"apiVersion: apps/v1\n",
        }.items():
            member = tarfile.TarInfo(filename)
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
    return path


def test_release_can_include_validated_helm_chart(tmp_path):
    package(tmp_path, "linux-64")
    package(tmp_path, "osx-64")
    chart = helm_chart(tmp_path)
    result = prepare(tmp_path, "--include-chart")
    assert result.returncode == 0, result.stderr
    assert (
        f"{hashlib.sha256(chart.read_bytes()).hexdigest()}  {chart.name}"
        in (tmp_path / "SHA256SUMS").read_text()
    )
    assert len((tmp_path / "SHA256SUMS").read_text().splitlines()) == 4


def test_release_rejects_wrong_helm_version(tmp_path):
    package(tmp_path, "linux-64")
    package(tmp_path, "osx-64")
    helm_chart(tmp_path, version="0.0.0")
    result = prepare(tmp_path, "--include-chart")
    assert result.returncode != 0
    assert "Unexpected Helm chart identity/version" in result.stderr
    assert not (tmp_path / "SHA256SUMS").exists()


def test_release_requires_requested_helm_chart(tmp_path):
    package(tmp_path, "linux-64")
    package(tmp_path, "osx-64")
    result = prepare(tmp_path, "--include-chart")
    assert result.returncode != 0
    assert f"quetz-{__version__}.tgz" in result.stderr
    assert not (tmp_path / "SHA256SUMS").exists()
