"""
Phase 5 — Risk Scoring & Summary

Architecture:
  1. Fetch assets from DB
  2. Rule-based scoring (deterministic, fast, auditable — no LLM)
  3. LLM generates executive summary FROM the rule findings (not inventing risks)

Why rules first, LLM second?
  Rules give consistent, verifiable, explainable risk scores.
  LLM gives a human-readable narrative on top of those scores.
  Pure LLM risk scoring would be slow, inconsistent, and unauditable.
"""

from datetime import datetime, timezone
from typing import Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cachetools import TTLCache

from app.services.analysis.base import DARKATLAS_SYSTEM_PROMPT, get_llm
from app.services.asset_service import get_all_assets_for_analysis

# Cache LLM summaries for 5 minutes — keyed by (org_id, tag, asset_type)
_risk_cache: TTLCache = TTLCache(maxsize=128, ttl=300)


# ── Risk severity ordering ────────────────────────────────────────────────────

RISK_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}

# Ports that should never be publicly exposed, mapped to (service name, risk level)
DANGEROUS_PORTS = {
    "23/":   ("Telnet",   "critical"),  # plaintext, completely insecure
    "3389/": ("RDP",      "critical"),  # remote desktop, top attack vector
    "22/":   ("SSH",      "high"),      # should be IP-restricted, not public
    "21/":   ("FTP",      "high"),      # plaintext file transfer
    "25/":   ("SMTP",     "medium"),    # open mail relay risk
    "8080/": ("HTTP-alt", "medium"),    # unencrypted alternate HTTP
    "80/":   ("HTTP",     "low"),       # unencrypted web traffic
}


# ── Output schemas ────────────────────────────────────────────────────────────

class RiskFinding(BaseModel):
    """A single risk finding for one asset."""
    asset_id: str
    asset_value: str
    asset_type: str
    risk_level: str        # critical | high | medium | low
    finding: str           # what the risk is (specific, factual)
    recommendation: str    # what to do about it


class RiskSummaryResponse(BaseModel):
    """Full risk analysis response."""
    total_assets_analyzed: int
    risk_counts: dict          # {"critical": N, "high": N, "medium": N, "low": N}
    findings: list[RiskFinding]
    summary: str               # LLM-generated executive summary
    analyzed_at: str


# ── Rule engine ───────────────────────────────────────────────────────────────

def _assess_certificate(asset: dict) -> list[RiskFinding]:
    """
    Certificate risks:
      - Expired certificate         → HIGH
      - Expiring within 30 days     → HIGH
      - Expiring within 90 days     → MEDIUM
      - Certificate marked stale    → MEDIUM
    """
    findings = []
    meta = asset.get("metadata", {})
    expires_str = meta.get("expires_at")

    if expires_str:
        try:
            expires_at = datetime.fromisoformat(str(expires_str).replace("Z", "+00:00"))
            # Ensure timezone-aware comparison
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            days_left = (expires_at - now).days

            if days_left < 0:
                findings.append(RiskFinding(
                    asset_id=str(asset["id"]),
                    asset_value=asset["value"],
                    asset_type="certificate",
                    risk_level="high",
                    finding=(
                        f"Certificate EXPIRED {abs(days_left)} day(s) ago "
                        f"(expiry: {expires_str})"
                    ),
                    recommendation=(
                        "Renew this certificate immediately. "
                        "Expired certificates cause browser security warnings and block users."
                    ),
                ))
            elif days_left <= 30:
                findings.append(RiskFinding(
                    asset_id=str(asset["id"]),
                    asset_value=asset["value"],
                    asset_type="certificate",
                    risk_level="high",
                    finding=f"Certificate expires in {days_left} day(s) — imminent expiry",
                    recommendation=(
                        "Renew immediately. "
                        "Certificates expiring within 30 days are a production incident risk."
                    ),
                ))
            elif days_left <= 90:
                findings.append(RiskFinding(
                    asset_id=str(asset["id"]),
                    asset_value=asset["value"],
                    asset_type="certificate",
                    risk_level="medium",
                    finding=f"Certificate expires in {days_left} day(s)",
                    recommendation="Schedule renewal within the next 2 weeks.",
                ))
        except (ValueError, TypeError):
            # Could not parse the date — flag for review
            findings.append(RiskFinding(
                asset_id=str(asset["id"]),
                asset_value=asset["value"],
                asset_type="certificate",
                risk_level="low",
                finding=f"Certificate has unreadable expiry date: '{expires_str}'",
                recommendation="Fix the expires_at metadata format to enable proper tracking.",
            ))

    if asset.get("status") == "stale":
        findings.append(RiskFinding(
            asset_id=str(asset["id"]),
            asset_value=asset["value"],
            asset_type="certificate",
            risk_level="medium",
            finding="Certificate is marked stale — may be unmonitored or abandoned",
            recommendation=(
                "Verify if this certificate is still in use. "
                "Archive it if the associated service has been decommissioned."
            ),
        ))

    return findings


