"""
Asset service — all database operations live here.

Routes call this service. The service talks to the database.
This separation means:
  - Routes stay thin (just HTTP concerns)
  - Business logic is testable without HTTP
  - Database logic is reusable across multiple routes
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset, AssetRelationship, AssetType, AssetStatus
from app.schemas.asset import (
    AssetImport,
    AssetListResponse,
    AssetResponse,
    BulkImportRequest,
    BulkImportResponse,
    ImportError,
)


# ── Bulk import with deduplication ────────────────────────────────────────────

async def bulk_import_assets(
    db: AsyncSession,
    request: BulkImportRequest,
) -> BulkImportResponse:
    """
    Import up to 1000 assets in one call.

    Deduplication strategy:
      - Natural key: (type, value)
      - If asset exists → UPDATE last_seen, merge tags and metadata
      - If asset is new → INSERT with first_seen = last_seen = now
      - Relationships are upserted the same way

    Partial success: if one asset fails, others still succeed.
    All errors are collected and returned in the response.
    """
    created = 0
    updated = 0
    errors: list[ImportError] = []
    processed_assets: list[Asset] = []

    for index, asset_data in enumerate(request.assets):
        try:
            asset, was_created = await _upsert_asset(db, asset_data)
            processed_assets.append(asset)
            if was_created:
                created += 1
            else:
                updated += 1
        except Exception as e:
            # Collect the error but continue processing the rest
            errors.append(ImportError(
                index=index,
                value=asset_data.value,
                error=str(e),
            ))

    # Now handle relationships (after all assets are saved so FKs exist)
    for index, asset_data in enumerate(request.assets):
        if not asset_data.relationships:
            continue
        # Find the source asset we just saved
        source = await _get_asset_by_type_value(db, asset_data.type, asset_data.value)
        if not source:
            continue
        for rel in asset_data.relationships:
            try:
                target = await _get_asset_by_type_value(
                    db, rel.target_type, rel.target_value
                )
                if target:
                    await _upsert_relationship(
                        db, source.id, target.id, rel.relationship_type
                    )
            except Exception as e:
                errors.append(ImportError(
                    index=index,
                    value=f"{asset_data.value} -> {rel.target_value}",
                    error=f"Relationship error: {e}",
                ))

    return BulkImportResponse(
        created=created,
        updated=updated,
        errors=errors,
        assets=[AssetResponse.from_orm(a) for a in processed_assets],
    )


async def _upsert_asset(
    db: AsyncSession,
    data: AssetImport,
) -> tuple[Asset, bool]:
    """
    Insert or update a single asset.
    Returns (asset, was_created).

    Uses PostgreSQL's INSERT ... ON CONFLICT DO UPDATE.
    This is atomic — no race conditions even under concurrent imports.
    """
    now = datetime.now(timezone.utc)

    # Check if asset already exists
    existing = await _get_asset_by_type_value(db, data.type, data.value)

    if existing:
        # ── UPDATE path ───────────────────────────────────────────────────
        # Update last_seen timestamp
        existing.last_seen = now

        # Merge tags: combine existing + new, deduplicate, keep sorted
        merged_tags = sorted(set(existing.tags or []) | set(data.tags))
        existing.tags = merged_tags

        # Merge metadata: new values override existing ones for the same key
        merged_metadata = {**(existing.asset_metadata or {}), **data.metadata}
        existing.asset_metadata = merged_metadata

        # Only update status if explicitly provided and different
        if data.status != existing.status:
            existing.status = data.status

        await db.flush()  # write to DB within this transaction
        return existing, False

    else:
        # ── INSERT path ───────────────────────────────────────────────────
        new_asset = Asset(
            type=data.type,
            value=data.value,
            status=data.status,
            source=data.source,
            tags=data.tags,
            asset_metadata=data.metadata,
            first_seen=now,
            last_seen=now,
        )
        db.add(new_asset)
        await db.flush()  # assigns the UUID and writes to DB
        return new_asset, True


async def _upsert_relationship(
    db: AsyncSession,
    source_id: Any,
    target_id: Any,
    relationship_type: str,
) -> AssetRelationship:
    """
    Insert a relationship if it doesn't exist yet.
    If it already exists, do nothing (idempotent).
    """
    # Check if it already exists
    stmt = select(AssetRelationship).where(
        AssetRelationship.source_id == source_id,
        AssetRelationship.target_id == target_id,
        AssetRelationship.relationship_type == relationship_type,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        return existing

    rel = AssetRelationship(
        source_id=source_id,
        target_id=target_id,
        relationship_type=relationship_type,
    )
    db.add(rel)
    await db.flush()
    return rel


async def _get_asset_by_type_value(
    db: AsyncSession,
    asset_type: AssetType,
    value: str,
) -> Asset | None:
    """Look up an asset by its natural key (type + value)."""
    stmt = select(Asset).where(
        Asset.type == asset_type,
        Asset.value == value.strip().lower(),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ── Query / list assets ───────────────────────────────────────────────────────

async def list_assets(
    db: AsyncSession,
    asset_type: AssetType | None = None,
    status: AssetStatus | None = None,
    tag: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> AssetListResponse:
    """
    Return a paginated, filtered list of assets.

    Filters:
      type   — exact match on asset type
      status — exact match on status
      tag    — asset must have this tag in its tags list
      search — partial match on the value field
    """
    # Build base query
    stmt = select(Asset)

    # Apply filters
    if asset_type:
        stmt = stmt.where(Asset.type == asset_type)
    if status:
        stmt = stmt.where(Asset.status == status)
    if search:
        # ilike = case-insensitive LIKE
        stmt = stmt.where(Asset.value.ilike(f"%{search}%"))
    if tag:
        # Cast JSON → JSONB to enable the @> (contains) operator in PostgreSQL
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import JSONB
        stmt = stmt.where(cast(Asset.tags, JSONB).contains([tag]))

    # Count total (for pagination metadata)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Apply pagination
    offset = (page - 1) * page_size
    stmt = stmt.order_by(Asset.last_seen.desc()).offset(offset).limit(page_size)

    result = await db.execute(stmt)
    assets = result.scalars().all()

    return AssetListResponse(
        total=total,
        page=page,
        page_size=page_size,
        assets=[AssetResponse.from_orm(a) for a in assets],
    )


async def get_asset_by_id(
    db: AsyncSession,
    asset_id: str,
) -> Asset | None:
    """Fetch a single asset by its UUID."""
    import uuid as uuid_lib
    try:
        uid = uuid_lib.UUID(str(asset_id))
    except ValueError:
        return None

    stmt = select(Asset).where(Asset.id == uid)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()