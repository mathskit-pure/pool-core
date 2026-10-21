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
