import tomllib
from pathlib import Path

import yaml

from quetz.config import Config

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/source/_examples/kubernetes"


def objects(name):
    return list(yaml.safe_load_all((EXAMPLES / name).read_text()))


def test_workload_has_no_kubernetes_credentials_and_runs_unprivileged():
    account = objects("bootstrap.yaml")[1]
    assert account["kind"] == "ServiceAccount"
    assert account["automountServiceAccountToken"] is False
    for filename in ["migrate.yaml", "workload.yaml"]:
        resource = objects(filename)[0]
        pod = resource["spec"]["template"]["spec"]
        assert pod["serviceAccountName"] == "quetz"
        assert pod["automountServiceAccountToken"] is False
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["securityContext"]["runAsUser"] == 10001
        container = pod["containers"][0]
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert container["securityContext"]["allowPrivilegeEscalation"] is False
        assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
        assert container["envFrom"] == [{"secretRef": {"name": "quetz-runtime"}}]
    deployment = objects("workload.yaml")[0]
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"]["type"] == "Recreate"


def test_configuration_uses_oidc_authority_and_environment_secrets(monkeypatch):
    path = EXAMPLES / "config.toml"
    data = tomllib.loads(path.read_text())
    assert "secret" not in data["session"]
    assert "client_secret" not in data["oidc"]
    monkeypatch.setattr(Config, "_instances", {})
    monkeypatch.setenv(
        "QUETZ_SQLALCHEMY_DATABASE_URL", "postgresql://quetz:secret@database/quetz"
    )
    monkeypatch.setenv("QUETZ_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("QUETZ_OIDC_CLIENT_SECRET", "test-client-secret")
    config = Config(str(path))
    assert config.oidc_only is True
    assert config.session_https_only is True
    assert config.oidc_roles_claim == ["resource_access", "{client_id}", "roles"]
    assert config.oidc_client_secret == "test-client-secret"


def test_probe_paths_exist_and_readiness_is_separate(client):
    pod = objects("workload.yaml")[0]["spec"]["template"]["spec"]
    container = pod["containers"][0]
    for probe in ["startupProbe", "readinessProbe", "livenessProbe"]:
        assert client.get(container[probe]["httpGet"]["path"]).status_code == 200
    assert (
        container["readinessProbe"]["httpGet"]["path"]
        != container["livenessProbe"]["httpGet"]["path"]
    )
    job = objects("migrate.yaml")[0]
    args = job["spec"]["template"]["spec"]["containers"][0]["args"]
    assert args == ["quetz", "init-db", "/data", "--create-deployment"]
