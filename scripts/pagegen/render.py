# -*- coding: utf-8 -*-
"""把 ``page_data.json`` 渲染成「舞弊调整质量因子 · 季度动态股池」整页 HTML。

设计约束
--------
1. **单一输入**：只读 ``page_data.json``，不碰任何 CSV / 中间产物。这样同一份渲染器
   既能在本机跑，也能在云端只拿到数据包时独立跑。
2. **不写死任何会随季度变化的东西**：回测起止月、期数、κ 敏感性表里的具体数值，
   全部从数据包现算。否则下一季刷新后，标题写着旧日期、正文引用旧夏普，会与表格自相矛盾。
3. 结构性文案（重构说明、模型口径、结论措辞）保持原样 —— 它们是叙事，不是数据。

用法::

    python scripts/pagegen/render.py --data data/page_data.json --out /tmp/pool.html
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STRAT = ["CSFM(N=20, κ=1.5)", "TSFM(N=30, κ=1.0)", "质量Top28 v1", "质量Top28 v2"]
BENCH = ["沪深300", "中证500", "创业板50"]
COL = {"CSFM(N=20, κ=1.5)": "#c0392b", "TSFM(N=30, κ=1.0)": "#2c6f9e",
       "质量Top28 v1": "#0f9d58", "质量Top28 v2": "#7b3fa0",
       "沪深300": "#9ca3af", "中证500": "#e08a1e", "创业板50": "#0ea5e9"}
SHORT = {"CSFM(N=20, κ=1.5)": "CSFM", "TSFM(N=30, κ=1.0)": "TSFM",
         "质量Top28 v1": "质量 v1", "质量Top28 v2": "质量 v2",
         "沪深300": "沪深300", "中证500": "中证500", "创业板50": "创业板50"}

D: dict = {}


# ---------------------------------------------------------------- 小工具
def pct(x, d=2):
    return "—" if x is None else f"{x*100:.{d}f}%"


def num(x, d=2):
    return "—" if x is None else f"{x:.{d}f}"


def get(k, seg):
    for r in D.get("summary", []):
        if r["k"] == k and r["seg"] == seg:
            return r
    return {}


def _dates():
    return (D.get("curve") or {}).get("dates") or []


def span():
    """回测起止，形如 ``2015-01 → 2026-10``。

    起点**不能**直接取 curve.dates[0]：曲线首点的值已经是 ``1 + 首期收益``，
    真实起点是它的前一个月（否则会把 2015-01 写成 2015-02）。
    故优先读数据包 meta；缺失时才用首点月份兜底。
    """
    m = D.get("meta") or {}
    if m.get("start") and m.get("end"):
        return f"{m['start']} → {m['end']}"
    d = _dates()
    if d:
        return f"{d[0][:7]} → {d[-1][:7]}"
    return "—"


def months():
    """月度净值序列长度（CSFM/TSFM 的期数）。优先取绩效表里的真实期数。"""
    r = get("CSFM(N=20, κ=1.5)", "全期")
    if r.get("n"):
        return int(r["n"])
    m = D.get("meta") or {}
    if m.get("n_months"):
        return int(m["n_months"])
    return len(_dates())


def quarters():
    """质量Top28 的期数。必须取绩效表真实期数 —— 按月份数/3 估会少一期。"""
    r = get("质量Top28 v2", "全期")
    if r.get("n"):
        return int(r["n"])
    m = D.get("meta") or {}
    if m.get("n_quarters"):
        return int(m["n_quarters"])
    n = months()
    return int(round(n / 3.0)) if n else 0


def kappa_cell(nm, n, k):
    for x in D.get("kappa", []):
        if x["s"] == nm and x["n"] == n and abs(x["k"] - k) < 1e-9:
            return x
    return None


# ---------------------------------------------------------------- 样式
CSS = """
:root{--bg:#f7f8fa;--card:#fff;--bd:#e5e7eb;--tx:#1f2937;--mut:#6b7280;--ac:#c0392b;--ac2:#2c6f9e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
 font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Inter,sans-serif;line-height:1.6}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:26px;margin:0 0 6px} h2{font-size:19px;margin:34px 0 12px}
