#!/usr/bin/env bash
# 云端换季：把 cloud/season/ 的「名单层快照」覆盖到 data15，再重算净值并重建页面。
#
# 为什么需要这个脚本
# ─────────────────────────────────────────────────────────────
# 云端季度任务（cloud/quarterly.sh）只更新 pool-data 的 pools.json（申万三级各取前 5、
# 约 440 只），而页面第二/五章的股池走的是 finchain 口径：data15/pools_v5.csv
# （总市值 ≥300 亿 × 各行业 FAQ 前 3，约 200~490 只）与 pools_v6_ind50.csv
# （行业市值前 50 × 各行业前 3）。这两份文件的生成依赖全量财报、FAQ 面板与市值面板
# （数百 MB，不入库），云端无法自行重建 —— 所以云端一直换不了季。
#
# 做法：换季后由本机跑一次换季，把生成好的名单层提交到 cloud/season/，云端
# `git pull` 后由本脚本覆盖到 data15，再重算净值、重建页面、覆写节点并发布。
#
# 前提：data15 必须已存在（至少要有 px_daily.pkl / factor_ret_15.csv /
# expo_month_15.csv / pool_ret_15.csv / faq 面板等中间件）。不存在时本脚本直接退出，
# 不会造出半套数据 —— 那种情况下需要走冷启动 bootstrap。
#
# 用法：
#   bash cloud/fin_season.sh                 # 覆盖名单 → 重算 → 重建 → 上传发布
#   bash cloud/fin_season.sh --data-only     # 只覆盖名单层，不重建页面
#   bash cloud/fin_season.sh --no-upload     # 重建到本地 out15，不上传
#   GIT_PULL=1 bash cloud/fin_season.sh      # 先 git pull 再执行
#
# 退出码：0 成功 / 7 git 失败 / 9 data15 缺中间件 / 其它 = 对应脚本失败码
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

DATA_ONLY=0
UPLOAD=1
for a in "$@"; do
  case "$a" in
    --data-only) DATA_ONLY=1 ;;
    --no-upload) UPLOAD=0 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) warn "未知参数：$a"; exit 2 ;;
  esac
done

SEASON="$HERE/season"
D15="$("$PY" -c "import sys;sys.path.insert(0,'$POOL_DIR/scripts');from paths import FIN_D15;print(FIN_D15)")"
[[ -n "$D15" ]] || die "取不到 FIN_D15 路径" 9

log "===== 云端换季开始（data15 = $D15）====="

if [[ "${GIT_PULL:-0}" == "1" ]]; then
  pull_all pool-core || exit 7
fi

# ── 前置检查：data15 的中间件必须齐全，否则覆盖名单也跑不出净值 ──
MISS=()
for f in px_daily.pkl factor_ret_15.csv expo_month_15.csv pool_ret_15.csv; do
  [[ -s "$D15/$f" ]] || MISS+=("$f")
done
if ((${#MISS[@]})); then
  warn "data15 缺中间件：${MISS[*]}"
  warn "  说明云端从未跑过 finchain 冷启动，仅有名单层算不出净值。"
  warn "  需先补齐（见 cloud/README.md 的冷启动说明）："
  warn "    - px_daily.pkl        本机 data15 的日线宽表（约 460MB，不入库）"
  warn "    - factor_ret_15.csv   因子月度收益  ← build_factors15.py"
  warn "    - expo_month_15.csv   因子暴露面板  ← build_factors15.py"
  warn "    - pool_ret_15.csv     股池日收益    ← build_px_fin.py 之后由 finchain 生成"
  die "data15 不完整，已停止（未改动任何文件）" 9
fi

[[ -s "$SEASON/pools_v5.csv" ]] || die "缺 cloud/season/pools_v5.csv" 9

# ── 备份 + 覆盖 ──
STAMP="$(date +%Y%m%d_%H%M%S)"
BAK="$D15/_bak_season_$STAMP"
mkdir -p "$BAK"
for f in pools_v5.csv pools_v5_stat.csv pools_v6_ind50.csv pools_v6_ind50_stat.csv universe_pit.csv; do
  [[ -s "$SEASON/$f" ]] || { warn "season 缺 $f，跳过"; continue; }
  [[ -e "$D15/$f" ]] && cp -p "$D15/$f" "$BAK/$f"
  cp -p "$SEASON/$f" "$D15/$f"
  log "  覆盖 $f"
done
log "原文件已备份到 $BAK"

# ── 校验：期数与最新报告期 ──
"$PY" - "$D15" <<'PY' || die "覆盖后校验未通过" 9
import sys, pandas as pd
d15 = sys.argv[1]
v5 = pd.read_csv(f"{d15}/pools_v5.csv", dtype={"code": str})
v6 = pd.read_csv(f"{d15}/pools_v6_ind50.csv", dtype={"code": str})
for nm, d in (("pools_v5", v5), ("pools_v6_ind50", v6)):
    print(f"  [校验] {nm}: {d['asof'].nunique()} 期，最新 {d['asof'].max()}"
          f"（{d.loc[d['asof'] == d['asof'].max(), 'report_period'].iloc[0]}）"
          f" / {len(d.loc[d['asof'] == d['asof'].max()])} 只")
assert v5["asof"].max() == v6["asof"].max(), "v5 与 v6 最新期不一致"
PY

if [[ "$DATA_ONLY" == "1" ]]; then
  log "已按 --data-only 停止：名单层已覆盖，未重算净值、未动页面。"
  exit 0
fi

# ── 重算净值 → 内容包 → 重建页面 ──
cd "$POOL_DIR" || exit 7
log "===== 重算净值（daily_nav15）====="
"$PY" scripts/finchain/daily_nav15.py || die "daily_nav15 失败" 10

log "===== 打包内容（pack_page）====="
"$PY" scripts/finchain/pack_page.py || die "pack_page 失败" 11

if [[ "$UPLOAD" == "1" ]]; then
  log "===== 重建并发布页面 ====="
  "$PY" scripts/finchain/rebuild_page.py --upload --publish || die "页面重建/发布失败" 12
else
  log "===== 重建页面（不上传，--no-upload）====="
  "$PY" scripts/finchain/rebuild_page.py || die "页面重建失败" 12
fi

log "===== 云端换季完成 ====="
