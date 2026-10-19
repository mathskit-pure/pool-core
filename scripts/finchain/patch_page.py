# -*- coding: utf-8 -*-
"""在原版版式上替换内容（不改任何 UI 细节）。

输入：data/page_base.html（原版页面）+ out15/page_content.json（新数据）
输出：out15/pool_page_v5.html

只做四件事：
  ① 说明文字里过期的口径（回测起点、持仓数、基准、v2 权重规则、报告期范围、KPI）
  ② 二、季度股池明细：35 期新池（沿用原 .card/.ind/.mini 结构）
  ③ 三、组合回测：var BT 换成 2015-2026 逐日净值 + 静态表 + 时间轴刻度
  ④ 四、仓位建议（var POS，按新净值重算）+ 五、持仓变动明细（最近 8 期）
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# 路径统一由 scripts/paths.py 解析（本机 Windows 与云端 Linux 同一份代码）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import DATA, FIN_OUT as OUT  # noqa: E402

TPL = os.path.join(DATA, "page_base.html")


def clean(h):
    """去掉编辑器节点标记（import_html 会重新生成），顺便把体积压下来"""
    h = re.sub(r"<!--pnid:\w+-->", "", h)
    h = re.sub(r' data-page-node-id="\w+"', "", h)
    h = re.sub(r' data-pnid-children="\w+"', "", h)
    return h


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------- 二、季度股池 ----------------
def sec_pools(P):
    cards = []
    for p in P:
        inds = []
        for it in p["inds"]:
            rows = "".join(
                f'<tr><td class="rk">{i+1}</td><td class="mono">{r["c"]}</td><td>{esc(r["n"])}</td>'
                f'<td class="num">{r["s"]:.2f}</td>'
                f'<td class="num">{"—" if r["m"] is None else int(r["m"])}</td></tr>'
                for i, r in enumerate(it["rows"]))
            inds.append(
                f'<div class="ind"><div class="ind-h"><span class="ind-name">{esc(it["ind"])}</span>'
                f'<span class="muted">{len(it["rows"])} 只</span></div>'
                f'<table class="mini"><thead><tr><th>#</th><th>代码</th><th>名称</th>'
                f'<th>评分</th><th>市值(亿)</th></tr></thead><tbody>{rows}</tbody></table></div>')
        cards.append(
            f'<section class="card"><div class="card-h"><h3>{p["label"]}'
            f'<span class="pill">信息可得 {p["avail"]}</span></h3>'
            f'<span class="muted">{p["n"]} 只 · {p["nind"]} 个申万三级行业</span></div>'
            f'<details><summary>展开 / 收起（{p["nind"]} 个行业 · {p["n"]} 只）</summary>'
            f'<div class="grid">{"".join(inds)}</div></details></section>')

    return (f'<h2>二、季度股池（申万三级行业各取前 5，不足 5 只不补入）</h2>\n'
            f'<details class="blk-fold"><summary class="blk-fold-s">'
            f'<span class="blk-fold-i">&#9654;</span><span class="blk-fold-t">季报明细</span>'
            f'<span class="blk-fold-n">共 {len(P)} 期 · {P[0]["label"]} → {P[-1]["label"]}</span>'
            f'<span class="blk-fold-a"><span class="blk-fold-off">点击展开</span>'
            f'<span class="blk-fold-on">点击收起</span></span></summary>'
            f'<div class="blk-fold-b">{"".join(cards)}</div></details>\n')


# ---------------- 三、回测表 ----------------
# 注意：原版页面的行 id 是 r0,r1,r2,r4,r5,r6（跳过 r3），而内联脚本按
# BT.order 的顺序写 r0..r5 —— 于是「创业板50」那一行实际显示的是科创50 的数据，
# 科创50 那一行则是永不更新的静态值。这里按 order 顺序重排为 r0..r5，行数不变。
ROWS = [("r0", "因子动量·横截面 CSFM", "因子动量CSFM"),
        ("r1", "因子动量·时间序列 TSFM", "因子动量TSFM"),
        ("r2", "质量Top28组合", "质量Top28组合"),
        ("r3", "沪深300", "沪深300"),
        ("r4", "中证500", "中证500"),
        ("r5", "创业板50", "创业板50")]


def pct(v, sign=False):
    if v is None:
        return "—"
    return f"{v*100:+.2f}%" if sign else f"{v*100:.2f}%"


def sec_bt_table(perf):
    out = []
    for rid, label, key in ROWS:
        p = perf[key]
        cells = [pct(p["cum"]), pct(p["ann"]), pct(p["vol"]), pct(p["dd"], True),
                 f'{p["sh"]:.2f}', f'{p["cal"]:.2f}' if p["cal"] is not None else "—"]
        tds = "".join(f'<td class="num" id="{rid}_{i}">{v}</td>' for i, v in enumerate(cells))
        out.append(f'<tr><td><b>{label}</b></td>{tds}</tr>')
    return "<tbody>" + "".join(out) + "</tbody>"


def sec_recent(rows, kind):
    """五、持仓变动明细的单组合 tbody"""
    body = []
    for i, r in enumerate(rows):
        latest = '<span class="pill">最新一期</span>' if i == 0 else ""
        pos = ""
        if r["pos"] is not None:
            ttl = ("CSFM" if kind == "CSFM" else "TSFM") + " 建议权益仓位：T 日收盘达标、T+1 生效；仅调整总仓位，不调整持仓个股"
            pos = f'<span class="pbox b-ctrl" title="{ttl}">仓位 {r["pos"]}%</span>'
        nav = ""
        if r["ret"] is not None:
            cls = "up" if r["ret"] >= 0 else "dn"
            nav = f'<span class="pbox b-nav {cls}">较上期 {r["ret"]*100:+.2f}%</span>'
        head = f'<td class="day">{r["date"]}{pos}{nav}{latest}</td>'

        hold = "".join(
            f'<span class="{"nm-new" if h["new"] else "nm"}">{esc(h["n"])}</span>'
            f'<span class="wt">{h["w"]*100:.2f}%</span>' for h in r["hold"])
        outs = []
        for o in r["out"]:
            if o["r"] is None:
                outs.append(f'<span class="nm-out">{esc(o["n"])}</span>'
                            f'<span class="join">建仓 {o["e"] or "—"}</span> <span class="mut">—</span>')
            else:
                cls = "up" if o["r"] >= 0 else "dn"
                outs.append(f'<span class="nm-out">{esc(o["n"])}</span>'
                            f'<span class="join">建仓 {o["e"] or "—"}</span> '
                            f'<span class="{cls}">{o["r"]*100:+.2f}%</span>')
        out_cell = "、".join(outs) if outs else '<span class="mut">无</span>'
        body.append(f'<tr>{head}<td class="cell">{hold}</td><td class="cell">{out_cell}</td></tr>')
    return "<tbody>" + "".join(body) + "</tbody>"


def ticks(dates):
    ys = []
    for y in range(int(dates[0][:4]) + 1, int(dates[-1][:4]) + 1):
        k = next((i for i, d in enumerate(dates) if d >= f"{y}-01-01"), None)
        if k is None:
            continue
        ys.append((y, k / (len(dates) - 1) * 100))
    return "".join(f'<span style="left:{p:.2f}%">{y}</span>' for y, p in ys)


def build():
    h = clean(open(TPL, encoding="utf-8").read())
    D = json.load(open(os.path.join(OUT, "page_content.json"), encoding="utf-8"))
    P, bt, perf, pos, recent, kpi, meta = (D["periods"], D["bt"], D["perf"], D["pos"],
                                           D["recent"], D["kpi"], D["meta"])

    # ---- ① 头部说明与 KPI
    h = h.replace("报告期：2019年一季报 → 2026年中报",
                  f'报告期：{P[0]["label"]} → {P[-1]["label"]}')
    reps = [("<b>评分报告期</b>".replace("<b>", ""), None)]
    h = re.sub(r'(<span>评分报告期</span>)<b>\d+</b>', rf'\g<1><b>{kpi["n_period"]}</b>', h)
    h = re.sub(r'(<span>股池覆盖个股\(并集\)</span>)<b>[\d,]+</b>',
               rf'\g<1><b>{kpi["n_stock"]:,}</b>', h)
    h = re.sub(r'(<span>申万三级行业</span>)<b>\d+</b>', rf'\g<1><b>{kpi["n_ind"]}</b>', h)
    h = re.sub(r'(<span>质量Top28组合持仓</span>)<b>\d+</b>', rf'\g<1><b>{kpi["n_hold"]}</b>', h)

    # ---- ② 二章整体重建
    a = h.find('<h2>二、季度股池')
    b = h.find('<h2>三、组合回测')
    assert a > 0 and b > a, "找不到二/三章边界"
    h = h[:a] + sec_pools(P) + "\n" + h[b:]

    # ---- ③ 三章
    a = h.find('<h2>三、组合回测')
    b = h.find('<h2>四、CSFM 和 TSFM')
    seg = h[a:b]

    # 说明文字：起点、CSFM/TSFM 参数、基准
    seg = seg.replace("回测自 <b>2019-05-06</b> 起。",
                      f'回测自 <b>{meta["start"]}</b> 起（因子动量需 12 个月因子收益做动量，'
                      f'2015-01 尚无有效动量，故首个决策日为 2015-02-27；'
                      f'六条曲线统一在该日归一到 1.00）。')
    seg = seg.replace(
        '取当期股池内得分最高的 <b>30 只等权持有、月度调仓</b>',
        '取当期股池内得分最高的 <b>CSFM 20 只 / TSFM 30 只等权持有、月度调仓</b>')
    seg = seg.replace(
        '个股得分 = Σ（因子动量权重 × 个股标准化暴露）/ √10',
        '个股得分 = Σ（因子动量权重 × 个股标准化暴露）/ √10')
    seg = seg.replace(
        '对比基准</b>：沪深300、创业板50、科创50 三个宽基指数；',
        '对比基准</b>：沪深300、中证500、创业板50 三个宽基指数'
        '（沪深300 与中证500 合成中证800，正是本页标的池的两半）；')
    # 注意：原文里的 "< 5,000" 是裸小于号，浏览器按文本处理，但正则抽文本时会被当成标签开头。
    # 重写这段时统一用 &lt; 转义，避免不同解析器下被吞掉半句。
    seg = seg.replace(
        '权重按 v2 三道筛分配：剔除 20 日均成交额 < 5,000 万元的标的，按换手率代理＝20 日均成交额÷总市值 剔除最拥挤的 1/3，余者 ∝ 1/(换手分位+0.15)、单只限幅 2%~8%）',
        '行业上限 2 只；剔除 20 日均成交额 &lt; 5,000 万元的标的；'
        '余者按 20 日换手率反向加权，权重 ∝ 1/(1 + 换手率/当期中位数)）')
    # κ 门控说明（CSFM 用 1.5、TSFM 用 1.0），插在 CSFM/TSFM 段末尾的"注意"前
    if 'F 反馈强度' not in seg:
        seg = seg.replace('。<b>注意</b>',
                          '。CSFM 与 TSFM 均叠加 <b>F 反馈强度门控</b>：'
                          '把 10 个因子的「24 个月自相关」与「12 个月趋势 R²」合成拥挤度分位 F，'
                          '因子权重乘以 (1 − κ·F)，κ=0 即不门控、κ 越大越回避拥挤因子；'
                          '实测 κ 从 0 提到 1.5 波动降 9%~14%，故 CSFM 取 κ=1.5，'
                          'TSFM 因权重本身较薄取 κ=1.0。<b>注意</b>')

    # 静态表
    seg = re.sub(r'<tbody>.*?</tbody>', sec_bt_table(perf), seg, count=1, flags=re.S)
    # BT
    bt_json = json.dumps(bt, ensure_ascii=False, separators=(",", ":"))
    seg = re.sub(r'var BT=\{.*?\};;', lambda m: f'var BT={bt_json};;', seg, count=1, flags=re.S)
    # 时间轴刻度 / 滑块 / 底部日期行
    seg = re.sub(r'<div class="rng-ticks">.*?</div>',
                 f'<div class="rng-ticks">{ticks(bt["dates"])}</div>', seg, count=1, flags=re.S)
    M = len(bt["dates"]) - 1
    seg = seg.replace('max="1802"', f'max="{M}"').replace('value="1802"', f'value="{M}"')
    seg = re.sub(r'(<span class="rng-txt" id="btTxt">)[^<]*(</span>)',
                 rf'\g<1>{bt["dates"][0]} → {bt["dates"][-1]} · {len(bt["dates"])} 个交易日\g<2>', seg)
    seg = seg.replace('全部（19-11 起）', '全部')
    seg = seg.replace('<text fill="#374151" font-size="12" font-weight="400" x="806" y="178">科创50</text>',
                      '<text fill="#374151" font-size="12" font-weight="400" x="806" y="178">中证500</text>')
    seg = seg.replace('stroke="#8e44ad"', 'stroke="#3d6fb5"')
    h = h[:a] + seg + h[b:]

    # ---- ④ 四章 var POS + 当前仓位
    pos_json = json.dumps(pos, ensure_ascii=False, separators=(",", ":"))
    h = re.sub(r'var POS=\{.*?\};', lambda m: f'var POS={pos_json};', h, count=1, flags=re.S)
    h = re.sub(r'(CSFM 建议仓位（当前 )\d+%', rf'\g<1>{pos["csfm"][-1]}%', h)
    h = re.sub(r'(TSFM 建议仓位（当前 )\d+%', rf'\g<1>{pos["tsfm"][-1]}%', h)

    # ---- ⑤ 五章三个 tbody
    marks = ["5.1　因子动量·横截面 CSFM", "5.2　因子动量·时间序列 TSFM",
             "5.3　质量Top28组合", "六、如何更新最新一季股池"]
    keys = ["CSFM", "TSFM", "Q28"]
    for i, k in enumerate(keys):
        s0 = h.find(marks[i])
        s1 = h.find(marks[i + 1])
        assert 0 < s0 < s1, f"找不到 {marks[i]}"
        seg = h[s0:s1]
        seg = re.sub(r'<tbody>.*?</tbody>', sec_recent(recent[k], k), seg, count=1, flags=re.S)
        # 摘要行与表头都写着「持仓 N 只」，两处都要改
        seg = re.sub(r'持仓 \d+ 只', f'持仓 {len(recent[k][0]["hold"])} 只', seg)
        h = h[:s0] + seg + h[s1:]

    # 五章标题里的期数说明保持"8 期"，但把 5.3 的持仓数同步
    # 版式标记：refresh_page.py 见到它就交棒（结构与 v3 相同，只能靠显式标记区分）
    h = h.replace("<body>", "<body><!--page-engine:finchain-v5-->", 1)

    out = os.path.join(OUT, "pool_page_v5.html")
    open(out, "w", encoding="utf-8").write(h)
    print(f"✓ {out}  {len(h.encode())/1e6:.2f} MB")
    return out


if __name__ == "__main__":
    build()
