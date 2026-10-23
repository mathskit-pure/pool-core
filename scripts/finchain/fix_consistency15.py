# -*- coding: utf-8 -*-
"""修复 2015-2026 三组合回测的口径不一致 + 停牌处理错误。

背景（2026-10-23 排查结论）
--------------------------------
1. 线上页面的「绩效汇总」来自 perf_all.py → final_summary_15.csv（月度/季度序列），
   「净值曲线」来自 daily_nav15.py → daily_nav_15.csv（日频引擎）。
   两者是不同的引擎，同一策略算出完全不同的结果：
       CSFM  页面 282.86% vs 日净值 3.9%
       Q28   页面 14.29%/年 vs 日净值 6.37%/年
   实测：日频引擎的持仓与月度引擎逐期一致（2023-06-30 抽样 20/20 重合），
   且日净值分段收益与「后复权收盘价直接买入持有」相差仅 -0.1~-0.2%（= 成本），
   说明日频引擎是可信的，问题在于月度/季度序列侧的错误。

2. 停牌处理错误（2015 股灾期影响最大）：
   - 季度引擎：`seg.reindex(codes).fillna(0.0)` —— 期末停牌的股票直接按 0 收益计，
     复牌后的补涨/补跌被完全抹掉。典型案例 000792 盐湖股份：2021-08-10 复牌单日
     +200.8%，在季度口径里记为 0。
   - 日频引擎：调仓日不检查个股是否可交易，会把当天停牌的股票按最后价"买入"。

本脚本做的事
--------------------------------
① 在日频引擎基础上加「调仓日可交易过滤」：调仓日无成交（停牌/未上市）的标的不买入，
   权重在可交易标的内重新归一；
② 用修好的引擎重算 CSFM / TSFM / Q28 的日净值；
③ 从日频净值聚合出月度净值与绩效表（表 = 图，同源）；
④ 输出一致性校验表，量化三套旧口径的偏差。

输出
--------------------------------
out15/daily_nav_15_fixed.csv     修好的日频净值（date × CSFM/TSFM/Q28）
out15/holdings_15_fixed.csv      修好的持仓（含不可交易剔除记录）
out15/perf_unified_15.csv        统一口径绩效表（表=图同源）
out15/consistency_check_15.csv   三套旧口径 vs 修复口径的对照
"""
import os
import sys
import json
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from paths import FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402

COST = 0.0010                      # 单边成本 10bp
START = pd.Timestamp("2015-01-01")
SEGS = [("2015-2018", "2015-01-01", "2018-12-31"),
        ("2019-2026", "2019-01-01", "2026-12-31")]


