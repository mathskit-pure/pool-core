# -*- coding: utf-8 -*-
"""拉取官方成分并集 1578 只的「不复权收盘价」（单日基准），用于还原真实价格与市值。

用法：得到 price_scale = 后复权价 / 不复权价，历史真实价 = 后复权价 / scale
输出 price_scale.csv: code, px_hfq, px_raw, scale
"""
import baostock as bs
import csv
import os
import sys
import time
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_D15  # noqa: E402
W = str(FIN_D15)
OUT = os.path.join(W, "price_scale.csv")
PROG = os.path.join(W, "scale_prog.json")
REF_DATE = "2026-10-16"


def login():
    for _ in range(6):
        lg = bs.login()
        if lg.error_code == "0":
            return True
        time.sleep(2)
    return False


def bs_code(c6):
    return ("sh." if c6[0] == "6" else ("bj." if c6[:2] in ("43", "83", "87", "92") else "sz.")) + c6


def main():
    pit = list(csv.DictReader(open(os.path.join(W, "official_csi800_pit_2015.csv"), encoding="utf-8")))
    codes = sorted({r["code"][2:] if r["code"][:2] in ("sh", "sz") else r["code"] for r in pit})
    done = {}
    if os.path.exists(PROG):
        done = json.load(open(PROG, encoding="utf-8"))
    print(f"[start] total={len(codes)} done={len(done)}", flush=True)

    assert login(), "login failed"
    todo = [c for c in codes if c not in done]
    for i, c in enumerate(todo):
        rec = None
        for att in range(3):
            rs = bs.query_history_k_data_plus(bs_code(c), "date,close",
                                              start_date=REF_DATE, end_date=REF_DATE,
                                              frequency="d", adjustflag="3")
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            if rows and rows[0][1]:
                rec = float(rows[0][1])
                break
            if rs.error_code != "0":
                bs.logout(); time.sleep(1.0); login()
            else:
                break
        done[c] = rec
        if (i + 1) % 100 == 0:
            tmp = PROG + ".tmp"
            json.dump(done, open(tmp, "w", encoding="utf-8"))
            os.replace(tmp, PROG)
            print(f"  {i+1}/{len(todo)} {c}={rec}", flush=True)
    json.dump(done, open(PROG, "w", encoding="utf-8"))
    bs.logout()

    ok = {k: v for k, v in done.items() if v}
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "px_raw"])
        for k, v in sorted(ok.items()):
            w.writerow([k, v])
    print(f"[done] 有效 {len(ok)}/{len(codes)} -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
