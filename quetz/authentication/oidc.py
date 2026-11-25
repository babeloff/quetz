"""OIDC login and authoritative server roles from validated access tokens."""

import base64
import hashlib
import json
import math
import re
import time
from urllib.parse import urlsplit

import httpx
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from authlib.jose.errors import JoseError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request
from joserfc.errors import JoseError as JOSEError

from quetz.config import Config
from quetz.dao import Dao
from quetz.deps import get_config, get_dao
from quetz.errors import ConfigError

from . import auth_dao
from .base import BaseAuthenticationHandlers
from .oauth2 import OAuthAuthenticator


# tag::oidc-authentication[]
class OIDCHandlers(BaseAuthenticationHandlers):
    authorize_methods = ["GET"]

    async def enabled(self, config: Config = Depends(get_config)):
        return config.configured_section("oidc")

    async def login(self, request: Request, config: Config = Depends(get_config)):
        auth = get_oidc_authenticator(config)
        if auth is None:
            raise HTTPException(404, "OIDC is not configured")
        await auth.metadata()
        redirect_uri = request.url_for("authorize_oidc")
        return await auth.client.authorize_redirect(request, str(redirect_uri))

    async def authorize(
        self,
        request: Request,
        dao: Dao = Depends(get_dao),
        config: Config = Depends(get_config),
    ):
        auth = get_oidc_authenticator(config)
        if auth is None:
            raise HTTPException(404, "OIDC is not configured")
        return await BaseAuthenticationHandlers.authorize(
            auth.handler, request, dao, config
        )