def _assess_service(asset: dict) -> list[RiskFinding]:
    """
    Service risks: check if dangerous ports are publicly exposed.
    """
    findings = []
    value = asset.get("value", "")

    for port_pattern, (service_name, risk_level) in DANGEROUS_PORTS.items():
        if port_pattern in value:
            if risk_level == "critical":
                finding = (
                    f"CRITICAL: {service_name} port publicly exposed ({value}). "
                    f"{service_name} is an extremely high-risk attack vector."
                )
                recommendation = (
                    f"Immediately block public access to {service_name}. "
                    "This service should NEVER be internet-facing. "
                    "Restrict to VPN or trusted IP allowlist only."
                )
            elif risk_level == "high":
                finding = f"High-risk service publicly exposed: {service_name} ({value})"
                recommendation = (
                    f"Restrict {service_name} access to known trusted IPs. "
                    "Consider placing behind a VPN. Review access logs for unauthorized attempts."
                )
            else:
                finding = f"Potentially risky service exposed: {service_name} ({value})"
                recommendation = (
                    f"Confirm {service_name} exposure is intentional. "
                    "Ensure proper authentication and encryption are in place."
                )

            findings.append(RiskFinding(
                asset_id=str(asset["id"]),
                asset_value=value,
                asset_type="service",
                risk_level=risk_level,
                finding=finding,
                recommendation=recommendation,
            ))
            break  # one finding per service asset

    return findings


def _assess_technology(asset: dict) -> list[RiskFinding]:
    """
    Technology risks: flag versioned technologies for EOL review.
    """
    findings = []
    meta = asset.get("metadata", {})
    version = meta.get("version", "")
    name = meta.get("name", asset.get("value", "technology"))

    if version:
        findings.append(RiskFinding(
            asset_id=str(asset["id"]),
            asset_value=asset["value"],
            asset_type="technology",
            risk_level="medium",
            finding=(
                f"Technology version detected: {name} {version} — "
                "verify this version is not end-of-life (EOL)"
            ),
            recommendation=(
                f"Check if {name} {version} still receives security patches. "
                "Upgrade immediately if it has reached EOL. "
                "Monitor CVE databases for known vulnerabilities in this version."
            ),
        ))

    return findings


def _assess_stale(asset: dict) -> list[RiskFinding]:
    """Stale domains, subdomains, and IPs may be forgotten attack surface."""
    asset_type = asset.get("type", "")
    if asset_type not in ("domain", "subdomain", "ip_address"):
        return []

    return [RiskFinding(
        asset_id=str(asset["id"]),
        asset_value=asset["value"],
        asset_type=asset_type,
        risk_level="medium",
        finding=(
            f"Stale {asset_type} detected: {asset['value']} — "
            "asset is not actively monitored"
        ),
        recommendation=(
            "Verify if this asset is still in use. "
            "Forgotten assets are common entry points for attackers. "
            "Archive it if decommissioned; mark it active if still in use."
        ),
    )]


