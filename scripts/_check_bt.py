# -*- coding: utf-8 -*-
"""临时校验脚本：解析页面里的 var BT= 数据块并打印摘要。"""
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def bt_span(s):
    a = s.find("var BT=")
    i = s.index("{", a)
    depth = 0
    instr = esc = False
    for k in range(i, len(s)):
        ch = s[k]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
        else:
            if ch == '"':
                instr = True
            elif ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0:
                    return i, k + 1
    raise SystemExit("BT 括号不匹配")


def main(path):
    s = open(path, encoding="utf-8", errors="replace").read()
    i0, i1 = bt_span(s)
    bt = json.loads(s[i0:i1])
    print("order:", bt["order"])
    print("label:", bt["label"])
    print("dates:", len(bt["dates"]), bt["dates"][0], "→", bt["dates"][-1])
    for key in bt["order"]:
        ser = bt["series"][key]
        n0 = sum(1 for v in ser if v is None)
        print("  %-22s len=%d nulls=%d first=%s last=%s"
              % (key, len(ser), n0, ser[0], ser[-1]))
    # 统计表
    mk = s.find("累计收益")
    ts = s.rfind("<table", 0, mk)
    te = s.find("</table>", mk)
    tbl = s[ts:te]
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", tbl, re.S)
    print("\n统计表：")
    for tr in rows:
        cells = re.findall(r"<(?:td|th)[^>]*>(.*?)</(?:td|th)>", tr, re.S)
        txt = [re.sub(r"<[^>]+>|<!--.*?-->", "", c).strip() for c in cells]
        if txt:
            print("  ", " | ".join(txt))


if __name__ == "__main__":
    main(sys.argv[1])
