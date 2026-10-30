# -*- coding: utf-8 -*-
"""日频净值引擎：把月度/季度调仓的选股结果展开成逐日净值。

为什么需要：页面「三、组合回测」的曲线与区间统计按**交易日**计算
（滑块步长 = 1 个交易日，近 1 年 = 252 个交易日），月度净值喂不进去。

口径与 backtest15.py / backtest_quality15.py 完全一致，只是把每段持仓
用「份额自然漂移」的方式逐日累计：
    段内净值(t) = Σ_i w_i · Π_{s<=t}(1 + r_i,s)
调仓日扣双边成本（turnover × 2 × 10bp），与月度回测同一公式。

输出：
    out15/daily_nav_15.csv     date × [CSFM, TSFM, Q28]（2017 年首个交易日起，各列首值 1.00）
    out15/holdings_15.csv      rebal_date, combo, code, weight（全期，含 2015-2016 预热期）
    out15/daily_meta.json      参数、调仓日、窗口起止
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
# 主口径（2017-2026，见 out15/perf_from2017.csv）
CS_N, CS_K = 20, 1.5
TS_N, TS_K = 30, 1.0
TOP_N = 28
# ── 股池文件：按组合分派（2026-10-30 起）──
# 动量两组合（CSFM / TSFM）改用「行业市值前 50 × 各行业 FAQ 前 3」的受限池，
# 依据是 2026-10-29 的 A/B 测算：CSFM 年化 3.67%→9.84%、回撤 −52.2%→−37.6%；
# TSFM 收益几乎不变（8.91%→8.87%）但回撤 −42.0%→−38.8%，风险更低。
# 质量Top28 仍用原池（全行业）—— 换池会让它年化从 10.34% 掉到 6.47%，
# 且二章「季度股池」的口径必须保持不变，故不动。
# 换池只换输入文件，选股 / 加权 / 成本 / 执行时点代码一行未改。
# POOL_FILE_V5 是复现与情景测试的总开关：一旦设置，两个组合同时指向该文件
# （scenario_ind50.py 依赖这一点做「三组合同池」对照）。
def pool_file(combo="CSFM"):
    """返回该组合当期使用的股池文件名（运行时读环境变量，便于情景脚本中途改写）。"""
    force = os.environ.get("POOL_FILE_V5")
    if force:
        return force
    if combo == "Q28":
        return os.environ.get("POOL_FILE_Q28") or "pools_v5.csv"
    return os.environ.get("POOL_FILE_MOM") or "pools_v6_ind50.csv"


# 兼容旧引用（历史上是单一常量）；新代码请用 pool_file(combo)
POOLS_FILE = pool_file()

# ── 统计窗口起点（2026-10-23 定）──
# 2015-2016 含三轮股灾、2016 年首个交易日熔断与千股停牌：期间大量标的连续跌停、
# 调仓日无法成交、停牌权重最高达 25%，收益分布极端到不具备外推意义，计入反而让
# 「组合本身好不好」这个判断失真。因此业绩与净值统一从 2017 年首个交易日起算。
# 注意：**计算并不跳过这两年** —— 因子动量需要 12 个月历史收益预热，2017 年首个
# 调仓日的权重必须由 2015-2016 的行情算出，期初持仓也是当时真实持仓（不是凭空建仓）。
# 这两年的数据只用于预热与期初状态，不进入任何统计口径。
NAV_START = "2017-01-01"


def perf_daily(nav):
    r = nav.pct_change().dropna()
    n = len(r)
    ann = nav.iloc[-1] ** (252.0 / n) - 1
    vol = float(r.std(ddof=0) * np.sqrt(252))
    dd = (nav / nav.cummax() - 1).min()
    return {"累计": nav.iloc[-1] - 1, "年化": ann, "年化波动": vol,
            "夏普": ann / vol if vol else np.nan, "最大回撤": dd,
            "卡玛": ann / abs(dd) if dd < 0 else np.nan, "交易日": n}


def filt_tradable(reb, C, combo=""):
    """调仓日不可交易（当天无成交价 = 停牌/未上市）的标的剔除，权重重新归一。

    为什么必须过滤：`build_nav` 对持仓期内的停牌日按「收益记 0（价格冻结）」处理，
    但**调仓日当天就停牌的票会被按停牌前最后价"买入"**，等复牌那天把整段涨跌幅
    一次性记进净值 —— 那是实盘买不到的收益。2015-09 那期持仓有 25% 权重处于停牌，
    2021-08 盐湖股份复牌单日 +200.8% 就是最典型的虚增来源。

    与 fix_consistency15.filt_tradable 同口径，供生产链路复用。

    返回 (过滤后的 picks, 剔除明细 list)。
    """
    out, dropped = {}, []
    for d, w in reb.items():
        if d not in C.index:
            out[d] = w
            continue
        row = C.loc[d]
        ok = [c for c in w.index if c in row.index and pd.notna(row[c])]
        for c in w.index:
            if c not in ok:
                dropped.append({"combo": combo, "rebal_date": d.strftime("%Y-%m-%d"),
                                "code": c, "weight": float(w[c]),
                                "reason": "调仓日停牌/无价"})
        if not ok:                      # 全期无一只可买 → 该期空仓（极罕见）
            continue
        ww = w.reindex(ok)
        out[d] = ww / ww.sum()
    return out, dropped


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

    # 候选域：动量组合专用池（默认「行业市值前 50 × 各行业 FAQ 前 3」）。
    # 组合只在当期该池内选股；其余(因子收益、Z 分数、门控)与全行业口径完全一致。
    POOL = pool_file("CSFM")
    print(f"  [池] CSFM/TSFM ← {POOL}", flush=True)
    pools = pd.read_csv(os.path.join(D15, POOL), dtype={"code": str})
    pools["code"] = pools["code"].str.zfill(6)
    pool_by_asof = pools.groupby("asof")["code"].apply(set).to_dict()
    pool_asofs = sorted(pool_by_asof)

    def pool_at(d):
        cand = [a for a in pool_asofs if pd.Timestamp(a) <= d]
        return pool_by_asof[cand[-1]] if cand else set()

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
            pm = pool_at(d)
            if pm:
                sc = sc[sc.index.isin(pm)]
            if sc.empty:
                continue
            top = sc.nlargest(N)
            if len(top) < N // 2:
                continue
            out[nm][d] = pd.Series(1.0 / len(top), index=list(top.index))
    print(f"[CSFM] {len(out['CSFM'])} 个调仓日  [TSFM] {len(out['TSFM'])} 个", flush=True)
    return out


def quality_picks():
    """质量组合：按「信息可得日」调仓，候选池 = 当期股池（申万三级各取 FAQ 前 3）。

    与旧口径的区别
      旧：季度末交易日调仓，候选池 = 官方中证800 内按行业取前 5
      新：报告披露完成次月首日（5/1、9/1、11/1）后的第一个交易日调仓，
          候选池 = 当期股池（已按 300 亿市值筛过）。

    **v2 三道筛（2026-10-19 起真正接入 scripts/quality_v2.select_v2）**
      ① 候选：FAQ 降序、单个申万三级行业 ≤ 2 只，取满 28 只候选
      ② 流动性：20 日均成交额 < 5,000 万剔除（剩余 < 15 只才放宽到 3,000 万）
      ③ 拥挤度：换手代理 = 20 日均成交额 ÷ 总市值，候选内排序，剔除分位 > 2/3 的
         最拥挤 1/3；过滤后 < 8 只则判定规则失效、退回候选名单
      ④ 权重：∝ 1/(换手分位 + 0.15)，单只限幅 2%~8%，迭代归一

    因此每期持仓数不再固定 28 只，而是三道筛后的存活数（通常 17~20 只）。
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import quality_v2 as Q2

    # 质量组合保持原池（全行业），与二章「季度股池」同一份文件
    POOL = pool_file("Q28")
    print(f"  [池] Q28      ← {POOL}", flush=True)
    pools = pd.read_csv(os.path.join(D15, POOL), dtype={"code": str})
    pools["code"] = pools["code"].str.zfill(6)
    pools["grp"] = pools["sw3"].fillna("未分类")
    by_asof = {a: g.copy() for a, g in pools.groupby("asof")}

    px = pd.read_pickle(os.path.join(D15, "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    amt = px.pivot(index="date", columns="code", values="amount").ffill(limit=250)
    trade = pd.DatetimeIndex(sorted(px["date"].unique()))
    amt20 = amt.rolling(20, min_periods=10).mean()

    # 总市值：月末面板（个股偶有缺月，向前补 13 个月）
    ex = pd.read_csv(os.path.join(D15, "expo_month_15.csv"), dtype={"code": str},
                     usecols=["date", "code", "mcap"], parse_dates=["date"])
    ex["code"] = ex["code"].str.zfill(6)
    mcap = ex.dropna(subset=["mcap"]).pivot_table(index="date", columns="code",
                                                  values="mcap", aggfunc="last").sort_index()
    mcap = mcap.ffill(limit=13)

    out, stats = {}, []
    for a in sorted(by_asof):
        nxt = trade[trade > pd.Timestamp(a)]
        if len(nxt) == 0:
            continue
        d = nxt[0]
        g = by_asof[a]
        ranked = g.sort_values("FAQ_score", ascending=False)
        cands = [(str(r["code"]), float(r["FAQ_score"])) for _, r in ranked.iterrows()
                 if pd.notna(r["FAQ_score"])]
        if len(cands) < Q2.MIN_FINAL:
            continue
        sw3 = dict(zip(g["code"].astype(str), g["grp"]))

        # 换手代理：(adv20, adv20 / 总市值)，只用调仓日 T 及之前的数据
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
            # 三道筛没法正常跑（换手数据不足 / 过滤后过少）→ 等权兜底，仍守行业 ≤2
            codes = [c for c, _ in picked] if len(picked[0]) == 2 else [c for c, _, _ in picked]
            n = max(len(codes), 1)
            w = pd.Series(1.0 / n, index=codes)
            print(f"  [降级] {a} {meta['degrade']} → 等权 {n} 只", flush=True)
        w = w / w.sum()
        out[d] = w
        stats.append({"asof": a, "date": d.strftime("%Y-%m-%d"), "n": len(w),
                      "degrade": meta["degrade"], "floor": meta["floor"],
                      "wmin": float(w.min()), "wmax": float(w.max())})

    n_ok = sum(1 for s in stats if s["degrade"] == "ok")
    ns = [s["n"] for s in stats]
    print(f"[Q28] {len(out)} 个调仓日（信息可得日次一交易日）· 三道筛正常 {n_ok} 期 · "
          f"持仓 {min(ns)}~{max(ns)} 只（均值 {np.mean(ns):.1f}）", flush=True)
    print(f"      权重区间 {min(s['wmin'] for s in stats):.2%}~"
          f"{max(s['wmax'] for s in stats):.2%}", flush=True)
    pd.DataFrame(stats).to_csv(os.path.join(OUT, "q28_v2_stats.csv"), index=False)
    return out

def main():
    px = pd.read_pickle(os.path.join(D15, "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    R = px.pivot(index="date", columns="code", values="ret").sort_index()
    last = R.index[-1]
    print(f"[px] 日收益 {R.shape[0]} 日 × {R.shape[1]} 只 {R.index[0]:%Y-%m-%d}~{last:%Y-%m-%d}", flush=True)

    picks = csfm_tsfm_picks()
    picks["Q28"] = quality_picks()

    # 调仓日可交易过滤：停牌/当天无价的标的不计入持仓，权重按剩余标的重新归一
    close = px.pivot(index="date", columns="code", values="close").sort_index()
    drops = []
    for nm in list(picks):
        picks[nm], dp = filt_tradable(picks[nm], close, nm)
        drops.extend(dp)
    if drops:
        pd.DataFrame(drops).to_csv(os.path.join(OUT, "dropped_untradable_15.csv"),
                                   index=False)
        by = pd.DataFrame(drops).groupby("combo").size().to_dict()
        print(f"  [可交易过滤] 剔除 {len(drops)} 只次（调仓日停牌/无价）："
              f"CSFM {by.get('CSFM', 0)} / TSFM {by.get('TSFM', 0)} / Q28 {by.get('Q28', 0)}",
              flush=True)

    navs, holds = {}, []
    for nm, reb in picks.items():
        s = build_nav(reb, R, last)
        navs[nm] = s
        for d, w in reb.items():
            for c, v in w.items():
                holds.append({"rebal_date": d.strftime("%Y-%m-%d"), "combo": nm,
                              "code": c, "weight": float(v)})
        p = perf_daily(s)
        print(f"  [预热] {nm:5} {s.index[0]:%Y-%m-%d}~{s.index[-1]:%Y-%m-%d} "
              f"累计{p['累计']:7.1%} 年化{p['年化']:6.2%}（含 2015-2016，仅用于预热，不进统计）",
              flush=True)

    N = pd.DataFrame(navs).sort_index()
    # 裁到统计窗口：起点之前的数据已参与因子动量预热与期初持仓，此处只截断输出。
    if NAV_START:
        N = N[N.index >= pd.Timestamp(NAV_START)]
        N = N / N.iloc[0]                       # 各列统一在窗口首日归一到 1.00
    for nm in N.columns:
        p = perf_daily(N[nm])
        print(f"  {nm:5} {N.index[0]:%Y-%m-%d}~{N.index[-1]:%Y-%m-%d} "
              f"累计{p['累计']:7.1%} 年化{p['年化']:6.2%} 波动{p['年化波动']:6.2%} "
              f"夏普{p['夏普']:5.2f} 回撤{p['最大回撤']:7.2%}", flush=True)

    N.to_csv(os.path.join(OUT, "daily_nav_15.csv"))
    pd.DataFrame(holds).to_csv(os.path.join(OUT, "holdings_15.csv"), index=False)
    json.dump({"cs": [CS_N, CS_K], "ts": [TS_N, TS_K],
               "n_cs": len(picks["CSFM"]), "n_ts": len(picks["TSFM"]), "n_q28": len(picks["Q28"]),
               "nav_start": NAV_START, "start": N.index[0].strftime("%Y-%m-%d"),
               "end": N.index[-1].strftime("%Y-%m-%d"), "n_days": int(len(N))},
              open(os.path.join(OUT, "daily_meta.json"), "w"), ensure_ascii=False)
    print("done", flush=True)


if __name__ == "__main__":
    main()
