# -*- coding: utf-8 -*-
"""研报情绪 / 目标价 与 后续股价 的相关性检验。

范围与边界（务必先读）：
  数据源只能回溯 5~6 个月的「月度评级分布」，且只有当前时点的一致目标价快照。
  所以「最近 11 期逐期研报」拿不到，唯一能做干净检验的是**当前这一期**：
  调仓日 2026-09-02，调仓前 3 个月 = 2026-06 ~ 2026-08（评级数据覆盖），
  结果变量 = 建仓后至 2026-10-16 的复权收益。

输出：data/mood11_corr.csv（明细）、data/mood11_corr.json（统计量）
"""
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from paths import DATA, FIN_D15 as D15  # noqa: E402

REBAL = pd.Timestamp("2026-09-02")
PRE_MONTHS = ("202606", "202607", "202608")      # 调仓前 3 个月
POST_MONTHS = ("202609", "202610")               # 建仓后至今


def load_ret():
    px = pd.read_pickle(os.path.join(D15, "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    R = px.pivot(index="date", columns="code", values="ret").sort_index()
    seg = R.loc[R.index > REBAL]
    cum = (1 + seg.fillna(0)).cumprod().iloc[-1] - 1
    return cum, R.index[-1]


def main():
    mood = json.load(open(os.path.join(DATA, "mood_q28.json"), encoding="utf-8"))
    rat = json.load(open(os.path.join(DATA, "ratings19.json"), encoding="utf-8"))["rows"]
    rm = {r["code"]: r for r in rat}
    cum, last_day = load_ret()

    rows = []
    for r in mood["rows"]:
        c = r["code"]
        g = rm.get(c, {"tp_cons": None, "m": {}})
        m = g["m"]
        pre_cnt = sum(m.get(k, 0) for k in PRE_MONTHS)
        post_cnt = sum(m.get(k, 0) for k in POST_MONTHS)
        nm = sum(1 for k in PRE_MONTHS if m.get(k, 0) > 0)
        tp_mid = (r["tp_lo"] + r["tp_hi"]) / 2 if r["tp_lo"] else np.nan
        up_mood = (tp_mid / r["price"] - 1) * 100 if np.isfinite(tp_mid) else np.nan
        up_cons = (g["tp_cons"] / r["price"] - 1) * 100 if g["tp_cons"] else np.nan
        rows.append(dict(code=c, name=r["name"], weight=r["weight"],
                         ret=float(cum.get(c, np.nan)) * 100,
                         pre_cnt=pre_cnt, post_cnt=post_cnt, pre_months=nm,
                         tp_mid=tp_mid, up_mood=up_mood, up_cons=up_cons,
                         mood_cls=r["mood_cls"], mood_level=r["mood_level"]))
    d = pd.DataFrame(rows)
    d.to_csv(os.path.join(DATA, "mood11_corr.csv"), index=False, encoding="utf-8-sig")

    print(f"窗口：{REBAL.date()} → {last_day.date()}   样本 {len(d)} 只")
    print(f"等权平均收益 {d['ret'].mean():+.2f}%   中位 {d['ret'].median():+.2f}%   "
          f"正收益 {(d['ret'] > 0).sum()}/{len(d)}")

    def cor(x, y, label, n_min=8):
        s = pd.DataFrame({"x": x, "y": y}).replace([np.inf, -np.inf], np.nan).dropna()
        if len(s) < n_min:
            print(f"  {label:24s} 样本 {len(s)} 不足，跳过")
            return None
        pr, pp = pearsonr(s["x"], s["y"])
        sr, sp = spearmanr(s["x"], s["y"])
        print(f"  {label:24s} n={len(s):3d}  pearson r={pr:+.3f}(p={pp:.3f})  "
              f"spearman ρ={sr:+.3f}(p={sp:.3f})")
        return dict(label=label, n=int(len(s)), pearson=float(pr), p_pearson=float(pp),
                    spearman=float(sr), p_spearman=float(sp))

    print("\n相关性（x = 调仓前已知信息，y = 建仓后收益）")
    stats = []
    for x, lab in [(d["pre_cnt"], "调仓前3月机构家数"),
                   (d["pre_months"], "调仓前3月有覆盖月数"),
                   (d["up_mood"], "目标价隐含涨幅(研报原文)"),
                   (d["up_cons"], "目标价隐含涨幅(一致预期)")]:
        s = cor(x, d["ret"], lab)
        if s:
            stats.append(s)

    print("\n情绪分级（人工读研报正文）分组收益")
    grp = d.groupby("mood_cls")["ret"].agg(["size", "mean", "median"]).round(2)
    print(grp.to_string())

    print("\n零覆盖 vs 有覆盖")
    cov = d.assign(has=d["pre_cnt"] > 0).groupby("has")["ret"].agg(["size", "mean", "median"]).round(2)
    cov.index = ["零覆盖" if not i else "有覆盖" for i in cov.index]
    print(cov.to_string())

    print("\n目标价兑现情况")
    u = d["up_mood"].dropna()
    print(f"  研报目标价平均隐含涨幅 {u.mean():+.1f}%（中位 {u.median():+.1f}%，n={len(u)}）")
    print(f"  同期实际收益          {d['ret'].mean():+.1f}%")
    print(f"  兑现率（实际/隐含）   {d['ret'].mean() / u.mean() * 100:+.0f}%")
    print(f"  目标价跑输幅度        {d['ret'].mean() - u.mean():+.1f}pp")

    json.dump({"window": [str(REBAL.date()), str(last_day.date())], "n": int(len(d)),
               "mean_ret": float(d["ret"].mean()), "median_ret": float(d["ret"].median()),
               "corr": stats,
               "group": {k: {kk: float(vv) for kk, vv in v.items()}
                         for k, v in grp.to_dict("index").items()},
               "tp_implied_mean": float(u.mean())},
              open(os.path.join(DATA, "mood11_corr.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n→ {os.path.join(DATA, 'mood11_corr.csv')}")


if __name__ == "__main__":
    main()
