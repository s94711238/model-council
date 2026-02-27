"""Unit tests for perplexity_check module — claim extraction and confidence scoring."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "scripts"))

from perplexity_check import (
    extract_verifiable_claims,
    _claim_type,
    _is_verifiable_sentence,
    _is_critical,
    _score_evidence,
    _normalize_spaces,
    _extract_text_and_citations,
)


class TestNormalizeSpaces:
    def test_collapses_whitespace(self) -> None:
        assert _normalize_spaces("hello   world\n\nfoo") == "hello world foo"

    def test_strips_edges(self) -> None:
        assert _normalize_spaces("  hello  ") == "hello"


class TestClaimType:
    def test_price_claim(self) -> None:
        assert _claim_type("The product costs $500 per unit") == "price"

    def test_market_metric(self) -> None:
        assert _claim_type("The CAGR is 15% over 5 years") == "market_metric"

    def test_citation(self) -> None:
        assert _claim_type("According to the WHO report published in 2023") == "citation"

    def test_timeline(self) -> None:
        assert _claim_type("The product was launched in 2024 with great success") == "timeline"

    def test_generic_fact(self) -> None:
        assert _claim_type("The company operates in multiple regions") == "fact"

    def test_chinese_price(self) -> None:
        assert _claim_type("產品價格為每單位 500 元") == "price"


class TestIsVerifiableSentence:
    def test_too_short(self) -> None:
        assert _is_verifiable_sentence("Short") is False

    def test_has_number_hint(self) -> None:
        assert _is_verifiable_sentence("The market size is $5.2 billion globally") is True

    def test_has_year(self) -> None:
        assert _is_verifiable_sentence("RNA sequencing was popularized around 2010 in research") is True

    def test_has_percentage(self) -> None:
        assert _is_verifiable_sentence("Growth rate is approximately 12% year over year") is True

    def test_has_market_keyword(self) -> None:
        assert _is_verifiable_sentence("The global market for biosensors is expanding rapidly") is True

    def test_plain_sentence_not_verifiable(self) -> None:
        assert _is_verifiable_sentence("This is an important consideration for the team") is False


class TestIsCritical:
    def test_price_is_critical(self) -> None:
        assert _is_critical("The price of sequencing has dropped significantly") is True

    def test_revenue_is_critical(self) -> None:
        assert _is_critical("Revenue exceeded expectations at $2.3M") is True

    def test_investment_chinese_is_critical(self) -> None:
        assert _is_critical("這項投資計畫值得關注") is True

    def test_generic_is_not_critical(self) -> None:
        assert _is_critical("The methodology uses standard protocols") is False


class TestExtractVerifiableClaims:
    def test_extracts_numeric_claims(self) -> None:
        report = (
            "The global sequencing market reached $25 billion in 2024. "
            "CAGR is projected at 18% through 2030. "
            "This is just a filler sentence without data. "
            "Revenue for the top 3 players exceeded $5 million."
        )
        claims = extract_verifiable_claims(report)
        assert len(claims) >= 2
        assert all("claim" in c and "type" in c and "critical" in c for c in claims)

    def test_deduplicates(self) -> None:
        report = (
            "The market size is $5 billion.\n"
            "The market size is $5 billion.\n"
        )
        claims = extract_verifiable_claims(report)
        assert len(claims) == 1

    def test_prioritizes_critical(self) -> None:
        report = (
            "Background context from 2020 about general research.\n"
            "Revenue reached $50 million in 2024, exceeding all forecasts.\n"
        )
        claims = extract_verifiable_claims(report)
        if len(claims) >= 2:
            # Critical claims should be sorted first
            critical_indices = [i for i, c in enumerate(claims) if c["critical"]]
            non_critical_indices = [i for i, c in enumerate(claims) if not c["critical"]]
            if critical_indices and non_critical_indices:
                assert min(critical_indices) < max(non_critical_indices)


class TestScoreEvidence:
    def test_high_overlap_high_confidence(self) -> None:
        claim = "The global sequencing market reached $25 billion in 2024"
        evidence = "According to reports, the global sequencing market reached approximately $25 billion by 2024, driven by NGS adoption."
        citations = ["https://example.edu/report", "https://nih.gov/data"]
        confidence, signals = _score_evidence(claim, evidence, citations)
        assert confidence >= 0.5
        assert signals["token_overlap"] > 0.5

    def test_no_evidence_low_confidence(self) -> None:
        claim = "The product costs $500"
        evidence = ""
        citations = []
        confidence, signals = _score_evidence(claim, evidence, citations)
        assert confidence <= 0.3

    def test_contradiction_lowers_confidence(self) -> None:
        claim = "The market grew 50% in 2024"
        evidence_ok = "Market growth was strong in 2024 with reports showing 50 percent increases across sectors."
        evidence_bad = "This claim is incorrect and misleading. No evidence supports 50 percent growth."
        citations = ["https://example.com"]

        conf_ok, _ = _score_evidence(claim, evidence_ok, citations)
        conf_bad, signals_bad = _score_evidence(claim, evidence_bad, citations)
        assert conf_bad < conf_ok
        assert signals_bad["contradiction"] < 0

    def test_authoritative_citations_boost(self) -> None:
        claim = "RNA sequencing adoption increased since 2015"
        evidence = "Studies confirm RNA sequencing adoption has risen steadily since 2015."
        auth_citations = ["https://nih.gov/study", "https://nature.com/article"]
        no_auth_citations = ["https://random-blog.com/post", "https://example.xyz/data"]

        conf_auth, signals_auth = _score_evidence(claim, evidence, auth_citations)
        conf_no_auth, signals_no_auth = _score_evidence(claim, evidence, no_auth_citations)
        assert signals_auth["citation_authority"] > signals_no_auth["citation_authority"]

    def test_numeric_match_matters(self) -> None:
        claim = "Revenue was $2.3 million with 15% growth"
        evidence_match = "The company reported revenue of 2.3 million dollars and 15 percent growth."
        evidence_no_match = "The company showed strong growth in the financial period."
        citations = ["https://example.com"]

        conf_match, signals_match = _score_evidence(claim, evidence_match, citations)
        conf_no_match, signals_no_match = _score_evidence(claim, evidence_no_match, citations)
        assert signals_match["numeric_match"] > signals_no_match["numeric_match"]

    def test_confidence_capped_at_095(self) -> None:
        claim = "test"
        evidence = "test " * 200
        citations = [f"https://nih.gov/{i}" for i in range(10)]
        confidence, _ = _score_evidence(claim, evidence, citations)
        assert confidence <= 0.95


class TestExtractTextAndCitations:
    def test_extracts_urls_from_nested_dict(self) -> None:
        raw = {
            "results": [
                {"url": "https://example.com/1", "text": "Some evidence text here for testing"},
                {"url": "https://example.com/2", "text": "More evidence text for the claim"},
            ]
        }
        evidence, citations = _extract_text_and_citations(raw)
        assert len(citations) == 2
        assert "evidence" in evidence.lower()

    def test_deduplicates_citations(self) -> None:
        raw = {
            "results": [
                {"url": "https://example.com/same", "text": "Text A is long enough to pass"},
                {"url": "https://example.com/same", "text": "Text B is long enough to pass"},
            ]
        }
        _, citations = _extract_text_and_citations(raw)
        assert len(citations) == 1
