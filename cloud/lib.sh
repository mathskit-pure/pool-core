#!/usr/bin/env bash
# 云端流水线公共变量与函数（被 bootstrap.sh / daily.sh / weekly.sh / quarterly.sh source）
#
# 云端布局（可用 WB_WORKSPACE 整体改写）：
#   /workspace/afgi_tdx    AFGI 情绪指数        github.com/mathskit-pure/afgi-tdx
#   /workspace/pool-core   舞弊因子主项目        github.com/mathskit-pure/pool-core
#   /workspace/prof-model  PROF 盈利能力模型     github.com/mathskit-pure/prof-model
#   /workspace/mom_opt     动量轮动回测引擎      github.com/mathskit-pure/mom-opt
#   /workspace/pool-data   季度股池数据侧        github.com/mathskit-pure/pool-data
#
# 五个仓库均为公开仓库，云端免凭证 git clone / pull。
set -uo pipefail

WS="${WB_WORKSPACE:-/workspace}"
export PATH="$HOME/.local/bin:$PATH"
PY="${PYTHON:-python3}"

AFGI_DIR="$WS/afgi_tdx"
POOL_DIR="$WS/pool-core"
PROF_DIR="$WS/prof-model"
MOM_DIR="$WS/mom_opt"
PDATA_DIR="$WS/pool-data"

GITHUB_USER="${GITHUB_USER:-mathskit-pure}"
PAGE_NODE="iB8I58mCTooLicPQ0Kyq0M"

log()  { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
warn() { printf '[%s] !! %s\n' "$(date '+%H:%M:%S')" "$*" >&2; }
die()  { printf '[%s] !! %s\n' "$(date '+%H:%M:%S')" "$*" >&2; exit "${2:-1}"; }

# 仓库目录名 → GitHub 仓库名（目录名与仓库名不一致的只有 mom_opt / afgi_tdx）
repo_name() {
  case "$1" in
    afgi_tdx)  echo "afgi-tdx" ;;
    pool-core) echo "pool-core" ;;
    prof-model) echo "prof-model" ;;
    mom_opt)   echo "mom-opt" ;;
    pool-data) echo "pool-data" ;;
    *)         echo "$1" ;;
  esac
}

# clone_or_pull <目录名>：不存在就 clone，存在就 pull（pull 失败只告警，沿用现有代码）
clone_or_pull() {
  local name="$1" dir="$WS/$1" url="https://github.com/$GITHUB_USER/$(repo_name "$1").git"
  if [[ -d "$dir/.git" ]]; then
    git -C "$dir" pull --ff-only -q || warn "git pull 失败（$name），沿用现有代码"
  else
    mkdir -p "$WS"
    git clone -q "$url" "$dir" || die "git clone 失败：$url" 7
  fi
}

# pull_all [目录名...]：默认拉全部
pull_all() {
  local names=("$@")
  [[ ${#names[@]} -eq 0 ]] && names=(afgi_tdx pool-core prof-model mom_opt pool-data)
  for n in "${names[@]}"; do clone_or_pull "$n"; done
}

# pip 安装（Debian 托管环境需要 --break-system-packages，逐个尝试）
pip_install() {
  if "$PY" -m pip install -q "$@" 2>/dev/null; then return 0; fi
  "$PY" -m pip install -q --break-system-packages "$@"
}

# 安装 westock CLI（跨平台 Go 二进制，公网下载、无鉴权）
install_westock() {
  if command -v westock >/dev/null 2>&1; then
    log "westock 已存在：$(command -v westock)"
    return 0
  fi
  local ver="${WESTOCK_VERSION:-v0.0.4}"
  local os arch
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m)"; case "$arch" in x86_64|amd64) arch="amd64";; aarch64|arm64) arch="arm64";; esac
  local url="https://stockbuddy.qq.com/release/workbuddy/cli/${ver}/westock-${os}-${arch}"
  log "安装 westock：$url → ~/.local/bin/westock"
  mkdir -p "$HOME/.local/bin"
  curl -fsSL "$url" -o "$HOME/.local/bin/westock" || die "westock 下载失败：$url" 8
  chmod +x "$HOME/.local/bin/westock"
  export PATH="$HOME/.local/bin:$PATH"
  grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null || \
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
  westock --help >/dev/null 2>&1 || die "westock 安装后不可用" 8
  log "westock 安装完成"
}
