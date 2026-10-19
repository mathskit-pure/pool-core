# -*- coding: utf-8 -*-
"""把 2015-2026 新数据打包成页面内容包 out15/page_content.json。

页面沿用原版版式（不改 UI），只替换内容：
    二、季度股池明细      → periods
    三、组合回测          → bt（逐日净值 6 条线）+ perf（静态表）
    四、CSFM/TSFM 仓位    → pos（沿用 pos_sync 的规则，从新净值重算）
    五、持仓变动明细      → recent（各组合最近 8 个调仓日）
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# 路径统一由 scripts/paths.py 解析（本机 Windows 与云端 Linux 同一份代码）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE as POOLCORE, FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402

COMBOS = {"CSFM": "因子动量CSFM", "TSFM": "因子动量TSFM", "Q28": "质量Top28组合"}
BENCH = ["沪深300", "中证500", "创业板50"]
COLOR = {"因子动量CSFM": "#d81b60", "因子动量TSFM": "#00897b", "质量Top28组合": "#0f9d58",
         "沪深300": "#7a7a7a", "中证500": "#3d6fb5", "创业板50": "#e08a1e"}
LABEL = {"因子动量CSFM": "因子动量·横截面 CSFM", "因子动量TSFM": "因子动量·时间序列 TSFM",
         "质量Top28组合": "质量Top28组合"}
POS_START = "2019-05-06"


def perf(nav):
    """与页面 JS calc() 完全同口径：总收益、年化(252)、波动(总体std×√252)、回撤、夏普、卡玛"""
    r = nav.pct_change().dropna()
    n = len(r)
    eq = float(nav.iloc[-1] / nav.iloc[0])
    ann = eq ** (252.0 / n) - 1
    vol = float(r.std(ddof=0) * np.sqrt(252))
    dd = float((nav / nav.cummax() - 1).min())
    return {"cum": eq - 1, "ann": ann, "vol": vol, "dd": dd,
            "sh": ann / vol if vol else None, "cal": ann / abs(dd) if dd < 0 else None,
            "n": n}


def label_of(asof):
    y, m = asof.year, asof.month
    return {5: f"{y}年一季报", 9: f"{y}年中报", 11: f"{y}年三季报"}.get(m, f"{y}年{m:02d}月")


def build_periods(name, mcap_panel):
    # 股池唯一来源：build_pools_v5.py 的产物（35 期、申万三级各取 FAQ 前 3）
    p = pd.read_csv(os.path.join(D15, "pools_v5.csv"), dtype={"code": str})
    p["code"] = p["code"].str.zfill(6)
    p["asof"] = pd.to_datetime(p["asof"])
    out = []
    for asof, g in p.groupby("asof", sort=True):
        # 市值取 asof 之前最近的月末
        idx = mcap_panel.index[mcap_panel.index <= asof]
        mm = mcap_panel.loc[idx[-1]] if len(idx) else None
        inds = []
        for ind, gg in g.groupby("sw3", sort=False):
            gg = gg.sort_values("FAQ_score", ascending=False)
            rows = []
            for _, r in gg.iterrows():
                mv = None
                if mm is not None and r["code"] in mm.index:
                    v = mm[r["code"]]
                    if pd.notna(v):
                        mv = round(float(v) / 1e8, 0)
                rows.append({"c": ("sh" if r["code"][0] == "6" else "sz") + r["code"],
                             "n": name.get(r["code"], r["code"]),
                             "s": round(float(r["FAQ_score"]), 2), "m": mv})
            inds.append({"ind": ind if isinstance(ind, str) else "未分类", "rows": rows})
        inds.sort(key=lambda x: (-len(x["rows"]), x["ind"]))
        out.append({"asof": asof.strftime("%Y-%m-%d"), "label": label_of(asof),
                    "avail": asof.strftime("%Y-%m-%d"),
                    "n": int(len(g)), "nind": len(inds), "inds": inds})
    return out


def build_bt(daily, bench):
    """逐日净值。六条线统一在**共同起点**（三个组合都已有净值的第一天）归一到 1.00，
    否则基准会从更早的日期起步，区间统计各算各的窗口，横向不可比。"""
    b = bench.pivot_table(index="date", columns="name", values="close").sort_index()
    frames = {}
    for k, col in COMBOS.items():
        s = daily[k].dropna()
        frames[col] = s
    for nm in BENCH:
        frames[nm] = b[nm].dropna()
    start = max(s.index[0] for s in frames.values())
    idx = sorted({d for s in frames.values() for d in s.index if start <= d <= max(x.index[-1] for x in frames.values())})
    series = {}
    for k, s in frames.items():
        s = s[s.index >= start]
        s = s / s.iloc[0]
        s = s.reindex(idx)
        series[k] = [None if pd.isna(v) else round(float(v), 4) for v in s]
    order = list(COMBOS.values()) + BENCH
    return {"dates": [d.strftime("%Y-%m-%d") for d in idx], "order": order,
            "color": {k: COLOR[k] for k in order},
            "label": {k: LABEL.get(k, k) for k in order}, "series": series}


def build_pos(daily):
    """沿用 pos_sync.positions_from_nav 的规则（R1 过热 / R2 均线 / R3 F 门控），
    只取 2019-05-06 起（中证2000 指数与持仓加权 F 都只有该区间数据）。"""
    sys.path.insert(0, os.path.join(POOLCORE, "scripts"))
    from pos_sync import positions_from_nav

    nav = daily[["CSFM", "TSFM"]].dropna()
    nav = nav[nav.index >= pd.Timestamp(POS_START)]
    fb = os.path.join(POOLCORE, "cloud", "state", "fbook_monthly.csv")
    fbook = pd.read_csv(fb, index_col=0, parse_dates=True).iloc[:, 0] if os.path.exists(fb) else None
    pos = positions_from_nav(nav.index, nav["CSFM"].tolist(), nav["TSFM"].tolist(), fbook)

    def idx_series(fn):
        p = os.path.join(POOLCORE, "cloud", "state", fn)
        s = pd.read_csv(p, index_col=0, parse_dates=True)["close"].reindex(nav.index).ffill()
        return [round(float(x), 2) for x in s]

    return {"dates": [d.strftime("%Y-%m-%d") for d in nav.index],
            "csfm": [int(round(x * 100)) for x in pos["因子动量CSFM"]],
            "tsfm": [int(round(x * 100)) for x in pos["因子动量TSFM"]],
            "zz": idx_series("idx_932000.csv"), "cyb": idx_series("idx_399006.csv")}


def build_recent(name, daily, pos, n_periods=8):
    """最近 8 个调仓日：持仓（含权重/新进）、剔除（建仓日 + 区间涨跌幅）、区间净值涨跌、建议仓位"""
    h = pd.read_csv(os.path.join(OUT, "holdings_15.csv"), dtype={"code": str})
    h["code"] = h["code"].str.zfill(6)
    px = pd.read_pickle(os.path.join(D15, "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    close = px.pivot(index="date", columns="code", values="close")
    close = close.ffill(limit=250)
    trade = close.index
    posidx = {d: i for i, d in enumerate(pd.to_datetime(pos["dates"]))}

    def exec_date(d):
        """决策日之后的第一个交易日"""
        nxt = trade[trade > d]
        return nxt[0] if len(nxt) else None

    out = {}
    for combo, key in COMBOS.items():
        sub = h[h["combo"] == combo]
        decs = sorted(pd.to_datetime(sub["rebal_date"].unique()))
        rows = []
        entry = {}
        for i, d in enumerate(decs):
            codes = sub[sub["rebal_date"] == d.strftime("%Y-%m-%d")]
            w = dict(zip(codes["code"], codes["weight"]))
            ed = exec_date(d)
            prev = set(rows[-1]["codes"]) if rows else set()
            cur = set(w)
            # 建仓日登记
            for c in cur - prev:
                entry[c] = ed
            new = cur - prev if rows else set()
            outs = []
            for c in sorted(prev - cur):
                e0 = entry.get(c)
                r = None
                if e0 is not None and c in close.columns:
                    a, b = close.at[e0, c] if e0 in close.index else np.nan, None
                    b = close.at[ed, c] if ed in close.index else np.nan
                    if pd.notna(a) and pd.notna(b) and a > 0:
                        r = float(b / a - 1)
                outs.append({"n": name.get(c, c), "c": ("sh" if c[0] == "6" else "sz") + c,
                             "e": e0.strftime("%Y-%m-%d") if e0 is not None else None,
                             "r": None if r is None else round(r, 4)})
            # 区间净值涨跌：上一个调仓日 → 当前调仓日
            ret = None
            if rows:
                d0 = pd.Timestamp(rows[-1]["date"])
                s = daily[combo].dropna()
                a = s.asof(d0)
                b = s.asof(ed)
                if pd.notna(a) and pd.notna(b) and a > 0:
                    ret = float(b / a - 1)
            hold = [{"n": name.get(c, c), "c": ("sh" if c[0] == "6" else "sz") + c,
                     "w": round(float(v), 4), "new": c in new} for c, v in w.items()]
            p = None
            if combo in ("CSFM", "TSFM"):
                j = posidx.get(ed)
                if j is not None:
                    p = pos["csfm" if combo == "CSFM" else "tsfm"][j]
            rows.append({"date": ed.strftime("%Y-%m-%d") if ed is not None else d.strftime("%Y-%m-%d"),
                         "dec": d.strftime("%Y-%m-%d"),
                         "ret": None if ret is None else round(ret, 4),
                         "pos": p, "hold": hold, "out": outs, "codes": list(cur)})
        rows = rows[-n_periods:]
        for r in rows:
            r.pop("codes")
        out[combo] = rows[::-1]  # 最新在上
    return out


def main():
    name = json.load(open(os.path.join(OUT, "name_map.json"), encoding="utf-8"))
    daily = pd.read_csv(os.path.join(OUT, "daily_nav_15.csv"), index_col=0, parse_dates=True)
    bench = pd.read_csv(os.path.join(OUT, "bench_daily.csv"), parse_dates=["date"])
    expo = pd.read_csv(os.path.join(D15, "expo_month_15.csv"), dtype={"code": str},
                       usecols=["date", "code", "mcap"], parse_dates=["date"])
    expo["code"] = expo["code"].str.zfill(6)
    # 市值面板：月末市值宽表。个股偶有月份缺失（停牌/未入面板），
    # 按代码向前补最多 13 个月，避免表格里出现大量「—」。
    mcap = expo.dropna(subset=["mcap"]).pivot_table(index="date", columns="code",
                                                    values="mcap", aggfunc="last").sort_index()
    mcap = mcap.ffill(limit=13)

    print("[1/5] 股池明细", flush=True)
    periods = build_periods(name, mcap)
    print(f"      {len(periods)} 期，并集 {len({r['c'][2:] for p in periods for i in p['inds'] for r in i['rows']})} 只", flush=True)

    print("[2/5] 净值曲线", flush=True)
    bt = build_bt(daily, bench)
    print(f"      {len(bt['dates'])} 个交易日", flush=True)

    print("[3/5] 静态绩效", flush=True)
    # 用与页面同一份（已四舍五入的）净值序列算，静态表才能和脚本重算的结果逐位一致
    perf_out = {}
    for key in bt["order"]:
        v = pd.Series([x for x in bt["series"][key]], index=pd.to_datetime(bt["dates"])).dropna()
        perf_out[key] = perf(v)

    print("[4/5] 仓位建议", flush=True)
    pos = build_pos(daily)

    print("[5/5] 持仓变动", flush=True)
    recent = build_recent(name, daily, pos)

    kpi = {"n_period": len(periods),
           "n_stock": len({r["c"][2:] for p in periods for i in p["inds"] for r in i["rows"]}),
           "n_ind": len({i["ind"] for p in periods for i in p["inds"]}),
           "n_hold": len(recent["Q28"][0]["hold"]) if recent["Q28"] else 0}

    data = {"periods": periods, "bt": bt, "perf": perf_out, "pos": pos,
            "recent": recent, "kpi": kpi,
            "meta": {"start": bt["dates"][0], "end": bt["dates"][-1],
                     "pos_start": pos["dates"][0], "pos_end": pos["dates"][-1]}}
    p = os.path.join(OUT, "page_content.json")
    json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"✓ {p}  {os.path.getsize(p)/1e6:.2f} MB")
    print("  KPI:", kpi)
    for k, v in perf_out.items():
        print(f"  {k:16} 年化{v['ann']:7.2%} 波动{v['vol']:6.2%} 夏普{v['sh']:5.2f} 回撤{v['dd']:7.2%}")


if __name__ == "__main__":
    main()
