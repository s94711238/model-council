#!/usr/bin/env bash
# ============================================================
# OpenClaw Gateway 效能診斷腳本
# 在你的 WSL2 主機上執行：bash diagnose-openclaw.sh
# ============================================================
set -euo pipefail

GATEWAY_URL="${OPENCLAW_GATEWAY_URL:-http://127.0.0.1:18789}"
OPENCLAW_PKG="/home/s94711238/.nvm/versions/node/v22.22.0/lib/node_modules/openclaw"
WORKSPACE="/home/s94711238/.openclaw/workspace"
REPORT_FILE="/tmp/openclaw-diag-$(date +%Y%m%d-%H%M%S).txt"

# Colors
RED='\033[0;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
CYN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYN}[DIAG]${NC} $*" | tee -a "$REPORT_FILE"; }
warn() { echo -e "${YEL}[WARN]${NC} $*" | tee -a "$REPORT_FILE"; }
err()  { echo -e "${RED}[ERR]${NC}  $*" | tee -a "$REPORT_FILE"; }
ok()   { echo -e "${GRN}[OK]${NC}   $*" | tee -a "$REPORT_FILE"; }
sep()  { echo "────────────────────────────────────────────────" | tee -a "$REPORT_FILE"; }

echo "" > "$REPORT_FILE"
log "OpenClaw Gateway 效能診斷報告"
log "時間: $(date '+%Y-%m-%d %H:%M:%S')"
log "主機: $(hostname)"
sep

# ============================================================
# 1. 系統資源概況
# ============================================================
log ""
log "=== 1. 系統資源 ==="

log "記憶體 (free -h):"
free -h 2>/dev/null | tee -a "$REPORT_FILE" || warn "free command unavailable"

log ""
log "Swap 使用:"
swapon --show 2>/dev/null | tee -a "$REPORT_FILE" || warn "swapon unavailable"

log ""
log "磁碟使用 (workspace + openclaw):"
df -h "$WORKSPACE" 2>/dev/null | tee -a "$REPORT_FILE" || true
df -h "$OPENCLAW_PKG" 2>/dev/null | tee -a "$REPORT_FILE" || true

log ""
log "CPU 負載:"
uptime 2>/dev/null | tee -a "$REPORT_FILE"

log ""
log "CPU 核心數:"
nproc 2>/dev/null | tee -a "$REPORT_FILE"

sep

# ============================================================
# 2. Node.js 環境
# ============================================================
log ""
log "=== 2. Node.js 環境 ==="

NODE_BIN="$(which node 2>/dev/null || echo '')"
if [ -n "$NODE_BIN" ]; then
    log "Node 路徑: $NODE_BIN"
    log "Node 版本: $(node --version)"
    log "npm 版本: $(npm --version 2>/dev/null || echo 'N/A')"
else
    err "找不到 node binary"
fi

log ""
log "Node.js 全域模組數量:"
if [ -d "$OPENCLAW_PKG/../" ]; then
    GLOBAL_MODULES=$(ls -1 "$OPENCLAW_PKG/../" 2>/dev/null | wc -l)
    log "  全域模組數: $GLOBAL_MODULES"
    ls -1 "$OPENCLAW_PKG/../" 2>/dev/null | tee -a "$REPORT_FILE"
fi

log ""
log "OpenClaw package 大小:"
if [ -d "$OPENCLAW_PKG" ]; then
    du -sh "$OPENCLAW_PKG" 2>/dev/null | tee -a "$REPORT_FILE"
    log "node_modules 子目錄大小:"
    du -sh "$OPENCLAW_PKG/node_modules" 2>/dev/null | tee -a "$REPORT_FILE" || log "  (no nested node_modules)"
    log ""
    log "依賴數量:"
    if [ -f "$OPENCLAW_PKG/package.json" ]; then
        DEPS=$(node -e "const p=require('$OPENCLAW_PKG/package.json'); console.log(Object.keys(p.dependencies||{}).length)" 2>/dev/null || echo "?")
        DEV_DEPS=$(node -e "const p=require('$OPENCLAW_PKG/package.json'); console.log(Object.keys(p.devDependencies||{}).length)" 2>/dev/null || echo "?")
        log "  dependencies: $DEPS"
        log "  devDependencies: $DEV_DEPS"
    fi
else
    err "OpenClaw package 不存在: $OPENCLAW_PKG"
fi

sep

# ============================================================
# 3. OpenClaw 進程狀態
# ============================================================
log ""
log "=== 3. OpenClaw 進程 ==="

log "所有 node 相關進程:"
ps aux 2>/dev/null | grep -E '[n]ode|[o]penclaw' | tee -a "$REPORT_FILE" || warn "ps unavailable"

log ""
log "Gateway 進程 (port 18789):"
if command -v ss &>/dev/null; then
    ss -tlnp 2>/dev/null | grep 18789 | tee -a "$REPORT_FILE" || log "  (port 18789 not found in ss output)"
