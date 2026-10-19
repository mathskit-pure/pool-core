# -*- coding: utf-8 -*-
"""拉取三个宽基指数日线（后复权/点位），2014-10 ~ 2026-10，供回测基准使用。"""
import os
import sys
import time
import pandas as pd
import baostock as bs

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_OUT  # noqa: E402
os.makedirs(FIN_OUT, exist_ok=True)
OUT = str(FIN_OUT / "bench_daily.csv")
IDX = {"sh.000300": "沪深300", "sh.000905": "中证500", "sz.399673": "创业板50"}


def login():
    for _ in range(6):
        if bs.login().error_code == "0":
            return True
        time.sleep(2)
    return False


def main():
    assert login()
    frames = []
    for code, name in IDX.items():
        rs = bs.query_history_k_data_plus(code, "date,close", start_date="2014-10-01",
                                         end_date="2026-10-16", frequency="d", adjustflag="3")
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        d = pd.DataFrame(rows, columns=["date", "close"])
        d["close"] = pd.to_numeric(d["close"], errors="coerce")
        d = d.dropna()
        d["date"] = pd.to_datetime(d["date"])
        d["name"] = name
        if d.empty:
            print(f"{name}: 无数据", flush=True)
        else:
            print(f"{name}: {len(d)} 行 {d['date'].min()} ~ {d['date'].max()}", flush=True)
        frames.append(d)
        time.sleep(0.3)
    bs.logout()
    pd.concat(frames).to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"[done] -> {OUT}")


if __name__ == "__main__":
    main()
