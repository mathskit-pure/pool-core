# -*- coding: utf-8 -*-
"""补全股票名称：baostock query_all_stock + 逐只 query_stock_basic 兜底（含退市股）。"""
import json
import os
import sys
import time

import baostock as bs
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_OUT  # noqa: E402
W = str(FIN_OUT)
OUT = os.path.join(W, "name_map.json")


def bs_code(c6):
    return ("sh." if c6[0] == "6" else ("bj." if c6[:2] in ("43", "83", "87", "92") else "sz.")) + c6


def login():
    for _ in range(6):
        if bs.login().error_code == "0":
            return True
        time.sleep(2)
    return False


def main():
    name = json.load(open(OUT, encoding="utf-8"))
    pool = pd.read_csv(os.path.join(W, "out15", "period_pools_2015_2026.csv"), dtype={"code": str})
    need = sorted(set(pool["code"]) - set(name))
    print(f"[start] 已有 {len(name)}，待补 {len(need)}", flush=True)
    if not need:
        return

    assert login()
    rs = bs.query_all_stock(day="2026-10-16")
    n = 0
    while rs.error_code == "0" and rs.next():
        r = rs.get_row_data()
        c = r[0].split(".")[-1]
        if len(c) == 6 and c.isdigit() and r[2]:
            name.setdefault(c, r[2].strip())
            n += 1
    print(f"[all_stock] 取到 {n} 条", flush=True)

    left = [c for c in need if c not in name]
    print(f"[left] 仍需逐只查 {len(left)}", flush=True)
    for i, c in enumerate(left):
        for _ in range(2):
            r = bs.query_stock_basic(code=bs_code(c))
            rows = []
            while r.error_code == "0" and r.next():
                rows.append(r.get_row_data())
            if rows:
                name[c] = rows[0][1].strip()
                break
            bs.logout(); time.sleep(0.4); login()
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(left)}", flush=True)
    bs.logout()

    json.dump(name, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    still = [c for c in need if c not in name]
    print(f"[done] 名称总数 {len(name)}，仍缺 {len(still)}: {still[:15]}", flush=True)


if __name__ == "__main__":
    main()
