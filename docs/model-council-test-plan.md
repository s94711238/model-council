# Model Council System Test Plan (V2)

This document outlines the testing strategy for the Model Council V2 system, focusing on the new risk routing, Perplexity integration, and dynamic dispatch logic.

## 1. Test Datasets

Prepare the following 5 test reports in the `references/test-cases/` directory:

| ID | Type | Description | File Path (Suggested) | Status |
|----|------|-------------|-----------------------|--------|
| **D1** | **Low Risk** | Literature Review (General Topic) | `references/test-cases/low-risk-lit-review.md` | **Ready** |
| **D2** | **Medium Risk** | Sanger Sequencing Competitor Analysis (SEA) | `references/test-cases/medium-risk-sanger-sea.md` | **Ready** |
| **D3** | **Medium Risk** | HBV scRNA-seq Literature Analysis | `references/test-cases/medium-risk-hbv-scrna.md` | **Ready** |
| **D4** | **High Risk** | Technical Architecture Decision (Complex) | `references/test-cases/high-risk-arch-decision.md` | **Ready** (Placeholder) |
| **D5** | **Edge Case** | Ultra-short report (Empty or <100 words) | `references/test-cases/edge-case-short.md` | **Ready** |

## 2. Test Levels & Checklists

### 2.1 Unit Tests (Component Isolation)

Run these tests individually using `pytest` or direct script execution.

#### **risk_router.py**
- [ ] **Low Risk Identification**: Correctly tags D1 as low risk.
- [ ] **Medium Risk Identification**: Correctly tags D2/D3 as medium risk.
- [ ] **High Risk Identification**: Correctly tags D4 as high risk.
- [ ] **Boundary Handling**: Handles empty input/missing file gracefully (no crash).
- [ ] **JSON Output Format**: Verifies output is valid JSON with `risk_level` and `reasoning`.

#### **perplexity_check.py**
- [ ] **Claim Extraction**: Extracts numerical claims, statistics, and citations from text.
- [ ] **API Connectivity**: Successfully calls Perplexity API (Sonar).
- [ ] **Quota Management**:
    - [ ] Tracks usage correctly.
    - [ ] Aborts/Warns if daily quota (>167 calls) is near/exceeded.
- [ ] **Error Handling**: Handles network timeouts or API errors without crashing the pipeline.

#### **dispatch_v2.py**
- [ ] **Integration**: Successfully imports and calls `risk_router` and `perplexity_check`.
- [ ] **Pre-check Logic**: Skips expensive models if pre-check fails (optional feature).
- [ ] **Dynamic Dispatch**:
    - [ ] Low Risk -> Gemini Only/Gemini+Perplexity.
    - [ ] Medium Risk -> +Codex/Sonnet.
    - [ ] High Risk -> Full Council (3 models).
- [ ] **Cost Tracking**: Estimates token usage before dispatching.

### 2.2 Integration Tests (Workflow Logic)

Verify that components work together to produce the expected execution plan.

| Test Case | Input | Expected Logic Path | Expected Cost | Pass/Fail |
|-----------|-------|---------------------|---------------|-----------|
| **TC1** | Low Risk (D1) | Risk: Low -> Dispatch: Gemini + Perplexity | < 15k tokens | |
| **TC2** | Med Risk (D2) | Risk: Med -> Dispatch: Gemini + Perplexity + Codex | ~25k tokens | |
| **TC3** | High Risk (D4) | Risk: High -> Dispatch: Full Council (3 Models) | ~45k tokens | |

### 2.3 End-to-End (E2E) Tests (Full Pipeline)

Run the full lifecycle from dispatch to synthesis.

#### **E2E-1: Full V2 Workflow**
```bash
# 1. Dispatch
python3 dispatch_v2.py references/sanger-sea-competitor-analysis.md

# 2. Collect (Manual step simulating async completion)
# (Note: In real usage, dispatch_v2 might trigger subagents directly. 
# For testing, we verify subagent spawning or run IDs.)
python3 collect.py <run-ids>

# 3. Synthesize
python3 synthesize.py <council-run-dir>

# 4. Verification
# Check if references/council-reports/<date>/final_report.md exists
```

#### **E2E-2: Cost & Quality Comparison (V1 vs V2)**
1. Run D2 (Sanger Analysis) using `dispatch.py` (V1). Record tokens/cost.
2. Run D2 (Sanger Analysis) using `dispatch_v2.py` (V2). Record tokens/cost.
3. Compare output quality (Jacob's review).

## 3. A/B Testing Plan & Metrics

Compare V1 (Baseline) vs V2 (Optimized) using 5 reports (D1-D5).

### Metrics Table

| Metric | Target (V2) | V1 Baseline (Avg) | V2 Measured (Avg) | Status |
|--------|-------------|-------------------|-------------------|--------|
| **False Negative Rate** | < 10% (Errors missed) | N/A | | |
| **False Positive Rate** | Low (Avoid alert fatigue) | N/A | | |
| **Token Cost** | **≥ 25% Savings** | ~40k/run | | |
| **Time to Completion** | Faster for Low/Med | ~5-10m | | |
| **User Satisfaction** | ≥ 4/5 (Jacob) | 3/5 | | |

## 4. Regression Tests

Ensure we haven't broken the old system.

- [ ] **V1 Script Health**: Run `python3 dispatch.py <file>` -> Does it still work?
- [ ] **Template Compatibility**: Do V2 outputs work with `synthesize.py` templates?
- [ ] **Synthesis**: Does `synthesize.py` still handle multiple report formats?

## 5. Execution Scripts

### Setup Test Data
```bash
mkdir -p references/test-cases
# (Manually create D1, D5 files here)
```

### Run Unit Tests (Placeholder)
```bash
# Assuming we create a tests/ folder later
# pytest tests/
python3 scripts/test_risk_router.py
python3 scripts/test_perplexity.py
```

### Run E2E Test (Bash Script)
Create `scripts/run_e2e_test.sh`:
```bash
#!/bin/bash
INPUT_FILE=$1
echo "Testing V2 Dispatch with $INPUT_FILE..."
python3 dispatch_v2.py "$INPUT_FILE"
# Add logic to check exit code and output
```

## 6. Go/No-Go Decision Matrix

| Criteria | Threshold | Status |
|----------|-----------|--------|
| **Unit Tests** | 100% Pass | |
| **Integration Tests** | 3/3 Pass | |
| **Token Savings** | ≥ 25% vs V1 | |
| **Accuracy** | ≥ 90% vs V1 | |
| **Critical Bugs** | 0 | |
| **Perplexity Quota** | Within Limits | |

**Decision**: 
- [ ] **GO**: All green. Deploy V2.
- [ ] **NO-GO**: Any red. Fix and re-test.

## 7. Bug Tracking Template

Copy this section for each bug found during testing.

### Bug ID: [BUG-00X]
- **Component**: (e.g., risk_router, dispatch)
- **Severity**: (Critical / Major / Minor)
- **Description**: 
- **Reproduction Steps**:
  1. 
  2. 
- **Expected Behavior**:
- **Actual Behavior**:
- **Fix Status**: (Open / In Progress / Fixed)
