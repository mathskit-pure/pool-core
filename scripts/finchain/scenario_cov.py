# -*- coding: utf-8 -*-
"""研报覆盖度过滤的两个反事实情景回测（只算数，不碰页面）。

对照三条净值，口径完全一致（同一份行情、同一套 cost / 停牌过滤 / 2017 起统计）：

    ① base      原 Q28：股池 → FAQ 降序取 28 只候选 → 三道筛 → 反比加权 2%~8%
    ② 情景A     历次持仓剔除零覆盖个股后，剩余权重按原比例归一
                （= 事后过滤，持仓数变少，不改选股）
    ③ 情景B     候选构建时剔除零覆盖个股，不递补
                （= 事前过滤，候选从 28 只降到 28-k 只，三道筛与加权全部重跑）

为什么情景 B 不递补：递补要从股池顺位继续往下取，而那些票散落在全股池 1071 只里，
无法逐只取得研报覆盖状态。宁可口径保守（宁缺毋滥），也不拿未知标签硬凑。

覆盖标签来源：data/coverage_label_all.csv（neodata 机构评级，334 只候选全覆盖）。
标签是「当前卖方覆盖」这一慢变量，不是入选当时的时点状态——见报告的口径说明。

用法：
    python scripts/finchain/scenario_cov.py            # 算并打印对比
    python scripts/finchain/scenario_cov.py --out xx.csv
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))          # scripts/
sys.path.insert(0, _HERE)                            # scripts/finchain/

from paths import DATA, FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402

import quality_v2 as Q2                                   # noqa: E402
from daily_nav15 import (COST, NAV_START, TOP_N, build_nav,  # noqa: E402
                         filt_tradable, perf_daily)

LABEL = os.path.join(DATA, "coverage_label_all.csv")


# ────────────────────────── 数据准备 ──────────────────────────
def load_inputs():
    pools = pd.read_csv(os.path.join(D15, "pools_v5.csv"), dtype={"code": str})
    pools["code"] = pools["code"].str.zfill(6)
    pools["grp"] = pools["sw3"].fillna("未分类")
    by_asof = {a: g.copy() for a, g in pools.groupby("asof")}

    px = pd.read_pickle(os.path.join(D15, "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    R = px.pivot(index="date", columns="code", values="ret").sort_index()
    C = px.pivot(index="date", columns="code", values="close").sort_index()
    amt = px.pivot(index="date", columns="code", values="amount").ffill(limit=250)
    trade = pd.DatetimeIndex(sorted(px["date"].unique()))
    amt20 = amt.rolling(20, min_periods=10).mean()

    ex = pd.read_csv(os.path.join(D15, "expo_month_15.csv"), dtype={"code": str},
                     usecols=["date", "code", "mcap"], parse_dates=["date"])
    ex["code"] = ex["code"].str.zfill(6)
    mcap = ex.dropna(subset=["mcap"]).pivot_table(index="date", columns="code",
                                                  values="mcap", aggfunc="last").sort_index()
    mcap = mcap.ffill(limit=13)

    lab = pd.read_csv(LABEL, dtype={"code": str})
    lab["code"] = lab["code"].str.zfill(6)
    has_cov = dict(zip(lab["code"], lab["has_cov"].astype(int)))

    return dict(pools=by_asof, R=R, C=C, amt20=amt20, mcap=mcap,
                trade=trade, has_cov=has_cov)


def picks_q28(D, drop_none=False, verbose=""):
    """复现 Q28 选股。drop_none=True 时候选阶段剔除零覆盖个股（情景 B）。

    与 daily_nav15.quality_picks 逐行同构，唯一区别是候选过滤开关。
    """
    has_cov = D["has_cov"]
    amt20, mcap, trade = D["amt20"], D["mcap"], D["trade"]
    out, stats = {}, []
    n_drop_total = 0
    for a in sorted(D["pools"]):
        nxt = trade[trade > pd.Timestamp(a)]
        if len(nxt) == 0:
            continue
        d = nxt[0]
        g = D["pools"][a]
        ranked = g.sort_values("FAQ_score", ascending=False)
        cands = [(str(r["code"]), float(r["FAQ_score"])) for _, r in ranked.iterrows()
                 if pd.notna(r["FAQ_score"])]
        if drop_none:
            before = len(cands)
            cands = [(c, s) for c, s in cands if has_cov.get(c, 1) == 1]
            n_drop_total += before - len(cands)
        if len(cands) < Q2.MIN_FINAL:
            continue
        sw3 = dict(zip(g["code"].astype(str), g["grp"]))

        a_row = amt20.loc[d] if d in amt20.index else None
        mrow = None
        if len(mcap.index):
            idx = mcap.index[mcap.index <= d]
            if len(idx):
                mrow = mcap.loc[idx[-1]]
        turn_map = {}
        if a_row is not None:
            for c in g["code"].astype(str):
                v = a_row.get(c, np.nan)
                if not np.isfinite(v):
                    continue
                mc = mrow.get(c, np.nan) if mrow is not None else np.nan
                if not (np.isfinite(mc) and mc > 0):
                    continue
                turn_map[c] = (float(v), float(v) / float(mc))

        picked, meta = Q2.select_v2(cands, sw3, turn_map, lq=TOP_N, max_per_ind=2)
        if not picked:
            continue
        if meta["degrade"] == "ok":
            w = pd.Series({c: ww for c, ww, _ in picked}, dtype=float)
        else:
            codes = [c for c, _ in picked] if len(picked[0]) == 2 else [c for c, _, _ in picked]
            n = max(len(codes), 1)
            w = pd.Series(1.0 / n, index=codes)
        w = w / w.sum()
        out[d] = w
        stats.append({"asof": a, "date": d.strftime("%Y-%m-%d"), "n": len(w),
                      "degrade": meta["degrade"]})
    if verbose:
        ns = [s["n"] for s in stats]
        print(f"  [{verbose}] {len(out)} 期 · 持仓 {min(ns)}~{max(ns)} 只（均值 {np.mean(ns):.1f}）"
              + (f" · 候选阶段剔除零覆盖 {n_drop_total} 只次" if drop_none else ""), flush=True)
    return out


def drop_none_from_holdings(reb, has_cov):
    """情景 A：持仓里剔掉零覆盖个股，剩余权重按原比例归一。"""
    out, detail = {}, []
    for d, w in reb.items():
        keep = [c for c in w.index if has_cov.get(c, 1) == 1]
        gone = [c for c in w.index if has_cov.get(c, 1) == 0]
        if not keep:
            continue
        ww = w.reindex(keep)
        ww = ww / ww.sum()
        out[d] = ww
        if gone:
            detail.append({"date": d.strftime("%Y-%m-%d"), "n_gone": len(gone),
                           "w_gone": float(w.reindex(gone).sum()),
                           "codes": ",".join(gone)})
    return out, detail


# ────────────────────────── 主流程 ──────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(DATA, "scenario_cov_nav.csv"))
    a = ap.parse_args()

    print("[1/4] 载入行情 / 股池 / 覆盖标签", flush=True)
    D = load_inputs()
    last = D["R"].index.max()
    lab = pd.read_csv(LABEL, dtype={"code": str})
    print(f"      标签 {len(lab)} 只：" +
          " / ".join(f"{k} {v}" for k, v in lab.cov_level.value_counts().items()), flush=True)

    print("[2/4] 复现三条选股", flush=True)
    base_raw = picks_q28(D, drop_none=False, verbose="base")
    scB_raw = picks_q28(D, drop_none=True, verbose="情景B（事前过滤）")
    scA_raw, dropA = drop_none_from_holdings(base_raw, D["has_cov"])
    ns = [len(w) for w in scA_raw.values()]
    print(f"  [情景A（事后过滤）] {len(scA_raw)} 期 · 持仓 {min(ns)}~{max(ns)} 只"
          f"（均值 {np.mean(ns):.1f}）· 共剔除 "
          f"{sum(x['n_gone'] for x in dropA)} 只次、"
          f"平均弃权 {np.mean([x['w_gone'] for x in dropA]):.2%}", flush=True)

    print("[3/4] 可交易过滤 + 逐日净值", flush=True)
    C = D["C"]
    navs, meta = {}, {}
    for nm, reb in (("base", base_raw), ("A", scA_raw), ("B", scB_raw)):
        reb2, _ = filt_tradable(reb, C, combo=nm)
        navs[nm] = build_nav(reb2, D["R"], last)
        meta[nm] = reb2

    N = pd.DataFrame(navs).sort_index()
    N = N[N.index >= pd.Timestamp(NAV_START)]
    N = N / N.iloc[0]
    print(f"      统计窗口 {N.index[0]:%Y-%m-%d} ~ {N.index[-1]:%Y-%m-%d} · {len(N)} 个交易日",
          flush=True)

    print("[4/4] 绩效", flush=True)
    rows = []
    for nm in ("base", "A", "B"):
        p = perf_daily(N[nm])
        p["组合"] = nm
        rows.append(p)
    P = pd.DataFrame(rows).set_index("组合")
    P.to_csv(a.out)

    # 用线上 Q28 列校验 base 复现是否正确
    daily = os.path.join(OUT, "daily_nav_15.csv")
    if os.path.exists(daily):
        ref = pd.read_csv(daily, index_col=0, parse_dates=True)["Q28"]
        ref = ref[ref.index >= pd.Timestamp(NAV_START)]
        ref = ref / ref.iloc[0]
        common = N.index.intersection(ref.index)
        if len(common) > 100:
            gap = float((N.loc[common, "base"] / ref.loc[common] - 1).abs().max())
            print(f"      base vs 线上 Q28 最大偏离 {gap:.2e} "
                  f"（{'一致' if gap < 1e-6 else '⚠ 口径有差，需核对'}）", flush=True)

    fmt = lambda v: f"{v:7.2%}" if abs(v) < 10 else f"{v:7.1%}"
    print("\n" + "=" * 78)
    print(f"{'组合':<26}{'累计':>10}{'年化':>9}{'波动':>9}{'夏普':>7}{'最大回撤':>10}")
    print("-" * 78)
    name = {"base": "① 原 Q28（基线）", "A": "② 情景A 持仓剔零覆盖", "B": "③ 情景B 候选剔零覆盖"}
    for k in ("base", "A", "B"):
        r = P.loc[k]
        print(f"{name[k]:<24}{fmt(r['累计']):>11}{fmt(r['年化']):>9}"
              f"{fmt(r['年化波动']):>9}{r['夏普']:>7.2f}{fmt(r['最大回撤']):>10}")
    print("=" * 78)
    for k in ("A", "B"):
        d = P.loc[k] - P.loc["base"]
        print(f"  {name[k]} − 基线：累计 {d['累计']:+.2%} · 年化 {d['年化']:+.2%} · "
              f"夏普 {d['夏普']:+.2f} · 回撤 {d['最大回撤']:+.2%}")

    N.to_csv(a.out.replace(".csv", "_daily.csv"))
    print(f"\n净值 → {a.out.replace('.csv', '_daily.csv')}\n绩效 → {a.out}")


if __name__ == "__main__":
    main()
