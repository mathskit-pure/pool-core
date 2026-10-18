#!/usr/bin/env bash
# 每日「仓位建议」刷新（独立任务，不吃主刷新链）
#
# 只做三件事：拉线上页面 → 用页面内嵌净值重算 CSFM/TSFM 建议仓位 → 覆写同一节点并重新发布。
# 不碰股池、不碰持仓名单、不碰第三节净值曲线，因此可以在主刷新链之外单独跑，
# 也不会因为主刷新链的模板版本不一致而被回滚。
#
# 用法：
#   bash cloud/pos_daily.sh                # 只跑
#   GIT_PULL=1 bash cloud/pos_daily.sh     # 先拉代码（定时任务用这个）
#
# 退出码：0 成功 / 12 仓位同步失败
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

log "===== 仓位建议刷新开始（工作区 $WS）====="

if [[ "${GIT_PULL:-0}" == "1" ]]; then
  pull_all pool-core
fi

cd "$POOL_DIR" || { warn "进入 $POOL_DIR 失败"; exit 12; }
mkdir -p data/_live

$PY scripts/pos_sync.py \
  --page data/_live/page.html \
  --download \
  --fbook data/fbook_monthly.csv \
  --upload --publish
rc=$?

if [[ $rc -ne 0 ]]; then
  warn "仓位同步失败（退出码 $rc）；页面未改动"
  exit 12
fi

log "===== 仓位建议刷新结束（成功）====="
