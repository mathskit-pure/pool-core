# -*- coding: utf-8 -*-
"""按年分段补拉 prices_full_v2.csv 的缺失区间。

背景：westock kline 对「单只 × 7 年」的请求会偶发截断（返回 140~250 行的一段），
且全区间重抓的成功率只有约 24%（第 1 轮 392 只只修好 95 只）。改为按年分段后，
单次请求约 240 行，实测可稳定完整返回。

安全性：已验证 hfq 的复权锚点不随请求区间变化 —— 同一只票在「2020 单年」、
「2019-2020」和「2019-2026」三种请求下，2020-06-30 的收盘价完全相同（98.51），
因此按年取回的数据可直接拼接，不产生接缝跳空。

迭代策略：「当年未上市」与「响应被截断」在单次请求里无法可靠区分（前者年末有
数据、起点晚，后者形态随机），因此判据放宽为「返回非空即写入」，由多轮迭代收敛。
"""
import json
import os
import subprocess
import sys
import time
from datetime import date

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
EXE = r"C:\Users\12066\.local\bin\westock.exe"
BASE = r"C:\Users\12066\WorkBuddy\2026-10-05-23-13-30"
SRC = os.path.join(BASE, "data", "prices_full_v2.csv")
YEARS = list(range(2019, date.today().year + 1))
BATCH = 4        # 实测 4 只 × 1 年（约 970 行）可完整返回，再大会被截断
ROUNDS = 5


def parse(txt, fallback=None):
    """批量响应含 code 列；单只响应没有，用 fallback（请求对象）回填。
    返回 {code: [(date, close)]}"""
    out, hdr = {}, None
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if hdr is None:
            hdr = cells
            continue
        if set("".join(cells)) <= set("- :"):
            continue
        if len(cells) != len(hdr):
            continue
        r = dict(zip(hdr, cells))
        c = r.get("code") or fallback
        d = r.get("date") or r.get("Date")
        px = r.get("last") or r.get("close") or r.get("Close")
        if c and d and px:
            out.setdefault(c, []).append((d, px))
    return out


def compute_need(df, per_year, all_dates, first_asof, latest):
    """待补判定：以「该票首个数据日 → 当年末」的应有交易日数为分母。

    直接拿全年交易日做分母会把「当年才上市」的票误判为缺失（它只交易了半年），
    导致年年重试却永远补不满，掩盖了真正的缺口。
    """
    cnt = df.assign(y=df["date"].str[:4].astype(int)).groupby(["code", "y"]).size().to_dict()
    first = df.groupby("code")["date"].min().to_dict()
    need = {}
    for c in df["code"].unique():
        f = first.get(c, latest)
        ys = []
        for y in YEARS:
            y_from = max(f, f"{y}-01-01")
            y_to = f"{y}-12-31"
            if y_from > y_to:
                continue
            expect = int(((all_dates >= y_from) & (all_dates <= y_to)).sum())
            if expect == 0:
                continue
            got = cnt.get((c, y), 0) or 0
            if got < expect * 0.95:
                ys.append(y)
        if ys:
            need[c] = ys
    return need


