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
#   PAGE=1 bash cloud/quarterly.sh           # 额外把页面重建并发布到线上节点
#
# 环境变量：
#   PAGE=1        数据侧完成后，调用 pool-core/scripts/finchain/rebuild_page.py
#                 做「选股/净值 → 内容包 → 原位替换 → 门禁 → 覆写节点 → 发布」。
#                 页面结构沿用原版，只换内容。默认关闭。
#
# 退出码：0 成功 / 7 git 失败 / 其它 = update_latest.py 自身失败码
#        （页面重发布失败只 warn，不改变退出码 —— 数据侧成功就算成功，页面可单独重跑）
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

# 默认 --no-import：update_latest.py 末尾会用本工程自己的 gen_page.py 全量重生成
# data/pool_page.html 并直接覆写页面节点 iB8I58mCTooLicPQ0Kyq0M，那会抹掉线上已有的
# 交互时间轴与「盈利能力Top40（4.3）」。所以默认只做数据侧，页面合并交给后续步骤
# （与本机季度任务的三条硬约束一致）。确实要覆写时显式 IMPORT=1。
if [[ $# -eq 0 && "${IMPORT:-0}" != "1" ]]; then
  log "默认 --no-import（只做数据侧）；如需连页面一起覆写请 IMPORT=1"
  set -- --no-import
fi

$PY scripts/update_latest.py "$@"
rc=$?

if [[ $rc -ne 0 ]]; then
  warn "季度股池更新失败（退出码 $rc）；脚本支持断点续跑，可直接重跑"
  exit $rc
fi

# ------- 页面重发布（原版版式 + 2015-2026 新数据） -------
# 2026-10-19 起页面结构不动，只换内容：走 pool-core 的 scripts/finchain/：
#   daily_nav15.py 选股/净值 → pack_page.py 内容包 → patch_page.py 原位替换
#   → 门禁 → import_html 覆写固定节点 → publish 同步外部网页。
# 整页重绘链路（republish_page.py / pagegen）已废弃，会拒绝执行。
#
# 默认不跑：发布动作对线上是覆盖式的，要求显式 PAGE=1。
if [[ "${PAGE:-0}" == "1" ]]; then
  log "===== 页面重建：节点 $PAGE_NODE ====="
  if ( cd "$POOL_DIR" && "$PY" scripts/finchain/rebuild_page.py --upload --publish ); then
    log "===== 页面重建完成 ====="
  else
    # 页面失败不回滚数据侧：数据已经落盘，页面可单独重跑
    warn "页面重建失败（数据侧已完成）。可单独重跑："
    warn "  cd $POOL_DIR && $PY scripts/finchain/rebuild_page.py --upload --publish"
  fi
fi

log "===== 季度股池更新结束（成功）====="
