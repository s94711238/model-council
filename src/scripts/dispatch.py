#!/usr/bin/env python3
"""Dispatch 3 Model Council verification sub-agents."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from common import OpenClawClient, OpenClawToolError, project_root


MODELS: dict[str, str] = {
    "codex": "openai-codex/gpt-5.3-codex",
    "sonnet": "google-antigravity/gemini-3-pro-high",
    "strategic": "google-antigravity/gemini-3-pro-high",
}


def load_template(template_path: str, report_content: str) -> str:
    """Replace [PRIMARY_REPORT] with actual content."""
    raw = Path(template_path).read_text(encoding="utf-8")
    return raw.replace("[PRIMARY_REPORT]", report_content)


def _extract_spawn_result(result: dict[str, Any]) -> tuple[str, str | None]:
    details = result.get("details") if isinstance(result.get("details"), dict) else {}

    run_id = details.get("runId")
    child_key = details.get("childSessionKey")

    if isinstance(run_id, str) and run_id:
        return run_id, child_key if isinstance(child_key, str) else None

    # Fallback: parse JSON in content text
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


def dispatch_council(primary_report_path: str) -> dict[str, str]:
    """Returns {'codex': run_id, 'sonnet': run_id, 'strategic': run_id}."""
    script_dir = project_root()
    templates_dir = script_dir / "templates"

    report_path = Path(primary_report_path).resolve()
    if not report_path.exists():
        raise FileNotFoundError(f"Primary report not found: {report_path}")

    report_content = report_path.read_text(encoding="utf-8")
    client = OpenClawClient()

    prompts = {
        role: load_template(str(templates_dir / f"{role}.md"), report_content)
        for role in ("codex", "sonnet", "strategic")
    }

    run_ids: dict[str, str] = {}
    session_keys: dict[str, str] = {}

    for role, prompt in prompts.items():
        args = {
            "task": prompt,
            "model": MODELS[role],
            "label": f"model-council-{role}-{report_path.stem}",
            "cleanup": "keep",
            "runTimeoutSeconds": 900,
        }
        result = client.invoke_tool("sessions_spawn", args=args, action="json")
        run_id, child_key = _extract_spawn_result(result)
        run_ids[role] = run_id
        if child_key:
            session_keys[role] = child_key

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path("references") / "council-runs" / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    dispatch_manifest = {
        "timestamp": timestamp,
        "primary_report": str(report_path),
        "run_ids": run_ids,
        "session_keys": session_keys,
        "models": MODELS,
    }
    (out_dir / "dispatch.json").write_text(json.dumps(dispatch_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return run_ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch 3 Model Council verification sub-agents")
    parser.add_argument("primary_report", help="Path to primary report markdown")
    args = parser.parse_args()

    try:
        run_ids = dispatch_council(args.primary_report)
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

    print(json.dumps(run_ids, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
