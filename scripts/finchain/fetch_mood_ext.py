# -*- coding: utf-8 -*-
"""第六章《市场情绪展望》的外部数据补强：三年一致预期 + 研报明细（带原文链接）。

为什么单独一个脚本
------------------
data/mood_q28.json 里的目标价区间、情绪档位、关键逻辑是**人工核验后固化的快照**，
不会随抓取自动变。本脚本只补两类确定性的东西，补完写进 data/mood19_ext.json：

  ① 一致预期（东财 F10 盈利预测 `jgyc` 的「近六月平均」行）
     → 26E / 27E / 28E 的 EPS 与对应 PE、参与预测的机构家数
     这是「未来三年 EPS」列与抽屉里三年预期卡的数据源。
  ② 个股研报明细（东财研报中心 reportapi，近 180 天）
     → 机构 / 日期 / 评级 / 前次评级 / 目标价 / 该份研报的 EPS 预测 / 标题 / infoCode / 研究员
     infoCode 拼成 https://data.eastmoney.com/report/zw_stock.jshtml?infocode=<ic>
     即研报原文页 —— 页面抽屉里每条标题都指向这里，这是「数据源可点开」的落点。

两个坑
------
* reportapi 的 `code=` 参数**不生效**（传了也返回 0 条），只能按 7 天窗口全市场分页
  再本地过滤，180 天约 70 页 / 30 秒。
* F10 的字段是 EPS1=2025A、EPS2=2026E、EPS3=2027E、EPS4=2028E，年份写在
  YEAR1..YEAR4 里，不要按「EPS1 就是今年」理解。

用法：
    python scripts/finchain/fetch_mood_ext.py            # 断点续跑，已抓的不重复
    python scripts/finchain/fetch_mood_ext.py --force    # 全部重抓
"""
import argparse
import json
import os
import sys
import time
from datetime import date, timedelta

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE, DATA  # noqa: E402

MOOD = os.path.join(DATA, "mood_q28.json")
OUT = os.path.join(DATA, "mood19_ext.json")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
RPT = "https://reportapi.eastmoney.com/report/list"
RPT_HDR = dict(UA, Referer="https://data.eastmoney.com/report/stock.jshtml")
F10 = "https://emweb.securities.eastmoney.com/PC_HSF10/ProfitForecast/PageAjax?code={}"
F10_HDR = dict(UA, Referer="https://emweb.securities.eastmoney.com/")

WIN_DAYS = 180


def _n(x):
    try:
        v = float(x)
        return v
    except (TypeError, ValueError):
        return None


