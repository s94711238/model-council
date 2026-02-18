# Model Council 系統優化分析：Token 成本 vs 準確性

**日期**: 2026-02-18  
**範圍**: 既有 A–E 方案 + 新增 F（Perplexity-assisted）+ 建議混合方案 G  
**目標**: 在 Jacob 的「商務 + 技術」混合場景下，顯著降 token、維持決策級準確性

---

## 0) Baseline 與分析假設

### 現行 baseline（每份報告）
- Stage 1 Primary（Gemini Pro High）: **10k**
- Stage 2 3 模型驗證（Codex + Sonnet + Gemini Pro）: **30k**
- Stage 3 Synthesis: **5k**
- **Total = 45k tokens/report**

### Jacob 場景風險分佈（建議預設）
- 高風險（商務決策/技術選型）: **30%**
- 中風險（市場研究/方案比較）: **50%**
- 低風險（文獻綜述/背景整理）: **20%**

> 這個分佈用於估算平均成本；實際值可在 2–4 週 telemetry 後重估。

---

## 1) Token 浪費點識別（現行設計）

| 浪費點 | 現象 | 估計浪費比例（對 45k） | 原因 |
|---|---|---:|---|
| 全模型讀完整 primary | 3 個驗證模型都 ingest 全文 | 20–30% | 重複閱讀共通段落、背景段落 |
| 無風險分級 | 低風險任務也走 full council | 10–20% | 驗證強度未隨風險調整 |
| 驗證輸出冗長 | 每個 verifier 自由發揮，重複敘述 | 5–10% | 缺少結構化 output schema |
| Synthesis 全文重讀 | 最終整合再次處理大量重複內容 | 8–12% | 未採用 diff/claim-based merge |
| 事實查核用 LLM 內部記憶 | 可搜尋 claim 沒先 web verify | 5–15% | 沒利用 Perplexity citation 工具 |

**總結**: 現行 45k 中，保守有 **~18k（40%）可優化空間**，但不能一次全部壓縮，需避免 accuracy 崩塌。

---

## 2) 方案逐一評估（A–F）

## A. Hierarchical Verification（階層式）

### 流程
1. Primary 10k
2. 摘要 2k（claim-focused）
3. Level-1 快速掃描（Codex）
4. 只有 fail 才進 Level-2 full council

### Token 估算
- 若 L1 pass rate = 70%
- Expected ≈ `10k + 2k + 3k + 0.3*(30k) + synth(3k)` = **27k**
- **節省 ~40%**（相較 45k）

### 準確性影響
- **FN（漏錯）風險**: 中等（8–12%）
- **FP（誤報）風險**: 低到中
- Coverage: 高（因 fail 路徑仍可 full verify）

### 評語
- 成本效益高，且適合逐步 rollout。
- 核心風險在 L1 gate 品質（門檻設錯會漏掉問題）。

---

## B. Divide & Conquer（分段分工）

### 流程
- Primary 拆 3 段，各模型只看 1 段

### Token 估算
- 驗證 token 約從 30k 降至 ~10–14k
- 總量約 **25–29k**
- **節省 36–44%**

### 準確性影響
- **FN 風險**: 較高（15–20%）
- 主要問題：跨段矛盾很容易漏檢（尤其商務假設與技術可行性衝突）

### 評語
- 便宜但對 Jacob 場景危險（跨域推理是核心需求）。

---

## C. Smart Summarization（先摘要再驗證）

### 流程
- 先摘要 2k 給 3 模型驗證，僅對分歧點 deep dive

### Token 估算
- 常態情況約 **20–25k**
- **節省 44–56%**

### 準確性影響
- **FN 風險**: 高（20–25%）
- 摘要丟失細節時，三模型會在同一個有偏摘要上達成「假共識」

### 評語
- 成本漂亮，但風險過高，不適合高風險決策預設流。

---

## D. Selective Verification（風險分級）

### 流程
- 高風險: 3 模型
- 中風險: 2 模型
- 低風險: 1 模型或 skip

### Token 估算（以 30/50/20 分佈）
- 驗證期望值 = `0.3*30k + 0.5*20k + 0.2*10k = 21k`
- Total ≈ `10k + 21k + 4k` = **35k**
- **節省 ~22%**（保守）
- 若低風險多數 skip、synth 精簡，可達 **28–35%**

### 準確性影響
- **FN 風險**: 低（5–8%），前提是風險分級準確

### 評語
- 最穩健、最符合業務現實；是很好的主骨架。

---

## E. Incremental Verification（增量派單）

### 流程
- 先 1 模型；問題超閾值再派第 2、3 模型

### Token 估算
- 若平均使用 1.5–1.8 模型
- 驗證 ≈ 15k–18k
- Total ≈ **29–33k**
- **節省 27–36%**

### 準確性影響
- **FN 風險**: 中等（10–14%）
- 依賴第一個模型的召回率（recall）

### 評語
- 性價比高，但 gating 邏輯要嚴謹，否則會 under-escalate。

---

## F. Perplexity-Assisted Verification（新增）

### 核心概念
先把「可搜尋 claim」交給 Perplexity Sonar Pro 做 citation-based fact check，LLM council 只處理：
1) 邏輯一致性、2) 戰略合理性、3) 不可搜尋或需領域判斷的 claim。

### 哪些任務適合 Perplexity
**非常適合（高 ROI）**
- 數字/統計（市場規模、CAGR、採用率）
- 引用存在性（paper/company report 是否存在）
- 時點事實（發布時間、版本、事件）
- 可公開查證的 competitor facts

