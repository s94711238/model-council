#!/usr/bin/env python3
"""Collect Model Council sub-agent outputs into structured run directory."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from common import OpenClawClient, OpenClawToolError, extract_text_from_message

TERMINAL_STATUSES = {"done", "error", "failed", "timeout", "killed", "cancelled"}


def _parse_run_ids(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("{"):
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("JSON run ids must be an object")
        return [str(v) for v in parsed.values()]

    parts: list[str] = []
    for token in raw.replace("\n", ",").split(","):
        token = token.strip()
        if token:
            parts.append(token)
    if not parts:
        raise ValueError("No run IDs provided")
    return parts


def _load_dispatch(dispatch_path: Path) -> tuple[dict[str, str], dict[str, str], str | None]:
    payload = json.loads(dispatch_path.read_text(encoding="utf-8"))
    run_ids = payload.get("run_ids", {})
    session_keys = payload.get("session_keys", {})
    primary_report = payload.get("primary_report")
    if not isinstance(run_ids, dict):
        raise ValueError("dispatch.json missing run_ids")
    return ({k: str(v) for k, v in run_ids.items()}, {k: str(v) for k, v in session_keys.items()}, str(primary_report) if primary_report else None)


def _map_roles(run_ids: list[str], role_map: dict[str, str]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    used: set[str] = set()
    for role, run_id in role_map.items():
        if run_id in run_ids:
            mapped[role] = run_id
            used.add(run_id)

    remaining = [r for r in run_ids if r not in used]
    for role in ("codex", "sonnet", "strategic"):
        if role not in mapped and remaining:
            mapped[role] = remaining.pop(0)

    for idx, run_id in enumerate(remaining, start=1):
        mapped[f"extra_{idx}"] = run_id
    return mapped


def _fetch_subagent_index(client: OpenClawClient) -> dict[str, dict[str, Any]]:
    result = client.invoke_tool("subagents", args={"action": "list"}, action="list")
    details = result.get("details") if isinstance(result.get("details"), dict) else {}

    rows: list[dict[str, Any]] = []
    for key in ("active", "recent"):
        value = details.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    rows.append(item)

    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        run_id = row.get("runId")
        if isinstance(run_id, str) and run_id:
            index[run_id] = row
    return index


def _wait_until_done(client: OpenClawClient, target_run_ids: set[str], timeout_seconds: int, poll_seconds: int) -> dict[str, dict[str, Any]]:
    deadline = time.time() + timeout_seconds
    latest: dict[str, dict[str, Any]] = {}

    while time.time() < deadline:
        index = _fetch_subagent_index(client)
        for run_id in target_run_ids:
            if run_id in index:
                latest[run_id] = index[run_id]

        terminal_count = 0
        for run_id in target_run_ids:
            status = str(latest.get(run_id, {}).get("status", "unknown")).lower()
            if status in TERMINAL_STATUSES:
                terminal_count += 1

        if terminal_count == len(target_run_ids):
            return latest

        time.sleep(max(3, poll_seconds))

    # timeout: mark missing as timeout
    for run_id in target_run_ids:
        if run_id not in latest:
            latest[run_id] = {"runId": run_id, "status": "timeout"}
        elif str(latest[run_id].get("status", "")).lower() not in TERMINAL_STATUSES:
            latest[run_id]["status"] = "timeout"
    return latest


def _extract_final_assistant_text(client: OpenClawClient, session_key: str) -> tuple[str, list[dict[str, Any]]]:
    history = client.invoke_tool(
        "sessions_history",
        args={"sessionKey": session_key, "limit": 200, "includeTools": False},
        action="json",
    )
    details = history.get("details") if isinstance(history.get("details"), dict) else {}
    messages = details.get("messages") if isinstance(details.get("messages"), list) else []

    final_text = ""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue
        text = extract_text_from_message(msg)
        if text:
            final_text = text

    return final_text, messages


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Model Council sub-agent outputs")
    parser.add_argument("run_ids", nargs="?", help="Comma-separated run IDs or JSON object string")
    parser.add_argument("--dispatch", help="Path to dispatch.json produced by dispatch.py")
    parser.add_argument("--timeout", type=int, default=900, help="Max seconds to wait (default: 900)")
    parser.add_argument("--poll", type=int, default=15, help="Poll interval in seconds (default: 15)")
    args = parser.parse_args()

    if not args.run_ids and not args.dispatch:
        raise SystemExit("Provide run_ids or --dispatch")

    role_run_ids: dict[str, str] = {}
    role_session_keys: dict[str, str] = {}
    primary_report: str | None = None

    if args.dispatch:
        dispatch_path = Path(args.dispatch)
        if not dispatch_path.exists():
            raise SystemExit(f"dispatch file not found: {dispatch_path}")
        role_run_ids, role_session_keys, primary_report = _load_dispatch(dispatch_path)

    provided_run_ids = _parse_run_ids(args.run_ids) if args.run_ids else list(role_run_ids.values())
    if not provided_run_ids:
        raise SystemExit("No run IDs resolved")

    client = OpenClawClient()
    status_map = _wait_until_done(client, set(provided_run_ids), timeout_seconds=args.timeout, poll_seconds=args.poll)

    role_map = _map_roles(provided_run_ids, role_run_ids)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path("references") / "council-runs" / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    model_outputs: dict[str, dict[str, Any]] = {}

    for role, run_id in role_map.items():
        row = status_map.get(run_id, {"runId": run_id, "status": "timeout"})
        status = str(row.get("status", "unknown")).lower()
        session_key = role_session_keys.get(role) or row.get("sessionKey")

        output_text = "No response"
        raw_messages: list[dict[str, Any]] = []

        if isinstance(session_key, str) and session_key and status in TERMINAL_STATUSES and status != "timeout":
            try:
                output_text, raw_messages = _extract_final_assistant_text(client, session_key)
                if not output_text:
                    output_text = "No response"
            except OpenClawToolError:
                output_text = "No response"

        role_file = out_dir / f"{role}.md"
        role_file.write_text(output_text, encoding="utf-8")

        (out_dir / f"{role}.history.json").write_text(
            json.dumps(raw_messages, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        model_outputs[role] = {
            "run_id": run_id,
            "status": status,
            "session_key": session_key,
            "result_file": str(role_file),
            "history_file": str(out_dir / f"{role}.history.json"),
        }

    manifest = {
        "timestamp": timestamp,
        "primary_report": primary_report,
        "run_ids": role_run_ids,
        "outputs": model_outputs,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"manifest": str(manifest_path), "outputs": model_outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
