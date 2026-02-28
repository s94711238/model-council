# OpenClaw Gateway 效能深層分析

> 環境: WSL2 @ MSI-Jacob | Node v22.22.0 | Gateway http://127.0.0.1:18789

---

## 一、已確認的 Client 端瓶頸

### 1. `collect.py` — 輪詢風暴壓 Gateway

```python
# collect.py:84-103
def _wait_until_done(client, target_run_ids, timeout_seconds, poll_seconds):
    while time.time() < deadline:
        index = _fetch_subagent_index(client)   # ← 每次都拉全量列表
        ...
        time.sleep(max(3, poll_seconds))         # ← 預設 15s，但最低 3s
```

**問題**：每次 poll 都呼叫 `subagents(action="list")`，Gateway 必須遍歷所有 active + recent sessions 序列化回傳。如果你累積了大量歷史 session，這個操作會越來越慢。

**影響**：Gateway CPU + 記憶體被反覆 list 操作佔用。

### 2. `sessions_history` 拉取無上限

```python
# collect.py:114-121
history = client.invoke_tool(
    "sessions_history",
    args={"sessionKey": session_key, "limit": 200, "includeTools": False},
)
```

**問題**：`limit: 200` 代表每個 session 最多拉 200 則訊息。如果 sub-agent 對話長，回傳的 JSON body 可能上 MB 等級，Gateway 要序列化整包、Python 端要 JSON parse 整包。

### 3. `perplexity_check.py` — 序列化逐筆呼叫

```python
# perplexity_check.py:218-226
for claim_obj in selected:
    res = verify_with_perplexity(claim_text)  # ← 逐筆同步 HTTP
```

**問題**：每個 claim 都是一次完整的 HTTP round-trip → Gateway → web_search → 回來。5 筆 claim = 5 次序列化請求，每次 Gateway 內部又可能有自己的外部 HTTP call（Perplexity API）。

### 4. `dispatch_v2.py` — Template 注入造成巨大 payload

```python
# dispatch_v2.py:136-144
prompt = load_template(str(template), report_content, context=perplexity_context)
args = {"task": prompt, ...}
result = client.invoke_tool("sessions_spawn", args=args)
```

**問題**：整份 primary report（可能數千字）+ Perplexity context 全部塞進 `args.task`，經 JSON encode → HTTP POST → Gateway JSON parse → 再轉發給下游模型。同樣的 report 被傳了 1-3 次。

### 5. 每個 `OpenClawClient()` 都重讀 config

```python
# common.py:27-29
self.gateway_url = gateway_url or os.getenv(...) or self._default_gateway_url()
self.token = token or os.getenv(...) or self._default_gateway_token()
```

`_default_gateway_url()` 和 `_default_gateway_token()` 各自呼叫 `_load_openclaw_config()` → 讀磁碟 + JSON parse。`perplexity_check.py` 的 `verify_with_perplexity()` 每次都 `OpenClawClient()` → 每筆 claim 讀兩次 config file。

---

## 二、Gateway 端可能的結構性瓶頸

> 以下基於 Node.js Gateway 架構通性推斷，需用診斷腳本確認。

### 6. Sub-agent 殘留 (Session Leaking)

`dispatch.py` 設定 `"cleanup": "keep"`——session 不自動回收。如果你跑過很多次 council，每次 3 個 sub-agent，Gateway 的 session store 會持續膨脹：

- Session 物件佔記憶體
- `subagents(action="list")` 遍歷越來越慢
- 可能觸發 V8 GC 壓力

**驗證方式**：跑診斷腳本 §5 看 active/recent 數量。

### 7. Node.js v22 全域安裝的 node_modules 膨脹

全域安裝的 npm package 會把所有 dependencies 拉進一個平坦的 `node_modules/`。如果 OpenClaw 有重量級依賴（如 esbuild, puppeteer, sharp 之類），啟動時 `require()` resolve 會慢。

**驗證方式**：跑診斷腳本 §9。

### 8. WSL2 跨層 I/O 損耗

WSL2 的 ext4 VHD 在 NTFS 上方，有兩個已知效能陷阱：

| 路徑類型 | 效能 | 說明 |
|----------|------|------|
| `/home/...` (Linux FS) | **正常** | 直接走 9p/ext4 |
| `/mnt/c/...` (Windows FS) | **慢 3-10x** | 跨 Plan 9 protocol 橋接 |

如果 OpenClaw 的 workspace、log、或 state 檔放在 `/mnt/c/` 下，I/O 會嚴重拖慢。

**驗證方式**：確認 workspace 路徑。你說的是 `/home/s94711238/.openclaw/workspace` → 這是 Linux FS，正常；但如果 Gateway 有任何操作去讀 `/mnt/c/` 的東西就會卡。

### 9. 記憶體壓力 → GC Stall

WSL2 預設吃掉 Windows 50% RAM 或 8GB（取較小值）。如果 Windows 主機同時跑 VS Code + Chrome + Gateway + 多個 sub-agent sessions：

- 記憶體見頂 → Linux 開始用 swap
- Node.js V8 GC 被觸發更頻繁
- 每次 major GC 可能 stall 幾百 ms

**驗證方式**：診斷腳本 §1 + §8。

### 10. Gateway 日誌膨脹

如果 OpenClaw 寫 log 到 `~/.openclaw/` 下的 `.log` 文件且沒有 rotation，長期累積可能導致：
- 磁碟空間壓力
- 如果 Gateway 做 log streaming（tail -f 之類），持續 I/O 開銷

---

## 三、行動方案（優先順序）

### 立即可做（Client 端優化）

| # | 動作 | 預期效果 | 風險 |
|---|------|----------|------|
| A1 | `perplexity_check.py` 的 `verify_with_perplexity()` 改為只建立一次 `OpenClawClient` 並傳入 | 省去每筆 claim 2 次磁碟讀取 | 極低 |
| A2 | `collect.py` 的 poll 只查目標 run_id，而非全量 list | 減少 Gateway 遍歷成本 | 需確認 API 是否支援 filter |
| A3 | `dispatch_v2.py` 把 report content 存到 workspace file，template 只引用路徑 | 大幅減少 HTTP payload 大小 | 需 sub-agent 能讀 workspace file |

### 需要跑診斷腳本後決定（Gateway 端）

| # | 動作 | 觸發條件 |
|---|------|----------|
| B1 | 清理歷史 sessions | active+recent > 20 |
| B2 | 設定 `"cleanup": "auto"` 取代 `"keep"` | session 數持續增長 |
| B3 | 加 `.wslconfig` 限制/增加 WSL 記憶體 | 可用記憶體 < 2GB |
| B4 | 清理/rotate Gateway 日誌 | log 檔 > 100MB |
| B5 | 檢查 `node_modules` 是否有不必要的重量級依賴 | package size > 200MB |

---

## 四、如何使用診斷腳本

```bash
# 在你的 WSL2 終端裡執行（不是在這個沙盒環境）
cd /path/to/model-council
bash scripts/diagnose-openclaw.sh

# 或者直接用 curl 從 repo 拉
# 報告會自動保存到 /tmp/openclaw-diag-*.txt
```

跑完後把 `/tmp/openclaw-diag-*.txt` 的內容貼回來，我可以根據實際數據給出精確的優化建議。
