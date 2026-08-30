"""FastAPI authentication dependencies without secret-bearing logs or errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException

from core.config import load_runtime_config


@dataclass(frozen=True)
class TenantIdentity:
    tenant_id: Optional[str]
    authenticated: bool


@dataclass(frozen=True)
class ReviewerIdentity:
    reviewer_id: Optional[str]
    allowed_tenants: Optional[tuple[str, ...]]
    authenticated: bool


async def authenticate_tenant(
    api_key: Optional[str] = Header(default=None, alias="X-Sentinel-API-Key"),
) -> TenantIdentity:
    config = load_runtime_config()
    if not config.auth_enabled:
        return TenantIdentity(tenant_id=None, authenticated=False)
    tenant_id = config.tenant_api_keys.get(api_key or "")
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Valid tenant credentials are required")
    return TenantIdentity(tenant_id=tenant_id, authenticated=True)


async def authenticate_reviewer(
    reviewer_key: Optional[str] = Header(default=None, alias="X-Sentinel-Reviewer-Key"),
) -> ReviewerIdentity:
    config = load_runtime_config()
    if not config.auth_enabled:
        return ReviewerIdentity(
            reviewer_id=None, allowed_tenants=None, authenticated=False
        )
    credential = config.reviewer_api_keys.get(reviewer_key or "")
    if credential is None:
        raise HTTPException(status_code=401, detail="Valid reviewer credentials are required")
    return ReviewerIdentity(
        reviewer_id=credential.reviewer_id,
        allowed_tenants=credential.allowed_tenants,
        authenticated=True,
    )


def tenant_identity_or_local(value: object) -> TenantIdentity:
    """Keep direct offline calls compatible while FastAPI resolves dependencies."""
    if isinstance(value, TenantIdentity):
        return value
    return TenantIdentity(tenant_id=None, authenticated=False)


def reviewer_identity_or_local(value: object) -> ReviewerIdentity:
    if isinstance(value, ReviewerIdentity):
        return value
    return ReviewerIdentity(reviewer_id=None, allowed_tenants=None, authenticated=False)
