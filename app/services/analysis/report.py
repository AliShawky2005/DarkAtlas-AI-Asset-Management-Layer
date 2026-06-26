"""
Phase 7 — Natural-Language Report Generation

Generates a complete written security report covering:
  1. Asset inventory summary (counts by type and status)
  2. Risk findings (from the rule engine)
  3. LLM-written executive narrative

The LLM receives structured facts and writes the report.
It never invents assets or findings not present in the data.
"""

from datetime import datetime, timezone
from typing import Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analysis.base import DARKATLAS_SYSTEM_PROMPT, get_llm, format_assets_for_prompt
from app.services.analysis.risk import score_assets
from app.services.asset_service import list_assets


# ── Response schema ───────────────────────────────────────────────────────────

class InventorySummary(BaseModel):
    total_assets: int
    by_type: dict       # {"domain": 2, "subdomain": 3, ...}
    by_status: dict     # {"active": 4, "stale": 1, ...}


class ReportResponse(BaseModel):
    generated_at: str
    scope: dict                   # what filters were applied
    inventory: InventorySummary
    risk_counts: dict
    report: str                   # the full LLM-written narrative


# ── Report prompt ─────────────────────────────────────────────────────────────

REPORT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", DARKATLAS_SYSTEM_PROMPT),
    ("human", """Generate a professional attack surface management report based on the data below.

INVENTORY:
{inventory_text}

ASSET DETAILS:
{asset_details}

RISK FINDINGS:
{risk_text}

Write a structured report with these sections:

## Executive Summary
2-3 sentences on overall posture and most critical finding.

## Asset Inventory
Summarize what assets exist and their distribution.

## Risk Analysis
Describe each risk finding with context. Be specific — name the assets and exact issues.

## Recommendations
List the top 3 prioritized actions the security team should take, ordered by urgency.

## Conclusion
One sentence on overall risk level and next step.

RULES:
- Only reference assets and findings explicitly provided above
- Be specific: name assets, cite metadata values, quote exact findings
- Do NOT invent vulnerabilities, assets, or recommendations not supported by the data
- Keep the report concise and actionable
"""),
])


# ── Inventory builder ─────────────────────────────────────────────────────────

def _build_inventory(assets: list[dict]) -> InventorySummary:
    """Count assets by type and status."""
    by_type: dict = {}
    by_status: dict = {}

    for asset in assets:
        t = asset.get("type", "unknown")
        s = asset.get("status", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        by_status[s] = by_status.get(s, 0) + 1

    return InventorySummary(
        total_assets=len(assets),
        by_type=by_type,
        by_status=by_status,
    )


def _format_inventory_text(inventory: InventorySummary) -> str:
    """Convert inventory counts to readable text for the prompt."""
    type_lines = "\n".join(
        f"  - {k}: {v}" for k, v in sorted(inventory.by_type.items())
    )
    status_lines = "\n".join(
        f"  - {k}: {v}" for k, v in sorted(inventory.by_status.items())
    )
    return (
        f"Total assets: {inventory.total_assets}\n"
        f"By type:\n{type_lines}\n"
        f"By status:\n{status_lines}"
    )


# ── Main function ─────────────────────────────────────────────────────────────

async def generate_report(
    db: AsyncSession,
    tag: Optional[str] = None,
    asset_type_filter: Optional[str] = None,
) -> ReportResponse:
    """
    Generate a full natural-language security report.

    Steps:
      1. Fetch all assets (optionally filtered)
      2. Build inventory statistics
      3. Run risk rule engine on all assets
      4. LLM writes the full report from the structured data
      5. Return report with metadata
    """
    from app.models.asset import AssetType as AT

    atype = None
    if asset_type_filter:
        try:
            atype = AT(asset_type_filter.strip().lower())
        except ValueError:
            pass

    # Fetch assets (up to 200)
    results = await list_assets(db, asset_type=atype, tag=tag, page=1, page_size=200)
    assets_data = [a.model_dump() for a in results.assets]

    if not assets_data:
        return ReportResponse(
            generated_at=datetime.now(timezone.utc).isoformat(),
            scope={"tag": tag, "asset_type": asset_type_filter},
            inventory=InventorySummary(total_assets=0, by_type={}, by_status={}),
            risk_counts={"critical": 0, "high": 0, "medium": 0, "low": 0},
            report="No assets found matching the specified scope. Import assets first using POST /api/v1/assets/import.",
        )

    # Build inventory stats
    inventory = _build_inventory(assets_data)

    # Run risk rules
    findings = score_assets(assets_data)
    risk_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        if f.risk_level in risk_counts:
            risk_counts[f.risk_level] += 1

    # Format data for the prompt
    inventory_text = _format_inventory_text(inventory)
    asset_details = format_assets_for_prompt(assets_data)

    if findings:
        risk_text = "\n".join(
            f"[{f.risk_level.upper()}] {f.asset_type} '{f.asset_value}': {f.finding}\n"
            f"  → Recommendation: {f.recommendation}"
            for f in findings
        )
    else:
        risk_text = "No risk findings identified."

    # LLM writes the full report
    llm = get_llm()
    chain = REPORT_PROMPT | llm | StrOutputParser()

    report_text = await chain.ainvoke({
        "inventory_text": inventory_text,
        "asset_details": asset_details,
        "risk_text": risk_text,
    })

    return ReportResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        scope={"tag": tag, "asset_type": asset_type_filter},
        inventory=inventory,
        risk_counts=risk_counts,
        report=report_text,
    )