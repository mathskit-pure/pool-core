# -*- coding: utf-8 -*-
"""重建《质量Top28组合 · 季度回测》派生页的数据块（var D）与页面静态文案。

背景
    派生页（node zEKKr1oOYkKVEQZEJ9ht8E）此前是 2019-05-06 起、固定 28 只等权的
    旧引擎产物，与主板页面里同名的「质量Top28组合」（v2 三道筛、股池口径、2%~8% 权重）
    算的不是同一件事。2026-10-23 起两个页面统一：窗口 2017-01-03 起、同一份
    out15/daily_nav_15.csv 的 Q28 列、同一份 holdings_15.csv 的持仓。

用法
    python scripts/finchain/build_q28_detail.py \
        --page /tmp/q28page/in.html --out /tmp/q28page/out.html

输入
    out15/daily_nav_15.csv     Q28 日净值（已在窗口首日归一到 1.00）
    out15/holdings_15.csv      Q28 逐期持仓（code/weight，rebal_date = T+1 成交日）
    out15/bench_daily.csv      沪深300 / 中证500 / 创业板50 日收盘
    out15/idx399006.csv        创业板指 399006 日收盘（baostock，2016-12 起）
    data15/px_daily.pkl        个股复权日线（open/close，用于「本期剔除」区间涨跌）
    out15/name_map.json        code -> 简称
输出
    --out 指定的 HTML（只改 var D 与若干静态文案，不动样式与结构）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_D15, FIN_OUT  # noqa: E402

NAV_START = "2017-01-01"       # 与 daily_nav15.NAV_START 保持一致
RF = 0.015                     # 夏普无风险利率（页面口径）
EQWT_TEXT = "权重 2%~8%"


# ---------------------------------------------------------------- 绩效
def perf(nav: pd.Series) -> dict:
    r = nav.pct_change().dropna()
    n = len(r)
    eq = float(nav.iloc[-1] / nav.iloc[0])
    ann = eq ** (252.0 / n) - 1
    vol = float(r.std(ddof=0) * np.sqrt(252))
    dd = float((nav / nav.cummax() - 1).min())
    return {"cum": round((eq - 1) * 100, 2), "ann": round(ann * 100, 3),
            "vol": round(vol * 100, 2), "mdd": round(dd * 100, 2),
            "sharpe": round((ann - RF) / vol, 2) if vol else None,
            "calmar": round(ann / abs(dd), 3) if dd < 0 else None, "nav": round(eq, 4)}


def label_of(d: pd.Timestamp) -> str:
    return {5: f"{d.year}一季报", 9: f"{d.year}中报", 11: f"{d.year}三季报"}.get(
        d.month, f"{d.year}年{d.month:02d}月")


# ---------------------------------------------------------------- 主构建
def build(page_html: str) -> tuple[str, dict]:
    nav = pd.read_csv(os.path.join(str(FIN_OUT), "daily_nav_15.csv"),
                      index_col=0, parse_dates=True)
    nav = nav[nav.index >= pd.Timestamp(NAV_START)]
    strat = nav["Q28"].dropna()
    dates = strat.index

    # 基准：三个指数统一在窗口首日归一到 1.00
    b = pd.read_csv(os.path.join(str(FIN_OUT), "bench_daily.csv"), parse_dates=["date"])
    bp = b.pivot_table(index="date", columns="name", values="close").sort_index()
    # 创业板指：优先用 out15 的副本，缺了就退回 cloud/state（两者由 fetch_idx_cyb.py 同步写）
    cyb_f = os.path.join(str(FIN_OUT), "idx399006.csv")
    if not os.path.exists(cyb_f):
        cyb_f = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "cloud", "state", "idx_399006.csv")
    cyb_raw = pd.read_csv(cyb_f, parse_dates=["date"]).set_index("date")["close"].sort_index()

    def anchor(s: pd.Series) -> pd.Series:
        s = s.reindex(dates).ffill().bfill()
        return s / s.iloc[0]

    series = {"strat": strat, "hs300": anchor(bp["沪深300"]),
              "zz500": anchor(bp["中证500"]), "cyb": anchor(cyb_raw)}
    levels = {"strat": strat, "hs300": bp["沪深300"].reindex(dates).ffill(),
              "zz500": bp["中证500"].reindex(dates).ffill(),
              "cyb": cyb_raw.reindex(dates).ffill()}

    # 持仓：股池口径、v2 三道筛后的实际名单与权重
    h = pd.read_csv(os.path.join(str(FIN_OUT), "holdings_15.csv"), dtype={"code": str})
    h["code"] = h["code"].str.zfill(6)
    q = h[h["combo"] == "Q28"]
    decs = sorted(pd.to_datetime(q["rebal_date"].unique()))
    decs = [d for d in decs if d >= pd.Timestamp(NAV_START)]

    name = json.load(open(os.path.join(str(FIN_OUT), "name_map.json"), encoding="utf-8"))
    px = pd.read_pickle(os.path.join(str(FIN_D15), "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    op = px.pivot_table(index="date", columns="code", values="open").sort_index()
    cl = px.pivot_table(index="date", columns="code", values="close").sort_index()

    def px_at(panel, d, c):
        if c not in panel.columns or d not in panel.index:
            return np.nan
        v = panel.at[d, c]
        if pd.isna(v):
            j = panel.index[panel.index <= d]
            v = panel.at[j[-1], c] if len(j) else np.nan
        return v

    def ret_between(k, d0, d1):
        """组合/基准在 (d0, d1] 的区间涨跌幅（%）"""
        s = levels[k]
        a, bb = s.asof(d0), s.asof(d1)
        return None if (pd.isna(a) or pd.isna(bb) or a <= 0) else round(float(bb / a - 1) * 100, 2)

    rows, entry = [], {}
    for i, d in enumerate(decs):
        sub = q[q["rebal_date"] == d.strftime("%Y-%m-%d")]
        w = {r["code"]: float(r["weight"]) for _, r in sub.iterrows()}
        w = dict(sorted(w.items(), key=lambda kv: -kv[1]))
        cur = set(w)
        for c in cur - (set(rows[-1]["codes"]) if rows else set()):
            entry[c] = d
        outs = []
        if rows:
            for c in sorted(set(rows[-1]["codes"]) - cur):
                e0 = entry.get(c)
                a, bb = (px_at(op, e0, c), px_at(op, d, c)) if e0 is not None else (np.nan, np.nan)
                cum = None
                if pd.notna(a) and pd.notna(bb) and a > 0:
                    cum = f"{(bb / a - 1) * 100:+.1f}%"
                outs.append({"name": name.get(c, c),
                             "entry": e0.strftime("%Y-%m-%d") if e0 is not None else None,
                             "cum": cum})
        d0 = pd.Timestamp(rows[-1]["date"]) if rows else dates[0]
        rows.append({
            "date": d.strftime("%Y-%m-%d"), "report": label_of(d), "rep": label_of(d),
            "ret": ret_between("strat", d0, d),
            "hs300": ret_between("hs300", d0, d),
            "zz500": ret_between("zz500", d0, d),
            "cyb": ret_between("cyb", d0, d),
            "prev": None, "src": "pool",
            "hold": [[name.get(c, c), f"{v * 100:.1f}%"] for c, v in w.items()],
            "ex": outs, "codes": sorted(cur),
        })
    for r in rows:
        r.pop("codes")

    last = pd.Timestamp(rows[-1]["date"])
    cur_block = {"from": rows[-1]["date"], "to": dates[-1].strftime("%Y-%m-%d")}
    for k in ("strat", "hs300", "zz500", "cyb"):
        cur_block[k] = ret_between(k, last, dates[-1])

    D = {"meta": {"start": dates[0].strftime("%Y-%m-%d"),
                  "end": dates[-1].strftime("%Y-%m-%d"), "n": int(len(dates))},
         "dates": [d.strftime("%Y-%m-%d") for d in dates],
         "perf": {k: perf(v) for k, v in series.items()},
         "series": {k: [round(float(x), 6) for x in v] for k, v in series.items()},
         "rebalances": rows,
         "latestCount": len(rows[-1]["hold"]),
         "eqwt": EQWT_TEXT,
         "current": cur_block}
    return page_html, D


# ---------------------------------------------------------------- 页面替换
def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def fmtp(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return ("+" if v > 0 else "") + f"{v:.2f}%"


def cls(v):
    if v is None:
        return "mut"
    return "up" if v > 0 else ("dn" if v < 0 else "mut")


def render_rows(D: dict) -> str:
    """服务端渲染调仓表（与页面内联 JS 的输出逐字一致），保证脚本失效时也不是旧数据。"""
    reb = D["rebalances"]
    out = ['<tr><th>调仓日</th><th>本期持仓</th><th>本期剔除（上期有、本期无）</th></tr>']
    for i in range(len(reb) - 1, -1, -1):
        rr = reb[i]
        is_last, is_first = (i == len(reb) - 1), (i == 0)
        cls_row = "r-last" if is_last else ("r-first" if is_first else "")
        day = f'<span class="dt">{esc(rr["date"])}</span>'
        if rr.get("rep"):
            day += ('<span class="pill" style="margin-left:0;margin-top:3px;display:table">'
                    + esc(rr["rep"]) + "</span>")
        if rr["ret"] is None:
            day += '<span class="pchg mut">建仓首期</span>'
        else:
            day += f'<span class="pchg {cls(rr["ret"])}">组合 {fmtp(rr["ret"])}</span>'
            day += f'<span class="pchg hs3 {cls(rr["hs300"])}">沪深300 {fmtp(rr["hs300"])}</span>'
        prev_set = {x[0] for x in reb[i - 1]["hold"]} if i > 0 and reb[i - 1].get("hold") else set()
        has_prev = bool(i > 0 and reb[i - 1].get("hold"))
        if rr.get("hold"):
            parts = []
            for nm, wt in rr["hold"]:
                k = "nm-new" if (has_prev and nm not in prev_set) else "nm"
                parts.append(f'<span class="{k}">{esc(nm)}</span>'
                             + (f'<span class="wt">{esc(wt)}</span>' if wt else ""))
            hold = "、".join(parts)
            hold += (f'<span class="cnt">{len(rr["hold"])} 只 · {esc(D["eqwt"])}</span>')
        else:
            hold = '<span class="mut">—</span>'
        if rr.get("ex"):
            parts = []
            for e in rr["ex"]:
                cum = ""
                if e.get("cum"):
                    cum = f'<span class="cum {"dn" if str(e["cum"]).startswith("-") else "up"}">{esc(e["cum"])}</span>'
                parts.append(f'<span class="nm-out">{esc(e["name"])}</span>'
                             + (f'<span class="pos">建仓 {esc(e["entry"])} {cum}</span>' if e.get("entry") else ""))
            exs = "、".join(parts)
        else:
            exs = '<span class="mut">—</span>'
        out.append(f'<tr class="{cls_row}"><td class="day c-day">{day}</td>'
                   f'<td class="c-hold">{hold}</td><td>{exs}</td></tr>')
    return "\n".join(out)


NOTE_LI = [
    "<li>组合：候选域为<b>当期「舞弊调整质量因子·季度动态股池」</b>（申万三级行业各取 FAQ 前 3，"
    "股池已按总市值过滤），每期按 <b>FAQ（舞弊调整质量因子）得分降序、单个申万三级行业最多 2 只</b>"
    "取满 28 只候选；再做<b>三道筛</b>：① 20 日均成交额低于 5,000 万元的剔除（存活不足 15 只时放宽到 3,000 万）；"
    "② 换手代理（20 日均成交额 ÷ 总市值）在候选内排序，剔除最拥挤的 1/3；③ 权重 ∝ 1 / (换手分位 + 0.15)，"
    "单只限幅 2%~8%（迭代归一，实测区间 2.9%~8.4%，均值约 5.3%）。因此每期持仓数不固定"
    "（2017 年以来 18~22 只），也<b>不等权</b>。"
    "季度调仓（5/1、9/1、11/1 为信息可得日，其后第一个交易日成交），季度内不再平衡。</li>",
    "<li>时点：因子只用当期已公告的财报（信息可得日 = 公告日），T 日决策、<b>T+1 开盘成交</b>；"
    "调仓日<b>取不到收盘价（停牌 / 已退市）的标的一律不买</b>，权重在剩余标的内重新归一——"
    "否则会按停牌前价格「买入」，复牌涨幅被凭空计入。未到期的最后一期按 {end} 收盘估值。</li>",
    "<li>成本：买入、卖出各 10bp，按实际换手计（首期建仓按 100% 计），已计入净值。</li>",
    "<li><b>统计窗口 2017-01-03 起</b>：2015-2016 含三轮股灾、2016 年首个交易日熔断与千股停牌，"
    "不计入业绩，仅用于因子动量与股池所需的预热；六条曲线统一在窗口首日归一到 1.00。"
    "首行区间为窗口起点 → 窗口内首个调仓日，期初持仓沿用 2016-11-02 的选股结果（窗口外预热）。</li>",
    "<li>表格每行「组合 / 沪深300」都是<b>上一个调仓日 → 本调仓日</b>的区间涨跌幅；"
    "最后一行（{from}）之后为进行中的一期：组合 <b class=\"{cs}\">{strat}</b>、"
    "沪深300 <b class=\"{ch}\">{hs300}</b>、中证500 {zz500}、创业板指 {cyb}（至 {to}）。</li>",
    "<li>「本期剔除」列：建仓日 = 该股在本组合中<b>首次出现</b>的调仓日，"
    "累计涨跌幅 = 建仓日 T+1 开盘价 → 剔除日 T+1 开盘价（复权价）。</li>",
    "<li>绩效用日频收盘净值计算，年化按 252 个交易日折算；夏普 = (年化收益 − 1.5%) ÷ 年化波动；"
    "基准为价格指数，不含分红。</li>",
    "<li>与旧版差异：旧版本页是<b>另一套引擎</b>——在当期真实中证800 成分内选 28 只<b>等权</b>、2019-05-06 起，"
    "与主页面里同名的「质量Top28组合」并不同源。把窗口对齐到同一段（2019-05-06 → 2026-10-16）后："
    "旧版本页 年化 15.36% / 夏普 0.70 / 回撤 −23.44%，本版 13.04% / 0.60 / −28.49%，差 2.3pp；"
    "差异来自三处——候选域（中证800 成分 vs 季度股池）、加权方式（等权 vs 拥挤度倒数加权）、"
    "以及本版剔除了调仓日停牌标的（旧版按停牌前价格「买入」，复牌涨幅被计入收益）。"
    "本版改用与主页面<b>同一份净值与持仓</b>，两页数值逐位一致。"
    "归因与未来函数明细见《质量Top28 · 超额归因与未来函数审计》。</li>",
    "<li>数据来源：FAQ 因子面板（v107）、季度股池（pools_v5）、个股复权日线（东财 / 通达信，缺口已补齐）、"
    "创业板指 399006（baostock）。本页为量化研究展示，不构成投资建议。</li>",
]


def render_perf(D: dict) -> str:
    """绩效对比表（与 JS 的 perfHtml 逐字一致）"""
    names = [("strat", "质量Top28组合"), ("hs300", "沪深300"),
             ("zz500", "中证500"), ("cyb", "创业板指")]
    out = ['<tr><th>组合 / 基准</th><th class="num">累计收益</th><th class="num">年化收益</th>'
           '<th class="num">年化波动</th><th class="num">最大回撤</th><th class="num">夏普</th>'
           '<th class="num">卡玛</th></tr>']
    for k, nm in names:
        m = D["perf"][k]
        out.append(f'<tr><td>{esc(nm)}</td>'
                   f'<td class="num {cls(m["cum"])}">{fmtp(m["cum"])}</td>'
                   f'<td class="num {cls(m["ann"])}">{fmtp(m["ann"])}</td>'
                   f'<td class="num">{m["vol"]:.2f}%</td>'
                   f'<td class="num dn">{m["mdd"]:.2f}%</td>'
                   f'<td class="num">{m["sharpe"]:.2f}</td>'
                   f'<td class="num">{m["calmar"]:.2f}</td></tr>')
    return "\n".join(out)


def patch_html(h: str, D: dict) -> str:
    # 1) var D 数据块
    i = h.find("var D = ")
    assert i > 0, "页面里没有 var D"
    j = h.find("};\n", i)
    assert j > i
    blob = json.dumps(D, ensure_ascii=False, separators=(",", ":"))
    h = h[:i] + "var D = " + blob + ";" + h[j + 2:]

    m = D["meta"]
    cur = D["current"]
    # 2) 静态文案（JS 运行时也会重写，这里保证无脚本时同样正确）
    subs = [
        (r"(id=\"span\"[^>]*>(?:<!--pnid:[^>]*?-->)?)[^<]*(</span>)",
         lambda g: g.group(1) + f'{m["start"]} → {m["end"]} · {m["n"]} 个交易日' + g.group(2)),
        (r"(id=\"chartnote\"[^>]*>(?:<!--pnid:[^>]*?-->)?)[^<]*(</div>)",
         lambda g: g.group(1) + f'纵轴为对数刻度；起点归一为 1.00。区间 {m["start"]} → {m["end"]}。' + g.group(2)),
        (r"(id=\"perfnote\"[^>]*>(?:<!--pnid:[^>]*?-->)?)[^<]*(</span>)",
         lambda g: g.group(1) + f'统计区间 {m["start"]} → {m["end"]}'
                                '（夏普＝(年化收益 − 1.5%) ÷ 年化波动；卡玛＝年化收益 ÷ |最大回撤|）' + g.group(2)),
        (r"净值曲线（起点 = 1，\d{4}-\d{2}-\d{2}）", lambda g: f'净值曲线（起点 = 1，{m["start"]}）'),
        (r"调仓明细（\d{4} 年以来每一次调仓）", lambda g: f'调仓明细（{m["start"][:4]} 年以来每一次调仓）'),
    ]
    for pat, fn in subs:
        h = re.sub(pat, fn, h, count=1)

    # KPI 六个方框（JS 运行时会重绘，这里保证静态也正确）
    p = D["perf"]["strat"]
    kpis = [("累计收益", fmtp(p["cum"]), cls(p["cum"])),
            ("年化收益", fmtp(p["ann"]), cls(p["ann"])),
            ("最大回撤", f'{p["mdd"]:.2f}%', ""),
            ("夏普 / 卡玛", f'{p["sharpe"]:.2f} / {p["calmar"]:.2f}', ""),
            ("调仓期数", f'{len(D["rebalances"])} 期', ""),
            ("最新持仓", f'{D["latestCount"]} 只', "")]
    for lab, val, c in kpis:
        pat = ("(" + re.escape(lab) + r"</span>)(<b\b[^>]*>)((?:<!--pnid:[^>]*?-->)?)[^<]*(</b>)")

        def _rep(g, v=val, cc=c):
            tag = re.sub(r'\s+class(?:="[^"]*")?(?=[\s>])', "", g.group(2))
            tag = tag.replace("<b ", f'<b class="{cc}" ', 1) if cc else tag
            return g.group(1) + tag + g.group(3) + v + g.group(4)

        h, n = re.subn(pat, _rep, h, count=1)
        assert n == 1, f"KPI「{lab}」没找到"

    # 3) eqwt 语义：不再等权
    h = h.replace("' · 等权 ' + D.eqwt", "' · ' + D.eqwt")

    # 4) 口径说明整块重写（JS 一份 + 静态一份，二者文字完全相同）
    body = []
    for s in NOTE_LI:
        s = s.replace("{end}", m["end"]).replace("{from}", esc(cur["from"]))
        s = s.replace("{to}", esc(cur["to"]))
        s = s.replace("{cs}", cls(cur["strat"])).replace("{strat}", fmtp(cur["strat"]))
        s = s.replace("{ch}", cls(cur["hs300"])).replace("{hs300}", fmtp(cur["hs300"]))
        s = s.replace("{zz500}", fmtp(cur["zz500"])).replace("{cyb}", fmtp(cur["cyb"]))
        body.append(s)

    a = h.find("var note = '<b>口径说明</b><ul>'")
    assert a > 0, "页面里没有口径说明块"
    bnd = h.find("document.getElementById('note').innerHTML = note;", a)
    assert bnd > a
    js_lis = [" + '" + s.replace("'", "\\'") + "'" for s in body]
    js_lis[-1] = js_lis[-1][:-1] + "</ul>'"          # 末条补上 </ul>
    note = "var note = '<b>口径说明</b><ul>'\n " + "\n ".join(js_lis) + ";\n"
    h = h[:a] + note + h[bnd:]

    # 静态部分：<div class="note" id="note"> 里的 <b>口径说明</b><ul>...</ul>
    k = h.find('id="note"')
    assert k > 0, "页面里没有 #note"
    u1 = h.find("</ul>", k)
    assert u1 > k
    h = (h[:h.find(">", k) + 1] + "<b>口径说明</b><ul>"
         + "".join(body) + "</ul>" + h[u1 + 5:])

    # 5) 静态表格（保留 tbody 开标签，只换里面的 tr）
    for tbl_id, render in (("perf", render_perf), ("reb", render_rows)):
        k = h.find(f'id="{tbl_id}"')
        assert k > 0, f"页面里没有 #{tbl_id}"
        t0 = h.find("<tbody", k)
        assert t0 > k, f"#{tbl_id} 里没有 tbody"
        s0 = h.find(">", t0) + 1
        s1 = h.find("</tbody>", s0)
        assert s1 > s0
        h = h[:s0] + render(D) + "\n" + h[s1:]
    return h


def clean(h: str) -> str:
    """去掉编辑器节点标记（import_html 会重新生成），顺便把体积压下来"""
    h = re.sub(r"<!--pnid:\w+-->", "", h)
    h = re.sub(r' data-page-node-id="\w+"', "", h)
    h = re.sub(r' data-pnid-children="\w+"', "", h)
    return h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True, help="模板页面 HTML（线上页面下载件）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-pnid", action="store_true", help="保留编辑器节点标记（仅用于本地比对）")
    a = ap.parse_args()
    h = open(a.page, encoding="utf-8").read()
    _, D = build(h)
    h2 = patch_html(h, D)
    if not a.keep_pnid:
        h2 = clean(h2)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(h2)
    p = D["perf"]["strat"]
    print(f"[done] {a.out}")
    print(f"       窗口 {D['meta']['start']} → {D['meta']['end']}，{D['meta']['n']} 个交易日")
    print(f"       组合 累计 {p['cum']:+.2f}% / 年化 {p['ann']:.3f}% / 回撤 {p['mdd']:.2f}% "
          f"/ 夏普 {p['sharpe']:.2f} / 卡玛 {p['calmar']:.3f} / 末值 {p['nav']:.4f}")
    print(f"       调仓 {len(D['rebalances'])} 期，最新 {D['latestCount']} 只，"
          f"首期 {D['rebalances'][0]['date']}，末期 {D['rebalances'][-1]['date']}")


if __name__ == "__main__":
    main()
