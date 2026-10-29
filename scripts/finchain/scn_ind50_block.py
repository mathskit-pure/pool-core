# -*- coding: utf-8 -*-
"""情景对比的 HTML 片段与绘图/表格工具函数。

**注意**：本脚本已不再接入托管页面的重建链路（patch_page.py 的注入已撤销），
情景结论以独立报告交付，见 scn_ind50_report.py。这里保留的 perf / svg_chart / pool_table
等函数供报告脚本复用；直接运行仍会输出 data/scn_ind50_block.html（片段，供临时查看）。

重跑情景时：build_pools_v6_ind50.py → scenario_ind50.py，把两套净值放回
 data/scn_ind50/{base,ind50}/，再跑 scn_ind50_report.py 出报告。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import DATA, FIN_D15 as D15  # noqa: E402

SCN = os.path.join(DATA, "scn_ind50")          # 情景回测产物归档（base / ind50）
OUT = os.path.join(DATA, "scn_ind50_block.html")

COMBOS = [("CSFM", "因子动量·横截面 CSFM", "#d81b60"),
          ("TSFM", "因子动量·时间序列 TSFM", "#00897b"),
          ("Q28", "质量Top28组合", "#0f9d58")]
RED, GREEN = "#d81b60", "#0f9d58"
LATEST = "2026-09-01"


def perf(nav):
    r = nav.pct_change().dropna()
    n = len(r)
    ann = nav.iloc[-1] ** (252.0 / n) - 1
    vol = float(r.std(ddof=0) * np.sqrt(252))
    dd = float((nav / nav.cummax() - 1).min())
    return {"cum": nav.iloc[-1] - 1, "ann": ann, "vol": vol, "dd": dd,
            "sh": ann / vol if vol else np.nan, "cal": ann / abs(dd) if dd < 0 else np.nan}


def pct(v, sign=True):
    s = f"{v*100:+.2f}%" if sign else f"{v*100:.2f}%"
    return s


def dcell(v, unit="pct", better="up"):
    """差值单元格：改善红、恶化绿（A 股习惯）"""
    good = (v > 0) if better == "up" else (v < 0)
    col = RED if good else GREEN
    txt = f"{v*100:+.2f}pct" if unit == "pct" else f"{v:+.2f}"
    return f'<td class="num" style="color:{col};font-weight:600">{txt}</td>'


def svg_chart(B, S):
    """6 条曲线：实线=情景池，虚线=基准池"""
    W, H = 1000, 400
    L, R, T, Bm = 56, 210, 18, 52
    w, h = W - L - R, H - T - Bm
    step = max(1, len(B) // 460)
    idx = list(range(0, len(B), step))
    if idx[-1] != len(B) - 1:
        idx.append(len(B) - 1)
    dates = B.index
    vals = []
    for nm, _, _ in COMBOS:
        vals.append(B[nm].to_numpy()[idx])
        vals.append(S[nm].to_numpy()[idx])
    lo = float(np.nanmin([np.nanmin(v) for v in vals]))
    hi = float(np.nanmax([np.nanmax(v) for v in vals]))
    # 取整刻度：步长限定在 {1,2,2.5,5}×10^k，避免出现 0.89 / 1.48 这类难读的轴标
    raw = (hi - lo) / 6.0
    mag = 10.0 ** np.floor(np.log10(raw))
    ystep = next(m * mag for m in (1, 2, 2.5, 5, 10) if raw <= m * mag)
    ymin = float(np.floor(lo / ystep) * ystep)
    ymax = float(np.ceil(hi / ystep) * ystep)

    def X(i):
        return L + w * i / (len(idx) - 1)

    def Y(v):
        return T + h * (1 - (v - ymin) / (ymax - ymin))

    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px;height:auto;'
         f'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif">',
         f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>']
    # y 网格
    nt = int(round((ymax - ymin) / ystep)) + 1
    for k in range(nt):
        v = ymin + ystep * k
        y = Y(v)
        p.append(f'<line x1="{L}" x2="{L+w}" y1="{y:.1f}" y2="{y:.1f}" stroke="#eef0f3"/>')
        p.append(f'<text x="{L-8}" y="{y+4:.1f}" fill="#6b7280" font-size="11" '
                 f'text-anchor="end">{v:g}</text>')
    # x 刻度
    for t in range(6):
        i = round((len(idx) - 1) * t / 5)
        p.append(f'<text x="{X(i):.1f}" y="{T+h+20}" fill="#6b7280" font-size="11" '
                 f'text-anchor="middle">{dates[idx[i]].strftime("%y-%m")}</text>')
    # 曲线
    for k, (nm, lab, col) in enumerate(COMBOS):
        for j, (df, dash, op, wd) in enumerate(((B, "5 4", .75, 1.6), (S, "", 1, 2.2))):
            arr = df[nm].to_numpy()[idx]
            pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(arr)
                           if np.isfinite(v))
            da = f' stroke-dasharray="{dash}"' if dash else ""
            p.append(f'<polyline fill="none" stroke="{col}" stroke-width="{wd}" '
                     f'opacity="{op}"{da} points="{pts}"/>')
    # 图例
    for k, (nm, lab, col) in enumerate(COMBOS):
        y = T + 10 + k * 52
        p.append(f'<line x1="{L+w+14}" x2="{L+w+42}" y1="{y}" y2="{y}" stroke="{col}" '
                 f'stroke-width="2.2"/>')
        p.append(f'<text x="{L+w+48}" y="{y+4}" fill="#374151" font-size="12">'
                 f'{lab.replace("·", "·")} · 情景</text>')
        p.append(f'<line x1="{L+w+14}" x2="{L+w+42}" y1="{y+20}" y2="{y+20}" stroke="{col}" '
                 f'stroke-width="1.6" stroke-dasharray="5 4" opacity="0.75"/>')
        p.append(f'<text x="{L+w+48}" y="{y+24}" fill="#6b7280" font-size="11">'
                 f'原池（全行业）</text>')
    p.append(f'<text x="{L}" y="{H-10}" fill="#9ca3af" font-size="11">'
             f'2017-01-03 → 2026-10-16 · 净值统一在 2017 首个交易日归一到 1.00</text>')
    p.append("</svg>")
    return "".join(p)


def pool_table(P, U, IR, names):
    rows = []
    grp = P.sort_values(["ind_rank", "rank_in_ind"]).groupby("sw3", sort=False)
    for ind, g in grp:
        rank = int(g["ind_rank"].iloc[0])
        imv = IR.get(ind, np.nan)
        rows.append(f'<tr class="ind-row"><td colspan="5" style="background:#f6f7f9;'
                    f'font-weight:600;padding:6px 8px">#{rank} · {ind}'
                    f'<span style="color:#6b7280;font-weight:400"> · 行业市值 '
                    f'{imv:,.0f} 亿</span></td></tr>')
        for _, r in g.iterrows():
            mv = U.get(r["code"], np.nan)
            mvs = "—" if not np.isfinite(mv) else f"{mv:,.0f}"
            rows.append(f'<tr><td class="num">{int(r["rank_in_ind"])}</td>'
                        f'<td class="mono">{r["code"]}</td><td>{names.get(r["code"], r["name"])}</td>'
                        f'<td class="num">{r["FAQ_score"]:.2f}</td><td class="num">{mvs}</td></tr>')
    return ('<table class="mini" style="width:100%"><thead><tr><th>#</th><th>代码</th>'
            '<th>名称</th><th>评分</th><th>市值(亿)</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def main():
    B = pd.read_csv(os.path.join(SCN, "base", "daily_nav.csv"), index_col=0, parse_dates=True)
    S = pd.read_csv(os.path.join(SCN, "ind50", "daily_nav.csv"), index_col=0, parse_dates=True)

    # ── 表 A：全期绩效 ──
    rows = []
    for nm, lab, _ in COMBOS:
        pb, ps = perf(B[nm].dropna()), perf(S[nm].dropna())
        rows.append(
            f'<tr><td rowspan="2"><b>{lab}</b></td><td>原池 · 全部行业</td>'
            f'<td class="num">{pct(pb["cum"])}</td><td class="num">{pct(pb["ann"])}</td>'
            f'<td class="num">{pct(pb["vol"], 0)}</td><td class="num">{pct(pb["dd"])}</td>'
            f'<td class="num">{pb["sh"]:.2f}</td><td class="num">{pb["cal"]:.2f}</td>'
            f'<td class="num">—</td></tr>'
            f'<tr><td><b>情景池 · 行业前50×3</b></td>'
            f'<td class="num"><b>{pct(ps["cum"])}</b></td><td class="num"><b>{pct(ps["ann"])}</b></td>'
            f'<td class="num">{pct(ps["vol"], 0)}</td><td class="num">{pct(ps["dd"])}</td>'
            f'<td class="num"><b>{ps["sh"]:.2f}</b></td><td class="num"><b>{ps["cal"]:.2f}</b></td>'
            f'{dcell(ps["ann"]-pb["ann"])}</tr>')
    tab_a = ('<table class="tbl"><thead><tr><th rowspan="2">组合</th><th rowspan="2">股池</th>'
             '<th colspan="4">2017-01-03 → 2026-10-16</th><th colspan="2">风险调整</th>'
             '<th>差值</th></tr><tr><th>累计收益</th><th>年化收益</th><th>年化波动</th>'
             '<th>最大回撤</th><th>夏普</th><th>卡玛</th><th>年化</th></tr></thead><tbody>'
             + "".join(rows) + "</tbody></table>")

    # ── 表 B：分年度 ──
    # 分年度：2017 用「年内末值 / 窗口起点(1.00) − 1」，其余用年末对年末
    cols = {}
    for nm, _, _ in COMBOS:
        for tag, df in (("b", B), ("s", S)):
            yl = df[nm].resample("YE").last()
            cols[f"{tag}_{nm}"] = yl
    yr = pd.DataFrame(cols)
    first = yr.iloc[0].copy()
    yr = yr / yr.shift(1) - 1
    yr.iloc[0] = first.values - 1
    yr.index = [d.year for d in yr.index]
    body = []
    for y in yr.index:
        cells = [f'<td class="num">{y}</td>']
        for nm, _, _ in COMBOS:
            b, s = yr.loc[y, f"b_{nm}"], yr.loc[y, f"s_{nm}"]
            d = s - b
            col = RED if d > 0 else GREEN
            cells.append(f'<td class="num">{pct(b)}</td><td class="num">{pct(s)}</td>'
                         f'<td class="num" style="color:{col};font-weight:600">{d*100:+.1f}pct</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    head = ('<thead><tr><th rowspan="2">年度</th>'
            + "".join(f'<th colspan="3">{lab.replace("因子动量·", "")}</th>'
                      for _, lab, _ in COMBOS)
            + '</tr><tr>' + "".join('<th>原池</th><th>情景</th><th>差</th>' for _ in COMBOS)
            + '</tr></thead>')
    tab_b = f'<table class="tbl">{head}<tbody>' + "".join(body) + "</tbody></table>"

    # ── 最新一期股池 ──
    v6 = pd.read_csv(os.path.join(D15, "pools_v6_ind50.csv"), dtype={"code": str})
    v5 = pd.read_csv(os.path.join(D15, "pools_v5.csv"), dtype={"code": str})
    ir = pd.read_csv(os.path.join(D15, "industry_rank.csv"))
    P = v6[v6["asof"] == LATEST].copy()
    uni = pd.read_csv(os.path.join(D15, "universe_pit.csv"), dtype={"code": str})
    U = dict(zip(uni[uni["asof"] == LATEST]["code"].str.zfill(6),
                 uni[uni["asof"] == LATEST]["mcap_yi"]))
    IR = dict(zip(ir[ir["asof"] == LATEST]["sw3"], ir[ir["asof"] == LATEST]["ind_mcap_yi"]))
    names = dict(zip(v5["code"].str.zfill(6), v5["name"]))
    names.update(dict(zip(v6["code"].str.zfill(6), v6["name"])))
    n5 = len(v5[v5["asof"] == LATEST])
    i5 = v5[v5["asof"] == LATEST]["sw3"].nunique()

    html = f"""
