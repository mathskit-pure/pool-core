# -*- coding: utf-8 -*-
"""按「官方中证800 逐期成分 + 申万三级行业内 FAQ 前 5」生成每期股池。

这一步原先只在交互式会话里跑过、没有落成脚本，导致季度更新无法产出新一期池。
本文件把它固化下来，并保证：重跑一遍与线上正在用的
``period_pools_2015_2026.csv`` 完全一致（见 scripts/finchain/selftest.py）。

输入：
    FIN_D15/official_csi800_pit_2015.csv   官方成分逐期快照（build_pit_2015b.py）
    FIN_D15/faq_panel_2015.csv.gz          FAQ 全期评分面板（faq_engine_15.py）
输出：
    FIN_OUT/period_pools_2015_2026.csv     每期 800 只成分内按行业前 5 的池

口径要点：
  1. 时点对齐：只取 ``pd <= asof`` 的评分（pd = min(公告日, 法定披露截止日)）；
  2. 每只股票取「已披露的最新一期」，同一期不重复；
  3. 行业内按 FAQ_score 降序，取前 5（不足则全取）；
  4. 期序取 asof >= START_POOL，与回测起点一致。

用法：
    python scripts/finchain/build_pools.py
    python scripts/finchain/build_pools.py --check   # 只比对不覆盖
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402

os.makedirs(OUT, exist_ok=True)

START_POOL = "2015-01-01"
PER_IND = 5
OUTFILE = os.path.join(OUT, "period_pools_2015_2026.csv")


def norm6(s):
    return s.astype(str).str.strip().str[-6:].str.zfill(6)


def build():
    faq = pd.read_csv(os.path.join(D15, "faq_panel_2015.csv.gz"), dtype={"code": str},
                      low_memory=False)
    faq["code"] = norm6(faq["code"])
    faq["pd"] = pd.to_datetime(faq["pd"], errors="coerce")
    faq["EndDate"] = pd.to_datetime(faq["EndDate"], errors="coerce")
    faq = faq.dropna(subset=["pd", "FAQ_score"])
    print(f"[faq] {len(faq):,} 行 / {faq['code'].nunique()} 只 / "
          f"{faq['EndDate'].nunique()} 个报告期", flush=True)

    pit = pd.read_csv(os.path.join(D15, "official_csi800_pit_2015.csv"), dtype=str)
    pit["code"] = norm6(pit["code"])
    pit["asof"] = pd.to_datetime(pit["asof"], errors="coerce")
    pit = pit.dropna(subset=["asof"])
    print(f"[pit] {len(pit):,} 行 / {pit['asof'].nunique()} 期", flush=True)

    # 预先按 code 排好，逐期筛选更快
    faq = faq.sort_values(["code", "pd"], kind="mergesort")

    rows = []
    for asof, g in pit.groupby("asof", sort=True):
        if asof < pd.Timestamp(START_POOL):
            continue
        mem = set(g["code"])
        sub = faq[(faq["pd"] <= asof) & (faq["code"].isin(mem))]
        if sub.empty:
            print(f"  !! {asof:%Y-%m-%d} 无可用评分", flush=True)
            continue
        # 每只股票取已披露的最新一期
        sub = sub.groupby("code", sort=False).tail(1)
        # 行业内取前 5（稳定排序，分数相同时按代码，保证可复现）
        sub = sub.sort_values(["sw3", "FAQ_score", "code"],
                              ascending=[True, False, True], kind="mergesort")
        top = sub.groupby("sw3", sort=False).head(PER_IND).assign(asof=asof)
        rows.append(top[["asof", "code", "sw3", "FAQ_score", "FAQ_pct",
                         "EndDate", "pd"]])
        print(f"  {asof:%Y-%m-%d} 成分 {len(mem):4d} → 评分可用 {sub['code'].nunique():4d}"
              f" → 入池 {len(top):4d} 只 / {top['sw3'].nunique()} 行业", flush=True)

    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["asof", "sw3", "FAQ_score"],
                          ascending=[True, True, False], kind="mergesort")
    return out.reset_index(drop=True)


def main():
    out = build()
    print(f"\n[total] {out['asof'].nunique()} 期 / {len(out)} 行 / "
          f"{out['code'].nunique()} 只 / {out['sw3'].nunique()} 行业", flush=True)

    if "--check" in sys.argv:
        if not os.path.exists(OUTFILE):
            print("[check] 目标文件不存在，无从比对")
            return
        old = pd.read_csv(OUTFILE, dtype={"code": str})
        old["asof"] = pd.to_datetime(old["asof"])
        old["code"] = norm6(old["code"])
        new = out.copy()
        new["asof"] = pd.to_datetime(new["asof"])
        ko = {(a, c) for a, c in zip(old["asof"], old["code"])}
        kn = {(a, c) for a, c in zip(new["asof"], new["code"])}
        only_old, only_new = ko - kn, kn - ko
        print(f"[check] 旧 {len(ko)} 行 / 新 {len(kn)} 行；仅旧有 {len(only_old)}，仅新有 {len(only_new)}")
        if only_old:
            print("  仅旧有样例:", sorted(only_old)[:5])
        if only_new:
            print("  仅新有样例:", sorted(only_new)[:5])
        m = old.merge(new, on=["asof", "code"], suffixes=("_old", "_new"))
        if len(m):
            d = (m["FAQ_score_old"] - m["FAQ_score_new"]).abs()
            print(f"[check] 交集 {len(m)} 行，FAQ 分差 max={d.max():.6f} mean={d.mean():.6f}")
            bad = m.iloc[np.where(d > 1e-6)[0]]
            if len(bad):
                print(f"[check] 分数不一致 {len(bad)} 行，样例:")
                print(bad[["asof", "code", "FAQ_score_old", "FAQ_score_new"]].head(5).to_string())
        same = not only_old and not only_new
        print(f"[check] 结论：{'完全一致' if same else '存在差异（需核对口径）'}")
        return

    tmp = OUTFILE + ".tmp"
    out.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, OUTFILE)
    print(f"[saved] {OUTFILE} ({os.path.getsize(OUTFILE)/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
