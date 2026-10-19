# -*- coding: utf-8 -*-
"""抓取申万三级行业（2021版）成分 → FIN_SW。

原 qmj_fraud/src/s2_sw.py，改动：
  1. 路径走 paths.py（缓存目录 FIN_ROOT/sw3，输出 FIN_SW）
  2. 单个行业失败重试后仍失败时，**不阻塞整体**（history: legulegu 曾整站卡死）
  3. 汇总时输出覆盖率，便于判断是否需要重跑

用法：
    python scripts/finchain/fetch_sw.py
"""
import csv
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_ROOT, FIN_SW  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from em import http_get  # noqa: E402

OV = "https://legulegu.com/stockdata/sw-industry-overview"
CONS = "https://legulegu.com/stockdata/index-composition?industryCode=%s"
CACHE = FIN_ROOT / "sw3"


def parse_l3(html):
    i = html.find('id="level3Items"')
    seg = html[i:] if i > 0 else html
    items, seen = [], set()
    for m in re.finditer(r'<div id="(\d{6}\.SI)"', seg):
        code = m.group(1)
        if code in seen:
            continue
        seen.add(code)
        blk = seg[m.end():m.end() + 4000]
        nm = re.search(r'lg-industries-item-number">\s*([^<(（]+)', blk)
        items.append((code, nm.group(1).strip() if nm else ""))
    return items


def fetch_one(code):
    fp = os.path.join(CACHE, code + ".csv")
    if os.path.exists(fp) and os.path.getsize(fp) > 30:
        return 0
    for attempt in range(4):
        try:
            h = http_get(CONS % code, headers={"Referer": "https://legulegu.com/"},
                         tries=2, timeout=60)
            i = h.find('index-basic-composition-item')
            seg = h[i:] if i > 0 else ""
            codes = [m.group(1) for m in
                     re.finditer(r'data-stock-code="(\d{6})\.(SH|SZ|BJ)"', seg)]
            tmp = fp + ".tmp"
            with open(tmp, "w", newline="", encoding="utf-8") as f:
                f.write("code\n" + "\n".join(sorted(set(codes))) + "\n")
            os.replace(tmp, fp)
            return len(set(codes))
        except Exception:
            time.sleep(2.0 * (attempt + 1))
    return -1


def main():
    os.makedirs(CACHE, exist_ok=True)
    html = http_get(OV, headers={"Referer": "https://legulegu.com/"}, timeout=90)
    items = parse_l3(html)
    print("L3 industries:", len(items), flush=True)
    if not items:
        raise SystemExit("!! 申万三级行业列表解析为空，站点结构可能变了")
    json.dump(items, open(FIN_ROOT / "sw3_list.json", "w", encoding="utf-8"),
              ensure_ascii=False)

    from concurrent.futures import ThreadPoolExecutor
    t0 = time.time()
    done = [0]
    fails = []

    def work(it):
        code, _ = it
        n = fetch_one(code)
        done[0] += 1
        if done[0] % 40 == 0:
            print("  %d/%d %.0fs" % (done[0], len(items), time.time() - t0), flush=True)
        return code, n

    with ThreadPoolExecutor(max_workers=5) as ex:
        for code, n in ex.map(work, items):
            if n < 0:
                fails.append(code)
    if fails:
        print("!! 抓取失败 %d 个行业：%s" % (len(fails), fails[:20]), flush=True)

    name_map = dict(items)
    out = []
    for code, _ in items:
        fp = os.path.join(CACHE, code + ".csv")
        if not os.path.exists(fp):
            continue
        with open(fp, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                out.append({"code": r["code"], "l3code": code, "l3name": name_map[code]})
    if not out:
        raise SystemExit("!! 申万三级映射为空，未写盘")
    tmp = str(FIN_SW) + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["code", "l3code", "l3name"])
        w.writeheader()
        w.writerows(out)
    os.replace(tmp, FIN_SW)
    print("saved %d 行 / %d 只 -> %s" % (len(out), len({r["code"] for r in out}), FIN_SW),
          flush=True)


if __name__ == "__main__":
    main()
