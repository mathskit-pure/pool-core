# -*- coding: utf-8 -*-
"""补齐创业板指（399006）日线到 2016-12 起，供派生页《质量Top28组合 · 季度回测》使用。

背景
    cloud/state/idx_399006.csv 是仓位建议模块带过来的，只从 2018-02-13 开始
    （中证2000 与该模块的起点一致）。派生页的统计窗口在 2026-10-23 统一到
    2017-01-03 后，基准线需要 2016-12 起的点位。baostock 的指数点位与线上文件
    在重叠区间内相差 < 0.01 点（约 3e-6 相对误差，纯浮点表示差异），可安全重建。

用法
    python scripts/finchain/fetch_idx_cyb.py            # 写入 cloud/state 与 out15
    python scripts/finchain/fetch_idx_cyb.py --dry-run  # 只比对不落盘

输出
    cloud/state/idx_399006.csv     date,close（2016-12-01 起，覆盖 pos_sync 与派生页）
    <FIN_OUT>/idx399006.csv        同上副本（派生页重建脚本直接读这份）
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE, FIN_OUT  # noqa: E402

CODE = "sz.399006"
START = "2016-12-01"
STATE = BASE / "cloud" / "state" / "idx_399006.csv"


def login():
    import baostock as bs
    for _ in range(6):
        if bs.login().error_code == "0":
            return bs
        time.sleep(2)
    return None


def fetch(end: str) -> pd.DataFrame:
    bs = login()
    if bs is None:
        raise SystemExit("baostock 登录失败")
    try:
        rs = bs.query_history_k_data_plus(CODE, "date,close", start_date=START,
                                          end_date=end, frequency="d", adjustflag="3")
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        code, msg = rs.error_code, rs.error_msg
    finally:
        bs.logout()
    if code != "0":
        raise SystemExit(f"baostock 取数失败：{code} {msg}")
    d = pd.DataFrame(rows, columns=["date", "close"])
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d["date"] = pd.to_datetime(d["date"])
    return d.dropna().sort_values("date").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    new = fetch(a.end)
    print(f"[fetch] {CODE} {len(new)} 行 {new['date'].min().date()} ~ {new['date'].max().date()}")

    if STATE.exists():
        old = pd.read_csv(STATE, index_col=0, parse_dates=True)["close"]
        j = old.to_frame("old").join(new.set_index("date")["close"].rename("new"), how="inner")
        if len(j):
            print(f"[check] 重叠 {len(j)} 日，最大差异 {(j['old'] - j['new']).abs().max():.6f} 点")
        else:
            print("[check] 与现有文件无重叠区间，按新数据整体重建")
    if a.dry_run:
        print("[dry-run] 未落盘")
        return

    STATE.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(STATE, index=False)
    print(f"[write] {STATE}")

    dst = FIN_OUT / "idx399006.csv"
    dst.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(dst, index=False)
    print(f"[write] {dst}")


if __name__ == "__main__":
    main()
