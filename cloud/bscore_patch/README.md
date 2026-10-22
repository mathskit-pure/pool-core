# B-score 看板增量刷新（五章式）

线上页面 `VLeP5CSpUchSY3qawGq88W` 在 2026-10-22 恢复成「五章式」结构后，原有的
`import_html.py` 整体覆写会把页面换成另一套自动看板模板。这里改成**在现有页面上打补丁**：
只替换动态读数，章节、文案、样式、节点标记全部保持原样。

## 一条命令

```bash
GIT_PULL=1 bash /workspace/pool-core/cloud/bscore_patch/run.sh
```

做的事：
1. 取线上当前页当基线（失败则退回本目录 `template_v23.html`）；若线上页已不是五章式结构，自动用模板重建。
2. 用 `/workspace/bscore/data/latest.json` 的读数 + `/workspace/bscore/data/cb_history.csv` 兜底，
   刷新四类区域：指标表 6 行、三大指数表 3 行、触发测算段、第四章走势图。
3. 通过 `import_html.py` 写回原节点。

退出码：`0` 已刷新 / `3` 缺数据安全跳过 / `2` 补丁失败（页面不动）/ `1` 环境异常。

## 只改哪四类地方

| 区域 | 内容 |
|---|---|
| 一、当前指标与历史分位 | 便宜度分位（当前/历史）、PB 便宜分位（PB/分位）、双便宜均值 CB、破净股占比、加权 PB、有效样本 |
| 二、指数状态 | 沪深300 / 中证500 / 中证1000 的收位、涨跌幅、距250日高点回撤 |
| 三、买卖建议 | 「触发测算」段的三个目标值与三个「（当前 X）」 |
| 四、历史走势 | 月频 CB 曲线（有月频序列源才重绘，否则保留原图） |

## 读数 schema（`latest.json` 读不动时的降级格式）

若云端 `latest.json` 的键名与刷新器的候选键都对不上（刷新器会以退出码 2 明确报出来），
就让上层按下面的固定 schema 另写一份 `readings.json`，再用 `BSCORE_LATEST` 指过去，
**数值必须从 `latest.json` / 页面原文逐字抄**，不要自己算：

```json
{
  "trade_date": "2026-10-21",
  "cb": 0.571,
  "bm_median": 0.412, "bm_hist": 0.658,
  "pb": 3.74, "pb_percentile": 0.503,
  "broken_net": 7.6, "weighted_pb": 2.21, "sample_n": 5273,
  "index": {
    "hs300":  {"close": 4238, "chg": 1.6,  "dd": -16.2},
    "zz500":  {"close": 6891, "chg": -0.4, "dd": -23.7},
    "zz1000": {"close": 6815, "chg": 0.0,  "dd": -24.0}
  },
  "trigger": {"pb": 2.86, "bm": 0.669, "hs300": 4022}
}
```

要点：
- 百分位类（`cb` / `bm_*` / `pb_percentile` / `trigger.bm`）写 **0~1**；写成 0~100 会被自动除以 100。
- 涨跌幅与回撤（`chg` / `dd`）写**百分数数值**（`-16.2` 表示 −16.2%），不是小数。
- 刷新器会做量级校验（PB 0.01~50、指数点位 100~100000 等），越界直接退出码 2，不写页面。

## 数据过期横幅（`stale_banner.py`）

看板依赖云端任务刷新，任务一旦停摆，页面会「安静地过期」——页头只有一行小字，很容易被当成最新信号。
`stale_banner.py` 在页头下方插一条醒目横幅，写清数据停在哪个交易日、已连续多少个交易日未更新：

```bash
python3 stale_banner.py --html 当前页.html --out 带横幅.html \
  --data-date 2026-10-16 --reason "10-22 02:00 与 03:30 两棒均无任何写入"
```

- 横幅带 `<!--STALE_BANNER:start-->` / `end` 标记，**幂等**（重复跑不会叠加）。
- `patch_v23.py` 刷新成功时会**自动摘掉**整块横幅——数据新鲜了就不该还挂着过期提示。
- 交易日只按周末扣除，不含法定节假日库；今天未收盘不计入。

## 安全设计

- **锚点未命中就退出，不写页面**。宁可当天不刷，也不写坏版式。
- 字段解析用「候选键 + 父键拼接 + 归一化模糊匹配」，兼容 `latest.json` 键名调整；
  `latest.json` 缺的估值字段自动回退到 `cb_history.csv` 最后一行。
- `--probe` 只导出真实结构不写页面，用于首次对接/键名变更时核对：

```bash
python3 patch_v23.py --template template_v23.html --latest /workspace/bscore/data/latest.json \
  --history /workspace/bscore/data/cb_history.csv --out /dev/null --probe --json-out /tmp/probe.json
```

## 本机回归结果（2026-10-22）

| 用例 | 结果 |
|---|---|
| 把页面自身读数回灌 | 输出与模板逐字节一致 |
| 换一组新读数 | 仅 22 行变化，全在四类锚点内 |
| 故意删掉 `cb` 字段 | 退出码 2，不产出文件 |
| `cb` 只存在于 `cb_history.csv` | 自动回退取值成功 |
| 标签配平（html/body/table/tr/td/script/style/b） | 全配平 |
