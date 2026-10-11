# -*- coding: utf-8 -*-
"""合并 2019-2023 补拉行情与 2024 年至今行情，按 (code, date) 去重后回写 prices.csv。"""
import os
import sys
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = r"C:\Users\12066\WorkBuddy\2026-10-05-23-13-30"


def main():
    cur = pd.read_csv(os.path.join(BASE, "data", "prices.csv"), dtype={"code": str})
    hist = pd.read_csv(os.path.join(BASE, "data", "prices_hist.csv"), dtype={"code": str})
    print("现有:", cur.shape, cur["date"].min(), "→", cur["date"].max())
    print("补拉:", hist.shape, hist["date"].min(), "→", hist["date"].max())
    allp = pd.concat([hist, cur], ignore_index=True)
    allp = allp.dropna(subset=["code", "date", "close"])
    allp = allp.drop_duplicates(subset=["code", "date"], keep="last")
    allp = allp.sort_values(["code", "date"]).reset_index(drop=True)
    allp.to_csv(os.path.join(BASE, "data", "prices.csv"), index=False, encoding="utf-8")

    g = allp.groupby("code")["date"].agg(["count", "min", "max"])
    n_full = int(g["count"].max())
    short = g[g["count"] < n_full * 0.99]
    print("合并后:", allp.shape, "| 覆盖完整:", n_full, "条 | 覆盖不足:", len(short))
    if len(short):
        print(short.sort_values("count").head(30).to_string())


if __name__ == "__main__":
    main()
