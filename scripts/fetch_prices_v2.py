# -*- coding: utf-8 -*-
"""重拉股池个股全区间（2019-01-01 → 最新交易日）后复权日线（可靠版）。

上一版 fetch_prices_full.py 的两个坑：
  1. qfq 前复权把长期高分红个股的早年价格折成负数 → 改用 hfq 后复权；
  2. 限频降级到 batch=1 时，单只响应没有 code 列，行被写成空 code，
     事后靠顺序回填导致代码错配（523 只里仅 268 只起点在 2019 年初）。

本版对策：
  * 恒定 batch=2（实测 2 只 × 1877 个交易日可完整返回且带 code 列），
    限频只做退避重试，绝不降级到 1；
  * 每批回读响应中的 code 集合，必须等于请求集合，否则丢弃重试；
  * 每只单独记录行数，结束后输出覆盖度报告供人工确认。
"""
import csv
import json
import os
import subprocess
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE, WESTOCK as EXE, DATA  # noqa: E402  路径：本机 Windows 与云端 Linux 通用

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
OUT = os.path.join(DATA, "prices_full_v2.csv")
PROG = os.path.join(BASE, "data", "price_v2_progress.json")
START = "2019-01-01"
END = date.today().strftime("%Y-%m-%d")
BATCH = 2


def parse(txt):
    rows, hdr = [], None
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
        if len(cells) == len(hdr):
            rows.append(dict(zip(hdr, cells)))
    return rows


def main():
    codes = sorted(json.load(open(os.path.join(BASE, "scripts", "codes_pool.json"),
                                  encoding="utf-8")))
    prog = json.load(open(PROG, encoding="utf-8")) if os.path.exists(PROG) else {}
    done = set(prog.get("done", []))
    todo = [c for c in codes if c not in done]
    print(f"total={len(codes)} todo={len(todo)} range={START}..{END}", flush=True)

    exists = os.path.exists(OUT) and os.path.getsize(OUT) > 0
    f = open(OUT, "a", encoding="utf-8", newline="")
    w = None
    sleep_s = 4.0
    i, t0 = 0, time.time()
    while i < len(todo):
        chunk = todo[i:i + BATCH]
        try:
            r = subprocess.run([EXE, "kline", ",".join(chunk), "--period", "day",
                                "--start", START, "--end", END, "--fq", "hfq"],
                               capture_output=True, timeout=300)
            txt = r.stdout.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            txt = ""

        if "服务限频" in txt or not txt.strip():
            sleep_s = min(90.0, sleep_s * 1.6)
            print(f"[限频] sleep={sleep_s:.1f} done={len(done)}", flush=True)
            time.sleep(sleep_s)
            continue

        rows = parse(txt)
        by_code = {}
        for r_ in rows:
            c = r_.get("code")
            d = r_.get("date") or r_.get("Date")
            px = r_.get("last") or r_.get("close") or r_.get("Close")
            if not c or not d or not px:
                continue
            by_code.setdefault(c, []).append((d, px))

        # 校验：请求的代码必须都出现，且每只至少有 100 行
        if set(by_code) != set(chunk) or any(len(v) < 100 for v in by_code.values()):
            sleep_s = min(90.0, sleep_s * 1.3)
            print(f"[残缺] {chunk} got={{{', '.join(f'{k}:{len(v)}' for k, v in by_code.items())}}} "
                  f"sleep={sleep_s:.1f}", flush=True)
            time.sleep(sleep_s)
            continue

        if w is None:
            w = csv.DictWriter(f, fieldnames=["code", "date", "close"], extrasaction="ignore")
            if not exists:
                w.writeheader()
        for c, lst in by_code.items():
            for d, px in lst:
                w.writerow({"code": c, "date": d, "close": px})
        f.flush()

        done.update(chunk)
        prog["done"] = sorted(done)
        json.dump(prog, open(PROG, "w", encoding="utf-8"), ensure_ascii=False)

        rate = len(done) / max(1e-9, (time.time() - t0) / 60)
        print(f"[ok] done={len(done)}/{len(codes)} rate={rate:.1f}/min "
              f"eta={(len(codes) - len(done)) / max(1e-9, rate):.0f}min", flush=True)
        i += BATCH
        sleep_s = max(3.0, sleep_s * 0.9)
        time.sleep(sleep_s)
    f.close()
    print("DONE", len(done), flush=True)


if __name__ == "__main__":
    main()
