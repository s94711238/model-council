#!/usr/bin/env python3
"""Risk Router for Model Council.

Analyzes report content and routes to an appropriate verification level.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Literal

RiskLevel = Literal["low", "medium", "high"]

KEYWORDS_HIGH = [
    "投資",
    "收購",
    "併購",
    "m&a",
    "架構設計",
    "技術選型",
    "critical",
    "mission critical",
    "capex",
    "due diligence",
]
KEYWORDS_MEDIUM = [
    "市場分析",
    "競爭者",
    "competition",
    "pricing",
    "strategy",
    "go-to-market",
    "gtm",
    "商業模式",
    "benchmark",
]
KEYWORDS_LOW = [
    "文獻綜述",
    "literature review",
    "summary",
    "overview",
    "背景",
    "background",
]

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
NUMBER_RE = re.compile(r"\b\d+(?:[\.,]\d+)?\b")

BASELINE_FULL_COUNCIL_TOKENS = 45_000


def _count_keywords(text: str, keywords: list[str]) -> int:
    lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in lower)


def _estimate_complexity(content: str) -> dict[str, float | int]:
    words = re.findall(r"\w+", content, flags=re.UNICODE)
    word_count = len(words)
    line_count = content.count("\n") + 1
    number_count = len(NUMBER_RE.findall(content))
    citation_count = len(URL_RE.findall(content)) + len(re.findall(r"\[[0-9]+\]", content))

    number_density = number_count / max(1, word_count)
    citation_density = citation_count / max(1, line_count)

    return {
        "word_count": word_count,
        "line_count": line_count,
        "number_count": number_count,
        "citation_count": citation_count,
        "number_density": round(number_density, 4),
        "citation_density": round(citation_density, 4),
    }


def assess_risk(report_path: str) -> dict:
    """Assess report risk level based on content analysis."""
    path = Path(report_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Report not found: {path}")

    content = path.read_text(encoding="utf-8")
    content_lower = content.lower()

    high_hits = _count_keywords(content_lower, KEYWORDS_HIGH)
    medium_hits = _count_keywords(content_lower, KEYWORDS_MEDIUM)
    low_hits = _count_keywords(content_lower, KEYWORDS_LOW)
    complexity = _estimate_complexity(content)

    score = 0
    reasons: list[str] = []

    if high_hits:
        score += high_hits * 4
        reasons.append(f"high-risk keywords x{high_hits}")
    if medium_hits:
        score += medium_hits * 2
        reasons.append(f"medium-risk keywords x{medium_hits}")
    if low_hits:
        score -= min(low_hits, 2)
        reasons.append(f"low-risk indicators x{low_hits}")

    if complexity["word_count"] > 2_500:
        score += 2
        reasons.append("long report (>2500 words)")
    elif complexity["word_count"] < 700:
        score -= 1
        reasons.append("short report (<700 words)")

    if float(complexity["number_density"]) >= 0.10:
        score += 2
        reasons.append("high numeric density (>=10%)")
    elif float(complexity["number_density"]) >= 0.04:
        score += 1
        reasons.append("medium numeric density (>=4%)")

    if int(complexity["citation_count"]) == 0 and int(complexity["number_count"]) >= 8:
        score += 1
        reasons.append("many numeric claims but no citations")

    # Hard override rules
    if high_hits >= 2 and int(complexity["number_count"]) >= 10:
        risk_level: RiskLevel = "high"
        reasons.append("override: strategic/high-impact + many numeric claims")
    elif score >= 8:
        risk_level = "high"
    elif score >= 3:
        risk_level = "medium"
    else:
        risk_level = "low"

    strategy = route_verification(risk_level)

    return {
        "report_path": str(path),
        "risk_level": risk_level,
        "reasoning": "; ".join(reasons) if reasons else "No strong risk indicators",
        "score": score,
        "signals": {
            "high_keyword_hits": high_hits,
            "medium_keyword_hits": medium_hits,
            "low_keyword_hits": low_hits,
            **complexity,
        },
        "verification_strategy": {
            "level": strategy["verification_level"],
            "use_perplexity": strategy["use_perplexity"],
            "models": strategy["models"],
        },
        "estimated_tokens": strategy["estimated_cost"],
    }


def route_verification(risk_level: RiskLevel) -> dict:
    """Return verification strategy based on risk level."""
    if risk_level == "high":
        models = ["codex", "sonnet", "strategic"]
        level = "full_council"
        cost = 45_000
        use_perplexity = False
    elif risk_level == "medium":
        models = ["codex"]
        level = "layer0_plus_layer1"
        cost = 30_000
        use_perplexity = True
    else:
        models = []
        level = "layer0_only"
        cost = 15_000
        use_perplexity = True

    return {
        "risk_level": risk_level,
        "verification_level": level,
        "use_perplexity": use_perplexity,
        "models": models,
        "estimated_cost": cost,
        "estimated_savings_vs_v1": BASELINE_FULL_COUNCIL_TOKENS - cost,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Assess report risk and route verification strategy")
    parser.add_argument("report", help="Path to report markdown/text file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print output")
    args = parser.parse_args()

    try:
        assessment = assess_risk(args.report)
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1) from exc

    indent = 2 if args.pretty else None
    print(json.dumps(assessment, ensure_ascii=False, indent=indent))


if __name__ == "__main__":
    main()
