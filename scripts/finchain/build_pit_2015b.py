# -*- coding: utf-8 -*-
"""构建 2015-2026 官方中证800 PIT 成分序列（沪深300 ∪ 中证500，Baostock 按日期回溯）。
带会话保活/断点续跑：Baostock 单会话查询次数有限，检测到空结果即重连重试。
"""
import baostock as bs
import csv
import os
import sys
import time
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_D15 as OUT  # noqa: E402
OUT = str(OUT)
os.makedirs(OUT, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
FP = os.path.join(OUT, "official_csi800_pit_2015.csv")


def info_dates():
    ds = []
    for y in range(2014, 2027):
        for m, d in ((5, 1), (9, 1), (11, 1)):
            s = f"{y}-{m:02d}-{d:02d}"
            if "2014-05-01" <= s <= "2026-09-01":
                ds.append(s)
    return sorted(set(ds))


def login():
    for _ in range(5):
        lg = bs.login()
        if lg.error_code == "0":
            return True
        time.sleep(2)
    return False


def fetch(fn, date, retries=5):
    for attempt in range(retries):
        rs = fn(date=date)
        rows = []
        while rs.error_code == "0" and rs.next():
            r = rs.get_row_data()
            rows.append((r[1].replace(".", ""), r[2], r[0]))
        if rows:
            return rows
        if attempt < retries - 1:
            bs.logout()
            time.sleep(1.2)
            login()
    return []


def load_done():
    if not os.path.exists(FP):
        return set(), []
    rows = []
    with open(FP, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    cnt = Counter(r["asof"] for r in rows)
    done = {a for a, c in cnt.items() if c >= 750}
    return done, [r for r in rows if r["asof"] in done]


def save(rows):
    with open(FP, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["asof", "code", "source", "index_update_date"])
        w.writeheader()
        w.writerows(rows)


def main():
    assert login(), "baostock login failed"
    done, rows = load_done()
    print(f"[resume] 已完成 {len(done)} 期", flush=True)
    todo = [d for d in info_dates() if d not in done]
    print(f"[plan] 待拉 {len(todo)} 期", flush=True)

    for d in todo:
        h = fetch(bs.query_hs300_stocks, d)
        z = fetch(bs.query_zz500_stocks, d)
        if not h or not z:
            print(f"[WARN] {d}: hs300={len(h)} zz500={len(z)} 跳过", flush=True)
            continue
        upd = h[0][2]
        m = {}
        for c, n, _ in h:
            m[c] = "hs300"
        for c, n, _ in z:
            m.setdefault(c, "zz500")
        for c, src in m.items():
            rows.append({"asof": d, "code": c, "source": src, "index_update_date": upd})
        print(f"{d}: hs300={len(h)} zz500={len(z)} union={len(m)} 调样日={upd}", flush=True)
        save(rows)
        time.sleep(0.25)

    bs.logout()
    periods = sorted({r["asof"] for r in rows})
    codes = {r["code"] for r in rows}
    print(f"[done] 期数={len(periods)} 行数={len(rows)} 跨期并集={len(codes)}", flush=True)
    print(f"[periods] {periods}", flush=True)


if __name__ == "__main__":
    main()
