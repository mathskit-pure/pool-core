# -*- coding: utf-8 -*-
"""生成页面第六模块《市场情绪展望》的 HTML 片段。

数据源：data/mood_q28.json（人工研报检索结果的结构化沉淀）
产物：data/mood_block.html（插入到主页面页脚之前）

为什么不放进 pack_page.py 的数据流：研报目标价与情绪研判无法自动抓取，
属于「人工核验后固化的快照」，因此单独成块、按调仓期更新一次。
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_JSON = os.path.join(BASE, "data", "mood_q28.json")
DEFAULT_OUT = os.path.join(BASE, "data", "mood_block.html")


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def rich(s):
    """转义后把 **关键句** 变成红色加粗。

    「不被表面文字蒙蔽」这件事没法靠脚本判断，但「哪一句是关键」可以让
    写数据的人（或滚动任务里的模型）用 ** 标出来，渲染层负责把它染红。
    这样标红位置始终跟着内容走，不会因为改文案而错位。
    """
    out = esc(s)
    return re.sub(r"\*\*(.+?)\*\*", r'<b class="hl">\1</b>', out)


# 变化类型 → (符号, 短语)。三种都用红色，靠符号区分方向：
# 用户要的是「重大变化就标红」，不区分好坏，但得让人一眼看出往哪边变。
FLAG_META = {
    "down": ("▼", "情绪下调"),
    "up": ("▲", "情绪上调"),
    "logic": ("⚡", "逻辑变化"),
    "none": ("○", "转为无覆盖"),
}


def pct(x):
    return f"{x:+.1f}%"


def implied(price, lo, hi):
    """隐含空间；返回 (文本, 方向类)"""
    if lo is None:
        return "—", "mut"
    if hi is None or abs(hi - lo) < 1e-9:
        v = (lo / price - 1) * 100
        return f"隐含 {pct(v)}", ("up" if v >= 0 else "dn")
    a = (lo / price - 1) * 100
    b = (hi / price - 1) * 100
    cls = "up" if (a + b) / 2 >= 0 else "dn"
    return f"隐含 {pct(a)} ~ {pct(b)}", cls


def tp_cell(r):
    lo, hi = r.get("tp_lo"), r.get("tp_hi")
    if lo is None:
        body = f'<span class="mut">未给出目标价</span>'
    elif hi is None or abs(hi - lo) < 1e-9:
        body = f'<b>{lo:.2f}</b> <span class="mut">{"单值" if r.get("tp_note") == "单值" else ""}</span>'
    else:
        body = f'<b>{lo:.2f} ~ {hi:.2f}</b>'
    imp, icls = implied(r["price"], lo, hi)
    return (f'{body}<br><span class="{icls} mood-imp">{imp}</span>'
            f'<div class="mood-src">{esc(r["tp_src"])}</div>')


def flag_html(r):
    """行内「重大变化」红标：类型徽标 + 一句话说明 + 变化日期。"""
    f = (r.get("flag") or "").strip()
    if not f:
        return ""
    icon, label = FLAG_META.get(f, ("●", "变化"))
    txt = esc(r.get("flag_txt") or "")
    at = esc(r.get("flag_at") or "")
    when = f'<u>{at}</u>' if at else ""
    return (f'<div class="mood-flag mf-{esc(f)}"><b>{icon} {label}</b>'
            f'{("　" + txt) if txt else ""}{when}</div>')


def row_html(r):
    chg_cls = "up" if r["chg"] >= 0 else "dn"
    hot = " mood-hot" if (r.get("flag") or "").strip() else ""
    return f"""<tr class="{hot.strip()}">
