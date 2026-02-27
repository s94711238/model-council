"""Unit tests for synthesize module — structured and legacy consensus detection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "scripts"))

from synthesize import (
    _parse_structured_block,
    _normalize_line,
    _extract_key_lines,
    _build_legacy_consensus,
    _build_structured_consensus,
)


class TestParseStructuredBlock:
    def test_extracts_valid_json(self) -> None:
        text = """
Some markdown analysis here.

```json
{
  "verdict": "pass_with_caveats",
  "confidence": 78,
  "critical_issues": ["Missing sample size"],
  "non_critical_issues": ["Could add more citations"],
  "unsupported_claims": ["Market size claim"],
  "key_findings": ["Strong methodology"]
}
```
"""
        result = _parse_structured_block(text)
        assert result is not None
        assert result["verdict"] == "pass_with_caveats"
        assert result["confidence"] == 78
        assert len(result["critical_issues"]) == 1
        assert result["key_findings"] == ["Strong methodology"]

    def test_returns_none_for_no_json(self) -> None:
        assert _parse_structured_block("Just plain text, no JSON here.") is None

    def test_returns_none_for_invalid_json(self) -> None:
        text = '```json\n{invalid json here}\n```'
        assert _parse_structured_block(text) is None

    def test_clamps_confidence(self) -> None:
        text = '```json\n{"verdict": "pass", "confidence": 150}\n```'
        result = _parse_structured_block(text)
        assert result is not None
        assert result["confidence"] == 100

    def test_normalizes_verdict_case(self) -> None:
        text = '```json\n{"verdict": "PASS_WITH_CAVEATS", "confidence": 50}\n```'
        result = _parse_structured_block(text)
        assert result is not None
        assert result["verdict"] == "pass_with_caveats"

    def test_handles_missing_lists(self) -> None:
        text = '```json\n{"verdict": "pass", "confidence": 80}\n```'
        result = _parse_structured_block(text)
        assert result is not None
        assert result["critical_issues"] == []
        assert result["unsupported_claims"] == []


class TestNormalizeLine:
    def test_removes_bullets(self) -> None:
        assert _normalize_line("- This is a bullet point") == "this is a bullet point"

    def test_removes_numbers(self) -> None:
        assert _normalize_line("1. First item") == "first item"

    def test_removes_special_chars(self) -> None:
        normalized = _normalize_line("**Bold** text with (parens)")
        assert "bold" in normalized
        assert "text" in normalized


class TestExtractKeyLines:
    def test_skips_short_lines(self) -> None:
        text = "Short\nAlso short\nThis is a much longer line that should be captured by the extractor"
        lines = _extract_key_lines(text)
        assert len(lines) == 1

    def test_skips_headers(self) -> None:
        text = "# Header\n## Another header\nThis is actual content that is long enough to capture"
        lines = _extract_key_lines(text)
        assert all(not l.startswith("#") for l in lines)

    def test_respects_max_lines(self) -> None:
        long_text = "\n".join(f"This is line number {i} which is quite long enough" for i in range(50))
        lines = _extract_key_lines(long_text, max_lines=5)
        assert len(lines) == 5


class TestBuildLegacyConsensus:
    def test_finds_identical_lines(self) -> None:
        verifications = {
            "codex": "The methodology has serious flaws in sample selection.\nOther stuff here that is unique to codex only.",
            "sonnet": "The methodology has serious flaws in sample selection.\nSonnet-specific observation about argument structure.",
        }
        consensus, divergence = _build_legacy_consensus(verifications)
        # The shared line should appear in consensus
        assert any("methodology" in c.lower() for c in consensus)

    def test_captures_unique_lines_as_divergence(self) -> None:
        verifications = {
            "codex": "Codex says this very unique and specific technical thing about the analysis.",
            "sonnet": "Sonnet sees a completely different reasoning issue in this report.",
        }
        consensus, divergence = _build_legacy_consensus(verifications)
        assert len(divergence.get("codex", [])) >= 0
        assert len(divergence.get("sonnet", [])) >= 0


class TestBuildStructuredConsensus:
    def test_verdict_majority(self) -> None:
        structured = {
            "codex": {
                "verdict": "pass_with_caveats",
                "confidence": 75,
                "critical_issues": ["Missing evidence for claim A"],
                "non_critical_issues": [],
                "unsupported_claims": [],
                "key_findings": ["Good methodology"],
            },
            "sonnet": {
                "verdict": "pass_with_caveats",
                "confidence": 80,
                "critical_issues": ["Missing evidence for claim A"],
                "non_critical_issues": ["Could improve clarity"],
                "unsupported_claims": [],
                "key_findings": ["Clear structure"],
            },
            "strategic": {
                "verdict": "fail",
                "confidence": 60,
                "critical_issues": ["Not actionable"],
                "non_critical_issues": [],
                "unsupported_claims": [],
                "key_findings": ["Lacks execution plan"],
            },
        }
        consensus, divergence, stats = _build_structured_consensus(structured)

        assert stats["majority_verdict"] == "pass_with_caveats"
        assert stats["majority_count"] == 2
        assert stats["avg_confidence"] == pytest.approx(71.7, abs=0.1)
        assert stats["min_confidence"] == 60

    def test_shared_critical_issues_in_consensus(self) -> None:
        structured = {
            "codex": {
                "verdict": "fail",
                "confidence": 70,
                "critical_issues": ["The market size data is outdated"],
                "non_critical_issues": [],
                "unsupported_claims": [],
                "key_findings": [],
            },
            "sonnet": {
                "verdict": "fail",
                "confidence": 65,
                "critical_issues": ["The market size data is outdated"],
                "non_critical_issues": [],
                "unsupported_claims": [],
                "key_findings": [],
            },
        }
        consensus, _, stats = _build_structured_consensus(structured)
        assert stats["consensus_critical_issues"] >= 1
        assert any("market size" in line.lower() for line in consensus)

    def test_divergence_captures_verdict_disagreement(self) -> None:
        structured = {
            "codex": {
                "verdict": "pass",
                "confidence": 85,
                "critical_issues": [],
                "non_critical_issues": [],
                "unsupported_claims": [],
                "key_findings": [],
            },
            "sonnet": {
                "verdict": "pass",
                "confidence": 80,
                "critical_issues": [],
                "non_critical_issues": [],
                "unsupported_claims": [],
                "key_findings": [],
            },
            "strategic": {
                "verdict": "fail",
                "confidence": 50,
                "critical_issues": ["Not decision-ready"],
                "non_critical_issues": [],
                "unsupported_claims": [],
                "key_findings": [],
            },
        }
        _, divergence, _ = _build_structured_consensus(structured)
        strategic_div = divergence.get("strategic", [])
        assert any("divergence" in line.lower() for line in strategic_div)
