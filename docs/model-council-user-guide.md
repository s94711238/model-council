# Model Council 使用指南

## Quick Start (5 步驟)

### Step 1: 產生 Primary Report
```bash
# 手動派 Gemini sub-agent
# 或使用 gemini-grounding skill 搜尋
```

### Step 2: 派遣驗證議會
```bash
cd ~/.openclaw/skills/model-council
python3 scripts/dispatch.py /path/to/primary-report.md
```

輸出：
```
Dispatching Model Council...
✓ Codex verification: run_abc123
✓ Sonnet verification: run_def456
✓ Strategic analysis: run_ghi789
```

### Step 3: 等待完成（3-5 分鐘）
議會會自動在背景執行，完成後通知 Telegram。

或手動檢查：
```bash
python3 scripts/collect.py abc123,def456,ghi789
```

### Step 4: 收集結果
```bash
python3 scripts/collect.py abc123,def456,ghi789
```

輸出：
```
Collecting results...
✓ Codex: references/council-runs/20260218-0920/codex.md
✓ Sonnet: references/council-runs/20260218-0920/sonnet.md
✓ Strategic: references/council-runs/20260218-0920/strategic.md
```

### Step 5: 整合報告
```bash
python3 scripts/synthesize.py references/council-runs/20260218-0920/
```

輸出：
```
Synthesizing final report...
✓ Final: references/[topic]-council-final.md
```

## 進階使用

### 自訂驗證重點
編輯 prompt templates：
```bash
references/model-council-prompts/codex-verification-template.md
```

### 調整模型分工
修改 `dispatch.py` 中的 model 選擇。

### 一鍵執行（完整流程）
```bash
python3 scripts/run-council.py "東南亞 NGS 市場趨勢"
```

## 範例場景

### 場景 1: 競爭者分析
Primary: Gemini 搜尋競爭者 + 定價
Council: Codex 驗證數字，Sonnet 評估策略，Strategic 建議定位

### 場景 2: 技術選型
Primary: Gemini 閱讀文獻比較技術
Council: Codex 檢查技術細節，Sonnet 評估成本，Strategic 分析長期影響

## 常見問題

Q: 如果只有 2 個模型完成怎麼辦？
A: 2/3 足夠產出報告，會標註缺失模型。

Q: 可以只用單一模型驗證嗎？
A: 可以，但失去多角度優勢，不如直接用單一 sub-agent。

Q: 成本如何？
A: Gemini 免費（1,500/天），驗證約 30k tokens（~$0.01 USD）。
