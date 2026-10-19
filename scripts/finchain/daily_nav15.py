# -*- coding: utf-8 -*-
"""日频净值引擎：把月度/季度调仓的选股结果展开成逐日净值。

为什么需要：页面「三、组合回测」的曲线与区间统计按**交易日**计算
（滑块步长 = 1 个交易日，近 1 年 = 252 个交易日），月度净值喂不进去。

口径与 backtest15.py / backtest_quality15.py 完全一致，只是把每段持仓
用「份额自然漂移」的方式逐日累计：
    段内净值(t) = Σ_i w_i · Π_{s<=t}(1 + r_i,s)
调仓日扣双边成本（turnover × 2 × 10bp），与月度回测同一公式。

输出：
    out15/daily_nav_15.csv     date × [CSFM, TSFM, Q28]
    out15/holdings_15.csv      rebal_date, combo, code, weight
    out15/daily_meta.json      参数与调仓日
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# 路径统一由 scripts/paths.py 解析（本机 Windows 与云端 Linux 同一份代码）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402

os.makedirs(OUT, exist_ok=True)

COST = 0.0010
FACTORS = ["size", "bm", "roa", "accr", "cp", "ep", "illiq", "turn", "bab", "ivol"]
# 主口径（2015-2026 全样本，见 final_summary_15.csv）
CS_N, CS_K = 20, 1.5
TS_N, TS_K = 30, 1.0
TOP_N = 28


def perf_daily(nav):
    r = nav.pct_change().dropna()
    n = len(r)
    ann = nav.iloc[-1] ** (252.0 / n) - 1
    vol = float(r.std(ddof=0) * np.sqrt(252))
    dd = (nav / nav.cummax() - 1).min()
    return {"累计": nav.iloc[-1] - 1, "年化": ann, "年化波动": vol,
            "夏普": ann / vol if vol else np.nan, "最大回撤": dd,
            "卡玛": ann / abs(dd) if dd < 0 else np.nan, "交易日": n}


def build_nav(rebal, R, last_date):
    """rebal: {决策日: Series(code->w)}。返回逐日净值 Series。"""
    segs = sorted(rebal)
    out = {}
    cur = 1.0
    prev = None
    for i, d in enumerate(segs):
        w = rebal[d]
        end = segs[i + 1] if i + 1 < len(segs) else last_date
        codes = list(w.index)
        turn = 1.0 if prev is None else 0.5 * len(set(codes) ^ set(prev)) / max(len(codes), 1)
        cur *= (1.0 - turn * 2 * COST)
        out[d] = cur
        days = R.index[(R.index > d) & (R.index <= end)]
        if len(days) == 0:
            prev = codes
            continue
        sub = R.loc[days, codes]
        # 停牌/未上市 → 当日收益记 0（价格冻结），与「当日无成交」一致
        sub = sub.fillna(0.0)
        cum = (1.0 + sub).cumprod()
        val = (cum.to_numpy() * w.to_numpy()).sum(axis=1)
        for t, v in zip(days, val):
            out[t] = cur * float(v)
        cur *= float(val[-1])
        prev = codes
    s = pd.Series(out).sort_index()
    return s


def csfm_tsfm_picks():
    """复现 backtest15.py 的选股，输出 {(combo): {决策日: Series}}"""
    fr = pd.read_csv(os.path.join(D15, "factor_ret_15.csv"), index_col=0, parse_dates=True)[FACTORS]
    expo = pd.read_csv(os.path.join(D15, "expo_month_15.csv"), parse_dates=["date"], dtype={"code": str})
    expo["code"] = expo["code"].str.zfill(6)
    pr = pd.read_csv(os.path.join(D15, "pool_ret_15.csv"), parse_dates=["date"], dtype={"code": str})
    pr["code"] = pr["code"].str.zfill(6)
    cr = pd.read_csv(os.path.join(OUT, "factor_crowding_15.csv"), index_col=0, parse_dates=True)
    Fm = cr[[f"F_{f}" for f in FACTORS]].copy()
    Fm.columns = FACTORS

    z = {f: expo.pivot(index="date", columns="code", values=f"z_{f}") for f in FACTORS}
    member = expo.groupby("date")["code"].apply(set).to_dict()

    mc = (1 + fr).cumprod()
    mom = mc.shift(1) / mc.shift(13) - 1
    med = mom.median(axis=1)
    w_ts = np.sign(mom)
    w_cs = np.sign(mom.sub(med, axis=0)).replace(0, 1.0)
    Fhat = Fm / 100.0

    dates = [d for d in mom.index if d in member]
    out = {"CSFM": {}, "TSFM": {}}
    for nm, wmat, N, kappa in (("CSFM", w_cs, CS_N, CS_K), ("TSFM", w_ts, TS_N, TS_K)):
        for d in dates:
            if d not in wmat.index:
                continue
            w = wmat.loc[d].dropna()
            if w.empty:
                continue
            if kappa and d in Fhat.index:
                w = w * (1 - kappa * Fhat.loc[d].reindex(w.index).fillna(0.0))
            acc = None
            for f in w.index:
                if d not in z[f].index:
                    continue
                v = z[f].loc[d] * w[f]
                acc = v if acc is None else acc.add(v, fill_value=0)
            if acc is None:
                continue
            sc = (acc / np.sqrt(len(w))).dropna()
            top = sc.nlargest(N)
            if len(top) < N // 2:
                continue
            out[nm][d] = pd.Series(1.0 / len(top), index=list(top.index))
    print(f"[CSFM] {len(out['CSFM'])} 个调仓日  [TSFM] {len(out['TSFM'])} 个", flush=True)
    return out


def quality_picks():
    """复现 backtest_quality15.py 的 v2 选股与反换手加权，季度频率"""
    faq = pd.read_csv(os.path.join(D15, "faq_panel_2015.csv.gz"), dtype={"code": str},
                      parse_dates=["EndDate", "pd"])
    faq["code"] = faq["code"].astype(str).str.zfill(6)
    pit = pd.read_csv(os.path.join(D15, "official_csi800_pit_2015.csv"), dtype=str)
    pit["c"] = pit["code"].map(lambda x: x[2:] if x[:2] in ("sh", "sz") else x)
    mem_by = pit.groupby("asof")["c"].apply(set).to_dict()
    asofs = sorted(mem_by)

    px = pd.read_pickle(os.path.join(D15, "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    clo = px.pivot(index="date", columns="code", values="close").ffill(limit=250)
    amt = px.pivot(index="date", columns="code", values="amount").ffill(limit=250)
    vol = px.pivot(index="date", columns="code", values="volume")

    # 季度末交易日：按日历季末取「不晚于该季末的最后一个交易日」。
    # 不能像原来那样按 (年,季) 分组取 max —— 数据截止在季度中间时，
    # 会把最后一个交易日（如 2026-10-16）当成一个季末，凭空多出一次调仓。
    trade = pd.DatetimeIndex(sorted(px["date"].unique()))
    qe = pd.date_range("2014-12-31", trade[-1], freq="QE")
    me = pd.DatetimeIndex([trade[trade <= q][-1] for q in qe if (trade <= q).any()])
    me = me[me >= pd.Timestamp("2014-12-31")]
    amt_ma = amt.rolling(20, min_periods=10).mean().reindex(me)
    vol_ma = vol.rolling(20, min_periods=10).mean().reindex(me)

    finp = pd.read_pickle(os.path.join(D15, "fin_pit.pkl"))
    sh = finp.sort_values("avail").drop_duplicates("code", keep="last").set_index("code")["shares"]
    turn20 = vol_ma * 100.0 / sh.reindex(vol_ma.columns)
    turn_med = turn20.median(axis=1)

    out = {}
    for d in me:
        cand = [a for a in asofs if pd.Timestamp(a) <= d]
        if not cand:
            continue
        mem = mem_by[cand[-1]]
        f = faq[(faq["pd"] <= d) & (faq["code"].isin(mem)) & faq["FAQ_score"].notna()].copy()
        if f.empty:
            continue
        f = f.sort_values("pd").drop_duplicates("code", keep="last")
        f["grp"] = f["sw3"].fillna("未分类")
        pool = f.sort_values("FAQ_score", ascending=False).groupby("grp", sort=False).head(5)
        if len(pool) < TOP_N:
            continue
        ranked = pool.sort_values("FAQ_score", ascending=False)
        cnt, top2 = {}, []
        for _, r in ranked.iterrows():
            g = r["grp"]
            if cnt.get(g, 0) >= 2:
                continue
            a = amt_ma.loc[d].get(r["code"], np.nan) if d in amt_ma.index else np.nan
            if not (a >= 5e7):
                continue
            top2.append(r)
            cnt[g] = cnt.get(g, 0) + 1
            if len(top2) >= TOP_N:
                break
        if len(top2) < TOP_N:
            got = {x["code"] for x in top2}
            for _, r in ranked.iterrows():
                if len(top2) >= TOP_N:
                    break
                if r["code"] in got or cnt.get(r["grp"], 0) >= 2:
                    continue
                top2.append(r)
                cnt[r["grp"]] = cnt.get(r["grp"], 0) + 1
        codes = [x["code"] for x in top2]
        tr = turn20.loc[d].reindex(codes).fillna(turn_med.loc[d]) if d in turn20.index else pd.Series(1.0, index=codes)
        tr = tr.clip(lower=tr.quantile(0.05) if tr.notna().any() else 1e-6)
        raw = 1.0 / (1.0 + tr / (tr.median() if tr.median() > 0 else 1.0))
        w = raw / raw.sum()
        out[d] = w
    print(f"[Q28] {len(out)} 个季度调仓日", flush=True)
    return out


def main():
    px = pd.read_pickle(os.path.join(D15, "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    R = px.pivot(index="date", columns="code", values="ret").sort_index()
    last = R.index[-1]
    print(f"[px] 日收益 {R.shape[0]} 日 × {R.shape[1]} 只 {R.index[0]:%Y-%m-%d}~{last:%Y-%m-%d}", flush=True)

    picks = csfm_tsfm_picks()
    picks["Q28"] = quality_picks()

    navs, holds = {}, []
    for nm, reb in picks.items():
        s = build_nav(reb, R, last)
        navs[nm] = s
        for d, w in reb.items():
            for c, v in w.items():
                holds.append({"rebal_date": d.strftime("%Y-%m-%d"), "combo": nm,
                              "code": c, "weight": float(v)})
        p = perf_daily(s)
        print(f"  {nm:5} {s.index[0]:%Y-%m-%d}~{s.index[-1]:%Y-%m-%d} "
              f"累计{p['累计']:7.1%} 年化{p['年化']:6.2%} 波动{p['年化波动']:6.2%} "
              f"夏普{p['夏普']:5.2f} 回撤{p['最大回撤']:7.2%}", flush=True)

    N = pd.DataFrame(navs).sort_index()
    N.to_csv(os.path.join(OUT, "daily_nav_15.csv"))
    pd.DataFrame(holds).to_csv(os.path.join(OUT, "holdings_15.csv"), index=False)
    json.dump({"cs": [CS_N, CS_K], "ts": [TS_N, TS_K],
               "n_cs": len(picks["CSFM"]), "n_ts": len(picks["TSFM"]), "n_q28": len(picks["Q28"])},
              open(os.path.join(OUT, "daily_meta.json"), "w"), ensure_ascii=False)
    print("done", flush=True)


if __name__ == "__main__":
    main()