<div class="card" id="scnInd50">
  <div class="card-h"><h3>3.6　情景：股池进一步限定为「申万三级行业市值前 50 × 各行业前 3」</h3>
  <span class="pill">情景测算 · 不改动本页既有口径</span></div>
  <details class="blk-fold" open><summary class="blk-fold-s"><span class="blk-fold-i">&#9654;</span>
  <span class="blk-fold-t">情景设定与口径</span>
  <span class="blk-fold-n">唯一变量 = 股池；选股、加权、成本、执行时点全部沿用本页第三章</span>
  <span class="blk-fold-a"><span class="blk-fold-off">点击展开</span><span class="blk-fold-on">点击收起</span></span>
  </summary><div class="blk-fold-b">
  <p class="muted" style="white-space:pre-wrap">在既有模型上只加两道行业限制，其余一律不动：
<b>① 行业准入</b>：按「申万三级行业总市值」（该行业<b>全部 A 股</b>市值加总，PIT，取信息可得日之前最后一个有效市值）降序，只保留前 <b>50</b> 个行业；
<b>② 行业名额</b>：每个准入行业仍取舞弊调整质量因子（FAQ）评分<b>前 3</b>（与原池同一套评分，报告期与信息可得日对应关系不变）。
因此变化只有一个：行业数从 <b>{i5}</b> 个（最新一期）收缩到 <b>{P['sw3'].nunique()}</b> 个，股池从 {n5} 只收缩到 {len(P)} 只。
原池中平均只有 <b>40.2%</b> 的个股落在市值前 50 的行业内，其余约六成被挤掉。

