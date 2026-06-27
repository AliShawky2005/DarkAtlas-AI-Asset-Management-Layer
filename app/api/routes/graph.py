"""
Graph visualization routes — Bonus 3.

GET /api/v1/graph/data  — JSON {nodes, edges} for the current org
GET /graph              — self-contained HTML visualization page
"""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, FileResponse
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_org_id, require_reader
from app.models.api_key import ApiKey
from app.services.asset_service import get_graph_data

router = APIRouter()


@router.get(
    "/data",
    summary="Get graph data",
    description="Returns nodes and edges for the asset relationship graph, scoped to your org.",
)
async def graph_data(
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_reader),
) -> dict:
    return await get_graph_data(db, organization_id=org_id)


@router.get(
    "",
    response_class=HTMLResponse,
    summary="Asset relationship graph visualization",
    description="Interactive D3.js force-directed graph of all assets and their relationships.",
    include_in_schema=False,
)
async def graph_page():
    """Serve the self-contained graph.html visualization page."""
    html_path = Path(__file__).parent.parent.parent / "static" / "graph.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>graph.html not found</h1>", status_code=404)
