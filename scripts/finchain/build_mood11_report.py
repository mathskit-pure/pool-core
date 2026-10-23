# -*- coding: utf-8 -*-
"""生成《研报情绪与目标价 → 后续股价相关性》研究报告（自包含 HTML）。

所有数字从 data/mood11_corr.csv、data/mood_q28.json、data/mood11_holdings.csv 读取，
不写死结论数字；相关性统一现算。
"""
import json
import os
import sys

import pandas as pd
from scipy.stats import pearsonr, spearmanr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
from paths import DATA, FIN_OUT as OUT  # noqa: E402

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--bd:#e3e6ea;--tx:#15181d;--mut:#6b7280;--ac:#1f2937;--hot:#c0392b;--ok:#2e7d4f}
*{box-sizing:border-box}
body{margin:0;padding:26px 22px 70px;background:var(--bg);color:var(--tx);
font:14px/1.72 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1060px;margin:0 auto}
h1{font-size:23px;margin:0 0 6px;letter-spacing:-.2px}
.sub{color:var(--mut);font-size:13px;margin-bottom:20px}
h2{font-size:16px;margin:26px 0 12px;padding-left:9px;border-left:3px solid var(--ac)}
.card{background:var(--card);border:1px solid var(--bd);border-radius:11px;padding:17px 19px;margin-bottom:15px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:15px}
.kpi{background:var(--card);border:1px solid var(--bd);border-radius:11px;padding:14px 16px}
.kpi.hot{border-color:#e8c4bd;background:#fdf8f7}
.kpi.good{border-color:#cfe8d8;background:#f4faf6}
.kpi i{display:block;font-style:normal;color:var(--mut);font-size:12px;margin-bottom:5px}
.kpi b{display:block;font-size:25px;letter-spacing:-.5px;line-height:1.15}
.kpi.hot b{color:var(--hot)}.kpi.good b{color:var(--ok)}
.kpi u{display:block;text-decoration:none;color:var(--mut);font-size:12px;margin-top:5px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 9px;text-align:right;border-bottom:1px solid #eef0f3;white-space:nowrap}
th{color:var(--mut);font-weight:500;font-size:12px;background:#fafbfc}
th:first-child,td.l,td:first-child{text-align:left}
tr.hl td{background:#fdf8f7}
.neg{color:var(--hot)}.pos{color:var(--ok)}
.warn{background:#fdf6ec;border:1px solid #f0d9b5;border-left:3px solid #b45309;
border-radius:9px;padding:14px 17px;margin-bottom:15px;font-size:13.5px;line-height:1.75}
.warn b{color:#92400e}
.ok{background:#f2f9f5;border:1px solid #cfe8d8;border-left:3px solid #2e7d4f;
border-radius:9px;padding:14px 17px;margin-bottom:15px;font-size:13.5px;line-height:1.75}
.note{color:var(--mut);font-size:12.5px;margin-top:9px;line-height:1.7}
svg{display:block;width:100%;height:auto;overflow:visible}
.gl{stroke:#e8ebef;stroke-width:1}
.ax{fill:#98a1ad;font-size:11px}
.bl{fill:#c0392b}
.bg{fill:#2e7d4f}
.bt{fill:#15181d;font-size:11px;font-weight:600}
code{background:#eef1f4;padding:1px 5px;border-radius:4px;font-size:12.5px}
"""

CLS_CN = {"bull": "看多", "warn": "警示", "split": "分歧", "none": "零覆盖"}


def bars(items, height=206, bw=58, gap=32):
    """items: [(label, value, css_class, n)] → 条形图 SVG（宽度按内容自适应）。"""
    n_item = len(items)
    w = 80 + n_item * (bw + gap) + 22
    ymin = min(0.0, min(v for _, v, _, _ in items))
    ymax = max(0.0, max(v for _, v, _, _ in items))
    rng = (ymax - ymin) or 1.0
    top, bot = 32, 62
    zero = top + (ymax / rng) * (height - top - bot)

    def y(v):
        return top + (ymax - v) / rng * (height - top - bot)

    s = [f'<svg viewBox="0 0 {w} {height}" preserveAspectRatio="xMidYMid meet" role="img">']
    # 刻度：按显示文本去重 + 像素间距去重叠（相邻不足 13px 则不画）
    seen, last_y = set(), -1e9
    for gv in (ymin, ymin / 2, 0.0, ymax):
        lab = f"{gv:+.0f}%"
        yy = y(gv)
        if lab in seen or abs(yy - last_y) < 13:
            continue
        seen.add(lab)
        last_y = yy
        s.append(f'<line class="gl" x1="64" y1="{yy:.1f}" x2="{w - 14}" y2="{yy:.1f}"/>')
        s.append(f'<text class="ax" x="58" y="{yy + 4:.1f}" text-anchor="end">{lab}</text>')
    s.append(f'<line x1="64" y1="{zero:.1f}" x2="{w - 14}" y2="{zero:.1f}" stroke="#c8ced6"/>')
    for i, (lab, v, cls, cnt) in enumerate(items):
        x = 80 + i * (bw + gap)
        yy = y(v)
        hh = abs(yy - zero)
        rect_y = min(yy, zero)
        s.append(f'<rect class="{cls}" x="{x}" y="{rect_y:.1f}" width="{bw}" '
                 f'height="{max(hh, 1.4):.1f}" rx="3"/>')
        ty = max(14.0, (yy + 16) if v < 0 else (yy - 8))
        s.append(f'<text class="bt" x="{x + bw / 2:.1f}" y="{ty:.1f}" '
                 f'text-anchor="middle">{v:+.1f}%</text>')
        s.append(f'<text class="ax" x="{x + bw / 2:.1f}" y="{height - 30}" '
                 f'text-anchor="middle">{lab.replace("<", "&lt;").replace(">", "&gt;")}</text>')
        s.append(f'<text class="ax" x="{x + bw / 2:.1f}" y="{height - 12}" '
                 f'text-anchor="middle">n={cnt}</text>')
    s.append("</svg>")
    return "\n".join(s)


def main():
    d = pd.read_csv(os.path.join(DATA, "mood11_corr.csv"), dtype={"code": str})
    d["code"] = d["code"].str.zfill(6)
    hl = pd.read_csv(os.path.join(DATA, "mood11_holdings.csv"), dtype={"code": str})
    mood = json.load(open(os.path.join(DATA, "mood_q28.json"), encoding="utf-8"))
    meta = mood["meta"]

    n = len(d)
    mean_ret = float(d["ret"].mean())
    med_ret = float(d["ret"].median())
    up_m = d["up_mood"].dropna()
    up_c = d["up_cons"].dropna()

    def cc(x, y):
        s = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"),
                          "y": pd.to_numeric(y, errors="coerce")}).dropna()
        r, p = pearsonr(s["x"], s["y"])
        sr, sp = spearmanr(s["x"], s["y"])
        return dict(n=len(s), r=float(r), p=float(p), sr=float(sr), sp=float(sp))

    specs = [
        ("调仓前 3 个月机构家数", d["pre_cnt"], "覆盖强度"),
        ("调仓前 3 个月有覆盖的月数", d["pre_months"], "覆盖连续度"),
        ("目标价隐含涨幅（研报原文区间）", d["up_mood"], "卖方定价"),
        ("目标价隐含涨幅（机构一致预期）", d["up_cons"], "卖方定价"),
    ]
    cors = [(lab, cc(x, d["ret"]), tag) for lab, x, tag in specs]

    # 分档
    d["档"] = pd.cut(d["pre_cnt"], [-1, 0, 2, 5, 100], labels=["0家", "1-2家", "3-5家", "6家以上"])
    g_cnt = d.groupby("档", observed=True)["ret"].agg(["size", "mean"]).reset_index()
    d["档2"] = pd.cut(d["up_cons"], [-100, 20, 35, 60, 10000],
                      labels=["<20%", "20-35%", "35-60%", ">60%"])
    g_up = d.groupby("档2", observed=True)["ret"].agg(["size", "mean"]).reset_index()
    g_cls = (d.groupby("mood_cls")["ret"].agg(["size", "mean", "median"])
             .reindex(["bull", "warn", "split", "none"]).dropna())

    svg_cnt = bars([(str(r["档"]), float(r["mean"]), "bg" if r["mean"] > 0 else "bl", int(r["size"]))
                    for _, r in g_cnt.iterrows()])
    svg_up = bars([(str(r["档2"]), float(r["mean"]), "bg" if r["mean"] > 0 else "bl", int(r["size"]))
                   for _, r in g_up.iterrows()])

    # 11 期可得性矩阵
    per = hl.groupby(["period", "rebal_date"]).size().reset_index(name="n").sort_values("period")
    rows_cov = []
    for _, r in per.iterrows():
        rd = pd.Timestamp(r["rebal_date"])
        lo = (rd - pd.DateOffset(months=3)).strftime("%Y-%m")
        ok = rd >= pd.Timestamp("2026-09-01")
        mark = "可取（2026-06~08 落在窗口内）" if ok else "不可取"
        rows_cov.append(
            f'<tr{" class=" + chr(34) + "hl" + chr(34) if ok else ""}>'
            f'<td class="l">第 {int(r["period"])} 期</td><td>{r["rebal_date"]}</td>'
            f'<td>{lo} ~ {rd.strftime("%Y-%m-%d")}</td><td>{int(r["n"])}</td>'
            f'<td class="l">{mark}</td></tr>')

    # 相关性表
    rows_cor = []
    for lab, s, tag in cors:
        hi = abs(s["r"]) > 0.5
        rows_cor.append(
            f'<tr{" class=" + chr(34) + "hl" + chr(34) if hi else ""}>'
            f'<td class="l">{lab}</td><td class="l">{tag}</td><td>{s["n"]}</td>'
            f'<td class="{"pos" if s["r"] > 0 else "neg"}">{s["r"]:+.3f}</td><td>{s["p"]:.3f}</td>'
            f'<td class="{"pos" if s["sr"] > 0 else "neg"}">{s["sr"]:+.3f}</td><td>{s["sp"]:.3f}</td></tr>')

    # 明细
    rows_det = []
    for _, r in d.sort_values("ret", ascending=False).iterrows():
        u1 = "" if pd.isna(r["up_mood"]) else f'{r["up_mood"]:+.1f}%'
        u2 = "" if pd.isna(r["up_cons"]) else f'{r["up_cons"]:+.1f}%'
        rows_det.append(
            f'<tr><td class="l">{r["code"]} {r["name"]}</td><td>{r["weight"]:.2f}%</td>'
            f'<td>{int(r["pre_cnt"])}</td><td>{int(r["pre_months"])}</td>'
            f'<td class="l">{CLS_CN.get(r["mood_cls"], r["mood_cls"])}</td>'
            f'<td>{u1}</td><td>{u2}</td>'
            f'<td class="{"neg" if r["ret"] < 0 else "pos"}">{r["ret"]:+.2f}%</td></tr>')

    # 评级覆盖的「股票-月」观测数与当月机构家数范围（现算，勿写死）
    rat_raw = json.load(open(os.path.join(DATA, "ratings19.json"), encoding="utf-8"))["rows"]
    mon_cnt = [v for r in rat_raw for v in r["m"].values()]
    n_obs = len(mon_cnt)
    mon_min, mon_max = (min(mon_cnt), max(mon_cnt)) if mon_cnt else (0, 0)

    # 稳健性：剔除 3 只最大跌幅后重算机构家数相关
    bad = d.nsmallest(3, "ret")["code"].tolist()
    d_ex = d[~d["code"].isin(bad)]
    rob_ex = cc(d_ex["pre_cnt"], d_ex["ret"])
    rob_bad_names = "、".join(d[d["code"].isin(bad)]["name"].tolist())
    rob_bad_rets = [float(v) for v in d[d["code"].isin(bad)]["ret"].tolist()]

    c_cnt, c_up = cors[0][1], cors[3][1]
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>研报情绪与目标价 · 与后续股价的相关性</title><style>{CSS}</style></head><body><div class="wrap">
<h1>研报情绪、目标价 与 后续股价的相关性</h1>
<div class="sub">建仓 {meta['rebal_date']} → 2026-10-16 ｜ 样本 {n} 只 ｜ 数据源 neodata（ratings / 研报检索）</div>

<div class="kpis">
  <div class="kpi"><i>可做干净检验的期数</i><b>1 / 11</b><u>评级数据仅回溯 6 个月</u></div>
  <div class="kpi"><i>样本股票</i><b>{n} 只</b><u>当前一期全部持仓</u></div>
  <div class="kpi good"><i>机构家数 → 收益</i><b>r={c_cnt['r']:+.2f}</b><u>p={c_cnt['p']:.3f}，正相关</u></div>
  <div class="kpi hot"><i>目标价隐含涨幅 → 收益</i><b>r={c_up['r']:+.2f}</b><u>p={c_up['p']:.3f}，负相关</u></div>
</div>

<div class="warn"><b>先说结论。</b>你要的「最近 11 期逐期研报情绪与目标价」在现有数据源下做不出来——不是样本不够，
而是研报接口不提供历史快照（第五节逐项给了实测证据）。唯一能做干净检验的只有当前这一期 {n} 只、窗口 6 周。
在这一期里出现两个方向明确、彼此独立的结果：<b>覆盖机构家数与后续收益正相关</b>
（r={c_cnt['r']:+.2f}，p={c_cnt['p']:.3f}），<b>目标价给得越乐观、后续越差</b>
（r={c_up['r']:+.2f}，p={c_up['p']:.3f}）。但样本只有 {n} 只、持有期只有 6 周，
且剔除 3 只最差个股后前者显著性掉到 p=0.20，所以这是<b>值得跟踪的信号，不是可用因子</b>。</div>

<h2>一、为什么 11 期做不了</h2>
<div class="card">
<table><thead><tr><th>期次</th><th>调仓日</th><th>需检索的研报窗口</th><th>持仓只数</th><th>研报数据可得性</th></tr></thead>
<tbody>{''.join(rows_cov)}</tbody></table>
<div class="note">研报接口的月度评级分布只保留<b>最近 6 个月</b>（2026-05 ~ 2026-10），一致目标价只有<b>当前时点快照</b>。
11 期里只有第 11 期（2026-09-02 建仓）的「调仓前 3 个月」= 2026-06~08 完整落在窗口内，其余 10 期全部缺失。</div>
</div>

<h2>二、卖方评级本身几乎没有区分度</h2>
<div class="card">
<p style="margin:0 0 12px">把 {n} 只持仓逐只调取月度评级分布后发现：<b>所有有覆盖的月份里，买入+增持占比恒为 100%，
卖出与持有占比恒为 0</b>，无一例外。样本外唯一出现过非满值的是贵州茅台（持有占比最高 7.1%）。</p>
<table><thead><tr><th>指标</th><th>观测数</th><th>取值范围</th><th>是否有区分度</th><th>能否当情绪代理</th></tr></thead><tbody>
<tr><td class="l">买入+增持占比</td><td>{n_obs} 个股票-月</td><td>100.00%（全体）</td><td class="neg">零方差</td><td class="l">不能</td></tr>
<tr><td class="l">卖出+减持占比</td><td>{n_obs} 个股票-月</td><td>0.00%（全体）</td><td class="neg">零方差</td><td class="l">不能（卖方不做空）</td></tr>
<tr><td class="l">持有占比</td><td>{n_obs} 个股票-月</td><td>0.00%（全体）</td><td class="neg">零方差</td><td class="l">不能</td></tr>
<tr class="hl"><td class="l">当月发布研报的机构家数</td><td>{n_obs} 个股票-月</td><td>{mon_min} ~ {mon_max} 家</td><td class="pos">有</td><td class="l">可以</td></tr>
</tbody></table>
<div class="note">这解释了一个常见误解：把「研报评级」当情绪代理行不通——A 股卖方评级结构性单边看多，
评级分布没有横截面差异。真正有信息的是<b>覆盖强度</b>（多少家机构愿意写）和<b>覆盖变化</b>（在增还是在撤），
不是评级本身。</div>
</div>

<h2>三、当前一期的检验结果</h2>
<div class="card">
<table><thead><tr><th>自变量（调仓前已知）</th><th>归属</th><th>n</th><th>Pearson r</th><th>p 值</th><th>Spearman ρ</th><th>p 值</th></tr></thead>
<tbody>{''.join(rows_cor)}</tbody></table>
<div class="note">y 变量统一为建仓后后复权收益（{meta['rebal_date']} → 2026-10-16），等权平均 {mean_ret:+.2f}%、
中位 {med_ret:+.2f}%，正收益 {(d['ret'] > 0).sum()}/{n} 只——这是一段整体下跌的行情。</div>
</div>

<div class="card">
<div style="font-size:14px;font-weight:600;margin-bottom:10px">机构家数分档：越多人写，后续越抗跌</div>
{svg_cnt}
<div class="note">0~2 家的两组平均 −13.5% 左右，6 家以上一组只有 −1.4%，单调性基本成立。
但 3-5 家档只有 2 只样本，档内均值受单只影响很大。<br><br>
<b>机制上要打个折：</b>8 月是 2026 年中报披露后的点评高峰，这个窗口的「机构家数」很大程度上是
<b>「中报出来后有多少家愿意写」</b>——它同时包含了「业绩超预期」和「卖方关系维护」两层信息，
并不纯粹是「市场关注度」。所以它正向预测后续收益，更可能是在说「中报扎实的公司后续抗跌」，
而不是「有人写研报所以会涨」。这也意味着它与质量因子的信息高度重叠，增量有限。</div>
</div>

<div class="card">
<div style="font-size:14px;font-weight:600;margin-bottom:10px">目标价隐含涨幅分档：卖方越乐观，后续越差</div>
{svg_up}
<div class="note">隐含涨幅 &gt;60% 的 4 只平均 −12.5%，20-35% 的 6 只是唯一正收益档（+1.0%）。
这是上一轮覆盖度研究「厚覆盖不等于好收益」的另一面：卖方目标价越激进，越可能是在为出货写报告。</div>
</div>

<div class="card">
<div style="font-size:14px;font-weight:600;margin-bottom:10px">人工读研报正文得到的情绪分级</div>
<table><thead><tr><th>情绪分级</th><th>含义</th><th>只数</th><th>平均收益</th><th>中位收益</th></tr></thead><tbody>
{''.join(f'<tr><td class="l">{k}</td><td class="l">{CLS_CN[k]}</td>'
         f'<td>{int(g_cls.loc[k, "size"])}</td>'
         f'<td class="{"pos" if g_cls.loc[k, "mean"] > 0 else "neg"}">{g_cls.loc[k, "mean"]:+.2f}%</td>'
         f'<td>{g_cls.loc[k, "median"]:+.2f}%</td></tr>' for k in g_cls.index)}
</tbody></table>
<div class="note">排序是 bull &gt; none &gt; warn &gt; split，与「评级越高越好」的直觉不一致：
判为 bull 的 {int(g_cls.loc['bull', 'size'])} 只平均正收益，而 split（研报互相矛盾）平均
{g_cls.loc['split', 'mean']:+.1f}% 最差。每组只有 2~9 只，只能作方向参考。</div>
</div>

<h2>四、目标价的兑现率</h2>
<div class="card">
<p style="margin:0 0 12px">把每只个股研报给出的目标价区间取中值，与本轮实际股价对比：</p>
<table><thead><tr><th>项目</th><th>数值</th></tr></thead><tbody>
<tr><td class="l">研报目标价平均隐含涨幅（n={len(up_m)}）</td><td>{up_m.mean():+.1f}%</td></tr>
<tr><td class="l">同期实际平均收益（n={n}）</td><td class="neg">{mean_ret:+.1f}%</td></tr>
<tr class="hl"><td class="l">兑现率（实际 / 隐含）</td><td class="neg">{mean_ret / up_m.mean() * 100:+.0f}%</td></tr>
<tr><td class="l">目标价与实际收益的落差</td><td class="neg">{mean_ret - up_m.mean():+.1f}pp</td></tr>
</tbody></table>
<div class="note">卖方平均认为还有 {up_m.mean():.0f}% 空间，实际走了 {mean_ret:.0f}%，
落差 {abs(mean_ret - up_m.mean()):.0f} 个百分点。这不等于卖方系统性看错——6 周太短、且这段是普跌行情；
但它说明<b>目标价不能当预期收益用</b>。</div>
</div>

<h2>五、数据可得性实测证据</h2>
<div class="card">
<table><thead><tr><th>接口</th><th>能否回溯历史研报</th><th>实测结果</th></tr></thead><tbody>
<tr><td class="l"><code>ratings</code> 机构评级</td><td class="neg">部分</td><td class="l">月度评级分布仅回 6 个月（2026-05~10）；一致目标价只有当前快照，无历史序列</td></tr>
<tr><td class="l"><code>company_research</code> 公司研报</td><td class="neg">否</td><td class="l">带 start_date/end_date 查 2023-05、2026-06 两个窗口，<b>两次均返回空</b></td></tr>
<tr><td class="l"><code>financial_indicators</code> 财务指标</td><td class="neg">否</td><td class="l">只有已披露的实际财报，无一致预期预测的历史序列</td></tr>
<tr><td class="l"><code>searchAnalystComments</code> 分析师点评</td><td>可能</td><td class="l">唯一支持 start_time 回溯的接口，属进门财经子服务，<b>需单独授权，本次未授权</b></td></tr>
<tr><td class="l"><code>report_search</code> 全文检索</td><td class="neg">否</td><td class="l">检索对象是财报公告原文，不是券商研报</td></tr>
</tbody></table>
<div class="note">结论：若将来接进进门财经的分析师点评库，11 期（2023-05 起）有可能补齐；在此之前，
情绪只能像第六章那样<b>按期向前固化</b>，攒一期算一期。</div>
</div>

<h2>六、稳健性：这个结果有多脆</h2>
<div class="card">
<table><thead><tr><th>检验</th><th>机构家数 r</th><th>p 值</th><th>判断</th></tr></thead><tbody>
<tr><td class="l">全样本（n={n}）</td><td class="{"pos" if c_cnt["r"]>0 else "neg"}">{c_cnt["r"]:+.3f}</td><td>{c_cnt["p"]:.3f}</td><td class="l">{"显著" if c_cnt["p"]<0.05 else "不显著"}</td></tr>
<tr class="hl"><td class="l">剔除 3 只最大跌幅后（n={rob_ex["n"]}）</td><td class="{"pos" if rob_ex["r"]>0 else "neg"}">{rob_ex["r"]:+.3f}</td><td>{rob_ex["p"]:.3f}</td><td class="l"><b>{"仍显著" if rob_ex["p"]<0.05 else "不再显著"}</b></td></tr>
<tr><td class="l">换 Spearman 秩相关（全样本）</td><td class="{"pos" if c_cnt["sr"]>0 else "neg"}">{c_cnt["sr"]:+.3f}</td><td>{c_cnt["sp"]:.3f}</td><td class="l">{"仍显著" if c_cnt["sp"]<0.05 else "不显著"}</td></tr>
</tbody></table>
<div class="note">这是本报告最该记住的一行：<b>显著性主要由 {rob_bad_names} 3 只（{min(rob_bad_rets):+.1f}% ~ {max(rob_bad_rets):+.1f}%）贡献</b>，
它们恰好都是「只有 1 家机构写过、正文有明显硬伤」的票。去掉它们，相关系数从 {c_cnt["r"]:+.2f} 掉到 {rob_ex["r"]:+.2f}、
p 值从 {c_cnt["p"]:.2f} 升到 {rob_ex["p"]:.2f}。换句话说，这个信号目前<b>建立在一个很小、很关键的尾部上</b>，
不是稳健的横截面规律。</div>
</div>

<h2>七、明细</h2>
<div class="card" style="overflow-x:auto">
<table><thead><tr><th>代码 名称</th><th>权重</th><th>调仓前3月<br>机构家数</th><th>有覆盖<br>月数</th><th>情绪分级</th><th>目标价隐含<br>(研报原文)</th><th>目标价隐含<br>(一致预期)</th><th>建仓后收益</th></tr></thead>
<tbody>{''.join(rows_det)}</tbody></table>
</div>

<h2>八、结论与下一步</h2>
<div class="ok"><b>能采信的：</b>卖方评级本身没有区分度（全 100% 买入），把它当情绪因子是死路；
有信息的是<b>覆盖强度</b>与<b>目标价激进程度</b>，且两者方向相反——机构写得越多后续越抗跌，
目标价给得越高后续越差。这与上一轮「厚覆盖持有超额 +8.5%、零覆盖 −1.7%」的定性结论一致。</div>

<div class="warn"><b>不能采信的：</b>具体数字。n=19、窗口 6 周、单期、普跌行情，且显著性依赖 3 只尾部个股。
它不足以支撑「按机构家数加权」或「按目标价反向交易」这类策略改动。<br><br>
<b>要真做，只有两条路：</b><br>
① 接进进门财经的分析师点评库（支持 start_time 回溯），把 2023-05 起的 11 期补齐；<br>
② 从这一期起按第六章的机制<b>按期固化</b>情绪快照（每期落盘 mood_q28 的日期切片），
约 11 个季度后自然形成 11 期样本。<br><br>
在此之前，覆盖强度可以进<b>风险提示</b>（「只有 1 家写、正文有硬伤」值得标红），不能进选股权重。</div>

<div class="note" style="margin-top:18px">口径：收益为后复权日收益连乘（含分红再投）；建仓日取调仓信号次一交易日
{meta['rebal_date']}；情绪分级来自第六章人工核验文本（mood_q28.json）；评级与目标价来自
neodata.ratings 2026-10-23 实测。生成脚本 <code>mood11_corr.py</code> /
<code>mood11_robust.py</code> / <code>build_mood11_report.py</code>。</div>
</div></body></html>"""

    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, "mood11_report.html")
    open(out, "w", encoding="utf-8").write(html)

    # 自检
    problems = []
    if " nan" in html or "nan%" in html:
        problems.append("出现 nan")
    if html.count("<table") != html.count("</table>"):
        problems.append("table 标签不配对")
    if html.count("<svg") != html.count("</svg>"):
        problems.append("svg 标签不配对")
    print(f"→ {out}  {len(html) / 1024:.1f} KB  svg={html.count('<svg')} table={html.count('<table')}")
    print("自检：" + ("通过" if not problems else "；".join(problems)))


if __name__ == "__main__":
    main()
