#!/usr/bin/env python3
"""Synthesize Model Council verification outputs into final report.

V2: Parses structured JSON blocks from verifier output for reliable
consensus/divergence detection, with fallback to legacy line matching.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from common import project_root

VALID_VERDICTS = {"pass", "pass_with_caveats", "fail"}

# Regex to extract fenced JSON block from verifier markdown output
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(\{.*?\})\s*\n```", re.DOTALL)


def _parse_structured_block(markdown_text: str) -> dict[str, Any] | None:
    """Extract and validate the structured JSON block from verifier output."""
    match = _JSON_BLOCK_RE.search(markdown_text)
    if not match:
        return None

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    verdict = data.get("verdict")
    if isinstance(verdict, str):
        data["verdict"] = verdict.lower().strip()

    confidence = data.get("confidence")
    if isinstance(confidence, (int, float)):
        data["confidence"] = max(0, min(100, int(confidence)))
    else:
        data["confidence"] = None

    for key in ("critical_issues", "non_critical_issues", "unsupported_claims", "key_findings"):
        val = data.get(key)
        if not isinstance(val, list):
            data[key] = []
        else:
            data[key] = [str(item) for item in val if item]

    return data


# ---------------------------------------------------------------------------
# Legacy fallback: line-based consensus (kept for backward compatibility)
# ---------------------------------------------------------------------------

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


def _build_legacy_consensus(verifications: dict[str, str]) -> tuple[list[str], dict[str, list[str]]]:
    """Original line-matching consensus (fallback when structured data unavailable)."""
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


# ---------------------------------------------------------------------------
# Structured consensus: uses parsed JSON blocks from verifier outputs
# ---------------------------------------------------------------------------

def _build_structured_consensus(
    structured: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, list[str]], dict[str, Any]]:
    """Build consensus and divergence from structured verifier JSON blocks.

    Returns (consensus_lines, divergence_dict, aggregate_stats).
    """
    # --- Verdict consensus ---
    verdicts = {role: d.get("verdict", "unknown") for role, d in structured.items()}
    verdict_counts = Counter(verdicts.values())
    majority_verdict, majority_count = verdict_counts.most_common(1)[0]

    # --- Confidence aggregation ---
    confidences = {role: d.get("confidence") for role, d in structured.items()}
    valid_conf = [c for c in confidences.values() if c is not None]
    avg_confidence = round(sum(valid_conf) / len(valid_conf), 1) if valid_conf else None
    min_confidence = min(valid_conf) if valid_conf else None

    # --- Issue cross-referencing ---
    # Collect all critical issues and find overlap
    all_critical: dict[str, list[str]] = {}
    for role, d in structured.items():
        all_critical[role] = d.get("critical_issues", [])

    # Find issues mentioned by 2+ models (normalized comparison)
    issue_sources: dict[str, list[str]] = {}  # normalized -> [roles]
    issue_raw: dict[str, str] = {}  # normalized -> original text
    for role, issues in all_critical.items():
        for issue in issues:
            norm = _normalize_line(issue)
            if len(norm) < 10:
                continue
            issue_sources.setdefault(norm, []).append(role)
            issue_raw.setdefault(norm, issue)

    consensus_issues = [
        issue_raw[norm] for norm, roles in issue_sources.items() if len(roles) >= 2
    ]

    # --- Unsupported claims cross-referencing ---
    all_unsupported: dict[str, list[str]] = {}
    for role, d in structured.items():
        all_unsupported[role] = d.get("unsupported_claims", [])

    claim_sources: dict[str, list[str]] = {}
    claim_raw: dict[str, str] = {}
    for role, claims in all_unsupported.items():
        for claim in claims:
            norm = _normalize_line(claim)
            if len(norm) < 10:
                continue
            claim_sources.setdefault(norm, []).append(role)
            claim_raw.setdefault(norm, claim)

    consensus_unsupported = [
        claim_raw[norm] for norm, roles in claim_sources.items() if len(roles) >= 2
    ]

    # --- Build consensus lines ---
    consensus_lines: list[str] = []
    if majority_count >= 2:
        label = majority_verdict.replace("_", " ").title()
        consensus_lines.append(f"Council verdict: **{label}** ({majority_count}/{len(structured)} models agree)")
    if avg_confidence is not None:
        consensus_lines.append(f"Average confidence: {avg_confidence}/100 (min: {min_confidence})")
    for issue in consensus_issues[:5]:
        consensus_lines.append(f"Shared critical issue: {issue}")
    for claim in consensus_unsupported[:3]:
        consensus_lines.append(f"Shared unsupported claim: {claim}")

    # --- Key findings aggregation ---
    for role, d in structured.items():
        for finding in d.get("key_findings", [])[:2]:
            consensus_lines.append(f"[{role}] {finding}")

    # --- Build divergence ---
    divergence: dict[str, list[str]] = {}
    for role, d in structured.items():
        unique: list[str] = []
        # Issues only this model flagged
        for issue in d.get("critical_issues", []):
            norm = _normalize_line(issue)
            if norm in issue_sources and len(issue_sources[norm]) == 1:
                unique.append(f"[critical] {issue}")
        for issue in d.get("non_critical_issues", [])[:3]:
            unique.append(f"[minor] {issue}")
        # Verdict divergence
        if verdicts[role] != majority_verdict and majority_count >= 2:
            v = verdicts[role].replace("_", " ").title()
            unique.insert(0, f"Verdict divergence: {v} (vs majority {majority_verdict.replace('_', ' ').title()})")
        divergence[role] = unique[:5]

    aggregate = {
        "verdicts": verdicts,
        "majority_verdict": majority_verdict,
        "majority_count": majority_count,
        "confidences": confidences,
        "avg_confidence": avg_confidence,
        "min_confidence": min_confidence,
        "consensus_critical_issues": len(consensus_issues),
        "consensus_unsupported_claims": len(consensus_unsupported),
    }

    return consensus_lines, divergence, aggregate


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

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
    structured_blocks: dict[str, dict[str, Any]] = {}
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
            parsed = _parse_structured_block(text)
            if parsed is not None:
                structured_blocks[role] = parsed
        else:
            verifications[role] = "No response"

    if success_count < 2:
        raise SystemExit("Need at least 2 successful verification models to synthesize final report")

    # --- Decide strategy: structured vs legacy ---
    use_structured = len(structured_blocks) >= 2
    aggregate_stats: dict[str, Any] | None = None

    if use_structured:
        consensus_items, divergence, aggregate_stats = _build_structured_consensus(structured_blocks)
        consensus_md = "\n".join(f"- {line}" for line in consensus_items) if consensus_items else "- Limited consensus extracted."
    else:
        consensus_items, divergence = _build_legacy_consensus(verifications)
        consensus_md = "\n".join(f"- {line}" for line in consensus_items) if consensus_items else "- Limited explicit consensus extracted."

    divergence_lines: list[str] = []
    for role in ("codex", "sonnet", "strategic"):
        divergence_lines.append(f"### {role.capitalize()}")
        model_lines = divergence.get(role, [])
        if not model_lines:
            divergence_lines.append("- No strong unique disagreement extracted.")
        else:
            divergence_lines.extend(f"- {line}" for line in model_lines)
    divergence_md = "\n".join(divergence_lines)

    # --- Build final assessment ---
    final_assessment = [
        "Validation completed using 3-model council review.",
        f"Successful verifiers: {success_count}/3.",
    ]

    if aggregate_stats:
        mv = aggregate_stats["majority_verdict"].replace("_", " ").title()
        final_assessment.append(f"Council majority verdict: **{mv}** ({aggregate_stats['majority_count']}/{len(structured_blocks)} agree).")
        if aggregate_stats["avg_confidence"] is not None:
            final_assessment.append(f"Average confidence: {aggregate_stats['avg_confidence']}/100 (min: {aggregate_stats['min_confidence']}).")
        if aggregate_stats["consensus_critical_issues"] > 0:
            final_assessment.append(f"{aggregate_stats['consensus_critical_issues']} critical issue(s) flagged by multiple models — address before publication.")
        if aggregate_stats["consensus_unsupported_claims"] > 0:
            final_assessment.append(f"{aggregate_stats['consensus_unsupported_claims']} unsupported claim(s) flagged by multiple models — verify with primary sources.")
        final_assessment.append("Structured output mode: consensus derived from verifier JSON blocks.")
    else:
        final_assessment.append("Legacy mode: consensus derived from text-line matching (upgrade verifier templates for better accuracy).")

    final_assessment.extend([
        "Adopt consensus items as high-confidence corrections.",
        "Treat divergence items as follow-up checks before external publication.",
        "If divergence affects core conclusions, run an additional targeted verification pass.",
    ])

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

    result_payload: dict[str, Any] = {
        "output": str(out_path),
        "success_models": success_count,
        "structured_mode": use_structured,
    }
    if aggregate_stats:
        result_payload["aggregate"] = aggregate_stats

    print(json.dumps(result_payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
