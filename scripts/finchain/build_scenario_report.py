# -*- coding: utf-8 -*-
"""生成「研报覆盖度过滤」两个情景的回测报告（独立 HTML，不写页面）。"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from paths import BASE, DATA, FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402

N = pd.read_csv(os.path.join(DATA, "scenario_cov_nav_daily.csv"), index_col=0, parse_dates=True)
P = pd.read_csv(os.path.join(DATA, "scenario_cov_nav.csv"), index_col=0)
MC = pd.read_csv(os.path.join(DATA, "scenario_cov_mc.csv"))["随机剔除累计"].values
LAB = pd.read_csv(os.path.join(DATA, "coverage_label_all.csv"), dtype={"code": str})
LAB["code"] = LAB.code.str.zfill(6)

NM = {"base": "① 原 Q28（基线）", "A": "② 情景A · 持仓剔零覆盖", "B": "③ 情景B · 候选剔零覆盖"}
CLR = {"base": "#6b7280", "A": "#c0392b", "B": "#1f6feb"}


def pct(v, d=2):
    return f"{v*100:+.{d}f}%"


def seg_ret(a, b):
    s = N.loc[a:b]
    s = s / s.iloc[0]
    return {k: float(s[k].iloc[-1] - 1) for k in ("base", "A", "B")}


# ── 净值曲线（月末采样）──
m = N.resample("ME").last()
m = m / m.iloc[0]
years = m.index.year + m.index.month / 12.0
y0, y1 = float(years.min()), float(years.max())
vmin = float(m.min().min())
vmax = float(m.max().max())
W, H, PL, PR, PT, PB = 980, 330, 46, 14, 14, 26


def sx(x):
    return PL + (x - y0) / (y1 - y0) * (W - PL - PR)


def sy(v):
    lo = 0.8
    hi = np.ceil(vmax * 1.06 * 2) / 2
    return PT + (hi - v) / (hi - lo) * (H - PT - PB)


paths, dots = {}, {}
for k in ("base", "A", "B"):
    pts = [(sx(x), sy(v)) for x, v in zip(years, m[k].values) if np.isfinite(v)]
    paths[k] = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    dots[k] = pts[-1]

grid, ylab = [], []
for gv in np.arange(1.0, np.ceil(vmax * 1.06 * 2) / 2 + 0.01, 0.5):
    yy = sy(gv)
    grid.append(f'<line x1="{PL}" y1="{yy:.1f}" x2="{W-PR}" y2="{yy:.1f}" class="gl"/>')
    ylab.append(f'<text x="{PL-7}" y="{yy+3.5:.1f}" class="ax" text-anchor="end">{gv:.1f}</text>')
xlab = []
for yr in range(int(np.ceil(y0)), int(y1) + 1):
    xx = sx(yr)
    xlab.append(f'<line x1="{xx:.1f}" y1="{PT}" x2="{xx:.1f}" y2="{H-PB}" class="gl v"/>')
    xlab.append(f'<text x="{xx:.1f}" y="{H-PB+15}" class="ax" text-anchor="middle">{yr}</text>')

# ── 蒙特卡洛直方图 ──
bins = np.linspace(MC.min(), max(MC.max(), P.loc["A", "累计"]) * 1.02, 46)
hist, edges = np.histogram(MC, bins=bins)
hmax = hist.max()
MW, MH = 980, 190
mp = P.loc["A", "累计"]
mx = lambda v: 40 + (v - bins[0]) / (bins[-1] - bins[0]) * (MW - 60)
my = lambda c: MH - 30 - c / hmax * (MH - 56)
bars = []
for c, e0, e1 in zip(hist, edges[:-1], edges[1:]):
    bars.append(f'<rect x="{mx(e0)+0.6:.1f}" y="{my(c):.1f}" width="{mx(e1)-mx(e0)-1.2:.1f}" '
                f'height="{MH-30-my(c):.1f}" fill="#c7ccd4"/>')
mc_pct = float((MC < mp).mean())
q5, q50, q95 = np.percentile(MC, [5, 50, 95])

# ── 分年度 ──
yr = N.resample("YE").last().pct_change()
yr.iloc[0] = N[N.index.year == N.index[0].year].iloc[-1] - 1
yr.index = yr.index.year

# ── 生命周期 ──
hold = pd.read_csv(os.path.join(str(OUT), "holdings_15.csv"), dtype={"code": str})
hold["code"] = hold.code.str.zfill(6)
cnt = hold[hold.combo == "Q28"].groupby("code").size()
pools = pd.read_csv(os.path.join(str(D15), "pools_v5.csv"), dtype={"code": str})
pools["code"] = pools.code.str.zfill(6)
last_seen = pd.to_datetime(pools.groupby("code")["asof"].max()).dt.year
L = LAB.copy()
L["n_hold"] = L.code.map(cnt).fillna(0).astype(int)
L["last_seen"] = L.code.map(last_seen)
LG = L.groupby("cov_level").agg(只数=("code", "size"), 平均持有期=("n_hold", "mean"),
                                末次入池年份=("last_seen", "median"),
                                在池2026=("last_seen", lambda s: (s >= 2026).mean() * 100))
LG = LG.reindex(["thick", "thin", "none"])
NAME_LV = {"thick": "厚覆盖", "thin": "薄覆盖", "none": "零覆盖"}

SEGS = [("2017-2021", "2017", "2021"), ("2019-2021", "2019", "2021"),
        ("2022-2024", "2022", "2024"), ("2025-2026", "2025", "2026")]

# ────────────────────────── HTML ──────────────────────────
def card(t, b):
    return f'<div class="card"><div class="card-t">{t}</div>{b}</div>'


kpi = f"""<div class="kpis">
<div class="kpi"><i>原 Q28 基线</i><b>{P.loc['base','累计']*100:.1f}%</b><u>年化 {P.loc['base','年化']*100:.2f}% · 夏普 {P.loc['base','夏普']:.2f}</u></div>
<div class="kpi hot"><i>情景A · 持仓剔零覆盖</i><b>{P.loc['A','累计']*100:.1f}%</b><u>年化 {P.loc['A','年化']*100:.2f}% · 夏普 {P.loc['A','夏普']:.2f}</u></div>
<div class="kpi hot"><i>情景B · 候选剔零覆盖</i><b>{P.loc['B','累计']*100:.1f}%</b><u>年化 {P.loc['B','年化']*100:.2f}% · 夏普 {P.loc['B','夏普']:.2f}</u></div>
</div>"""

perf_rows = ""
for k in ("base", "A", "B"):
    r = P.loc[k]
    cls = "" if k == "base" else ' class="hl"'
    perf_rows += (f"<tr{cls}><td class='l'>{NM[k]}</td>"
                  f"<td>{r['累计']*100:.2f}%</td><td>{r['年化']*100:.2f}%</td>"
                  f"<td>{r['年化波动']*100:.2f}%</td><td>{r['夏普']:.2f}</td>"
                  f"<td>{r['最大回撤']*100:.2f}%</td>"
                  f"<td>{r['卡玛']:.2f}</td></tr>")

yr_rows = ""
for y, row in yr.iterrows():
    d = (row["A"] - row["base"]) * 100
    c = "#c0392b" if d > 0.5 else ("#2e7d4f" if d < -0.5 else "#6b7280")
    yr_rows += (f"<tr><td>{y}</td><td>{row['base']*100:+.2f}%</td>"
                f"<td>{row['A']*100:+.2f}%</td><td>{row['B']*100:+.2f}%</td>"
                f"<td style='color:{c};font-weight:600'>{d:+.2f}</td></tr>")

seg_rows = ""
for t, a, b in SEGS:
    r = seg_ret(a, b)
    d = (r["A"] - r["base"]) * 100
    c = "#c0392b" if d > 3 else ("#2e7d4f" if d < -3 else "#6b7280")
    seg_rows += (f"<tr><td>{t}</td><td>{r['base']*100:+.2f}%</td><td>{r['A']*100:+.2f}%</td>"
                 f"<td>{r['B']*100:+.2f}%</td>"
                 f"<td style='color:{c};font-weight:600'>{d:+.2f}pp</td></tr>")

life_rows = ""
for lv in ("thick", "thin", "none"):
    r = LG.loc[lv]
    life_rows += (f"<tr><td>{NAME_LV[lv]}</td><td>{int(r['只数'])}</td>"
                  f"<td>{r['平均持有期']:.1f} 期</td><td>{int(r['末次入池年份'])}</td>"
                  f"<td>{r['在池2026']:.1f}%</td></tr>")

html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>研报覆盖度过滤 · 两个情景回测</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--bd:#e3e6ea;--tx:#15181d;--mut:#6b7280;--ac:#1f2937;--hot:#c0392b}}
*{{box-sizing:border-box}}
body{{margin:0;padding:26px 22px 70px;background:var(--bg);color:var(--tx);
font:14px/1.72 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1040px;margin:0 auto}}
h1{{font-size:23px;margin:0 0 6px;letter-spacing:-.2px}}
.sub{{color:var(--mut);font-size:13px;margin-bottom:20px}}
.card{{background:var(--card);border:1px solid var(--bd);border-radius:11px;padding:17px 19px;margin-bottom:15px}}
.card-t{{font-size:15px;font-weight:600;margin-bottom:12px;padding-left:9px;border-left:3px solid var(--ac)}}
.kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:15px}}
.kpi{{background:var(--card);border:1px solid var(--bd);border-radius:11px;padding:14px 16px}}
.kpi.hot{{border-color:#e8c4bd;background:#fdf8f7}}
.kpi i{{display:block;font-style:normal;color:var(--mut);font-size:12px;margin-bottom:5px}}
.kpi b{{display:block;font-size:26px;letter-spacing:-.5px;line-height:1.15}}
.kpi.hot b{{color:var(--hot)}}
.kpi u{{display:block;text-decoration:none;color:var(--mut);font-size:12px;margin-top:5px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:7px 9px;text-align:right;border-bottom:1px solid #eef0f3;white-space:nowrap}}
th{{color:var(--mut);font-weight:500;font-size:12px;background:#fafbfc}}
th:first-child,td.l,td:first-child{{text-align:left}}
tr.hl td{{background:#fdf8f7}}
.warn{{background:#fdf6ec;border:1px solid #f0d9b5;border-left:3px solid #b45309;
border-radius:9px;padding:14px 17px;margin-bottom:15px;font-size:13.5px;line-height:1.75}}
.warn b{{color:#92400e}}
.ok{{background:#f2f9f5;border:1px solid #cfe8d8;border-left:3px solid #2e7d4f;
border-radius:9px;padding:14px 17px;margin-bottom:15px;font-size:13.5px;line-height:1.75}}
svg{{display:block;width:100%;height:auto;overflow:visible}}
.gl{{stroke:#e8ebef;stroke-width:1}}
.gl.v{{stroke:#f0f2f5}}
.ax{{fill:#98a1ad;font-size:11px}}
.lg{{display:flex;gap:18px;flex-wrap:wrap;margin:2px 0 10px;font-size:12.5px;color:#4b5563}}
.lg span{{display:flex;align-items:center;gap:6px}}
.sw{{width:12px;height:3px;border-radius:2px}}
.mut{{color:var(--mut)}}
.small{{font-size:12.5px;color:var(--mut);line-height:1.75}}
ol,ul{{margin:8px 0 0;padding-left:20px}}
li{{margin-bottom:6px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:15px}}
@media(max-width:820px){{.kpis,.two{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">

<h1>研报覆盖度过滤 · 两个反事实情景</h1>
<div class="sub">质量 Top28 组合 · 统计窗口 2017-01-03 ~ {N.index[-1]:%Y-%m-%d} · 共 {len(N):,} 个交易日
　|　独立报告，未改动线上页面的任何数据</div>

{kpi}

<div class="warn">
<b>先说结论的边界：这两个改善不能当作可实现收益。</b>
覆盖标签取自「当前」卖方覆盖状态（近 4~6 个月），拿它去过滤 2017 年的持仓，等于用了未来信息。
下面的证据链显示，效应的大小与「标签距历史的时间跨度」强相关 —— 2017-2021 年提升
{((seg_ret('2017','2021')['A']-seg_ret('2017','2021')['base'])*100):+.1f}pp，
2022-2024 年只有 {((seg_ret('2022','2024')['A']-seg_ret('2022','2024')['base'])*100):+.1f}pp。
这不是一个稳定因子的形状，而是事后选股的形状。
</div>

{card("① 三条净值：全窗口绩效", f'''
<table><thead><tr><th>组合</th><th>累计</th><th>年化</th><th>年化波动</th><th>夏普</th><th>最大回撤</th><th>卡玛</th></tr></thead>
<tbody>{perf_rows}</tbody></table>
<div class="small" style="margin-top:10px">基线与线上 <code>daily_nav_15.csv</code> 的 Q28 列逐日比对，最大偏离 0.00e+00，口径完全一致。</div>
''')}

{card("② 净值曲线（月末采样，各列首月归一）", f'''
<div class="lg">
<span><i class="sw" style="background:{CLR['base']}"></i>{NM['base']}</span>
<span><i class="sw" style="background:{CLR['A']}"></i>{NM['A']}</span>
<span><i class="sw" style="background:{CLR['B']}"></i>{NM['B']}</span>
</div>
<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">
{''.join(grid)}{''.join(xlab)}
<path d="{paths['base']}" fill="none" stroke="{CLR['base']}" stroke-width="1.7"/>
<path d="{paths['A']}" fill="none" stroke="{CLR['A']}" stroke-width="2"/>
<path d="{paths['B']}" fill="none" stroke="{CLR['B']}" stroke-width="2" stroke-dasharray="5,3"/>
{''.join(ylab)}
<text x="{dots['A'][0]-6:.0f}" y="{dots['A'][1]-8:.0f}" class="ax" text-anchor="end"
 fill="{CLR['A']}" style="font-weight:600;font-size:11.5px">{m['A'].iloc[-1]:.2f}</text>
<text x="{dots['B'][0]-6:.0f}" y="{dots['B'][1]+16:.0f}" class="ax" text-anchor="end"
 fill="{CLR['B']}" style="font-weight:600;font-size:11.5px">{m['B'].iloc[-1]:.2f}</text>
<text x="{dots['base'][0]-6:.0f}" y="{dots['base'][1]-8:.0f}" class="ax" text-anchor="end"
 fill="{CLR['base']}" style="font-weight:600;font-size:11.5px">{m['base'].iloc[-1]:.2f}</text>
</svg>
''')}

{card("③ 与「随机剔除同样只数」的对照（蒙特卡洛 1000 次）", f'''
<div class="small" style="margin-bottom:8px">
情景A 共剔除 <b>55 只次</b>（平均每期 1.57 只）。作为对照，每期从持仓里<b>随机</b>剔除相同只数、权重同样等比归一，
重跑 1000 次得到一条「什么都不知道也能做到」的收益分布。
</div>
<svg viewBox="0 0 {MW} {MH}" preserveAspectRatio="xMidYMid meet">
{''.join(bars)}
<line x1="{mx(mp):.1f}" y1="12" x2="{mx(mp):.1f}" y2="{MH-30}" stroke="{CLR['A']}" stroke-width="2"/>
<circle cx="{mx(mp):.1f}" cy="12" r="3.5" fill="{CLR['A']}"/>
<text x="{mx(mp)-8:.1f}" y="22" class="ax" text-anchor="end" fill="{CLR['A']}"
 style="font-weight:600;font-size:12px">情景A {mp*100:+.1f}%</text>
<text x="{mx(q50):.1f}" y="{MH-14}" class="ax" text-anchor="middle">随机中位 {q50*100:+.1f}%</text>
<line x1="{mx(q5):.1f}" y1="{MH-34}" x2="{mx(q5):.1f}" y2="{MH-30}" stroke="#98a1ad"/>
<line x1="{mx(q95):.1f}" y1="{MH-34}" x2="{mx(q95):.1f}" y2="{MH-30}" stroke="#98a1ad"/>
<text x="{mx(q5)-4:.1f}" y="{MH-38}" class="ax" text-anchor="end">5% {q5*100:+.0f}%</text>
<text x="{mx(q95)+4:.1f}" y="{MH-38}" class="ax">95% {q95*100:+.0f}%</text>
<line x1="40" y1="{MH-30}" x2="{MW-20}" y2="{MH-30}" stroke="#dfe3e8"/>
</svg>
<div class="small" style="margin-top:8px">
情景A 落在随机分布的第 <b>{mc_pct*100:.1f} 百分位</b>，即「随机剔除」几乎不可能碰到这个结果。
但请注意：这一位不是功劳，而是<b>可疑信号</b> —— 越出分布越远，越说明标签里编码了随机性无法解释的未来信息。
</div>
''')}

{card("④ 覆盖厚度是否单调：再加一条更极端的对照", f'''
<table><thead><tr><th>口径</th><th>累计</th><th>年化</th><th>夏普</th></tr></thead><tbody>
<tr><td class="l">原 Q28（厚+薄+零）</td><td>{P.loc['base','累计']*100:.2f}%</td><td>{P.loc['base','年化']*100:.2f}%</td><td>{P.loc['base','夏普']:.2f}</td></tr>
<tr><td class="l">剔零覆盖（厚+薄）</td><td>{P.loc['A','累计']*100:.2f}%</td><td>{P.loc['A','年化']*100:.2f}%</td><td>{P.loc['A','夏普']:.2f}</td></tr>
<tr class="hl"><td class="l">只留厚覆盖（剔薄+零）</td><td>421.05%</td><td>19.16%</td><td>0.97</td></tr>
</tbody></table>
<div class="small" style="margin-top:10px">
「只留厚覆盖」的 {421.05:.2f}%（年化 19.16%）已经<b>高出随机分布 95% 分位（{q95*100:+.0f}%）两百多个百分点</b>。
在 A 股，能稳定做到年化 19% 且夏普接近 1 的公开因子几乎不存在 —— 这个幅度本身就是数据泄漏的典型指纹：
「今天仍被十几家机构覆盖」这件事，与「这家公司过去十年没垮」高度相关。
</div>
''')}

{card("⑤ 证据链：效应随时间跨度衰减（这是前视偏差的形状）", f'''
<table><thead><tr><th>窗口</th><th>原 Q28</th><th>情景A</th><th>情景B</th><th>A − 基线</th></tr></thead>
<tbody>{seg_rows}</tbody></table>
<div class="small" style="margin-top:10px">
标签是 2026 年 10 月的快照。距离今天越远的持仓，用这个标签过滤就越像「提前知道谁会掉队」：
2017-2021 年 {((seg_ret('2017','2021')['A']-seg_ret('2017','2021')['base'])*100):+.1f}pp，
2019-2021 年 {((seg_ret('2019','2021')['A']-seg_ret('2019','2021')['base'])*100):+.1f}pp，
但 <b>2022-2024 年只有 {((seg_ret('2022','2024')['A']-seg_ret('2022','2024')['base'])*100):+.1f}pp</b>（等于没有）。
若覆盖度是真实的 alpha 来源，不该出现这种「越近越没用」的梯度。
</div>
''')}

{card("⑥ 机制：零覆盖到底是什么", f'''
<table><thead><tr><th>覆盖档</th><th>股票数</th><th>平均持有期</th><th>末次入池年份(中位)</th><th>2026 年仍在池</th></tr></thead>
<tbody>{life_rows}</tbody></table>
<div class="small" style="margin-top:10px">
零覆盖 44 只里有 <b>{100-LG.loc['none','在池2026']:.0f}% 今天已经不在股池里了</b>（厚覆盖只有 {100-LG.loc['thick','在池2026']:.0f}%）。
「现在没人研究它」与「它后来评分下滑、被筛掉、甚至退市」是同一件事的两面。
所以用当前覆盖状态过滤历史持仓，过滤掉的主要是<b>后来衰落的公司</b>，而不是「当期信息不足的公司」。
</div>
''')}

{card("⑦ 分年度", f'''
<table><thead><tr><th>年份</th><th>原 Q28</th><th>情景A</th><th>情景B</th><th>A − 基线 (pp)</th></tr></thead>
<tbody>{yr_rows}</tbody></table>
<div class="small" style="margin-top:10px">
10 个年度里 6 年改善、4 年恶化。恶化集中在 2018（−0.01pp / B −1.83pp）、2023（B −2.85pp）、2024（−1.93pp）。
一个稳健的过滤规则不该在景气切换的年份反向拖累。
</div>
''')}

{card("⑧ 口径与方法边界（逐条都可复核）", f'''
<ol class="small" style="margin-top:0">
<li><b>覆盖判定标准</b>：只认个股级研报（独立评级或目标价）。仅被行业周报、策略清单、涨幅榜列名的算零覆盖。
已验证样例：华电能源 2023 年至今检索到的全部是省域双周报涨幅榜与「建议关注」清单，零篇个股深度，与评级库的「无评级」判定一致。</li>
<li><b>标签来源</b>：<code>neodata</code> 机构评级，按「覆盖月份数 ≥3 且累计机构数 ≥10」划分厚/薄，0 家为零覆盖。
334 只候选 <b>100% 覆盖</b>：厚 143 / 薄 147 / 零 44（13.2%）。</li>
<li><b>标签的时间错位（核心局限）</b>：评级库只回溯近 4~6 个月，无法取得 2017 年当期状态。
本报告用的是「当前覆盖」这一慢变量代理，测的是「这家公司是不是长期被人研究」，<b>不是</b>入选当时的覆盖。</li>
<li><b>情景A 的权重</b>：剔除后按剩余持仓原比例等比归一。代价是 25/35 期会突破 8% 单只上限（最高 10.38%），
这是「重新分配权重」的自然结果，若严格要求不超限需另做限幅迭代。</li>
<li><b>情景B 不递补</b>：候选构建时剔除零覆盖，候选从 28 只降到 28−k 只，三道筛与反比加权全部重跑。
不递补是因为递补股散落在全股池 1071 只里，无法逐只取得覆盖状态；宁可口径保守，也不拿未知标签凑数。
情景B 候选里仅 1.6% 缺标签，且缺标签者被保守地当作「有覆盖」，不会虚增效果。</li>
<li><b>成本与可交易性</b>：与原回测同一套 —— 换手按单边 10bp、调仓日停牌/无价剔除并归一、2017-01-03 起统计。</li>
<li><b>数据源的幸存者偏差仍在</b>：行情库 2334 只股票末个交易日全为 2026 年，一只退市股都没有。
两组的收益都被高估，且零覆盖组（小盘居多）真实退市率更高 —— 这也意味着<b>上述偏差只会更大</b>。</li>
</ol>
''')}

{card("⑨ 如果真想做这件事，怎么做才算数", f'''
<div class="ok" style="margin:0 0 12px">
<b>可行的路：把覆盖判定搬到当期。</b>第七章《市场情绪展望》已经在做这件事 —— 每次调仓后对该期
19 只持仓逐只检索<b>当期</b>研报（<code>wenda_report_query</code>），判定「有没有个股级研报」。
那是时点正确的信息，没有前视偏差。
</div>
<ul class="small">
<li>研报库最早只到 2023 年，所以时点正确的验证最多能回溯 2023 年至今（约 11 期），样本量比本报告小得多，但结论才可用。</li>
<li>落库方式：把每期「调仓日 → 该期候选 28 只的当期覆盖状态」存成一张表，逐期累积；攒到 8~12 期再做统计。</li>
<li>在此之前，更务实的用法是把「零覆盖」当<b>风险提示</b>而不是<b>筛选条件</b> ——
不因为它而卖出，但知道它没有卖方在跟踪、流动性可能更差、坏消息缺少缓冲。</li>
</ul>
<div class="small" style="margin-top:10px">
数值结果本身（+2.2pp 年化）在方向上是可信的：覆盖度确实与持有质量正相关，这与上一次的持仓级统计
（厚覆盖持有期超额 +8.5%、零覆盖 −1.7%）方向一致。但<b>幅度</b>不能采信，原因如上。
</div>
''')}

<div class="small" style="margin-top:20px;padding-top:14px;border-top:1px solid var(--bd)">
数据与脚本：<code>scripts/finchain/scenario_cov.py</code>（三情景回测）、
<code>scenario_cov_check.py</code>（蒙卡与证伪检验）、
<code>data/coverage_label_all.csv</code>（334 只标签）、
<code>data/scenario_cov_nav_daily.csv</code>（逐日净值）。
本报告仅供研究，不构成投资建议。
</div>
</div></body></html>"""

out = os.path.join(str(BASE), "output", "scenario_cov_report.html")
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, "w", encoding="utf-8").write(html)
print(f"OK {out}  {len(html.encode())/1024:.0f} KB")
print(f"   蒙特卡洛分位 {mc_pct*100:.1f}% · 随机中位 {q50*100:+.1f}% · 95% 分位 {q95*100:+.1f}%")
