"""
Pydantic schemas — the contract between the API and the outside world.

Rule: ORM models talk to the database. Schemas talk to API users.
They look similar but serve completely different purposes.

Import flow:
  HTTP Request JSON --> AssetImport (validate input)
  ORM Asset object  --> AssetResponse (format output)
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.asset import AssetSource, AssetStatus, AssetType


# ── Import schemas (what the API user sends us) ───────────────────────────────

class RelationshipImport(BaseModel):
    """
    A relationship declaration inside a bulk import.
    Instead of requiring the target's UUID (which the user doesn't know yet),
    we identify the target by its type + value — the natural key.
    """
    target_type: AssetType
    target_value: str
    relationship_type: str = Field(
        ...,
        examples=["subdomain_of", "resolves_to", "runs_on", "secured_by", "uses"],
    )


class AssetImport(BaseModel):
    """
    Schema for a single asset in a bulk import request.
    All fields except type and value have sensible defaults.
    """
    type: AssetType
    value: str = Field(..., min_length=1, max_length=2048)
    status: AssetStatus = AssetStatus.ACTIVE
    source: AssetSource = AssetSource.IMPORT
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    relationships: list[RelationshipImport] = Field(default_factory=list)

    @field_validator("value")
    @classmethod
    def normalize_value(cls, v: str) -> str:
        """
        Normalize asset values before storing.
        Strips whitespace and lowercases the value so that:
          "  API.Example.COM  " and "api.example.com" are treated as the same asset.
        """
        return v.strip().lower()

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, v: list[str]) -> list[str]:
        """Strip and lowercase all tags for consistency."""
        return [tag.strip().lower() for tag in v if tag.strip()]


class BulkImportRequest(BaseModel):
    """
    The top-level request body for POST /api/v1/assets/import.
    Accepts 1 to 1000 assets in a single call.
    """
    assets: list[AssetImport] = Field(..., min_length=1, max_length=1000)


# ── Response schemas (what we send back to the API user) ─────────────────────

class RelationshipResponse(BaseModel):
    """Response shape for a single relationship."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID
    relationship_type: str
    created_at: datetime


class AssetResponse(BaseModel):
    """
    Response shape for a single asset.

    Note the `metadata` field: in the ORM model the column is named
    `asset_metadata` (to avoid clashing with SQLAlchemy internals).
    We use a custom from_orm() to remap it back to `metadata` in the API.
    """
    id: uuid.UUID
    type: AssetType
    value: str
    status: AssetStatus
    first_seen: datetime
    last_seen: datetime
    source: AssetSource
    tags: list[str]
    metadata: dict[str, Any]

    @classmethod
    def from_orm(cls, asset: Any) -> "AssetResponse":
        """
        Manually maps an ORM Asset object to this schema.
        Handles the asset_metadata → metadata rename transparently.
        """
        return cls(
            id=asset.id,
            type=asset.type,
            value=asset.value,
            status=asset.status,
            first_seen=asset.first_seen,
            last_seen=asset.last_seen,
            source=asset.source,
            tags=asset.tags or [],
            metadata=asset.asset_metadata or {},
        )


class ImportError(BaseModel):
    """Describes one asset that failed during bulk import."""
    index: int          # position in the original request list (0-based)
    value: str          # the asset value that failed
    error: str          # human-readable reason


class BulkImportResponse(BaseModel):
    """
    Summary returned after POST /api/v1/assets/import completes.
    Partial success is allowed: some assets can succeed while others fail.
    """
    created: int                    # new assets inserted
    updated: int                    # existing assets updated (dedup hit)
    errors: list[ImportError]       # assets that failed with reasons
    assets: list[AssetResponse]     # all successfully processed assets


class AssetListResponse(BaseModel):
    """Paginated list of assets returned by GET /api/v1/assets."""
    total: int
    page: int
    page_size: int
    assets: list[AssetResponse]