#!/usr/bin/env python3
"""Perplexity Fact Checker for Model Council.

Extracts verifiable claims from a report and checks them with web_search.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from common import OpenClawClient, OpenClawToolError

MAX_DAILY_QUOTA = 167
QUOTA_STATE_PATH = Path(__file__).resolve().parents[1] / "state" / "perplexity_quota.json"

SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?\.])\s+|\n+")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
NUMBER_HINT_RE = re.compile(r"(\$\s?\d|\d\s?%|\d+(?:\.\d+)?\s?(?:USD|TWD|NTD|million|billion|萬|億))", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

CRITICAL_HINTS = ["價格", "price", "market", "市占", "營收", "revenue", "cagr", "成長率", "投資"]


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _claim_type(sentence: str) -> str:
    lower = sentence.lower()
    if any(k in lower for k in ["$", "usd", "price", "pricing", "價格"]):
        return "price"
    if any(k in lower for k in ["cagr", "%", "growth", "成長", "市占"]):
        return "market_metric"
    if URL_RE.search(sentence) or "according to" in lower or "來源" in sentence:
        return "citation"
    if YEAR_RE.search(sentence):
        return "timeline"
    return "fact"


def _is_verifiable_sentence(sentence: str) -> bool:
    s = sentence.strip()
    if len(s) < 18:
        return False
    return bool(NUMBER_HINT_RE.search(s) or URL_RE.search(s) or YEAR_RE.search(s) or "市場" in s or "market" in s.lower())


def _is_critical(sentence: str) -> bool:
    lower = sentence.lower()
    return any(h in lower for h in CRITICAL_HINTS)


def extract_verifiable_claims(report_content: str) -> list[dict[str, Any]]:
    """Extract claims that can be checked via web search (MVP regex approach)."""
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in SENTENCE_SPLIT_RE.split(report_content):
        sentence = _normalize_spaces(raw)
        if not sentence or not _is_verifiable_sentence(sentence):
            continue

        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)

        claims.append(
            {
                "claim": sentence[:400],
                "type": _claim_type(sentence),
                "critical": _is_critical(sentence),
            }
        )

    # prioritize important + numeric richness
    claims.sort(key=lambda c: (not c["critical"], c["type"] != "price", len(c["claim"])))
    return claims


def _extract_text_and_citations(raw_result: dict[str, Any]) -> tuple[str, list[str]]:
    citations: list[str] = []
    blobs: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str):
                    if k.lower() in {"url", "link", "source"} and v.startswith("http"):
                        citations.append(v)
                    elif len(v) > 20:
                        blobs.append(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            blobs.append(node)
            citations.extend(URL_RE.findall(node))

    walk(raw_result)
    unique_citations = []
    seen = set()
    for u in citations:
        if u not in seen:
            seen.add(u)
            unique_citations.append(u)

    evidence = _normalize_spaces("\n".join(blobs))[:1800]
    return evidence, unique_citations[:10]


def verify_with_perplexity(claim: str) -> dict[str, Any]:
    """Verify one claim via OpenClaw web_search tool."""
    client = OpenClawClient()
    query = f"Verify this claim with sources and current data: {claim}"

    try:
        result = client.invoke_tool(
            "web_search",
            args={
                "query": query,
                "count": 5,
                "country": "ALL",
                "search_lang": "en",
                "ui_lang": "en",
            },
            action="json",
        )
    except OpenClawToolError as exc:
        return {
            "claim": claim,
            "verified": "uncertain",
            "evidence": f"web_search failed: {exc}",
            "citations": [],
            "confidence": 0.0,
            "error": str(exc),
        }

    evidence, citations = _extract_text_and_citations(result)

    lower_evidence = evidence.lower()
    claim_lower = claim.lower()
    overlap_tokens = [t for t in re.findall(r"[a-zA-Z]{4,}|\d+(?:\.\d+)?", claim_lower) if t in lower_evidence]
    confidence = min(0.95, 0.2 + len(set(overlap_tokens)) * 0.06 + min(len(citations), 5) * 0.07)

    if len(citations) >= 2 and confidence >= 0.55:
        verdict: bool | str = True
    elif confidence < 0.35:
        verdict = False
    else:
        verdict = "uncertain"

    return {
        "claim": claim,
        "verified": verdict,
        "evidence": evidence or "No evidence extracted",
        "citations": citations,
        "confidence": round(confidence, 2),
    }


def _load_quota_state() -> dict[str, Any]:
    if not QUOTA_STATE_PATH.exists():
        return {"date": datetime.now().strftime("%Y-%m-%d"), "used": 0}
    try:
        return json.loads(QUOTA_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"date": datetime.now().strftime("%Y-%m-%d"), "used": 0}


def _save_quota_state(state: dict[str, Any]) -> None:
    QUOTA_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUOTA_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _available_quota() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    state = _load_quota_state()
    if state.get("date") != today:
        state = {"date": today, "used": 0}
        _save_quota_state(state)
    used = int(state.get("used", 0))
    return max(0, MAX_DAILY_QUOTA - used)


def _consume_quota(n: int) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    state = _load_quota_state()
    if state.get("date") != today:
        state = {"date": today, "used": 0}
    state["used"] = int(state.get("used", 0)) + n
    state["date"] = today
    _save_quota_state(state)


def batch_verify(claims: list[dict[str, Any]], max_queries: int = 10) -> dict[str, Any]:
    """Batch verify claims, prioritizing critical ones and enforcing daily quota."""
    quota_left = _available_quota()
    if quota_left <= 0:
        return {
            "summary": {"verified": 0, "failed": 0, "uncertain": 0},
            "quota": {"daily_limit": MAX_DAILY_QUOTA, "available": 0, "used_now": 0},
            "results": [],
            "warning": "Perplexity quota exhausted for today",
        }

    ordered = sorted(claims, key=lambda c: (not bool(c.get("critical")), c.get("type", "")))
    allowed = min(max_queries, quota_left, len(ordered))
    selected = ordered[:allowed]

    results: list[dict[str, Any]] = []
    for claim_obj in selected:
        claim_text = str(claim_obj.get("claim", "")).strip()
        if not claim_text:
            continue
        res = verify_with_perplexity(claim_text)
        res["type"] = claim_obj.get("type")
        res["critical"] = bool(claim_obj.get("critical"))
        results.append(res)

    _consume_quota(len(results))

    summary = {
        "verified": sum(1 for r in results if r.get("verified") is True),
        "failed": sum(1 for r in results if r.get("verified") is False),
        "uncertain": sum(1 for r in results if r.get("verified") == "uncertain"),
    }

    return {
        "summary": summary,
        "quota": {
            "daily_limit": MAX_DAILY_QUOTA,
            "available_before": quota_left,
            "used_now": len(results),
            "available_after": max(0, quota_left - len(results)),
        },
        "results": results,
        "total_claims_detected": len(claims),
        "claims_verified": len(results),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract and verify report claims via Perplexity web_search")
    parser.add_argument("report", help="Path to report markdown/text file")
    parser.add_argument("--max-queries", type=int, default=10, help="Max queries to run (default: 10)")
    args = parser.parse_args()

    report_path = Path(args.report).expanduser().resolve()
    if not report_path.exists():
        print(f"ERROR: report not found: {report_path}")
        raise SystemExit(1)

    content = report_path.read_text(encoding="utf-8")
    claims = extract_verifiable_claims(content)
    result = batch_verify(claims, max_queries=max(1, args.max_queries))

    output = {
        "report": str(report_path),
        "claims_preview": claims[:15],
        "verification": result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
