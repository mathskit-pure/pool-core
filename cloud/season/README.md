# cloud/season —— 股池「名单层」快照

云端换季用的输入。由 `cloud/fin_season.sh` 覆盖到 `data15/`。

## 为什么入库

页面第二/五章的股池走 finchain 口径（不是 pool-data 的 pools.json）：

| 文件 | 口径 | 谁在用 |
|---|---|---|
| `pools_v5.csv` | 总市值 ≥300 亿 × 申万三级行业各取 FAQ 前 3 | 二章股池、第五章 Q28、第六章名单 |
| `pools_v6_ind50.csv` | 行业市值前 50 × 各行业 FAQ 前 3 | 第五章 CSFM / TSFM |
| `universe_pit.csv` | 每期 ≥300 亿 且剔除 ST / 上市未满 365 天 的标的池 | 上面两份的上游，供核验 |

生成这三份要全量财报（`fund/*.csv` 约 203MB）、FAQ 面板、市值面板 —— 都不入库，
云端也没有抓取入口，所以云端一直换不了季。换季后由本机跑一遍，把结果提交到这里，
云端 `git pull` 即可同步。总量约 1.9 MB。

## 何时更新

每次换季（5/1 一季报、9/1 中报、11/1 三季报）之后，在本机执行：

```bash
cd <work15>              # 本机 2026-10-19-13-04-18/work
python build_universe_1800.py        # 重建标的池（36 期）
python build_pools_v5.py             # 重建 pools_v5（36 期）
cd <pool-core>
python scripts/finchain/build_pools_v6_ind50.py   # 重建 v6（36 期）
cp <work15>/data15/{pools_v5.csv,pools_v5_stat.csv,pools_v6_ind50.csv,pools_v6_ind50_stat.csv,universe_pit.csv} cloud/season/
git add cloud/season && git commit -m "chore(season): <报告期> 股池快照"
```

然后云端执行 `bash cloud/fin_season.sh`（或等季度任务自动调用）。

## 注意

- 这三个文件是**时点快照**，必须与 `data15/px_daily.pkl` 的行情末端大致同期；
  行情领先快照太久时，第五章最新一期会是旧报告期，`rebuild_page.py` 里的
  `stale_pool()` 闸门会拒绝上传（保护线上不被旧数据覆盖）。
- 期数必须完整。2026-11 曾因误判"期数被扩大"，把 36 期截成 2019 年起的 24 期，
  导致 Q28 少了 2015~2018 的 12 期、净值从 2015-05 才开始。**36 期是生产基线**。
- `fin_season.sh` 覆盖前会备份到 `data15/_bak_season_<时间戳>/`，可随时回滚。
