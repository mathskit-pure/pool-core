# -*- coding: utf-8 -*-
"""修复 prices_full.csv 中缺失 code 的行。

成因：westock kline 单只请求返回的表没有 code 列，而脚本按 `r_.get("code")` 取值，
导致 batch=1 抓取的 534 个代码块 code 为空。

恢复方法：批量响应是按代码分组连续输出的，因此文件里每个代码的记录是一段日期
递减的连续块；块的出现顺序与抓取顺序（codes_pool.json 的升序）一致，前 26 个
带 code 的块可直接对齐。逐块回填后再用「hfq/qfq 比值恒定」做校验。
"""
import json
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = r"C:\Users\12066\WorkBuddy\2026-10-05-23-13-30"
SRC = os.path.join(BASE, "data", "prices_full.csv")
QFX = os.path.join(BASE, "data", "prices.csv")        # 已验证完整的 qfq 数据（校验基准）
OUT = os.path.join(BASE, "data", "prices_full_fixed.csv")


def split_blocks(dates):
    """日期递减为同一块；出现回升即新块。返回 (start, end) 左闭右开。"""
    blocks, s = [], 0
    prev = None
    for i, d in enumerate(dates):
        if prev is not None and d > prev:
            blocks.append((s, i))
            s = i
        prev = d
    blocks.append((s, len(dates)))
    return blocks


def main():
    d = pd.read_csv(SRC, dtype=str)
    n_raw = len(d)
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d = d.dropna(subset=["date", "close"]).reset_index(drop=True)
    dates = list(d["date"])
    blocks = split_blocks(dates)
    print(f"rows={n_raw} kept={len(d)} blocks={len(blocks)}")

    pool = json.load(open(os.path.join(BASE, "scripts", "codes_pool.json"), encoding="utf-8"))
    pool = sorted(pool)
    print("codes_pool:", len(pool))

    labeled = [c for c in d["code"].dropna().unique()]
    labeled_set = set(labeled)
    # 前若干块带 code，按出现顺序即为已标注代码序列；其后按 codes_pool 升序剩余部分顺序回填
    lab_order = []
    seen = set()
    for c in d["code"]:
        if isinstance(c, str) and c not in seen:
            seen.add(c)
            lab_order.append(c)
    print("labeled blocks:", len(lab_order))

    rest = [c for c in pool if c not in labeled_set]
    assign = []
    idx = 0
    for c in lab_order:
        assign.append(c)
    for (s, e) in blocks[len(lab_order):]:
        assign.append(rest[idx] if idx < len(rest) else None)
        idx += 1
    print("assign:", len(assign), "unassigned:", sum(1 for a in assign if a is None))

    codes = [None] * len(d)
    for (s, e), c in zip(blocks, assign):
        for i in range(s, e):
            codes[i] = c
    d["code"] = codes
    bad = d["code"].isna().sum()
    print("rows without code after fix:", int(bad))
    if bad:
        raise SystemExit("回填失败")

    # ── 校验：hfq/qfq 在同一代码上应为常数 ──────────────────────────────
    q = pd.read_csv(QFX, dtype={"code": str})
    q["close"] = pd.to_numeric(q["close"], errors="coerce")
    q = q.dropna(subset=["close"]).drop_duplicates(["code", "date"])
    qmap = {c: g.set_index("date")["close"] for c, g in q.groupby("code")}

    prob = []
    for c, g in d.groupby("code"):
        qs = qmap.get(c)
        if qs is None:
            prob.append((c, "no-qfq", None))
            continue
        s = g.set_index("date")["close"]
        # qfq 基准：2019-2023 段锚在 2023-12-31、2024+ 段锚在 2026-09-30，
        # 只有 2024+ 段与本次 hfq 同锚，比值才是常数 → 只取该段校验
        common = s.index.intersection(qs.index)
        common = [x for x in common if x >= "2024-01-02"]
        if len(common) < 100:
            prob.append((c, "few-overlap", len(common)))
            continue
        ratio = s.loc[common] / qs.loc[common]
        ratio = ratio[(ratio > 0) & ratio.notna()]
        if len(ratio) < 100:
            prob.append((c, "bad-ratio", len(ratio)))
            continue
        cv = float(ratio.std(ddof=0) / ratio.mean())
        if cv > 0.02:
            prob.append((c, f"cv={cv:.4f}", len(ratio)))
    print("\n校验异常代码数:", len(prob))
    for p in prob[:40]:
        print("  ", p)

    d = d[["code", "date", "close"]].drop_duplicates(["code", "date"])
    d = d.sort_values(["code", "date"]).reset_index(drop=True)
    d.to_csv(OUT, index=False, encoding="utf-8")
    miss = sorted(set(pool) - set(d["code"].unique()))
    print("\n缺失代码:", len(miss), miss)
    json.dump(miss, open(os.path.join(BASE, "scripts", "codes_missing.json"), "w",
                         encoding="utf-8"), ensure_ascii=False)
    g = d.groupby("code")["date"].agg(["count", "min", "max"])
    print("\nwritten:", OUT, d.shape)
    print("codes:", len(g), "| n_full:", int(g["count"].max()))


if __name__ == "__main__":
    main()
