# -*- coding: utf-8 -*-
"""抓取指定日期窗口内的个股研报（东方财富研报中心公开接口，无需 key）。

用途：第六章《市场情绪展望》滚动更新时，逐只核对「上一基准日之后」的新研报。
输出 data/mood_new_reports.json，并按持仓代码打印明细（含目标价、评级、机构、标题）。

用法：
    python scripts/finchain/fetch_new_reports.py --from 2026-10-23 --to 2026-10-27
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
from paths import BASE, DATA  # noqa: E402

URL = "https://reportapi.eastmoney.com/report/list"
HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
}


def _get(url, params, timeout=40, tries=3):
    q = urllib.parse.urlencode(params)
    for k in range(tries):
        try:
            req = urllib.request.Request(url + "?" + q, headers=HDR)
            raw = urllib.request.urlopen(req, timeout=timeout).read()
            return json.loads(raw.decode("utf-8", "replace"))
        except Exception as e:                                    # noqa: BLE001
            if k == tries - 1:
                print(f"    !! 失败 {type(e).__name__} {e}", flush=True)
                return {}
            time.sleep(1.0 * (k + 1))
    return {}


def fetch_range(b, e, page_size=100):
    """拉 [b,e] 全市场个股研报，按 TotalPage 翻页。"""
    out, page, total = [], 1, 1
    while page <= total:
        p = {
            "industryCode": "*", "pageSize": str(page_size), "industry": "*",
            "rating": "*", "ratingChange": "*", "beginTime": b, "endTime": e,
            "pageNo": str(page), "fields": "", "qType": "0", "orgCode": "",
            "code": "", "rcode": "", "p": str(page), "pageNum": str(page),
        }
        j = _get(URL, p)
        out.extend(j.get("data") or [])
        total = int(j.get("TotalPage") or 1)
        page += 1
        time.sleep(0.25)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="b", required=True)
    ap.add_argument("--to", dest="e", required=True)
    ap.add_argument("--mood", default=os.path.join(BASE, "data", "mood_q28.json"))
    ap.add_argument("--out", default=os.path.join(BASE, "data", "mood_new_reports.json"))
    a = ap.parse_args()

    mood = json.load(open(a.mood, encoding="utf-8"))
    codes = {str(r["code"]).zfill(6): r["name"] for r in mood["rows"]}

    print(f"[pull] {a.b} ~ {a.e} 全市场研报 ...", flush=True)
    recs = fetch_range(a.b, a.e)
    print(f"[pull] 全市场 {len(recs)} 篇", flush=True)

    hit = {}
    for r in recs:
        c = str(r.get("stockCode") or "").zfill(6)
        if c not in codes:
            continue
        hit.setdefault(c, []).append({
            "org": r.get("orgSName") or r.get("orgName") or "",
            "date": (r.get("publishDate") or "")[:10],
            "title": r.get("title") or "",
            "rating": r.get("emRatingName") or "",
            "last_rating": r.get("lastEmRatingName") or "",
            "tp_t": r.get("indvAimPriceT"),
            "tp_l": r.get("indvAimPriceL"),
            "ind": r.get("indvInduName") or "",
            "ic": r.get("infoCode") or "",
            "researcher": r.get("researcher") or "",
        })

    for v in hit.values():
        v.sort(key=lambda x: (x["date"], x["org"]), reverse=True)

    out = {"meta": {"from": a.b, "to": a.e, "n_all": len(recs),
                    "n_hit": sum(len(v) for v in hit.values()),
                    "n_covered": len(hit)}, "stocks": hit}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"[out] {a.out}：{len(hit)}/{len(codes)} 只有新研报，合计 {out['meta']['n_hit']} 篇\n")
    for c, name in codes.items():
        rs = hit.get(c, [])
        print(f"── {c} {name}  {len(rs)} 篇")
        for r in rs:
            tp = ""
            if r["tp_t"] or r["tp_l"]:
                tp = f'  目标价 {r["tp_l"] or ""}~{r["tp_t"] or ""}'
            print(f'   {r["date"]} {r["org"]:6s} [{r["rating"] or "-"}] {tp}  {r["title"][:60]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
