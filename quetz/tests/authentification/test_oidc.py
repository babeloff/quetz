import base64
import json
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from authlib.jose import JsonWebKey, jwt
from fastapi import HTTPException

from quetz.authentication.oidc import OIDCAuthenticator, get_oidc_authenticator
from quetz.authorization import Rules
from quetz.db_models import Identity, User
from quetz.errors import ConfigError

ISSUER = "https://id.example/realms/quetz"


@pytest.fixture
def config_extra():
    return f"""
[oidc]
issuer = "{ISSUER}"
client_id = "quetz"
client_secret = "test-only-client-secret"
[users]
default_role = "owner"
admins = ["oidc:alice"]
create_default_channel = true
"""


@pytest.fixture
def provider():
    key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    private = key.as_dict(is_private=True)
    private["kid"] = "test-key"
    public = key.as_dict()
    public["kid"] = "test-key"
    state = {
        "claims": {
            "active": True,
            "iss": ISSUER,
            "aud": ["quetz"],
            "sub": "subject-1",
            "exp": int(time.time()) + 300,
            "token_type": "Bearer",
            "preferred_username": "alice",
            "resource_access": {"quetz": {"roles": []}},
        },
        "nonce": "",
        "id_overrides": {},
        "requests": [],
    }

    def respond(request):
        state["requests"].append(request)
        path = request.url.path
        if path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": state.get("metadata_issuer", ISSUER),
                    "authorization_endpoint": ISSUER + "/authorize",
                    "token_endpoint": ISSUER + "/token",
                    "jwks_uri": ISSUER + "/keys",
                    "introspection_endpoint": state.get(
                        "introspection_url", ISSUER + "/introspect"
                    ),
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if path.endswith("/keys"):
            return httpx.Response(200, json={"keys": [public]})
        if path.endswith("/introspect"):
            if state.get("unavailable"):
                return httpx.Response(503)
            assert request.headers["authorization"].startswith("Basic ")
            assert "token=access-token" in request.content.decode()
            return httpx.Response(200, json=state["claims"])
        if path.endswith("/token"):
            claims = {
                "iss": ISSUER,
                "aud": "quetz",
                "sub": "subject-1",
                "exp": int(time.time()) + 300,
                "iat": int(time.time()),
                "nonce": state["nonce"],
                **state["id_overrides"],
            }
            signing_key = private
            if state.get("invalid_signature"):
                signing_key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
            token = jwt.encode(
                {"alg": "RS256", "kid": "test-key"}, claims, signing_key
            ).decode()
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token",
                    "token_type": "Bearer",
                    "expires_in": 300,
                    "id_token": token,
                },
            )
        raise AssertionError(f"Unexpected provider URL {request.url}")

    state["transport"] = httpx.MockTransport(respond)
    return state


@pytest.fixture
def oidc(config, provider):
    auth = OIDCAuthenticator(config, client_kwargs={"transport": provider["transport"]})
    config._oidc_authenticator = auth
    return auth


@pytest.fixture
def oidc_client(oidc, request):
    client = request.getfixturevalue("client")
    from quetz.main import auth_registry

    if not auth_registry.is_registered("oidc"):
        auth_registry.register(oidc)
    return client


def bearer(client, path="/api/me", **kwargs):
    return client.get(path, headers={"Authorization": "Bearer access-token"}, **kwargs)


@pytest.mark.parametrize(
    "roles,expected",
    [
        ([], None),
        (["member"], "member"),
        (["maintainer"], "maintainer"),
        (["owner"], "owner"),
        (["member", "owner", "maintainer"], "owner"),
        (["unrecognized"], None),
    ],
)
def test_oidc_roles(oidc_client, provider, db, roles, expected):
    provider["claims"]["resource_access"]["quetz"]["roles"] = roles
    response = bearer(oidc_client)
    assert response.status_code == 200, response.text
    user = db.query(User).filter_by(username="alice").one()
    assert user.role == expected
    assert not user.emails
    identity = db.query(Identity).filter_by(user_id=user.id).one()
    assert json.loads(identity.identity_id) == [ISSUER, "subject-1"]
    assert identity.provider == "oidc"
    assert not user.channel_members