def load_px():
    px = pd.read_pickle(os.path.join(D15, "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    C = px.pivot(index="date", columns="code", values="close").sort_index()
    R = px.pivot(index="date", columns="code", values="ret").sort_index()
    return C, R


def filt_tradable(reb, C):
    """调仓日不可交易（当天没有成交价 = 停牌/未上市）的标的剔除，权重重新归一。
    返回 (新 picks, 剔除记录)。这是本次修复的核心：旧引擎会按最后一个价格"买入"停牌股。"""
    out, dropped = {}, []
    for d, w in reb.items():
        if d not in C.index:
            out[d] = w
            continue
        row = C.loc[d]
        ok = [c for c in w.index if c in row.index and pd.notna(row[c])]
        bad = [c for c in w.index if c not in ok]
        for c in bad:
            dropped.append({"rebal_date": d.strftime("%Y-%m-%d"), "code": c,
                            "weight": float(w[c]), "reason": "调仓日停牌/无价"})
        if not ok:
            continue
        ww = w.reindex(ok)
        out[d] = ww / ww.sum()
    return out, dropped


def build_nav(rebal, R, last_date):
    """段内 buy&hold：段净值(t) = Σ_i w_i · Π_{s<=t}(1+r_i,s)；
    持仓期间停牌 → 当日收益记 0（价格冻结），复牌日一次性补涨/补跌。
    与 daily_nav15.build_nav 同构，只多了可交易过滤后的权重。"""
    segs = sorted(rebal)
    out, cur, prev = {}, 1.0, None
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
        sub = R.loc[days, codes].fillna(0.0)
        cum = (1.0 + sub).cumprod()
        val = (cum.to_numpy() * w.to_numpy()).sum(axis=1)
        for t, v in zip(days, val):
            out[t] = cur * float(v)
        cur *= float(val[-1])
        prev = codes
    return pd.Series(out).sort_index()


def perf(s, ppy=252):
    s = pd.Series(s).dropna()
    if len(s) < 20:
        return {}
    r = s.pct_change().dropna() if ppy == 252 else s
    nav = s if ppy == 252 else (1 + s).cumprod()
    yrs = len(r) / float(ppy) if ppy == 252 else len(s) / float(ppy)
    ann = nav.iloc[-1] ** (1 / yrs) - 1
    vol = r.std(ddof=1) * np.sqrt(ppy)
    dd = (nav / nav.cummax() - 1).min()
    return {"累计": float(nav.iloc[-1] - 1), "年化": float(ann), "年化波动": float(vol),
            "夏普": float(ann / vol) if vol > 0 else np.nan, "最大回撤": float(dd),
            "卡玛": float(ann / abs(dd)) if dd < 0 else np.nan,
            "胜率": float((r > 0).mean()), "期数": int(len(r)),
            "期末": str(s.index[-1].date())}


def main():
    C, R = load_px()
    last = R.index[-1]
    print(f"[px] {R.shape[0]} 日 × {R.shape[1]} 只 {R.index[0]:%Y-%m-%d}~{last:%Y-%m-%d}", flush=True)

    import daily_nav15 as DN
    picks = DN.csfm_tsfm_picks()
    picks["Q28"] = DN.quality_picks()

    fixed, dropped_all, navs = {}, [], {}
    for nm, reb in picks.items():
        reb2, dropped = filt_tradable(reb, C)
        dropped_all += [{"combo": nm, **x} for x in dropped]
        fixed[nm] = reb2
        navs[nm] = build_nav(reb2, R, last)
        p = perf(navs[nm])
        print(f"  {nm:5} 调仓 {len(reb2)} 次（剔除不可交易 {len(dropped)} 只次）"
              f" {p['期末']} 累计{p['累计']:7.1%} 年化{p['年化']:6.2%} "
              f"回撤{p['最大回撤']:7.2%} 夏普{p['夏普']:5.2f}", flush=True)

    N = pd.DataFrame(navs).sort_index()
    N.to_csv(os.path.join(OUT, "daily_nav_15_fixed.csv"))
    holds = []
    for nm, reb in fixed.items():
        for d, w in reb.items():
            for c, v in w.items():
                holds.append({"rebal_date": d.strftime("%Y-%m-%d"), "combo": nm,
                              "code": c, "weight": float(v)})
    pd.DataFrame(holds).to_csv(os.path.join(OUT, "holdings_15_fixed.csv"), index=False)
    pd.DataFrame(dropped_all).to_csv(os.path.join(OUT, "dropped_untradable_15.csv"),
                                     index=False, encoding="utf-8-sig")

    # ── 统一绩效表（表 = 图，全部从日频净值聚合）+ 基准 ──
    bench = pd.read_csv(os.path.join(OUT, "bench_daily.csv"), parse_dates=["date"])
    rows = []
    for nm, col in (("CSFM(N=20, κ=1.5)", "CSFM"), ("TSFM(N=30, κ=1.0)", "TSFM"),
                    ("质量Top28", "Q28")):
        s = N[col].dropna()
        p = perf(s)
        rows.append({"组合": nm, "区间": "全期", "口径": "日频(修复)", **p})
        for lab, a, b in SEGS:
            seg = s[(s.index >= pd.Timestamp(a)) & (s.index <= pd.Timestamp(b))]
            pp = perf(seg)
            if pp:
                rows.append({"组合": nm, "区间": lab, "口径": "日频(修复)", **pp})
    for nm, g in bench.groupby("name"):
        s = g.set_index("date")["close"].sort_index()
        s = s[s.index >= START].dropna()
        base = s.iloc[0]
        s = s / base
        p = perf(s)
        rows.append({"组合": nm, "区间": "全期", "口径": "日频", **p})
        for lab, a, b in SEGS:
            seg = s[(s.index >= pd.Timestamp(a)) & (s.index <= pd.Timestamp(b))]
            if len(seg) < 20:
                continue
            pp = perf(seg)
            if pp:
                rows.append({"组合": nm, "区间": lab, "口径": "日频", **pp})
    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(OUT, "perf_unified_15.csv"), index=False, encoding="utf-8-sig")

    fmt = lambda x: "—" if pd.isna(x) else f"{x*100:6.2f}%"
    print(f"\n{'组合':<20}{'区间':<11}{'年化':>8}{'波动':>9}{'夏普':>7}{'回撤':>9}{'卡玛':>7}")
    for _, r in T.iterrows():
        print(f"{r['组合']:<20}{r['区间']:<11}{fmt(r['年化']):>8}{fmt(r['年化波动']):>9}"
              f"{r['夏普']:7.2f}{fmt(r['最大回撤']):>9}{r['卡玛']:7.2f}")

    # ── 一致性校验：三套旧口径 vs 修复口径 ──
    chk = []
    old_daily = pd.read_csv(os.path.join(OUT, "daily_nav_15.csv"), index_col=0, parse_dates=True)
    navm = pd.read_csv(os.path.join(OUT, "nav_cs_ts_15.csv"), index_col=0, parse_dates=True)
    summ = pd.read_csv(os.path.join(OUT, "final_summary_15.csv"))
    for nm, col in (("CSFM", "CSFM"), ("TSFM", "TSFM"), ("Q28", "Q28")):
        fx = perf(N[col].dropna())
        od = perf(old_daily[col].dropna()) if col in old_daily.columns else {}
        page = summ[(summ["组合"].str.startswith(nm)) & (summ["区间"] == "全期")] if nm != "Q28" \
            else summ[(summ["组合"] == "质量Top28 v2") & (summ["区间"] == "全期")]
        pv = float(page["累计"].iloc[0]) if len(page) else np.nan
        pvp = float(page["年化"].iloc[0]) if len(page) else np.nan
        chk.append({"组合": nm, "页面表格_累计": pv, "页面表格_年化": pvp,
                    "旧日净值_累计": od.get("累计"), "旧日净值_年化": od.get("年化"),
                    "修复后_累计": fx.get("累计"), "修复后_年化": fx.get("年化")})
    CK = pd.DataFrame(chk)
    CK.to_csv(os.path.join(OUT, "consistency_check_15.csv"), index=False, encoding="utf-8-sig")
    print("\n=== 三套口径对照 ===")
    print(CK.to_string(index=False,
                       formatters={"页面表格_累计": "{:.1%}".format, "页面表格_年化": "{:.2%}".format,
                                   "旧日净值_累计": "{:.1%}".format, "旧日净值_年化": "{:.2%}".format,
                                   "修复后_累计": "{:.1%}".format, "修复后_年化": "{:.2%}".format}))

    # 2015 年分段专项（用户关心的区间）
    print("\n=== 2015 年专项 ===")
    for col in ("CSFM", "TSFM", "Q28"):
        s = N[col].dropna()
        y15 = s[(s.index >= "2015-01-01") & (s.index <= "2015-12-31")]
        if len(y15) < 20:
            continue
        print(f"  {col:5} 2015 全年 {y15.iloc[-1]/y15.iloc[0]-1:+7.2%}  "
              f"起点 {y15.index[0].date()}  最大回撤 {(y15/y15.cummax()-1).min():7.2%}")
    print(f"\n剔除不可交易记录 {len(dropped_all)} 条 → dropped_untradable_15.csv")
    print("完成：daily_nav_15_fixed.csv / perf_unified_15.csv / consistency_check_15.csv")


if __name__ == "__main__":
    main()
