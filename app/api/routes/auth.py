"""
Auth / API key management routes — Bonus 2: RBAC.

Endpoints:
  POST   /api/v1/auth/keys           — create a new API key (admin)
  GET    /api/v1/auth/keys           — list API keys for my org (admin)
  DELETE /api/v1/auth/keys/{key_id}  — revoke a key (admin)
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_org_id, require_admin
from app.models.api_key import ApiKey, Role
from app.services.auth_service import create_api_key, get_keys_for_org, revoke_key

router = APIRouter()


# ── Request / response schemas ────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=128,
                       description="Human-readable label to identify this key",
                       examples=["ci-pipeline", "dashboard-readonly"])
    role: Role = Field(Role.READER, description="'admin' for full access, 'reader' for read-only")


class ApiKeyCreatedResponse(BaseModel):
    """Returned once on creation. The raw key is not stored and cannot be retrieved again."""
    id: uuid.UUID
    label: str
    role: str
    organization_id: str
    raw_key: str  # shown ONCE — save it immediately


class ApiKeyListItem(BaseModel):
    id: uuid.UUID
    label: str
    role: str
    organization_id: str
    is_active: bool


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create API key",
    description=(
        "Create a new API key for your organization.\n\n"
        "⚠️ The raw key is shown **once** in the response — save it immediately. "
        "It cannot be retrieved again.\n\n"
        "**Requires admin key.**"
    ),
)
async def create_key(
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_admin),
) -> ApiKeyCreatedResponse:
    key_obj, raw_key = await create_api_key(
        db,
        org_id=org_id,
        role=body.role,
        label=body.label,
    )
    return ApiKeyCreatedResponse(
        id=key_obj.id,
        label=key_obj.label,
        role=key_obj.role.value,
        organization_id=key_obj.organization_id,
        raw_key=raw_key,
    )


@router.get(
    "/keys",
    response_model=list[ApiKeyListItem],
    summary="List API keys",
    description="List all API keys for your organization. **Requires admin key.**",
)
async def list_keys(
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_admin),
) -> list[ApiKeyListItem]:
    keys = await get_keys_for_org(db, org_id)
    return [
        ApiKeyListItem(
            id=k.id,
            label=k.label,
            role=k.role.value,
            organization_id=k.organization_id,
            is_active=k.is_active,
        )
        for k in keys
    ]


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke API key",
    description="Deactivate an API key. The key will no longer be accepted. **Requires admin key.**",
)
async def revoke_key_endpoint(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_admin),
) -> None:
    revoked = await revoke_key(db, key_id, org_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Key {key_id} not found in your organization.",
        )
