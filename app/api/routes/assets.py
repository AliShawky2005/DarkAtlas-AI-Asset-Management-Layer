"""
Asset routes — HTTP layer only.

Each route does three things:
  1. Validate input (Pydantic does this automatically)
  2. Call the service layer
  3. Return the response

No business logic lives here. No SQL lives here.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import AsyncSession, get_db, require_api_key
from app.models.asset import AssetStatus, AssetType
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
        "Existing assets (matched by type + value) are updated, not duplicated. "
        "Requires X-API-Key header."
    ),
    dependencies=[Depends(require_api_key)],  # auth enforced here
)
async def import_assets(
    request: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
) -> BulkImportResponse:
    """
    Bulk import endpoint — the main data ingestion route.

    Send a JSON body like:
    {
      "assets": [
        {
          "type": "domain",
          "value": "example.com",
          "tags": ["production"],
          "metadata": {},
          "relationships": []
        }
      ]
    }
    """
    return await bulk_import_assets(db, request)


@router.get(
    "",
    response_model=AssetListResponse,
    summary="List assets",
    description="Retrieve assets with optional filtering and pagination.",
)
async def get_assets(
    asset_type: AssetType | None = Query(None, alias="type", description="Filter by asset type"),
    status: AssetStatus | None = Query(None, description="Filter by status"),
    tag: str | None = Query(None, description="Filter by tag (exact match)"),
    search: str | None = Query(None, description="Search in asset value (partial match)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Results per page"),
    db: AsyncSession = Depends(get_db),
) -> AssetListResponse:
    return await list_assets(
        db,
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
) -> AssetResponse:
    asset = await get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset {asset_id} not found.",
        )
    return AssetResponse.from_orm(asset)