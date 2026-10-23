# -*- coding: utf-8 -*-
"""在原版版式上替换内容（不改任何 UI 细节）。

输入：data/page_base.html（原版页面）+ out15/page_content.json（新数据）
输出：out15/pool_page_v5.html

只做四件事：
  ① 说明文字里过期的口径（回测起点、持仓数、基准、v2 权重规则、报告期范围、KPI）
  ② 二、季度股池明细：35 期新池（沿用原 .card/.ind/.mini 结构）
  ③ 三、组合回测：var BT 换成 2017-2026 逐日净值 + 静态表 + 时间轴刻度
  ④ 四、仓位建议（var POS，按新净值重算）+ 五、持仓变动明细（最近 8 期）
  ⑤ 七、市场情绪展望：研报目标价 + 情绪拆解（片段来自 data/mood_block.html）
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

# 股池口径：申万三级行业各取 FAQ 评分前 N 只（与 build_pools_v5.py 的 TOPN 一致）
TOPN_IND = 3
MCAP_MIN = 300  # 亿元


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

    return (f'<h2>二、季度股池（申万三级行业各取前 {TOPN_IND}，不足 {TOPN_IND} 只不补入）</h2>\n'
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


def sec_recent(rows, kind, fancy=False):
    """五、持仓变动明细的单组合 tbody

    三个组合统一版式（2026-10-19 起）：
      · 每条「名称 + 权重」用不可断行容器 <span class="it"> 包住，条目之间用「、」分隔，
        与「本期剔除」列完全同构，避免名称与百分比被拆到两行、整格糊成一片。
      · 5.3 质量组合（fancy=True）另在三个单元格末尾各带一行 <span class="cnt"> 小字副行
        （决策日 / 「N 只 · 新增 M」/「K 只」）。
    """
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
        dec = r.get("dec") or r["date"]
        cnt = (f'<span class="cnt">{dec}</span>') if fancy else ""
        head = f'<td class="day">{r["date"]}{pos}{nav}{latest}{cnt}</td>'

        items = [f'<span class="it"><span class="{"nm-new" if h["new"] else "nm"}">'
                 f'{esc(h["n"])}</span><span class="wt">{h["w"]*100:.2f}%</span></span>'
                 for h in r["hold"]]
        hold = "、".join(items)
        if fancy:
            n_new = sum(1 for h in r["hold"] if h["new"])
            tail = f'{len(r["hold"])} 只' + (f' · 新增 {n_new}' if n_new else "")
            hold += f'<span class="cnt">{tail}</span>'

        outs = []
        for o in r["out"]:
            r_txt = ('<span class="mut">—</span>' if o["r"] is None else
                     f'<span class="{"up" if o["r"] >= 0 else "dn"}">{o["r"]*100:+.2f}%</span>')
            outs.append(f'<span class="it"><span class="nm-out">{esc(o["n"])}</span>'
                        f'<span class="join">建仓 {o["e"] or "—"}</span>{r_txt}</span>')
        if outs:
            out_cell = "、".join(outs)
            if fancy:
                out_cell += f'<span class="cnt">{len(r["out"])} 只</span>'
        else:
            out_cell = '<span class="mut">无</span>'
            if fancy:
                out_cell += '<span class="cnt">0 只</span>'
        body.append(f'<tr>{head}<td class="cell">{hold}</td>'
                    f'<td class="cell">{out_cell}</td></tr>')
    return "<tbody>" + "".join(body) + "</tbody>"



def ticks(dates):
    ys = []
    for y in range(int(dates[0][:4]) + 1, int(dates[-1][:4]) + 1):
        k = next((i for i, d in enumerate(dates) if d >= f"{y}-01-01"), None)
        if k is None:
            continue
        ys.append((y, k / (len(dates) - 1) * 100))
    return "".join(f'<span style="left:{p:.2f}%">{y}</span>' for y, p in ys)


# ---------------- 顶部「得分 / 仓位建议」卡片 ----------------
# 2026-10-19 页面重构时被整张删掉，本次按原样还原（位置＝KPI 行末尾第 6 张）。
# 数值优先跟随 out15/bscore_card.json（B-score 链路每天写入则自动更新），
# 没有该文件时用最近一次快照（2026-10-16：CB 0.559 → 建议仓位 50%）。
BSCORE_JSON = os.path.join(str(OUT), "bscore_card.json")
BSCORE_SNAPSHOT = {"pos": 50, "cb": "0.559", "asof": "2026-10-16"}


def bscore_card():
    v = dict(BSCORE_SNAPSHOT)
    if os.path.exists(BSCORE_JSON):
        try:
            v.update({k: x for k, x in json.load(open(BSCORE_JSON, encoding="utf-8")).items()
                      if x not in (None, "")})
        except Exception as e:  # 数据文件坏了不阻断出图，退回快照
            print(f"  ! bscore_card.json 读取失败（{e}），用快照值", flush=True)
    return ('<div class="kpi"><span>B-score 建议仓位</span>'
            f'<b>{int(v["pos"])}%</b>'
            '<span class="afgi-bd" style="display:inline-block; background:#fff7ed; '
            'color:#b45309; border-radius:999px; padding:1px 9px; font-size:12px; '
            f'font-weight:600">CB {v["cb"]}</span>'
            f'<span style="display:block; margin-top:3px">截至 {v["asof"]}</span></div>')


def insert_kpi_card(h, card_html):
    """把卡片塞进 <div class="kpis"> 的末尾（按 div 配平找闭合点，不用贪婪正则）"""
    tag = '<div class="kpis">'
    i = h.find(tag)
    assert i > 0, "找不到 KPI 行"
    j = i + len(tag)
    depth = 1
    for m in re.finditer(r"<div\b|</div>", h[j:]):
        depth += 1 if m.group(0).startswith("<div") else -1
        if depth == 0:
            k = j + m.start()
            return h[:k] + card_html + h[k:]
    raise AssertionError("KPI 行未闭合")


# ---------------- 五章：持仓 / 剔除两列版式 ----------------
# 诉求：① 两列等宽；② 每条持仓不得在「名称」与「百分比」之间被拆行
#      （原来 span 直接相连，浏览器可在任意位置断行，出现「提前换行」）。
TBL_CSS = """
/* 2026-10-19 五章版式修复：两列等宽 + 条目内不断行 */
.tbl5{table-layout:fixed}
.tbl5 .c-hold,.tbl5 .c-out{width:auto}
.tbl5 .cell .it{display:inline-block;white-space:nowrap;margin:0 1px}
.tbl5 .cell .wt{margin-left:2px}
.tbl5 .cell .join{margin:0 4px}
@media(max-width:640px){.grid,.strategy-grid{grid-template-columns:1fr}}
"""


def inject_tbl_css(h):
    i = h.find("</style>")
    assert i > 0, "找不到 </style>"
    return h[:i] + TBL_CSS + h[i:]


# ---------------- 七章：市场情绪展望 ----------------
# 研报目标价与情绪研判无法自动抓取，属于「人工核验后固化的快照」：
# data/mood_q28.json（结构化数据）→ build_mood_block.py 渲染 → data/mood_block.html。
# 换期时重跑 build_mood_block.py 即可，本函数只负责把片段塞到页脚之前。
MOOD_BLOCK = os.path.join(DATA, "mood_block.html")
MOOD_BEGIN = "<!--MOOD-SEC-BEGIN-->"
MOOD_END = "<!--MOOD-SEC-END-->"
MOOD_CSS_BEGIN = "/*MOOD-CSS-BEGIN*/"
MOOD_CSS_END = "/*MOOD-CSS-END*/"


def strip_mood(h):
    """摘掉已存在的七章正文与样式。返回 (html, 被摘掉的 CSS 文本或 None)。

    为什么要连 CSS 一起摘：cloud/seed_page_base.py --force 会把**线上页面**
    重新拉回来当模板，而线上页面是含七章的。只摘正文不摘样式，样式就会
    每 seed 一次叠一份。
    """
    while MOOD_BEGIN in h:
        a = h.find(MOOD_BEGIN)
        b = h.find(MOOD_END, a)
        if b < 0:
            break
        h = h[:a] + h[b + len(MOOD_END):]
    css = None
    a = h.find(MOOD_CSS_BEGIN)
    if a >= 0:
        b = h.find(MOOD_CSS_END, a)
        if b > a:
            css = h[a + len(MOOD_CSS_BEGIN):b]
            h = h[:a] + h[b + len(MOOD_CSS_END):]
    return h, css


def insert_mood_block(h):
    """插到六章之后、页脚说明之前。幂等：重复执行不会叠加。

    片段头部的 <style> 会被摘出来并入主样式表（避免 body 中间出现 style 标签），
    其余 HTML 落到正文。
    """
    h, _ = strip_mood(h)                       # 先清旧块（换期重跑 / 模板被污染时）
    if not os.path.exists(MOOD_BLOCK):
        print("  · 跳过七章（缺 data/mood_block.html，先跑 build_mood_block.py）", flush=True)
        return h
    blk = open(MOOD_BLOCK, encoding="utf-8").read().strip()

    m = re.match(r"\s*<style[^>]*>([\s\S]*?)</style>\s*", blk)
    if m:
        blk = blk[m.end():]
        end = h.find("</style>")
        assert end > 0, "找不到 </style>"
        h = h[:end] + m.group(1).strip() + "\n" + h[end:]

    foot = '<p class="muted" style="margin-top:26'
    k = h.find(foot)
    if k < 0:                                  # 兜底：插在 </body> 前
        k = h.rfind("</body>")
        assert k > 0, "找不到页脚，无法插入七章"
    return h[:k] + f"\n{MOOD_BEGIN}\n{blk}\n{MOOD_END}\n" + h[k:]


def build():
    h = clean(open(TPL, encoding="utf-8").read())
    D = json.load(open(os.path.join(OUT, "page_content.json"), encoding="utf-8"))
    P, bt, perf, pos, recent, kpi, meta = (D["periods"], D["bt"], D["perf"], D["pos"],
                                           D["recent"], D["kpi"], D["meta"])

    # ---- ① 头部说明与 KPI
    h = h.replace("报告期：2019年一季报 → 2026年中报",
                  f'报告期：{P[0]["label"]} → {P[-1]["label"]}')
    # 标的池口径：原句是「动态中证800 成分股…不再设市值门槛、不再纳入中证1000」，
    # 与现行口径正好相反，必须整段换掉，不能只改数字。
    h = h.replace(
        "标的池：动态 中证800 成分股（沪深300 ∪ 中证500），随指数成分定期调整，"
        "不再设市值门槛、不再纳入中证1000",
        f"标的池：全市场总市值 ≥ {MCAP_MIN} 亿元的个股（每期调仓前按当期总市值重算，"
        f"不看指数成分归属）")
    reps = [("<b>评分报告期</b>".replace("<b>", ""), None)]
    h = re.sub(r'(<span>评分报告期</span>)<b>\d+</b>', rf'\g<1><b>{kpi["n_period"]}</b>', h)
    h = re.sub(r'(<span>股池覆盖个股\(并集\)</span>)<b>[\d,]+</b>',
               rf'\g<1><b>{kpi["n_stock"]:,}</b>', h)
    h = re.sub(r'(<span>申万三级行业</span>)<b>\d+</b>', rf'\g<1><b>{kpi["n_ind"]}</b>', h)
    # 三道筛落地后每期不再是 28 只，标签补「(筛后)」免得误读
    h = h.replace("<span>质量Top28组合持仓</span>", "<span>质量Top28组合持仓(筛后)</span>")
    h = re.sub(r'(<span>质量Top28组合持仓\(筛后\)</span>)<b>\d+</b>',
               rf'\g<1><b>{kpi["n_hold"]}</b>', h)

    # ---- ①b 顶部还原「得分 + 仓位建议」卡片（2026-10-19 被误删） ----
    h = insert_kpi_card(h, bscore_card())
    # ---- ①c 五章两列版式修复 ----
    h = inject_tbl_css(h)

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
                      f'回测自 <b>{meta["start"]}</b> 起（2017-01-01 为元旦非交易日，'
                      f'取 2017 年首个交易日为净值基准日；期初持仓沿用前一调仓日的结果，'
                      f'因子动量所需的 12 个月历史收益在窗口外预热、不参与统计；'
                      f'六条曲线统一在该日归一到 1.00）。'
                      f'<b>2015-2016 不计入业绩</b>：该区间含三轮股灾、2016 年首日熔断与'
                      f'千股停牌，调仓日大量标的无法成交、停牌权重一度达 25%，'
                      f'收益分布极端且不可复制，计入会让「组合本身好不好」失真。')
    seg = seg.replace(
        '取当期股池内得分最高的 <b>30 只等权持有、月度调仓</b>',
        '取当期股池内得分最高的 <b>CSFM 20 只 / TSFM 30 只等权持有、月度调仓</b>')
    seg = seg.replace(
        '个股得分 = Σ（因子动量权重 × 个股标准化暴露）/ √10',
        '个股得分 = Σ（因子动量权重 × 个股标准化暴露）/ √10')
    seg = seg.replace(
        '对比基准</b>：沪深300、创业板50、科创50 三个宽基指数；',
        '对比基准</b>：沪深300、中证500、创业板50 三个宽基指数；')
    # 原句尾巴写着「沪深300 与中证500 合成中证800，正是本页标的池的两半」。
    # 现行标的池只看市值、与指数成分无关，这句必须删，否则自相矛盾。
    seg = seg.replace('（沪深300 与中证500 合成中证800，正是本页标的池的两半）', '')
    # 注意：原文里的 "< 5,000" 是裸小于号，浏览器按文本处理，但正则抽文本时会被当成标签开头。
    # 重写这段时统一用 &lt; 转义，避免不同解析器下被吞掉半句。
    # 2026-10-19：v2 三道筛已在 daily_nav15.quality_picks 真正落地，这段说明恢复原口径，
    # 只补一句「筛后剩多少只」，免得读者以为仍是固定 28 只。
    seg = seg.replace(
        '权重按 v2 三道筛分配：剔除 20 日均成交额 < 5,000 万元的标的，按换手率代理＝20 日均成交额÷总市值 剔除最拥挤的 1/3，余者 ∝ 1/(换手分位+0.15)、单只限幅 2%~8%）',
        '权重按 v2 三道筛分配：先按得分降序、单行业 ≤2 只取满 28 只候选，'
        '再剔除 20 日均成交额 &lt; 5,000 万元的标的，按换手率代理＝20 日均成交额÷总市值 '
        '剔除最拥挤的 1/3，余者 ∝ 1/(换手分位+0.15)、单只限幅 2%~8%；'
        '因此实际持仓 = 三道筛后的存活数，近年多在 18~22 只，不再固定 28 只）')
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
    # 5.3 的选股说明：候选是「取满 28 只」，实际持仓是三道筛后的存活数
    h = h.replace("当期股池内按舞弊调整质量因子得分降序取前 28 只",
                  "当期股池内按舞弊调整质量因子得分降序取满 28 只候选")
    h = h.replace("（取代原「前 3 名各 16%」）</b>",
                  "（取代原「前 3 名各 16%」）；三道筛后通常剩 18~22 只，"
                  "KPI 与各期表头写的都是筛后实际持仓数</b>")
    marks = ["5.1　因子动量·横截面 CSFM", "5.2　因子动量·时间序列 TSFM",
             "5.3　质量Top28组合", "六、如何更新最新一季股池"]
    keys = ["CSFM", "TSFM", "Q28"]
    for i, k in enumerate(keys):
        s0 = h.find(marks[i])
        s1 = h.find(marks[i + 1])
        assert 0 < s0 < s1, f"找不到 {marks[i]}"
        seg = h[s0:s1]
        seg = re.sub(r'<tbody>.*?</tbody>',
                     lambda m, k=k: sec_recent(recent[k], k, fancy=(k == "Q28")),
                     seg, count=1, flags=re.S)
        # 摘要行与表头都写着「持仓 N 只」，两处都要改（表头是「本期持仓（N 只）」）
        n_now = len(recent[k][0]["hold"])
        seg = re.sub(r'持仓 \d+ 只', f'持仓 {n_now} 只', seg)
        seg = re.sub(r'本期持仓（\d+ 只）', f'本期持仓（{n_now} 只）', seg)
        h = h[:s0] + seg + h[s1:]

    # ---- ⑥ 六章「如何更新最新一季股池」的流程说明
    h = h.replace(
        "拉取最新一期三大报表（标的池为动态中证800成分股，随指数成分定期调整）。",
        f"拉取最新一期三大报表（标的池为全市场总市值 ≥ {MCAP_MIN} 亿元的个股，"
        f"每期调仓前按当期总市值重算，不看指数成分归属）。")
    h = h.replace(
        "按申万三级行业取评分前 5，生成新一期股池并写入本页。",
        f"按申万三级行业取评分前 {TOPN_IND}，生成新一期股池并写入本页。")

    # ---- ⑦ 七章「市场情绪展望」：研报目标价 + 情绪拆解（人工核验快照）
    h = insert_mood_block(h)

    # 版式标记：refresh_page.py 见到它就交棒（结构与 v3 相同，只能靠显式标记区分）
    h = h.replace("<body>", "<body><!--page-engine:finchain-v5-->", 1)

    out = os.path.join(OUT, "pool_page_v5.html")
    open(out, "w", encoding="utf-8").write(h)
    print(f"✓ {out}  {len(h.encode())/1e6:.2f} MB")
    return out


if __name__ == "__main__":
    build()
