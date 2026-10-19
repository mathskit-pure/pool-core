# -*- coding: utf-8 -*-
"""质量 Top28 组合回测（2015-2026，官方中证800 成分内）。
流程：每期官方成分 → FAQ 评分 → 申万三级各取前5 建池 → 池内取 FAQ Top28
v1：等权；v2：行业≤2 / 流动性≥5000万 / 反换手加权
季度调仓（跟随财报可得性），复用 quality_v2.py 规则。
"""
import os
import sys
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402
os.makedirs(OUT, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
COST = 0.0010
TOP_N = 28


def perf(s, ppy=4):
    """ppy=4：季度收益序列。年化/波动必须按季度折年，不能当月度。"""
    s = s.dropna()
    if len(s) < 6:
        return {"期数": len(s)}
    nav = (1 + s).cumprod()
    yrs = len(s) / float(ppy)
    ann = nav.iloc[-1] ** (1 / yrs) - 1
    vol = s.std(ddof=1) * np.sqrt(ppy)
    dd = (nav / nav.cummax() - 1).min()
    return {"累计": nav.iloc[-1] - 1, "年化": ann, "年化波动": vol,
            "夏普": ann / vol if vol > 0 else np.nan,
            "最大回撤": dd, "卡玛": ann / abs(dd) if dd < 0 else np.nan,
            "胜率": (s > 0).mean(), "最差期": s.min(), "期数": len(s)}


def main():
    faq = pd.read_csv(os.path.join(D15, "faq_panel_2015.csv.gz"), dtype={"code": str},
                      parse_dates=["EndDate", "pd"])
    faq["code"] = faq["code"].astype(str).str.zfill(6)
    pit = pd.read_csv(os.path.join(D15, "official_csi800_pit_2015.csv"), dtype=str)
    pit["c"] = pit["code"].map(lambda x: x[2:] if x[:2] in ("sh", "sz") else x)
    mem_by = pit.groupby("asof")["c"].apply(set).to_dict()
    asofs = sorted(mem_by)

    px = pd.read_pickle(os.path.join(D15, "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    # 月末交易日
    dts = pd.Series(px["date"].unique())
    me = pd.DatetimeIndex(sorted(dts.groupby([dts.dt.year, dts.dt.quarter]).max().values))
    # 季度调仓：2014-12-31 决策（2014Q3 报表可得），2015-03-31 起计收益 → 净值起点对齐 2015-01
    me = me[me >= pd.Timestamp("2014-12-31")]
    clo = px.pivot(index="date", columns="code", values="close")
    amt = px.pivot(index="date", columns="code", values="amount")
    # 关键：日频前向填充停牌价，避免「季度末价格为 NaN → pct_change 跨多季」的伪收益
    clo = clo.ffill(limit=250)
    amt = amt.ffill(limit=250)
    clo_me = clo.reindex(me)
    amt_ma = amt.rolling(20, min_periods=10).mean().reindex(me)
    # 20 日换手率（成交量/股本），用于反换手加权
    finp = pd.read_pickle(os.path.join(D15, "fin_pit.pkl"))
    sh = finp.sort_values("avail").drop_duplicates("code", keep="last").set_index("code")["shares"]
    vol_ma = px.pivot(index="date", columns="code", values="volume").rolling(20, min_periods=10).mean().reindex(me)
    turn20 = vol_ma * 100.0 / sh.reindex(vol_ma.columns)
    turn_med = turn20.median(axis=1)
    # 算力：月末环比收益（缩尾：剔除后复权序列异常导致的极端跳变）
    r_me = clo_me.pct_change()
    r_me = r_me.clip(lower=-0.60, upper=1.50)

    print(f"[me] 季度末 {len(me)} 个: {me[0]:%Y-%m} ~ {me[-1]:%Y-%m}", flush=True)

    def pick_pool(d):
        """当期官方成分 + 最新可得 FAQ → 申万三级取前5"""
        cand = [a for a in asofs if pd.Timestamp(a) <= d]
        if not cand:
            return None, None
        mem = mem_by[cand[-1]]
        f = faq[(faq["pd"] <= d) & (faq["code"].isin(mem)) & faq["FAQ_score"].notna()].copy()
        if f.empty:
            return None, None
        # 每代码只保留最新一期
        f = f.sort_values("pd").drop_duplicates("code", keep="last")
        # 三级行业取前5（未分类的单列一组）
        f["grp"] = f["sw3"].fillna("未分类")
        pool = f.sort_values("FAQ_score", ascending=False).groupby("grp", sort=False).head(5)
        return pool, mem

    rows, codes_hist = {}, {}
    hold_v1, hold_v2 = None, None
    ret_v1, ret_v2, ret_all = {}, {}, {}
    pool_size = {}
    for i, d in enumerate(me):
        pool, mem = pick_pool(d)
        if pool is None or len(pool) < TOP_N:
            continue
        pool_size[d] = len(pool)
        ranked = pool.sort_values("FAQ_score", ascending=False)

        # v1：直接 top28 等权
        top1 = ranked.head(TOP_N)
        # v2：行业≤2 + 流动性 + 反换手加权
        cnt, top2 = {}, []
        for _, r in ranked.iterrows():
            g = r["grp"]
            if cnt.get(g, 0) >= 2:
                continue
            a = amt_ma.loc[d].get(r["code"], np.nan) if d in amt_ma.index else np.nan
            if not (a >= 5e7):  # 20日成交额 ≥5000万
                continue
            top2.append(r)
            cnt[g] = cnt.get(g, 0) + 1
            if len(top2) >= TOP_N:
                break
        if len(top2) < TOP_N:  # 流动性约束过严时放宽
            got = {x["code"] for x in top2}
            for _, r in ranked.iterrows():
                if len(top2) >= TOP_N:
                    break
                if r["code"] in got:
                    continue
                if cnt.get(r["grp"], 0) >= 2:
                    continue
                top2.append(r); cnt[r["grp"]] = cnt.get(r["grp"], 0) + 1

        # 下一期区间收益
        if i + 1 >= len(me):
            continue
        nxt = me[i + 1]
        seg = r_me.loc[nxt]

        for tag, top, hold in (("v1", top1, hold_v1), ("v2", pd.DataFrame(top2), hold_v2)):
            if top is None or len(top) == 0:
                continue
            codes = list(top["code"])
            r = seg.reindex(codes).fillna(0.0)
            # 单只个股单期收益再缩尾，避免个别异常值主导组合
            r = r.clip(lower=-0.60, upper=1.50)
            if tag == "v1":
                w = pd.Series(1.0 / len(codes), index=codes)
            else:
                # 反换手加权：20 日换手率越高，权重越低（避免追高换手）
                tr = turn20.loc[d].reindex(codes).fillna(turn_med.loc[d]) if d in turn20.index else pd.Series(
                    1.0, index=codes)
                tr = tr.clip(lower=tr.quantile(0.05) if tr.notna().any() else 1e-6)
                raw = 1.0 / (1.0 + tr / (tr.median() if tr.median() > 0 else 1.0))
                w = raw / raw.sum()
            rr = float((r * w).sum())
            prev = set(hold) if hold is not None else None
            turn = 1.0 if prev is None else 0.5 * len(set(codes) ^ prev) / max(len(codes), 1)
            net = rr - turn * 2 * COST
            # 收益记在「实现日」（区间末端），与净值曲线时间轴一致
            (ret_v1 if tag == "v1" else ret_v2)[nxt] = net
            if tag == "v1":
                hold_v1 = codes
            else:
                hold_v2 = codes

    s1 = pd.Series(ret_v1).sort_index()
    s2 = pd.Series(ret_v2).sort_index()
    tab = pd.DataFrame({"v1": perf(s1), "v2": perf(s2)}).T
    print("\n[质量Top28]")
    print(tab.to_string(formatters={"累计": "{:.2%}".format, "年化": "{:.2%}".format,
                                    "年化波动": "{:.2%}".format, "夏普": "{:.2f}".format,
                                    "最大回撤": "{:.2%}".format, "卡玛": "{:.2f}".format,
                                    "胜率": "{:.1%}".format, "最差期": "{:.2%}".format}), flush=True)
    print(f"[pool] 每期股池只数: 均 {np.mean(list(pool_size.values())):.0f} "
          f"({min(pool_size.values())}~{max(pool_size.values())})，共 {len(pool_size)} 期", flush=True)
    pd.DataFrame({"v1": s1, "v2": s2}).to_csv(os.path.join(OUT, "quality_ret_15.csv"))
    pd.DataFrame({"v1": (1 + s1).cumprod(), "v2": (1 + s2).cumprod()}).to_csv(
        os.path.join(OUT, "quality_nav_15.csv"))
    tab.to_csv(os.path.join(OUT, "quality_perf_15.csv"), encoding="utf-8-sig")


if __name__ == "__main__":
    main()
