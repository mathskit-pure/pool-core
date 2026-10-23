#!/usr/bin/env bash
# 云端首次初始化：装依赖 → 装 westock → 克隆 5 个仓库 → 冷启动建缓存。
#
# 约定：大体积行情缓存不入库，云端首次自行重建（本脚本），之后由 daily.sh 增量维护。
# 幂等：每个阶段都先检查产物是否已存在，已存在就跳过；中断后重跑可续。
#
# 用法：
#   bash cloud/bootstrap.sh              # 跑全部阶段
#   STAGES="repos westock deps" bash cloud/bootstrap.sh   # 只跑指定阶段
#   SKIP_PROF=1 bash cloud/bootstrap.sh  # 跳过最耗时的 PROF 财报全量抓取
#
# 阶段：deps / westock / repos / afgi / pool / ohlc / rebuild / prof / check
# 退出码：0 成功；7 git 失败；8 westock 失败；其它 = 各脚本自身失败码
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

STAGES="${STAGES:-deps westock repos afgi pool ohlc rebuild prof check}"
has_stage() { case " $STAGES " in *" $1 "*) return 0;; *) return 1;; esac; }

log "===== 云端 bootstrap 开始（工作区 $WS）====="
log "解释器：$($PY -V 2>&1)  系统：$(uname -s) $(uname -m)"

# ---------------------------------------------------------------- 依赖
if has_stage deps; then
  log "--- [deps] Python 依赖"
  pip_install --upgrade pip
  # afgi_tdx 自带 requirements.txt（pandas/numpy/pytdx）；其余工程依赖同样的三件套
  # 却没有声明文件，所以这里直接装，避免等仓库克隆完才发现缺包
  pip_install pandas numpy pytdx
  log "--- [deps] 完成"
fi

# ---------------------------------------------------------------- westock
if has_stage westock; then
  log "--- [westock] 行情 CLI"
  install_westock
fi

# ---------------------------------------------------------------- 克隆仓库
if has_stage repos; then
  log "--- [repos] 克隆/更新 5 个仓库"
  pull_all
  [[ -f "$AFGI_DIR/requirements.txt" ]] && pip_install -r "$AFGI_DIR/requirements.txt"
  log "--- [repos] 完成"
fi

# ---------------------------------------------------------------- AFGI 缓存
if has_stage afgi; then
  log "--- [afgi] 建立行情缓存（约 4~10 分钟）"
  ( cd "$AFGI_DIR" && $PY run.py --bars 800 ) || die "AFGI 缓存建立失败" 20
  log "--- [afgi] 完成"
fi

# ---------------------------------------------------------------- 主项目行情
if has_stage pool; then
  log "--- [pool] 主项目冷启动"
  mkdir -p "$POOL_DIR/data"

  # 1) 页面模板：从资料库线上节点直接取（唯一权威来源，不入库）
  ( cd "$POOL_DIR" && $PY cloud/seed_page_base.py ) || die "页面模板拉取失败" 21

  # 2) 基准指数（沪深300 / 创业板50 / 科创50）
  if [[ -s "$POOL_DIR/data/bench_all.csv" ]]; then
    log "  bench_all.csv 已存在，跳过"
  else
    ( cd "$POOL_DIR" && $PY scripts/fetch_bench.py ) || die "基准指数抓取失败" 22
  fi

  # 3) 个股全区间 hfq 日线（2019-01-01 → 今天，支持断点续跑）
  if [[ -s "$POOL_DIR/data/prices_full_v2.csv" ]]; then
    log "  prices_full_v2.csv 已存在，跳过"
  else
    log "  拉取 ~560 只标的全区间日线，预计 20~40 分钟（脚本支持断点续跑）"
    ( cd "$POOL_DIR" && $PY scripts/fetch_prices_v2.py ) || die "个股全量行情抓取失败" 23
  fi
  log "--- [pool] 完成"
fi

# ---------------------------------------------------------------- 原始 OHLC
if has_stage ohlc; then
  log "--- [ohlc] 原始不复权日 K（涨停判定 / T+1 开盘价必需），约 10~30 分钟"
  mkdir -p "$MOM_DIR/data"
  if [[ -s "$MOM_DIR/data/ohlc_raw.csv" ]]; then
    log "  ohlc_raw.csv 已存在，跳过"
  else
    ( cd "$MOM_DIR" && $PY scripts/fetch_ohlc.py --incr ) || die "原始 OHLC 抓取失败" 24
  fi
  log "--- [ohlc] 完成"
fi

# ---------------------------------------------------------------- 首次回测
if has_stage rebuild; then
  log "--- [rebuild] 动量轮动引擎首次回测"
  ( cd "$MOM_DIR" && $PY scripts/rebuild.py ) || die "回测失败" 25
  log "--- [rebuild] 完成"
fi

# ---------------------------------------------------------------- PROF 财报
if has_stage prof; then
  if [[ "${SKIP_PROF:-0}" == "1" ]]; then
    log "--- [prof] SKIP_PROF=1，跳过（PROF 首次跑需要 daily.sh 补）"
  else
    log "--- [prof] 财报全量抓取（最耗时，40~60 分钟，支持断点续跑）"
    mkdir -p "$PROF_DIR/prof" "$PROF_DIR/pool"
    ( cd "$PROF_DIR" && $PY catchup.py ) || warn "catchup 未完成（可重跑续跑）"
    ( cd "$PROF_DIR" && $PY sync_prices.py ) || warn "行情同步失败"
    ( cd "$PROF_DIR" && $PY prof_score.py ) || die "PROF 评分失败" 26
    ( cd "$PROF_DIR" && $PY backtest_prof.py ) || die "PROF 回测失败" 27
    log "--- [prof] 完成"
  fi
fi

# ---------------------------------------------------------------- 自检
if has_stage check; then
  log "--- [check] 产物自检"
  miss=0
  for f in \
    "$AFGI_DIR/output/afgi_timeseries.csv" \
    "$POOL_DIR/data/page_base.html" \
    "$POOL_DIR/data/mood_q28.json" \
    "$POOL_DIR/data/prices_full_v2.csv" \
    "$POOL_DIR/data/bench_all.csv" \
    "$MOM_DIR/data/ohlc_raw.csv"
  do
    if [[ -s "$f" ]]; then log "  OK   $(basename "$f")"; else warn "  缺失 $f"; miss=$((miss+1)); fi
  done
  [[ "$miss" -eq 0 ]] || die "自检发现 $miss 个缺失产物" 30
fi

log "===== bootstrap 完成 ====="
log "下一步：先跑一次 bash cloud/daily.sh 验证整链，再建云端定时任务"
