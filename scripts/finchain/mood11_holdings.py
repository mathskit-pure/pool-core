# -*- coding: utf-8 -*-
"""导出最近 N 期 Q28 持仓明细，供研报情绪研究取数用。

持仓来自 scenario_cov.picks_q28()，与页面 / 回测同一套规则：
股池 → FAQ 降序取 28 只候选（单申万三级 ≤2）→ 三道筛 → 反比加权 2%~8%。
"""
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from paths import DATA  # noqa: E402
from scenario_cov import load_inputs, picks_q28  # noqa: E402

N = 11
OUT_CSV = os.path.join(DATA, "mood11_holdings.csv")


def main():
    D = load_inputs()
    reb = picks_q28(D, verbose="Q28")
    dates = sorted(reb)[-N:]
    rows = []
    for i, d in enumerate(dates):
        w = reb[d]
        asof = [a for a in sorted(D["pools"]) if pd.Timestamp(a) < d]
        asof = asof[-1] if asof else ""
        for c, ww in w.items():
            rows.append({"period": i + 1, "asof": asof,
                         "rebal_date": d.strftime("%Y-%m-%d"),
                         "code": c, "weight": round(float(ww) * 100, 2)})
    df = pd.DataFrame(rows)

    # 股票名称从股池带过来
    nm = {}
    for a, g in D["pools"].items():
        for _, r in g.iterrows():
            if pd.notna(r.get("name")):
                nm.setdefault(str(r["code"]).zfill(6), str(r["name"]))
    df["name"] = df["code"].map(nm).fillna("")
    df = df[["period", "asof", "rebal_date", "code", "name", "weight"]]
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print(f"期数 {len(dates)}：{dates[0].date()} ~ {dates[-1].date()}")
    print(f"持仓记录 {len(df)} 条 · 唯一股票 {df['code'].nunique()} 只")
    print(df.groupby("rebal_date").agg(只数=("code", "size"),
                                       权重和=("weight", "sum")).to_string())
    # 重复持有次数分布
    cnt = df.groupby("code").size().sort_values(ascending=False)
    print("\n重复持有次数分布：", dict(cnt.value_counts().sort_index()))
    print(f"→ {OUT_CSV}")


if __name__ == "__main__":
    main()
