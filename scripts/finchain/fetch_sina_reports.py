# -*- coding: utf-8 -*-
"""按股票抓取研报清单 + 详情（新浪财经研报库，公开 HTML，无需 key）。

为什么不用东财 reportapi：实测其「个股研报」列表严重欠覆盖
（爱美客 2026 年全年只回 8 篇，缺 09-17 华创等；601001 缺 09-02 国泰海通），
而新浪研报库同一只票能回到 30+ 篇且含机构全称、日期、研究员，更适合逐只核对。
评级/目标价/摘要再从详情页抓。

用法：
    python scripts/finchain/fetch_sina_reports.py --from 2026-10-23 --to 2026-10-27
    python scripts/finchain/fetch_sina_reports.py --from 2026-10-23 --to 2026-10-27 --detail
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from paths import BASE  # noqa: E402

LIST = ("https://stock.finance.sina.com.cn/stock/go.php/vReport_List/"
        "kind/search/index.phtml?symbol={sym}&t1=all&page={page}")
DETAIL = "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/{rid}/index.phtml"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

RE_ROW = re.compile(
    r'<td class="tal f14">.*?title="(.*?)".*?rptid/(\d+)/index\.phtml.*?'
    r'<td>([^<]*)</td>\s*<td>(\d{4}-\d\d-\d\d)</td>.*?'
    r'fname05"><span>(.*?)</span>', re.S)


def sym_of(code):
    c = str(code).zfill(6)
    return ("sh" if c[0] in "69" else "sz") + c


def get(url, tries=3, timeout=30):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            return urllib.request.urlopen(req, timeout=timeout).read().decode("gb18030", "replace")
        except Exception as e:                                    # noqa: BLE001
            if k == tries - 1:
                print(f"    !! {type(e).__name__} {e}", flush=True)
                return ""
            time.sleep(1.0 * (k + 1))
    return ""


def list_reports(code, date_from, max_page=3):
    """返回该票 date >= date_from 的研报行（按日期倒序，遇到更早的即停）。"""
    rows, stop = [], False
    for page in range(1, max_page + 1):
        h = get(LIST.format(sym=sym_of(code), page=page))
        if not h:
            break
        found = RE_ROW.findall(h)
        if not found:
            break
        for title, rid, kind, d, org in found:
            if d < date_from:
                stop = True
                continue
            rows.append({"code": str(code).zfill(6), "title": title.strip(),
                         "rptid": rid, "kind": kind.strip(), "date": d,
                         "org": org.strip()})
        if stop:
            break
        time.sleep(0.2)
    return rows


def _text(s):
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).replace("&nbsp;", " ").strip()


def detail(rid):
    """抓详情页：评级、目标价、摘要正文（有就取）。"""
    h = get(DETAIL.format(rid=rid))
    out = {"rating": "", "tp": "", "pe": "", "abstract": ""}
    if not h:
        return out
    body = re.search(r'<div class="blk_container">(.*?)</div>\s*</div>', h, re.S)
    txt = _text(body.group(1)) if body else _text(h)

    m = re.search(r"投资评级[^\u4e00-\u9fa5]{0,4}(买入|增持|推荐|强烈推荐|谨慎推荐|中性|持有|减持|卖出|跑赢行业|优于大市|审慎增持)", txt)
    if not m:
        m = re.search(r"(买入|增持|强烈推荐|谨慎推荐|跑赢行业|中性|减持)", txt[:600])
    if m:
        out["rating"] = m.group(1)

    m = re.search(r"目标价[格]?[^\d]{0,8}([\d.]+)(?:\s*[-~—至]\s*([\d.]+))?\s*元", txt)
    if m:
        out["tp"] = f"{m.group(1)}~{m.group(2)}" if m.group(2) else m.group(1)

    m = re.search(r"(20\d\d)[Ee]?\s*年?\s*(?:PE|市盈率)[^\d]{0,6}([\d.]+)\s*[xX倍]", txt)
    if m:
        out["pe"] = f"{m.group(1)}E {m.group(2)}x"

    out["abstract"] = txt[:2200]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="b", required=True)
    ap.add_argument("--to", dest="e", required=True)
    ap.add_argument("--mood", default=os.path.join(BASE, "data", "mood_q28.json"))
    ap.add_argument("--out", default=os.path.join(BASE, "data", "mood_sina_reports.json"))
    ap.add_argument("--detail", action="store_true", help="逐篇抓详情（评级/目标价/摘要）")
    a = ap.parse_args()

    mood = json.load(open(a.mood, encoding="utf-8"))
    codes = [(str(r["code"]).zfill(6), r["name"]) for r in mood["rows"]]

    hit = {}
    for code, name in codes:
        rs = [x for x in list_reports(code, a.b) if x["date"] <= a.e]
        if a.detail:
            for x in rs:
                x.update(detail(x["rptid"]))
                time.sleep(0.2)
        if rs:
            hit[code] = rs
        print(f"── {code} {name}  {len(rs)} 篇")
        for x in rs:
            extra = ""
            if a.detail:
                extra = f'  评级 {x["rating"] or "-"}  {x["tp"] or ""}'
            print(f'   {x["date"]} {x["org"][:10]:10s} {x["title"][:52]}{extra}')

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"meta": {"from": a.b, "to": a.e, "n": sum(len(v) for v in hit.values()),
                            "n_covered": len(hit)}, "stocks": hit}, f,
                  ensure_ascii=False, indent=1)
    print(f"\n[out] {a.out}：{len(hit)}/{len(codes)} 只有新研报，共 "
          f"{sum(len(v) for v in hit.values())} 篇")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