h3{font-size:16px;margin:0}
.sub{color:var(--mut);font-size:14px;margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:16px 18px;margin-bottom:14px}
.card-h{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:8px}
.pill{display:inline-block;background:#eef2ff;color:#3730a3;border-radius:999px;
 padding:2px 10px;font-size:12px;margin-left:8px;font-weight:400}
.muted{color:var(--mut);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-top:10px}
.ind{border:1px solid var(--bd);border-radius:9px;padding:10px 12px;background:#fcfcfd}
.ind-h{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}
.ind-name{font-weight:600;font-size:14px}
table{width:100%;border-collapse:collapse;font-size:13px}
.mini th,.mini td{padding:4px 6px;text-align:left;border-bottom:1px solid #f1f2f4}
.tbl th,.tbl td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--bd)}
.tbl th{background:#f3f4f6;font-weight:600}
.num{text-align:right;font-variant-numeric:tabular-nums}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:14px}
.kpi{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 14px}
.kpi b{display:block;font-size:21px;margin-top:2px}
.kpi span{color:var(--mut);font-size:12px}
.note{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:12px 14px;font-size:13px}
.warn{background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:12px 14px;font-size:13px}
code{background:#f3f4f6;padding:1px 6px;border-radius:4px;font-size:12px}
ol,ul{padding-left:22px;margin:8px 0}
li{margin:4px 0;font-size:14px}
details>summary{cursor:pointer;color:var(--ac2);font-size:13px;outline:none}
.blk-fold{border:1px solid var(--bd);border-radius:10px;background:#fcfcfd;margin-bottom:10px}
.blk-fold-s{display:flex;align-items:center;gap:10px;padding:10px 14px;list-style:none}
.blk-fold-t{font-weight:600;color:var(--tx);font-size:14px}
.blk-fold-n{color:var(--mut);font-size:12px}
.blk-fold-a{margin-left:auto;color:var(--ac2);font-size:12px}
.blk-fold-b{padding:0 14px 12px}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:var(--mut)}
.rk{color:var(--mut);width:22px}
.chart{width:100%;height:auto;margin-top:8px}
.btns{display:flex;gap:6px;margin:6px 0}
.btns button{font:inherit;font-size:12px;padding:3px 12px;border:1px solid var(--bd);background:#fff;
 color:#374151;border-radius:999px;cursor:pointer}
.btns button.on{background:var(--ac2);color:#fff;border-color:var(--ac2)}
.leg{display:flex;flex-wrap:wrap;gap:14px;margin:6px 0 0;font-size:12px;color:#374151}
.leg i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:5px;border-radius:2px}
.tag{display:inline-block;border-radius:4px;padding:1px 7px;font-size:12px;line-height:1.5}
.tag-new{background:#fdecea;color:#c0392b;border:1px solid #f5c6c2;font-weight:600}
.tag-keep{background:#f3f4f6;color:#6b7280;border:1px solid #e5e7eb}
.tag-out{background:#e8f0fb;color:#1d5fa8;border:1px solid #c6d9f2;font-weight:600}
tr.r-new td{background:#fdf3f2}
tr.r-out td{background:#f2f6fd}
.up{color:#c0392b;font-weight:600}.dn{color:#128a53;font-weight:600}
@media(max-width:640px){.wrap{padding:18px 12px 40px}}
"""


# ---------------------------------------------------------------- 各区块
def kpi_row():
    cur = D["pools"][-1]
    cs, q2 = get("CSFM(N=20, κ=1.5)", "全期"), get("质量Top28 v2", "全期")
    return f"""<div class="kpis">
<div class="kpi"><span>最新一期</span><b>{cur['label']}</b><span class="muted">信息可得 {cur['asof']}</span></div>
<div class="kpi"><span>股池规模</span><b>{cur['n']} 只</b><span class="muted">{cur['nind']} 个申万三级行业</span></div>
<div class="kpi"><span>CSFM 年化 / 夏普</span><b>{pct(cs.get('ann'))}</b><span class="muted">夏普 {num(cs.get('sh'))}</span></div>
<div class="kpi"><span>质量Top28 v2 年化 / 夏普</span><b>{pct(q2.get('ann'))}</b><span class="muted">夏普 {num(q2.get('sh'))}</span></div>
<div class="kpi"><span>回测区间</span><b>{span()}</b><span class="muted">{D['pools'][0]['label']} → {cur['label']} 共 {len(D['pools'])} 期</span></div>
</div>"""


def sec_intro():
    n = len(D["pools"])
    m = D.get("meta") or {}
    n_snap = m.get("n_snapshots", 38)
    n_union = m.get("n_union", 1633)
    return f"""<h2>一、本次重构：标的池改为官方中证800 历史成分</h2>
<div class="card">
<p class="muted" style="margin-top:0">此前版本的「季度股池」候选域是<b>按总市值取前 800 名</b>拟合中证800，并非指数真实成分。
本次改用 Baostock 回溯的<b>沪深300 ∪ 中证500 官方成分快照</b>（每期 800 只、按指数调样日 PIT 对齐），
在其内部重算舞弊调整质量因子（FAQ），仍按申万三级行业各取前 5 组成股池。</p>
<table class="tbl"><thead><tr><th>项目</th><th>旧版</th><th>新版</th></tr></thead><tbody>
<tr><td>候选域</td><td>全 A 按总市值降序取前 800</td><td>官方中证800 成分（沪深300 ∪ 中证500）逐期快照</td></tr>
<tr><td>与官方成分重叠</td><td>72.6% ~ 85.2%</td><td>100%（同源）</td></tr>
<tr><td>期数覆盖</td><td>2019Q1 起 23 期</td><td>{n} 期明细；回测口径向前延至 2015-01</td></tr>
<tr><td>行业中性</td><td>申万三级各取前 5</td><td>同（不足 5 只不补入）</td></tr>
<tr><td>回测样本</td><td>2019-05 起</td><td>2015-01 起（{years_text()}，含 2015 股灾与 2016 熔断）</td></tr>
</tbody></table>
<p class="muted">成分快照共 {n_snap} 期（2014-05 起至最新一期），跨期并集 {n_union:,} 只。财务数据按法定披露截止日
（Q1 4/30、中报 8/31、三季报 10/31、年报次年 4/30）做时点对齐，不使用公告日字段（该字段存在错标，曾出现 2018Q3 报告被标为 2019-10）。</p>
</div>"""


def years_text():
    d = _dates()
    if len(d) >= 2:
        y0, y1 = int(d[0][:4]), int(d[-1][:4])
        m0, m1 = int(d[0][5:7]), int(d[-1][5:7])
        y = (y1 - y0) + (m1 - m0) / 12.0
        return f"{y:.1f} 年"
    return "11.8 年"


def sec_pools():
    rows = []
    for p in reversed(D["pools"]):  # 最新在前
        s = f"""<section class="card"><div class="card-h"><h3>{p['label']}<span class="pill">信息可得 {p['asof']}</span></h3>
<span class="muted">{p['n']} 只 · {p['nind']} 个申万三级行业</span></div>
<details><summary>展开 / 收起（{p['nind']} 个行业 · {p['n']} 只）</summary><div class="grid">"""
        for ind in p["inds"]:
            s += f'<div class="ind"><div class="ind-h"><span class="ind-name">{ind["name"]}</span>' \
                 f'<span class="muted">{len(ind["items"])} 只</span></div><table class="mini"><thead><tr>' \
                 '<th>#</th><th>代码</th><th>名称</th><th>评分</th><th>市值(亿)</th></tr></thead><tbody>'
            for i, it in enumerate(ind["items"], 1):
                pre = "sh" if it["c"][0] == "6" else ("bj" if it["c"][:2] in ("43", "83", "87", "92") else "sz")
                mv = "—" if it["m"] is None else f"{it['m']:.0f}"
                s += (f'<tr><td class="rk">{i}</td><td class="mono">{pre}{it["c"]}</td><td>{it["n"]}</td>'
                      f'<td class="num">{it["s"]:.2f}</td><td class="num">{mv}</td></tr>')
            s += "</tbody></table></div>"
        s += "</div></details></section>"
        rows.append(s)
    return f"""<h2>二、季度股池（申万三级行业各取前 5，不足 5 只不补入）</h2>
<div class="card"><div class="card-h"><h3>季报明细</h3>
<span class="muted">共 {len(D['pools'])} 期 · {D['pools'][0]['label']} → {D['pools'][-1]['label']}</span></div>
<p class="muted">每期在「当期官方中证800 成分」内，取最新可得财报的 FAQ 评分，按申万三级行业降序取前 5。
评分已做行业内中性（Q_z / F_z 四支柱加权），跨行业可比但不宜直接当作绝对收益预测。</p></div>
<div>{''.join(rows)}</div>"""


def sec_bt():
    def tr(k, lab=None):
        r = get(k, "全期")
        if not r:
            return ""
        s1, s2 = get(k, "2015-2018"), get(k, "2019-2026")
        bold = ' style="font-weight:600"' if k in BENCH else ""
        return (f'<tr{bold}><td>{lab or k}</td><td class="num">{pct(r.get("cum"))}</td>'
                f'<td class="num">{pct(r.get("ann"))}</td><td class="num">{pct(r.get("vol"))}</td>'
                f'<td class="num">{pct(r.get("dd"))}</td><td class="num">{num(r.get("sh"))}</td>'
                f'<td class="num">{num(r.get("cal"))}</td>'
                f'<td class="num">{pct(s1.get("ann"))}</td><td class="num">{num(s1.get("sh"))}</td>'
                f'<td class="num">{pct(s2.get("ann"))}</td><td class="num">{num(s2.get("sh"))}</td></tr>')

    body = "".join(tr(k) for k in STRAT) + \
           '<tr><td colspan="11" class="muted" style="background:#fafafa">对比基准</td></tr>' + \
           "".join(tr(k) for k in BENCH)

    leg = "".join(f'<span><i style="background:{COL[k]}"></i>{SHORT.get(k,k)}</span>'
                  for k in STRAT + BENCH)
    return f"""<h2>三、组合回测（{span()}，标的池 = 上述动态股池）</h2>
<div class="card">
<details><summary>模型与执行口径（点击展开）</summary>
<p class="muted" style="white-space:pre-wrap;margin-top:8px"><b>候选域与调仓</b>：每个调仓日只允许持有「当期官方中证800 成分 ∪ 当期股池」内的个股；CSFM / TSFM 月度调仓，质量Top28 季度调仓。
<b>成本</b>：全部换手按单边 10bp 计收（佣金＋印花税＋冲击成本）。
<b>停牌与异常</b>：日线前向填充上限 250 日，单期个股收益按 −60% / +150% 截尾，避免复权跳变与停牌跨期造成的伪收益。
<b>财务时点</b>：按法定披露截止日可得，杜绝前视。</p>
<p class="muted" style="white-space:pre-wrap"><b>CSFM / TSFM</b>：依据 Ma, Liao &amp; Jiang (2024, JEF)《Factor momentum in the Chinese stock market》。
在池内每月计算 10 个非动量因子（规模、价值 BM、盈利 ROA、应计、现金流价格比、盈利价格比、非流动性 Amihud、换手率、低贝塔 BAB、低特质波动）的横截面 Z 分数；
每因子取最高 20% 与最低 20% 构建多空组合得到月度因子收益。CSFM 按因子 12 个月累计收益的<b>横截面中位数</b>分多空，TSFM 按其<b>自身正负号</b>分多空；
个股得分 = Σ(因子动量权重 × 个股 Z) / √10，取池内前 N 只等权，按月调仓。
<b>F 反馈强度门控</b>：以因子收益的 24 个月自相关与 12 个月趋势 R² 合成拥挤度 F，权重乘以 (1 − κ·F)，κ 越大越回避「动量已被交易拥挤」的因子。</p>
<p class="muted" style="white-space:pre-wrap"><b>质量Top28</b>：不用动量、不叠加 CSFM 门控。直接在当期股池内按 FAQ 得分降序取前 28 只，单行业最多 2 只。
v1 = 等权；v2 = 三道筛（剔除 20 日均成交额 &lt; 5,000 万元、剔除换手最拥挤 1/3、余者按 1/(换手分位+0.15) 加权、单只限幅 2%~8%）。季度调仓、季度内不再平衡。
<b>基准</b>：沪深300、中证500、创业板50。科创50 于 2020 年才有行情，且中证800 池不含科创板，故不再作为基准。</p>
</details>
</div>
<div class="card">
<div class="card-h"><h3>绩效汇总</h3><span class="muted">年化 / 波动按各组合调仓频率折算；夏普为年化超额（无风险利率取 0）</span></div>
<table class="tbl"><thead><tr><th rowspan="2">组合</th><th colspan="6" style="text-align:center">全期 {span()}</th>
<th colspan="4" style="text-align:center">分段</th></tr>
<tr><th class="num">累计</th><th class="num">年化</th><th class="num">波动</th><th class="num">最大回撤</th><th class="num">夏普</th><th class="num">卡玛</th>
<th class="num">15-18 年化</th><th class="num">夏普</th><th class="num">19-26 年化</th><th class="num">夏普</th></tr></thead>
<tbody>{body}</tbody></table>
<p class="muted">质量Top28 为季度收益序列，年化/波动已按 4 期/年折算（共 {quarters()} 期，2015Q1 起）。
CSFM/TSFM 为月度序列（{months()} 期）。</p>
</div>
<div class="card">
<div class="card-h"><h3>净值曲线</h3><span class="muted">起点归一为 1.00</span></div>
<div class="btns" id="rng"><button data-r="all" class="on">全部</button><button data-r="5y">近 5 年</button><button data-r="3y">近 3 年</button><button data-r="1y">近 1 年</button></div>
<div id="chart"></div>
<div class="leg">{leg}</div>
</div>"""


def sec_kappa():
    ks = [0.0, 0.5, 1.0, 1.5]
    rows_def = [("CSFM", 20, True), ("CSFM", 30, False), ("TSFM", 30, True), ("TSFM", 40, False)]

    def row(nm, n, main):
        v0 = kappa_cell(nm, n, 0.0)
        cells = ""
        for k in ks:
            v = kappa_cell(nm, n, k)
            cells += (f'<td class="num">{pct(v["vol"])}</td><td class="num">{num(v["sh"])}</td>'
                      if v else '<td class="num">—</td><td class="num">—</td>')
        v15 = kappa_cell(nm, n, 1.5)
        drop = "—" if not (v0 and v15) else f'{(v15["vol"]/v0["vol"]-1)*100:+.1f}%'
        mark = ' style="font-weight:600"' if main else ""
        lab = f'{nm}（N={n}）' + ('<span class="pill">主口径</span>' if main else "")
        return f'<tr{mark}><td>{lab}</td>{cells}<td class="num">{drop}</td></tr>'

    head = "".join(f'<th colspan="2" style="text-align:center">κ={k:g}</th>' for k in ks)
    sub = "".join('<th class="num">波动</th><th class="num">夏普</th>' for _ in ks)

    # 结论段里的数字一律现算，避免季度重跑后正文与表格打架
    def vol_at(nm, n, k):
        v = kappa_cell(nm, n, k)
        return None if not v else v["vol"]

    def sh_at(nm, n, k):
        v = kappa_cell(nm, n, k)
        return None if not v else v["sh"]

    cs_v0, cs_v15 = vol_at("CSFM", 20, 0.0), vol_at("CSFM", 20, 1.5)
    drops = []
    for nm, n, _ in rows_def:
        a, b = vol_at(nm, n, 0.0), vol_at(nm, n, 1.5)
        if a and b:
            drops.append((b / a - 1) * 100)
    # drops 是负值（表示下降），取绝对值后从小到大排，才能写成「9%~14%」
    drop_txt = (f"{abs(max(drops)):.0f}%~{abs(min(drops)):.0f}%"
                if drops else "9%~14%")
    p1 = (f'CSFM N=20 从 {cs_v0*100:.1f}% 降到 {cs_v15*100:.1f}%'
          if cs_v0 is not None and cs_v15 is not None else "")

    # 纯按夏普的最优点（用于解释主口径为何不取它）
    cs_all = [x for x in D.get("kappa", []) if x["s"] == "CSFM"]
    best = max(cs_all, key=lambda x: x["sh"]) if cs_all else None
    best_txt = ""
    if best:
        bv, mv = best["vol"], vol_at("CSFM", 20, 1.5)
        gap = f'、但波动高 {(bv - mv)*100:.1f} 个百分点' if bv and mv and bv > mv else ""
        best_txt = (f"CSFM 若纯按夏普排，最优点是 N={best['n']} / κ={best['k']:g}"
                    f"（夏普 {best['sh']:.3f}）{gap}；主口径 N=20 / κ=1.5 的夏普 "
                    f"{(sh_at('CSFM', 20, 1.5) or 0):.3f}，差 {(best['sh'] - (sh_at('CSFM', 20, 1.5) or 0)):.3f}，"
                    f"换来更低的波动与更浅的回撤。")

    cs20 = (sh_at("CSFM", 20, 0.0), sh_at("CSFM", 20, 1.5))
    cs30 = (sh_at("CSFM", 30, 0.0), sh_at("CSFM", 30, 1.5))
    ts30 = (sh_at("TSFM", 30, 0.0), sh_at("TSFM", 30, 1.5))
    s2 = ("CSFM 在两端是抬升的（N=20：{:.2f} → {:.2f}，N=30：{:.2f} → {:.2f}），但中间档位并非单调；"
          "TSFM 更极端 —— κ=1.5 时夏普从 {:.2f} 掉到 {:.2f}".format(*cs20, *cs30, *ts30)
          if all(x is not None for x in cs20 + cs30 + ts30) else
          "CSFM 两端抬升，但 TSFM 在 κ 过大时反而变差")

    return f"""<h2>四、F 反馈强度：κ 如何压波动</h2>
<div class="card">
<p class="muted" style="margin-top:0">F 把因子的「24 个月自相关」与「12 个月趋势 R²」合成为拥挤度百分位，权重乘以 (1 − κ·F)。
κ=0 即不门控；κ 越大，越回避已被反复交易、动量趋于拥挤的因子。下表固定持股数 N，单看 κ 的作用：</p>
<table class="tbl"><thead><tr><th rowspan="2">组合</th>{head}<th rowspan="2" class="num">波动<br>变化</th></tr>
<tr>{sub}</tr></thead><tbody>{''.join(row(*r) for r in rows_def)}</tbody></table>
<p class="muted"><b>结论一（稳健）：κ 单调压波动。</b>四个 N 下 κ 从 0 提到 1.5，年化波动全部下降 {drop_txt}，
{p1}——这是"降波动"最直接的来源，且在不同持股数下方向一致。</p>
<p class="muted"><b>结论二（有条件）：夏普不保证单调抬升。</b>{s2}。TSFM 每因子只取自身收益符号，
权重本就更"薄"，再乘 (1−1.5F) 会把有效信号削没。故主口径取 <b>CSFM N=20 / κ=1.5</b>、<b>TSFM N=30 / κ=1.0</b>。
{best_txt}</p>
<div class="warn">κ 与 N 都是在全样本上挑的，属于样本内最优，存在过拟合风险。若要上实盘，建议固定 κ 后做滚动前推（walk-forward）验证，而非每年重挑参数。</div>
</div>"""


def sec_hold():
    cur = D["pools"][-1]
    prev = D["pools"][-2] if len(D["pools"]) > 1 else D["pools"][-1]

    def top28(p):
        flat = [(i["name"], it) for i in p["inds"] for it in i["items"]]
        flat.sort(key=lambda x: -x[1]["s"])
        cnt, out = {}, []
        for ind, it in flat:
            if cnt.get(ind, 0) >= 2:
                continue
            out.append({**it, "ind": ind})
            cnt[ind] = cnt.get(ind, 0) + 1
            if len(out) >= 28:
                break
        return out

    a, b = top28(cur), top28(prev)
    na = {x["c"] for x in a}
    nb = {x["c"] for x in b}
    rows = ""
    for i, it in enumerate(a, 1):
        if it["c"] not in nb:
            tag, cls = '<span class="tag tag-new">新进</span>', "r-new"
        else:
            tag, cls = '<span class="tag tag-keep">保留</span>', ""
        mv = "—" if it["m"] is None else f"{it['m']:.0f}"
        pre = "sh" if it["c"][0] == "6" else ("bj" if it["c"][:2] in ("43", "83", "87", "92") else "sz")
        rows += (f'<tr class="{cls}"><td class="rk">{i}</td><td class="mono">{pre}{it["c"]}</td><td>{it["n"]}</td>'
                 f'<td>{it["ind"]}</td><td class="num">{it["s"]:.2f}</td><td class="num">{mv}</td><td>{tag}</td></tr>')
    out_list = [x for x in b if x["c"] not in na]
    outs = "".join(f'<tr class="r-out"><td class="mono">{x["c"]}</td><td>{x["n"]}</td><td>{x["ind"]}</td>'
                   f'<td class="num">{x["s"]:.2f}</td><td><span class="tag tag-out">退出</span></td></tr>'
                   for x in out_list)
    return f"""<h2>五、最新一期持仓：质量Top28 v2</h2>
<div class="card">
<div class="card-h"><h3>{cur['label']}（信息可得 {cur['asof']}）</h3>
<span class="muted">28 只 · 单行业≤2 · 相对上期（{prev['label']}）新进 {len(na-nb)} 只 / 退出 {len(nb-na)} 只</span></div>
<table class="tbl"><thead><tr><th>#</th><th>代码</th><th>名称</th><th>申万三级</th><th class="num">FAQ 评分</th><th class="num">市值(亿)</th><th>状态</th></tr></thead>
<tbody>{rows}</tbody></table>
</div>
<div class="card"><div class="card-h"><h3>本期退出</h3><span class="muted">{len(out_list)} 只</span></div>
<table class="tbl"><thead><tr><th>代码</th><th>名称</th><th>申万三级</th><th class="num">上期评分</th><th>状态</th></tr></thead>
<tbody>{outs or '<tr><td colspan="5" class="muted">无</td></tr>'}</tbody></table>
<p class="muted">退出原因多为上期评分下滑、同行业已满 2 只，或落入 v2 流动性 / 拥挤度剔除区间。CSFM / TSFM 为月度调仓，持仓变动频繁（年均换手 500%+），不在本页逐期列示。</p>
</div>"""


def sec_howto():
    return """<h2>六、如何更新最新一季股池</h2>
<div class="card"><ol>
<li><b>成分快照</b>：用 Baostock <code>query_hs300_stocks(date)</code> / <code>query_zz500_stocks(date)</code> 按信息可得日取并集（800 只）；新一期调样日需同步补拉。</li>
<li><b>财务三表</b>：拉最新报告期的 lrb / zcfz / xjll / yjbb，计算 ROE-TTM、ROA、应计、现金转换、分红稀释、投资扩张四支柱。</li>
<li><b>FAQ 评分</b>：<code>FAQ = Q_z − 1.0·F_z</code>，四支柱权重 盈利 0.34 / 会计质量 0.22 / 分红稀释 0.22 / 投资 0.22，行业内中性。</li>
<li><b>股池生成</b>：按申万三级行业降序取前 5（不足 5 只不补），写入本期明细。</li>
<li><b>替换标的池</b>：三个组合从这个信息可得日起按新池调仓，历史净值不回改。</li>
</ol></div>"""


CHART_JS = """<script>
var D=%(data)s;
var COL=%(col)s, SHORT=%(short)s, ORDER=%(order)s;
var ALLW=900, H=380, PL=52, PR=96, PT=20, PB=36;
function draw(range){
  var dts=D.curve.dates, ser=D.curve.series;
  var n=dts.length, i0=0;
  if(range!=='all'){
    var yrs=parseInt(range), cut=new Date(dts[n-1]);
    cut.setFullYear(cut.getFullYear()-yrs);
    var iso=cut.toISOString().slice(0,10);
    while(i0<n-1 && dts[i0]<iso) i0++;
  }
  var lo=1e9,hi=-1e9;
  ORDER.forEach(function(k){var s=ser[k];for(var i=i0;i<n;i++){if(s[i]>hi)hi=s[i];if(s[i]<lo)lo=s[i];}});
  // 对数轴：净值跨度大（0.5~5）时线性轴会把前 5 年压平
  var lg=function(v){return Math.log(Math.max(v,1e-6))};
  var y0=lg(lo)-0.04*(lg(hi)-lg(lo)), y1=lg(hi)+0.04*(lg(hi)-lg(lo));
  var W=ALLW, x=function(i){return PL+(W-PL-PR)*(i-i0)/Math.max(1,n-1-i0)};
  var y=function(v){return PT+(H-PT-PB)*(y1-lg(v))/(y1-y0)};
  var h='<svg viewBox="0 0 '+W+' '+H+'" class="chart">';
  for(var g=0;g<5;g++){
    var v=Math.exp(y0+(y1-y0)*g/4), yy=y(v);
    h+='<line x1="'+PL+'" y1="'+yy+'" x2="'+(W-PR)+'" y2="'+yy+'" stroke="#eef0f3"/>';
    h+='<text x="'+(PL-8)+'" y="'+(yy+4)+'" text-anchor="end" font-size="11" fill="#6b7280">'+v.toFixed(2)+'</text>';
  }
  ORDER.forEach(function(k){
    var s=ser[k], pts=[];
    for(var i=i0;i<n;i+=1) pts.push(x(i).toFixed(1)+','+y(s[i]).toFixed(1));
    h+='<polyline points="'+pts.join(' ')+'" fill="none" stroke="'+COL[k]+'" stroke-width="'+(k.indexOf('沪深')>=0||k.indexOf('中证')>=0||k.indexOf('创业')>=0?1.4:2.2)+'"/>';
  });
  // 末端标签：按 y 排序后强制最小间距，避免净值和接近时文字叠在一起
  var labs=ORDER.map(function(k){return {k:k, yy:y(ser[k][n-1]), v:ser[k][n-1]}});
  labs.sort(function(a,b){return a.yy-b.yy});
  for(var j=1;j<labs.length;j++){ if(labs[j].yy-labs[j-1].yy<13) labs[j].yy=labs[j-1].yy+13; }
  labs.forEach(function(L){
    h+='<text x="'+(W-PR+8)+'" y="'+(L.yy+4)+'" font-size="11" fill="'+COL[L.k]+'">'+(SHORT[L.k]||L.k)+' '+L.v.toFixed(2)+'</text>';
  });
  var ticks=[0,0.25,0.5,0.75,1];
  ticks.forEach(function(t){
    var i=Math.min(n-1,Math.round(i0+(n-1-i0)*t));
    h+='<text x="'+x(i)+'" y="'+(H-12)+'" text-anchor="middle" font-size="11" fill="#9ca3af">'+dts[i].slice(0,7)+'</text>';
  });
  h+='</svg>';
  document.getElementById('chart').innerHTML=h;
}
document.getElementById('rng').addEventListener('click',function(e){
  var b=e.target.closest('button'); if(!b) return;
  [].forEach.call(this.querySelectorAll('button'),function(x){x.classList.remove('on')});
  b.classList.add('on'); draw(b.dataset.r);
});
draw('all');
</script>"""


# ---------------------------------------------------------------- 入口
def build(data: dict) -> str:
    """把数据包渲染成完整 HTML 字符串。"""
    global D
    D = data
    if not D.get("pools"):
        raise ValueError("page_data.json 缺少 pools")
    js = CHART_JS % {
        "data": json.dumps({"curve": D["curve"]}, ensure_ascii=False, separators=(",", ":")),
        "col": json.dumps(COL, ensure_ascii=False),
        "short": json.dumps(SHORT, ensure_ascii=False),
        "order": json.dumps(STRAT + BENCH, ensure_ascii=False),
    }
    cur = D["pools"][-1]
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<script src="/page/page_comm/inject.js"></script>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>舞弊调整质量因子 · 季度动态股池</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<h1>舞弊调整质量因子 · 季度动态股池</h1>
<div class="sub">标的池 = 官方中证800 历史成分（沪深300 ∪ 中证500，逐期 PIT 快照）· 申万三级行业各取前 5 · 回测 {span()} · 截至 {cur['asof']}</div>
{kpi_row()}
{sec_intro()}
{sec_pools()}
{sec_bt()}
{sec_kappa()}
{sec_hold()}
{sec_howto()}
<div class="note" style="margin-top:22px">口径提醒：本期起「标的池」不再用市值前 800 拟合，改为官方指数成分；
因此历史各期股池、以及三个组合的历史净值与旧版页面<b>不可直接对比</b>。旧版 2019-05 起的日频回测（CSFM 年化 42%）存在幸存者偏差与次新股涨停虚增，
新版统一做了次新股过滤、停牌前向填充、收益截尾与时点财务，数字更低但可复现。κ / N 为样本内选择，存在过拟合风险，实盘应留出样本外验证。</div>
</div>{js}</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="page_data.json → 季度股池页面 HTML")
    ap.add_argument("--data", required=True, help="数据包 JSON 路径")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    a = ap.parse_args()

    data = json.load(open(a.data, encoding="utf-8"))
    doc = build(data)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"[render] {a.out} {os.path.getsize(a.out)/1e6:.2f} MB  "
          f"（{len(data['pools'])} 期，最新 {data['pools'][-1]['label']}）")


if __name__ == "__main__":
    main()
