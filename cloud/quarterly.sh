#!/usr/bin/env bash
# 云端季度股池更新（数据侧）：推断报告期 → 抓三大报表 → 评分 → 重建股池 → 重拉行情。
#
# 触发：每年 5/1（一季报）、9/1（中报）、11/1（三季报）各跑一次（4 号保险补跑）。
# 只做「数据侧」第一步；合并股池、重跑回测、刷新页面由定时任务里的后续步骤完成。
#
# 用法：
#   bash cloud/quarterly.sh                  # 自动推断报告期
#   bash cloud/quarterly.sh --period 2026-09-30
#   bash cloud/quarterly.sh --no-fetch       # 跳过财报抓取
#
# 退出码：0 成功 / 7 git 失败 / 其它 = update_latest.py 自身失败码
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

log "===== 季度股池更新开始（工作区 $WS）====="

if [[ "${GIT_PULL:-0}" == "1" ]]; then
  pull_all pool-data pool-core prof-model mom_opt
fi

cd "$PDATA_DIR" || exit 7
mkdir -p "$PDATA_DIR/data/raw"

$PY scripts/update_latest.py "$@"
rc=$?

if [[ $rc -ne 0 ]]; then
  warn "季度股池更新失败（退出码 $rc）；脚本支持断点续跑，可直接重跑"
  exit $rc
fi

log "===== 季度股池更新结束（成功）====="
