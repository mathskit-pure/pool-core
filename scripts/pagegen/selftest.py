# -*- coding: utf-8 -*-
"""验证器的自检：故意注入故障，确认每一层闸门都会真的拦下来。

一个只会说"通过"的验证器等于没有验证器。这里对正常数据包做 6 个定向破坏，
每个都必须被对应层拦下；只要有一个漏过，说明该层检查是摆设。

用法：``python scripts/pagegen/selftest.py [--data <page_data.json>]``
退出码：0 全部按预期拦下 / 1 存在漏检
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from paths import DATA, WORK15  # noqa: E402

from pagegen.render import build  # noqa: E402
from pagegen.verify import verify  # noqa: E402


def cases(base: dict, html: str):
    """返回 [(名称, 期望出错的层, 变异后的 (html, data))]。"""
    out = []

    # 1 数据层：声明条数与明细不符
    d = copy.deepcopy(base)
    d["pools"][-1]["n"] += 1
    out.append(("股池条数被改（+1）", "data", (html, d)))

    # 2 数据层：Top28 少一只
    d = copy.deepcopy(base)
    d["q28"] = d["q28"][:-1]
    out.append(("Top28 少一只", "data", (html, d)))

    # 3 数据层：净值序列被截断
    d = copy.deepcopy(base)
    k = "CSFM(N=20, κ=1.5)"
    d["curve"]["series"][k] = d["curve"]["series"][k][:-5]
    out.append(("净值序列被截断 5 个点", "data", (html, d)))

    # 4 数据层：绩效表数字被篡改（互校应发现与曲线不符）
    d = copy.deepcopy(base)
    for r in d["summary"]:
        if r["k"] == "质量Top28 v2" and r["seg"] == "全期":
            r["ann"] = (r["ann"] or 0) + 0.10
    out.append(("绩效表年化被抬高 10pct", "data", (html, d)))

    # 5 结构层：少一个闭合 </div>
    out.append(("少一个 </div>", "structural", (html.replace("</div>", "", 1), base)))

    # 6 脚本层：把数据变量改名，draw() 里就会炸
    out.append(("图表脚本变量被改名", "script", (html.replace("var D=", "var DD=", 1), base)))

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    a = ap.parse_args()
    p = a.data or str(DATA / "page_data.json")
    if not os.path.exists(p):
        p = os.path.join(str(WORK15), "out15", "page_data.json")
    base = json.load(open(p, encoding="utf-8"))
    html = build(base)

    ok0, rep0 = verify(html, base)
    print(f"[基线] {'通过' if ok0 else '竟然不通过'}（数据包 {os.path.basename(p)}）")
    if not ok0:
        for k in ("structural", "script", "data"):
            for it in rep0[k]:
                print(f"   ✗ {it}")
        return 1

    miss = []
    for name, layer, (h, d) in cases(base, html):
        ok, rep = verify(h, d)
        hit = bool(rep[layer])
        mark = "拦下" if hit else "漏检"
        print(f"[{'OK' if hit else '!!'}] {name:<24} → {layer} 层{mark}")
        if hit:
            print(f"       {rep[layer][0]}")
        else:
            miss.append(name)

    print("=" * 62)
    if miss:
        print(f"自检失败：{len(miss)} 个故障未被拦下 —— {miss}")
        return 1
    print(f"自检通过：{len(cases(base, html))} 个注入故障全部被对应层拦下")
    return 0


if __name__ == "__main__":
    sys.exit(main())
