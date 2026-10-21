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

线上季度股池页 = **原版版式 + 2015-2026 新数据**：结构、样式、交互、图表 JS 全部沿用原版，
只是把说明文字、35 期股池、三个组合的回测/调仓数据换成了新口径。页面里仍有
`var BT=` / `svg#btChart` / `td#r{i}_{c}` 这些老锚点，靠 `<!--page-engine:finchain-v5-->` 标记区分。

| 脚本 | 适用结构 | 现状 |
|---|---|---|
| `scripts/finchain/rebuild_page.py` | 原版版式 + 新数据（v5） | **当前唯一可用**，季度/每日页面更新走这里 |
| `scripts/refresh_page.py` | 旧结构（v2/v3） | 已加版式守卫：识别到 v4/v5 会打印提示并**跳过（退 0）** |
| `scripts/republish_page.py` + `scripts/pagegen/` | 整页重绘（v4） | **已废弃**：默认退 9 拒绝执行（用户否决了改版 UI） |

`rebuild_page.py` 三步可单独跑：

```
daily_nav15.py ──> out15/page_content.json ──> pool_page_v5.html ──门禁──> import_html ──> publish
```

- `daily_nav15.py` 复现 CSFM/TSFM/质量Top28 选股，再把月度/季度持仓用「份额自然漂移」展开成**逐日净值**
  （页面图表按交易日计算，月度净值喂不进去）；
- `pack_page.py` 打包内容，六条曲线统一在 2015-02-27 归一到 1.00；
- `patch_page.py` 在 `data/page_base.html` **原位替换**内容，不新增/删除任何标签结构；
- 上传前跑与 `daily_refresh.py` 同一套门禁，缺区块或命中旧口径特征即拒绝上传（线上保持原状）。

**`data/page_base.html` 是干净原版模板，finchain 链路不回写它** —— 每次都从它出发，
回写会导致下一次在已替换内容上二次替换。页面引擎由 `data/page_engine.txt`（值 `finchain-v5`）显式声明。

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

## B-score 看板的组合模块（cloud/bscombo/）

`A股B-score择时信号看板`（节点 `VLeP5CSpUchSY3qawGq88W`）由两段组成：
底座看板（`/workspace/bscore/src/daily_update.py` 生成）= CB 读数与信号；
组合模块（本目录脚本）= 质量Top28 × 择时信号的搭配、回测对比、持仓与建议仓位。

```bash
python3 cloud/bscombo/rebuild_bscombo.py            # 重算 → 回写页面 → 重新发布
python3 cloud/bscombo/rebuild_bscombo.py --dry-run  # 只算不改页面
```

口径（2026-10-21 修订，替换旧的 `/workspace/bscombo/update_bscombo.py`）：

- 净值直接取 `data/page_data.json` 里股池页发布的质量Top28 v2 序列，两页数字同源；
- 仓位＝`0.3 + 0.7 × 1[沪深300 > 月线 MA10]`，月末决定、下月生效；
- CB 从「仓位主控」降级为「风险提示阀」：仅在 CB<0.15（极贵）时把仓位再打 5 折；
- 出图前断言每条曲线 ≥12 个不同取值，防止再出现「250 个点同一高度」的假曲线。

失效背景：旧口径 `clip((CB−0.354)/0.45)` 在 2015-2026 全样本把夏普从 0.58 压到 0.18、
年化从 11.6% 压到 1.6% —— 估值分位砍掉的是上涨段，挡不住下跌段。
