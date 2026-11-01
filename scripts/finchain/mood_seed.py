# -*- coding: utf-8 -*-
"""按最新一期质量Top28组合持仓，重建 data/mood_q28.json 的骨架。

背景：第六章的研报内容（目标价、情绪判断）没法自动抓，历来由人工检索后固化。
但每次换期，名单一变，旧快照的「个股/权重」就与五章对不上，页面会自相矛盾。
本脚本只做**确定性**的三件事：

  ① 名单与权重：从 out15/holdings_15.csv 最新一期直接取（与五章同源）
  ② 价格与涨跌：置空，交给 roll_mood.py 用腾讯行情（不复权）刷
  ③ 目标价与情绪：置空占位，由 fetch_mood_ext.py 拉到的研报明细回填

回填规则（build_rows.py 里实现，逐条可溯源）：
  目标价只取研报里**写明的具体价位**，并标注机构与日期；无价位的整行标「无法溯源」。

用法：
    python scripts/finchain/mood_seed.py                 # 生成骨架（覆盖 data/mood_q28.json）
    python scripts/finchain/mood_seed.py --dry-run       # 只看会写出什么
"""
import argparse
import json
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE, FIN_OUT  # noqa: E402

OUT = os.path.join(BASE, "data", "mood_q28.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report-from", default=None)
    ap.add_argument("--report-to", default=None)
    a = ap.parse_args()

    h = pd.read_csv(os.path.join(FIN_OUT, "holdings_15.csv"), dtype={"code": str})
    q = h[h["combo"] == "Q28"]
    last = sorted(q["rebal_date"].unique())[-1]
    cur = q[q["rebal_date"] == last].sort_values("weight", ascending=False)
    name = json.load(open(os.path.join(FIN_OUT, "name_map.json"), encoding="utf-8"))

    rows = []
    for r in cur.itertuples():
        c = r.code[-6:]
        rows.append({
            "code": c, "name": name.get(r.code, name.get(c, c)),
            "weight": round(float(r.weight) * 100, 2),
            "price": None, "chg": None,
            "tp_lo": None, "tp_hi": None, "tp_src": "", "tp_note": "",
            "mood_level": "待核对", "mood_cls": "none",
            "key": "", "risk": "",
            "flag": "", "flag_txt": "", "flag_at": "",
        })

    rf = a.report_from or (pd.Timestamp(last) - pd.Timedelta(days=92)).strftime("%Y-%m-%d")
    rt = a.report_to or last
    doc = {
        "meta": {
            "rebal_date": last, "t_date": rt,
            "report_from": rf, "report_to": rt,
            "n_holdings": len(rows),
            "source": f"{rf} ~ {rt} 券商研报；股价为该日收盘（不复权，腾讯行情）",
            "last_roll": "", "n_flag": 0,
        },
        "rows": rows,
    }
    print(f"最新一期 {last}：{len(rows)} 只，权重合计 {sum(r['weight'] for r in rows):.2f}%")
    print(f"研报窗口 {rf} ~ {rt}")
    if a.dry_run:
        print(json.dumps(doc["meta"], ensure_ascii=False, indent=1))
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"[write] {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
