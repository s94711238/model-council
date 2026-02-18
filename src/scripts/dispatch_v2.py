#!/usr/bin/env python3
"""Optimized Model Council Dispatcher (V2).

Integrates risk assessment + Perplexity pre-check, then dispatches only needed models.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from common import OpenClawClient, OpenClawToolError, project_root
from perplexity_check import batch_verify, extract_verifiable_claims
from risk_router import BASELINE_FULL_COUNCIL_TOKENS, assess_risk, route_verification

MODELS: dict[str, str] = {
    "codex": "openai-codex/gpt-5.3-codex",
    "sonnet": "google-antigravity/gemini-3-pro-high",
    "strategic": "google-antigravity/gemini-3-pro-high",
}


def load_template(template_path: str, report_content: str, context: str = "") -> str:
    raw = Path(template_path).read_text(encoding="utf-8")
    prompt = raw.replace("[PRIMARY_REPORT]", report_content)
    if context:
        prompt += f"\n\n---\nPerplexity fact-check context (V2):\n{context}\n"
    return prompt


def _extract_spawn_result(result: dict[str, Any]) -> tuple[str, str | None]:
    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    run_id = details.get("runId")
    child_key = details.get("childSessionKey")

    if isinstance(run_id, str) and run_id:
        return run_id, child_key if isinstance(child_key, str) else None

    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if not isinstance(text, str):
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            run_id = parsed.get("runId")
            child_key = parsed.get("childSessionKey")
            if isinstance(run_id, str) and run_id:
                return run_id, child_key if isinstance(child_key, str) else None

    raise OpenClawToolError(f"Cannot parse sessions_spawn result: {result}")


def _build_perplexity_context(perplexity_results: dict[str, Any]) -> str:
    if not perplexity_results:
        return "No Perplexity check executed."

    lines: list[str] = []
    summary = perplexity_results.get("summary", {})
    if isinstance(summary, dict):
        lines.append(f"summary={summary}")

    results = perplexity_results.get("results", [])
    if isinstance(results, list):
        for row in results[:8]:
            if not isinstance(row, dict):
                continue
            claim = str(row.get("claim", ""))[:180]
            verdict = row.get("verified")
            confidence = row.get("confidence")
            lines.append(f"- [{verdict} @ {confidence}] {claim}")

    return "\n".join(lines) if lines else "Perplexity run with empty output."


def dispatch_council_v2(primary_report_path: str, max_queries: int = 5) -> dict[str, Any]:
    """Enhanced dispatcher with risk-adaptive routing."""
    script_dir = project_root()
    templates_dir = script_dir / "templates"

    report_path = Path(primary_report_path).expanduser().resolve()
    if not report_path.exists():
        raise FileNotFoundError(f"Primary report not found: {report_path}")

    report_content = report_path.read_text(encoding="utf-8")

    # 1) Risk assessment
    risk_info = assess_risk(str(report_path))
    risk_level = risk_info["risk_level"]

    # 2) Perplexity pre-check for low/medium
    perplexity_results: dict[str, Any] = {}
    extracted_claims: list[dict[str, Any]] = []
    if risk_level in {"low", "medium"}:
        extracted_claims = extract_verifiable_claims(report_content)
        perplexity_results = batch_verify(extracted_claims, max_queries=max_queries)

    # 3) Route verification
    strategy = route_verification(risk_level)
    target_models = strategy["models"]

    # Escalation gate (MVP): if critical claims are contradicted/unresolved, add sonnet
    escalation_triggered = False
    if risk_level in {"low", "medium"} and isinstance(perplexity_results.get("results"), list):
        bad_critical = [
            r
            for r in perplexity_results["results"]
            if isinstance(r, dict)
            and r.get("critical") is True
            and r.get("verified") in {False, "uncertain"}
        ]
        if bad_critical and "sonnet" not in target_models:
            target_models = [*target_models, "sonnet"]
            escalation_triggered = True

    client = OpenClawClient()
    run_ids: dict[str, str] = {}
    session_keys: dict[str, str] = {}

    perplexity_context = _build_perplexity_context(perplexity_results)

    # 4) Dispatch only routed models
    for role in target_models:
        template = templates_dir / f"{role}.md"
        if not template.exists():
            raise FileNotFoundError(f"Missing template for role={role}: {template}")

        prompt = load_template(str(template), report_content, context=perplexity_context)
        args = {
            "task": prompt,
            "model": MODELS[role],
            "label": f"model-council-v2-{role}-{report_path.stem}",
            "cleanup": "keep",
            "runTimeoutSeconds": 900,
        }
        result = client.invoke_tool("sessions_spawn", args=args, action="json")
        run_id, child_key = _extract_spawn_result(result)
        run_ids[role] = run_id
        if child_key:
            session_keys[role] = child_key

    estimated_cost = int(strategy["estimated_cost"])
    if escalation_triggered:
        estimated_cost += 10_000

    final = {
        "risk_level": risk_level,
        "risk_info": risk_info,
        "perplexity_results": perplexity_results,
        "dispatched_models": target_models,
        "run_ids": run_ids,
        "session_keys": session_keys,
        "estimated_cost": estimated_cost,
        "cost_baseline_v1": BASELINE_FULL_COUNCIL_TOKENS,
        "estimated_savings": BASELINE_FULL_COUNCIL_TOKENS - estimated_cost,
        "escalation_triggered": escalation_triggered,
    }

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path("references") / "council-runs" / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "dispatch_v2.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    # For compatibility with collect.py / existing workflow
    compat_manifest = {
        "timestamp": timestamp,
        "primary_report": str(report_path),
        "run_ids": run_ids,
        "session_keys": session_keys,
        "models": {k: MODELS[k] for k in target_models},
        "v2": {
            "risk_level": risk_level,
            "estimated_cost": estimated_cost,
            "estimated_savings": BASELINE_FULL_COUNCIL_TOKENS - estimated_cost,
        },
    }
    (out_dir / "dispatch.json").write_text(json.dumps(compat_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return final


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch Model Council V2 (risk-adaptive)")
    parser.add_argument("primary_report", help="Path to primary report markdown")
    parser.add_argument("--max-queries", type=int, default=5, help="Max Perplexity queries for pre-check")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Print full V2 payload. Default prints run_ids only (dispatch.py compatible)",
    )
    args = parser.parse_args()

    try:
        result = dispatch_council_v2(args.primary_report, max_queries=max(1, args.max_queries))
    except OpenClawToolError as exc:
        text = str(exc)
        if "sessions_spawn" in text and "Tool not available" in text:
            print("ERROR: sessions_spawn is blocked for HTTP /tools/invoke.")
            print("Hint: set gateway.tools.allow = ['sessions_spawn'] in OpenClaw config.")
        else:
            print(f"ERROR: {exc}")
        raise SystemExit(1) from exc
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1) from exc

    if args.full:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["run_ids"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
