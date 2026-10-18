# 云端定时任务配置（粘贴到 App「云端工作 → 自动化 → +」）

> 桌面会话创建的是**本机**任务；云端任务只能在 WorkBuddy App / 网页端的
> 「云端工作」里创建。下面 4 条按「新建定时任务 → 粘贴 prompt → 设时间」操作即可。
>
> 工作目录（cwds）统一填：`/workspace/pool-core`
>
> ⚠️ **禁止双跑**：创建云端任务的同时，必须把对应的本机任务置为 PAUSED，
> 两条链路会覆写同一个资料库页面节点 `iB8I58mCTooLicPQ0Kyq0M`，互相覆盖。

---

## 0. 先跑一次：云端环境初始化（一次性，不是定时任务）

**调度类型**：一次性（选一个你有空的时段，建议晚上）

```text
在云端工作区 /workspace 初始化 A 股因子流水线的运行环境。

执行（耗时较长，请后台运行并等待完成，可能 1~3 小时）：

    git clone https://github.com/mathskit-pure/pool-core.git /workspace/pool-core || true
    bash /workspace/pool-core/cloud/bootstrap.sh

脚本会依次完成：装 Python 依赖（pandas / numpy / pytdx）→ 装 westock 行情 CLI →
克隆 5 个公开仓库到 /workspace（afgi_tdx / pool-core / prof-model / mom_opt / pool-data）
→ 建立 AFGI 行情缓存 → 从资料库线上节点拉取页面模板 → 重拉个股全区间 hfq 日线与基准指数
→ 拉原始不复权 OHLC → 首次回测 → PROF 财报全量抓取与回测 → 产物自检。

要点：
· 大体积行情缓存不入库，全部由本脚本重建；每个阶段先检查产物是否已存在，已存在就跳过，
  中断后直接重跑同一条命令即可续跑，不会产生重复数据。
· PROF 财报抓取最耗时（40~60 分钟）。时间不够可 `SKIP_PROF=1 bash cloud/bootstrap.sh`
  先跳过，后续由每日任务自动补上。
· 只跑指定阶段：`STAGES="repos westock deps" bash cloud/bootstrap.sh`。

退出码：0 成功；7 git 失败；8 westock 安装失败；20~27 各阶段失败；30 自检发现缺失产物。

完成后汇报：各阶段成功与否、/workspace 下的目录清单、关键产物的体积与最新日期
（afgi_timeseries.csv / prices_full_v2.csv / bench_all.csv / ohlc_raw.csv / page_base.html）。
若有阶段失败，指出是哪一阶段与错误摘要；修好后重跑同一条命令即可。
```

初始化成功后，再跑一次 `GIT_PULL=1 bash /workspace/pool-core/cloud/daily.sh` 验证整链，
然后才启用下面的定时任务。

---

## 1. A股因子流水线·每日整链（主刷新 → 发布）

**调度类型**：重复 · 每周 周二/周三/周四/周五/周六 · 09:00
（T+1 上午处理 T 日数据；AFGI 由 07:30 的独立云端任务先完成，本任务是第二、三棒）

```text
在云端执行「舞弊调整质量因子·季度动态股池」的每日整链（主刷新 → 复核发布）。

    GIT_PULL=1 bash /workspace/pool-core/cloud/daily.sh

【调度位置】T+1 上午 09:00 处理 T 日数据：
  07:30 AFGI 情绪指数（独立任务） → 09:00 主刷新（本任务） → 复核发布（本任务）。
主刷新要读 AFGI 的 afgi_timeseries.csv。

脚本依次完成：
[1/2] 主刷新：增量拉 560 只标的 hfq 日线 → 数据体检（阻断级异常即中止，不写入、不上传）
  → 补齐原始不复权 OHLC → 动量轮动引擎回测（现行 N=15 / K=10 / L=50）
  → 就地刷新页面数据区 → 覆写资料库节点 iB8I58mCTooLicPQ0Kyq0M → 回写 data/page_base.html。
[2/2] PROF：已于 2026-10-18 弃用，整段跳过（v3 版式不含「盈利能力Top40」章节）。
  需要恢复历史计算时用 PROF_ENABLE=1，只跑数据四步，不做页面插入。

退出码：0 成功（含「非交易日跳过」）；10 主刷新失败（整链中止，不发布）；
11 PROF 阶段失败（PROF 已弃用，默认不会触发）。耗时约 10~20 分钟。

汇报（简体中文，简要）：最新交易日、动量轮动累计收益与夏普、质量Top28组合累计收益、
动量×AFGI稳健联合累计收益与当前目标仓位、AFGI 数值与状态、最新调仓日与本次换仓的
买/卖/持有数量、距下次调仓还需几个交易日、
页面是否上传成功（https://www.workbuddy.cn/space/d/iB8I58mCTooLicPQ0Kyq0M ）。

若退出码非 0，说明失败在哪一步与错误摘要 —— 不要绕过数据体检强行上传。
若输出「未探测到新交易日」，说明是休市，直接说明「休市，无需更新」即可。
```

