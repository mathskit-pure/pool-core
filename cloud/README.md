# 云端流水线编排脚本

本机 Windows 与云端 Linux 共用同一份业务代码：所有路径由各工程的 `paths.py`
集中解析（Windows 沿用既有 WorkBuddy 目录，Linux 走 `/workspace` 兄弟布局），
因此这里只需要编排「谁先跑、谁后跑」，不再需要维护两套代码。

## 云端目录布局

| 目录 | 工程 | GitHub 仓库 |
|---|---|---|
| `/workspace/afgi_tdx` | AFGI 市场情绪指数 | `mathskit-pure/afgi-tdx` |
| `/workspace/pool-core` | 舞弊调整质量因子·主项目 | `mathskit-pure/pool-core` |
| `/workspace/prof-model` | PROF 盈利能力模型 | `mathskit-pure/prof-model` |
| `/workspace/mom_opt` | 动量轮动回测引擎 | `mathskit-pure/mom-opt` |
| `/workspace/pool-data` | 季度股池数据侧 | `mathskit-pure/pool-data` |

五个仓库都是公开仓库，云端免凭证 `git clone` / `git pull`。

## 脚本

| 脚本 | 作用 | 对应云端定时任务 |
|---|---|---|
| `bootstrap.sh` | 首次初始化：装依赖 + westock CLI + 克隆仓库 + **冷启动建缓存** | 手工跑一次 |
| `daily.sh` | 每日整链：主刷新 → PROF | 每交易日 T+1 上午 |
| `weekly.sh` | 六大数据源一致性巡检（只读） | 每周五 |
| `quarterly.sh` | 季度股池数据侧更新（`PAGE=1` 时连带重发布页面） | 5/1 · 9/1 · 11/1 |
| `lib.sh` | 公共变量与函数（被上面几个 source） | — |
| `seed_page_base.py` | 从资料库线上节点拉模板 → `data/page_base.html` | bootstrap 调用 |

### 页面更新走哪条路（重要）

线上季度股池页自 2026-10-19 起是**「数据包 + 整页重绘」**结构：净值全靠内联 JS 现画，
股池按行业分组嵌套渲染，页面里没有 `var BT=` / `svg#btChart` / `td#r{i}_{c}` 这些老锚点。

| 脚本 | 适用结构 | 现状 |
|---|---|---|
| `scripts/republish_page.py` + `scripts/pagegen/` | 新结构（v4） | **当前唯一可用**，季度更新走这里 |
| `scripts/refresh_page.py` | 旧结构（v2/v3） | 已加版式守卫：识别到 v4 会打印提示并**跳过（退 0）**，不会误报失败，也不会把页面改回旧版 |

`republish_page.py` 的四段是分开的，任何一段都能单跑：

```
data/page_data.json ──render──> data/pool_page.html ──verify──> import_html ──> publish
```

- `render` 只吃 `page_data.json`，不碰任何 CSV —— 云端只要拿到数据包就能独立出页面；
- `verify` 做**结构 / 脚本 / 数据**三层检查，其中数据层会用净值曲线反算年化·波动·夏普
  与绩效表互校；任一失败即拒绝上传（`--force` 才会强上）；
- `python scripts/pagegen/selftest.py` 是验证器自己的回归：注入 6 个故障，确认每层都真的会拦。

AFGI 由 **独立的云端任务**负责（它自己有 `cloud/daily.sh`），不在这里。

## 冷启动说明

大体积行情缓存一律不入库，云端首次自行重建：

- `data/page_base.html`（10MB，页面模板）→ 从资料库节点 `iB8I58mCTooLicPQ0Kyq0M` 直接拉线上最新版；
- `data/prices_full_v2.csv`（26MB，hfq 日线）→ `scripts/fetch_prices_v2.py` 全区间重拉，支持断点续跑；
- `data/bench_all.csv` → `scripts/fetch_bench.py`；
- `mom_opt/data/ohlc_raw.csv`（60MB）→ `fetch_ohlc.py --incr`；
- `prof-model/prof/*.csv` → `catchup.py` 全量抓财报（最耗时，40~60 分钟）。

每个阶段都先检查产物是否已存在，已存在就跳过；中断后重跑可续。

## 常用命令

```bash
# 首次初始化（耗时较长，建议后台跑）
bash /workspace/pool-core/cloud/bootstrap.sh

# 只跑某几个阶段
STAGES="repos westock deps" bash cloud/bootstrap.sh
SKIP_PROF=1 bash cloud/bootstrap.sh          # 跳过最耗时的 PROF 财报抓取

# 每日整链
GIT_PULL=1 bash /workspace/pool-core/cloud/daily.sh

# 非交易日也要强制重跑
FORCE=1 GIT_PULL=1 bash cloud/daily.sh

# 周巡检 / 季度股池
GIT_PULL=1 bash cloud/weekly.sh
GIT_PULL=1 bash cloud/quarterly.sh
```

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功（含「非交易日跳过」这种正常结果） |
| 1 | 周巡检有告警 |
| 7 | git clone 失败 |
| 8 | westock CLI 安装失败 |
| 10 | 主刷新失败（整链中止，不跑 PROF） |
| 11 | PROF 任一步失败 |
| 20–27 | bootstrap 各阶段失败（AFGI / 模板 / 基准 / 行情 / OHLC / 回测 / PROF） |
| 30 | bootstrap 自检发现缺失产物 |

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `WB_WORKSPACE` | `/workspace` | 云端工作区根 |
| `PYTHON` | `python3` | Python 解释器 |
| `WESTOCK_VERSION` | `v0.0.4` | westock CLI 版本 |
| `GITHUB_USER` | `mathskit-pure` | 仓库所在账号 |
| `WB_LIBRARY_SKILL` | 自动探测 | 资料库 skill 路径（含 `page/import_html.py`） |
| `WESTOCK_BIN` | Windows `westock.exe` / Linux `westock` | 行情 CLI 路径 |
