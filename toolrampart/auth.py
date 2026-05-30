from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping
from typing import Any, Protocol

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, Field


class Principal(BaseModel):
    actor: str
    scopes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Authenticator(Protocol):
    def authenticate(self, headers: Mapping[str, str]) -> Principal | None: ...


class APIKeyAuthenticator:
    """Authenticate with Authorization: Bearer or X-ToolRampart-Key."""

    def __init__(self, keys: dict[str, Principal | dict[str, Any]]) -> None:
        self._keys = {
            key: value if isinstance(value, Principal) else Principal.model_validate(value)
            for key, value in keys.items()
        }

    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        token = _bearer_token(headers.get("authorization", ""))
        if not token:
            token = headers.get("x-toolrampart-key")
        if not token:
            return None
        return self._keys.get(token)


class HashedAPIKeyAuthenticator:
    """Authenticate API keys without storing plaintext keys."""

    def __init__(self, keys: dict[str, dict[str, Any]]) -> None:
        self._keys = keys

    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        token = _bearer_token(headers.get("authorization", ""))
        if not token:
            token = headers.get("x-toolrampart-key")
        if not token:
            return None

        preferred_key_id = headers.get("x-toolrampart-key-id")
        key_items = (
            [(preferred_key_id, self._keys[preferred_key_id])]
            if preferred_key_id in self._keys
            else list(self._keys.items())
        )
        for key_id, config in key_items:
            if config.get("active", True) is False:
                continue
            stored_hash = str(config["hash"])
            if verify_api_key(token, stored_hash):
                return Principal(
                    actor=str(config["actor"]),
                    scopes=list(config.get("scopes", [])),
                    metadata={"auth": "api_key", "key_id": key_id},
                )
        return None


class JWTAuthenticator:
    """Minimal HS256 JWT verifier for signed actors and scopes."""

    def __init__(
        self,
        *,
        secret: str,
        issuer: str | None = None,
        audience: str | None = None,
    ) -> None:
        self.secret = secret.encode("utf-8")
        self.issuer = issuer
        self.audience = audience

    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        token = _bearer_token(headers.get("authorization", ""))
        if not token:
            return None
        payload = verify_hs256_jwt(
            token,
            secret=self.secret,
            issuer=self.issuer,
            audience=self.audience,
        )
        scopes = payload.get("scopes", payload.get("scope", []))
        if isinstance(scopes, str):
            scopes = [scope for scope in scopes.split(" ") if scope]
        actor = str(payload.get("sub") or payload.get("actor") or "anonymous")
        return Principal(
            actor=actor,
            scopes=list(scopes),
            metadata={
                "auth": "jwt",
                "issuer": payload.get("iss"),
                "audience": payload.get("aud"),
            },
        )


class JWKSAuthenticator:
    """Verify RS256/ES256 JWTs using a JWKS URL or in-memory JWKS document."""

    def __init__(
        self,
        *,
        jwks_url: str | None = None,
        jwks: dict[str, Any] | None = None,
        issuer: str | None = None,
        audience: str | None = None,
        algorithms: list[str] | None = None,
    ) -> None:
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "JWKSAuthenticator requires PyJWT with crypto support: "
                "pip install 'pyjwt[crypto]'"
            ) from exc

        self._jwt = jwt
        self.jwks_url = jwks_url
        self.jwks = jwks
        self.issuer = issuer
        self.audience = audience
        self.algorithms = algorithms or ["RS256", "ES256"]
        self._jwk_client = jwt.PyJWKClient(jwks_url) if jwks_url else None

    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        token = _bearer_token(headers.get("authorization", ""))
        if not token:
            return None

        try:
            signing_key = self._signing_key(token)
            payload = self._jwt.decode(
                token,
                signing_key,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self.issuer,
            )
        except Exception as exc:
            raise HTTPException(status_code=401, detail="invalid JWT") from exc

        scopes = payload.get("scopes", payload.get("scope", []))
        if isinstance(scopes, str):
            scopes = [scope for scope in scopes.split(" ") if scope]
        actor = str(payload.get("sub") or payload.get("actor") or "anonymous")
        return Principal(
            actor=actor,
            scopes=list(scopes),
            metadata={
                "auth": "jwks",
                "issuer": payload.get("iss"),
                "audience": payload.get("aud"),
            },
        )

    def _signing_key(self, token: str) -> Any:
        if self._jwk_client is not None:
            return self._jwk_client.get_signing_key_from_jwt(token).key
        if not self.jwks:
            raise HTTPException(status_code=401, detail="missing JWKS configuration")
        header = self._jwt.get_unverified_header(token)
        key_id = header.get("kid")
        for jwk in self.jwks.get("keys", []):
            if jwk.get("kid") == key_id:
                return self._jwt.PyJWK.from_dict(jwk).key
        raise HTTPException(status_code=401, detail="unknown JWT key id")