def score_assets(assets: list[dict]) -> list[RiskFinding]:
    """
    Run all risk rules against a list of assets.
    Returns findings sorted by severity (critical first).
    """
    all_findings: list[RiskFinding] = []

    for asset in assets:
        asset_type = asset.get("type", "")
        status = asset.get("status", "")

        # Type-specific rules
        if asset_type == "certificate":
            all_findings.extend(_assess_certificate(asset))
        elif asset_type == "service":
            all_findings.extend(_assess_service(asset))
        elif asset_type == "technology":
            all_findings.extend(_assess_technology(asset))

        # Cross-type rule: stale assets
        if status == "stale":
            all_findings.extend(_assess_stale(asset))

    # Sort: critical → high → medium → low
    all_findings.sort(
        key=lambda f: RISK_ORDER.get(f.risk_level, 0),
        reverse=True,
    )
    return all_findings


# ── LLM executive summary ─────────────────────────────────────────────────────

RISK_SUMMARY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", DARKATLAS_SYSTEM_PROMPT),
    ("human", """You are writing an executive risk summary for a security team.

FINDINGS FROM AUTOMATED RULE SCAN:
{findings_text}

STATISTICS:
- Total assets analyzed: {total}
- Critical findings: {critical}
- High findings: {high}
- Medium findings: {medium}
- Low findings: {low}

Write a concise executive summary (3-5 sentences) that:
1. States the overall risk posture clearly
2. Calls out the most urgent issue(s) by name
3. Gives one clear recommended immediate action
4. Is professional and factual — based ONLY on the findings above

If there are no findings, state that the attack surface appears clean.
Do NOT invent risks not present in the findings.
"""),
])


async def generate_risk_summary(
    findings: list[RiskFinding],
    total_assets: int,
    risk_counts: dict,
) -> str:
    """Generate an LLM executive summary from rule-based findings."""
    if not findings:
        return (
            "No significant risks were identified in the analyzed assets. "
            "The attack surface appears clean based on the available data. "
            "Continue regular monitoring to maintain this posture."
        )

    llm = get_llm()
    chain = RISK_SUMMARY_PROMPT | llm | StrOutputParser()

    findings_text = "\n".join(
        f"[{f.risk_level.upper()}] {f.asset_type} '{f.asset_value}': {f.finding}"
        for f in findings
    )

    return await chain.ainvoke({
        "findings_text": findings_text,
        "total": total_assets,
        "critical": risk_counts.get("critical", 0),
        "high": risk_counts.get("high", 0),
        "medium": risk_counts.get("medium", 0),
        "low": risk_counts.get("low", 0),
    })


# ── Main entry point ──────────────────────────────────────────────────────────

async def analyze_risk(
    db: AsyncSession,
    tag: Optional[str] = None,
    asset_type_filter: Optional[str] = None,
    organization_id: str = "default",
) -> RiskSummaryResponse:
    """
    Full risk analysis pipeline.

    Steps:
      1. Fetch assets from DB (optionally scoped by tag or type)
      2. Run all risk rules against every asset
      3. LLM writes executive summary from the findings
      4. Return structured result

    Optional filters let you scope the analysis:
      tag=production  → only analyze production assets
      type=certificate → only analyze certificates
    """
    # Check cache first (keyed by org + filters)
    cache_key = (organization_id, tag, asset_type_filter)
    if cache_key in _risk_cache:
        return _risk_cache[cache_key]

    # Fetch assets scoped to this org
    assets_data = await get_all_assets_for_analysis(
        db,
        organization_id=organization_id,
        tag=tag,
        asset_type_filter=asset_type_filter,
    )

    # Rule-based scoring — pure Python, no LLM
    findings = score_assets(assets_data)

    # Count by severity
    risk_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        if f.risk_level in risk_counts:
            risk_counts[f.risk_level] += 1

    # LLM writes the narrative summary from the findings
    summary = await generate_risk_summary(findings, len(assets_data), risk_counts)

    result = RiskSummaryResponse(
        total_assets_analyzed=len(assets_data),
        risk_counts=risk_counts,
        findings=findings,
        summary=summary,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
    )
    _risk_cache[cache_key] = result
    return result