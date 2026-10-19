# -*- coding: utf-8 -*-
"""FAQ 评分引擎（2015-2026 全期统一口径）。

严格复用 pool-core/scripts/score.py 的公式：
  四支柱 (盈利 .34 / 会计质量 .22 / 分红稀释 .22 / 投资 .22) → Q_score
  F 舞弊信号 → F_score
  FAQ = Q_z − 1.0·F_z （同报告期重新标准化，行业中性）

数据源（替代原 westock 宽表，改全市场长历史）：
  fund/lrb.csv    利润表（累计值）
  fund/zcfz.csv   资产负债表
  fund/xjll.csv   现金流量表
  fund/yjbb.csv   业绩报表（BPS / ROE / 毛利率 / EPS）
  dividend.csv    分红（baostock，每股派现）
行业：meta.json sw1/sw2/sw3 优先，sw3_map.csv（legulegu 当前申万三级）兜底。
"""
import os
import sys
import json
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import (FIN_D15 as D15, FIN_FUND as FUND,  # noqa: E402
                   FIN_META as META, FIN_SW as SW3MAP)
os.makedirs(D15, exist_ok=True)

NUM = lambda s: pd.to_numeric(s, errors="coerce")


def norm6(x):
    s = str(x).split(".")[0].strip()
    return s.zfill(6) if s.isdigit() else s


def load_fund():
    def rd(name, cols):
        p = os.path.join(FUND, name)
        d = pd.read_csv(p, dtype=str, engine="python", on_bad_lines="skip")
        keep = [c for c in cols if c in d.columns]
        d = d[keep].copy()
        d["code"] = d["SECURITY_CODE"].map(norm6)
        return d
    inc = rd("lrb.csv", ["SECURITY_CODE", "REPORT_DATE", "NOTICE_DATE", "OPERATE_INCOME",
                         "OPERATE_COST", "TOTAL_OPERATE_INCOME", "PARENT_NETPROFIT",
                         "DEDUCT_PARENT_NETPROFIT", "OPERATE_PROFIT", "TOTAL_PROFIT",
                         "INVEST_INCOME", "INDUSTRY_NAME"])
    bal = rd("zcfz.csv", ["SECURITY_CODE", "REPORT_DATE", "NOTICE_DATE", "TOTAL_ASSETS",
                          "TOTAL_LIABILITIES", "TOTAL_EQUITY", "ACCOUNTS_RECE", "INVENTORY",
                          "MONETARYFUNDS", "FIXED_ASSET", "CURRENT_RATIO", "DEBT_ASSET_RATIO",
                          "ACCOUNTS_PAYABLE", "ADVANCE_RECEIVABLES", "SHORT_LOAN"])
    cf = rd("xjll.csv", ["SECURITY_CODE", "REPORT_DATE", "NOTICE_DATE", "NETCASH_OPERATE",
                         "NETCASH_INVEST", "NETCASH_FINANCE", "SALES_SERVICES",
                         "CONSTRUCT_LONG_ASSET"])
    yj = rd("yjbb.csv", ["SECURITY_CODE", "REPORTDATE", "NOTICE_DATE", "TOTAL_OPERATE_INCOME",
                         "PARENT_NETPROFIT", "WEIGHTAVG_ROE", "BPS", "XSMLL",
                         "BASIC_EPS", "DEDUCT_BASIC_EPS"])

    for d, dc in ((inc, "REPORT_DATE"), (bal, "REPORT_DATE"), (cf, "REPORT_DATE"), (yj, "REPORTDATE")):
        d["EndDate"] = pd.to_datetime(d[dc], errors="coerce").dt.normalize()
        d.dropna(subset=["EndDate"], inplace=True)
        d["y"] = d["EndDate"].dt.year
        d["m"] = d["EndDate"].dt.month
        d["pd"] = pd.to_datetime(d["NOTICE_DATE"], errors="coerce")
        # 法定披露截止日（中国 A 股）：Q1 4/30、H1 8/31、Q3 10/31、年报次年 4/30
        def _deadline(ed):
            if pd.isna(ed):
                return pd.NaT
            y, m = ed.year, ed.month
            return {3: pd.Timestamp(f"{y}-04-30"), 6: pd.Timestamp(f"{y}-08-31"),
                    9: pd.Timestamp(f"{y}-10-31"), 12: pd.Timestamp(f"{y+1}-04-30")}.get(m, ed + pd.Timedelta(days=90))
        dl = d["EndDate"].map(_deadline)
        # 取 min(实际公告日, 法定截止日)：尊重提前披露，同时纠正数据源里错标的公告日
        d["pd"] = np.where(d["pd"].notna() & (d["pd"] >= d["EndDate"]),
                           np.minimum(d["pd"], dl), dl)
        d["pd"] = pd.to_datetime(d["pd"])
        d.sort_values(["code", "EndDate", "pd"], inplace=True)
        d.drop_duplicates(["code", "EndDate"], keep="first", inplace=True)
    return inc, bal, cf, yj


