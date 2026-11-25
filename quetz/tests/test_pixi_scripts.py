import runpy
import shlex
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    return runpy.run_path(str(ROOT / "pixi-scripts" / f"{name}.py"))


def test_docs_clean_preserves_sources(tmp_path):
    clean = load("clean_docs")["clean"]
    (tmp_path / "docs/build/html").mkdir(parents=True)
    source = tmp_path / "docs/source/index.adoc"
    source.parent.mkdir()
    source.write_text("= Documentation\n")
    clean(tmp_path)
    clean(tmp_path)
    assert not (tmp_path / "docs/build").exists()
    assert source.read_text() == "= Documentation\n"


def test_plugin_failures_do_not_skip_other_plugins(tmp_path, monkeypatch):
    script = load("run_plugins")
    for name in ["quetz_a", "quetz_b", "quetz_c"]:
        (tmp_path / "plugins" / name).mkdir(parents=True)
    run = Mock(side_effect=[SimpleNamespace(returncode=c) for c in [1, 0, 1, 0, 0]])
    monkeypatch.setattr(script["subprocess"], "run", run)
    assert script["test_plugins"](tmp_path) == 1
    commands = [call.args[0] for call in run.call_args_list]
    assert len(commands) == 5
    assert all(cmd[:5] == ["pixi", "run", "--locked", "-e", "dev"] for cmd in commands)
    assert commands[-1][-1] == "plugins/quetz_c"


def test_services_wait_for_health(monkeypatch):
    script = load("ci_services")
    run = Mock(return_value=SimpleNamespace(stdout="healthy\n"))
    monkeypatch.setattr(script["subprocess"], "run", run)
    script["start"]()
    commands = [call.args[0] for call in run.call_args_list]
    assert sum(cmd[:2] == ["podman", "run"] for cmd in commands) == 2
    assert sum(cmd[:2] == ["podman", "inspect"] for cmd in commands) == 2


def test_services_timeout_reports_logs(monkeypatch):
    script = load("ci_services")
    run = Mock(return_value=SimpleNamespace(stdout="starting\n"))
    monkeypatch.setattr(script["subprocess"], "run", run)
    monkeypatch.setattr(script["time"], "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="quetz-ci-postgres"):
        script["start"]()
    assert ["podman", "logs", "quetz-ci-postgres"] in [
        call.args[0] for call in run.call_args_list
    ]


def test_postgres_wait_preserves_command_arguments(monkeypatch):
    script = load("wait_for_postgres")
    run = Mock(
        side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]
    )
    execute = Mock()
    monkeypatch.setattr(script["subprocess"], "run", run)
    monkeypatch.setattr(script["time"], "sleep", lambda _: None)
    monkeypatch.setattr(script["os"], "execvp", execute)
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")
    script["wait_and_exec"]("database", ["quetz", "start", "a deployment"])
    assert run.call_args.kwargs["env"]["PGPASSWORD"] == "test-password"
    execute.assert_called_once_with("quetz", ["quetz", "start", "a deployment"])


def test_postgres_command_failure_propagates(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")
    script = load("wait_for_postgres")
    monkeypatch.setattr(
        script["subprocess"], "run", Mock(side_effect=FileNotFoundError("psql"))
    )
    with pytest.raises(FileNotFoundError):
        script["wait_and_exec"]("database", [])


def test_download_failure_preserves_existing_package(tmp_path, monkeypatch):
    script = load("download_test_packages")
    filename = script["PACKAGES"]["linux-64"]
    original = tmp_path / "linux-64" / filename
    original.parent.mkdir()
    original.write_bytes(b"previous download")
    download = script["download"]
    monkeypatch.setitem(
        download.__globals__, "urlopen", Mock(side_effect=OSError("offline"))
    )
    with pytest.raises(OSError, match="offline"):
        download(tmp_path)
    assert original.read_bytes() == b"previous download"
    assert not list(tmp_path.rglob("*.part"))


def test_upload_uses_downloaded_packages_and_propagates_http_failure(
    tmp_path, monkeypatch
):
    script = load("upload_test_packages")
    package = tmp_path / "linux-64" / "xtensor-test.tar.bz2"
    package.parent.mkdir()
    package.write_bytes(b"example")
    response = Mock()
    response.raise_for_status.side_effect = script["requests"].HTTPError("rejected")
    post = Mock(return_value=response)
    monkeypatch.setattr(script["requests"], "post", post)
    monkeypatch.setenv("QUETZ_API_KEY", "test-api-key")
    monkeypatch.setenv("QUETZ_SERVER_URL", "http://localhost:8000/")
    with pytest.raises(script["requests"].HTTPError, match="rejected"):
        script["upload"](tmp_path, "channel0")
    assert (
        post.call_args.args[0]
        == "http://localhost:8000/api/channels/channel0/packages/xtensor/files/"
    )
    assert post.call_args.kwargs["headers"] == {"X-API-Key": "test-api-key"}
    files = post.call_args.kwargs["files"]
    assert files[0][1][0] == package.name
    assert files[0][1][1].closed


def test_upload_requires_downloaded_packages(tmp_path):
    with pytest.raises(ValueError, match="download-test-packages"):
        load("upload_test_packages")["upload"](tmp_path, "channel0")


def test_pixi_task_scripts_follow_qep2():
    manifests = [ROOT / "pixi.toml", *sorted((ROOT / "plugins").glob("*/pixi.toml"))]
    for path in manifests:
        manifest = tomllib.loads(path.read_text())
        sections = [manifest, *manifest.get("feature", {}).values()]
        for section in sections:
            for task in section.get("tasks", {}).values():
                command = task if isinstance(task, str) else task.get("cmd", "")
                arguments = (
                    shlex.split(command) if isinstance(command, str) else command
                )
                for argument in arguments:
                    if argument.endswith((".py", ".sh", ".bat", ".nu")):
                        script = Path(argument)
                        assert script.parts[0] == "pixi-scripts", path
                        assert script.suffix in {".py", ".nu"}, path
                        assert (path.parent / script).is_file(), path
    assert not list((ROOT / "docs").glob("*Makefile*"))
    assert not (ROOT / "docs/make.bat").exists()
