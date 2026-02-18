# Model Council 優化實作方案（推薦：方案 G）

**推薦方案**: Risk-Adaptive Evidence-First Cascade（D+F+A/E）  
**目標**: 平均 token 由 45k 降到 ~30k（約 -33%），高風險準確性維持 decision-grade

---

## 1) 系統設計（實作版）

## 新流程（v2）
1. `primary_generate`（Gemini）
2. `claim_extract`（結構化 claims）
3. `perplexity_verify`（可搜尋 claims）
4. `risk_route`（high/medium/low）
5. `verify_dispatch`（先最小必要模型）
6. `escalation_gate`（分數不夠才加派模型）
7. `synthesize_diff`（只整合爭議點 + 建議）

---

## 2) Code changes 需求（按檔案）

> 現況：`skills/model-council/scripts/` 目前只有 `common.py`，需補齊 orchestrator。

## A. 新增腳本

### `skills/model-council/scripts/orchestrate.py`
- 入口腳本，串整個 v2 pipeline
- 參數：
  - `--input <primary_report.md>`
  - `--risk <auto|high|medium|low>`
  - `--mode <baseline|optimized>`
  - `--feature-flags <json>`

### `skills/model-council/scripts/claims.py`
- 從 primary 產生結構化 claims：
```json
{
  "claims": [
    {
      "id": "C12",
      "text": "ASEAN NGS CAGR is 18% (2024-2028)",
      "type": "numeric|citation|timeline|logic|strategic",
      "searchable": true,
      "criticality": "high|medium|low",
      "source_span": "line 120-132"
    }
  ]
}
```

### `skills/model-council/scripts/perplexity_check.py`
- 對 `searchable=true` claims 呼叫 `web_search`
- 輸出 claim verdict：`supported | contradicted | unresolved`
- 每條 claim 要附 citations URL 清單

### `skills/model-council/scripts/risk_router.py`
- 規則式 + 關鍵字判斷：
  - high: 決策、採購、技術選型、資金配置
  - medium: 市場分析、策略草案
  - low: 背景整理、文獻綜述
- 支援人工覆寫（CLI flag）

### `skills/model-council/scripts/dispatch_v2.py`
- 根據 risk 決定 base 模型數
- 根據 perplexity verdict 只派 unresolved/contradicted claims 給 verifier

### `skills/model-council/scripts/escalation.py`
- Gate 規則（可配置）：
  - critical contradicted claims >= 1 → escalate
  - verifier confidence < 75 → escalate
  - unresolved high-critical claims >= 2 → escalate

### `skills/model-council/scripts/synthesize_diff.py`
- 只整合：
  1) consensus claims
  2) disputed claims
  3) must-fix actions
- 不再全文重述 primary

---

## B. 模板調整

### 既有模板（`templates/codex.md`, `sonnet.md`, `strategic.md`）
改為 JSON-first output（再附短評）：
```json
{
  "verdict": "pass_with_caveats",
  "confidence": 82,
  "critical_issues": [...],
  "claim_reviews": [
    {"claim_id":"C12","status":"supported|contradicted|unclear","reason":"..."}
  ],
  "actions": [...]
}
```

### 新增模板
- `templates/claims-extraction.md`
- `templates/perplexity-verdict-merge.md`
- `templates/synthesis-diff.md`

---

## C. 設定檔

新增 `skills/model-council/config.yaml`：
```yaml
features:
  use_perplexity_prefilter: true
  use_risk_routing: true
  use_escalation_gate: true
  use_diff_synthesis: true

thresholds:
  min_verifier_confidence: 75
  max_unresolved_claims_medium: 3
  max_unresolved_claims_low: 1

routing:
  high: [codex, sonnet, strategic]
  medium: [codex, sonnet]
  low: [codex]
```

---

## 3) 預估成效（上線前目標值）

- Token/report（平均）: **45k → 30k（-33%）**
- 高風險 case token: **45k → 37k**
- 中風險 case token: **45k → 30.5k**
- 低風險 case token: **45k → 19k**
- 高風險 decision reversal: 目標 **<5%**

---

## 4) 測試計畫（必做）

## 測試資料集
- 60 份歷史/模擬報告
  - high 20, medium 20, low 20
- 每份有人工標註：
  - 重大錯誤
  - claim truth label
  - 決策可用性分數

## 測試層級
1. **Unit tests**
   - claims parsing 正確率
   - risk router 分類一致性
   - escalation trigger 判定
2. **Integration tests**
   - v2 pipeline 全鏈路跑通
   - 任一子步驟失敗時 fallback 到 baseline
3. **A/B evaluation**
   - A: baseline full council
   - B: optimized v2

## 驗收標準（Go/No-go）
- token 降幅 ≥ 30%
- CEMR 劣化 ≤ +2%（絕對值）
- 高風險 reversal < 5%
- 端到端延遲不高於 baseline +15%

---

## 5) Rollout 路線圖（4 週）

## Week 1：可觀測性 + 結構化輸出
- 落地 claim schema、verifier JSON schema
- 記錄每步 token/latency/錯誤

## Week 2：Perplexity prefilter + risk router
- 先 shadow mode（只記錄，不影響決策）
- 比對與 baseline 差異

## Week 3：escalation gate + diff synthesis
- 10–20% 流量灰度
- 每日人工 spot-check 高風險樣本

## Week 4：擴大流量
- 50% → 100%（若指標達標）

---

## 6) Rollback 策略（必要）

## Feature flag 緊急開關
任一指標異常時，立即關閉：
- `use_escalation_gate=false`
- `use_risk_routing=false`
- `use_perplexity_prefilter=false`

系統自動回到 baseline：
- full 3-model verification + 舊 synthesis

## 觸發 rollback 條件
- 24h 內 high-risk reversal > 8%
- CEMR 較 baseline 高 > 3%
- pipeline fail rate > 5%

---

## 7) Jacob 可立即執行的最小版本（MVP）

1. 上 `risk_router.py`（先 D）  
2. 上 `perplexity_check.py`（再 F）  
3. 調整 verifier 模板為 JSON schema（減輸出冗字）  
4. 最後加 `escalation.py`（A/E）

這個順序能在最短時間得到可衡量降本，且風險可控。

---

## 8) 補充：Perplexity 任務分工建議

**Perplexity 負責**
- claim existence / citation check
- 數字與市場資料交叉查證
- 時效性事實（最近事件）

**Council 負責**
- 邏輯鏈與假設完整性
- 商務可執行性
- 技術與組織限制下的策略建議

> 原則：讓 Perplexity 做「查得到的事」，讓 Council 做「需要判斷的事」。
