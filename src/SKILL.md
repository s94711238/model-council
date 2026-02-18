---
name: model-council
description: >
  Model Council verification system. Takes a Gemini primary research report
  and dispatches 3 verification models (Codex/Sonnet/Strategic) in parallel,
  then synthesizes their feedback into a final validated report.
  Use when you need high-confidence multi-perspective validation of research/analysis.
---

# Model Council

Automated multi-model verification system for research reports.

## Quick Start

```bash
# Dispatch council for a report
python3 scripts/dispatch.py /path/to/primary-report.md

# Collect results (after sub-agents finish)
python3 scripts/collect.py <run-ids>

# Synthesize final report
python3 scripts/synthesize.py /path/to/verifications/
```

## Full Workflow

1. **Primary Research**: Generate initial report with Gemini Pro High
2. **Dispatch**: `dispatch.py` spawns 3 verification sub-agents
3. **Wait**: Sub-agents run in parallel (3-5 minutes)
4. **Collect**: `collect.py` gathers verification outputs
5. **Synthesize**: `synthesize.py` creates final report

## Scripts

### dispatch.py
- Reads primary report
- Loads verification templates
- Spawns 3 sub-agents with appropriate prompts
- Returns run IDs for tracking

### collect.py
- Polls sub-agent status
- Retrieves completed outputs
- Saves to structured directory

### synthesize.py
- Reads primary + 3 verifications
- Identifies consensus/divergence
- Generates final integrated report

## Optimized Workflow (V2)

For cost-optimized verification:

```bash
# Auto-route based on risk
python3 scripts/dispatch_v2.py /path/to/report.md

# Manual risk assessment
python3 scripts/risk_router.py /path/to/report.md

# Standalone Perplexity check
python3 scripts/perplexity_check.py /path/to/report.md
```

### Cost Comparison
- V1 (Full council): ~45k tokens
- V2 (Risk-adaptive): ~30k tokens avg (-33%)

## Notes

- Scripts call OpenClaw Gateway `POST /tools/invoke` and use session tools:
  - `sessions_spawn`
  - `subagents(action="list")`
  - `sessions_history`
- If `dispatch.py` reports `Tool not available: sessions_spawn`, allow it in Gateway config:

```json5
{
  gateway: {
    tools: {
      allow: ["sessions_spawn"]
    }
  }
}
```

- Default output directory: `references/council-runs/<timestamp>/`
