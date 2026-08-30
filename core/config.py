"""Validated runtime configuration for Phase 5 security and privacy controls."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


class ConfigurationError(RuntimeError):
    """Raised when security-sensitive runtime configuration is invalid."""


@dataclass(frozen=True)
class ReviewerCredential:
    reviewer_id: str
    allowed_tenants: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeConfig:
    auth_enabled: bool
    tenant_api_keys: dict[str, str]
    reviewer_api_keys: dict[str, ReviewerCredential]
    audit_content_mode: str
    cors_origins: tuple[str, ...]


def _boolean(name: str, default: str = "false") -> bool:
    raw = os.getenv(name, default).strip().lower()
    if raw not in {"true", "false"}:
        raise ConfigurationError(f"{name} must be true or false")
    return raw == "true"


def _json_object(name: str) -> dict:
    raw = os.getenv(name, "{}").strip() or "{}"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{name} must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"{name} must be a JSON object")
    return value


def load_runtime_config() -> RuntimeConfig:
    auth_enabled = _boolean("SENTINEL_AUTH_ENABLED")

    raw_tenants = _json_object("SENTINEL_TENANT_API_KEYS_JSON")
    if any(not isinstance(key, str) or not key or not isinstance(tenant, str) or not tenant
           for key, tenant in raw_tenants.items()):
        raise ConfigurationError(
            "SENTINEL_TENANT_API_KEYS_JSON must map non-empty keys to tenant IDs"
        )

    raw_reviewers = _json_object("SENTINEL_REVIEWER_API_KEYS_JSON")
    reviewers: dict[str, ReviewerCredential] = {}
    for key, value in raw_reviewers.items():
        if not isinstance(key, str) or not key or not isinstance(value, dict):
            raise ConfigurationError("SENTINEL_REVIEWER_API_KEYS_JSON has an invalid entry")
        reviewer_id = value.get("reviewer_id")
        allowed = value.get("allowed_tenants")
        if (
            not isinstance(reviewer_id, str) or not reviewer_id
            or not isinstance(allowed, list) or not allowed
            or any(not isinstance(tenant, str) or not tenant for tenant in allowed)
        ):
            raise ConfigurationError(
                "Each reviewer credential needs reviewer_id and non-empty allowed_tenants"
            )
        reviewers[key] = ReviewerCredential(reviewer_id, tuple(dict.fromkeys(allowed)))

    if auth_enabled and not raw_tenants:
        raise ConfigurationError(
            "SENTINEL_AUTH_ENABLED=true requires SENTINEL_TENANT_API_KEYS_JSON"
        )
    if auth_enabled and not reviewers:
        raise ConfigurationError(
            "SENTINEL_AUTH_ENABLED=true requires SENTINEL_REVIEWER_API_KEYS_JSON"
        )

    audit_mode = os.getenv("SENTINEL_AUDIT_CONTENT_MODE", "redacted").strip().lower()
    if audit_mode not in {"redacted", "metadata_only", "raw"}:
        raise ConfigurationError(
            "SENTINEL_AUDIT_CONTENT_MODE must be redacted, metadata_only, or raw"
        )

    raw_origins = os.getenv(
        "SENTINEL_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    )
    origins = tuple(dict.fromkeys(item.strip() for item in raw_origins.split(",") if item.strip()))
    if not origins or "*" in origins:
        raise ConfigurationError("SENTINEL_CORS_ORIGINS must list explicit origins")

    return RuntimeConfig(
        auth_enabled=auth_enabled,
        tenant_api_keys=dict(raw_tenants),
        reviewer_api_keys=reviewers,
        audit_content_mode=audit_mode,
        cors_origins=origins,
    )


def validate_runtime_config() -> RuntimeConfig:
    """Validate all Phase 5 configuration at application startup."""
    return load_runtime_config()
