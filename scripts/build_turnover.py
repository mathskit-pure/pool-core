# -*- coding: utf-8 -*-
"""为「质量 Top28 组合 v2」构造换手率面板。

换手率代理 = 20 日均成交额 ÷ 总市值（数据源无流通股本，用总市值口径）。
每期取「报告期信息可得日 asof 之后的第一个交易日」= 回测的实际调仓日 T，
只用 T 及之前 20 个交易日的成交额 —— 不含未来数据。

输入
  data/pools.json                    季度股池成员（含 mktcap / asof）
  成交量源（按优先级）
    1) $MOM_OPT_DIR/data/ohlc_raw.csv   兄弟工程 mom_opt 的日线（本地有）
    2) data/ohlc_vol.csv                code,date,close,vol
输出
  data/turnover_panel.csv             报告期,调仓日,code,adv20,mktcap,turn

用法
  python scripts/build_turnover.py                  # 全量重建
  python scripts/build_turnover.py --only-latest    # 只补最新一期（增量追加/覆盖）
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE, DATA, MOM_OPT   # noqa: E402

OUT = os.path.join(DATA, "turnover_panel.csv")
WINDOW = 20


def load_vol():
    for p in (os.path.join(MOM_OPT, "data", "ohlc_raw.csv"),
              os.path.join(DATA, "ohlc_vol.csv")):
        if os.path.exists(p):
            px = pd.read_csv(p, dtype={"code": str})
            px["date"] = pd.to_datetime(px["date"])
            px["close"] = pd.to_numeric(px["close"], errors="coerce")
            px["vol"] = pd.to_numeric(px["vol"], errors="coerce")
            px = px.dropna(subset=["close", "vol"])
            px["amt"] = px["close"] * px["vol"] * 100.0     # 手 → 股
            print(f"成交量源：{p}（{px['code'].nunique()} 只，{len(px)} 行）")
            return px
    raise SystemExit("找不到成交量文件（ohlc_raw.csv 或 data/ohlc_vol.csv）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-latest", action="store_true")
    a = ap.parse_args()

    pools = json.load(open(os.path.join(DATA, "pools.json"), encoding="utf-8"))
    px = load_vol()
    cal = np.sort(px["date"].unique())
    amt = px.pivot_table(index="date", columns="code", values="amt", aggfunc="last").sort_index()
    amt20 = amt.rolling(WINDOW, min_periods=max(5, WINDOW // 2)).mean()

    periods = sorted(pools)
    if a.only_latest:
        periods = periods[-1:]

    rows = []
    for per in periods:
        info = pools[per]
        asof = info.get("asof")
        if not asof:
            continue
        i = cal.searchsorted(np.datetime64(pd.Timestamp(asof)), side="left")
        if i >= len(cal):
            continue
        T = cal[i]                                     # 调仓日 = asof 后首个交易日
        adv = amt20.loc[T] if T in amt20.index else None
        if adv is None:
            continue
        for m in info["members"]:
            c, cap = m["code"], m.get("mktcap")
            if not cap or cap <= 0 or c not in adv.index or not np.isfinite(adv[c]):
                continue
            rows.append({"报告期": per, "调仓日": pd.Timestamp(T).strftime("%Y-%m-%d"),
                         "code": c, "adv20": float(adv[c]), "mktcap": float(cap),
                         "turn": float(adv[c] / cap)})
    new = pd.DataFrame(rows)
    if new.empty:
        raise SystemExit("没有可写入的面板数据")

    if a.only_latest and os.path.exists(OUT):
        old = pd.read_csv(OUT, encoding="utf-8-sig", dtype={"code": str})
        keep = old[~old["报告期"].isin(set(new["报告期"]))]
        new = pd.concat([keep, new], ignore_index=True)
    new = new.sort_values(["报告期", "turn"]).reset_index(drop=True)
    new.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"写入 {OUT}：{len(new)} 行 · {new['报告期'].nunique()} 期 · "
          f"{new['code'].nunique()} 只")
    g = new.groupby("报告期")["turn"].agg(["size", "median", "min", "max"])
    print(g.tail(6).to_string())


if __name__ == "__main__":
    main()