<td class="mood-stk"><b>{esc(r['name'])}</b><span class="mood-code">{esc(r['code'])} · {r['weight']:.2f}%</span></td>
<td class="mood-px"><b>{r['price']:.2f}</b><span class="{chg_cls}">{r['chg']:+.2f}%</span></td>
<td class="mood-tp">{tp_cell(r)}</td>
<td class="mood-md">{flag_html(r)}<span class="mood-tag mt-{r['mood_cls']}">{esc(r['mood_level'])}</span>
<div class="mood-key">{rich(r['key'])}</div>
<div class="mood-risk"><b>风险</b>　{rich(r['risk'])}</div></td>
</tr>"""



def stats(rows):
    has = [r for r in rows if r.get("tp_lo") is not None]
    mids = []
    for r in has:
        lo = r["tp_lo"]
        hi = r["tp_hi"] if r.get("tp_hi") is not None else lo
        mids.append(((lo + hi) / 2 / r["price"] - 1) * 100)
    mids.sort()
    med = mids[len(mids) // 2] if len(mids) % 2 else (mids[len(mids) // 2 - 1] + mids[len(mids) // 2]) / 2
    none = [r for r in rows if r.get("tp_lo") is None]
    down = [r for r in rows if "下调" in (r.get("tp_src") or "")]
    flagged = [r for r in rows if (r.get("flag") or "").strip()]
    return {
        "n": len(rows), "n_has": len(has), "n_none": len(none),
        "median": med, "down": down, "mids": mids,
        "n_flag": len(flagged), "flagged": flagged,
    }


CSS = """
<style>
/*MOOD-CSS-BEGIN*/
.mood-note{background:#fbfcfd;border:1px solid var(--bd);border-left:3px solid var(--ac2);
 border-radius:8px;padding:10px 14px;font-size:13px;color:#4b5563;margin:10px 0 14px;line-height:1.72}
.mood-note b{color:var(--tx)}
.mood-kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.mood-kpi .k{border:1px solid var(--bd);border-radius:9px;padding:9px 12px;background:#fcfcfd}
.mood-kpi .k i{display:block;font-style:normal;font-size:12px;color:var(--mut);margin-bottom:3px}
.mood-kpi .k b{font-size:19px;font-variant-numeric:tabular-nums}
.mood-kpi .k u{display:block;text-decoration:none;font-size:11px;color:#9ca3af;margin-top:2px}
.mood-wrap{overflow-x:auto;border:1px solid var(--bd);border-radius:9px}
table.mood{width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed;min-width:920px}
table.mood th{background:#f3f4f6;font-weight:600;text-align:left;padding:9px 11px;
 border-bottom:1px solid var(--bd);font-size:12.5px;color:#374151;white-space:nowrap}
table.mood td{padding:11px;border-bottom:1px solid #eef0f2;vertical-align:top}
table.mood tr:last-child td{border-bottom:none}
table.mood tbody tr:hover td{background:#fafbfc}
.mood-stk b{font-size:14px;display:block;line-height:1.35}
.mood-code{display:block;font-size:11.5px;color:#9ca3af;margin-top:3px;font-variant-numeric:tabular-nums}
.mood-px b{font-size:15px;display:block;font-variant-numeric:tabular-nums}
.mood-px span{display:block;font-size:12px;margin-top:2px;font-variant-numeric:tabular-nums}
.mood-tp b{font-variant-numeric:tabular-nums}
.mood-imp{display:block;font-size:12px;margin-top:2px;font-weight:600}
.mood-src{font-size:11.5px;color:#9ca3af;line-height:1.55;margin-top:5px}
.mood-tag{display:inline-block;border-radius:5px;padding:2px 8px;font-size:11.5px;
 font-weight:600;line-height:1.6;margin-bottom:6px}
.mt-bull{background:#fdecea;color:#c0392b;border:1px solid #f5c6c2}
.mt-split{background:#fff7ed;color:#b45309;border:1px solid #fde3c4}
.mt-warn{background:#eef2f7;color:#3f4a5a;border:1px solid #dbe3ec}
.mt-none{background:#f3f4f6;color:#6b7280;border:1px solid #e5e7eb}
.mood-key{font-size:12.5px;line-height:1.72;color:#374151}
.mood-risk{font-size:12px;line-height:1.62;color:#7b4a4a;margin-top:6px;
 padding-top:6px;border-top:1px dashed #eceef1}
.mood-risk b{color:#c0392b;font-weight:600}
.mood-sum{margin-top:16px;border:1px solid var(--bd);border-radius:9px;
 background:#fbfcfd;padding:12px 15px}
.mood-sum h4{margin:0 0 8px;font-size:13.5px;color:var(--tx)}
.mood-sum ol{margin:0;padding-left:20px;font-size:13px;line-height:1.85;color:#374151}
.mood-sum li{margin-bottom:5px}
.mood-sum li b{color:var(--tx)}
@media(max-width:760px){table.mood{min-width:0}table.mood th:nth-child(2),
 table.mood td:nth-child(2){display:none}}
/* 滚动更新：情绪或逻辑出现重大变化的那一行整体标红（红底 + 左侧红边 + 红色徽标）*/
.mood-kpi .k b.hotv{color:#c0392b}
.mood-hot td{background:#fffafa}
.mood-hot td:first-child{box-shadow:inset 3px 0 0 #c0392b}
.mood-hot:hover td{background:#fff5f3}
.mood-flag{display:block;font-size:11.5px;line-height:1.6;color:#c0392b;background:#fdf1ef;
 border:1px solid #f6cfc9;border-radius:5px;padding:4px 8px;margin-bottom:6px}
.mood-flag b{color:#a52a1e;font-weight:700}
.mood-flag u{text-decoration:none;color:#b06a60;margin-left:6px;font-variant-numeric:tabular-nums}
.mood-flag.mf-up{border-color:#f0b8b0}
.mood-flag.mf-up b{color:#c0392b}
b.hl{color:#c0392b;font-weight:700}
/*MOOD-CSS-END*/
</style>
"""


def build(d):
    m = d["meta"]
    rows = d["rows"]
    s = stats(rows)

    kpis = [
        ("有明确目标价", f'{s["n_has"]} / {s["n"]}', "研报中写出的具体价位"),
        ("目标价中位隐含空间", pct(s["median"]), "按区间中值对 T 日收盘价"),
        ("目标价较前次下调", f'{len(s["down"])} 只', "研报中括号内标注的前值更高"),
        ("无个股研报覆盖", f'{s["n_none"]} 只', "含无评级、有评级无价位、价位无法溯源"),
    ]
    if s["n_flag"]:
        kpis.insert(0, ("本期重大变化", f'{s["n_flag"]} 只',
                        "情绪或逻辑较上次更新有实质变动，行内标红"))
    kpi_html = "".join(
        f'<div class="k"><i>{esc(a)}</i><b{(" class=\'hotv\'" if a == "本期重大变化" else "")}>{esc(b)}</b><u>{esc(c)}</u></div>'
        for a, b, c in kpis)

    note = (
        f'本表列出质量 Top28 组合<b>最新一期（{m["rebal_date"]} 调仓）</b>的全部 {m["n_holdings"]} 只持仓，'
        f'股价为 <b>T 日 {m["t_date"]}</b> 收盘（前复权）。目标价取自 <b>{m["report_from"]} ~ {m["report_to"]}</b>'
        f'（本次调仓前后一个完整季报窗口）券商研报中<b>写明的具体价位</b>，并保留其发布机构与日期。'
        f'<br>「市场情绪」一列不复述研报标题，而是拆开看三件事：'
        f'<b>盈利预测往哪个方向改</b>、<b>目标价与现价的距离是否被上调/下调维持</b>、'
        f'<b>评级措辞与当期业绩之间有没有落差</b>。'
        f'标题写「买入」但盈利预测连降、或目标价隐含 70% 空间却三个月未动、'
        f'或买入评级建立在资产处置而非经营之上的，都在这一列点名。'
        f'<br><b>本表按交易日滚动更新</b>：股价每日刷新，研报与情绪判断随新研报重估。'
        f'某只票的<b>情绪档位</b>或<b>关键逻辑</b>较上一次更新出现实质变化时'
        f'（评级/目标价方向反转、盈利预测大幅修正、业绩与叙事背离、覆盖转空或转多），'
        f'该行整行标红，情绪列顶部给出变化说明与变化日期，关键句以<b class="hl">红色加粗</b>标出。'
        f'标红只表示「变了」，不表示好坏。'
    )

    # 权重聚合：周期资源类（铝/煤/电/钨铟）
    cyc = {"601600", "000807", "000933", "601001", "600546", "601991", "600578", "600961", "600397"}
    cyc_w = sum(r["weight"] for r in rows if r["code"] in cyc)

    summary = f"""<div class="mood-sum">
<h4>看完 19 份研报后的四个判断</h4>
<ol>
<li><b>组合的卖方叙事高度集中在周期资源。</b>铝（中国铝业、云铝、神火）、煤（晋控煤业、山煤国际）、
电（大唐发电、京能电力）、钨铟（株冶、江钨）合计 {cyc_w:.1f}% 权重，超过一半。这解释了为什么
「目标价隐含空间」整体看着不错——它们吃的是同一条商品价格链，一旦商品转向，{len(rows)} 只里的这一半会同步回撤，
分散度远低于 19 只这个数字给人的感觉。</li>
<li><b>目标价整体在往下修，而不是往上修。</b>{len(s["down"])} 只明确下调（晋控煤业 24.12→21.65、
云铝 39.90→33.92、爱美客 26 年净利被砍 26%、隆鑫四家里三家在降），只有 2 只上调（京能 5.57→6.08、TCL 7.4→8.00）。
周期股的下调尤其值得注意：云铝是「业绩创历史最好、目标价反而降」，因为可比公司 PE 从 10 倍压到 8.5 倍——
盈利在涨、估值在缩，这类票的多头逻辑只能是业绩不能是估值。</li>
<li><b>有三只「买入评级」经不起对照。</b>大悦城两家买入/增持，但 26H1 归母 −7.23 亿、结算毛利率腰斩、
销售 −54.9%，买的是 REITs 出表的一次性收益；江钨装备被给「买入」，可上半年营收 −93.73%、归母仅 120 万，
赌的是尚未完成的 18.98 亿并购；株冶集团的「45 元一致目标价」在检索范围内找不到任何一篇研报可以溯源，
它的真实逻辑只是铟价，而铟的定价权不在国内冶炼厂手里。</li>
<li><b>真正「评级、目标价、当期业绩」三者对得上的只有三只。</b>滨江集团（净现金、融资成本 2.8%、
三家目标价 11.15~13.00 方向一致）、京能电力（Q2 在电价跌煤价涨下仅 −1.3%，被上调目标价）、
神火股份（前三季归母 +114.5%、PE 6~7 倍；但要注意 Q3 计提了 4.13 亿矿山减值）。
三只的共同点不是弹性大，而是<b>现金流与分红能落地</b>。</li>
</ol>
<div class="muted" style="margin-top:9px;font-size:12px">
口径提醒：券商目标价是 6~12 个月视角的卖方观点，且存在「只调盈利不调目标价」的滞后习惯；
本表把它们摆在一起是为了看<b>分歧方向</b>，不是当作价格预测。表中「无覆盖」不等于公司质地差，
只代表当前没有卖方在做跟踪——这本身也是一种信息。</div>
</div>"""

    return f"""{CSS}
<h2>六、市场情绪展望</h2>
<div class="card">
<div class="card-h"><h3>最新一期持仓 · 卖方目标价与情绪拆解</h3>
<span class="pill">{m["n_holdings"]} 只 · {m["rebal_date"]} 调仓 · T 日 {m["t_date"]}</span></div>
<div class="mood-note">{note}</div>
<div class="mood-kpi">{kpi_html}</div>
<div class="mood-wrap"><table class="mood">
<colgroup><col style="width:15%"><col style="width:11%"><col style="width:27%"><col style="width:47%"></colgroup>
<thead><tr><th>个股（权重）</th><th>T 日股价</th><th>研报目标价范围</th><th>市场情绪</th></tr></thead>
<tbody>
{"".join(row_html(r) for r in rows)}
</tbody></table></div>
{summary}
</div>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=DEFAULT_JSON)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()
    with open(a.json, encoding="utf-8") as f:
        d = json.load(f)
    h = build(d)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(h)
    s = stats(d["rows"])
    print(f"OK -> {a.out}  ({len(h)} 字符, {s['n']} 行)")
    print(f"   有目标价 {s['n_has']} / 无 {s['n_none']} / 中位隐含 {s['median']:+.1f}% / 下调 {len(s['down'])}")


if __name__ == "__main__":
    main()
