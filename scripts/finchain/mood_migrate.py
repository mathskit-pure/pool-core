# -*- coding: utf-8 -*-
"""把第六章 mood_q28.json 从「上一期名单」迁到「最新一期名单」。

分工：
  · 仍在本期的老持仓 → 沿用上一期已人工核验的目标价/情绪/逻辑（研报日期见 tp_src），
    仅把权重换成新一期（价格由 roll_mood.py 用腾讯不复权行情刷）。
  · 新进名单 → 只用**可溯源的事实**填：东财研报中心的研报标题/机构/日期、
    研报 API 给出的目标价（有就写，没有就明确写「均未给目标价」），
    以及三大报表算出来的三季报增速。不做无出处的估值判断。

用法：
    python scripts/finchain/mood_migrate.py [--period 2026-11-02]
"""
import argparse
import csv
import json
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE, FIN_OUT, POOL_DATA  # noqa: E402

MOOD = os.path.join(BASE, "data", "mood_q28.json")
EXT = os.path.join(BASE, "data", "mood19_ext.json")

# 不在本地财报清单（codes_big.json 566 只）里的持仓，三季报数据取自 westock finance
EXTRA_Q3 = {
    "601068": dict(np=4.47, yoy=-9.58, yoyq=-97.54, rev=-28.77, gm=14.46),
    "600517": dict(np=12.79, yoy=-42.72, yoyq=-92.70, rev=0.70, gm=12.91),
    "600703": dict(np=-12.04, yoy=None, yoyq=74.36, rev=-26.05, gm=-11.27),
    "600895": dict(np=4.93, yoy=-19.97, yoyq=-33.70, rev=6.41, gm=55.73),
    "600161": dict(np=4.28, yoy=-47.72, yoyq=-30.65, rev=-7.23, gm=35.32),
}


def q3_facts():
    """从本地三大报表取 2026 三季报（累计归母/同比/单季同比/营收同比/毛利率）。"""
    out = {}
    p = os.path.join(str(POOL_DATA), "data", "raw", "income.csv")
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("EndDate") != "2026-09-30":
                continue
            c = row["code"][-6:]

            def num(k):
                try:
                    return float(row[k])
                except (TypeError, ValueError, KeyError):
                    return None

            np_ = num("NPParentCompanyOwners")
            out[c] = dict(
                np=None if np_ is None else np_ / 1e8,
                yoy=num("NPParentCompanyYOY"),
                yoyq=num("NPParentCompanyYOY_Q"),
                rev=num("OperatingRevenueGrowRate_Q"),
                gm=num("GrossIncomeRatio"),
            )
    out.update(EXTRA_Q3)
    return out


def fmt(v, unit="%", nd=1):
    if v is None:
        return "—"
    return f"{v:+.{nd}f}{unit}"


def fact_line(c, f):
    """把三季报拼成一句可核验的事实陈述。"""
    if not f:
        return "本地财报未覆盖该股（不在 566 只清单内），三季报数据缺失"
    parts = []
    if f["np"] is not None:
        if f["np"] < 0:
            parts.append(f"前三季归母 {f['np']:.2f} 亿（亏损）")
        else:
            parts.append(f"前三季归母 {f['np']:.2f} 亿")
    if f["yoy"] is not None:
        parts.append(f"同比 {fmt(f['yoy'])}")
    if f["yoyq"] is not None:
        parts.append(f"Q3 单季 {fmt(f['yoyq'])}")
    if f["rev"] is not None:
        parts.append(f"单季营收 {fmt(f['rev'])}")
    if f["gm"] is not None:
        parts.append(f"毛利率 {f['gm']:.1f}%")
    return "三季报：" + "、".join(parts)


def report_brief(reps, n=2):
    """最近 N 篇研报的机构/日期/标题要点（标题截断到 30 字）。"""
    if not reps:
        return ""
    out = []
    for r in reps[:n]:
        t = (r.get("title") or "").strip()
        t = t.split("：")[-1] if "：" in t else t
        t = t[:30]
        rt = (r.get("rating") or "").strip()
        out.append(f"{r.get('org')} {str(r.get('date'))[5:]}「{t}」{('·' + rt) if rt else ''}")
    return "；".join(out)


