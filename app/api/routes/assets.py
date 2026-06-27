"""
Asset routes — HTTP layer only. Bonus 1 + 2 applied.

Changes from v1:
  - org_id injected from X-Org-Id header (multi-tenancy)
  - require_admin on write ops, require_reader on reads (RBAC)
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import AsyncSession, get_db, get_org_id, require_admin, require_reader
from app.models.asset import AssetStatus, AssetType
from app.models.api_key import ApiKey
from app.schemas.asset import (
    AssetListResponse,
    AssetResponse,
    BulkImportRequest,
    BulkImportResponse,
)
from app.services.asset_service import (
    bulk_import_assets,
    get_asset_by_id,
    list_assets,
)

router = APIRouter()


@router.post(
    "/import",
    response_model=BulkImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk import assets",
    description=(
        "Import up to 1000 assets in one request. "
        "Existing assets (matched by type + value + org) are updated, not duplicated. "
        "**Requires admin role.**"
    ),
)
async def import_assets(
    request: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_admin),   # RBAC: admin only
) -> BulkImportResponse:
    return await bulk_import_assets(db, request, organization_id=org_id)


@router.get(
    "",
    response_model=AssetListResponse,
    summary="List assets",
    description="Retrieve assets with optional filtering and pagination. Requires any valid API key.",
)
async def get_assets(
    asset_type: AssetType | None = Query(None, alias="type", description="Filter by asset type"),
    status: AssetStatus | None = Query(None, description="Filter by status"),
    tag: str | None = Query(None, description="Filter by tag (exact match)"),
    search: str | None = Query(None, description="Search in asset value (partial match)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Results per page"),
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_reader),  # RBAC: reader or admin
) -> AssetListResponse:
    return await list_assets(
        db,
        organization_id=org_id,
        asset_type=asset_type,
        status=status,
        tag=tag,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{asset_id}",
    response_model=AssetResponse,
    summary="Get asset by ID",
)
async def get_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_reader),  # RBAC: reader or admin
) -> AssetResponse:
    asset = await get_asset_by_id(db, asset_id, organization_id=org_id)
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset {asset_id} not found.",
        )
    return AssetResponse.from_orm(asset)