class ChainedAuthenticator:
    def __init__(self, *authenticators: Authenticator) -> None:
        self.authenticators = authenticators

    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        for authenticator in self.authenticators:
            principal = authenticator.authenticate(headers)
            if principal is not None:
                return principal
        return None


def trusted_header_principal(headers: Mapping[str, str]) -> Principal | None:
    actor = headers.get("x-toolrampart-actor")
    if not actor:
        return None
    scopes = headers.get("x-toolrampart-scopes", "")
    return Principal(
        actor=actor,
        scopes=[scope.strip() for scope in scopes.split(",") if scope.strip()],
        metadata={"auth": "trusted_headers"},
    )


async def principal_from_request(
    request: Request,
    *,
    authenticator: Authenticator | None = None,
    trust_headers: bool = False,
    required: bool = False,
) -> Principal | None:
    headers = {key.lower(): value for key, value in request.headers.items()}

    principal: Principal | None = None
    if authenticator:
        principal = authenticator.authenticate(headers)
    if principal is None and trust_headers:
        principal = trusted_header_principal(headers)

    if required and principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid ToolRampart credentials",
        )
    return principal


def verify_hs256_jwt(
    token: str,
    *,
    secret: bytes,
    issuer: str | None = None,
    audience: str | None = None,
) -> dict[str, Any]:
    try:
        header_text, payload_text, signature_text = token.split(".")
        signing_input = f"{header_text}.{payload_text}".encode("ascii")
        header = _decode_json(header_text)
        payload = _decode_json(payload_text)
        signature = _decode_base64url(signature_text)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid JWT") from exc

    if header.get("alg") != "HS256":
        raise HTTPException(status_code=401, detail="unsupported JWT algorithm")

    expected = hmac.new(secret, signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="invalid JWT signature")

    now = int(time.time())
    if "exp" in payload and now >= int(payload["exp"]):
        raise HTTPException(status_code=401, detail="expired JWT")
    if "nbf" in payload and now < int(payload["nbf"]):
        raise HTTPException(status_code=401, detail="JWT is not active yet")
    if issuer and payload.get("iss") != issuer:
        raise HTTPException(status_code=401, detail="invalid JWT issuer")
    if audience:
        token_audience = payload.get("aud")
        audiences = token_audience if isinstance(token_audience, list) else [token_audience]
        if audience not in audiences:
            raise HTTPException(status_code=401, detail="invalid JWT audience")

    return payload


def sign_hs256_jwt(payload: dict[str, Any], *, secret: str, header: dict[str, Any] | None = None) -> str:
    jwt_header = {"typ": "JWT", "alg": "HS256", **(header or {})}
    header_text = _encode_base64url(json.dumps(jwt_header, separators=(",", ":")).encode("utf-8"))
    payload_text = _encode_base64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_text}.{payload_text}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_text}.{payload_text}.{_encode_base64url(signature)}"


def generate_api_key(prefix: str = "trp") -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str, *, iterations: int = 210_000, salt: str | None = None) -> str:
    key_salt = salt or secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        api_key.encode("utf-8"),
        key_salt.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${key_salt}${base64.urlsafe_b64encode(digest).decode('ascii')}"


def verify_api_key(api_key: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, digest_text = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hash_api_key(api_key, iterations=int(iterations_text), salt=salt)
    except Exception:
        return False
    return hmac.compare_digest(candidate, stored_hash)


def _bearer_token(value: str) -> str | None:
    prefix = "bearer "
    if value.lower().startswith(prefix):
        return value[len(prefix) :].strip()
    return None


def _decode_json(value: str) -> dict[str, Any]:
    return json.loads(_decode_base64url(value))


def _decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