def test_roles_from_another_client_cannot_elevate(oidc_client, provider, db):
    provider["claims"]["resource_access"]["other-client"] = {"roles": ["owner"]}
    assert bearer(oidc_client).status_code == 200
    assert db.query(User).filter_by(username="alice").one().role is None


@pytest.mark.parametrize(
    "change",
    [
        {"active": False},
        {"active": "true"},
        {"iss": "https://attacker.example"},
        {"aud": "other-client"},
        {"aud": None},
        {"exp": 0},
        {"exp": None},
        {"exp": "9999999999"},
        {"sub": ""},
        {"sub": None},
        {"token_type": "Refresh"},
        {"nbf": 9999999999},
        {"resource_access": {"quetz": {"roles": "owner"}}},
    ],
)
def test_invalid_access_token_is_rejected(oidc_client, provider, db, change):
    provider["claims"].update(change)
    assert bearer(oidc_client).status_code == 401
    assert db.query(User).filter_by(username="alice").one_or_none() is None


@pytest.mark.parametrize(
    "change",
    [
        {"metadata_issuer": "https://attacker.example"},
        {"introspection_url": "http://id.example/introspect"},
        {"unavailable": True},
    ],
)
def test_oidc_provider_failure_is_closed(oidc_client, provider, db, change):
    provider.update(change)
    assert bearer(oidc_client).status_code == 503
    assert db.query(User).filter_by(username="alice").one_or_none() is None


def test_role_demotion_is_synchronized(oidc_client, provider, db):
    provider["claims"]["resource_access"]["quetz"]["roles"] = ["owner"]
    assert bearer(oidc_client).status_code == 200
    user = db.query(User).filter_by(username="alice").one()
    auth = Rules(None, {"user_id": str(uuid.UUID(bytes=user.id))}, db)
    auth.assert_create_mirror_channel()
    provider["claims"]["resource_access"]["quetz"]["roles"] = []
    assert bearer(oidc_client).status_code == 200
    assert user.role is None
    with pytest.raises(HTTPException) as error:
        auth.assert_create_channel()
    assert error.value.status_code == 403


def test_oidc_managed_roles_are_read_only(oidc_client, provider):
    provider["claims"]["resource_access"]["quetz"]["roles"] = ["owner"]
    assert bearer(oidc_client).status_code == 200
    response = oidc_client.put(
        "/api/users/alice/role",
        json={"role": "member"},
        headers={"Authorization": "Bearer access-token"},
    )
    assert response.status_code == 409
    response = oidc_client.post(
        "/api/api-keys",
        json={"description": "legacy", "roles": []},
        headers={"Authorization": "Bearer access-token"},
    )
    assert response.status_code == 409


def test_oidc_rejects_identity_collision(oidc_client, provider, user, db):
    provider["claims"]["preferred_username"] = user.username
    assert bearer(oidc_client).status_code == 422
    assert not db.query(Identity).filter_by(provider="oidc").count()


def test_oidc_only_disables_legacy_credentials(oidc_client, user):
    assert oidc_client.get(f"/api/dummylogin/{user.username}").status_code == 404
    assert (
        oidc_client.get("/api/users", headers={"X-API-Key": "legacy"}).status_code
        == 401
    )
    assert (
        oidc_client.get(
            "/api/users", headers={"Authorization": "Basic abc"}
        ).status_code
        == 401
    )
    assert (
        oidc_client.get(
            "/api/users",
            headers={"Authorization": "Bearer access-token", "X-API-Key": "legacy"},
        ).status_code
        == 400
    )


def login(client, provider):
    response = client.get("/auth/oidc/login", follow_redirects=False)
    assert response.status_code == 302
    params = parse_qs(urlsplit(response.headers["location"]).query)
    provider["nonce"] = params["nonce"][0]
    assert params["code_challenge_method"] == ["S256"]
    assert "code_challenge" in params
    return params["state"][0]