class OIDCAuthenticator(OAuthAuthenticator):
    provider = "oidc"
    handler_cls = OIDCHandlers
    scope = "openid profile email"
    sync_roles = True

    def __init__(self, config, client_kwargs=None, provider=None, app=None):
        self.oauth = OAuth()
        self._metadata = None
        self._transport = (client_kwargs or {}).get("transport")
        self.client_kwargs = {"code_challenge_method": "S256"}
        super().__init__(config, client_kwargs, provider, app)

    def configure(self, config):
        super().configure(config)
        self.config = config
        self.is_enabled = config.configured_section("oidc")
        if not self.is_enabled:
            return
        self.issuer = config.oidc_issuer
        self.client_id = config.oidc_client_id
        self.client_secret = config.oidc_client_secret
        self.only = config.oidc_only
        self.audience = config.oidc_audience or self.client_id
        self._check_url(self.issuer, ConfigError)
        if not self.client_id or not self.client_secret:
            raise ConfigError("OIDC client_id and client_secret must not be empty")
        self.server_metadata_url = (
            self.issuer.rstrip("/") + "/.well-known/openid-configuration"
        )
        self.roles_claim = [
            self.client_id if p == "{client_id}" else p for p in config.oidc_roles_claim
        ]
        if not self.roles_claim or not all(
            isinstance(p, str) and p for p in self.roles_claim
        ):
            raise ConfigError("oidc.roles_claim must be a nonempty list of claim names")
        self.role_mapping = {
            "owner": config.oidc_owner_role,
            "maintainer": config.oidc_maintainer_role,
            "member": config.oidc_member_role,
        }
        if len(set(self.role_mapping.values())) != 3 or not all(
            self.role_mapping.values()
        ):
            raise ConfigError("OIDC role mappings must be distinct, nonempty names")
        key = hashlib.sha256(
            b"quetz-oidc-session-v1\0" + config.session_secret.encode()
        ).digest()
        self._cipher = Fernet(base64.urlsafe_b64encode(key))
        self.default_role = None
        self.create_default_channel = False

    def _check_url(self, url, error=ValueError):
        if not isinstance(url, str):
            raise error("OIDC endpoints must be URLs")
        parsed = urlsplit(url)
        allowed = (
            ("https", "http") if self.config.oidc_allow_insecure_http else ("https",)
        )
        if (
            parsed.scheme not in allowed
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise error(
                "OIDC requires trusted HTTPS URLs without credentials or fragments"
            )

    async def metadata(self):
        if self._metadata is None:
            try:
                metadata = await self.client.load_server_metadata()
                if metadata.get("issuer") != self.issuer:
                    raise ValueError("Issuer mismatch")
                for key in (
                    "authorization_endpoint",
                    "token_endpoint",
                    "jwks_uri",
                    "introspection_endpoint",
                ):
                    self._check_url(metadata.get(key))
                algorithms = set(
                    metadata.get("id_token_signing_alg_values_supported", [])
                )
                allowed = algorithms & {
                    "RS256",
                    "RS384",
                    "RS512",
                    "PS256",
                    "PS384",
                    "PS512",
                    "ES256",
                    "ES384",
                    "ES512",
                    "EdDSA",
                }
                if not allowed:
                    raise ValueError("No asymmetric signing algorithm")
                metadata["id_token_signing_alg_values_supported"] = sorted(allowed)
                self.client.server_metadata.update(metadata)
                self._metadata = metadata
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                raise HTTPException(
                    503, "OIDC provider discovery is unavailable or invalid"
                ) from exc
        return self._metadata

    def role_from_claims(self, claims):
        roles = claims
        for part in self.roles_claim:
            if not isinstance(roles, dict):
                raise HTTPException(401, "Invalid OIDC role claims")
            roles = roles.get(part, [])
            if roles == []:
                break
        if not isinstance(roles, list) or not all(
            isinstance(role, str) for role in roles
        ):
            raise HTTPException(401, "Invalid OIDC role claims")
        return next(
            (role for role, external in self.role_mapping.items() if external in roles),
            None,
        )

    async def introspect(self, access_token):
        if not isinstance(access_token, str) or not access_token:
            raise HTTPException(
                401, "Invalid OIDC access token", headers={"WWW-Authenticate": "Bearer"}
            )
        metadata = await self.metadata()
        try:
            async with httpx.AsyncClient(
                timeout=10, follow_redirects=False, transport=self._transport
            ) as client:
                response = await client.post(
                    metadata["introspection_endpoint"],
                    auth=(self.client_id, self.client_secret),
                    data={"token": access_token, "token_type_hint": "access_token"},
                )
                response.raise_for_status()
                claims = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "OIDC token introspection is unavailable") from exc
        now = time.time()
        if not isinstance(claims, dict):
            raise HTTPException(401, "Invalid OIDC access token")
        audience = claims.get("aud")
        audience = [audience] if isinstance(audience, str) else audience
        expiry = claims.get("exp")
        not_before = claims.get("nbf", 0)
        token_type = claims.get("token_type")
        if (
            claims.get("active") is not True
            or claims.get("iss") != self.issuer
            or not isinstance(claims.get("sub"), str)
            or not claims["sub"]
            or not isinstance(audience, list)
            or not all(isinstance(a, str) for a in audience)
            or self.audience not in audience
            or type(expiry) not in (int, float)
            or not math.isfinite(expiry)
            or expiry <= now
            or type(not_before) not in (int, float)
            or not math.isfinite(not_before)
            or not_before > now
            or not isinstance(token_type, str)
            or token_type.lower() != "bearer"
        ):
            raise HTTPException(
                401, "Invalid OIDC access token", headers={"WWW-Authenticate": "Bearer"}
            )
        self.role_from_claims(claims)
        return claims

    def profile(self, claims):
        username = claims.get("preferred_username", claims["sub"])
        if not isinstance(username, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,254}", username
        ):
            raise HTTPException(401, "Invalid OIDC username")
        return {
            "id": json.dumps([self.issuer, claims["sub"]], separators=(",", ":")),
            "login": username,
            "name": claims.get("name", username),
            "avatar_url": "",
            "emails": [],
        }

    def sync_user(self, dao, claims):
        return auth_dao.get_user_by_identity(
            dao,
            self.provider,
            self.profile(claims),
            self.config,
            self.role_from_claims(claims),
            sync_role=True,
        )

    def session_token(self, value):
        try:
            if not isinstance(value, str) or not value.startswith("oidc1."):
                raise ValueError("Missing encrypted token")
            payload = json.loads(self._cipher.decrypt(value[6:].encode()))
            if (
                payload["issuer"] != self.issuer
                or payload["client_id"] != self.client_id
            ):
                raise ValueError("Session issuer/client mismatch")
            return payload
        except (InvalidToken, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(401, "Invalid OIDC session") from exc

    async def authenticate(self, request, data=None, dao=None, config=None):
        await self.metadata()
        try:
            token = await self.client.authorize_access_token(
                request,
                claims_options={"iss": {"essential": True, "value": self.issuer}},
                leeway=0,
            )
            identity = token.get("userinfo")
            if (
                not token.get("id_token")
                or not identity
                or identity.get("iss") != self.issuer
            ):
                raise ValueError("Missing validated ID token")
            claims = await self.introspect(token.get("access_token"))
            if identity.get("sub") != claims["sub"]:
                raise ValueError("ID/access token subject mismatch")
        except (
            OAuthError,
            JoseError,
            JOSEError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            raise HTTPException(401, "OIDC login failed") from exc
        request.state.oidc_claims = claims
        payload = json.dumps(
            {
                "access_token": token["access_token"],
                "sub": claims["sub"],
                "issuer": self.issuer,
                "client_id": self.client_id,
            }
        )
        encrypted = "oidc1." + self._cipher.encrypt(payload.encode()).decode()
        profile = self.profile(claims)
        return {
            "username": profile["login"],
            "profile": profile,
            "auth_state": {"token": encrypted},
        }

    async def user_role(self, request, profile):
        return self.role_from_claims(request.state.oidc_claims)

    async def user_channels(self, request, profile):
        return None

    async def validate_token(self, token):
        try:
            payload = self.session_token(token)
            claims = await self.introspect(payload["access_token"])
            return claims["sub"] == payload["sub"]
        except HTTPException:
            return False


def get_oidc_authenticator(config):
    if not config.configured_section("oidc"):
        return None
    if not hasattr(config, "_oidc_authenticator"):
        config._oidc_authenticator = OIDCAuthenticator(config)
    return config._oidc_authenticator


# end::oidc-authentication[]
