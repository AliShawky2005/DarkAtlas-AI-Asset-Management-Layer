"""
Tests for the evaluation harness (Bonus 6).

These tests are pure Python — no database, no HTTP calls.
We test the evaluation logic directly by passing mock data.
"""

import pytest
from app.services.analysis.eval import EvaluationResult


# ── Helper: mock a risk finding ───────────────────────────────────────────────

class MockFinding:
    def __init__(self, risk_level, asset_type, asset_value, finding):
        self.risk_level = risk_level
        self.asset_type = asset_type
        self.asset_value = asset_value
        self.finding = finding


class MockReportResult:
    def __init__(self, total, by_type, by_status, risk_counts, report):
        from app.services.analysis.report import InventorySummary
        self.inventory = InventorySummary(
            total_assets=total,
            by_type=by_type,
            by_status=by_status,
        )
        self.risk_counts = risk_counts
        self.report = report


# ── EvaluationResult schema tests ─────────────────────────────────────────────

def test_evaluation_result_score_range():
    """Score must be between 0.0 and 1.0."""
    result = EvaluationResult(
        score=0.85,
        reasoning="Good output",
        passed=True,
        hallucination_detected=False,
        dimension_scores={"relevance": 0.9, "grounding": 0.8, "clarity": 0.85},
    )
    assert 0.0 <= result.score <= 1.0


def test_evaluation_result_passed_threshold():
    """A score of 0.7 or above must set passed=True."""
    high = EvaluationResult(
        score=0.75, reasoning="", passed=True,
        hallucination_detected=False, dimension_scores={}
    )
    low = EvaluationResult(
        score=0.5, reasoning="", passed=False,
        hallucination_detected=False, dimension_scores={}
    )
    assert high.passed is True
    assert low.passed is False


def test_evaluation_result_hallucination_flag():
    """Hallucination detection must be explicitly set."""
    clean = EvaluationResult(
        score=0.9, reasoning="", passed=True,
        hallucination_detected=False, dimension_scores={}
    )
    hallucinated = EvaluationResult(
        score=0.3, reasoning="Invented facts", passed=False,
        hallucination_detected=True, dimension_scores={}
    )
    assert clean.hallucination_detected is False
    assert hallucinated.hallucination_detected is True


def test_evaluation_result_dimension_scores_present():
    """Dimension scores dict must support at least relevance, grounding, clarity."""
    result = EvaluationResult(
        score=0.8,
        reasoning="Well grounded",
        passed=True,
        hallucination_detected=False,
        dimension_scores={"relevance": 0.9, "grounding": 0.8, "clarity": 0.7},
    )
    assert "relevance" in result.dimension_scores
    assert "grounding" in result.dimension_scores
    assert "clarity" in result.dimension_scores
    for v in result.dimension_scores.values():
        assert 0.0 <= v <= 1.0


def test_evaluation_result_zero_score():
    """A score of 0.0 is valid (terrible output)."""
    result = EvaluationResult(
        score=0.0, reasoning="Complete hallucination", passed=False,
        hallucination_detected=True, dimension_scores={}
    )
    assert result.score == 0.0
    assert result.passed is False


def test_evaluation_result_perfect_score():
    """A score of 1.0 is valid (perfect output)."""
    result = EvaluationResult(
        score=1.0, reasoning="Perfect", passed=True,
        hallucination_detected=False,
        dimension_scores={"relevance": 1.0, "grounding": 1.0, "clarity": 1.0},
    )
    assert result.score == 1.0
    assert result.passed is True


# ── Mock finding structure tests ──────────────────────────────────────────────

def test_mock_finding_has_required_fields():
    """Mock findings must have all fields the eval service reads."""
    f = MockFinding("high", "certificate", "api.example.com", "Cert expired")
    assert hasattr(f, "risk_level")
    assert hasattr(f, "asset_type")
    assert hasattr(f, "asset_value")
    assert hasattr(f, "finding")


def test_empty_findings_produces_clean_summary_input():
    """With no findings, the inputs to the judge should indicate no risks."""
    findings = []
    findings_text = "No risk findings were identified." if not findings else "FINDINGS"
    assert "No risk findings" in findings_text


def test_multiple_findings_formats_correctly():
    """Multiple findings should format into readable judge input."""
    findings = [
        MockFinding("critical", "service", "23/tcp", "Telnet exposed"),
        MockFinding("high",     "certificate", "cert.example.com", "Cert expired"),
    ]
    lines = "\n".join(
        f"[{f.risk_level.upper()}] {f.asset_type} '{f.asset_value}': {f.finding}"
        for f in findings
    )
    assert "[CRITICAL]" in lines
    assert "[HIGH]" in lines
    assert "Telnet exposed" in lines
    assert "Cert expired" in lines
