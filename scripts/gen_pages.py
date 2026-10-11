# -*- coding: utf-8 -*-
"""把「舞弊调整质量因子·季度动态股池」长页面拆成 4 个子页面 + 1 个目录导航页。

    页面1  标的池说明 + 评分模型
    页面2  季度股池（23 期）
    页面3  动量轮动回测
    页面4  持仓变动明细 + 如何更新最新一期三大报（目录页为原页面改造）

首次运行时尚无 nodeId，导航链接占位为 "#"；创建出节点后把 id 写入
data/page_nodes.json，再跑一次即可生成带真实跳转链接的版本。
"""
import html
import json
import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = r"C:\Users\12066\WorkBuddy\2026-10-05-23-13-30"
DATA = os.path.join(BASE, "data")
NODES = os.path.join(DATA, "page_nodes.json")
BASE_URL = "https://www.workbuddy.cn/space/d/{}"

ORDER = ["2019-03-31", "2019-06-30", "2019-09-30",
         "2020-03-31", "2020-06-30", "2020-09-30",
         "2021-03-31", "2021-06-30", "2021-09-30",
         "2022-03-31", "2022-06-30", "2022-09-30",
         "2023-03-31", "2023-06-30", "2023-09-30",
         "2024-03-31", "2024-06-30", "2024-09-30",
         "2025-03-31", "2025-06-30", "2025-09-30",
         "2026-03-31", "2026-06-30"]

N_SHOW_MOM = 5
N_SHOW_QUAL = 8
BACKTEST_START = "2019-05-06"

PAGES = [("p1", "标的池与评分模型"), ("p2", "季度动态股池"),
         ("p3", "动量轮动回测"), ("p4", "持仓变动与更新")]

CSS = """
:root{{--bg:#f7f8fa;--card:#fff;--bd:#e5e7eb;--tx:#1f2937;--mut:#6b7280;--ac:#c0392b;--ac2:#2c6f9e}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tx);
 font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Inter,sans-serif;line-height:1.6}}
.wrap{{max-width:1180px;margin:0 auto;padding:28px 20px 60px}}
h1{{font-size:26px;margin:0 0 6px}} h2{{font-size:19px;margin:34px 0 12px}}
h3{{font-size:16px;margin:0}}
.sub{{color:var(--mut);font-size:14px;margin-bottom:18px}}
.card{{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:16px 18px;margin-bottom:14px}}
.card-h{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:8px}}
.pill{{display:inline-block;background:#eef2ff;color:#3730a3;border-radius:999px;
 padding:2px 10px;font-size:12px;margin-left:8px;font-weight:400}}
.muted{{color:var(--mut);font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-top:10px}}
.ind{{border:1px solid var(--bd);border-radius:9px;padding:10px 12px;background:#fcfcfd}}
.ind-h{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}}
.ind-name{{font-weight:600;font-size:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
.mini th,.mini td{{padding:4px 6px;text-align:left;border-bottom:1px solid #f1f2f4}}
.tbl th,.tbl td{{padding:8px 10px;text-align:left;border-bottom:1px solid var(--bd)}}
.tbl th{{background:#f3f4f6;font-weight:600}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.tag{{display:inline-block;border-radius:4px;padding:1px 7px;font-size:12px;line-height:1.5}}
.up{{color:#c0392b;font-weight:600}} .dn{{color:#128a53;font-weight:600}} .mut{{color:#9ca3af}}
.nm{{color:#374151}} .nm-new{{color:#c0392b;font-weight:600}} .nm-out{{color:#128a53;font-weight:600}}
.tbl5 td{{vertical-align:top;line-height:2}}
.tbl5 .c-day{{width:150px}} .tbl5 .c-hold{{width:38%}}
.tbl5 .day{{white-space:nowrap;font-weight:600}}
.tbl5 .cell{{font-size:13px}}
.tbl5 .cnt{{display:block;color:#9ca3af;font-size:12px;margin-top:4px}}
.sub-h{{font-size:13px;font-weight:600;color:#374151;margin:4px 0 6px}}
.legend{{background:#fcfcfd;border:1px solid var(--bd);border-radius:9px;
 padding:9px 12px;font-size:13px;margin-bottom:12px}}
.join{{color:#9ca3af;font-size:11px;margin-left:4px;font-weight:400}}
.mono{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:var(--mut)}}
.rk{{color:var(--mut);width:22px}}
details>summary{{cursor:pointer;color:var(--ac2);font-size:13px;outline:none}}
.chart{{width:100%;height:auto;margin-top:8px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:14px}}
.kpi{{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 14px}}
.kpi b{{display:block;font-size:21px;margin-top:2px}}
.kpi span{{color:var(--mut);font-size:12px}}
.note{{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:12px 14px;font-size:13px}}
code{{background:#f3f4f6;padding:1px 6px;border-radius:4px;font-size:12px}}
ol,ul{{padding-left:22px;margin:8px 0}}
li{{margin:4px 0;font-size:14px}}
.nav{{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 20px;padding:8px 10px;background:var(--card);
 border:1px solid var(--bd);border-radius:10px}}
.nav a{{color:var(--mut);text-decoration:none;font-size:13px;padding:5px 11px;border-radius:6px}}
.nav a:hover{{background:#f3f4f6;color:var(--tx)}}
.nav a.on{{background:var(--ac);color:#fff;font-weight:600}}
.nav .home{{margin-right:auto;color:var(--ac2);font-weight:600}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px;margin-top:18px}}
.pcard{{display:block;background:var(--card);border:1px solid var(--bd);border-radius:12px;
 padding:16px 18px;text-decoration:none;color:inherit}}
.pcard:hover{{border-color:var(--ac2);box-shadow:0 2px 10px rgba(0,0,0,.07)}}
.pcard b{{display:block;font-size:16px;margin-bottom:5px}}
.pcard span{{color:var(--mut);font-size:13px}}
"""


