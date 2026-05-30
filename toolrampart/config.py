from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .auth import (
    APIKeyAuthenticator,
    ChainedAuthenticator,
    HashedAPIKeyAuthenticator,
    JWKSAuthenticator,
    JWTAuthenticator,
    Principal,
)
from .core import ToolRampart
from .storage import create_audit_store, create_rate_limit_store
from .telemetry import Telemetry


class APIKeyConfig(BaseModel):
    actor: str
    scopes: list[str] = Field(default_factory=list)


class HashedAPIKeyConfig(BaseModel):
    actor: str
    scopes: list[str] = Field(default_factory=list)
    hash: str
    active: bool = True


class AuthConfig(BaseModel):
    required: bool = False
    trust_headers: bool = False
    api_keys: dict[str, APIKeyConfig] = Field(default_factory=dict)
    hashed_api_keys: dict[str, HashedAPIKeyConfig] = Field(default_factory=dict)
    jwt_secret: str | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_jwks_url: str | None = None
    jwt_algorithms: list[str] = Field(default_factory=lambda: ["RS256", "ES256"])


class ExecutionConfig(BaseModel):
    timeout_seconds: float | None = 30
    max_retries: int = 0


class StorageConfig(BaseModel):
    audit_path: str | None = None
    storage_url: str | None = None
    redis_url: str | None = None
    retention_days: int | None = 90


class TelemetryConfig(BaseModel):
    enabled: bool = True
    service_name: str = "toolrampart"


class ToolRampartConfig(BaseModel):
    auth: AuthConfig = Field(default_factory=AuthConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)


def load_config(path: str | Path = "toolrampart.toml") -> ToolRampartConfig:
    config_path = Path(path)
    data: dict[str, Any] = {}
    if config_path.exists():
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))

    config = ToolRampartConfig.model_validate(data)
    return _apply_env_overrides(config)


def create_rampart_from_config(config: ToolRampartConfig) -> ToolRampart:
    audit_log = create_audit_store(config.storage.storage_url, config.storage.audit_path)
    rate_limiter = create_rate_limit_store(config.storage.redis_url)
    return ToolRampart(
        audit_log=audit_log,
        rate_limiter=rate_limiter,
        execution_timeout_seconds=config.execution.timeout_seconds,
        max_retries=config.execution.max_retries,
        telemetry=Telemetry(
            enabled=config.telemetry.enabled,
            service_name=config.telemetry.service_name,
        ),
    )


def authenticator_from_config(config: ToolRampartConfig) -> ChainedAuthenticator | None:
    authenticators = []
    if config.auth.api_keys:
        authenticators.append(
            APIKeyAuthenticator(
                {
                    key: Principal(actor=value.actor, scopes=value.scopes)
                    for key, value in config.auth.api_keys.items()
                }
            )
        )
    if config.auth.hashed_api_keys:
        authenticators.append(
            HashedAPIKeyAuthenticator(
                {
                    key_id: {
                        "actor": value.actor,
                        "scopes": value.scopes,
                        "hash": value.hash,
                        "active": value.active,
                    }
                    for key_id, value in config.auth.hashed_api_keys.items()
                }
            )
        )
    if config.auth.jwt_secret:
        authenticators.append(
            JWTAuthenticator(
                secret=config.auth.jwt_secret,
                issuer=config.auth.jwt_issuer,
                audience=config.auth.jwt_audience,
            )
        )
    if config.auth.jwt_jwks_url:
        authenticators.append(
            JWKSAuthenticator(
                jwks_url=config.auth.jwt_jwks_url,
                issuer=config.auth.jwt_issuer,
                audience=config.auth.jwt_audience,
                algorithms=config.auth.jwt_algorithms,
            )
        )
    if not authenticators:
        return None
    return ChainedAuthenticator(*authenticators)


def _apply_env_overrides(config: ToolRampartConfig) -> ToolRampartConfig:
    data = config.model_dump()
    if os.getenv("TOOLRAMPART_AUDIT_PATH"):
        data["storage"]["audit_path"] = os.environ["TOOLRAMPART_AUDIT_PATH"]
    if os.getenv("TOOLRAMPART_STORAGE_URL"):
        data["storage"]["storage_url"] = os.environ["TOOLRAMPART_STORAGE_URL"]
    if os.getenv("TOOLRAMPART_REDIS_URL"):
        data["storage"]["redis_url"] = os.environ["TOOLRAMPART_REDIS_URL"]
    if os.getenv("TOOLRAMPART_JWT_SECRET"):
        data["auth"]["jwt_secret"] = os.environ["TOOLRAMPART_JWT_SECRET"]
    if os.getenv("TOOLRAMPART_TELEMETRY_ENABLED"):
        data["telemetry"]["enabled"] = os.environ["TOOLRAMPART_TELEMETRY_ENABLED"].lower() in {
            "1",
            "true",
            "yes",
        }
    return ToolRampartConfig.model_validate(data)