def add_ttm(df, valcols):
    """累计值 → TTM。需要同一 code 的当年年报与去年同期累计。"""
    d = df.copy()
    d["y"] = d["EndDate"].dt.year
    d["m"] = d["EndDate"].dt.month
    for c in valcols:
        d[c] = NUM(d[c]) if c in d.columns else np.nan
    # 年报映射
    fy = d[d["m"] == 12].set_index(["code", "y"])[valcols]
    fy_prev = fy.copy()
    fy_prev.index = fy_prev.index.set_levels(fy_prev.index.levels[1] - 1, level=1)
    fy_prev = fy_prev[~fy_prev.index.duplicated()]
    # 去年同期累计
    same_prev = d.set_index(["code", "y", "m"])[valcols]
    same_prev.index = same_prev.index.set_levels(same_prev.index.levels[1] - 1, level=1)
    same_prev = same_prev[~same_prev.index.duplicated()]

    out = {}
    cur = d.set_index(["code", "y", "m"])[valcols]
    pf = fy_prev.reindex(cur.index.droplevel(2)).values
    pv = same_prev.reindex(cur.index).values
    vals = cur.values.astype(float)
    is_fy = (d["m"].values == 12)[:, None]
    ttm = np.where(is_fy, vals, vals + pf - pv)
    ttm = pd.DataFrame(ttm, index=cur.index, columns=valcols).reset_index()
    return ttm


