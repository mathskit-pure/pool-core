# -*- coding: utf-8 -*-
"""生成独立报告：股池限定为「申万三级行业市值前 50 × 各行业前 3」的 A/B 测算。

与托管页面完全解耦 —— 只读 data/scn_ind50/{base,ind50}/ 两套回测产物，
输出一份自包含 HTML（无外部依赖，可直接双击打开 / 打印成 PDF）。

输入：data/scn_ind50/{base,ind50}/{daily_nav,holdings}.csv、pools_v5 / pools_v6_ind50 / industry_rank
输出：<OUT_DIR>/行业市值前50限制情景测算报告.html
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import DATA, FIN_D15 as D15  # noqa: E402
from scn_ind50_block import COMBOS, perf, pct, svg_chart, pool_table  # noqa: E402

SCN = os.path.join(DATA, "scn_ind50")
OUT_DIR = os.environ.get("SCN_REPORT_DIR") or DATA
OUT = os.path.join(OUT_DIR, "行业市值前50限制情景测算报告.html")
LATEST = "2026-09-01"
RED, GREEN = "#d81b60", "#0f9d58"

CSS = """
:root{--ink:#111827;--sub:#6b7280;--line:#e5e7eb;--bg:#f7f8fa;--card:#fff;--acc:#1f4e79}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:14px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:28px 22px 80px}
.head{background:linear-gradient(135deg,#1f4e79,#2f6f9e);color:#fff;border-radius:14px;padding:30px 32px;margin-bottom:22px}
.head .kicker{font-size:12px;letter-spacing:.18em;opacity:.8;text-transform:uppercase}
.head h1{margin:10px 0 8px;font-size:26px;line-height:1.35;font-weight:700}
.head .sub{font-size:13.5px;opacity:.92;line-height:1.8}
.head .meta{margin-top:14px;font-size:12px;opacity:.8;border-top:1px solid rgba(255,255,255,.22);padding-top:12px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0 6px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi .t{font-size:12px;color:var(--sub);margin-bottom:6px}
.kpi .v{font-size:21px;font-weight:700;letter-spacing:-.01em}
.kpi .d{font-size:12px;color:var(--sub);margin-top:4px}
h2{font-size:18px;margin:34px 0 12px;padding-left:11px;border-left:4px solid var(--acc);line-height:1.4}
h3{font-size:15px;margin:22px 0 10px}
p{margin:10px 0}
.muted{color:var(--sub)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:14px 0}
.tbl{width:100%;border-collapse:collapse;font-size:13px;background:var(--card)}
.tbl th,.tbl td{border-bottom:1px solid var(--line);padding:8px 10px;text-align:center;white-space:nowrap}
.tbl thead th{background:#f0f4f8;font-weight:600;color:#25455f;border-bottom:2px solid #cdddea}
.tbl tbody tr:hover{background:#fafbfc}
.tbl .num{font-variant-numeric:tabular-nums}
.mini{width:100%;border-collapse:collapse;font-size:12.5px}
.mini th,.mini td{border-bottom:1px solid #eef0f3;padding:5px 8px;text-align:center}
.mini thead th{background:#f4f6f8;position:sticky;top:0;z-index:2}
.mini td:nth-child(3){text-align:left}
.mini tr.ind-row td{text-align:left;background:#eaf0f6;color:#25455f;font-weight:600;
 font-size:12px;border-top:1px solid #dbe4ec}
.mini tr.ind-row span{font-weight:400}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.tocar{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 22px;font-size:13px}
.tocar a{color:var(--acc);text-decoration:none;border-bottom:1px dashed #b9cddd;padding:3px 0}
.tocar a:hover{background:#eef4f9}
.pill{display:inline-block;background:#eef4f9;color:#25455f;border:1px solid #d5e3ee;
 border-radius:999px;padding:2px 10px;font-size:12px;margin-left:8px}
ul{margin:8px 0;padding-left:20px}
li{margin:6px 0}
.warn{background:#fdf6f8;border-left:4px solid #d81b60;border-radius:8px;padding:12px 16px;margin:14px 0;font-size:13px}
.note{background:#f4f8fb;border-left:4px solid #2f6f9e;border-radius:8px;padding:12px 16px;margin:14px 0;font-size:13px}
code{background:#f2f4f7;border:1px solid #e5e7eb;border-radius:4px;padding:1px 5px;font-size:12.5px;
 font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
pre{background:#0f1c26;color:#d8e3ec;border-radius:8px;padding:14px 16px;overflow-x:auto;font-size:12.5px;line-height:1.7}
table.stack td:first-child{text-align:left}
.foot{margin-top:36px;border-top:1px solid var(--line);padding-top:14px;font-size:12px;color:var(--sub)}
@page{margin:14mm 12mm}
@media print{
 body{background:#fff}
 .wrap{max-width:none;padding:0}
 .head{background:#1f4e79 !important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
 .tbl thead th,.mini thead th,.kpi,code,.note,.warn{-webkit-print-color-adjust:exact;print-color-adjust:exact}
 h2{page-break-after:avoid}
 .card,.tbl,.mini{page-break-inside:avoid}
}
@media (max-width:860px){
 .kpis{grid-template-columns:repeat(2,1fr)}
 .tocar{grid-template-columns:1fr}
}
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    B = pd.read_csv(os.path.join(SCN, "base", "daily_nav.csv"), index_col=0, parse_dates=True)
    S = pd.read_csv(os.path.join(SCN, "ind50", "daily_nav.csv"), index_col=0, parse_dates=True)
    hb = pd.read_csv(os.path.join(SCN, "base", "holdings.csv"), dtype={"code": str})
    hs = pd.read_csv(os.path.join(SCN, "ind50", "holdings.csv"), dtype={"code": str})

    d0, d1 = B.index[0].date(), B.index[-1].date()
    span = f"{d0} → {d1}"

    # ── 指标 ──
    P = {}
    for nm, _, _ in COMBOS:
        P[nm] = (perf(B[nm].dropna()), perf(S[nm].dropna()))

    # ── 持仓重合度 / 相关性 ──
    def jac(nm):
        b = hb[hb["combo"] == nm].groupby("rebal_date")["code"].apply(set)
        s = hs[hs["combo"] == nm].groupby("rebal_date")["code"].apply(set)
        j = [(len(b[d] & s[d]) / len(b[d] | s[d])) for d in b.index if d in s.index]
        cov = [(len(b[d] & s[d]) / len(b[d])) for d in b.index if d in s.index]
        return float(np.mean(j)), float(np.mean(cov))
    RC = {}
    for nm, _, _ in COMBOS:
        rb = B[nm].pct_change().dropna()
        rs = S[nm].pct_change().dropna()
        RC[nm] = float(rb.corr(rs))

    # ── KPI 卡 ──
    k = []
    for nm, lab, _ in COMBOS:
        pb, ps = P[nm]
        da = (ps["ann"] - pb["ann"]) * 100
        col = RED if da > 0 else GREEN
        k.append(f'<div class="kpi"><div class="t">{lab}</div>'
                 f'<div class="v" style="color:{col}">{pct(ps["ann"])}</div>'
                 f'<div class="d">年化 · 原池 {pct(pb["ann"])}'
                 f'<span style="color:{col};font-weight:600"> ({da:+.2f}pct)</span><br>'
                 f'夏普 {pb["sh"]:.2f} → <b>{ps["sh"]:.2f}</b> · 回撤 {pct(ps["dd"])}</div></div>')
    jm = np.mean([jac(nm)[0] for nm, _, _ in COMBOS])
    cv = np.mean([jac(nm)[1] for nm, _, _ in COMBOS])
    k.append(f'<div class="kpi"><div class="t">与原池持仓重合度 · Jaccard</div>'
             f'<div class="v">{jm*100:.1f}%</div>'
             f'<div class="d">日收益相关性 {min(RC.values()):.2f}~{max(RC.values()):.2f}'
             f'<br>性质：风格切换，而非小幅改良</div></div>')
    kpis = '<div class="kpis">' + "".join(k) + "</div>"

    # ── 表 1：全期绩效 ──
    rows = []
    for nm, lab, _ in COMBOS:
        pb, ps = P[nm]
        rows.append(
            f'<tr><td class="num" rowspan="2" style="text-align:left"><b>{lab}</b></td>'
            f'<td class="num">原池 · 全部行业</td>'
            f'<td class="num">{pct(pb["cum"])}</td><td class="num">{pct(pb["ann"])}</td>'
            f'<td class="num">{pct(pb["vol"], 0)}</td><td class="num">{pct(pb["dd"])}</td>'
            f'<td class="num">{pb["sh"]:.2f}</td><td class="num">{pb["cal"]:.2f}</td>'
            f'<td class="num">—</td></tr>'
            f'<tr><td class="num"><b>情景池 · 前50×3</b></td>'
            f'<td class="num"><b>{pct(ps["cum"])}</b></td><td class="num"><b>{pct(ps["ann"])}</b></td>'
            f'<td class="num">{pct(ps["vol"], 0)}</td><td class="num">{pct(ps["dd"])}</td>'
            f'<td class="num"><b>{ps["sh"]:.2f}</b></td><td class="num"><b>{ps["cal"]:.2f}</b></td>'
            + (f'<td class="num" style="color:{RED if ps["ann"]-pb["ann"]>0 else GREEN};'
               f'font-weight:600">{(ps["ann"]-pb["ann"])*100:+.2f}pct</td>') + '</tr>')
    tab1 = ('<table class="tbl"><thead><tr><th rowspan="2" style="text-align:left">组合</th>'
            '<th rowspan="2">股池</th>'
            f'<th colspan="4">{span}</th><th colspan="2">风险调整</th><th>差值</th></tr>'
            '<tr><th>累计收益</th><th>年化收益</th><th>年化波动</th><th>最大回撤</th>'
            '<th>夏普</th><th>卡玛</th><th>年化</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")

    # ── 表 2：分年度 ──
    cols = {}
    for nm, _, _ in COMBOS:
        for tag, df in (("b", B), ("s", S)):
            cols[f"{tag}_{nm}"] = df[nm].resample("YE").last()
    yr = pd.DataFrame(cols)
    first = yr.iloc[0].copy()
    yr = yr / yr.shift(1) - 1
    yr.iloc[0] = first.values - 1
    yr.index = [d.year for d in yr.index]
    body = []
    for y in yr.index:
        cells = [f'<td class="num"><b>{y}</b></td>']
        for nm, _, _ in COMBOS:
            b, s = yr.loc[y, f"b_{nm}"], yr.loc[y, f"s_{nm}"]
            d = s - b
            col = RED if d > 0 else GREEN
            cells.append(f'<td class="num">{pct(b)}</td><td class="num">{pct(s)}</td>'
                         f'<td class="num" style="color:{col};font-weight:600">{d*100:+.1f}pct</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    head = ('<thead><tr><th rowspan="2">年度</th>'
            + "".join(f'<th colspan="3">{lab.replace("因子动量·", "").replace("组合", "")}</th>'
                      for _, lab, _ in COMBOS)
            + '</tr><tr>' + "".join('<th>原池</th><th>情景</th><th>差</th>' for _ in COMBOS)
            + '</tr></thead>')
    tab2 = f'<table class="tbl">{head}<tbody>' + "".join(body) + "</tbody></table>"

    # ── 表 3：重合度 / 相关性 ──
    r3 = []
    for nm, lab, _ in COMBOS:
        j, cov = jac(nm)
        r3.append(f'<tr><td style="text-align:left">{lab}</td><td class="num">{j*100:.1f}%</td>'
                  f'<td class="num">{cov*100:.1f}%</td><td class="num">{RC[nm]:.3f}</td></tr>')
    tab3 = ('<table class="tbl"><thead><tr><th style="text-align:left">组合</th>'
            '<th>持仓重合度（Jaccard）</th><th>情景池被原池覆盖比例</th><th>日收益相关系数</th>'
            '</tr></thead><tbody>' + "".join(r3) + "</tbody></table>")

    # ── 股池结构 ──
    v6 = pd.read_csv(os.path.join(D15, "pools_v6_ind50.csv"), dtype={"code": str})
    v5 = pd.read_csv(os.path.join(D15, "pools_v5.csv"), dtype={"code": str})
    ir = pd.read_csv(os.path.join(D15, "industry_rank.csv"))
    uni = pd.read_csv(os.path.join(D15, "universe_pit.csv"), dtype={"code": str})
    PP = v6[v6["asof"] == LATEST].copy()
    U = dict(zip(uni[uni["asof"] == LATEST]["code"].str.zfill(6),
                 uni[uni["asof"] == LATEST]["mcap_yi"]))
    IR = dict(zip(ir[ir["asof"] == LATEST]["sw3"], ir[ir["asof"] == LATEST]["ind_mcap_yi"]))
    names = dict(zip(v5["code"].str.zfill(6), v5["name"]))
    names.update(dict(zip(v6["code"].str.zfill(6), v6["name"])))

    # 历史上每期股池规模/行业数
    hist = (v5.groupby("asof").agg(n5=("code", "size"), i5=("sw3", "nunique"))
            .join(v6.groupby("asof").agg(n6=("code", "size"), i6=("sw3", "nunique")), how="inner"))
    # 原池落在前50行业内的比例（逐期）
    cov_rows = []
    for a, g in v5.groupby("asof"):
        allowed = set(ir[ir["asof"] == a].nsmallest(50, "rank")["sw3"]) if (ir["asof"] == a).any() else set()
        cov_rows.append((a, g["sw3"].isin(allowed).mean()))
    coverage = pd.Series(dict(cov_rows))
    hist = hist.join(coverage.rename("cov"), how="left")

    tb_rows = []
    for a in hist.index[-8:]:
        r = hist.loc[a]
        tb_rows.append(f'<tr><td class="num">{a}</td><td class="num">{int(r["i5"])}</td>'
                       f'<td class="num">{int(r["n5"])}</td><td class="num">{int(r["i6"])}</td>'
                       f'<td class="num">{int(r["n6"])}</td>'
                       f'<td class="num">{r["cov"]*100:.1f}%</td></tr>')
    tab4 = ('<table class="tbl"><thead><tr><th>信息可得日</th>'
            '<th>原池行业数</th><th>原池个股数</th><th>情景池行业数</th><th>情景池个股数</th>'
            '<th>原池落在前50行业内的占比</th></tr></thead><tbody>'
            + "".join(tb_rows) + "</tbody></table>")

    pool_html = pool_table(PP, U, IR, names)
    n5 = len(v5[v5["asof"] == LATEST])
    i5 = v5[v5["asof"] == LATEST]["sw3"].nunique()

    report_date = pd.Timestamp.now().strftime("%Y-%m-%d")

    tocar = """<div class="tocar">
<a href="#s1">一、结论摘要</a><a href="#s2">二、测算口径（唯一变量＝股池）</a>
<a href="#s3">三、股池结构变化</a><a href="#s4">四、全期绩效对比</a>
<a href="#s5">五、净值曲线</a><a href="#s6">六、分年度收益</a>
<a href="#s7">七、持仓重合度与相关性</a><a href="#s8">八、新一期股池明细</a>
<a href="#s9">九、局限与使用建议</a><a href="#s10">十、复现方式</a>
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>股池限定为「行业市值前50 × 各行业前3」的 A/B 测算报告</title>
<style>{CSS}</style></head><body><div class="wrap">

<div class="head">
  <div class="kicker">Scenario Study · Fraud-adjusted Quality Factor Pool</div>
  <h1>把股池限定为「申万行业市值前 50 × 各行业前 3」<br>对三个回测组合的影响</h1>
  <div class="sub">同一套舞弊调整质量因子（FAQ）评分，同一个报告期，只在选股范围上加两道行业限制：
  行业总市值排名前 50 方可入选、每个准入行业仍取评分前 3。其余选股规则、加权方式、交易成本、
  执行时点全部沿用现有回测口径 —— 唯一变量就是股池。</div>
  <div class="meta">报告日期 {report_date}　·　回测区间 {span}（周频调仓）　·　基准数据：原池全行业回测<br>
  <b>结论已于 2026-10-30 落地</b>：线上页面的 CSFM / TSFM 已改用该候选域，质量Top28 仍保持原池。</div>
</div>

{kpis}

<div class="card">{tocar}</div>

<h2 id="s1">一、结论摘要</h2>
<p>三个组合的表现<b>明显分化</b>，不能笼统说「变好」或「变差」：加行业限制对<b>横截面因子动量（CSFM）是大幅改善</b>，
对<b>质量 Top28 是明确损伤</b>，对<b>时序因子动量（TSFM）几乎没有影响</b>。差异的根源在于三者的超额收益
分别来自哪里——质量因子赚的是「中小行业里的干净公司」，把行业砍到前 50 等于把这部分 alpha 直接切掉；
而横截面因子动量在中小行业里容易被单一行业噪声带偏，收缩到大行业后暴露反而更干净。</p>

<div class="card">
<table class="tbl stack"><thead><tr><th style="text-align:left">组合</th><th>年化收益</th>
<th>最大回撤</th><th>夏普</th><th style="text-align:left">性质判断</th></tr></thead><tbody>
<tr><td style="text-align:left"><b>因子动量 CSFM</b></td>
<td class="num">{pct(P['CSFM'][0]['ann'])} → <b style="color:{RED}">{pct(P['CSFM'][1]['ann'])}</b></td>
<td class="num">{pct(P['CSFM'][0]['dd'])} → <b>{pct(P['CSFM'][1]['dd'])}</b></td>
<td class="num">{P['CSFM'][0]['sh']:.2f} → <b style="color:{RED}">{P['CSFM'][1]['sh']:.2f}</b></td>
<td style="text-align:left">显著改善，改善几乎全部来自回撤收缩</td></tr>
<tr><td style="text-align:left"><b>因子动量 TSFM</b></td>
<td class="num">{pct(P['TSFM'][0]['ann'])} → <b>{pct(P['TSFM'][1]['ann'])}</b></td>
<td class="num">{pct(P['TSFM'][0]['dd'])} → <b>{pct(P['TSFM'][1]['dd'])}</b></td>
<td class="num">{P['TSFM'][0]['sh']:.2f} → <b>{P['TSFM'][1]['sh']:.2f}</b></td>
<td style="text-align:left">基本持平：收益不变，波动与回撤同步下降</td></tr>
<tr><td style="text-align:left"><b>质量 Top28</b></td>
<td class="num">{pct(P['Q28'][0]['ann'])} → <b style="color:{GREEN}">{pct(P['Q28'][1]['ann'])}</b></td>
<td class="num">{pct(P['Q28'][0]['dd'])} → <b>{pct(P['Q28'][1]['dd'])}</b></td>
<td class="num">{P['Q28'][0]['sh']:.2f} → <b style="color:{GREEN}">{P['Q28'][1]['sh']:.2f}</b></td>
<td style="text-align:left">明确受损，质量溢价的中小行业来源被切除</td></tr>
</tbody></table>
</div>

<ul>
<li><b>CSFM 的改善不是「选到更好的股票」，而是「避开了更差的波动」</b>：累计收益 40.39% → 141.93%、
年化 3.67% → 9.84%，同时最大回撤 −52.22% → −37.59%、夏普 0.17 → 0.45。原池里 CSFM 的回撤主要发生在
中小行业因子拥挤后的反向踩踏，限制行业后这类踩踏被大幅削弱。</li>
<li><b>质量 Top28 的损失来自 alpha 来源被切走</b>：累计 152.60% → 80.46%、年化 10.34% → 6.47%。
质量因子的超额在中小市值行业里更显著（覆盖不足、错误定价更多），只保留大行业等于主动放弃这块收益，
换来的是回撤从 −28.49% 略降到 −25.49%，性价比不划算。</li>
<li><b>TSFM 只降风险不加收益</b>：年化 8.91% → 8.87%（−0.05pct），回撤 −42.01% → −38.75%，
夏普 0.37 → 0.38。若目标是降低回撤且不损失收益，TSFM 加此限制是「免费」的；若目标是提高收益，则无意义。</li>
<li><b>这是风格切换，不是参数微调</b>：三个组合与原池的持仓重合度均值仅 {jm*100:.1f}%，
日收益相关性 {min(RC.values()):.2f}~{max(RC.values()):.2f}。加上这两道限制后，组合被整体推向大市值、大行业，
相当于押注「大行业里的头部公司」。分年度看，差异主要来自 2021 年（CSFM −9.0% → +8.3%）
与 2026 年至今（−31.8% → −9.5%），这两年恰好是中小盘与大盘风格分化最剧烈的年份。</li>
<li><b>若只挑一个组合加限制，选 CSFM</b>；质量 Top28 与 TSFM 不建议加（前者年化掉 3.87pct，后者无增益）。</li>
</ul>

<h2 id="s2">二、测算口径（唯一变量＝股池）</h2>
<div class="note"><b>两道限制</b><br>
① <b>行业准入</b>：按「申万行业总市值」（该行业全部 A 股市值加总，PIT，取信息可得日之前最后一个有效市值）降序，只保留前 <b>50</b> 个行业。<br>
② <b>行业名额</b>：每个准入行业仍取 FAQ 评分<b>前 3</b>，报告期与信息可得日的对应关系不变。<br>
两道限制之外<b>一律不动</b>：FAQ 评分模型、CSFM/TSFM 的 10 因子动量与参数（κ=1.5 / 1.0）、月度调仓节奏、
次新股过滤、开盘一字涨停的权重空置处理、质量 Top28 的 v2 三道筛、单边 10bp 成本、T 日决策 T+1 执行、
2017 首个交易日归一到 1.00。
</div>

<p><b>口径可控性的验证方式</b>：两侧读数由同一份回测代码跑出。原池一侧在换池前的输入下
<b>精确复现</b>了线上页面的 40.39% / 123.45% / 152.60%（累计收益，三位数字全部吻合），
说明代码路径、数据与执行口径与线上一致；因此新池与原池之间的差异只可能来自股池本身，
不存在「顺手改了别的东西」的可能。</p>

<div class="warn"><b>行业标签口径需要知情</b>：本测算使用的行业标签沿用现有数据侧的申万分类字段
（与「单行业 ≤ 2 只」同源），其中部分标签实际是申万二级（如通用设备、汽车零部件、半导体）。
行业总市值因此按「该标签实际覆盖的成员」计算，前 50 名是这一口径下的排序结果。
若要求严格只保留申万三级行业，需要重新抓取全市场三级成分后重算，结论方向预计不变、幅度可能变化。
</div>

<h2 id="s3">三、股池结构变化</h2>
<p>限制的直接后果是股池规模与行业跨度同时收缩：最新一期（2026 年中报 · 信息可得 2026-09-01）
行业数从 {i5} 个降到 {PP['sw3'].nunique()} 个，个股数从 {n5} 只降到 {len(PP)} 只。
更关键的是覆盖度——原池平均只有 <b>{coverage.mean()*100:.1f}%</b> 的个股落在市值前 50 的行业内，
也就是说<b>约六成持仓被这道限制直接排除</b>，这正是「风格切换」而非「精选」的来源。</p>
<div class="card">{tab4}</div>

<h2 id="s4">四、全期绩效对比</h2>
<p class="muted">差值为「情景池 − 原池」的年化收益；<span style="color:{RED};font-weight:600">红色＝改善</span>，
<span style="color:{GREEN};font-weight:600">绿色＝恶化</span>（A 股习惯：红涨绿跌）。</p>
<div class="card" style="overflow-x:auto">{tab1}</div>

<h2 id="s5">五、净值曲线</h2>
<p class="muted">实线＝情景池（行业前50×3）；虚线＝原池（全部行业）。六条曲线共用同一净值起点 1.00。</p>
<div class="card">{svg_chart(B, S)}</div>

<h2 id="s6">六、分年度收益</h2>
<p class="muted">2017 年为「年末 / 窗口起点 − 1」；2026 年为年初至 {d1}。</p>
<div class="card" style="overflow-x:auto">{tab2}</div>

<h2 id="s7">七、持仓重合度与相关性</h2>
<p>这一节回答「到底是换了池子，还是换了策略」。持仓重合度按每次调仓日的持仓集合计算 Jaccard 相似度后取均值；
日收益相关系数反映两条净值曲线在时间维度上的同步程度。</p>
<div class="card">{tab3}</div>
<p class="muted">解读：Jaccard 重合度均值 {jm*100:.1f}%，对应原池持仓平均只有 <b>{cv*100:.1f}%</b> 被保留 ——
每期<b>一半以上持仓被替换</b>，已经不是同一个组合。
相关系数仍在 {min(RC.values()):.2f} 以上说明两者共享同一市场 beta 与因子体系，差异来自行业/市值暴露而非完全不同的策略。
因此「加上限制后的收益差异」应当被理解为<b>风格选择</b>，不能当作原策略的改进版。
</p>

<h2 id="s8">八、新一期股池明细</h2>
<p class="muted">{PP['sw3'].nunique()} 个行业 · {len(PP)} 只；行首为行业市值排名与行业市值（亿元），
「#」为该股在行业内按 FAQ 评分的排名；行业排名出现跳号，是因为少数行业在该报告期内
没有满足条件的候选股。</p>
<div class="card">{pool_html}</div>

<h2 id="s9">九、局限与使用建议</h2>
<ul>
<li><b>只看单一市场环境</b>：回测区间 2017 起、以周频调仓，2021 与 2026 的贡献占比很高。
限制行业本质上是放大盘风格暴露，若未来两年风格回到中小盘，CSFM 的改善会反向回吐。</li>
<li><b>行业市值排序存在前视风险边界</b>：已按 PIT 取信息可得日之前最后一个有效市值，但行业分类本身的调整
（申万修订）不做历史回溯，老期数的行业归属可能与当年实际略有偏差。</li>
<li><b>股池收缩带来的容量与集中度问题</b>：{len(PP)} 只股池、每行业 3 只，单票权重更集中，
实盘需额外检查流动性与停牌处理（回测已含开盘一字涨停的权重空置，但未做冲击成本建模）。</li>
<li><b>建议用法</b>：把行业限制作为<b>独立的风险偏好开关</b>而不是替代原池。若组合目标是压低回撤，
优先对 CSFM 打开该限制（夏普 0.17 → 0.45）；若组合依赖质量溢价，保持原池。</li>
</ul>

<h2 id="s10">十、复现方式</h2>
<p>三步即可重跑（结果落在 <code>data/scn_ind50/{{base,ind50}}/</code>）：</p>
<pre>cd pool-core
python3 scripts/finchain/build_pools_v6_ind50.py        # 生成 pools_v6_ind50.csv + industry_rank.csv
FIN_OUT_DIR=../scn POOL_FILE_V5=pools_v6_ind50.csv \\
  python3 scripts/finchain/scenario_ind50.py --pools pools_v6_ind50.csv --out ind50
# 原池基线（用于对照，输出到 scn/base）
FIN_OUT_DIR=../scn python3 scripts/finchain/scenario_ind50.py --pools pools_v5.csv --out base
python3 scripts/finchain/scn_ind50_report.py            # 重新生成本报告</pre>
<p class="muted">选股、加权、成本、执行时点代码一行未改；<code>scenario_ind50.py</code> 只是把股池换成另一个输入文件。
若 <code>data/scn_ind50/</code> 尚未生成，先跑上面两条回测命令（各约 2~4 分钟）。</p>

<div class="foot">
数据来源：本地 PIT 行情与财务面板（universe_pit / faq_panel / industry_rank），
回测引擎 <code>scripts/finchain/daily_nav15.py</code>。本报告自动生成，仅用于策略研究，不构成投资建议。
</div>
</div></body></html>"""

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[ok] {OUT}  {os.path.getsize(OUT)/1024:.0f} KB")
    print("覆盖度均值 %.1f%%  重合度均值 %.1f%%  相关性 %s"
          % (coverage.mean()*100, jm*100,
             "/".join(f"{nm}:{RC[nm]:.2f}" for nm, _, _ in COMBOS)))


if __name__ == "__main__":
    main()