elif command -v netstat &>/dev/null; then
    netstat -tlnp 2>/dev/null | grep 18789 | tee -a "$REPORT_FILE" || log "  (port 18789 not found)"
else
    warn "ss/netstat unavailable, trying lsof"
    lsof -i :18789 2>/dev/null | tee -a "$REPORT_FILE" || warn "lsof also unavailable"
fi

log ""
log "Node 進程記憶體用量 (RSS, top 10):"
ps -eo pid,rss,vsz,comm,args 2>/dev/null | grep -E '[n]ode' | sort -k2 -rn | head -10 | \
    awk '{printf "  PID=%-7s RSS=%-8s VSZ=%-8s %s\n", $1, $2"K", $3"K", $5}' | tee -a "$REPORT_FILE" || true

log ""
log "Node 進程總數:"
NODE_PROCS=$(ps aux 2>/dev/null | grep -c '[n]ode' || echo "0")
log "  $NODE_PROCS 個 node 進程"
if [ "$NODE_PROCS" -gt 10 ]; then
    warn "⚠️  Node 進程數偏多 (>10)，可能有 sub-agent 殘留"
fi

sep

# ============================================================
# 4. Gateway 回應效能測試
# ============================================================
log ""
log "=== 4. Gateway 延遲測試 ==="

# Health check
log "Health endpoint 延遲 (5 次測量):"
for i in 1 2 3 4 5; do
    START=$(date +%s%N)
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "$GATEWAY_URL/healthz" 2>/dev/null || echo "000")
    END=$(date +%s%N)
    ELAPSED_MS=$(( (END - START) / 1000000 ))
    if [ "$HTTP_CODE" = "200" ]; then
        log "  #$i: ${ELAPSED_MS}ms (HTTP $HTTP_CODE)"
    else
        err "  #$i: ${ELAPSED_MS}ms (HTTP $HTTP_CODE) ← 非 200"
    fi
done

log ""
log "tools/invoke 空呼叫延遲 (echo test):"
for i in 1 2 3; do
    START=$(date +%s%N)
    RESP=$(curl -s --connect-timeout 5 --max-time 15 \
        -X POST "$GATEWAY_URL/tools/invoke" \
        -H "Content-Type: application/json" \
        -d '{"tool":"echo","args":{"message":"ping"},"action":"json","sessionKey":"diag","dryRun":true}' 2>/dev/null || echo '{"error":"timeout"}')
    END=$(date +%s%N)
    ELAPSED_MS=$(( (END - START) / 1000000 ))
    log "  #$i: ${ELAPSED_MS}ms"
done

sep

# ============================================================
# 5. 子 Session / Sub-agent 殘留
# ============================================================
log ""
log "=== 5. Session / Sub-agent 狀態 ==="

OPENCLAW_CONFIG="$HOME/.openclaw/openclaw.json"
TOKEN=""
if [ -f "$OPENCLAW_CONFIG" ]; then
    TOKEN=$(node -e "try{const c=require('$OPENCLAW_CONFIG');console.log(c.gateway?.auth?.token||'')}catch{}" 2>/dev/null || echo "")
fi

