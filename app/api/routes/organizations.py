"""
Organization management routes — Bonus 1: Multi-tenancy.

Endpoints:
  POST /api/v1/orgs        — create a new organization (admin)
  GET  /api/v1/orgs        — list all organizations (admin)
  GET  /api/v1/orgs/{id}   — get one organization (admin)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.api_key import ApiKey
from app.models.organization import Organization

router = APIRouter()


class OrgCreate(BaseModel):
    id: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z0-9\-_]+$",
                    examples=["acme-corp", "buguard"])
    name: str = Field(..., min_length=1, max_length=256)


class OrgResponse(BaseModel):
    id: str
    name: str


@router.post(
    "",
    response_model=OrgResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create organization",
    description="Create a new tenant organization. **Requires admin key.**",
)
async def create_org(
    body: OrgCreate,
    db: AsyncSession = Depends(get_db),
    _key: ApiKey = Depends(require_admin),
) -> OrgResponse:
    # Check if org already exists
    stmt = select(Organization).where(Organization.id == body.id)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Organization '{body.id}' already exists.",
        )

    org = Organization(id=body.id, name=body.name)
    db.add(org)
    await db.flush()
    return OrgResponse(id=org.id, name=org.name)


@router.get(
    "",
    response_model=list[OrgResponse],
    summary="List organizations",
    description="List all organizations. **Requires admin key.**",
)
async def list_orgs(
    db: AsyncSession = Depends(get_db),
    _key: ApiKey = Depends(require_admin),
) -> list[OrgResponse]:
    result = await db.execute(select(Organization))
    orgs = result.scalars().all()
    return [OrgResponse(id=o.id, name=o.name) for o in orgs]


@router.get(
    "/{org_id}",
    response_model=OrgResponse,
    summary="Get organization by ID",
)
async def get_org(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    _key: ApiKey = Depends(require_admin),
) -> OrgResponse:
    stmt = select(Organization).where(Organization.id == org_id)
    org = (await db.execute(stmt)).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail=f"Organization '{org_id}' not found.")
    return OrgResponse(id=org.id, name=org.name)
