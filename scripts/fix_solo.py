# -*- coding: utf-8 -*-
"""对按年补拉的"顽固缺口"改用单只请求兜底。

现象：westock kline 的批量响应会确定性漏掉部分代码 —— 4 只一起请求时，这 109 只票
（上汽、恒瑞、白云山等大票）在 2026 年始终返回空，但单独请求同一只票、同一区间
可以完整返回 183 行。因此批量重试多少次都补不上，必须走单只请求。

单只响应没有 code 列，用请求对象显式回填（parse 的 fallback 参数）。
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
TODAY = date.today().strftime("%Y-%m-%d")


def parse(txt, code):
    out, hdr = [], None
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
        d = r.get("date") or r.get("Date")
        px = r.get("last") or r.get("close") or r.get("Close")
        if d and px:
            out.append((code, d, px))
    return out


def compute_need(df, all_dates, latest):
    cnt = df.assign(y=df["date"].str[:4].astype(int)).groupby(["code", "y"]).size().to_dict()
    first = df.groupby("code")["date"].min().to_dict()
    need = {}
    for c in df["code"].unique():
        f = first.get(c, latest)
        ys = []
        for y in YEARS:
            y_from = max(f, f"{y}-01-01")
            if y_from > f"{y}-12-31":
                continue
            expect = int(((all_dates >= y_from) & (all_dates <= f"{y}-12-31")).sum())
            got = cnt.get((c, y), 0) or 0
            if expect and got < expect * 0.95:
                ys.append(y)
        if ys:
            need[c] = ys
    return need


def main():
    df = pd.read_csv(SRC, dtype={"code": str})
    df = df.dropna(subset=["close"]).drop_duplicates(["code", "date"])
    all_dates = pd.Index(sorted(df["date"].unique()))
    latest = all_dates[-1]
    print(f"现有 {len(df)} 行 / {df['code'].nunique()} 只 · 最新 {latest}", flush=True)

    need = compute_need(df, all_dates, latest)
    total = sum(len(v) for v in need.values())
    print(f"待补 {len(need)} 只 / {total} 个「票×年」", flush=True)
    if not need:
        return

    sleep_s, t0 = 4.0, time.time()
    n = 0
    for y in YEARS:
        codes = [c for c, ys in need.items() if y in ys]
        if not codes:
            continue
        print(f"\n── {y} 年 · 单只补 {len(codes)} 只 ──", flush=True)
        for code in codes:
            try:
                # 结束日不能是未来：对当年请求 --end 2026-12-31 接口会直接返回空，
                # 必须截到今天（这也是 2026 年数据一直补不上的真正原因）
                r = subprocess.run([EXE, "kline", code, "--period", "day",
                                    "--start", f"{y}-01-01",
                                    "--end", min(f"{y}-12-31", TODAY),
                                    "--fq", "hfq"], capture_output=True, timeout=300)
                txt = r.stdout.decode("utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                txt = ""
            if "服务限频" in txt or not txt.strip():
                sleep_s = min(45.0, sleep_s * 1.5)
                print(f"  [限频] {code} sleep={sleep_s:.1f}", flush=True)
                time.sleep(sleep_s)
                continue
            rows = parse(txt, code)
            if rows:
                nd = pd.DataFrame(rows, columns=["code", "date", "close"])
                nd["close"] = pd.to_numeric(nd["close"], errors="coerce")
                nd = nd.dropna(subset=["close"])
                df = pd.concat([df, nd], ignore_index=True) \
                       .drop_duplicates(["code", "date"])
            n += 1
            if n % 20 == 0:
                df.to_csv(SRC, index=False, encoding="utf-8")
                print(f"  进度 {n}/{total} · 现有 {len(df)} 行", flush=True)
            sleep_s = max(3.5, sleep_s * 0.94)
            time.sleep(sleep_s)

    df = df.sort_values(["code", "date"]).reset_index(drop=True)
    df.to_csv(SRC, index=False, encoding="utf-8")
    rem = compute_need(df, all_dates, latest)
    print(f"\n最终 {len(df)} 行 / {df['code'].nunique()} 只", flush=True)
    print(f"仍未补齐 {len(rem)} 只 / {sum(len(v) for v in rem.values())} 个「票×年」",
          flush=True)
    for c in list(rem)[:15]:
        print("  ", c, rem[c], flush=True)


if __name__ == "__main__":
    main()
