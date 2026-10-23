# -*- coding: utf-8 -*-
"""mood11_corr 的稳健性检验：剔除极值、分档、口径对照。"""
import os
import sys

import pandas as pd
from scipy.stats import pearsonr, spearmanr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
from paths import DATA  # noqa: E402

pd.set_option("display.width", 200)


def main():
    d = pd.read_csv(os.path.join(DATA, "mood11_corr.csv"), dtype={"code": str})
    d["code"] = d["code"].str.zfill(6)

    print("=== 1) 剔除 3 只最大跌幅后是否仍成立 ===")
    bad = d.nsmallest(3, "ret")
    print("  剔除：" + "、".join(f"{r['name']}({r['ret']:.1f}%)" for _, r in bad.iterrows()))
    d2 = d[~d["code"].isin(bad["code"])]
    for x, lab in [("pre_cnt", "机构家数"), ("up_mood", "目标价隐含(研报)"),
                   ("up_cons", "目标价隐含(一致)")]:
        s = d2[[x, "ret"]].dropna()
        if len(s) < 6:
            continue
        r, p = pearsonr(s[x], s["ret"])
        sr, sp = spearmanr(s[x], s["ret"])
        print(f"  {lab:20s} n={len(s):2d}  r={r:+.3f}(p={p:.3f})  rho={sr:+.3f}(p={sp:.3f})")

    print("\n=== 2) 机构家数分档收益 ===")
    d["档"] = pd.cut(d["pre_cnt"], [-1, 0, 2, 5, 100],
                     labels=["0家", "1-2家", "3-5家", "6家以上"])
    print(d.groupby("档", observed=True)["ret"].agg(["size", "mean", "median"]).round(2).to_string())

    print("\n=== 3) 目标价隐含涨幅分档收益（一致预期口径）===")
    d["档2"] = pd.cut(d["up_cons"], [-100, 20, 35, 60, 10000],
                      labels=["<20%", "20-35%", "35-60%", ">60%"])
    print(d.groupby("档2", observed=True)["ret"].agg(["size", "mean", "median"]).round(2).to_string())

    print("\n=== 4) 情绪分级 × 机构家数 ===")
    print(d.pivot_table(index="mood_cls", columns="pre_cnt", values="ret",
                        aggfunc="count").fillna(0).astype(int).to_string())

    print("\n=== 5) 全样本明细 ===")
    cols = ["code", "name", "weight", "pre_cnt", "pre_months", "ret",
            "up_mood", "up_cons", "mood_cls"]
    print(d[cols].round(2).to_string(index=False))

    print("\n=== 6) 描述统计 ===")
    print(f"  机构家数：min={d['pre_cnt'].min():.0f} 中位={d['pre_cnt'].median():.0f} "
          f"max={d['pre_cnt'].max():.0f} 零覆盖={(d['pre_cnt'] == 0).sum()} 只")
    print(f"  研报目标价隐含涨幅中位 {d['up_mood'].median():+.1f}%，"
          f"实际收益中位 {d['ret'].median():+.1f}%")


if __name__ == "__main__":
    main()
