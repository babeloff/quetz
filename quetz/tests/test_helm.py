import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from quetz._version import __version__

CHART = (
    Path(__file__).resolve().parents[2] / "docs/source/_examples/kubernetes/helm/quetz"
)


def render(*arguments, release="quetz"):
    return subprocess.run(
        [
            "helm",
            "template",
            release,
            str(CHART),
            "--namespace",
            "packages",
            *arguments,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def resources(*arguments, **kwargs):
    result = render(*arguments, **kwargs)
    assert result.returncode == 0, result.stderr
    return [item for item in yaml.safe_load_all(result.stdout) if item]


@pytest.mark.parametrize("mode,replicas,jobs", [("migrate", 0, 1), ("serve", 1, 0)])
def test_modes_separate_migration_from_serving(mode, replicas, jobs):
    objects = resources("--set", f"mode={mode}")
    (deployment,) = [obj for obj in objects if obj["kind"] == "Deployment"]
    assert deployment["spec"]["replicas"] == replicas
    assert deployment["spec"]["strategy"]["type"] == "Recreate"
    assert (
        deployment["spec"]["selector"]["matchLabels"]["app.kubernetes.io/component"]
        == "server"
    )
    (service,) = [obj for obj in objects if obj["kind"] == "Service"]
    assert service["spec"]["selector"]["app.kubernetes.io/component"] == "server"
    assert len([obj for obj in objects if obj["kind"] == "Job"]) == jobs
    assert not [
        obj
        for obj in objects
        if obj["kind"]
        in ["Secret", "Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding"]
    ]
    for obj in objects:
        assert obj["metadata"]["namespace"] == "packages"
        if obj["kind"] not in ["Deployment", "Job"]:
            continue
        template = obj["spec"]["template"]
        assert template["metadata"]["labels"]["app.kubernetes.io/instance"] == "quetz"
        pod = template["spec"]
        assert pod["automountServiceAccountToken"] is False
        assert pod["securityContext"]["runAsUser"] == 10001
        container = pod["containers"][0]
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert container["envFrom"] == [{"secretRef": {"name": "quetz-runtime"}}]
        assert container["image"].endswith(f":v{__version__}")


def test_values_reach_configuration_and_scoped_resources():
    objects = resources(
        "--set",
        "oidc.issuer=https://login.example.org/realms/company",
        "--set",
        "oidc.clientId=packages",
        "--set",
        "oidc.audience=packages-api",
        "--set",
        "existingSecret=company-secrets",
        release="company",
    )
    (configmap,) = [obj for obj in objects if obj["kind"] == "ConfigMap"]
    config = tomllib.loads(configmap["data"]["config.toml"])
    assert config["oidc"]["issuer"] == "https://login.example.org/realms/company"
    assert config["oidc"]["client_id"] == "packages"
    assert config["oidc"]["audience"] == "packages-api"
    assert config["oidc"]["only"] is True
    assert "client_secret" not in config["oidc"]
    assert "secret" not in config["session"]
    (policy,) = [obj for obj in objects if obj["kind"] == "NetworkPolicy"]
    assert (
        policy["spec"]["podSelector"]["matchLabels"]["app.kubernetes.io/instance"]
        == "company"
    )
    for obj in objects:
        if obj["kind"] in ["Deployment", "Job"]:
            pod = obj["spec"]["template"]["spec"]
            assert pod["containers"][0]["envFrom"] == [
                {"secretRef": {"name": "company-secrets"}}
            ]


def test_external_storage_and_identity_can_be_selected():
    objects = resources(
        "--set",
        "persistence.existingClaim=retained-packages",
        "--set",
        "serviceAccount.create=false",
        "--set",
        "serviceAccount.name=existing-identity",
        "--set",
        "ingress.enabled=false",
        "--set",
        "networkPolicy.enabled=false",
    )
    assert not [
        obj
        for obj in objects
        if obj["kind"]
        in ["PersistentVolumeClaim", "ServiceAccount", "Ingress", "NetworkPolicy"]
    ]
    for obj in objects:
        if obj["kind"] in ["Deployment", "Job"]:
            pod = obj["spec"]["template"]["spec"]
            assert pod["serviceAccountName"] == "existing-identity"
            assert (
                pod["volumes"][0]["persistentVolumeClaim"]["claimName"]
                == "retained-packages"
            )


@pytest.mark.parametrize(
    "setting",
    [
        "replicaCount=2",
        "mode=unsafe",
        "oidc.issuer=http://insecure.example",
        "oidc.clientSecret=not-permitted",
        "unknownField=value",
    ],
)
def test_schema_rejects_unsupported_or_secret_values(setting):
    result = render("--set", setting)
    assert result.returncode != 0


def test_chart_versions_follow_application():
    chart = yaml.safe_load((CHART / "Chart.yaml").read_text())
    assert chart["version"] == chart["appVersion"] == __version__
