# -*- coding: utf-8 -*-
"""公共 HTTP 工具：东财 datacenter / 腾讯行情，带重试与限速。

原属 qmj_fraud/src/em.py，迁入 finchain 后唯一的改动是 DATA 指向
``paths.FIN_ROOT``，不再依赖脚本所在目录的兄弟目录布局。
"""
import json
import os
import random
import ssl
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_FUND, FIN_MON, FIN_PX, FIN_ROOT  # noqa: E402

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

DATA = str(FIN_ROOT)
for _sub in (FIN_FUND, FIN_PX, FIN_MON, FIN_ROOT / "wk", FIN_ROOT / "out", FIN_ROOT / "sw3"):
    os.makedirs(_sub, exist_ok=True)


def http_get(url, headers=None, timeout=45, tries=5, encoding="utf-8"):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=h)
            raw = urllib.request.urlopen(req, timeout=timeout, context=CTX).read()
            return raw.decode(encoding, errors="ignore")
        except Exception as e:  # noqa
            last = e
            time.sleep(0.8 * (k + 1) + random.random() * 0.4)
    raise last


def em_query(report_name, flt=None, columns="ALL", page_size=500, max_pages=40,
             sort=None, sort_type=-1):
    """东财 datacenter 通用分页查询，返回 list[dict]。"""
    out = []
    page = 1
    while page <= max_pages:
        params = {
            "reportName": report_name, "columns": columns,
            "pageSize": page_size, "pageNumber": page,
        }
        if flt:
            params["filter"] = flt
        if sort:
            params["sortColumns"] = sort
            params["sortTypes"] = sort_type
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get?" + urllib.parse.urlencode(params)
        txt = http_get(url, headers={"Referer": "https://data.eastmoney.com/"})
        try:
            d = json.loads(txt)
        except Exception:
            break
        res = d.get("result") or {}
        rows = res.get("data") or []
        out.extend(rows)
        total_pages = res.get("pages") or 0
        if not rows or len(rows) < page_size or (total_pages and page >= total_pages):
            break
        page += 1
    return out


TQ_BASE = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?"


def tencent_kline(code, period="day", start="2009-01-01", end="2026-10-16",
                  adj="hfq", count=800):
    """腾讯 K 线（备用域名，支持向后分页）。code 形如 sh600519。
    adj: hfq/qfq/''(不复权)。返回按日期升序的 list[list]。"""
    rows = {}
    cur_end = end
    for _ in range(14):
        p = "%s,%s,,%s,%d,%s" % (code, period, cur_end, count, adj)
        try:
            txt = http_get(TQ_BASE + urllib.parse.urlencode({"param": p}),
                           headers={"Referer": "https://gu.qq.com/"}, tries=3)
            d = json.loads(txt)
        except Exception:
            break
        if d.get("msg"):
            break
        node = (d.get("data") or {}).get(code) or {}
        arr = None
        for v in node.values():
            if isinstance(v, list) and v and isinstance(v[0], list):
                arr = v
                break
        if not arr:
            break
        for r in arr:
            rows[r[0]] = r
        first = arr[0][0]
        if first <= start or len(arr) < count:
            break
        cur_end = first
    return [rows[k] for k in sorted(rows)]
