# -*- coding: utf-8 -*-
"""构造 2014-12 ~ 2026-10 的日线宽表与财务 PIT 面板（供因子构造与回测）。

行情：qmj_fraud/data/px/*.csv（后复权日线，2006起）+ work/data15/px_extra/*.csv（缺口补拉）
财务：fund/lrb+zcfz+xjll+yjbb → 时点面板 (code, avail, np, cfo, ta, te, shares)
"""
import os
import sys
import glob
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import (FIN_D15 as D15, FIN_PX as PX,  # noqa: E402
                   FIN_FUND as FUND)
os.makedirs(D15, exist_ok=True)
START = "2013-10-01"


def norm6(x):
    s = str(x).split(".")[0].strip()
    return s.zfill(6) if s.isdigit() else s


def build_px():
    frames = []
    for p in glob.glob(os.path.join(PX, "*.csv")):
        c = os.path.basename(p)[:6]
        try:
            d = pd.read_csv(p, dtype={"date": str})
        except Exception:
            continue
        if d.empty or "close" not in d.columns:
            continue
        d["code"] = c
        frames.append(d)
    for p in glob.glob(os.path.join(D15, "px_extra", "*.csv")):
        c = os.path.basename(p)[:6]
        try:
            d = pd.read_csv(p, dtype={"date": str})
        except Exception:
            continue
        if d.empty or "close" not in d.columns:
            continue
        d["code"] = c
        frames.append(d)
    px = pd.concat(frames, ignore_index=True)
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px = px.dropna(subset=["date", "close"])
    for c in ("open", "high", "low", "close", "volume"):
        if c in px.columns:
            px[c] = pd.to_numeric(px[c], errors="coerce")
    px = px[px["close"] > 0]
    px = px[px["date"] >= START]
    px = px.drop_duplicates(["code", "date"]).sort_values(["code", "date"]).reset_index(drop=True)
    px["ret"] = px.groupby("code")["close"].pct_change()
    if "amount" not in px.columns:
        px["amount"] = np.nan
    px["amount"] = pd.to_numeric(px["amount"], errors="coerce")
    fill = px["amount"].isna()
    px.loc[fill, "amount"] = px.loc[fill, "volume"].fillna(0) * 100.0 * px.loc[fill, "close"]
    px["idx"] = px.groupby("code")["close"].transform(lambda s: s / s.iloc[0])
    px.to_pickle(os.path.join(D15, "px_daily.pkl"))
    print(f"[px] rows={len(px):,} codes={px['code'].nunique()} "
          f"{px['date'].min():%Y-%m-%d}~{px['date'].max():%Y-%m-%d}", flush=True)
    return px


