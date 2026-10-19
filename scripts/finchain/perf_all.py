# -*- coding: utf-8 -*-
"""统一绩效口径：三组合 + 三基准，全期 2015-01 起，含分段（2015-2018 / 2019-2026）。

CSFM/TSFM 月度收益（nav 反推），质量Top28 季度收益（按季度折算年化）。
输出 final_summary_15.csv / nav_all_15.csv / curve_monthly.json 供报告与页面使用。
"""
import os
import sys
import json
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_OUT as OUT  # noqa: E402
START = pd.Timestamp("2015-01-01")
SEGS = [("2015-2018", "2015-01-01", "2018-12-31"), ("2019-2026", "2019-01-01", "2026-12-31")]

CS = "CSFM_N20_k1.5"
TS = "TSFM_N30_k1.0"


def perf(s, ppy):
    s = s.dropna()
    if len(s) < 4:
        return {}
    nav = (1 + s).cumprod()
    yrs = len(s) / float(ppy)
    ann = nav.iloc[-1] ** (1 / yrs) - 1
    vol = s.std(ddof=1) * np.sqrt(ppy)
    dd = (nav / nav.cummax() - 1).min()
    return {"累计": float(nav.iloc[-1] - 1), "年化": float(ann), "年化波动": float(vol),
            "夏普": float(ann / vol) if vol > 0 else np.nan, "最大回撤": float(dd),
            "卡玛": float(ann / abs(dd)) if dd < 0 else np.nan,
            "胜率": float((s > 0).mean()), "期末": s.index[-1], "期数": int(len(s))}


def main():
    navc = pd.read_csv(os.path.join(OUT, "nav_cs_ts_15.csv"), index_col=0, parse_dates=True)
    # 月度收益：nav[0]=1+r0
    def mret(col):
        n = navc[col].dropna()
        r = n.pct_change()
        r.iloc[0] = n.iloc[0] - 1.0
        return r

    r_cs, r_ts = mret(CS), mret(TS)
    q = pd.read_csv(os.path.join(OUT, "quality_ret_15.csv"), index_col=0, parse_dates=True)
    r_q1, r_q2 = q["v1"].dropna(), q["v2"].dropna()

    bench = pd.read_csv(os.path.join(OUT, "bench_daily.csv"), parse_dates=["date"])
    bm = {}
    for nm, g in bench.groupby("name"):
        s = g.set_index("date")["close"].sort_index()
        s = s[s.index >= START]
        me = s.groupby([s.index.year, s.index.month]).last()
        me.index = pd.to_datetime([f"{y}-{m:02d}-01" for y, m in me.index]) + pd.offsets.MonthEnd(0)
        bm[nm] = me.pct_change().dropna()

    series = {f"CSFM(N=20, κ=1.5)": (r_cs, 12), f"TSFM(N=30, κ=1.0)": (r_ts, 12),
              "质量Top28 v1": (r_q1, 4), "质量Top28 v2": (r_q2, 4)}
    for nm, s in bm.items():
        series[nm] = (s[s.index >= START], 12)

    rows = []
    for nm, (s, ppy) in series.items():
        s = s[s.index >= START]
        p = perf(s, ppy)
        rows.append({"组合": nm, "区间": "全期", **p})
        for lab, a, b in SEGS:
            seg = s[(s.index >= pd.Timestamp(a)) & (s.index <= pd.Timestamp(b))]
            pp = perf(seg, ppy)
            if pp:
                rows.append({"组合": nm, "区间": lab, **pp})
    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(OUT, "final_summary_15.csv"), index=False, encoding="utf-8-sig")

    fmt = lambda x: "—" if pd.isna(x) else f"{x*100:6.2f}%"
    print(f"{'组合':<20}{'区间':<11}{'年化':>8}{'波动':>9}{'夏普':>7}{'回撤':>9}{'卡玛':>7}{'期数':>5}")
    for _, r in T.iterrows():
        print(f"{r['组合']:<20}{r['区间']:<11}{fmt(r['年化']):>8}{fmt(r['年化波动']):>9}"
              f"{r['夏普']:7.2f}{fmt(r['最大回撤']):>9}{r['卡玛']:7.2f}{r['期数']:5d}")

    # 合并净值（月度，质量按季度末对齐）
    def to_nav(s, idx):
        nv = (1 + s).cumprod().reindex(idx, method="ffill")
        nv.iloc[0] = 1.0 if pd.isna(nv.iloc[0]) else nv.iloc[0]
        return nv

    idx = bm["沪深300"].index
    idx = idx[idx >= START]
    N = pd.DataFrame(index=idx)
    N["CSFM"] = to_nav(r_cs[r_cs.index >= START], idx)
    N["TSFM"] = to_nav(r_ts[r_ts.index >= START], idx)
    N["Q_v1"] = (1 + r_q1[r_q1.index >= START]).cumprod().reindex(idx, method="ffill")
    N["Q_v2"] = (1 + r_q2[r_q2.index >= START]).cumprod().reindex(idx, method="ffill")
    for nm, s in bm.items():
        N[nm] = (1 + s).cumprod().reindex(idx).ffill()
    N = N.ffill().bfill()
    N.index.name = "date"
    N.to_csv(os.path.join(OUT, "nav_all_15.csv"))
    print(f"\n[nav] {N.shape} {N.index[0].date()} ~ {N.index[-1].date()}")
    print(N.iloc[[0, -1]].round(3).to_string())

    js = {"dates": [d.strftime("%Y-%m-%d") for d in N.index],
          "series": {c: [round(float(v), 4) for v in N[c]] for c in N.columns}}
    with open(os.path.join(OUT, "curve_monthly.json"), "w", encoding="utf-8") as f:
        json.dump(js, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
