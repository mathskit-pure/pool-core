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
#   PAGE=1 bash cloud/quarterly.sh           # 额外把页面重发布到线上节点
#   PAGE=1 PAGE_DATA=/path/page_data.json bash cloud/quarterly.sh
#
# 环境变量：
#   PAGE=1        数据侧完成后，调用 pool-core/scripts/republish_page.py
#                 做「渲染 + 三层验证 + 覆写节点 + 发布外部网页」。默认关闭。
#   PAGE_DATA     数据包路径，默认 $PDATA_DIR/data/page_data.json
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

# ------- 页面重发布（新结构） -------
# 线上页面自 2026-10-19 起是「数据包 + 整页重绘」结构，旧的 refresh_page.py 锚点替换
# 已不适用（它会自己识别为 v4 并跳过）。页面更新统一走 pool-core 的 republish_page.py：
#   page_data.json → 渲染 → 三层验证 → import_html 覆写固定节点 → publish 同步外部网页。
#
# 默认不跑：需要数据侧先产出 page_data.json（PAGE_DATA 可指定路径），
# 且发布动作对线上是覆盖式的，故要求显式 PAGE=1。
if [[ "${PAGE:-0}" == "1" ]]; then
  PAGE_DATA="${PAGE_DATA:-$PDATA_DIR/data/page_data.json}"
  if [[ ! -f "$PAGE_DATA" ]]; then
    warn "PAGE=1 但数据包不存在：$PAGE_DATA（先产出 page_data.json，或用 PAGE_DATA 指定）"
  else
    log "===== 页面重发布：$PAGE_DATA → 节点 $PAGE_NODE ====="
    if ( cd "$POOL_DIR" && "$PY" scripts/republish_page.py \
           --data "$PAGE_DATA" --node-id "$PAGE_NODE" --upload --publish ); then
      log "===== 页面重发布完成 ====="
    else
      # 页面失败不回滚数据侧：数据已经落盘，页面可单独重跑
      warn "页面重发布失败（数据侧已完成）。可单独重跑："
      warn "  cd $POOL_DIR && $PY scripts/republish_page.py --data $PAGE_DATA --upload --publish"
    fi
  fi
fi

log "===== 季度股池更新结束（成功）====="