def build_panel():
    inc, bal, cf, yj = load_fund()

    # ---- TTM ----
    inc_ttm = add_ttm(inc, ["TOTAL_OPERATE_INCOME", "PARENT_NETPROFIT", "DEDUCT_PARENT_NETPROFIT",
                            "OPERATE_PROFIT", "OPERATE_COST"])
    inc_ttm.columns = ["code", "y", "m"] + [c + "_TTM" for c in inc_ttm.columns[3:]]
    cf_ttm = add_ttm(cf, ["NETCASH_OPERATE"])
    cf_ttm.columns = ["code", "y", "m", "CFO_TTM"]

    # ---- 合并 ----
    key = ["code", "y", "m"]
    base = inc[["code", "EndDate", "pd", "y", "m", "OPERATE_INCOME", "OPERATE_COST",
                "TOTAL_OPERATE_INCOME", "PARENT_NETPROFIT", "DEDUCT_PARENT_NETPROFIT",
                "OPERATE_PROFIT", "INDUSTRY_NAME"]].copy()
    base = base.merge(inc_ttm, on=key, how="left")
    b2 = bal[["code", "y", "m", "TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY",
              "ACCOUNTS_RECE", "INVENTORY", "MONETARYFUNDS", "FIXED_ASSET",
              "CURRENT_RATIO", "DEBT_ASSET_RATIO", "SHORT_LOAN"]].drop_duplicates(key)
    base = base.merge(b2, on=key, how="left")
    base = base.merge(cf_ttm, on=key, how="left")
    y2 = yj[["code", "y", "m", "WEIGHTAVG_ROE", "BPS", "XSMLL", "BASIC_EPS",
             "DEDUCT_BASIC_EPS", "pd"]].drop_duplicates(key).rename(columns={"pd": "pd_yj"})
    base = base.merge(y2, on=key, how="left")

    for c in ["TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY", "ACCOUNTS_RECE",
              "INVENTORY", "MONETARYFUNDS", "FIXED_ASSET", "CURRENT_RATIO",
              "DEBT_ASSET_RATIO", "BPS", "XSMLL", "BASIC_EPS", "WEIGHTAVG_ROE",
              "TOTAL_OPERATE_INCOME_TTM", "PARENT_NETPROFIT_TTM",
              "DEDUCT_PARENT_NETPROFIT_TTM", "OPERATE_PROFIT_TTM", "OPERATE_COST_TTM",
              "CFO_TTM", "PARENT_NETPROFIT", "TOTAL_OPERATE_INCOME", "OPERATE_PROFIT",
              "ACCOUNTS_RECE"]:
        if c in base.columns:
            base[c] = pd.to_numeric(base[c], errors="coerce")

    # ---- 分红 TTM ----
    divp = os.path.join(D15, "dividend.csv")
    if os.path.exists(divp):
        dv = pd.read_csv(divp, dtype=str, engine="python", on_bad_lines="skip")
        dv["code"] = dv["code6"].map(norm6)
        dv["ps"] = pd.to_numeric(dv.get("dividCashPsBeforeTax"), errors="coerce")
        dv["opdate"] = pd.to_datetime(dv.get("dividOperateDate"), errors="coerce")
        dv = dv.dropna(subset=["ps", "opdate"])
        # 每股派现按除权日；按 code 累计过去 12 个月
        dv = dv.sort_values(["code", "opdate"])
        div_rows = []
        for c, g in dv.groupby("code"):
            dates = g["opdate"].values.astype("datetime64[D]")
            ps = g["ps"].values
            for i in range(len(g)):
                lo = dates[i] - np.timedelta64(365, "D")
                mask = (dates > lo) & (dates <= dates[i])
                div_rows.append((c, dates[i], float(np.nansum(ps[mask]))))
        divttm = pd.DataFrame(div_rows, columns=["code", "opdate", "ps_ttm"])
        divttm["opdate"] = pd.to_datetime(divttm["opdate"]).astype("datetime64[ns]")
        base["pd"] = pd.to_datetime(base["pd"]).astype("datetime64[ns]")
        base = pd.merge_asof(base.sort_values("pd"), divttm.sort_values("opdate"),
                             left_on="pd", right_on="opdate", by="code",
                             direction="backward", allow_exact_matches=True)
        base["DIV_PS_TTM"] = base["ps_ttm"]
    else:
        base["DIV_PS_TTM"] = np.nan

    # ---- 行业 ----
    meta = json.load(open(META, encoding="utf-8"))
    m1 = {norm6(v.get("code", k)): (v.get("sw1"), v.get("sw2"), v.get("sw3"))
          for k, v in meta.items()}
    sw = pd.DataFrame([(k, a, b, c) for k, (a, b, c) in m1.items()],
                      columns=["code", "sw1", "sw2", "sw3"])
    if os.path.exists(SW3MAP):
        s3 = pd.read_csv(SW3MAP, dtype=str, engine="python")
        s3["code"] = s3["code"].map(norm6)
        s3 = s3.drop_duplicates("code")[["code", "l3name"]].rename(columns={"l3name": "sw3_fb"})
        base = base.merge(s3, on="code", how="left")
    else:
        base["sw3_fb"] = np.nan
    base = base.merge(sw, on="code", how="left")
    base["sw3"] = base["sw3"].fillna(base["sw3_fb"])
    base["sw1"] = base["sw1"].fillna("未分类")

    # 兜底：meta 无行业的股票，用 qmj panel 的申万二级（ind，128 类）分组
    PANEL2 = r"C:\Users\12066\WorkBuddy AI\2026-10-17-22-12-47\qmj_fraud\data\panel.csv"
    if os.path.exists(PANEL2):
        pn = pd.read_csv(PANEL2, dtype=str, usecols=["code", "ind"], engine="python", on_bad_lines="skip")
        pn["code"] = pn["code"].map(norm6)
        pn = pn.dropna(subset=["ind"]).drop_duplicates("code")
        base = base.merge(pn, on="code", how="left")
    else:
        base["ind"] = np.nan
    # 分组键：优先申万三级，其次申万二级，最后东财行业
    base["grp"] = base["sw3"].fillna(base["ind"]).fillna(base["INDUSTRY_NAME"]).fillna("未分类")
    base["sw3"] = base["grp"]
    return base


