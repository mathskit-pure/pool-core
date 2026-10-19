# -*- coding: utf-8 -*-
"""抓取全部 A 股季度财务面板（2009Q1 起），保留公告日用于时点对齐。

原 qmj_fraud/src/s1_fund.py + s1b_2009.py 合并：2009 年四期一并拉，避免两步顺序依赖。
断点续跑：已存在且体积正常的表直接跳过（云端重建时可分段重试）。

用法：
    python scripts/finchain/fetch_fund.py            # 缺失才拉
    python scripts/finchain/fetch_fund.py --force    # 强制重拉
"""
import csv
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_FUND, FIN_ROOT  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from em import em_query  # noqa: E402

PERIODS = []
for y in range(2009, 2027):
    for md in ("03-31", "06-30", "09-30", "12-31"):
        d = "%d-%s" % (y, md)
        if d <= "2026-09-30":
            PERIODS.append(d)

SPECS = [
    ("yjbb", "RPT_LICO_FN_CPD", "REPORTDATE",
     ["SECURITY_CODE", "SECURITY_NAME_ABBR", "REPORTDATE", "NOTICE_DATE", "TOTAL_OPERATE_INCOME",
      "PARENT_NETPROFIT", "WEIGHTAVG_ROE", "BPS", "MGJYXJJE", "XSMLL", "YSTZ", "SJLTZ",
      "BASIC_EPS", "DEDUCT_BASIC_EPS", "PUBLISHNAME"]),
    ("lrb", "RPT_DMSK_FN_INCOME", "REPORT_DATE",
     ["SECURITY_CODE", "SECURITY_NAME_ABBR", "REPORT_DATE", "NOTICE_DATE", "OPERATE_INCOME",
      "OPERATE_COST", "TOTAL_OPERATE_INCOME", "PARENT_NETPROFIT", "DEDUCT_PARENT_NETPROFIT",
      "OPERATE_PROFIT", "TOTAL_PROFIT", "SALE_EXPENSE", "MANAGE_EXPENSE", "FINANCE_EXPENSE",
      "INVEST_INCOME", "INDUSTRY_NAME"]),
    ("zcfz", "RPT_DMSK_FN_BALANCE", "REPORT_DATE",
     ["SECURITY_CODE", "REPORT_DATE", "NOTICE_DATE", "TOTAL_ASSETS", "TOTAL_LIABILITIES",
      "TOTAL_EQUITY", "ACCOUNTS_RECE", "INVENTORY", "MONETARYFUNDS", "FIXED_ASSET",
      "CURRENT_RATIO", "DEBT_ASSET_RATIO", "ACCOUNTS_PAYABLE", "ADVANCE_RECEIVABLES",
      "SHORT_LOAN", "INDUSTRY_NAME"]),
    ("xjll", "RPT_DMSK_FN_CASHFLOW", "REPORT_DATE",
     ["SECURITY_CODE", "REPORT_DATE", "NOTICE_DATE", "NETCASH_OPERATE", "NETCASH_INVEST",
      "NETCASH_FINANCE", "SALES_SERVICES", "CONSTRUCT_LONG_ASSET"]),
]


def log(*a):
    print(*a, flush=True)


def main():
    force = "--force" in sys.argv
    os.makedirs(FIN_FUND, exist_ok=True)
    for tag, rn, datecol, cols in SPECS:
        fp = os.path.join(FIN_FUND, tag + ".csv")
        if not force and os.path.exists(fp) and os.path.getsize(fp) > 10000:
            log("skip", tag, "(已存在 %.1f MB)" % (os.path.getsize(fp) / 1e6))
            continue
        rows = []
        t0 = time.time()
        for p in PERIODS:
            flt = "(%s='%s')" % (datecol, p)
            try:
                recs = em_query(rn, flt, page_size=500, max_pages=30)
            except Exception as e:
                log("  !!", tag, p, e)
                recs = []
            for r in recs:
                rows.append({c: r.get(c) for c in cols})
            log("  %s %s -> %d (total %d) %.0fs"
                % (tag, p, len(recs), len(rows), time.time() - t0))
            time.sleep(0.12)
        if not rows:
            log("  !! %s 一条都没拿到，跳过写盘（保留旧文件）" % tag)
            continue
        tmp = fp + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, fp)
        log("saved", tag, len(rows))

    # 股票清单（含已退市）
    codes = set()
    for tag, _, _, _ in SPECS:
        fp = os.path.join(FIN_FUND, tag + ".csv")
        if os.path.exists(fp):
            with open(fp, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    c = row.get("SECURITY_CODE")
                    if c:
                        codes.add(c)
    out = os.path.join(FIN_ROOT, "codes.csv")
    pd.DataFrame({"code": sorted(codes)}).to_csv(out, index=False)
    log("TOTAL codes", len(codes), "->", out)


if __name__ == "__main__":
    main()
