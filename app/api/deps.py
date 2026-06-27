"""
FastAPI dependencies — reusable building blocks injected into route handlers.

Bonus 1: get_org_id()  — extracts tenant from X-Org-Id header
Bonus 2: require_admin() / require_reader() — RBAC enforcement

Usage in a route:
    from app.api.deps import get_db, require_admin, get_org_id

    @router.post("/assets", dependencies=[Depends(require_admin)])
    async def create_asset(
        org_id: str = Depends(get_org_id),
        db: AsyncSession = Depends(get_db),
    ):
        ...
"""

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.api_key import ApiKey, Role
from app.services.auth_service import verify_api_key

# ── API Key header extractor ──────────────────────────────────────────────────
#
# auto_error=False: we handle the missing-key error ourselves for better messages
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# ── Bonus 1: Multi-tenant org extraction ─────────────────────────────────────

async def get_org_id(
    x_org_id: str | None = Header(None, alias="X-Org-Id"),
) -> str:
    """
    Extract the organization ID from the X-Org-Id request header.

    Defaults to "default" if the header is absent so existing callers
    without multi-tenancy awareness still work.

    Header format: X-Org-Id: acme-corp
    """
    org = (x_org_id or "").strip()
    if not org:
        return settings.DEFAULT_ORG_ID
    # Basic slug validation — prevent injection via header
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    if not all(c in allowed for c in org.lower()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Org-Id may only contain letters, numbers, hyphens, and underscores.",
        )
    return org.lower()


# ── Bonus 2: RBAC — key verification helpers ─────────────────────────────────

async def _get_current_key(
    raw_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """
    Internal dependency: look up and verify the API key from the header.

    Falls back to the legacy .env API_KEY for backwards compatibility —
    treated as an admin key for the "default" org.
    """
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "unauthorized",
                "message": "X-API-Key header is required.",
            },
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Legacy fallback: the .env API_KEY acts as a default-org admin key
    if raw_key == settings.API_KEY:
        # Return a synthetic key object (not in DB) for backwards compat
        return ApiKey(
            label="legacy-env-key",
            key_hash="",
            role=Role.ADMIN,
            organization_id=settings.DEFAULT_ORG_ID,
            is_active=True,
        )

    # New path: look up in ApiKey table
    key = await verify_api_key(db, raw_key)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "unauthorized",
                "message": "Invalid or revoked API key.",
            },
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return key


async def require_admin(
    key: ApiKey = Depends(_get_current_key),
) -> ApiKey:
    """
    Dependency: requires an active API key with admin role.
    Use on write endpoints (POST, PATCH, DELETE).
    """
    if key.role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "forbidden",
                "message": "This endpoint requires admin role.",
            },
        )
    return key


async def require_reader(
    key: ApiKey = Depends(_get_current_key),
) -> ApiKey:
    """
    Dependency: requires any active API key (admin or reader).
    Use on read endpoints (GET).
    """
    # Both admin and reader are allowed — just need a valid key
    return key


# Re-export so route files have a single import source
__all__ = [
    "get_db",
    "get_org_id",
    "require_admin",
    "require_reader",
    "AsyncSession",
    "Depends",
]
