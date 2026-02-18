#!/usr/bin/env python3
"""Synthesize Model Council verification outputs into final report."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from common import project_root


def _normalize_line(line: str) -> str:
    text = line.strip().lower()
    text = re.sub(r"^[\-\*\d\.\)\s]+", "", text)
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _extract_key_lines(markdown_text: str, max_lines: int = 20) -> list[str]:
    lines: list[str] = []
    for raw in markdown_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if len(line) < 24:
            continue
        if line.startswith("#"):
            continue
        norm = _normalize_line(line)
        if len(norm) < 20:
            continue
        lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines


def _build_consensus_and_divergence(verifications: dict[str, str]) -> tuple[list[str], dict[str, list[str]]]:
    normalized_to_raw: dict[str, str] = {}
    per_model: dict[str, set[str]] = {}

    for role, content in verifications.items():
        key_lines = _extract_key_lines(content)
        norm_set: set[str] = set()
        for line in key_lines:
            norm = _normalize_line(line)
            if not norm:
                continue
            norm_set.add(norm)
            normalized_to_raw.setdefault(norm, line)
        per_model[role] = norm_set

    counts = Counter()
    for norm_set in per_model.values():
        counts.update(norm_set)

    consensus_norm = [n for n, c in counts.items() if c >= 2]
    consensus = [normalized_to_raw[n] for n in consensus_norm[:8]]

    divergence: dict[str, list[str]] = {}
    for role, norm_set in per_model.items():
        unique_norms = [n for n in norm_set if counts[n] == 1]
        divergence[role] = [normalized_to_raw[n] for n in unique_norms[:5]]

    return consensus, divergence


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in {run_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _load_verification_text(run_dir: Path, output_meta: dict[str, Any]) -> str:
    result_file = output_meta.get("result_file")
    if isinstance(result_file, str) and Path(result_file).exists():
        return Path(result_file).read_text(encoding="utf-8").strip()

    role_guess = output_meta.get("role")
    if isinstance(role_guess, str):
        p = run_dir / f"{role_guess}.md"
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return ""


def _topic_from_primary(primary_path: str | None, fallback: str) -> str:
    if primary_path:
        stem = Path(primary_path).stem
        stem = re.sub(r"[^A-Za-z0-9\-]+", "-", stem).strip("-")
        if stem:
            return stem
    return fallback


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize Model Council outputs")
    parser.add_argument("verification_dir", help="Path to references/council-runs/<timestamp>/")
    args = parser.parse_args()

    run_dir = Path(args.verification_dir).resolve()
    if not run_dir.exists():
        raise SystemExit(f"Directory not found: {run_dir}")

    manifest = _load_manifest(run_dir)
    outputs = manifest.get("outputs", {})
    if not isinstance(outputs, dict):
        raise SystemExit("Invalid manifest: outputs missing")

    primary_report_path = manifest.get("primary_report")
    if not isinstance(primary_report_path, str) or not Path(primary_report_path).exists():
        raise SystemExit("Invalid manifest: primary_report missing or file not found")

    primary_text = Path(primary_report_path).read_text(encoding="utf-8")

    verifications: dict[str, str] = {}
    success_count = 0

    for role in ("codex", "sonnet", "strategic"):
        info = outputs.get(role, {})
        if not isinstance(info, dict):
            continue
        status = str(info.get("status", "")).lower()
        text = _load_verification_text(run_dir, info)
        if status == "done" and text and text != "No response":
            success_count += 1
            verifications[role] = text
        else:
            verifications[role] = "No response"

    if success_count < 2:
        raise SystemExit("Need at least 2 successful verification models to synthesize final report")

    consensus, divergence = _build_consensus_and_divergence(verifications)

    consensus_md = "\n".join(f"- {line}" for line in consensus) if consensus else "- Limited explicit consensus extracted."

    divergence_lines: list[str] = []
    for role in ("codex", "sonnet", "strategic"):
        divergence_lines.append(f"### {role.capitalize()}")
        model_lines = divergence.get(role, [])
        if not model_lines:
            divergence_lines.append("- No strong unique disagreement extracted.")
        else:
            divergence_lines.extend(f"- {line}" for line in model_lines)
    divergence_md = "\n".join(divergence_lines)

    final_assessment = [
        "Validation completed using 3-model council review.",
        f"Successful verifiers: {success_count}/3.",
        "Adopt consensus items as high-confidence corrections.",
        "Treat divergence items as follow-up checks before external publication.",
        "If divergence affects core conclusions, run an additional targeted verification pass.",
    ]
    final_assessment_md = "\n".join(f"- {line}" for line in final_assessment)

    synthesis_template = (project_root() / "templates" / "synthesis.md").read_text(encoding="utf-8")

    topic = _topic_from_primary(primary_report_path, fallback=run_dir.name)

    final_report = (
        synthesis_template.replace("[TOPIC]", topic)
        .replace("[PRIMARY_REPORT]", primary_text)
        .replace("[CODEX_VERIFICATION]", verifications.get("codex", "No response"))
        .replace("[SONNET_VERIFICATION]", verifications.get("sonnet", "No response"))
        .replace("[STRATEGIC_VERIFICATION]", verifications.get("strategic", "No response"))
        .replace("[CONSENSUS]", consensus_md)
        .replace("[DIVERGENCES]", divergence_md)
        .replace("[FINAL_ASSESSMENT]", final_assessment_md)
    )

    out_path = Path("references") / f"{topic}-council-final.md"
    out_path.write_text(final_report, encoding="utf-8")

    print(json.dumps({"output": str(out_path), "success_models": success_count}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
