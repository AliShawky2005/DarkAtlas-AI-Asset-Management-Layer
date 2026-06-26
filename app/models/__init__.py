# Import all models here so that:
# 1. `Base.metadata.create_all` in main.py can see every table
# 2. Alembic's autogenerate can discover all models automatically
#
# If you define a new model and forget to import it here,
# its table will never be created. This is a common gotcha.
from app.models.asset import Asset, AssetRelationship, AssetType, AssetStatus, AssetSource

__all__ = [
    "Asset",
    "AssetRelationship",
    "AssetType",
    "AssetStatus",
    "AssetSource",
]