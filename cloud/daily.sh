#!/usr/bin/env bash
# 云端每日整链（第二棒 + 第三棒）：主刷新 → PROF。
#
# 调度位置：AFGI 由独立的云端任务在 07:30 完成；本脚本处理同一批 T 日数据，
# 顺序不可颠倒 —— PROF 要同步主刷新刚更新好的 hfq 行情。
#
# 用法：
#   bash cloud/daily.sh                # 只跑，不拉代码
#   GIT_PULL=1 bash cloud/daily.sh     # 先 git pull 再跑（定时任务用这个）
#   bash cloud/daily.sh --force        # 无新交易日也强制重跑
#
# 退出码：0 成功（含非交易日跳过）/ 10 主刷新失败 / 11 PROF 失败 / 7 git 失败
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

FORCE_ARG=""
[[ "${FORCE:-0}" == "1" ]] && FORCE_ARG="--force"

log "===== 每日整链开始（工作区 $WS）====="

if [[ "${GIT_PULL:-0}" == "1" ]]; then
  pull_all pool-core mom_opt prof-model
fi

# ---------------------------------------------------------- 模板合规检查
# 线上版式已于 2026-10-18 升级为 v3：CSFM/TSFM 两个因子动量组合 + 四、历史仓位建议
# （双滑块时间轴）+ 质量Top28 v2 三道筛。旧模板（「三、动量轮动回测」口径）一旦被
# refresh_page.py 用来整页重建，就会把线上内容整段回退 —— 10-18 22:44 已发生过一次。
# 因此这里先校验模板；不合格就从资料库节点重新拉最新版，拉不到就中止（宁可不更新）。
TPL="$POOL_DIR/data/page_base.html"
if [[ ! -f "$TPL" ]] || ! grep -q 'id="posChart"' "$TPL" || grep -q '三、动量轮动回测' "$TPL"; then
  log "模板缺失或仍是旧版式 → 从资料库重新拉取（seed --force）"
  ( cd "$POOL_DIR" && $PY cloud/seed_page_base.py --force ) \
    || { warn "页面模板拉取失败（不覆盖线上，直接中止）"; exit 21; }
fi

# ------------------------------------------------------------------ 主刷新
log "=== [1/2] 主刷新：增量行情 → 体检 → 回测 → 就地刷新页面 → 上传 ==="
OUT_LOG="$(mktemp)"
( cd "$POOL_DIR" && $PY scripts/daily_refresh.py $FORCE_ARG ) 2>&1 | tee "$OUT_LOG"
rc=${PIPESTATUS[0]}

if [[ $rc -ne 0 ]]; then
  warn "主刷新失败（退出码 $rc），按约定中止，不跑 PROF、不上传"
  exit 10
fi

if grep -q "未探测到新交易日" "$OUT_LOG"; then
  log "非交易日：主刷新已跳过，PROF 一并跳过（页面保持原样）"
  rm -f "$OUT_LOG"
  log "===== 每日整链结束（休市，无需更新）====="
  exit 0
fi
rm -f "$OUT_LOG"

# ------------------------------------------------------------------ PROF
log "=== [2/2] PROF：同步行情 → 补抓财报 → 评分 → 回测 → 刷新 4.3 → 回写模板 ==="
cd "$PROF_DIR" || exit 11
# pool/ 与 prof/ 是被 .gitignore 排除的中间产物目录，云端冷启动需预建
mkdir -p "$PROF_DIR/pool" "$PROF_DIR/prof"

$PY sync_prices.py            || { warn "sync_prices 失败（源文件更旧/行数变少，已拒绝覆盖）"; exit 11; }
$PY catchup.py                || { warn "catchup 失败（财报抓取限频，可重跑续跑）"; exit 11; }
$PY prof_score.py             || { warn "prof_score 失败"; exit 11; }
$PY backtest_prof.py          || { warn "backtest_prof 失败"; exit 11; }
$PY update_prof_data.py --page-only || { warn "update_prof_data --page-only 失败"; exit 11; }
$PY sync_page_base.py         || { warn "sync_page_base 失败（模板未回写，明日主刷新会用旧模板）"; exit 11; }

# ------------------------------------------------------------------ 发布
log "=== [3/3] 统一发布：把三个固定页面重新发布为外部网页（解冻冻结快照，保证网页端同步）==="
( cd "$POOL_DIR" && $PY cloud/publish_pages.py ) \
  || warn "页面发布失败（不影响已入库数据；可重跑 cloud/publish_pages.py 或手动发布）"

log "===== 每日整链结束（成功）====="
