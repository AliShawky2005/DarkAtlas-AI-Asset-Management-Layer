"""
Tests for Pydantic schema validation and normalization.

Again — pure Python, no database needed.
We test that our schemas correctly validate and normalize input
before it ever reaches the database.
"""

import pytest
from pydantic import ValidationError

from app.models.asset import AssetStatus, AssetType
from app.schemas.asset import AssetImport, BulkImportRequest


# ── Value normalization ───────────────────────────────────────────────────────

def test_value_is_lowercased():
    """Asset values must be stored lowercase regardless of input case."""
    asset = AssetImport(type=AssetType.DOMAIN, value="EXAMPLE.COM")
    assert asset.value == "example.com"


def test_value_whitespace_stripped():
    """Leading and trailing whitespace must be removed from asset values."""
    asset = AssetImport(type=AssetType.DOMAIN, value="  example.com  ")
    assert asset.value == "example.com"


def test_value_combined_normalization():
    """Both uppercase and whitespace should be normalized together."""
    asset = AssetImport(type=AssetType.SUBDOMAIN, value="  API.EXAMPLE.COM  ")
    assert asset.value == "api.example.com"


def test_empty_value_rejected():
    """An empty asset value must be rejected with a validation error."""
    with pytest.raises(ValidationError):
        AssetImport(type=AssetType.DOMAIN, value="")


def test_value_too_long_rejected():
    """A value exceeding 2048 characters must be rejected."""
    with pytest.raises(ValidationError):
        AssetImport(type=AssetType.DOMAIN, value="a" * 2049)


# ── Tag normalization ─────────────────────────────────────────────────────────

def test_tags_lowercased():
    """Tags must be stored lowercase."""
    asset = AssetImport(type=AssetType.DOMAIN, value="example.com",
                        tags=["Production", "CRITICAL"])
    assert "production" in asset.tags
    assert "critical" in asset.tags


def test_empty_tags_filtered_out():
    """Empty strings and whitespace-only strings must be removed from tags."""
    asset = AssetImport(type=AssetType.DOMAIN, value="example.com",
                        tags=["", "  ", "valid-tag"])
    assert "" not in asset.tags
    assert "valid-tag" in asset.tags
    assert len([t for t in asset.tags if not t.strip()]) == 0


def test_tag_whitespace_stripped():
    """Whitespace inside tag values must be stripped."""
    asset = AssetImport(type=AssetType.DOMAIN, value="example.com",
                        tags=["  production  "])
    assert "production" in asset.tags


# ── Defaults ──────────────────────────────────────────────────────────────────

def test_default_status_is_active():
    """When status is not provided, it must default to 'active'."""
    asset = AssetImport(type=AssetType.DOMAIN, value="example.com")
    assert asset.status == AssetStatus.ACTIVE


def test_default_source_is_import():
    """When source is not provided, it must default to 'import'."""
    from app.models.asset import AssetSource
    asset = AssetImport(type=AssetType.DOMAIN, value="example.com")
    assert asset.source == AssetSource.IMPORT


def test_default_tags_is_empty_list():
    """When tags are not provided, they must default to an empty list."""
    asset = AssetImport(type=AssetType.DOMAIN, value="example.com")
    assert asset.tags == []


def test_default_metadata_is_empty_dict():
    """When metadata is not provided, it must default to an empty dict."""
    asset = AssetImport(type=AssetType.DOMAIN, value="example.com")
    assert asset.metadata == {}


# ── Type validation ───────────────────────────────────────────────────────────

def test_invalid_type_rejected():
    """An asset type not in the allowed enum must be rejected."""
    with pytest.raises(ValidationError):
        AssetImport(type="invalid_type", value="example.com")


def test_invalid_status_rejected():
    """An asset status not in the allowed enum must be rejected."""
    with pytest.raises(ValidationError):
        AssetImport(type=AssetType.DOMAIN, value="example.com",
                    status="expired")  # valid in English but not our enum


# ── Bulk import validation ────────────────────────────────────────────────────

def test_bulk_import_empty_list_rejected():
    """A bulk import request with zero assets must be rejected."""
    with pytest.raises(ValidationError):
        BulkImportRequest(assets=[])


def test_bulk_import_single_asset_accepted():
    """A bulk import with one asset must be accepted."""
    req = BulkImportRequest(assets=[
        AssetImport(type=AssetType.DOMAIN, value="example.com")
    ])
    assert len(req.assets) == 1


def test_bulk_import_list_too_large_rejected():
    """A bulk import exceeding 1000 assets must be rejected."""
    with pytest.raises(ValidationError):
        BulkImportRequest(assets=[
            AssetImport(type=AssetType.DOMAIN, value=f"domain{i}.com")
            for i in range(1001)
        ])