if [ -n "$TOKEN" ]; then
    log "嘗試查詢 subagents..."
    SUBAGENT_RESP=$(curl -s --connect-timeout 5 --max-time 15 \
        -X POST "$GATEWAY_URL/tools/invoke" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -d '{"tool":"subagents","args":{"action":"list"},"action":"list","sessionKey":"main","dryRun":false}' 2>/dev/null || echo '{"error":"failed"}')

    ACTIVE_COUNT=$(echo "$SUBAGENT_RESP" | node -e "
        const chunks=[];process.stdin.on('data',c=>chunks.push(c));
        process.stdin.on('end',()=>{
            try{
                const d=JSON.parse(chunks.join(''));
                const det=d.result?.details||d.details||{};
                const active=Array.isArray(det.active)?det.active.length:0;
                const recent=Array.isArray(det.recent)?det.recent.length:0;
                console.log(active+'_'+recent);
            }catch{console.log('parse_error')}
        })" 2>/dev/null || echo "error")

    if [ "$ACTIVE_COUNT" != "error" ] && [ "$ACTIVE_COUNT" != "parse_error" ]; then
        ACTIVE_N=$(echo "$ACTIVE_COUNT" | cut -d_ -f1)
        RECENT_N=$(echo "$ACTIVE_COUNT" | cut -d_ -f2)
        log "  活躍 sub-agents: $ACTIVE_N"
        log "  最近 sub-agents: $RECENT_N"
        if [ "$ACTIVE_N" -gt 5 ] 2>/dev/null; then
            warn "⚠️  活躍 sub-agent 數量偏多 ($ACTIVE_N)，建議清理"
        fi
    else
        warn "  無法解析 subagent 回應"
    fi
else
    warn "找不到 Gateway token，跳過 subagent 查詢"
fi

sep

# ============================================================
# 6. Workspace 磁碟佔用
# ============================================================
log ""
log "=== 6. Workspace 分析 ==="

if [ -d "$WORKSPACE" ]; then
    log "Workspace 總大小:"
    du -sh "$WORKSPACE" 2>/dev/null | tee -a "$REPORT_FILE"

    log ""
    log "Workspace 子目錄大小 (top 15):"
    du -sh "$WORKSPACE"/*/ 2>/dev/null | sort -rh | head -15 | tee -a "$REPORT_FILE"

    log ""
    log "Workspace 檔案數量:"
    TOTAL_FILES=$(find "$WORKSPACE" -type f 2>/dev/null | wc -l)
    log "  $TOTAL_FILES 個檔案"
    if [ "$TOTAL_FILES" -gt 10000 ]; then
        warn "⚠️  檔案數量偏多 (>10000)，可能拖慢 file watching"
    fi

    log ""
    log "大檔案 (>10MB):"
    find "$WORKSPACE" -type f -size +10M 2>/dev/null | head -10 | while read -r f; do
        SIZE=$(du -sh "$f" 2>/dev/null | cut -f1)
        log "  $SIZE  $f"
    done || log "  (none)"

    log ""
    log ".git 目錄大小:"
    find "$WORKSPACE" -maxdepth 3 -name ".git" -type d 2>/dev/null | while read -r gitdir; do
        SIZE=$(du -sh "$gitdir" 2>/dev/null | cut -f1)
        log "  $SIZE  $gitdir"
    done || log "  (none found)"
else
    warn "Workspace 目錄不存在: $WORKSPACE"
fi

sep

# ============================================================
# 7. OpenClaw 設定檔分析
# ============================================================
log ""
log "=== 7. 設定分析 ==="

if [ -f "$OPENCLAW_CONFIG" ]; then
    log "openclaw.json 存在 ($OPENCLAW_CONFIG)"
    log "設定檔大小: $(wc -c < "$OPENCLAW_CONFIG") bytes"
    # Print config without token
    node -e "
        const fs=require('fs');
        const cfg=JSON.parse(fs.readFileSync('$OPENCLAW_CONFIG','utf8'));
        if(cfg.gateway?.auth?.token) cfg.gateway.auth.token='[REDACTED]';
        console.log(JSON.stringify(cfg,null,2));
    " 2>/dev/null | tee -a "$REPORT_FILE" || warn "無法解析設定檔"
else
    warn "找不到 openclaw.json"
fi

log ""
log "OpenClaw 狀態檔:"
find "$HOME/.openclaw" -name "*.json" -o -name "*.log" -o -name "*.pid" 2>/dev/null | while read -r f; do
    SIZE=$(du -sh "$f" 2>/dev/null | cut -f1)
    log "  $SIZE  $f"
done || log "  (none)"

# Check for large log files
log ""
log "日誌檔大小:"
find "$HOME/.openclaw" -name "*.log" -type f 2>/dev/null | while read -r f; do
    SIZE=$(du -sh "$f" 2>/dev/null | cut -f1)
    LINES=$(wc -l < "$f" 2>/dev/null || echo "?")
    log "  $SIZE ($LINES lines)  $f"
    if [ "$(stat -c%s "$f" 2>/dev/null || echo 0)" -gt 104857600 ]; then
        warn "⚠️  日誌檔 >100MB: $f"
    fi
done || log "  (no log files)"

sep

# ============================================================
# 8. WSL2 特有問題
# ============================================================
log ""
log "=== 8. WSL2 環境 ==="

log "Kernel 版本:"
uname -r 2>/dev/null | tee -a "$REPORT_FILE"

log ""
log "/etc/wsl.conf:"
cat /etc/wsl.conf 2>/dev/null | tee -a "$REPORT_FILE" || log "  (not found)"

log ""
log "記憶體限制 (.wslconfig 反映):"
# WSL2 memory is visible in /proc/meminfo
TOTAL_MEM=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{printf "%.1f GB", $2/1024/1024}')
AVAIL_MEM=$(grep MemAvailable /proc/meminfo 2>/dev/null | awk '{printf "%.1f GB", $2/1024/1024}')
log "  Total: $TOTAL_MEM"
log "  Available: $AVAIL_MEM"

log ""
log "Windows 側 .wslconfig (如果可讀):"
WSLCONFIG="/mnt/c/Users/$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r')/.wslconfig"
if [ -f "$WSLCONFIG" ]; then
    cat "$WSLCONFIG" 2>/dev/null | tee -a "$REPORT_FILE"
else
    # Try common path
    for USER_DIR in /mnt/c/Users/*/; do
        if [ -f "${USER_DIR}.wslconfig" ]; then
            log "  Found: ${USER_DIR}.wslconfig"
            cat "${USER_DIR}.wslconfig" 2>/dev/null | tee -a "$REPORT_FILE"
            break
        fi
    done
    if ! grep -q "wslconfig" "$REPORT_FILE" 2>/dev/null; then
        log "  .wslconfig 未找到（使用 WSL2 預設值）"
    fi
fi

log ""
log "I/O 效能快速測試 (寫入 1MB 到 workspace):"
TESTFILE="$WORKSPACE/.diag-io-test-$$"
START=$(date +%s%N)
dd if=/dev/zero of="$TESTFILE" bs=1M count=1 2>/dev/null
sync
END=$(date +%s%N)
ELAPSED_MS=$(( (END - START) / 1000000 ))
rm -f "$TESTFILE"
log "  1MB 寫入: ${ELAPSED_MS}ms"
if [ "$ELAPSED_MS" -gt 500 ]; then
    warn "⚠️  磁碟 I/O 偏慢 (${ELAPSED_MS}ms for 1MB)，WSL2 ext4 可能有瓶頸"
fi

sep

# ============================================================
# 9. OpenClaw package.json 結構分析
# ============================================================
log ""
log "=== 9. OpenClaw Package 結構 ==="

if [ -f "$OPENCLAW_PKG/package.json" ]; then
    log "版本資訊:"
    node -e "
        const p=require('$OPENCLAW_PKG/package.json');
        console.log('  name:', p.name);
        console.log('  version:', p.version);
        console.log('  main:', p.main || '(none)');
        console.log('  engines:', JSON.stringify(p.engines||{}));
        console.log('  dependencies:', Object.keys(p.dependencies||{}).length);
        console.log('  scripts:', Object.keys(p.scripts||{}).join(', '));
    " 2>/dev/null | tee -a "$REPORT_FILE"

    log ""
    log "Top-level 依賴列表:"
    node -e "
        const p=require('$OPENCLAW_PKG/package.json');
        const deps=Object.entries(p.dependencies||{});
        deps.sort((a,b)=>a[0].localeCompare(b[0]));
        deps.forEach(([k,v])=>console.log('  '+k+': '+v));
    " 2>/dev/null | tee -a "$REPORT_FILE"

    log ""
    log "嵌套 node_modules 深度 / 總大小:"
    if [ -d "$OPENCLAW_PKG/node_modules" ]; then
        NESTED_SIZE=$(du -sh "$OPENCLAW_PKG/node_modules" 2>/dev/null | cut -f1)
        NESTED_COUNT=$(find "$OPENCLAW_PKG/node_modules" -maxdepth 1 -type d 2>/dev/null | wc -l)
        log "  Size: $NESTED_SIZE"
        log "  直接依賴目錄數: $NESTED_COUNT"

        log ""
        log "  最大的 10 個依賴:"
        du -sh "$OPENCLAW_PKG/node_modules"/*/ 2>/dev/null | sort -rh | head -10 | tee -a "$REPORT_FILE"
    fi
else
    warn "package.json 不存在"
fi

sep

# ============================================================
# 10. 結論與建議
# ============================================================
log ""
log "=== 10. 自動診斷摘要 ==="

ISSUES=0

# Check memory pressure
AVAIL_KB=$(grep MemAvailable /proc/meminfo 2>/dev/null | awk '{print $2}')
if [ -n "$AVAIL_KB" ] && [ "$AVAIL_KB" -lt 1048576 ] 2>/dev/null; then
    warn "⚠️  可用記憶體不足 1GB — 可能觸發 GC 壓力"
    ISSUES=$((ISSUES+1))
fi

# Check node process count
if [ "$NODE_PROCS" -gt 10 ] 2>/dev/null; then
    warn "⚠️  Node 進程過多 ($NODE_PROCS) — sub-agent 可能未正確回收"
    ISSUES=$((ISSUES+1))
fi

# Check swap usage
SWAP_USED=$(free 2>/dev/null | grep Swap | awk '{print $3}')
if [ -n "$SWAP_USED" ] && [ "$SWAP_USED" -gt 524288 ] 2>/dev/null; then
    warn "⚠️  Swap 使用 >512MB — 記憶體壓力大"
    ISSUES=$((ISSUES+1))
fi

if [ "$ISSUES" -eq 0 ]; then
    ok "未偵測到明顯系統級問題，瓶頸可能在 OpenClaw 內部邏輯"
fi

log ""
log "診斷報告已保存至: $REPORT_FILE"
log "請將此檔案內容分享回來以便進一步分析。"
echo ""
echo -e "${GRN}完成！${NC}報告路徑: $REPORT_FILE"
echo -e "執行 ${CYN}cat $REPORT_FILE${NC} 查看完整報告"