**不適合（仍需 Council）**
- 推理鏈是否成立（因果/反事實）
- 策略選擇與 trade-off
- 實作可行性（工程細節、組織能力）
- 專案約束下的最佳化判斷

### Token 估算
- 假設可搜尋 claim 佔驗證工作量 30%
- 3 verifier scope 可縮到 70–80%
- 驗證 token 從 30k 降到 **21–24k**
- Total ≈ **36–39k**
- **節省 13–20%**（單獨使用）

> 若再搭配 D/E，可達更高節省（見混合策略）。

### 準確性影響
- **FN 風險**: 低到中（6–9%）
- 優勢：對「可驗證事實」 precision/recall 通常優於純 LLM 記憶

### 成本面
- 若 Perplexity 在月費免費額度內，對 Jacob 幾乎是 **零增量美元成本**。
- 可形成「Gemini grounding + Perplexity citations」的雙免費工具層。

---

## 3) 評分矩陣（含 F）

> 權重：**準確性 45% / Token 節省 35% / 實作複雜度 20%**（複雜度越低分越高）

| 方案 | Token 節省 | 準確性保留 | 實作複雜度 | 加權總分(5) |
|---|---:|---:|---:|---:|
| A Hierarchical | 4.0 | 4.2 | 3.2 | **3.94** |
| B Divide & Conquer | 4.5 | 3.4 | 4.0 | **3.89** |
| C Smart Summary | 5.0 | 3.0 | 2.2 | **3.55** |
| D Selective | 3.4 | 4.6 | 4.4 | **4.18** |
| E Incremental | 4.1 | 3.9 | 3.4 | **3.89** |
| F Perplexity-Assisted | 2.8 | 4.4 | 4.0 | **3.79** |

**單一方案最佳**: **D（Selective）**  
**若追求更大降本**: 要走混合策略。

---

## 4) 建議第 6 種方案（G）

## G. Risk-Adaptive Evidence-First Cascade（推薦）
**= D（風險分級） + F（Perplexity 先查證） + A/E（分層/增量升級） + 結構化 diff synthesis**

### 流程
1. **Primary（Gemini）** 產出 report + claims list（結構化）
2. **Perplexity fact-check** 可搜尋 claims（附 citation + verdict）
3. **Risk router（D）** 決定 base 驗證強度（1/2/3 模型）
4. **Gate（A/E）**：先跑一個 verifier，分數不足再升級
5. **Synthesis（diff-based）** 只整合「有爭議 claim + 行動建議」，不重讀全文

### 量化預估（以 30/50/20 風險分佈）
- 高風險平均：**37k**
- 中風險平均：**30.5k**
- 低風險平均：**19k**
- 加權平均：`0.3*37 + 0.5*30.5 + 0.2*19 = 30.15k`

**=> 預估平均 ~30k/report（較 45k 節省 ~33%）**  
在低風險比例較高（>35%）時，可逼近 **40–50%** 節省。

### 準確性預估
- Accuracy 保留：**~92–95% baseline**
- FN 風險：**4–7%**（靠 escalation + high-risk 強制 full council 控制）

### 為什麼適合 Jacob
- 商務決策高風險 case 不降防護
- 技術/研究型 case 有顯著降本
- Perplexity 補足事實查核，Council 專注邏輯與戰略

---

## 5) 零成本驗證系統設計（Gemini + Perplexity）

## 目標
將「外部搜尋/查證」盡量放在免費或既有月費配額層，付費 token 留給真正需要推理的步驟。

### 零成本層（Evidence Layer）
- Gemini grounding：Primary 研究（免費配額）
- Perplexity Sonar Pro：claim citation 查證（免費額度內）

### 最小 token 層（Reasoning Layer）
- 只對 unresolved/high-risk claims 派 Council
- 使用結構化輸出，限制每 verifier 800–1200 output tokens

**實務上可達**：
- 「美元成本接近 0」+「token 成本下降 30–40%」

---

## 6) 實證數據需求與 A/B 設計

## 必收指標
1. **Tokens/report**（P50/P90）
2. **Critical Error Miss Rate（CEMR）**：漏掉重大錯誤比例
3. **Claim-level Recall/Precision**（對人工標註 truth set）
4. **Decision Reversal Rate**：若 full-council 重跑，結論是否翻轉
5. **Latency/report**（端到端）

## A/B 測試建議
- 樣本：至少 **60 份報告**（高/中/低風險各 20）
- A 組：現行 full 3-model baseline
- B 組：方案 G
- 觀察期：2–4 週
- 驗收門檻（建議）:
  - token 降幅 **≥30%**
  - CEMR 不劣化超過 **+2% 絕對值**
  - 高風險報告 decision reversal **<5%**

---

## 7) 最終建議（可立即開工）

## 推薦採用：**方案 G（分階段落地）**

### 先做（低風險、高回報）
1. 結構化 verifier output（壓輸出長度）
2. 加入風險分級路由（D）
3. 加入 Perplexity claim-check（F）

### 再做（進一步降本）
4. L1 gate + escalation（A/E）
5. diff-based synthesis

### 退路（fallback）
- 任一關卡信心不足、citation 衝突、或高風險標記觸發時：**自動回退 full 3-model**。

---

## 一句話結論
**可以在不明顯犧牲準確性的前提下，把平均成本從 45k 壓到約 30k（~33% 節省）；若低風險任務比例高，節省可進一步逼近 40–50%。**
