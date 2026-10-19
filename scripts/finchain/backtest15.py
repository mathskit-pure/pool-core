# -*- coding: utf-8 -*-
"""2015-01 ~ 2026-10 三组合回测（官方中证800 成分内）。
CSFM / TSFM：10 因子动量符号加权 z 分数选股，月度调仓，F 反馈强度 κ 门控
质量Top28：FAQ 排序 + v1/v2 约束，季度调仓
口径对齐 fmf/src/f2.py、f3.py 与 pool-core/scripts/quality_v2.py
"""
import os
import sys
import itertools
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402
os.makedirs(OUT, exist_ok=True)
FACTORS = ["size", "bm", "roa", "accr", "cp", "ep", "illiq", "turn", "bab", "ivol"]
COST = 0.0010
WIN_PCT, MIN_PCT = 48, 24


# ---------------- 绩效 ----------------
def perf(s, rf=0.0):
    s = s.dropna()
    if len(s) < 6:
        return {"月数": len(s)}
    nav = (1 + s).cumprod()
    yrs = len(s) / 12.0
    ann = nav.iloc[-1] ** (1 / yrs) - 1
    vol = s.std(ddof=1) * np.sqrt(12)
    dd = (nav / nav.cummax() - 1).min()
    return {"累计": nav.iloc[-1] - 1, "年化": ann, "年化波动": vol,
            "夏普": (ann - rf) / vol if vol > 0 else np.nan,
            "最大回撤": dd, "卡玛": ann / abs(dd) if dd < 0 else np.nan,
            "胜率": (s > 0).mean(), "最差月": s.min(), "月数": len(s)}


# ---------------- 因子拥挤 F ----------------
def roll_pct(s, win=WIN_PCT, minp=MIN_PCT):
    return s.rolling(win, min_periods=minp).apply(
        lambda w: float((w <= w[-1]).mean() * 100.0), raw=True)


def _es(seg, q=0.05):
    if len(seg) < 12:
        return np.nan
    k = max(1, int(len(seg) * q))
    return float(np.sort(seg)[:k].mean())


def _ar1(seg):
    if len(seg) < 12 or np.std(seg) < 1e-12:
        return np.nan
    return float(np.corrcoef(seg[:-1], seg[1:])[0, 1])


def _r2(seg):
    if len(seg) < 8 or np.std(seg) < 1e-12:
        return np.nan
    x = np.arange(len(seg), dtype=float)
    c = np.corrcoef(x, seg)[0, 1]
    return float(c ** 2) if np.isfinite(c) else np.nan


def build_crowding(fr):
    factors = list(fr.columns)
    mkt = fr.mean(axis=1)
    C, S, F = {}, {}, {}
    for f in factors:
        r = fr[f]
        cum12 = (1 + r.fillna(0)).rolling(12, min_periods=9).apply(np.prod, raw=True) - 1
        vcomp = -(r.rolling(3, min_periods=2).std() /
                  r.rolling(24, min_periods=12).std().replace(0, np.nan))
        herd = r.rolling(24, min_periods=12).corr(mkt)
        C[f] = pd.concat([roll_pct(cum12), roll_pct(vcomp), roll_pct(herd)], axis=1).mean(axis=1)
        es36 = r.rolling(36, min_periods=18).apply(_es, raw=True)
        vol36 = r.rolling(36, min_periods=18).std()
        sk36 = r.rolling(36, min_periods=18).apply(lambda w: pd.Series(w).skew(), raw=True)
        S[f] = pd.concat([roll_pct(-es36), roll_pct(vol36), roll_pct(-sk36)], axis=1).mean(axis=1)
        ar1 = r.rolling(24, min_periods=15).apply(_ar1, raw=True)
        r2 = r.rolling(12, min_periods=9).apply(_r2, raw=True)
        F[f] = pd.concat([roll_pct(ar1), roll_pct(r2)], axis=1).mean(axis=1)
    C, S, F = pd.DataFrame(C), pd.DataFrame(S), pd.DataFrame(F)
    R = 100.0 * (C / 100.0) * (S / 100.0) * (0.5 + F / 100.0) / 1.5
    out = pd.concat([C.add_prefix("C_"), S.add_prefix("S_"), F.add_prefix("F_"), R.add_prefix("R_")], axis=1)
    out.index.name = "date"
    return out