---

## 2. 股池页面数据一致性周巡检

**调度类型**：重复 · 每周 周五 · 12:00

```text
在云端做「舞弊调整质量因子·季度动态股池」三条流水线的数据一致性巡检
（只读，不写任何数据、不碰页面）。

    GIT_PULL=1 bash /workspace/pool-core/cloud/weekly.sh

脚本会并排列出六个数据源的最新日期 —— 主项目回测净值 nav.csv、主项目 hfq 行情
prices_full_v2.csv、AFGI 情绪指数 afgi_timeseries.csv、AFGI 仓位组合净值
afgi_combo_nav.csv、盈利能力模型回测净值 prof_nav.csv、PROF 本地行情副本 ——
并检查季度股池是否已纳入最新报告期。

容差（脚本已内置）：PROF 两个数据源已随「盈利能力Top40」弃用（2026-10-18）退出判定，
巡检表里只打印日期并标〔已弃用〕，不参与告警。

退出码 0：回复一句「本周巡检通过，全部数据源最新日期 = XXXX-XX-XX」，并给出页面链接
https://www.workbuddy.cn/space/d/iB8I58mCTooLicPQ0Kyq0M 即可。

退出码 1：按脚本打印的告警逐条用简体中文说明（哪条数据落后、落后几个交易日、股池缺哪个
报告期），并给出修复动作 ——
· 「AFGI 落后」：在 /workspace/afgi_tdx 补跑 run.py，并把报告覆写到固定节点 ddbJ1onUkhBUybcqWTrwG5；
· 「主刷新落后」：补跑 GIT_PULL=1 bash /workspace/pool-core/cloud/daily.sh；
· 「PROF 落后」：已弃用（2026-10-18），两个 PROF 源不再参与判定，可忽略；
  确需重算用 PROF_ENABLE=1 重跑 daily.sh（只跑数据，不做页面插入）；
· 「股池缺报告期」：补跑季度股池任务。
```

---

## 3. 更新舞弊调整质量因子季度股池（5/1 · 9/1 · 11/1）

**调度类型**：重复 · 每年 5/9/11 月 · 1 号与 4 号 · 05:30
（1 号主跑、4 号保险补跑；全流程幂等、支持断点续传，重复执行安全）

```text
在云端更新「舞弊调整质量因子 · 季度动态股池」。

第一步（数据侧）：

    GIT_PULL=1 bash /workspace/pool-core/cloud/quarterly.sh

该脚本按当天日期自动推断目标报告期（5 月 → 一季报 03-31，9 月 → 中报 06-30，
11 月 → 三季报 09-30），用固定标的清单 scripts/codes_big.json 抓该报告期及前推一年的
三大报表，按舞弊调整质量因子模型（质量分 Q − 标准化舞弊概率 F）评分，按申万三级行业
各取前 5 重建季度股池，并重拉股池个股前复权日线。脚本默认 --no-import（只做数据侧，
不碰线上页面）。

第二步（把新一季股池并入两条现行流水线）：
1. 把新生成的报告期（含 asof 信息可得日、成员名单与 FAQ 评分）合并进两份股池文件，
   保持原有 JSON 结构不变、只追加/覆盖该报告期：
   - /workspace/pool-core/data/pools.json
   - /workspace/prof-model/pools.json 与 pools_compact.json
2. 重跑回测（顺序不可颠倒）：
   - cd /workspace/mom_opt && python3 scripts/rebuild.py
     （严禁再调用 pool-core/scripts/backtest.py，那是已废止的旧口径）
   - cd /workspace/prof-model && python3 sync_prices.py && python3 prof_score.py
     && python3 backtest_prof.py（缺财报就先跑 catchup.py）
3. 刷新页面（PROF 页面插入已弃用，**不要**再跑 update_prof_data --page-only / sync_page_base）：
   - GIT_PULL=1 bash /workspace/pool-core/cloud/daily.sh 或
     cd /workspace/pool-core && python3 scripts/refresh_page.py，
     随后用资料库 page/import_html.py 覆写节点 iB8I58mCTooLicPQ0Kyq0M
     —— 必须带 --node-block-id iB8I58mCTooLicPQ0Kyq0M，绝不能新建页面。

【三条硬约束】
· 绝对不要运行 pool-core/scripts/gen_page.py 或 gen_pages.py 全量重生成页面，那会抹掉
  线上已有的交互时间轴、CSFM/TSFM 两个因子动量组合与「四、历史仓位建议」模块（v3 版式）。
· 若第二步任何一步失败或数据不完整，立即停止并汇报，不要用半成品覆写线上页面。
· 现行组合口径：质量组合为「质量Top28组合」v2 三道筛（剔除 20 日均成交额 < 5,000 万、
  按换手率代理＝20 日均成交额÷总市值 剔除最拥挤 1/3、权重 ∝ 1/(换手分位+0.15)、
  单只限幅 2%~8%）；CSFM / TSFM 两个因子动量组合与 B-score（质量Top30×估值择时）
  由各自链路维护；「盈利能力Top40」已于 2026-10-18 弃用，不再计算、不上页面。

重要：财报接口有频控，脚本内置自适应退避，全流程可能耗时 40~60 分钟，必须让它跑完，
不要中途中断；若中途失败可直接重跑（各阶段均有断点续传）。

完成后汇报：本次更新的报告期、股池覆盖行业数与入选只数、因子动量 CSFM / 因子动量 TSFM /
质量Top28组合 三者的累计收益与最大回撤，以及页面链接
https://www.workbuddy.cn/space/d/iB8I58mCTooLicPQ0Kyq0M 。
若本次是 4 号补跑且 1 号已成功，只需说明补跑结果（新增/补齐了哪些标的，或「无新增」）。
```

