# -*- coding: utf-8 -*-
"""情景：股池范围进一步限定为「申万三级行业市值前 50 × 各行业 FAQ 前 3」。

口径（与 build_pools_v5.py 只差两处，其余完全不动）
----------------------------------------------
基础候选池不变：全市场总市值 ≥ 300 亿、剔除 ST / 上市未满 365 天（universe_pit.csv）。
新增限制  ⓐ 行业准入：按「申万三级行业总市值」降序只保留前 50 个行业；
          ⓑ 行业名额：每个准入行业仍取 FAQ（舞弊调整质量因子）评分前 3。
于是股池从「全部行业 × 前 3」（约 200 个行业、370~490 只）收缩到「50 个行业 × 前 3」
（最多 150 只），行业个数是唯一变量 —— 便于把业绩变化全部归因到行业限制上。

行业总市值的计算（PIT）
----------------------------------------------
    mcap = 未复权月收盘价（<= asof 的最后一个观测） × 总股本
    总股本 = 股东权益(te) / 每股净资产(bps)，取公告日 avail <= asof 的最近一期
    行业总市值 = Σ 该行业全部 A 股 mcap（**全市场**，不是 300 亿池子内部，
                 否则大市值行业会被系统性低估）
    行业归属 = faq_panel 中该报告期（或之前最近一期）的 sw3

输出
    data15/industry_rank.csv          asof, sw3, ind_mcap_yi, rank
    data15/pools_v6_ind50.csv         asof, report_period, label, code, name, sw1, sw3,
                                      FAQ_score, rank_in_ind, ind_rank
    data15/pools_v6_ind50_stat.csv    每期行业数 / 股池只数 / 入选行业市值门槛
"""
import os
import sys
import glob
import csv

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_D15 as D15, FIN_MON as MON  # noqa: E402

TOP_IND = 50        # 只保留市值排名前 50 的申万三级行业
TOPN = 3            # 每个行业取 FAQ 前 3
PANEL = os.path.join(os.path.dirname(str(MON)), "panel.csv")
PERIOD_MAP = {"05-01": "-03-31", "09-01": "-06-30", "11-01": "-09-30"}
LABEL = {"05-01": "一季报", "09-01": "中报", "11-01": "三季报"}


def load_mon():
    frs = []
    for p in glob.glob(os.path.join(str(MON), "*.csv")):
        c = os.path.basename(p)[:6]
        if not c.isdigit():
            continue
        try:
            d = pd.read_csv(p, dtype={"date": str})
        except Exception:
            continue
        if d.empty or "close" not in d.columns:
            continue
        d["code"] = c
        frs.append(d[["code", "date", "close"]])
    mon = pd.concat(frs, ignore_index=True)
    mon["date"] = pd.to_datetime(mon["date"], errors="coerce")
    mon["close"] = pd.to_numeric(mon["close"], errors="coerce")
    mon = mon.dropna(subset=["date", "close"])
    mon = mon[mon["close"] > 0]
    return mon.sort_values(["code", "date"]).reset_index(drop=True)


