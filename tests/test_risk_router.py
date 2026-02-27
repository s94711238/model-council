"""Unit tests for risk_router module."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "scripts"))

from risk_router import assess_risk, route_verification, _count_keywords, _estimate_complexity


class TestCountKeywords:
    def test_finds_chinese_keywords(self) -> None:
        assert _count_keywords("這是一份投資報告分析收購目標", ["投資", "收購"]) == 2

    def test_finds_english_keywords_case_insensitive(self) -> None:
        assert _count_keywords("This is a M&A due diligence report", ["m&a", "due diligence"]) == 2

    def test_no_matches(self) -> None:
        assert _count_keywords("Hello world", ["投資", "m&a"]) == 0

    def test_partial_match_still_counts(self) -> None:
        assert _count_keywords("This report covers pricing strategy", ["pricing", "strategy"]) == 2


class TestEstimateComplexity:
    def test_short_content(self) -> None:
        result = _estimate_complexity("Hello world.")
        assert result["word_count"] == 2
        assert result["number_count"] == 0

    def test_counts_numbers(self) -> None:
        result = _estimate_complexity("Revenue is $5.2 million, CAGR 12.5%, market size 3.4 billion")
        assert result["number_count"] >= 3

    def test_counts_citations(self) -> None:
        result = _estimate_complexity("See [1] and [2] at https://example.com")
        assert result["citation_count"] >= 2  # 2 bracket citations + 1 URL

    def test_number_density(self) -> None:
        # 50% numbers, 50% words
        text = "1 2 3 4 5 hello world foo bar baz"
        result = _estimate_complexity(text)
        assert result["number_density"] > 0.0


class TestRouteVerification:
    def test_high_risk_full_council(self) -> None:
        result = route_verification("high")
        assert result["models"] == ["codex", "sonnet", "strategic"]
        assert result["use_perplexity"] is False
        assert result["estimated_cost"] == 45_000

    def test_medium_risk_codex_only(self) -> None:
        result = route_verification("medium")
        assert result["models"] == ["codex"]
        assert result["use_perplexity"] is True
        assert result["estimated_cost"] == 30_000

    def test_low_risk_no_models(self) -> None:
        result = route_verification("low")
        assert result["models"] == []
        assert result["use_perplexity"] is True
        assert result["estimated_cost"] == 15_000

    def test_savings_calculation(self) -> None:
        result = route_verification("low")
        assert result["estimated_savings_vs_v1"] == 45_000 - 15_000


class TestAssessRisk:
    def _write_temp_report(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        return f.name

    def test_high_risk_investment_report(self) -> None:
        path = self._write_temp_report(
            "投資分析報告：收購目標估值\n"
            "市場規模 $500 million，CAGR 15%\n"
            "技術選型：Kubernetes vs ECS\n"
            "Due diligence 重點：營收 $2.3M, capex $800K\n"
            "成長率 22%, 價格 $45/unit, 市占率 12%\n"
            "Estimated 2025 revenue: $5,000,000\n"
            "Estimated 2026 revenue: $7,500,000\n"
        )
        result = assess_risk(path)
        assert result["risk_level"] == "high"
        Path(path).unlink()

    def test_low_risk_literature_review(self) -> None:
        path = self._write_temp_report(
            "Literature Review: Background on RNA Sequencing\n"
            "This summary provides an overview of the field.\n"
        )
        result = assess_risk(path)
        assert result["risk_level"] == "low"
        Path(path).unlink()

    def test_medium_risk_market_analysis(self) -> None:
        path = self._write_temp_report(
            "市場分析報告\n"
            "競爭者分析 and pricing strategy evaluation\n"
            "Go-to-market plan for the new product line\n"
            "Benchmark against existing solutions in the market\n"
            "Revenue projection: $1.2M in year one\n"
        )
        result = assess_risk(path)
        assert result["risk_level"] in {"medium", "high"}  # medium keywords should push it up
        Path(path).unlink()

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            assess_risk("/nonexistent/path/report.md")

    def test_result_structure(self) -> None:
        path = self._write_temp_report("Simple test report content here.")
        result = assess_risk(path)
        assert "risk_level" in result
        assert "score" in result
        assert "signals" in result
        assert "verification_strategy" in result
        Path(path).unlink()