def nav_bar(cur):
    ids = json.load(open(NODES, encoding="utf-8")) if os.path.exists(NODES) else {}
    items = []
    for key, label in PAGES:
        url = BASE_URL.format(ids[key]) if ids.get(key) else "#"
        cls = ' class="on"' if key == cur else ""
        items.append(f'<a href="{url}"{cls}>{label}</a>')
    home = BASE_URL.format(ids["index"]) if ids.get("index") else "#"
    return f'<div class="nav"><a class="home" href="{home}">目录</a>{"".join(items)}</div>'


def svg_chart(nav):
    """内嵌 SVG 折线图（无外部依赖）"""
    if nav is None or nav.empty:
        return "<p class='muted'>暂无净值数据</p>"
    cols = [c for c in nav.columns if nav[c].notna().any()]
    if not cols:
        return ""
    W, H, PL, PR, PT, PB = 950, 340, 56, 180, 24, 34
    sub = nav[cols].dropna(how="all")
    if sub.empty:
        return ""
    lo = float(sub.min().min())
    hi = float(sub.max().max())
    if not (hi > lo):
        hi = lo + 1.0
    xs = list(sub.index)
    n = len(xs)

    def X(i):
        return PL + (W - PL - PR) * (i / max(1, n - 1))

    def Y(v):
        return PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))

    palette = ["#c0392b", "#2c6f9e", "#128a53", "#9ca3af", "#b8860b", "#6b7280"]
    paths, legend = [], []
    for k, c in enumerate(cols):
        s = sub[c].dropna()
        if s.empty:
            continue
        pts = " ".join(f"{X(xs.index(d)):.1f},{Y(float(v)):.1f}" for d, v in s.items())
        col = palette[k % len(palette)]
        paths.append(f'<polyline fill="none" stroke="{col}" stroke-width="1.6" points="{pts}"/>')
        legend.append(f'<text x="{W-PR+14}" y="{PT+18+k*20}" font-size="12" fill="{col}">'
                      f'{html.escape(c)}</text>')
    grid = []
    for g in range(5):
        v = lo + (hi - lo) * g / 4
        y = Y(v)
        grid.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}" '
                    f'stroke="#eceef1" stroke-width="1"/>')
        grid.append(f'<text x="8" y="{y+4:.1f}" font-size="11" fill="#9ca3af">{v:.2f}</text>')
    ticks = []
    for t in range(0, n, max(1, n // 6)):
        ticks.append(f'<text x="{X(t):.1f}" y="{H-10}" font-size="11" fill="#9ca3af" '
                     f'text-anchor="middle">{str(xs[t])[:7]}</text>')
    return (f'<svg class="chart" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">'
            f'{"".join(grid)}{"".join(paths)}{"".join(legend)}{"".join(ticks)}</svg>')


def main():
    pools = json.load(open(os.path.join(DATA, "pools.json"), encoding="utf-8"))
    caps = json.load(open(os.path.join(DATA, "caps.json"), encoding="utf-8"))

    nav = summ = hold = rm = q20 = qrm = None
    if os.path.exists(os.path.join(DATA, "nav.csv")):
        nav = pd.read_csv(os.path.join(DATA, "nav.csv"), index_col=0)
        nav.index = pd.to_datetime(nav.index)
    if os.path.exists(os.path.join(DATA, "backtest_summary.csv")):
        summ = pd.read_csv(os.path.join(DATA, "backtest_summary.csv"))
    if os.path.exists(os.path.join(DATA, "holdings.csv")):
        hold = pd.read_csv(os.path.join(DATA, "holdings.csv"), dtype={"代码": str})
    if os.path.exists(os.path.join(DATA, "removed.csv")):
        rm = pd.read_csv(os.path.join(DATA, "removed.csv"), dtype={"代码": str})
    if os.path.exists(os.path.join(DATA, "quality_top20.csv")):
        q20 = pd.read_csv(os.path.join(DATA, "quality_top20.csv"), dtype={"代码": str})
    if os.path.exists(os.path.join(DATA, "quality_removed.csv")):
        qrm = pd.read_csv(os.path.join(DATA, "quality_removed.csv"), dtype={"代码": str})

    keys = [p for p in ORDER if p in pools] + sorted(k for k in pools if k not in ORDER)
    n_big = sum(1 for c in caps.values() if c >= 300e8)
    total_codes = len({m["code"] for p in keys for m in pools[p]["members"]})
    n_ind = len({m["sw3"] for p in keys for m in pools[p]["members"]})
    label_first = html.escape(pools[keys[0]]["label"]) if keys else "-"
    label_last = html.escape(pools[keys[-1]]["label"]) if keys else "-"

    # ── 季度股池（页面2） ────────────────────────────────────────────────
    pool_html = []
    for p in keys:
        v = pools[p]
        mem = v["members"]
        by_ind = {}
        for m in mem:
            by_ind.setdefault(m["sw3"], []).append(m)
        groups = sorted(by_ind.items(), key=lambda kv: -len(kv[1]))
        pool_html.append(
            f"<section class='card'><div class='card-h'><h3>{html.escape(v['label'])}"
            f"<span class='pill'>信息可得 {v['asof']}</span></h3>"
            f"<span class='muted'>{len(mem)} 只 · {len(by_ind)} 个申万三级行业</span></div>")
        pool_html.append("<details>"
                         f"<summary>展开 / 收起（{len(by_ind)} 个行业 · {len(mem)} 只）</summary>"
                         "<div class='grid'>")
        for ind, ms in groups:
            pool_html.append("<div class='ind'><div class='ind-h'>"
                             f"<span class='ind-name'>{html.escape(ind)}</span>"
                             f"<span class='muted'>{len(ms)} 只</span></div>")
            pool_html.append("<table class='mini'><thead><tr><th>#</th><th>代码</th><th>名称</th>"
                             "<th>评分</th><th>市值(亿)</th></tr></thead><tbody>")
            for i, m in enumerate(ms, 1):
                mc = caps.get(m["code"])
                mcs = f"{mc/1e8:.0f}" if mc else "-"
                pool_html.append(
                    f"<tr><td class='rk'>{i}</td><td class='mono'>{m['code']}</td>"
                    f"<td>{html.escape(m['name'])}</td>"
                    f"<td class='num'>{m['FAQ_score']:.2f}</td><td class='num'>{mcs}</td></tr>")
            pool_html.append("</tbody></table></div>")
        pool_html.append("</div></details></section>")
    pool_html = "".join(pool_html)

    # ── 回测汇总表 + 净值图（页面3） ─────────────────────────────────────
    bt_html = ""
    if summ is not None and not summ.empty:
        rows = []
        for _, r in summ.iterrows():
            def f(k, pct=True, d=2):
                v = r.get(k)
                if pd.isna(v):
                    return "-"
                return f"{v*100:.{d}f}%" if pct else f"{v:.{d}f}"
            rows.append(f"<tr><td><b>{html.escape(str(r['组合']))}</b></td>"
                        f"<td class='num'>{f('累计收益')}</td><td class='num'>{f('年化收益')}</td>"
                        f"<td class='num'>{f('年化波动')}</td><td class='num'>{f('最大回撤')}</td>"
                        f"<td class='num'>{f('夏普比率', False)}</td>"
                        f"<td class='num'>{f('卡玛比率', False)}</td></tr>")
        bt_html = ("<table class='tbl'><thead><tr><th>组合</th><th>累计收益</th><th>年化收益</th>"
                   "<th>年化波动</th><th>最大回撤</th><th>夏普</th><th>卡玛</th></tr></thead>"
                   f"<tbody>{''.join(rows)}</tbody></table>")

    def pct_span(v, d=2):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "<span class='mut'>-</span>"
        col = "up" if v > 0 else ("dn" if v < 0 else "mut")
        sign = "+" if v > 0 else ""
        return f"<span class='{col}'>{sign}{v * 100:.{d}f}%</span>"

    def change_table(days, hold_df, rm_df, n_label, note_map=None, show_join=False):
        if hold_df is None or hold_df.empty or not days:
            return "<p class='muted'>暂无数据</p>"
        rows5 = []
        for di, day in enumerate(days):
            h = hold_df[hold_df["调仓日"] == day].sort_values("次序")
            names, n_new = [], 0
            for _, r in h.iterrows():
                nm = html.escape(str(r["名称"]))
                is_new = str(r.get("状态", "")) == "新增"
                n_new += int(is_new)
                names.append(f"<span class='nm-new'>{nm}</span>" if is_new
                             else f"<span class='nm'>{nm}</span>")
            outs, n_out = [], 0
            if rm_df is not None and not rm_df.empty:
                g = rm_df[rm_df["调仓日"] == day].sort_values("区间涨跌幅", ascending=False)
                n_out = len(g)
                for _, r in g.iterrows():
                    join = ""
                    if show_join:
                        ed = r.get("建仓日")
                        if ed is not None and not pd.isna(ed) and str(ed) != "nan":
                            join = f"<span class='join'>建仓 {html.escape(str(ed))}</span>"
                    outs.append(f"<span class='nm-out'>{html.escape(str(r['名称']))}</span>"
                                f"{join} {pct_span(r['区间涨跌幅'])}")
            tag = "最新一期" if di == 0 else f"倒数第 {di + 1} 期"
            note = f"<span class='cnt'>{(note_map or {}).get(day, '')}</span>" if note_map else ""
            rows5.append(
                f"<tr><td class='day'>{day}<span class='pill'>{tag}</span>{note}</td>"
                f"<td class='cell'>{'、'.join(names)}"
                f"<span class='cnt'>{len(h)} 只 · 新增 {n_new}</span></td>"
                f"<td class='cell'>{'、'.join(outs) if outs else '<span class=\"mut\">—</span>'}"
                f"<span class='cnt'>{n_out} 只</span></td></tr>")
        join_tip = ("；其后「建仓 xxxx-xx-xx」为加入持仓的调仓日，数字为「建仓日 → 剔除日」累计涨跌幅"
                    if show_join else "，其后数字为「建仓日 → 剔除日」累计涨跌幅")
        return (
            "<div class='legend'>"
            "<span class='nm-new'>红色</span> = 本期相较上期新纳入"
            "<span class='nm-out' style='margin-left:14px'>绿色</span> = 本期被剔除"
            f"{join_tip}"
            "<span class='mut' style='margin-left:14px'>（涨跌幅按 A 股习惯：红涨绿跌）</span></div>"
            "<table class='tbl tbl5'><thead><tr>"
            f"<th class='c-day'>调仓日</th><th class='c-hold'>本期持仓（{n_label}）</th>"
            "<th class='c-out'>本期剔除（较上期卖出 · 累计涨跌幅）</th>"
            f"</tr></thead><tbody>{''.join(rows5)}</tbody></table>")

    hold_html = ""
    if hold is not None and not hold.empty:
        days_m = sorted(hold["调仓日"].unique())[-N_SHOW_MOM:][::-1]
        hold_html = change_table(days_m, hold, rm, "12 只")
    q5_html = ""
    if q20 is not None and not q20.empty:
        days_q = sorted(q20["调仓日"].unique())[-N_SHOW_QUAL:][::-1]
        note_map = {r["调仓日"]: r["报告期"] for _, r in q20.iterrows()}
        q5_html = change_table(days_q, q20, qrm, "20 只", note_map, show_join=True)

    def page(title, cur, body):
        return (f'<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{title}</title><style>{CSS}</style></head><body><div class="wrap">'
                f'<h1>{title}</h1>'
                f'<div class="sub">舞弊调整质量因子 · 季度动态股池 · '
                f'报告期 {label_first} → {label_last} · 更新时点：定期报告披露截止次月首日</div>'
                f'{nav_bar(cur)}{body}'
                f'<p class="muted" style="margin-top:26px">本页仅为基于公开财报数据的量化研究展示，'
                f'不构成任何投资建议。</p></div></body></html>')

    # ── 页面1：标的池说明 + 评分模型 ─────────────────────────────────────
    body1 = f"""
<div class="kpis">
 <div class="kpi"><span>评分报告期</span><b>{len(keys)}</b></div>
 <div class="kpi"><span>股池覆盖个股(并集)</span><b>{total_codes}</b></div>
 <div class="kpi"><span>申万三级行业</span><b>{n_ind}</b></div>
 <div class="kpi"><span>动量组合持仓</span><b>12</b></div>
 <div class="kpi"><span>质量Top组合持仓</span><b>20</b></div>
</div>

<h2>一、标的池说明</h2>
<div class="card">
<p><b>池口径</b>：中证800 + 中证1000 成分股中，总市值 ≥ 300 亿元的 <b>{n_big}</b> 只个股。
这是一个<b>固定清单</b> —— 一旦确定就不再随市值变化或指数成份调整而改变，
以保证各期股池与回测在时间上可比。</p>
<table class="tbl"><thead><tr><th>项目</th><th>口径</th></tr></thead><tbody>
<tr><td>选样空间</td><td>中证800 成分 ∪ 中证1000 成分</td></tr>
<tr><td>市值门槛</td><td>总市值 ≥ 300 亿元（以建池时点为准）</td></tr>
<tr><td>清单调整</td><td>固定，不随市值与指数成份调整变化</td></tr>
<tr><td>行业分类</td><td>申万三级行业</td></tr>
<tr><td>股池构造</td><td>每期在每个申万三级行业内取评分前 5 名；不足 5 只的行业不补入</td></tr>
<tr><td>评分周期</td><td>一季报 / 中报 / 三季报（年报不参与评分）</td></tr>
<tr><td>信息可得日</td><td>定期报告披露截止次月首日：5 月 1 日 / 9 月 1 日 / 11 月 1 日</td></tr>
</tbody></table>
<p class="muted" style="margin-top:10px">当前已生成 <b>{len(keys)}</b> 期股池
（{label_first} → {label_last}），并集覆盖 <b>{total_codes}</b> 只个股、
<b>{n_ind}</b> 个申万三级行业。</p>
</div>

<h2>二、评分模型：舞弊调整质量因子（fmQMJ 思路）</h2>
<div class="card">
<p><b>质量分 Q</b> —— 依据 Hsu、Kalesnik &amp; Kose《什么是质量？》，七大质量特征中仅四类通过"三步稳健性检验"，
本模型只保留这四类，并按下表权重合成（行业内中位数中心化后取截面 z-score）：</p>
<table class="tbl"><thead><tr><th>支柱</th><th>权重</th><th>信号</th><th>文献依据</th></tr></thead><tbody>
<tr><td><b>盈利能力</b></td><td class="num">34%</td><td>ROE(TTM)、ROIC、ROA(TTM)、毛利率、净利率、净利现金含量</td>
<td>Novy-Marx 2013；Fama-French 2006/2015</td></tr>
<tr><td><b>会计质量</b></td><td class="num">22%</td><td>总应计 TATA、应收偏离 DSRI、资产质量 AQI、扣非/归母</td>
<td>Sloan 1996；Chan-Jegadeesh-Lakonishok 2006</td></tr>
<tr><td><b>分红与稀释</b></td><td class="num">22%</td><td>分红率、股息/权益、股本扩张(负向)</td>
<td>Boudoukh 等 2007；Loughran-Ritter 1995</td></tr>
<tr><td><b>投资活动</b></td><td class="num">22%</td><td>总资产增速(负向)、存货增速(负向)</td>
<td>Titman-Wei-Xie 2004；Cooper-Gulen-Schill 2008</td></tr>
</tbody></table>
<p class="muted">说明：原文证实 <b>盈利稳定性</b> 与 <b>资本结构</b> 实为低波(low-beta)变体、<b>盈利增长</b> 无文献支持，故不纳入质量分。</p>
<p><b>舞弊风险 F</b> —— 依据 Chen、Bu、Fang &amp; Xu《一种经欺诈概率调整的新质量因子》，以财报可观测的操纵代理变量刻画"未被发现的舞弊概率"：
应计异常 TATA、应收/收入偏离 DSRI、软资产 AQI、高增长诱因 SGI、毛利恶化 GMI、杠杆抬升 LVGI、商誉占比、股本扩张。</p>
<p><b>最终评分 FAQ = Q<sub>z</sub> − λ·F<sub>z</sub>（λ = 1.0）</b>：在质量分中扣除标准化舞弊概率，剔除"财报漂亮但操纵风险高"的个股。</p>
</div>
"""

    # ── 页面2：季度股池 ──────────────────────────────────────────────────
    body2 = (f"<h2>季度股池（申万三级行业各取前 5，不足 5 只不补入）</h2>"
             f"<div class='note' style='margin-bottom:14px'>共 <b>{len(keys)}</b> 期"
             f"（{label_first} → {label_last}）。每期在每个申万三级行业内按 FAQ 评分取前 5 名，"
             f"表格默认收起，点「展开 / 收起」查看明细。</div>{pool_html}")

    # ── 页面3：动量轮动回测 ──────────────────────────────────────────────
    body3 = f"""
<h2>动量轮动回测（标的池 = 动态股池）</h2>
<div class="card">
<p class="muted">模型来自《龙头动量轮动策略代码更新》：风险调整动量
 <code>Adj = N日平均收益 / √(N日收益方差)</code>；先筛原始动量为正，再按 Adj 取前 L 只；
 权重按 Adj 归一化；权重滞后 1 日（T 日决策、T+1 执行）。<br>
 本页参数：动量周期 N = 10 天，调仓间隔 K = 5 个交易日，持仓 L = 12 只，
 单个申万三级行业最多 2 只（出现第 3 只时剔除动量最低者并按序补录）；回测自 {BACKTEST_START} 起。<br><br>
 <b>次新股过滤</b>：上市未满 60 个交易日的个股不进入任何组合。回测区间含 2020 年前后上市的
 次新股，其连续一字涨停使日收益恒为 +10%、滚动方差≈0，风险调整动量 Adj 会被放大到 1000 以上，
 归一化后单票权重逼近 100%，形成"每天吃满涨停"的不可实现收益；一字板在实盘中无法建仓，
 故按上市交易日数过滤。<br><br>
 <b>质量Top20等权组合</b>：不用动量，直接在当期股池内按舞弊调整质量因子得分降序取前 20 只，
 单个申万三级行业最多 2 只（出现第 3 只时跳过其中得分最低者并按序补录）。
 <b>季度买入持有</b>：只在季度股池更新日（信息可得日后的首个交易日）换仓并等权建仓，
 <b>同一季度内不再平衡</b>，权重随价格自然漂移，直到下个季度重新等权建仓；换仓同样权重滞后 1 日。<br><br>
 <b>对比基准</b>：沪深300、创业板50、科创50 三个宽基指数，以及同一动态股池的等权组合；
 基准首日收益不计入，与策略"T 日决策、T+1 执行"对齐。</p>
{bt_html}
<div style="margin-top:14px">{svg_chart(nav)}</div>
</div>
"""

    # ── 页面4：持仓变动明细 + 如何更新 ───────────────────────────────────
    body4 = f"""
<h2>一、持仓变动明细（动量 {N_SHOW_MOM} 期 · 质量 Top20 {N_SHOW_QUAL} 期）</h2>
<div class="card">
<div class="sub-h" style="font-size:15px">1.1　动量轮动策略（持仓 12 只 · 每 5 个交易日调仓）</div>
{hold_html or '<p class="muted">暂无持仓数据</p>'}
<div class="sub-h" style="font-size:15px;margin-top:26px">1.2　质量Top20等权组合（持仓 20 只 · 季度买入持有 · 最近 {N_SHOW_QUAL} 个调仓日）</div>
<div class="note" style="margin-bottom:10px">调仓频率与回测一致：<b>每个季度调仓一次</b>
（调仓日＝报告期信息可得日，如 2026 年中报 → 2026-09-01），同一季度内持仓与成分不变。</div>
{q5_html or '<p class="muted">暂无持仓数据</p>'}
</div>

<h2>二、如何更新最新一期三大报</h2>
<div class="card">
<div class="note">A 股定期报告披露截止日：一季报 4/30、中报 8/31、三季报 10/31。
因此在 <b>5 月 1 日 / 9 月 1 日 / 11 月 1 日</b>（披露完成次月首日）可更新对应季度的股池。</div>
<ol>
<li>拉取最新一期三大报表（标的池为固定清单，不随市值与指数成份调整变化）。</li>
<li>用同一套舞弊调整质量因子模型计算该报告期评分。</li>
<li>按申万三级行业取评分前 5，生成新一期股池，写入「季度动态股池」页面。</li>
<li>以新一期股池替换动量模型的标的池，从"信息可得日"起继续轮动，
并刷新「动量轮动回测」与「持仓变动与更新」两个页面。</li>
</ol>
<p class="muted">已在系统中配置定时更新任务（每年 5 月 1 日、9 月 1 日、11 月 1 日自动执行上述流程）。
如需手动触发，可在对话中提出「更新最新一季股池」。</p>
</div>
"""

    # ── 目录导航页 ───────────────────────────────────────────────────────
    ids = json.load(open(NODES, encoding="utf-8")) if os.path.exists(NODES) else {}
    descs = {
        "p1": f"标的池口径与固定清单说明；舞弊调整质量因子 FAQ = Q<sub>z</sub> − λ·F<sub>z</sub> 的构造与文献依据",
        "p2": f"{len(keys)} 期季度股池（{label_first} → {label_last}），按申万三级行业各取评分前 5",
        "p3": f"自 {BACKTEST_START} 起的动量轮动、等权与质量 Top20 组合绩效，以及三大宽基基准对比",
        "p4": f"动量最近 {N_SHOW_MOM} 期、质量 Top20 最近 {N_SHOW_QUAL} 期的持仓变动，以及定期更新流程",
    }
    cards = []
    for i, (key, label) in enumerate(PAGES, 1):
        url = BASE_URL.format(ids[key]) if ids.get(key) else "#"
        cards.append(f'<a class="pcard" href="{url}"><b>{i}. {label}</b>'
                     f'<span>{descs[key]}</span></a>')
    index_body = (
        f'<div class="kpis">'
        f'<div class="kpi"><span>评分报告期</span><b>{len(keys)}</b></div>'
        f'<div class="kpi"><span>股池覆盖个股(并集)</span><b>{total_codes}</b></div>'
        f'<div class="kpi"><span>申万三级行业</span><b>{n_ind}</b></div>'
        f'<div class="kpi"><span>回测起点</span><b style="font-size:16px">{BACKTEST_START}</b></div>'
        f'</div>'
        f'<p class="muted">标的池：中证800 + 中证1000 成分股中总市值 ≥ 300 亿元的 '
        f'{n_big} 只个股（固定清单）· 报告期：{label_first} → {label_last}</p>'
        f'<div class="cards">{"".join(cards)}</div>')

    out = {
        "p1": page("舞弊调整质量因子 · 标的池与评分模型", "p1", body1),
        "p2": page("舞弊调整质量因子 · 季度动态股池", "p2", body2),
        "p3": page("舞弊调整质量因子 · 动量轮动回测", "p3", body3),
        "p4": page("舞弊调整质量因子 · 持仓变动与更新", "p4", body4),
    }
    for k, doc in out.items():
        path = os.path.join(DATA, f"{k}.html")
        open(path, "w", encoding="utf-8").write(doc)
        print(f"{path}  {len(doc):,} chars")

    idx = (f'<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>舞弊调整质量因子·季度动态股池</title><style>{CSS}</style></head>'
           f'<body><div class="wrap">'
           f'<h1>舞弊调整质量因子 · 季度动态股池</h1>'
           f'<div class="sub">原长页面已拆分为以下四个子页面，点击卡片进入</div>'
           f'{index_body}'
           f'<p class="muted" style="margin-top:26px">本页面仅为基于公开财报数据的量化研究展示，'
           f'不构成任何投资建议。</p></div></body></html>')
    open(os.path.join(DATA, "index.html"), "w", encoding="utf-8").write(idx)
    print(f'{os.path.join(DATA, "index.html")}  {len(idx):,} chars')


if __name__ == "__main__":
    main()