def build_fin():
    def rd(name, cols):
        d = pd.read_csv(os.path.join(FUND, name), dtype=str, engine="python", on_bad_lines="skip")
        keep = [c for c in cols if c in d.columns]
        d = d[keep].copy()
        d["code"] = d["SECURITY_CODE"].map(norm6)
        return d

    inc = rd("lrb.csv", ["SECURITY_CODE", "REPORT_DATE", "NOTICE_DATE",
                         "TOTAL_OPERATE_INCOME", "PARENT_NETPROFIT", "OPERATE_COST"])
    bal = rd("zcfz.csv", ["SECURITY_CODE", "REPORT_DATE", "NOTICE_DATE", "TOTAL_ASSETS", "TOTAL_EQUITY"])
    cf = rd("xjll.csv", ["SECURITY_CODE", "REPORT_DATE", "NOTICE_DATE", "NETCASH_OPERATE"])
    yj = rd("yjbb.csv", ["SECURITY_CODE", "REPORTDATE", "NOTICE_DATE", "BPS"])

    for d, dc in ((inc, "REPORT_DATE"), (bal, "REPORT_DATE"), (cf, "REPORT_DATE"), (yj, "REPORTDATE")):
        d["EndDate"] = pd.to_datetime(d[dc], errors="coerce").dt.normalize()
        d["avail"] = pd.to_datetime(d["NOTICE_DATE"], errors="coerce")
        d["avail"] = d["avail"].fillna(d["EndDate"] + pd.Timedelta(days=90))
        d["y"] = d["EndDate"].dt.year
        d["m"] = d["EndDate"].dt.month
    for d in (inc, bal, cf):
        for c in ("TOTAL_OPERATE_INCOME", "PARENT_NETPROFIT", "OPERATE_COST",
                  "TOTAL_ASSETS", "TOTAL_EQUITY", "NETCASH_OPERATE"):
            if c in d.columns:
                d[c] = pd.to_numeric(d[c], errors="coerce")

    # TTM：累计 → 滚动四季
    key = ["code", "y", "m"]

    def ttm(df, cols):
        """向量化 TTM：cur + FY(前一年) - 同期累计(前一年)；年报期直接取自身。"""
        cur = df.set_index(key)[cols]
        cur = cur[~cur.index.duplicated()].reset_index()
        cur = cur.sort_values(key)
        # 上一年年报（去掉 m 列，避免与左侧 m 冲突）
        fy = cur[cur["m"] == 12][["code", "y"] + cols].copy()
        fy["y"] = fy["y"] + 1
        fy = fy.rename(columns={c: c + "_FYP" for c in cols})
        # 上年同期累计
        sp = cur[key + cols].copy()
        sp["y"] = sp["y"] + 1
        sp = sp.rename(columns={c: c + "_SP" for c in cols})
        m = cur.merge(fy, on=["code", "y"], how="left").merge(sp, on=key, how="left")
        for c in cols:
            m[c + "_TTM"] = np.where(m["m"] == 12, m[c], m[c] + m[c + "_FYP"] - m[c + "_SP"])
        return m[key + [c + "_TTM" for c in cols]]

    inc_t = ttm(inc, ["TOTAL_OPERATE_INCOME", "PARENT_NETPROFIT"])
    cf_t = ttm(cf, ["NETCASH_OPERATE"])

    base = inc[key + ["EndDate", "avail"]].copy()
    base = base.merge(inc_t, on=key, how="left")
    base = base.merge(bal[key + ["TOTAL_ASSETS", "TOTAL_EQUITY"]].drop_duplicates(key), on=key, how="left")
    base = base.merge(cf_t, on=key, how="left")
    base = base.merge(yj[key + ["BPS"]].drop_duplicates(key), on=key, how="left")

    base["np"] = pd.to_numeric(base["PARENT_NETPROFIT_TTM"], errors="coerce")
    base["cfo"] = pd.to_numeric(base["NETCASH_OPERATE_TTM"], errors="coerce")
    base["ta"] = pd.to_numeric(base["TOTAL_ASSETS"], errors="coerce")
    base["te"] = pd.to_numeric(base["TOTAL_EQUITY"], errors="coerce")
    base["bps"] = pd.to_numeric(base["BPS"], errors="coerce")
    base["rev"] = pd.to_numeric(base["TOTAL_OPERATE_INCOME_TTM"], errors="coerce")
    base["shares"] = np.where(base["bps"] > 0, base["te"] / base["bps"], np.nan)

    fin = base.dropna(subset=["avail", "ta", "te"]).copy()
    fin = fin[fin["avail"] >= pd.Timestamp("2014-01-01")]
    fin = fin[["code", "EndDate", "avail", "np", "cfo", "ta", "te", "bps", "shares", "rev"]]
    fin = fin.sort_values(["code", "avail"]).drop_duplicates(["code", "EndDate"], keep="last")
    fin.to_pickle(os.path.join(D15, "fin_pit.pkl"))
    print(f"[fin] rows={len(fin):,} codes={fin['code'].nunique()} "
          f"avail {fin['avail'].min():%Y-%m-%d}~{fin['avail'].max():%Y-%m-%d}", flush=True)
    return fin


if __name__ == "__main__":
    if not os.path.exists(os.path.join(D15, "px_daily.pkl")):
        build_px()
    else:
        print("[px] px_daily.pkl 已存在，跳过", flush=True)
    build_fin()
