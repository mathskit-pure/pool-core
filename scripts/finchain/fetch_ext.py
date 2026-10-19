# -*- coding: utf-8 -*-
"""补拉：1) 分红（baostock，按除权年份）2) 缺口行情（baostock 后复权日线）
断点续跑，会话掉线自动重连。
"""
import baostock as bs
import csv
import os
import sys
import time
import json
import glob

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_D15  # noqa: E402
W = str(FIN_D15)
PXDIR = os.path.join(W, "px_extra")
DIVF = os.path.join(W, "dividend.csv")
PROG = os.path.join(W, "fetch_prog.json")
os.makedirs(PXDIR, exist_ok=True)


def login():
    for _ in range(6):
        lg = bs.login()
        if lg.error_code == "0":
            return True
        time.sleep(2)
    return False


def bs_code(c6):
    return ("sh." if c6[0] == "6" else "sz.") + c6


def load_prog():
    if os.path.exists(PROG):
        return json.load(open(PROG, encoding="utf-8"))
    return {"div_done": [], "px_done": []}


def save_prog(p):
    tmp = PROG + ".tmp"
    json.dump(p, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, PROG)


def main():
    assert login(), "login failed"
    pit = list(csv.DictReader(open(os.path.join(W, "official_csi800_pit_2015.csv"), encoding="utf-8")))
    codes = sorted({r["code"][2:] if r["code"][:2] in ("sh", "sz") else r["code"] for r in pit})
    pxhave = {os.path.basename(p)[:6] for p in glob.glob(
        r"C:\Users\12066\WorkBuddy AI\2026-10-17-22-12-47\qmj_fraud\data\px\*.csv")}
    prog = load_prog()

    # ---------- A. 分红 ----------
    done = set(prog["div_done"])
    todo = [c for c in codes if c not in done]
    print(f"[div] total={len(codes)} todo={len(todo)}", flush=True)
    hdr = None
    for i, c in enumerate(todo):
        recs = []
        for y in range(2013, 2027):
            for att in range(3):
                rs = bs.query_dividend_data(code=bs_code(c), year=str(y), yearType="operate")
                rows = []
                while rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())
                if rows or rs.error_code == "0":
                    break
                bs.logout(); time.sleep(1.0); login()
            for r in rows:
                recs.append(r)
        if recs:
            hdr = hdr or list(rs.fields)
            newf = not os.path.exists(DIVF)
            with open(DIVF, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if newf:
                    w.writerow(["code6"] + hdr)
                for r in recs:
                    w.writerow([c] + r)
        prog["div_done"].append(c)
        if (i + 1) % 50 == 0:
            save_prog(prog)
            print(f"[div] {i+1}/{len(todo)} last={c}", flush=True)
    save_prog(prog)
    bs.logout()
    print(f"[div done] {len(prog['div_done'])}", flush=True)

    # ---------- B. 缺口行情 ----------
    assert login(), "relogin failed"
    miss = [c for c in codes if c not in pxhave]
    print(f"[px] 缺口 {len(miss)} 只", flush=True)
    for i, c in enumerate(miss):
        fp = os.path.join(PXDIR, c + ".csv")
        if os.path.exists(fp) and os.path.getsize(fp) > 100:
            continue
        rows = []
        for att in range(4):
            rs = bs.query_history_k_data_plus(
                bs_code(c), "date,open,high,low,close,volume,amount,turn",
                start_date="2014-12-01", end_date="2026-10-16", frequency="d", adjustflag="1")
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            if rows:
                break
            bs.logout(); time.sleep(1.2); login()
        if rows:
            with open(fp, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["date", "open", "high", "low", "close", "volume", "amount", "turn"])
                w.writerows(rows)
        if (i + 1) % 20 == 0:
            print(f"[px] {i+1}/{len(miss)} {c} rows={len(rows)}", flush=True)
    bs.logout()
    print("[px done]", flush=True)


if __name__ == "__main__":
    main()