def load_panel():
    keep = {"code", "period", "avail", "name", "te", "bps"}
    rows = []
    with open(PANEL, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if not r.get("avail"):
                continue
            rows.append({k: r.get(k) for k in keep})
    p = pd.DataFrame(rows)
    p["code"] = p["code"].str.zfill(6)
    for c in ("te", "bps"):
        p[c] = pd.to_numeric(p[c], errors="coerce")
    return p


def load_names():
    best = {}
    with open(PANEL, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            c = (r.get("code") or "").strip().zfill(6)
            if len(c) != 6:
                continue
            nm = (r.get("name") or "").strip()
            p = r.get("period") or ""
            if not nm:
                continue
            if c not in best or p > best[c][0]:
                best[c] = (p, nm)
    return {c: v[1] for c, v in best.items()}


def main():
    uni = pd.read_csv(os.path.join(str(D15), "universe_pit.csv"), dtype={"code": str})
    uni["code"] = uni["code"].str.zfill(6)
    asofs = sorted(uni["asof"].unique())
    print(f"[universe] {len(asofs)} 期, {uni['code'].nunique()} 只", flush=True)

    faq = pd.read_csv(os.path.join(str(D15), "faq_panel_2015.csv.gz"), dtype={"code": str},
                      usecols=["code", "EndDate", "FAQ_score", "sw1", "sw3"])
    faq["code"] = faq["code"].str.zfill(6)
    faq["EndDate"] = faq["EndDate"].astype(str)
    faq = faq[faq["FAQ_score"].notna()].copy()
    print(f"[faq] {len(faq):,} 条", flush=True)

    # 行业归属：全期 sw3 备查，用于给「全市场个股」贴行业
    sw_hist = faq[["code", "EndDate", "sw3"]].dropna().drop_duplicates()
    sw_latest = sw_hist.sort_values("EndDate").groupby("code")["sw3"].last()

    mon = load_mon()
    print(f"[mon] {len(mon):,} 行 / {mon['code'].nunique()} 只", flush=True)
    panel = load_panel()
    print(f"[panel] {len(panel):,} 行 / {panel['code'].nunique()} 只", flush=True)
    names = load_names()

    rank_rows, pool_rows, stat = [], [], []
    for a in asofs:
        suf = a[5:10]
        if suf not in PERIOD_MAP:
            continue
        rp = a[:4] + PERIOD_MAP[suf]
        ad = pd.Timestamp(a)

        # ── 全市场 PIT 市值 ──
        sub = mon[mon["date"] <= ad]
        px = sub.groupby("code").tail(1).set_index("code")["close"]
        pv = panel[panel["avail"] <= a].sort_values(["code", "period"])
        fin = pv.groupby("code").tail(1).set_index("code")
        shares = fin["te"] / fin["bps"].where(fin["bps"] > 0.05)
        mcap = (px.reindex(shares.index) * shares) / 1e8
        mcap = mcap.replace([np.inf, -np.inf], np.nan).dropna()
        mcap = mcap[mcap > 0]

        # 行业归属：优先用该报告期的 sw3，缺失回落到历史最近一期
        sw_now = sw_hist[sw_hist["EndDate"] == rp].set_index("code")["sw3"]
        sw_use = sw_now.reindex(mcap.index)
        sw_use = sw_use.fillna(sw_latest.reindex(mcap.index))
        mm = pd.DataFrame({"sw3": sw_use, "mcap": mcap}).dropna()
        ind = mm.groupby("sw3")["mcap"].sum().sort_values(ascending=False)
        top = ind.head(TOP_IND)
        for k, (name, v) in enumerate(top.items(), 1):
            rank_rows.append({"asof": a, "sw3": name, "ind_mcap_yi": round(float(v), 1), "rank": k})
        keep_ind = set(top.index)

        # ── 候选池（≥300 亿、非 ST、非次新）→ 行业准入 → 行业内 FAQ 前 3 ──
        members = set(uni.loc[uni["asof"] == a, "code"])
        f = faq[(faq["EndDate"] == rp) & (faq["code"].isin(members))].copy()
        f["rank_all"] = f.groupby("sw3")["FAQ_score"].rank(ascending=False, method="first")
        f = f[f["sw3"].isin(keep_ind)]
        f["rank_in_ind"] = f.groupby("sw3")["FAQ_score"].rank(ascending=False, method="first")
        pool = f[f["rank_in_ind"] <= TOPN].sort_values(["sw3", "rank_in_ind"])
        for _, r in pool.iterrows():
            pool_rows.append({
                "asof": a, "report_period": rp, "label": f"{a[:4]}年{LABEL[suf]}",
                "code": r["code"], "name": names.get(r["code"], r["code"]),
                "sw1": r["sw1"], "sw3": r["sw3"],
                "FAQ_score": round(float(r["FAQ_score"]), 6),
                "rank_in_ind": int(r["rank_in_ind"]),
                "ind_rank": int(list(top.index).index(r["sw3"]) + 1),
            })
        stat.append({"asof": a, "report_period": rp, "cand": len(f),
                     "pool_in": len(members), "industries_in_pool": pool["sw3"].nunique(),
                     "picked": len(pool),
                     "ind50_min_mcap_yi": round(float(top.iloc[-1]), 1),
                     "ind_all": int(ind.shape[0])})
        print(f"{a} → {rp}: 全市场 {len(mcap):5d} 只 / 行业 {ind.shape[0]:3d} "
              f"→ 前50门槛 {top.iloc[-1]:8.0f} 亿 | 候选 {len(f):4d} → 股池 {len(pool):3d} 只 "
              f"/ {pool['sw3'].nunique():2d} 行业", flush=True)

    R = pd.DataFrame(rank_rows)
    R.to_csv(os.path.join(str(D15), "industry_rank.csv"), index=False, encoding="utf-8-sig")
    P = pd.DataFrame(pool_rows)
    P.to_csv(os.path.join(str(D15), "pools_v6_ind50.csv"), index=False, encoding="utf-8-sig")
    S = pd.DataFrame(stat)
    S.to_csv(os.path.join(str(D15), "pools_v6_ind50_stat.csv"), index=False, encoding="utf-8-sig")

    print()
    print(f"[done] {len(P):,} 行 / {P['code'].nunique()} 只 / {P['asof'].nunique()} 期")
    print(f"  股池规模 min={S['picked'].min()} max={S['picked'].max()} 均值={S['picked'].mean():.1f}"
          f"（v5：185~489，均值 {489 if False else 323:.0f}）")
    print(f"  行业数   min={S['industries_in_pool'].min()} max={S['industries_in_pool'].max()}")


if __name__ == "__main__":
    main()