def main():
    fr = pd.read_csv(os.path.join(D15, "factor_ret_15.csv"), index_col=0, parse_dates=True)[FACTORS]
    expo = pd.read_csv(os.path.join(D15, "expo_month_15.csv"), parse_dates=["date"], dtype={"code": str})
    expo["code"] = expo["code"].str.zfill(6)
    pr = pd.read_csv(os.path.join(D15, "pool_ret_15.csv"), parse_dates=["date"], dtype={"code": str})
    pr["code"] = pr["code"].str.zfill(6)

    print(f"[in] 因子收益 {fr.shape[0]} 月 {fr.index[0]:%Y-%m}~{fr.index[-1]:%Y-%m}; "
          f"暴露 {len(expo):,} 行", flush=True)

    # ---- 因子拥挤 F ----
    cr = build_crowding(fr)
    cr.to_csv(os.path.join(OUT, "factor_crowding_15.csv"))
    Fm = cr[[f"F_{f}" for f in FACTORS]].copy()
    Fm.columns = FACTORS

    # ---- 个股 F（60日 ar1 + 趋势R² 横截面百分位）----
    px = pd.read_pickle(os.path.join(D15, "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    ret_w = px.pivot(index="date", columns="code", values="ret")
    logi = np.log(px.pivot(index="date", columns="code", values="idx"))
    ar1w = ret_w.rolling(60, min_periods=40).apply(
        lambda w: float(np.corrcoef(w[:-1], w[1:])[0, 1]) if np.std(w) > 1e-12 else np.nan, raw=True)
    tt = pd.Series(np.arange(len(logi), dtype=float), index=logi.index)
    r2w = logi.rolling(60, min_periods=40).corr(tt) ** 2
    me = pd.DatetimeIndex(sorted(expo["date"].unique()))
    a = ar1w.reindex(me)
    b = r2w.reindex(me)
    Fs = 100.0 * (a.rank(axis=1, pct=True) + b.rank(axis=1, pct=True)) / 2.0
    print(f"[Fs] 个股F {Fs.shape[0]} 月 × {Fs.shape[1]} 只", flush=True)

    # ---- 宽表 ----
    z = {f: expo.pivot(index="date", columns="code", values=f"z_{f}") for f in FACTORS}
    Rw = pr.pivot(index="date", columns="code", values="ret_next")
    # 月收益缩尾：源后复权序列存在极端跳变，按回测惯例做 ±100% 截断
    Rw = Rw.clip(lower=-0.60, upper=1.00)
    member = expo.groupby("date")["code"].apply(set).to_dict()

    mc = (1 + fr).cumprod()
    mom = mc.shift(1) / mc.shift(13) - 1
    med = mom.median(axis=1)
    w_ts = np.sign(mom)
    w_cs = np.sign(mom.sub(med, axis=0)).replace(0, 1.0)
    Fhat = Fm / 100.0

    dates = [d for d in mom.index if d in member and d in Rw.index]
    print(f"[dec] 决策月 {len(dates)}: {dates[0]:%Y-%m} ~ {dates[-1]:%Y-%m}", flush=True)

    def run(wmat, N=30, kappa=0.0, fs_filter=None):
        recs, turns, prev, hold = {}, {}, None, []
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
            if fs_filter is not None and d in Fs.index:
                cand = sc.nlargest(int(N * 1.5))
                fs_ = Fs.loc[d].reindex(cand.index)
                if fs_.notna().sum() >= N:
                    thr = fs_.quantile(1 - fs_filter)
                    kept = cand[fs_ <= thr]
                    top = kept.nlargest(N) if len(kept) >= N else cand.nlargest(N)
                else:
                    top = cand.nlargest(N)
            else:
                top = sc.nlargest(N)
            if len(top) < N // 2:
                continue
            r = float(Rw.loc[d].reindex(top.index).fillna(0.0).mean())
            turn = 1.0 if prev is None else 0.5 * len(set(top.index) ^ set(prev)) / max(len(top), 1)
            recs[d] = r - turn * 2 * COST
            turns[d] = turn
            for c in top.index:
                hold.append((d, c, 1.0 / len(top)))
            prev = top.index
        return pd.Series(recs).sort_index(), pd.Series(turns).sort_index(), pd.DataFrame(
            hold, columns=["date", "code", "w"])

    # ---- 网格 ----
    rows = []
    navs = {}
    for nm, wmat in (("CSFM", w_cs), ("TSFM", w_ts)):
        for N in (15, 20, 30, 40, 50):
            for kappa in (0.0, 0.5, 1.0, 1.5):
                r, t, h = run(wmat, N=N, kappa=kappa)
                p = perf(r)
                rows.append({"组合": nm, "N": N, "kappa": kappa, **p,
                             "年换手": float(t.mean() * 12)})
                navs[f"{nm}_N{N}_k{kappa}"] = (1 + r).cumprod()
    G = pd.DataFrame(rows)
    G.to_csv(os.path.join(OUT, "grid_cs_ts_15.csv"), index=False, encoding="utf-8-sig")
    print("\n[CSFM/TSFM 参数前沿]")
    for nm in ("CSFM", "TSFM"):
        sub = G[G["组合"] == nm].sort_values("夏普", ascending=False).head(6)
        print(f"--- {nm} ---")
        print(sub[["N", "kappa", "年化", "年化波动", "夏普", "最大回撤"]].to_string(
            index=False, formatters={"年化": "{:.2%}".format, "年化波动": "{:.2%}".format,
                                     "夏普": "{:.2f}".format, "最大回撤": "{:.2%}".format}), flush=True)

    # 个股 F 过滤变体（对最优参数）
    for nm, wmat in (("CSFM", w_cs), ("TSFM", w_ts)):
        r, t, _ = run(wmat, N=30, kappa=1.0, fs_filter=0.2)
        p = perf(r)
        print(f"{nm}_SFX(N30,k1.0,剔高F20%): 年化{p['年化']:.2%} 波动{p['年化波动']:.2%} "
              f"夏普{p['夏普']:.2f} 回撤{p['最大回撤']:.2%}", flush=True)
        rows.append({"组合": nm + "_SFX", "N": 30, "kappa": 1.0, **p, "年换手": float(t.mean() * 12)})

    pd.DataFrame(rows).to_csv(os.path.join(OUT, "grid_all_15.csv"), index=False, encoding="utf-8-sig")

    cur = pd.DataFrame({k: v for k, v in navs.items()}).dropna(how="all")
    cur.to_csv(os.path.join(OUT, "nav_cs_ts_15.csv"))


if __name__ == "__main__":
    main()
