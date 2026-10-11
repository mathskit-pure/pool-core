#!/usr/bin/env bash
# 云端周巡检：六大数据源一致性检查（只读，不写数据、不碰页面）。
#
# 用法：
#   bash cloud/weekly.sh
#   GIT_PULL=1 bash cloud/weekly.sh
#
# 退出码：0 全部通过 / 1 有告警（按脚本打印逐条说明）/ 7 git 失败
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

log "===== 周巡检开始（工作区 $WS）====="

if [[ "${GIT_PULL:-0}" == "1" ]]; then
  pull_all pool-core prof-model afgi_tdx
fi

cd "$PROF_DIR" || exit 1
$PY healthcheck.py
rc=$?

if [[ $rc -eq 0 ]]; then
  log "===== 周巡检结束：全部通过 ====="
else
  warn "===== 周巡检结束：有告警（退出码 $rc），按打印逐条处理 ====="
fi
exit $rc