def pick_tp(reps):
    """研报 API 里写明的目标价（可能有高低两个）。只认明确价位。"""
    vals, srcs = [], []
    for r in reps:
        v = r.get("tp_l") if isinstance(r.get("tp_l"), (int, float)) else r.get("tp_t")
        if isinstance(v, (int, float)) and v > 0:
            vals.append(float(v))
            srcs.append(f"{r.get('org')} {str(r.get('date'))[5:]} 目标价 {v:.2f}")
    if not vals:
        return None, None, ""
    return min(vals), max(vals), "；".join(srcs[:3])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    doc = json.load(open(MOOD, encoding="utf-8"))
    ext = json.load(open(EXT, encoding="utf-8")).get("stocks") or {}
    old = {r["code"]: r for r in json.load(
        open(MOOD + ".bak_20261101", encoding="utf-8"))["rows"]}
    facts = q3_facts()

    carried, built = 0, 0
    for r in doc["rows"]:
        c = r["code"]
        st = ext.get(c) or {}
        reps = st.get("reports") or []
        o = old.get(c)

        if o and (o.get("key") or "").strip():
            # 仍在名单内且上期做过人工核验：定价、情绪判断与逻辑原样沿用，
            # 只补一条新的三季报事实（上期文本写于 10-30，个别标的还停在半年报口径）
            r["tp_lo"], r["tp_hi"] = o.get("tp_lo"), o.get("tp_hi")
            r["tp_src"], r["tp_note"] = o.get("tp_src") or "", o.get("tp_note") or ""
            r["mood_level"], r["mood_cls"] = o.get("mood_level") or "", o.get("mood_cls") or "none"
            key = (o.get("key") or "").strip()
            if "三季报" not in key and "前三季" not in key:
                key = f"{key}　{fact_line(c, facts.get(c))}。"
            r["key"], r["risk"] = key, o.get("risk") or ""
            carried += 1
            continue

        lo, hi, src = pick_tp(reps)
        if lo is None:
            r["tp_lo"] = r["tp_hi"] = None
            r["tp_src"] = (f"窗口内 {len(reps)} 篇个股研报均未写明具体目标价"
                           if reps else "近三个月无券商个股研报覆盖")
            r["tp_note"] = "无"
            r["mood_cls"] = "none"
            r["mood_level"] = (f"{len(reps)} 篇覆盖·无目标价" if reps else "零覆盖·无卖定价")
        else:
            r["tp_lo"], r["tp_hi"], r["tp_src"], r["tp_note"] = lo, hi, src, \
                ("单值" if lo == hi else "")
            r["mood_cls"] = "bull" if len(reps) and all(
                (x.get("rating") or "") in ("买入", "增持", "跑赢行业", "推荐") for x in reps) else "split"
            r["mood_level"] = f"目标价 {lo:.2f}" if lo == hi else f"目标价 {lo:.2f}~{hi:.2f}"

        key = [fact_line(c, facts.get(c))]
        if reps:
            key.append(f"卖方 {report_brief(reps)}")
            rt = [x.get("rating") for x in reps if x.get("rating")]
            if rt:
                key.append(f"评级 {'/'.join(sorted(set(rt)))}（{len(reps)} 篇）")
            else:
                key.append(f"窗口内 {len(reps)} 篇研报无明确评级")
        else:
            key.append("近三个月检索不到券商个股研报，无盈利预测与目标价可校验")
        r["key"] = "；".join(key)

        f = facts.get(c) or {}
        risks = []
        if f.get("yoyq") is not None and f["yoyq"] < -10:
            risks.append(f"Q3 单季归母同比 {fmt(f['yoyq'])}，单季动能弱于累计")
        if f.get("np") is not None and f["np"] < 0:
            risks.append("前三季仍亏损，盈利拐点未确认")
        if not reps:
            risks.append("无卖方覆盖，缺少盈利预测校验与目标价锚，回撤时无人托底")
        elif lo is None:
            risks.append("有研报但均未给出目标价，估值锚缺失，情绪判断只能靠评级措辞")
        if not risks:
            risks.append("三季报增速与卖方预期的一致性尚待新研报确认；无目标价可对照现价空间")
        r["risk"] = "；".join(risks) + "。"

        r["flag"], r["flag_txt"], r["flag_at"] = "", "", ""
        built += 1

    print(f"沿用上期核验 {carried} 只 / 按事实重建 {built} 只")
    tp_ok = sum(1 for r in doc["rows"] if r["tp_lo"] is not None)
    rep_ok = sum(1 for r in doc["rows"] if (ext.get(r["code"]) or {}).get("reports"))
    print(f"有可溯源目标价 {tp_ok}/{len(doc['rows'])}；有研报覆盖 {rep_ok}/{len(doc['rows'])}")

    if a.dry_run:
        for r in doc["rows"]:
            print(f'  {r["code"]} {r["name"]:6s} w{r["weight"]:5.2f} {r["mood_cls"]:5s} {r["mood_level"]}')
        return 0
    with open(MOOD, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"[write] {MOOD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
