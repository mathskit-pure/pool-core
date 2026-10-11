# -*- coding: utf-8 -*-
"""修补 prices_full_v2.csv 中被接口截断的个股。

成因：批量响应偶发截断（典型形态是只返回最早的 140 个交易日），而抓取脚本的
「每只 >=100 行」校验太宽松，把截断结果当成了完整数据放行。判据改为两条硬指标：
  1) 终点必须覆盖到全局最新交易日；
  2) 起点必须早于该股首次进入股池的信息可得日（否则动量窗口无法计算）。

修复方式：单只请求并显式回填 code（单只响应没有 code 列，但请求对象已知，
不会重演 batch=1 时代码错配的问题）。
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
START = "2019-01-01"
END = date.today().strftime("%Y-%m-%d")
MAX_ROUND = 4


def parse(txt, code):
    """单只响应没有 code 列，用请求对象回填。返回 [(date, close)]。"""
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


def main():
    df = pd.read_csv(SRC, dtype={"code": str})
    df = df.dropna(subset=["close"]).drop_duplicates(["code", "date"])
    latest = df["date"].max()
    print(f"现有 {len(df)} 行 / {df['code'].nunique()} 只 · 最新交易日 {latest}", flush=True)

    # 每只票首次进入股池的信息可得日 → 起点必须早于它
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

    g = df.groupby("code")["date"].agg(["count", "min", "max"])
    need_start = pd.Series({c: min(first_asof.get(c, "2019-05-01"), "2019-05-01")
                            for c in g.index})
    bad = g.index[(g["max"] < latest) | (g["min"] > need_start)].tolist()
    print(f"待修补 {len(bad)} 只", flush=True)

    sleep_s = 4.0
    t0 = time.time()
    for rnd in range(1, MAX_ROUND + 1):
        if not bad:
            break
        print(f"\n── 第 {rnd} 轮 · 剩余 {len(bad)} ──", flush=True)
        still = []
        for i, code in enumerate(bad):
            try:
                r = subprocess.run([EXE, "kline", code, "--period", "day",
                                    "--start", START, "--end", END, "--fq", "hfq"],
                                   capture_output=True, timeout=300)
                txt = r.stdout.decode("utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                txt = ""
            if "服务限频" in txt or not txt.strip():
                sleep_s = min(60.0, sleep_s * 1.5)
                print(f"  [限频] sleep={sleep_s:.1f}", flush=True)
                time.sleep(sleep_s)
                still.append(code)
                continue
            rows = parse(txt, code)
            if len(rows) < 100:
                still.append(code)
                continue
            new = pd.DataFrame(rows, columns=["code", "date", "close"])
            new["close"] = pd.to_numeric(new["close"], errors="coerce")
            new = new.dropna(subset=["close"])
            old = df[df["code"] == code]
            # 仅在更完整时替换
            if len(new) > len(old) or (len(new) == len(old) and new["date"].max() > old["date"].max()):
                df = df[df["code"] != code]
                df = pd.concat([df, new], ignore_index=True)
            df = df.drop_duplicates(["code", "date"])
            if (i + 1) % 20 == 0:
                rate = (i + 1) / max(1e-9, (time.time() - t0) / 60)
                print(f"  进度 {i + 1}/{len(bad)} rate={rate:.1f}/min", flush=True)
            sleep_s = max(3.0, sleep_s * 0.92)
            time.sleep(sleep_s)

        df.to_csv(SRC, index=False, encoding="utf-8")
        g = df.groupby("code")["date"].agg(["count", "min", "max"])
        need_start = pd.Series({c: min(first_asof.get(c, "2019-05-01"), "2019-05-01")
                                for c in g.index})
        bad = g.index[(g["max"] < latest) | (g["min"] > need_start)].tolist()
        print(f"  第 {rnd} 轮后仍不完整: {len(bad)}", flush=True)

    df = df.sort_values(["code", "date"]).reset_index(drop=True)
    df.to_csv(SRC, index=False, encoding="utf-8")
    g = df.groupby("code")["date"].agg(["count", "min", "max"])
    print(f"\n最终 {len(df)} 行 / {len(g)} 只 · n_full={int(g['count'].max())}", flush=True)
    print(f"终点覆盖最新日: {int((g['max'] >= latest).sum())}/{len(g)}", flush=True)
    print(f"起点满足要求:   {int((g['min'] <= need_start).sum())}/{len(g)}", flush=True)
    print(f"仍不完整: {len(bad)} {bad[:20]}", flush=True)


if __name__ == "__main__":
    main()
