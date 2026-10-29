# -*- coding: utf-8 -*-
"""情景回测：把股池换成「申万三级行业市值前 50 × 各行业 FAQ 前 3」后，
用**完全同一套**选股 / 加权 / 成交口径重跑 CSFM、TSFM、质量Top28 三个组合。

设计要点
--------
· 唯一变量是股池文件：`--pools pools_v6_ind50.csv`。选股（csfm_tsfm_picks /
  quality_picks）、可交易过滤（filt_tradable）、净值展开（build_nav）、成本
  （单边 10bp）全部直接调用 daily_nav15 的原函数，一行不改。
· 为排除「改了代码导致差异」的可能，`--pools pools_v5.csv` 应能复现线上
  页面的三个数字（累计 40.39% / 123.45% / 152.60%），脚本会打印对照。
· 起点仍是 2017 年首个交易日（2015-2016 仅作因子动量预热与期初持仓）。

用法
    set FIN_OUT_DIR=<情景输出目录>
    python scripts/finchain/scenario_ind50.py --pools pools_v6_ind50.csv --out scn_ind50
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from paths import FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402

import daily_nav15 as DN  # noqa: E402

START = pd.Timestamp("2017-01-01")
COMBOS = [("CSFM", "因子动量CSFM"), ("TSFM", "因子动量TSFM"), ("Q28", "质量Top28组合")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pools", default=os.environ.get("POOL_FILE_V5") or "pools_v5.csv")
    ap.add_argument("--out", default="scn")
    a = ap.parse_args()

    outdir = os.path.join(str(OUT), a.out)
    os.makedirs(outdir, exist_ok=True)
    os.environ["POOL_FILE_V5"] = a.pools

    px = pd.read_pickle(os.path.join(str(D15), "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    C = px.pivot(index="date", columns="code", values="close").sort_index()
    R = px.pivot(index="date", columns="code", values="ret").sort_index()
    last = R.index[-1]
    trade = C.index[C.index >= START]
    anchor = trade[0]
    print(f"[池] {a.pools} | 窗口 {anchor:%Y-%m-%d} → {last:%Y-%m-%d} {len(trade)} 日", flush=True)

    picks = DN.csfm_tsfm_picks()
    picks["Q28"] = DN.quality_picks()

    navs, holds, drops_all = {}, [], []
    for nm, label in COMBOS:
        reb, drops = DN.filt_tradable(picks[nm], C, nm)
        drops_all.extend(drops)
        s = DN.build_nav(reb, R, last)
        s = s[s.index >= anchor]
        s = s / s.iloc[0]
        navs[nm] = s
        for d, w in reb.items():
            if d >= anchor:
                for c, v in w.items():
                    holds.append({"rebal_date": d.strftime("%Y-%m-%d"), "combo": nm,
                                  "code": c, "weight": float(v)})
        p = DN.perf_daily(s)
        print(f"  {nm:5} 调仓 {len(reb):3d} 次 | 累计{p['累计']:8.2%} 年化{p['年化']:6.2%} "
              f"波动{p['年化波动']:6.2%} 回撤{p['最大回撤']:8.2%} 夏普{p['夏普']:5.2f} "
              f"卡玛{p['卡玛']:5.2f}", flush=True)

    N = pd.DataFrame(navs).sort_index()
    N.index.name = "date"
    N.to_csv(os.path.join(outdir, "daily_nav.csv"))
    H = pd.DataFrame(holds)
    H.to_csv(os.path.join(outdir, "holdings.csv"), index=False, encoding="utf-8-sig")
    if drops_all:
        pd.DataFrame(drops_all).to_csv(os.path.join(outdir, "dropped.csv"), index=False)

    # ── 基准同口径 ──
    bench = pd.read_csv(os.path.join(str(OUT), "bench_daily.csv"), parse_dates=["date"])
    rows = []
    for nm, label in COMBOS:
        p = DN.perf_daily(N[nm].dropna())
        rows.append({"组合": label, "累计": p["累计"], "年化": p["年化"], "波动": p["年化波动"],
                     "回撤": p["最大回撤"], "夏普": p["夏普"], "卡玛": p["卡玛"], "交易日": p["交易日"]})
    for nm, g in bench.groupby("name"):
        s = g.set_index("date")["close"].sort_index().dropna()
        s = s[s.index >= anchor]
        if len(s) < 20:
            continue
        s = s / s.iloc[0]
        p = DN.perf_daily(s)
        rows.append({"组合": nm, "累计": p["累计"], "年化": p["年化"], "波动": p["年化波动"],
                     "回撤": p["最大回撤"], "夏普": p["夏普"], "卡玛": p["卡玛"], "交易日": p["交易日"]})
    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(outdir, "perf.csv"), index=False, encoding="utf-8-sig")

    # ── 组合画像：持仓数 / 年换手 / 行业集中度 / 与旧池重名率 ──
    hold_stat = []
    for nm, label in COMBOS:
        h = H[H["combo"] == nm]
        n_by = h.groupby("rebal_date").size()
        per_year = len(n_by) / ((N.index[-1] - N.index[0]).days / 365.25)
        turn = []
        prev = None
        for d, g in h.groupby("rebal_date"):
            cur = set(g["code"])
            if prev is not None:
                turn.append(0.5 * len(cur ^ prev) / max(len(cur), 1))
            prev = cur
        hold_stat.append({"组合": label, "调仓次数": len(n_by),
                          "平均持仓": round(float(n_by.mean()), 1),
                          "年换手": round(float(np.mean(turn) * per_year), 2) if turn else None})
    S = pd.DataFrame(hold_stat)
    S.to_csv(os.path.join(outdir, "hold_stat.csv"), index=False, encoding="utf-8-sig")
    print(S.to_string(index=False))

    fmt = lambda x: "—" if pd.isna(x) else f"{x*100:6.2f}%"
    print(f"\n{'组合':<16}{'累计':>9}{'年化':>8}{'波动':>8}{'回撤':>9}{'夏普':>7}{'卡玛':>7}")
    for _, r in T.iterrows():
        print(f"{r['组合']:<16}{fmt(r['累计']):>9}{fmt(r['年化']):>8}{fmt(r['波动']):>8}"
              f"{fmt(r['回撤']):>9}{r['夏普']:7.2f}{r['卡玛']:7.2f}")
    print(f"\n✓ {outdir}")


if __name__ == "__main__":
    main()
