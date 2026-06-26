"""
Tests for the risk scoring rule engine.

These tests are pure Python — no database, no LLM, no network.
We test the rule engine by passing asset dictionaries directly
to score_assets() and verifying the findings.
"""

import pytest
from app.services.analysis.risk import score_assets, RISK_ORDER


# ── Helper ────────────────────────────────────────────────────────────────────

def make_asset(type_, value, status="active", tags=None, metadata=None):
    """Create a minimal asset dict for testing."""
    return {
        "id": f"test-{type_}-{value}",
        "type": type_,
        "value": value,
        "status": status,
        "tags": tags or [],
        "metadata": metadata or {},
    }


# ── Certificate tests ─────────────────────────────────────────────────────────

def test_expired_certificate_is_high_risk():
    """A certificate with a past expiry date must be flagged HIGH."""
    assets = [make_asset("certificate", "cert.example.com",
                         metadata={"expires_at": "2020-01-01"})]
    findings = score_assets(assets)
    risk_levels = [f.risk_level for f in findings]
    assert "high" in risk_levels, "Expired certificate should produce a HIGH finding"


def test_stale_certificate_is_medium_risk():
    """A certificate marked stale must produce at least a MEDIUM finding."""
    assets = [make_asset("certificate", "cert.example.com", status="stale")]
    findings = score_assets(assets)
    risk_levels = [f.risk_level for f in findings]
    assert "medium" in risk_levels, "Stale certificate should produce a MEDIUM finding"


def test_valid_certificate_no_findings():
    """An active certificate with no expiry data produces no findings."""
    assets = [make_asset("certificate", "good.example.com", status="active")]
    findings = score_assets(assets)
    assert len(findings) == 0, "Active certificate with no expiry data should have no findings"


def test_expired_cert_finding_mentions_asset_value():
    """The finding text must mention the specific asset value — no generic messages."""
    assets = [make_asset("certificate", "api.example.com",
                         metadata={"expires_at": "2019-06-01"})]
    findings = score_assets(assets)
    expired_findings = [f for f in findings if "EXPIRED" in f.finding.upper()]
    assert len(expired_findings) > 0
    assert "api.example.com" == expired_findings[0].asset_value


# ── Service / port tests ──────────────────────────────────────────────────────

def test_telnet_service_is_critical():
    """Telnet (port 23) publicly exposed must be CRITICAL."""
    assets = [make_asset("service", "23/tcp")]
    findings = score_assets(assets)
    assert any(f.risk_level == "critical" for f in findings), \
        "Telnet port should be CRITICAL"


def test_rdp_service_is_critical():
    """RDP (port 3389) publicly exposed must be CRITICAL."""
    assets = [make_asset("service", "3389/tcp")]
    findings = score_assets(assets)
    assert any(f.risk_level == "critical" for f in findings), \
        "RDP port should be CRITICAL"


def test_ssh_service_is_high():
    """SSH (port 22) publicly exposed must be HIGH."""
    assets = [make_asset("service", "22/tcp")]
    findings = score_assets(assets)
    assert any(f.risk_level == "high" for f in findings), \
        "SSH port should be HIGH"


def test_ftp_service_is_high():
    """FTP (port 21) publicly exposed must be HIGH."""
    assets = [make_asset("service", "21/tcp")]
    findings = score_assets(assets)
    assert any(f.risk_level == "high" for f in findings), \
        "FTP port should be HIGH"


def test_https_service_no_finding():
    """HTTPS (port 443) should not produce any risk finding."""
    assets = [make_asset("service", "443/tcp")]
    findings = score_assets(assets)
    assert len(findings) == 0, "HTTPS port 443 should not produce any finding"


# ── Technology tests ──────────────────────────────────────────────────────────

def test_versioned_technology_flagged_for_review():
    """Any technology with a version number should produce a MEDIUM finding."""
    assets = [make_asset("technology", "nginx",
                         metadata={"name": "nginx", "version": "1.14.0"})]
    findings = score_assets(assets)
    assert any(f.risk_level == "medium" for f in findings), \
        "Technology with version should produce MEDIUM finding for EOL review"


def test_technology_without_version_no_finding():
    """A technology with no version metadata should not be flagged."""
    assets = [make_asset("technology", "nginx", metadata={"name": "nginx"})]
    findings = score_assets(assets)
    assert len(findings) == 0


# ── Stale asset tests ─────────────────────────────────────────────────────────

def test_stale_domain_is_medium():
    """A stale domain should produce a MEDIUM finding."""
    assets = [make_asset("domain", "old.example.com", status="stale")]
    findings = score_assets(assets)
    assert any(f.risk_level == "medium" for f in findings)


def test_stale_subdomain_is_medium():
    """A stale subdomain should produce a MEDIUM finding."""
    assets = [make_asset("subdomain", "old.api.example.com", status="stale")]
    findings = score_assets(assets)
    assert any(f.risk_level == "medium" for f in findings)


def test_clean_active_domain_no_findings():
    """An active domain with no issues should produce no findings."""
    assets = [make_asset("domain", "example.com", status="active",
                         tags=["production"])]
    findings = score_assets(assets)
    assert len(findings) == 0


# ── Sorting tests ─────────────────────────────────────────────────────────────

def test_findings_sorted_critical_first():
    """
    When mixed severities exist, CRITICAL findings must come before HIGH and MEDIUM.
    """
    assets = [
        make_asset("service", "23/tcp"),              # → CRITICAL
        make_asset("certificate", "c.example.com",    # → HIGH (expired)
                   metadata={"expires_at": "2020-01-01"}),
        make_asset("domain", "old.example.com",       # → MEDIUM (stale)
                   status="stale"),
    ]
    findings = score_assets(assets)
    assert len(findings) > 0

    levels = [f.risk_level for f in findings]
    # Verify order: each finding's severity must be >= the next one's
    for i in range(len(levels) - 1):
        assert RISK_ORDER[levels[i]] >= RISK_ORDER[levels[i + 1]], \
            f"Findings not sorted: {levels[i]} came before {levels[i+1]}"


def test_empty_asset_list_returns_no_findings():
    """Scoring an empty list must return an empty findings list."""
    findings = score_assets([])
    assert findings == []


def test_multiple_assets_multiple_findings():
    """Multiple risky assets should produce multiple independent findings."""
    assets = [
        make_asset("service", "23/tcp"),
        make_asset("service", "3389/tcp"),
        make_asset("certificate", "c.example.com",
                   metadata={"expires_at": "2020-01-01"}),
    ]
    findings = score_assets(assets)
    assert len(findings) >= 3, "Each risky asset should produce at least one finding"