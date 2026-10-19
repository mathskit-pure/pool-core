# -*- coding: utf-8 -*-
"""组装页面数据包：股池（官方成分口径）+ 三组合绩效 + 净值 + 最新持仓。

输出 out15/page_data.json
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402
os.makedirs(OUT, exist_ok=True)
START_POOL = "2019-05-01"
TOP_N = 28


def period_label(asof):
    """按信息可得日月份推断报告期（5→一季报 / 9→中报 / 11→三季报）。

    不直接用 EndDate：个别公司季报缺失时沿用上一年报，同一期内 EndDate 会混两个报告期，
    取首行会误标成「年报」。
    """
    y, m = asof.year, asof.month
    return {5: f"{y}年一季报", 9: f"{y}年中报", 11: f"{y}年三季报"}.get(m, f"{y}年{m:02d}月")


def main():
    name = json.load(open(os.path.join(OUT, "name_map.json"), encoding="utf-8"))
    pool = pd.read_csv(os.path.join(OUT, "period_pools_2015_2026.csv"), dtype={"code": str})
    pool["code"] = pool["code"].str.zfill(6)
    pool["asof"] = pd.to_datetime(pool["asof"])
    pool["EndDate"] = pd.to_datetime(pool["EndDate"])
    pool = pool[pool["asof"] >= pd.Timestamp(START_POOL)]

    # 市值：exp 面板（date × code 的 mcap），取 asof 之前最近月末
    ex = pd.read_csv(os.path.join(D15, "expo_month_15.csv"), dtype={"code": str},
                     usecols=["date", "code", "mcap"], parse_dates=["date"])
    ex["code"] = ex["code"].str.zfill(6)
    ex = ex.dropna(subset=["mcap"])
    exm = ex.pivot_table(index="date", columns="code", values="mcap", aggfunc="last")

    pools = []
    for asof, g in pool.groupby("asof", sort=True):
        prev = exm.index[exm.index <= asof]
        mc = exm.loc[prev[-1]] if len(prev) else pd.Series(dtype=float)
        recs = []
        for _, r in g.iterrows():
            mv = mc.get(r["code"], np.nan)
            recs.append({"c": r["code"], "n": name.get(r["code"], "—"),
                         "s": round(float(r["FAQ_score"]), 2),
                         "m": round(float(mv) / 1e8, 0) if pd.notna(mv) else None,
                         "ind": r["sw3"] if isinstance(r["sw3"], str) else "未分类"})
        df = pd.DataFrame(recs).sort_values("s", ascending=False)
        df["m"] = df["m"].astype(object).where(df["m"].notna(), None)
        inds = []
        for ind, gi in df.groupby("ind", sort=False):
            gi = gi.sort_values("s", ascending=False)
            inds.append({"name": ind, "items": gi[["c", "n", "s", "m"]].to_dict("records")})
        # 行业按「行业内最高分」降序
        inds.sort(key=lambda x: -x["items"][0]["s"])
        pools.append({"asof": asof.strftime("%Y-%m-%d"),
                      "label": period_label(asof),
                      "end": g["EndDate"].iloc[0].strftime("%Y-%m-%d"),
                      "n": len(df), "nind": len(inds), "inds": inds})
    print(f"[pools] {len(pools)} 期，均 {np.mean([p['n'] for p in pools]):.0f} 只 / "
          f"{np.mean([p['nind'] for p in pools]):.0f} 行业", flush=True)

    # 最新一期质量 Top28（行业≤2，FAQ 降序）
    cur = pools[-1]
    flat = [(i["name"], it) for i in cur["inds"] for it in i["items"]]
    flat.sort(key=lambda x: -x[1]["s"])
    cnt, top = {}, []
    for ind, it in flat:
        if cnt.get(ind, 0) >= 2:
            continue
        top.append({**it, "ind": ind})
        cnt[ind] = cnt.get(ind, 0) + 1
        if len(top) >= TOP_N:
            break
    print(f"[q28] 最新一期 {cur['label']} 选出 {len(top)} 只，覆盖 {len(cnt)} 行业", flush=True)

    # 绩效表（perf_all 产出）
    T = pd.read_csv(os.path.join(OUT, "final_summary_15.csv"))
    summ = []
    for _, r in T.iterrows():
        summ.append({"k": r["组合"], "seg": r["区间"],
                     "cum": None if pd.isna(r["累计"]) else round(float(r["累计"]), 4),
                     "ann": None if pd.isna(r["年化"]) else round(float(r["年化"]), 4),
                     "vol": None if pd.isna(r["年化波动"]) else round(float(r["年化波动"]), 4),
                     "sh": None if pd.isna(r["夏普"]) else round(float(r["夏普"]), 3),
                     "dd": None if pd.isna(r["最大回撤"]) else round(float(r["最大回撤"]), 4),
                     "cal": None if pd.isna(r["卡玛"]) else round(float(r["卡玛"]), 3),
                     # 期数必须原样带出去：页面要写「N 期」，靠月份数除以 3 反推会在
                     # 首尾非整季时算错一期（141 个月 → 47 期，实际 48 期）
                     "n": None if pd.isna(r.get("期数")) else int(r["期数"]),
                     "end": str(r["期末"])[:10] if isinstance(r["期末"], str) else None})

    nav = pd.read_csv(os.path.join(OUT, "nav_all_15.csv"), index_col=0, parse_dates=True)
    # 列名对齐页面显示名（回测产出用短名）
    nav = nav.rename(columns={"CSFM": "CSFM(N=20, κ=1.5)", "TSFM": "TSFM(N=30, κ=1.0)",
                              "Q_v1": "质量Top28 v1", "Q_v2": "质量Top28 v2"})
    curve = {"dates": [d.strftime("%Y-%m-%d") for d in nav.index],
             "series": {c: [round(float(v), 4) for v in nav[c]] for c in nav.columns}}

    grid = pd.read_csv(os.path.join(OUT, "grid_cs_ts_15.csv"))
    grid = grid[grid["组合"].isin(["CSFM", "TSFM"])]
    # κ 敏感性：按 (组合, N, κ) 全量输出，页面自行取主导 N
    kap = [{"s": r["组合"], "n": int(r["N"]), "k": float(r["kappa"]),
            "vol": round(float(r["年化波动"]), 4), "ann": round(float(r["年化"]), 4),
            "sh": round(float(r["夏普"]), 3)} for _, r in grid.iterrows()]

    data = {"asof": cur["asof"], "label": cur["label"], "pools": pools, "summary": summ,
            "curve": curve, "q28": top, "kappa": kap,
            "pools_all": len(pools),
            # 回测区间不能直接用 curve.dates[0]：曲线的首点已经含了「首期收益」
            # （值 = 1 + r₁），所以真实起点是首点的前一个月。
            "meta": {"start": (nav.index[0] - pd.DateOffset(months=1)).strftime("%Y-%m"),
                     "end": nav.index[-1].strftime("%Y-%m"),
                     "n_months": int(len(nav)),
                     "n_quarters": int(pd.read_csv(os.path.join(OUT, "quality_ret_15.csv"))
                                       .shape[0])}}
    json.dump(data, open(os.path.join(OUT, "page_data.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"[saved] page_data.json {os.path.getsize(os.path.join(OUT, 'page_data.json'))/1e6:.2f} MB",
          flush=True)
    print(f"[summary] {len(summ)} 行；最新期 {cur['label']} {cur['n']} 只 {cur['nind']} 行业")


if __name__ == "__main__":
    main()
