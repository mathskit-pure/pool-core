# -*- coding: utf-8 -*-
"""逐只抓取持仓股研报（东方财富研报中心公开接口，无需 key）。

与 fetch_new_reports.py 的区别：**按 code 逐只查**，比「拉全市场再本地过滤」更全
（全市场 qType=0 分页上限有限，容易漏）。第六章滚动更新用这个。

用法：
    python scripts/finchain/fetch_stock_reports.py --from 2026-10-23 --to 2026-10-27
    python scripts/finchain/fetch_stock_reports.py --from 2026-09-25 --to 2026-10-27 --detail
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from paths import BASE  # noqa: E402

URL = "https://reportapi.eastmoney.com/report/list"
HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
}


def _get(params, timeout=40, tries=3):
    q = urllib.parse.urlencode(params)
    for k in range(tries):
        try:
            req = urllib.request.Request(URL + "?" + q, headers=HDR)
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace"))
        except Exception as e:                                    # noqa: BLE001
            if k == tries - 1:
                print(f"    !! 失败 {type(e).__name__} {e}", flush=True)
                return {}
            time.sleep(1.0 * (k + 1))
    return {}


def fetch_stock(code, b, e):
    out, page, total = [], 1, 1
    while page <= total:
        p = {
            "industryCode": "*", "pageSize": "50", "industry": "*", "rating": "*",
            "ratingChange": "*", "beginTime": b, "endTime": e, "pageNo": str(page),
            "fields": "", "qType": "0", "orgCode": "", "code": code, "rcode": "",
            "p": str(page), "pageNum": str(page),
        }
        j = _get(p)
        out.extend(j.get("data") or [])
        total = int(j.get("TotalPage") or 1)
        page += 1
        time.sleep(0.2)
    return out


def norm(r):
    return {
        "org": r.get("orgSName") or r.get("orgName") or "",
        "date": (r.get("publishDate") or "")[:10],
        "title": r.get("title") or "",
        "rating": r.get("emRatingName") or "",
        "last_rating": r.get("lastEmRatingName") or "",
        "tp_t": r.get("indvAimPriceT"),
        "tp_l": r.get("indvAimPriceL"),
        "eps26": r.get("predictThisYearEps"),
        "eps27": r.get("predictNextYearEps"),
        "eps28": r.get("predictNextTwoYearEps"),
        "ind": r.get("indvInduName") or "",
        "ic": r.get("infoCode") or "",
        "researcher": r.get("researcher") or "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="b", required=True)
    ap.add_argument("--to", dest="e", required=True)
    ap.add_argument("--mood", default=os.path.join(BASE, "data", "mood_q28.json"))
    ap.add_argument("--out", default=os.path.join(BASE, "data", "mood_stock_reports.json"))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    mood = json.load(open(a.mood, encoding="utf-8"))
    codes = [(str(r["code"]).zfill(6), r["name"]) for r in mood["rows"]]

    hit = {}
    for code, name in codes:
        rs = [norm(r) for r in fetch_stock(code, a.b, a.e)]
        rs.sort(key=lambda x: x["date"], reverse=True)
        if rs:
            hit[code] = rs
        if not a.quiet:
            print(f"── {code} {name}  {len(rs)} 篇")
            for r in rs:
                tp = ""
                if r["tp_t"] or r["tp_l"]:
                    tp = f'  目标价 {r["tp_l"] or "-"}~{r["tp_t"] or "-"}'
                e26 = f'  26E EPS {r["eps26"]}' if r["eps26"] else ""
                print(f'   {r["date"]} {r["org"]:8s} [{r["rating"] or "-"}]'
                      f'{tp}{e26}  {r["title"][:56]}')

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"meta": {"from": a.b, "to": a.e, "n_hit": sum(len(v) for v in hit.values()),
                            "n_covered": len(hit)}, "stocks": hit}, f,
                  ensure_ascii=False, indent=1)
    print(f"\n[out] {a.out}：{len(hit)}/{len(codes)} 只，共 "
          f"{sum(len(v) for v in hit.values())} 篇")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