def main():
    df = pd.read_csv(SRC, dtype={"code": str})
    df = df.dropna(subset=["close"]).drop_duplicates(["code", "date"])
    latest = df["date"].max()
    print(f"现有 {len(df)} 行 / {df['code'].nunique()} 只 · 最新 {latest}", flush=True)

    all_dates = pd.Index(sorted(df["date"].unique()))
    per_year = {y: int(((all_dates >= f"{y}-01-01") & (all_dates <= f"{y}-12-31")).sum())
                for y in YEARS}
    print("各年交易日数:", {y: per_year[y] for y in YEARS}, flush=True)

    pools = json.load(open(os.path.join(BASE, "data", "pools.json"), encoding="utf-8"))
    first_asof = {}
    for per, v in pools.items():
        a = v.get("asof")
        if not a:
            continue
        for m in v["members"]:
            c = m["code"]
            if c not in first_asof or a < first_asof[c]:
                first_asof[c] = a

    sleep_s, t0 = 4.0, time.time()
    for rnd in range(1, ROUNDS + 1):
        need = compute_need(df, per_year, all_dates, first_asof, latest)
        total = sum(len(v) for v in need.values())
        if not need:
            print("\n全部补齐，提前结束", flush=True)
            break
        print(f"\n===== 第 {rnd} 轮 · 待补 {len(need)} 只 / {total} 个「票×年」 =====",
              flush=True)
        n_done = 0
        for y in YEARS:
            codes = [c for c, ys in need.items() if y in ys]
            if not codes:
                continue
            print(f"── {y} 年 · {len(codes)} 只 ──", flush=True)
            start, end = f"{y}-01-01", f"{y}-12-31"
            from collections import deque
            queue = deque(codes)
            fails = {}
            while queue:
                chunk = [queue.popleft() for _ in range(min(BATCH, len(queue)))]
                try:
                    r = subprocess.run([EXE, "kline", ",".join(chunk), "--period", "day",
                                        "--start", start, "--end", end, "--fq", "hfq"],
                                       capture_output=True, timeout=300)
                    txt = r.stdout.decode("utf-8", errors="replace")
                except subprocess.TimeoutExpired:
                    txt = ""
                if "服务限频" in txt or not txt.strip():
                    sleep_s = min(60.0, sleep_s * 1.5)
                    print(f"  [限频] sleep={sleep_s:.1f}", flush=True)
                    time.sleep(sleep_s)
                    for c in chunk:            # 整批退回重试
                        queue.append(c)
                    continue
                got = parse(txt, fallback=chunk[0] if len(chunk) == 1 else None)
                new = []
                for c, rows in got.items():
                    for d, px in rows:
                        new.append({"code": c, "date": d, "close": px})
                if new:
                    nd = pd.DataFrame(new)
                    nd["close"] = pd.to_numeric(nd["close"], errors="coerce")
                    nd = nd.dropna(subset=["close"])
                    df = pd.concat([df, nd], ignore_index=True) \
                           .drop_duplicates(["code", "date"])
                # 批量响应会漏票：对未返回的代码单独重试，最多 3 次
                missing = [c for c in chunk if c not in got]
                for c in missing:
                    fails[c] = fails.get(c, 0) + 1
                    if fails[c] <= 3:
                        queue.append(c)
                    else:
                        print(f"  [无数据] {c} {y} 年重试 {fails[c]} 次仍为空", flush=True)
                n_done += 1
                if n_done % 50 == 0:
                    df.to_csv(SRC, index=False, encoding="utf-8")
                    print(f"  本轮 {n_done}/{total}", flush=True)
                if n_done > total * 6:          # 防死循环
                    print(f"  [中止] {y} 年重试次数超限", flush=True)
                    break
                sleep_s = max(3.5, sleep_s * 0.92)
                time.sleep(sleep_s)
        df.to_csv(SRC, index=False, encoding="utf-8")
        print(f"  第 {rnd} 轮结束 · 现有 {len(df)} 行", flush=True)

    df = df.sort_values(["code", "date"]).reset_index(drop=True)
    df.to_csv(SRC, index=False, encoding="utf-8")
    g = df.groupby("code")["date"].agg(["count", "min", "max"])
    print(f"\n最终 {len(df)} 行 / {len(g)} 只 · n_full={int(g['count'].max())}", flush=True)
    print(f"终点覆盖最新日: {int((g['max'] >= latest).sum())}/{len(g)}", flush=True)
    rem = compute_need(df, per_year, all_dates, first_asof, latest)
    print(f"仍未补齐: {len(rem)} 只 / {sum(len(v) for v in rem.values())} 个「票×年」", flush=True)
    for c in list(rem)[:15]:
        print("  ", c, rem[c], f"(现有 {g.loc[c,'min']} → {g.loc[c,'max']}, {g.loc[c,'count']} 行)",
              flush=True)


if __name__ == "__main__":
    main()
