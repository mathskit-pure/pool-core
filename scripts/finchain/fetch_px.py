# -*- coding: utf-8 -*-
"""抓取价格数据（腾讯 K 线，无需鉴权）。

用法:
    python scripts/finchain/fetch_px.py wk    # 全样本月线（不复权）→ mon/，用于真实市值
    python scripts/finchain/fetch_px.py day   # 日线（后复权）  → px/，用于回测

两者都是断点续跑：已存在且非空的文件直接跳过。
原 qmj_fraud/src/s3_px.py，唯一改动是路径走 paths.py。
"""
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_MON, FIN_PX, FIN_ROOT  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from em import tencent_kline  # noqa: E402

START = "2008-01-01"
END = "2026-10-16"


def tcode(c):
    if c[0] in "69":
        return "sh" + c
    if c[:2] in ("60", "68", "90"):
        return "sh" + c
    if c[:2] in ("00", "30", "20"):
        return "sz" + c
    return None


def load_codes(argv):
    """优先用命令行给的清单文件，其次 FIN_ROOT/codes.csv（fetch_fund 产出）。"""
    if len(argv) > 2:
        fp = argv[2]
    else:
        fp = os.path.join(FIN_ROOT, "codes.csv")
    with open(fp, encoding="utf-8-sig") as f:
        return [r["code"] for r in csv.DictReader(f)]


def fetch(mode, codes):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    sub = FIN_MON if mode == "wk" else FIN_PX
    period = "month" if mode == "wk" else "day"
    adj = "" if mode == "wk" else "hfq"
    os.makedirs(sub, exist_ok=True)
    todo = []
    for c in codes:
        fp = os.path.join(sub, c + ".csv")
        if os.path.exists(fp) and os.path.getsize(fp) > 40:
            continue
        if tcode(c):
            todo.append(c)
    print("codes %d / todo %d / -> %s" % (len(codes), len(todo), sub), flush=True)
    t0 = time.time()
    done = [0]

    def work(c):
        tc = tcode(c)
        try:
            rows = tencent_kline(tc, period=period, start=START, end=END, adj=adj, count=800)
        except Exception:
            rows = []
        fp = os.path.join(sub, c + ".csv")
        tmp = fp + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "close", "high", "low", "volume"])
            for r in rows:
                if len(r) >= 6:
                    w.writerow(r[:6])
        os.replace(tmp, fp)
        return len(rows)

    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(work, c): c for c in todo}
        for fu in as_completed(futs):
            done[0] += 1
            if done[0] % 300 == 0:
                print("  %s %d/%d %.0fs" % (mode, done[0], len(todo), time.time() - t0), flush=True)
    print("DONE", mode, done[0], "%.0fs" % (time.time() - t0), flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "wk"
    fetch(mode, load_codes(sys.argv))