---

## 启用顺序与切换检查表

| # | 动作 | 本机对应任务（需置 PAUSED） |
|---|---|---|
| 0 | 跑一次 bootstrap，再手动跑一次 daily.sh 验证 | — |
| 1 | 建「每日整链」云端任务（周二–周六 09:00） | 主刷新 `15ac7d83`（PROF `a7a3aeb2` 已弃用，保持暂停） |
| 2 | 建「周巡检」云端任务（周五 12:00） | 周巡检 `67f38af0` |
| 3 | 建「季度股池」云端任务（5/1·9/1·11/1 05:30） | 季度股池 `7535b496` |
| 3b | 建「每日仓位建议」云端任务（周二–周六 08:10，`cloud/pos_daily.sh`） | 无（新增） |

AFGI 本机任务 `3e8ca80b` 早已有独立的云端任务在跑，不在此列。
验证云端连续 3~5 个交易日稳定后，再决定删除还是长期保留本机任务（保留即必须保持 PAUSED）。

---

## 5 号｜每日仓位建议刷新（CSFM / TSFM）

> 独立任务，不参与 1 号主刷新链。只更新「四、CSFM 和 TSFM 历史仓位建议」图表数据
> 与「五、持仓变动明细」里 16 个调仓日的仓位方框，不动股池、持仓名单和第三节净值。

**建议调度**：周二–周六 08:10（主刷新 09:00 之前跑完，页面一早就带最新仓位）。
**执行命令**：

```bash
cd /workspace/pool-core && GIT_PULL=1 bash cloud/pos_daily.sh
```

**等价的 agent 提示词**（若用自然语言任务）：

```
刷新季度股池页面的 CSFM / TSFM 建议仓位。

1. cd /workspace/pool-core && git pull
2. 确保 data/fbook_monthly.csv（持仓加权反馈强度 F 的月度序列）、
   data/idx_932000.csv（中证2000）、data/idx_399006.csv（创业板指）存在；
   缺任一项就停止并汇报，不要用残缺数据覆写页面。
3. 执行 python3 scripts/pos_sync.py --page data/_live/page.html --download
   --fbook data/fbook_monthly.csv --upload --publish
   —— 脚本会：拉取线上页面 → 用页面内嵌的 BT 净值重算仓位（过热降仓 / 60日均线破位 /
   TSFM 的 F 门控，取最小值，T 日决策 T+1 生效）→ 覆写「var POS」数据 →
   刷新 16 个仓位方框与图例里的当前仓位 → 用 import_html.py --node-block-id
   iB8I58mCTooLicPQ0Kyq0M 覆写同一节点 → 重新发布外部网页。
4. 汇报：最新交易日、CSFM 与 TSFM 的当期建议仓位、是否触发降仓（哪条规则）。

【硬约束】
· 绝不新建页面；节点固定 iB8I58mCTooLicPQ0Kyq0M。
· 只改仓位区块：不要跑 gen_page.py / refresh_page.py / daily_refresh.py，
  否则会用旧模板覆盖线上新版式（含 CSFM/TSFM 两个组合的全部内容）。
· 若线上页面里没有 id="posChart"（说明版式被回滚），立即停止并汇报，
  不要自动插入模块。
```

**fbook_monthly.csv 怎么来**：由本机 `fmf` 工程（因子动量 × F 反馈强度）在每个调仓日重算后
提交到 pool-core 仓库；云端只读。F 门控是月频量，月中不需要更新。

