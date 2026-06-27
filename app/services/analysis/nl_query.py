"""
Phase 4 — Natural Language Asset Query

Chain: NL query → LLM extracts filters → real DB query → grounded results

The LLM never sees or returns asset data directly.
It only decides WHICH FILTERS to apply.
All actual asset data comes from the database.
This makes hallucination structurally impossible.
"""

from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import AssetStatus, AssetType
from app.services.analysis.base import get_llm
from app.services.asset_service import list_assets


# ── Structured output schema ──────────────────────────────────────────────────
#
# This Pydantic model defines the EXACT shape the LLM must return.
# with_structured_output() enforces this using tool calling under the hood.
# If the LLM tries to return anything else, LangChain rejects it.

class ParsedAssetQuery(BaseModel):
    """Structured filters extracted from a natural language query."""

    asset_type: Optional[str] = Field(
        None,
        description=(
            "Asset type to filter by. "
            "Valid values: domain, subdomain, ip_address, service, certificate, technology. "
            "Null if the query does not specify a type."
        ),
    )
    status: Optional[str] = Field(
        None,
        description=(
            "Asset status to filter by. "
            "Valid values: active, stale, archived. "
            "'expired' or 'old' maps to 'stale'. "
            "Null if the query does not specify a status."
        ),
    )
    tag: Optional[str] = Field(
        None,
        description=(
            "A single tag label to filter by, e.g. 'production', 'staging', 'critical'. "
            "Null if the query does not mention a tag or environment."
        ),
    )
    search: Optional[str] = Field(
        None,
        description=(
            "Partial string to search within asset values, e.g. 'api', '443', 'example.com'. "
            "Null if the query does not mention a specific name or pattern."
        ),
    )
    explanation: str = Field(
        ...,
        description="One concise sentence explaining which filters you applied and why.",
    )


# ── Prompt ────────────────────────────────────────────────────────────────────

NL_QUERY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a precise query parser for DarkAtlas, \
an Attack Surface Management platform by Buguard.

Your job: convert a natural language query into structured database filters.

AVAILABLE FILTERS:
  asset_type → domain | subdomain | ip_address | service | certificate | technology
  status     → active | stale | archived
  tag        → any label string (e.g. production, staging, critical, payment, internal)
  search     → partial match on the asset value field

MAPPING RULES (apply these automatically):
  "expired" / "expiring soon" / "old"       → status = stale
  "archived" / "removed" / "decommissioned" → status = archived
  "active" / "live" / "running" / "current" → status = active
  "production" / "prod"                     → tag = production
  "staging" / "stage" / "dev" / "test"      → tag = staging
  "critical" / "high priority"              → tag = critical
  "certificate" / "cert" / "ssl" / "tls"   → asset_type = certificate
  "subdomain" / "sub"                       → asset_type = subdomain
  "ip" / "ip address" / "server ip"         → asset_type = ip_address
  "service" / "port" / "open port"          → asset_type = service
  "technology" / "tech" / "framework"       → asset_type = technology

RULES:
  - Only set a filter if it is mentioned or strongly implied
  - Set all unmentioned filters to null
  - Never invent filters not supported above
  - tag can only hold ONE value — pick the most relevant one

EXAMPLES:
  "show me all expired certificates"
  → asset_type=certificate, status=stale, tag=null, search=null

  "find production subdomains with api in the name"
  → asset_type=subdomain, status=null, tag=production, search=api

  "what active assets do we have on staging"
  → asset_type=null, status=active, tag=staging, search=null

  "list all ip addresses"
  → asset_type=ip_address, status=null, tag=null, search=null
"""),
    ("human", "{query}"),
])


# ── Main function ─────────────────────────────────────────────────────────────

async def natural_language_query(db: AsyncSession, query: str, organization_id: str = "default") -> dict:
    """
    Translates a natural language query into a database query.

    Steps:
      1. LLM reads the query and outputs a ParsedAssetQuery object
      2. We validate each filter value against our enums
      3. We query the REAL database with the validated filters
      4. We return actual assets — the LLM never touches the results

    Returns a dict with:
      - query: the original user query
      - explanation: the LLM's interpretation
      - filters_applied: what filters were actually used
      - total: count of matching assets
      - assets: the actual asset list from the DB
    """
    llm = get_llm()

    # with_structured_output forces the LLM to return a ParsedAssetQuery.
    # Internally, LangChain registers ParsedAssetQuery as a tool and
    # forces the LLM to call it — so the output is always structured.
    structured_llm = llm.with_structured_output(ParsedAssetQuery)
    chain = NL_QUERY_PROMPT | structured_llm

    # Step 1: Parse the query (async — doesn't block the server)
    parsed: ParsedAssetQuery = await chain.ainvoke({"query": query})

    # Step 2: Validate enum values.
    # Even if the LLM returns a valid-looking string, we verify it against
    # our enums. Invalid values are silently ignored (not crashed on).
    asset_type: AssetType | None = None
    if parsed.asset_type:
        try:
            asset_type = AssetType(parsed.asset_type.strip().lower())
        except ValueError:
            pass  # LLM returned an unsupported type — treat as no filter

    status: AssetStatus | None = None
    if parsed.status:
        try:
            status = AssetStatus(parsed.status.strip().lower())
        except ValueError:
            pass

    # Sanitize tag and search: strip whitespace, lowercase, empty → None
    tag = parsed.tag.strip().lower() if parsed.tag and parsed.tag.strip() else None
    search = parsed.search.strip() if parsed.search and parsed.search.strip() else None

    # Step 3: Query the REAL database
    # This is the grounding step — results come from DB, not from the LLM
    results = await list_assets(
        db,
        organization_id=organization_id,
        asset_type=asset_type,
        status=status,
        tag=tag,
        search=search,
        page=1,
        page_size=50,  # max 50 results per NL query
    )

    # Step 4: Return results with full transparency about what was applied
    return {
        "query": query,
        "explanation": parsed.explanation,
        "filters_applied": {
            "type": asset_type.value if asset_type else None,
            "status": status.value if status else None,
            "tag": tag,
            "search": search,
        },
        "total": results.total,
        "assets": [a.model_dump() for a in results.assets],
    }