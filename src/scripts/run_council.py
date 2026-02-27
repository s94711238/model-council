#!/usr/bin/env python3
"""End-to-end Model Council orchestrator.

Chains: dispatch_v2 → collect → synthesize in a single command.

Usage:
    python run_council.py report.md
    python run_council.py report.md --max-queries 3 --timeout 600
    python run_council.py report.md --v1   # use V1 (full council, no risk routing)
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parent


def _run_script(script_name: str, args: list[str], label: str) -> str:
    """Run a council script and return its stdout."""
    cmd = [sys.executable, str(SCRIPTS_DIR / script_name), *args]
    logger.info("[%s] Running: %s", label, " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPTS_DIR.parents[1]))
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            logger.info("[%s] %s", label, line)
    if result.returncode != 0:
        logger.error("[%s] Failed (exit %d):\n%s", label, result.returncode, result.stdout + result.stderr)
        raise SystemExit(f"Stage '{label}' failed with exit code {result.returncode}")
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full Model Council pipeline: dispatch → collect → synthesize",
    )
    parser.add_argument("primary_report", help="Path to primary report markdown file")
    parser.add_argument("--max-queries", type=int, default=5, help="Max Perplexity queries for pre-check (default: 5)")
    parser.add_argument("--timeout", type=int, default=900, help="Max seconds to wait for sub-agents (default: 900)")
    parser.add_argument("--poll", type=int, default=15, help="Poll interval in seconds (default: 15)")
    parser.add_argument("--v1", action="store_true", help="Use V1 dispatcher (full council, no risk routing)")
    args = parser.parse_args()

    report_path = Path(args.primary_report).expanduser().resolve()
    if not report_path.exists():
        raise SystemExit(f"Report not found: {report_path}")

    # ── Stage 1: Dispatch ──
    logger.info("=" * 60)
    logger.info("STAGE 1: Dispatching verification sub-agents")
    logger.info("=" * 60)

    if args.v1:
        dispatch_out = _run_script("dispatch.py", [str(report_path)], "dispatch-v1")
    else:
        dispatch_out = _run_script(
            "dispatch_v2.py",
            [str(report_path), "--max-queries", str(args.max_queries), "--full"],
            "dispatch-v2",
        )

    try:
        dispatch_data = json.loads(dispatch_out)
    except json.JSONDecodeError:
        raise SystemExit(f"Cannot parse dispatch output as JSON:\n{dispatch_out[:500]}")

    # Find dispatch.json file to pass to collect
    run_ids: dict[str, str] = dispatch_data if args.v1 else dispatch_data.get("run_ids", {})
    if not run_ids:
        raise SystemExit("Dispatch produced no run IDs.")

    # Locate the dispatch.json on disk
    dispatch_json_path = _find_latest_dispatch_json()
    if not dispatch_json_path:
        raise SystemExit("Cannot find dispatch.json in references/council-runs/")

    logger.info("Dispatched %d model(s): %s", len(run_ids), ", ".join(run_ids.keys()))
    if not args.v1:
        risk = dispatch_data.get("risk_level", "?")
        savings = dispatch_data.get("estimated_savings", 0)
        logger.info("Risk level: %s | Estimated token savings: %d", risk, savings)

    # ── Stage 2: Collect ──
    logger.info("=" * 60)
    logger.info("STAGE 2: Collecting sub-agent outputs (timeout=%ds)", args.timeout)
    logger.info("=" * 60)

    collect_out = _run_script(
        "collect.py",
        ["--dispatch", str(dispatch_json_path), "--timeout", str(args.timeout), "--poll", str(args.poll)],
        "collect",
    )

    try:
        collect_data = json.loads(collect_out)
    except json.JSONDecodeError:
        raise SystemExit(f"Cannot parse collect output as JSON:\n{collect_out[:500]}")

    manifest_path = collect_data.get("manifest")
    if not manifest_path or not Path(manifest_path).exists():
        raise SystemExit(f"Manifest not found at: {manifest_path}")

    outputs = collect_data.get("outputs", {})
    success = sum(1 for o in outputs.values() if o.get("status") == "done" and o.get("output_length", 0) > 0)
    logger.info("Collected %d/%d successful outputs.", success, len(outputs))

    if success < 2:
        logger.error("Need at least 2 successful verifications to synthesize. Got %d.", success)
        raise SystemExit("Insufficient verifications for synthesis.")

    # ── Stage 3: Synthesize ──
    logger.info("=" * 60)
    logger.info("STAGE 3: Synthesizing final report")
    logger.info("=" * 60)

    run_dir = str(Path(manifest_path).parent)
    synth_out = _run_script("synthesize.py", [run_dir], "synthesize")

    try:
        synth_data = json.loads(synth_out)
    except json.JSONDecodeError:
        raise SystemExit(f"Cannot parse synthesize output as JSON:\n{synth_out[:500]}")

    final_report = synth_data.get("output", "?")
    structured = synth_data.get("structured_mode", False)

    logger.info("=" * 60)
    logger.info("DONE — Final report: %s", final_report)
    logger.info("Structured consensus mode: %s", structured)
    if "aggregate" in synth_data:
        agg = synth_data["aggregate"]
        logger.info(
            "Council verdict: %s (%d/%d) | Avg confidence: %s",
            agg.get("majority_verdict", "?"),
            agg.get("majority_count", 0),
            len(agg.get("verdicts", {})),
            agg.get("avg_confidence", "?"),
        )
    logger.info("=" * 60)

    print(json.dumps(synth_data, ensure_ascii=False, indent=2))


def _find_latest_dispatch_json() -> Path | None:
    """Find the most recent dispatch.json in references/council-runs/."""
    runs_dir = Path("references") / "council-runs"
    if not runs_dir.exists():
        return None
    candidates = sorted(runs_dir.iterdir(), reverse=True)
    for d in candidates:
        p = d / "dispatch.json"
        if p.exists():
            return p
    return None


if __name__ == "__main__":
    main()