def test_browser_login_encrypts_tokens_and_revokes(oidc_client, provider, db):
    state = login(oidc_client, provider)
    response = oidc_client.get(
        f"/auth/oidc/authorize?code=valid&state={state}", follow_redirects=False
    )
    assert response.status_code == 303, response.text
    cookie = oidc_client.cookies["session"].split(".")[0]
    session = json.loads(base64.b64decode(cookie))
    assert "access-token" not in json.dumps(session)
    assert session["token"].startswith("oidc1.")
    assert oidc_client.get("/api/me").status_code == 200
    provider["claims"]["active"] = False
    assert oidc_client.get("/api/me").status_code == 401


@pytest.mark.parametrize(
    "change",
    [
        {"nonce": "wrong"},
        {"iss": "https://attacker.example"},
        {"aud": "other-client"},
        {"exp": 0},
        {"sub": "other-subject"},
    ],
)
def test_browser_rejects_invalid_id_tokens(oidc_client, provider, db, change):
    state = login(oidc_client, provider)
    provider["id_overrides"].update(change)
    response = oidc_client.get(
        f"/auth/oidc/authorize?code=valid&state={state}", follow_redirects=False
    )
    assert response.status_code == 401, response.text
    assert not db.query(User).filter_by(username="alice").count()


def test_browser_rejects_invalid_state(oidc_client, provider):
    login(oidc_client, provider)
    assert (
        oidc_client.get("/auth/oidc/authorize?code=valid&state=wrong").status_code
        == 401
    )


def test_oidc_requires_https(config):
    config.oidc_issuer = "http://id.example/realms/quetz"
    with pytest.raises(ConfigError):
        OIDCAuthenticator(config)


def test_oidc_factory_is_scoped_to_config(oidc, config):
    assert get_oidc_authenticator(config) is oidc


@pytest.mark.parametrize(
    "claim,value", [("token_type", 42), ("exp", True), ("nbf", True)]
)
def test_malformed_token_claims(oidc_client, provider, claim, value):
    provider["claims"][claim] = value
    assert bearer(oidc_client).status_code == 401


@pytest.mark.parametrize("actor", [None, "member", "maintainer", "owner"])
@pytest.mark.parametrize("target", [None, "member", "maintainer", "owner"])
def test_role_removal_respects_hierarchy(actor, target):
    rules = Rules.__new__(Rules)
    rules.assert_user = lambda: b"user"
    rules.has_server_roles = lambda user_id, roles: actor in roles
    allowed = actor == "owner" or (actor == "maintainer" and target in (None, "member"))
    if allowed:
        rules.assert_assign_user_role(None, target)
    else:
        with pytest.raises(HTTPException):
            rules.assert_assign_user_role(None, target)


@pytest.mark.parametrize(
    "role,expected", [(None, 403), ("member", 201), ("maintainer", 201), ("owner", 201)]
)
def test_bearer_channel_creation(oidc_client, provider, role, expected):
    provider["claims"]["resource_access"]["quetz"]["roles"] = [role] if role else []
    response = oidc_client.post(
        "/api/channels",
        json={"name": "oidc-channel", "private": False},
        headers={"Authorization": "Bearer access-token"},
    )
    assert response.status_code == expected, response.text


@pytest.mark.parametrize(
    "role,expected", [(None, 403), ("member", 403), ("maintainer", 200), ("owner", 200)]
)
def test_bearer_access_to_private_channels(
    oidc_client, provider, public_channel, db, role, expected
):
    provider["claims"]["resource_access"]["quetz"]["roles"] = [role] if role else []
    public_channel.private = True
    db.commit()
    response = bearer(oidc_client, f"/api/channels/{public_channel.name}")
    assert response.status_code == expected, response.text


def test_browser_rejects_invalid_signature(oidc_client, provider, db):
    state = login(oidc_client, provider)
    provider["invalid_signature"] = True
    response = oidc_client.get(
        "/auth/oidc/authorize",
        params={"code": "valid", "state": state},
        follow_redirects=False,
    )
    assert response.status_code == 401, response.text
    assert not db.query(User).filter_by(username="alice").count()


def test_encrypted_session_rejects_tampering(oidc):
    with pytest.raises(HTTPException) as error:
        oidc.session_token("oidc1.invalid")
    assert error.value.status_code == 401