def add_derived(p):
    p = p.sort_values(["code", "EndDate"]).reset_index(drop=True)
    g = p.groupby("code")

    def safe_div(a, b):
        a = np.asarray(a, dtype=float)
        b = np.asarray(b, dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where((b == 0) | ~np.isfinite(b) | ~np.isfinite(a), np.nan, a / b)

    L = lambda c: g[c].shift(4)

    p["total_assets"] = p["TOTAL_ASSETS"]
    p["total_assets_y"] = L("total_assets")
    p["rev_ttm"] = p["TOTAL_OPERATE_INCOME_TTM"]
    p["rev_ttm_y"] = L("rev_ttm")
    p["ni_ttm"] = p["PARENT_NETPROFIT_TTM"]
    p["ni"] = p["PARENT_NETPROFIT"]
    p["deduct"] = p["DEDUCT_PARENT_NETPROFIT"]
    p["cfo_ttm"] = p["CFO_TTM"]
    p["se"] = p["TOTAL_EQUITY"]
    p["naps"] = p["BPS"]

    # 盈利能力
    p["roe_ttm"] = safe_div(p["ni_ttm"], p["se"]) * 100
    p["roa_ttm"] = safe_div(p["ni_ttm"], p["total_assets"]) * 100
    p["roic"] = safe_div(p["OPERATE_PROFIT_TTM"] * 0.75,
                         p["se"] + 0.5 * p["TOTAL_LIABILITIES"]) * 100
    p["gross_margin"] = safe_div(p["TOTAL_OPERATE_INCOME_TTM"] - p["OPERATE_COST_TTM"],
                                 p["TOTAL_OPERATE_INCOME_TTM"]) * 100
    p["net_margin"] = safe_div(p["ni_ttm"], p["rev_ttm"]) * 100
    p["gross_margin_y"] = L("gross_margin")
    p["cash_conversion"] = safe_div(p["cfo_ttm"], p["ni_ttm"])
    p["ni_quality"] = np.where(p["deduct"].notna(), safe_div(p["deduct"], p["ni"]), np.nan)

    # 会计质量
    p["accruals_ttm"] = p["ni_ttm"] - p["cfo_ttm"]
    p["tata"] = safe_div(p["accruals_ttm"], p["total_assets"])
    p["ar"] = p["ACCOUNTS_RECE"]
    p["inv"] = p["INVENTORY"]
    p["ar_y"] = L("ar")
    p["dsri"] = np.where((p["ar_y"] > 0) & (p["rev_ttm_y"] > 0),
                         safe_div(p["ar"] / p["rev_ttm"], p["ar_y"] / p["rev_ttm_y"]), np.nan)

    # 非流动资产近似：总资产 − (货币 + 应收 + 存货)
    p["cur_assets"] = p[["MONETARYFUNDS", "ACCOUNTS_RECE", "INVENTORY"]].sum(axis=1, min_count=1)
    p["noncur_assets"] = p["total_assets"] - p["cur_assets"]
    ncur_share = safe_div(p["noncur_assets"], p["total_assets"])
    ncur_share_y = safe_div(L("noncur_assets"), p["total_assets_y"])
    p["aqi"] = np.where(ncur_share_y > 0, ncur_share / ncur_share_y, np.nan)

    # 分红与稀释
    p["div_ttm"] = p["DIV_PS_TTM"] * safe_div(p["se"], p["naps"])  # 每股派现 × 股本
    p["payout"] = np.where(p["ni_ttm"] > 0, safe_div(p["div_ttm"], p["ni_ttm"]), np.nan)
    p["dividend_yield_proxy"] = np.where(p["ni_ttm"] > 0, safe_div(p["div_ttm"], p["se"]), np.nan)
    p["shares"] = np.where(p["naps"] > 0, safe_div(p["se"], p["naps"]), np.nan)
    p["naps_y"] = L("naps")
    p["shares_y"] = np.where(p["naps_y"] > 0, safe_div(L("se"), p["naps_y"]), np.nan)
    p["share_growth"] = np.where((p["shares_y"] > 0) & np.isfinite(p["shares"]),
                                 p["shares"] / p["shares_y"] - 1, np.nan)

    # 投资活动
    p["asset_growth"] = np.where(p["total_assets_y"] > 0,
                                 p["total_assets"] / p["total_assets_y"] - 1, np.nan)
    p["inv_growth"] = np.where(L("inv") > 0, p["inv"] / L("inv") - 1, np.nan)

    # F 舞弊信号
    p["gmi"] = np.where(p["gross_margin"] > 0, p["gross_margin_y"] / p["gross_margin"], np.nan)
    p["sgi"] = np.where(p["rev_ttm_y"] > 0, p["rev_ttm"] / p["rev_ttm_y"], np.nan)
    p["debt_assets"] = p["DEBT_ASSET_RATIO"]
    p["debt_assets_y"] = L("debt_assets")
    p["lvgi"] = np.where(p["debt_assets_y"] > 0, p["debt_assets"] / p["debt_assets_y"], np.nan)
    p["goodwill_ratio"] = np.nan  # fund 表无商誉，F 中该信号自动跳过
    return p


PILLARS = {
    "盈利能力": [("roe_ttm", +1), ("roic", +1), ("roa_ttm", +1),
               ("gross_margin", +1), ("net_margin", +1), ("cash_conversion", +1)],
    "会计质量": [("tata", -1), ("dsri", -1), ("aqi", -1), ("ni_quality", +1)],
    "分红与稀释": [("payout", +1), ("dividend_yield_proxy", +1), ("share_growth", -1)],
    "投资活动": [("asset_growth", -1), ("inv_growth", -1)],
}
FRAUD = [("tata", +1), ("dsri", +1), ("aqi", +1), ("sgi", +1),
         ("gmi", +1), ("lvgi", +1), ("share_growth", +1)]
PILLAR_W = {"盈利能力": 0.34, "会计质量": 0.22, "分红与稀释": 0.22, "投资活动": 0.22}
LAMBDA = 1.0


def zscore_industry_neutral(p, col):
    out = pd.Series(np.nan, index=p.index)
    for d, gdf in p.groupby("EndDate"):
        s = pd.to_numeric(gdf[col], errors="coerce")
        if s.notna().sum() < 20:
            continue
        lo, hi = s.quantile(0.01), s.quantile(0.99)
        s = s.clip(lo, hi)
        if gdf["sw1"].notna().any():
            med = s.groupby(gdf["sw1"]).transform("median")
            s = s - med
        mu, sd = s.mean(), s.std(ddof=0)
        if not np.isfinite(sd) or sd == 0:
            continue
        out.loc[gdf.index] = ((s - mu) / sd).clip(-3, 3)
    return out


def score(p):
    Z = {}
    for pillar, sigs in PILLARS.items():
        for c, _ in sigs:
            if c not in Z:
                Z[c] = zscore_industry_neutral(p, c)
    for c, _ in FRAUD:
        if c not in Z:
            Z[c] = zscore_industry_neutral(p, c)

    for pillar, sigs in PILLARS.items():
        mat = pd.concat([(Z[c] * d).rename(c) for c, d in sigs], axis=1)
        p["P_" + pillar] = mat.mean(axis=1, skipna=True)

    wsum = pd.Series(0.0, index=p.index)
    q = pd.Series(0.0, index=p.index)
    for pillar, w in PILLAR_W.items():
        v = p["P_" + pillar]
        ok = v.notna()
        q[ok] = q[ok] + w * v[ok]
        wsum[ok] = wsum[ok] + w
    p["Q_score"] = np.where(wsum > 0, q / wsum, np.nan)

    fmat = pd.concat([(Z[c] * d).rename(c) for c, d in FRAUD], axis=1)
    p["F_score"] = fmat.mean(axis=1, skipna=True)

    def restd(s):
        out = pd.Series(np.nan, index=p.index)
        for _, gdf in p.groupby("EndDate"):
            v = s.loc[gdf.index]
            if v.notna().sum() < 20:
                continue
            mu, sd = v.mean(), v.std(ddof=0)
            out.loc[gdf.index] = ((v - mu) / sd).clip(-3, 3) if sd else 0.0
        return out

    p["Q_z"] = restd(p["Q_score"])
    p["F_z"] = restd(p["F_score"])
    p["FAQ_score"] = p["Q_z"] - LAMBDA * p["F_z"]
    p["FAQ_pct"] = p.groupby("EndDate")["FAQ_score"].rank(pct=True) * 100
    return p


def main():
    print("[1/4] 读入并合并四表...", flush=True)
    p = build_panel()
    print(f"    panel rows={len(p)} codes={p['code'].nunique()} periods={p['EndDate'].nunique()}", flush=True)

    print("[2/4] 衍生指标...", flush=True)
    p = add_derived(p)

    print("[3/4] 打分（行业中性 z）...", flush=True)
    p = score(p)

    keep = ["code", "EndDate", "pd", "sw1", "sw2", "sw3", "FAQ_score", "FAQ_pct",
            "Q_score", "F_score", "Q_z", "F_z", "roe_ttm", "roa_ttm", "roic",
            "gross_margin", "net_margin", "cash_conversion", "tata", "dsri", "aqi",
            "ni_quality", "payout", "dividend_yield_proxy", "share_growth",
            "asset_growth", "inv_growth", "total_assets", "se", "ni_ttm", "rev_ttm"]
    keep = [c for c in keep if c in p.columns]
    out = p[keep].copy()
    fp = os.path.join(D15, "faq_panel_2015.csv.gz")
    out.to_csv(fp, index=False, compression="gzip")
    print(f"[4/4] saved {fp} rows={len(out)}", flush=True)

    cnt = out.dropna(subset=["FAQ_score"]).groupby(out["EndDate"].dt.year).size()
    print("可评分条数(按年):", cnt.to_dict(), flush=True)
    print("行业覆盖: sw3非未分类占比 %.1f%%" %
          (100 * (out["sw3"] != "未分类").mean()), flush=True)


if __name__ == "__main__":
    main()