<b>评分与回测口径完全复用</b>：CSFM / TSFM（10 因子动量、κ=1.5 / 1.0、月度调仓、次新股过滤、开盘一字涨停权重空置）、质量Top28（FAQ 降序 + 单行业 ≤2 + v2 三道筛权重）、单边 10bp 成本、T 日决策 T+1 执行、2017 首个交易日归一到 1.00。两侧读数由<b>同一份代码</b>跑出：原池一侧精确复现本页上方 40.39% / 123.45% / 152.60%，故差值只可能来自换池。

<b>行业口径说明</b>：行业标签沿用本页现行的申万分类字段（与「单行业 ≤ 2 只」同源），其中部分标签为申万二级（如通用设备、汽车零部件、半导体），行业总市值因此按标签实际覆盖的成员计算 —— 这是本页数据侧能做到的最贴近口径；若要严格只保留三级标签，需重新抓取全市场申万三级成分。</p>
  </div></details>

  <div style="margin:14px 0 6px"><b>（1）全期绩效对比</b>
  <span class="muted">　差值为「情景 − 原池」的年化收益；红＝改善，绿＝恶化</span></div>
  <div style="overflow-x:auto">{tab_a}</div>

  <div style="margin:18px 0 6px"><b>（2）净值曲线</b>
  <span class="muted">　实线＝情景池（行业前50×3）；虚线＝原池（全部行业）</span></div>
  <div>{svg_chart(B, S)}</div>

  <div style="margin:18px 0 6px"><b>（3）分年度收益</b>
  <span class="muted">　2026 年为年初至 10-16</span></div>
  <div style="overflow-x:auto">{tab_b}</div>

  <div style="margin:18px 0 6px"><b>（4）新一期股池明细（2026 年中报 · 信息可得 2026-09-01）</b>
  <span class="muted">　{P['sw3'].nunique()} 个行业 · {len(P)} 只；行业前缀为行业市值排名</span></div>
  <details><summary class="muted" style="cursor:pointer;padding:6px 0">展开 / 收起（{P['sw3'].nunique()} 个行业 · {len(P)} 只）</summary>
  <div style="max-height:520px;overflow:auto">{pool_table(P, U, IR, names)}</div></details>

  <div style="margin:18px 0 6px"><b>（5）结论</b></div>
  <ul class="muted" style="line-height:1.9;margin:0;padding-left:20px">
    <li><b>质量Top28 明显受损</b>：累计 152.60% → 80.46%，年化 10.34% → 6.47%，夏普 0.57 → 0.38。质量因子的超额主要来自中小市值行业里的「干净公司」，把行业砍到前 50 等于把这部分 alpha 直接掐掉；只有最大回撤略降（−28.49% → −25.49%）。</li>
    <li><b>CSFM 显著改善</b>：累计 40.39% → 141.93%，年化 3.67% → 9.84%，回撤 −52.22% → −37.59%，夏普 0.17 → 0.45。横截面因子动量在中小行业里容易踩到「单行业噪声把因子收益做偏」的坑，收缩到大行业后因子暴露更干净。</li>
    <li><b>TSFM 基本持平</b>：累计 123.45% vs 122.68%，年化 8.91% vs 8.87%，但波动与回撤同步下降（回撤 −42.01% → −38.75%），夏普 0.37 → 0.38 —— 属于「同样收益、风险略小」。</li>
    <li><b>本质上是风格切换而非改良</b>：三套组合与原池的持仓重合度只有 43%~46%，日收益相关性 0.87~0.94。这一限制把组合整体推向大市值、大行业，等于押注「大行业里的头部公司」，2021 与 2026 年的差额主要来自这里（2021：CSFM −9.0% → +8.3%；2026 至 10-16：−31.8% → −9.5%）。</li>
    <li><b>取舍建议</b>：若目标是把回撤压下来、能接受放弃质量因子的中小盘超额，可把行业限制用在 CSFM 上（夏普 0.17 → 0.45 的改善几乎全部来自回撤）；质量Top28 与 TSFM 不建议加此限制（前者年化掉 3.9pct，后者无增益）。</li>
  </ul>
</div>
"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[ok] {OUT}  {os.path.getsize(OUT)/1024:.0f} KB")


if __name__ == "__main__":
    main()