def get(url, params, hdr=None, tries=4, timeout=40):
    last = None
    for k in range(tries):
        try:
            r = requests.get(url, params=params, headers=hdr or UA, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:                       # noqa: BLE001
            last = e
            time.sleep(1.0 * (k + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def pre(code):
    return ("SH" if code[0] in "69" else "SZ") + code


def fetch_reports(codes, d0, d1):
    """全市场近 180 天个股研报，本地过滤到目标代码。"""
    raw, cur = [], d0
    while cur <= d1:
        e = min(cur + timedelta(days=6), d1)
        page, total = 1, 1
        while page <= total:
            try:
                j = get(RPT, {
                    "industryCode": "*", "pageSize": "100", "industry": "*",
                    "rating": "*", "ratingChange": "*",
                    "beginTime": cur.isoformat(), "endTime": e.isoformat(),
                    "pageNo": str(page), "qType": "0", "orgCode": "", "code": "",
                    "rcode": "", "p": str(page), "pageNum": str(page),
                }, RPT_HDR, tries=3, timeout=40)
            except Exception as ex:                  # noqa: BLE001
                print(f"  !! {cur} p{page} {ex}", flush=True)
                break
            raw.extend(j.get("data") or [])
            total = int(j.get("TotalPage") or 1)
            page += 1
            time.sleep(0.12)
        cur = e + timedelta(days=1)

    out = {}
    for r in raw:
        code = str(r.get("stockCode") or "")
        if code not in codes:
            continue
        d = (r.get("publishDate") or "")[:10]
        if not d:
            continue
        out.setdefault(code, []).append({
            "org": r.get("orgSName") or "",
            "date": d,
            "title": (r.get("title") or "").strip(),
            "rating": r.get("emRatingName") or "",
            "last_rating": r.get("lastEmRatingName") or "",
            "tp_t": _n(r.get("indvAimPriceT")),
            "tp_l": _n(r.get("indvAimPriceL")),
            "eps1": _n(r.get("predictThisYearEps")),
            "eps2": _n(r.get("predictNextYearEps")),
            "eps3": _n(r.get("predictNextTwoYearEps")),
            "ind": r.get("indvInduName") or "",
            "ic": r.get("infoCode") or "",
            "researcher": r.get("researcher") or "",
        })
    for v in out.values():
        v.sort(key=lambda x: x["date"], reverse=True)
    return out, len(raw)


def fetch_cons(code):
    """东财 F10 一致预期：近六月平均那行。返回 {e25a,e26,e27,e28,y*,n_org}"""
    rec = {"n_org": 0}
    try:
        j = get(F10.format(pre(code)), {}, F10_HDR, tries=3, timeout=25)
    except Exception as e:                           # noqa: BLE001
        return rec, str(e)
    rows = j.get("jgyc") or []
    avg = next((x for x in rows if x.get("ORG_NAME_ABBR") == "近六月平均"), None)
    if not avg:
        return rec, ""
    return {
        "e25a": _n(avg.get("EPS1")), "e26": _n(avg.get("EPS2")),
        "e27": _n(avg.get("EPS3")), "e28": _n(avg.get("EPS4")),
        "y25": avg.get("YEAR1"), "y28": avg.get("YEAR4"),
        "n_org": max(0, len(rows) - 1),
        "pe27_em": _n(avg.get("PE3")),
    }, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略已有结果，全部重抓")
    ap.add_argument("--days", type=int, default=WIN_DAYS)
    a = ap.parse_args()

    with open(MOOD, encoding="utf-8") as f:
        mood = json.load(f)
    rows = mood["rows"]
    codes = [r["code"] for r in rows]
    print(f"持仓 {len(codes)} 只：{' '.join(codes)}", flush=True)

    old = {}
    if os.path.exists(OUT) and not a.force:
        try:
            with open(OUT, encoding="utf-8") as f:
                old = json.load(f).get("stocks") or {}
        except (OSError, ValueError):
            old = {}

    t_date = date.fromisoformat(mood["meta"]["t_date"])
    d1 = t_date
    d0 = t_date - timedelta(days=a.days)
    print(f"[1/2] 研报明细 {d0} ~ {d1}（全市场分页 → 本地过滤）", flush=True)
    reps, n_raw = fetch_reports(set(codes), d0, d1)
    print(f"  全市场 {n_raw} 条 → 命中持仓 {sum(len(v) for v in reps.values())} 条 / "
          f"{len(reps)} 只", flush=True)

    print("[2/2] 一致预期（F10 近六月平均）", flush=True)
    stocks, ok, bad = {}, 0, []
    for i, r in enumerate(rows, 1):
        code = r["code"]
        prev = old.get(code) or {}
        cons = prev.get("cons") if (prev.get("cons") and not a.force) else None
        if not cons:
            cons, err = fetch_cons(code)
            if err:
                bad.append(code)
            time.sleep(0.12)
        stocks[code] = {
            "name": r["name"],
            "cons": cons or {"n_org": 0},
            "reports": reps.get(code, []),
        }
        if (cons or {}).get("e26"):
            ok += 1
        if i % 10 == 0:
            print(f"  {i}/{len(rows)}  有一致预期 {ok}", flush=True)

    payload = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "win_from": d0.isoformat(), "win_to": d1.isoformat(),
            "n": len(codes), "n_cons": ok,
            "n_with_report": sum(1 for v in stocks.values() if v["reports"]),
            "sources": {
                "consensus": "东方财富 F10 盈利预测（近六月平均）",
                "reports": "东方财富研报中心 reportapi（近 180 天个股研报）",
                "quote": "腾讯行情 qt.gtimg.cn（T 日不复权收盘）",
            },
        },
        "stocks": stocks,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"完成 → {OUT}", flush=True)
    print(f"  有一致预期 {ok}/{len(codes)}；有研报 "
          f"{payload['meta']['n_with_report']}/{len(codes)}；F10 失败 {len(bad)}", flush=True)
    for code, v in stocks.items():
        c = v["cons"]
        print(f"  {code} {v['name']:<6} EPS26/27/28 = {c.get('e26')}/{c.get('e27')}/{c.get('e28')}"
              f"  n_org={c.get('n_org')}  研报 {len(v['reports'])} 条", flush=True)


if __name__ == "__main__":
    main()
