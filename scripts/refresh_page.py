# -*- coding: utf-8 -*-
"""
页面「就地刷新」 —— 以已发布页面为模板，只重建数据驱动区域，每日自动重算。

为什么不是从头重新生成整个页面
------------------------------
资料库上已发布的页面里，含有本地 gen_page.py / backtest.py 目前产不出来的内容：
  * 「质量Top28组合 / 盈利能力Top40」等线上增量加进来的曲线与章节；
  * 第三节「可拖动时间轴 + 8 行统计表 + AFGI 仓位组合」等一整套交互式改造。
一旦用 gen_page.py 全量重生成，这些内容会被不可逆地抹掉。
所以改为「就地刷新」：保留模板的一切静态/富文本内容，只把下面 6 处数据区换掉。

每日重建的区域
--------------
  1) <script> 里的 var BT = {...}          —— 净值数据源（7 条曲线；AFGI粉线已下线，见下）
  2) <svg id="btChart">…</svg>             —— 静态兜底图（脚本被禁用时仍可见）
  3) 统计表 <td id="r{i}_{c}">             —— 区间统计数值（脚本加载后会再次重算）
  4) 时间轴控件 max / 区间文案              —— 随交易日数增长
  5) AFGI 说明段里的重定基系数「（2.53）」  —— 随净值变动（AFGI 粉线下线后不再触发）
  6) 4.1 持仓变动表 <tbody>                —— 权重 .wt + 调仓日下方仓位 .pos

序列口径（重要）
----------------
  * 有本地净值来源的组合（动量轮动策略、质量Top28组合、盈利能力Top40、三大宽基、等权组合）：
    历史沿用「模板里的已发布数值」，新增交易日按本地净值日收益外推 —— 保证线上已展示的
    历史数字不跳变，同时每天向下延伸。
  * AFGI仓位（粉线）已于 2026-10-08 从页面下线，当前线上版本不含该曲线。
    仅当模板里仍然存在 AFGI仓位 这条 key 时，才由 scripts/afgi_pos.py 实时重算
    （冻结历史 + 尾部增量）并乘以「2023-02-09 当日动量轮动策略净值」做图上定基；
    模板里没有就整段跳过，不调用 afgi_pos，也不做该组合的回测。

用法
----
    python scripts/refresh_page.py                 # 就地刷新 → data/pool_page.html
    python scripts/refresh_page.py --check         # 只做结构自检，不写文件
    python scripts/refresh_page.py --base X.html   # 指定模板文件
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import os
import re
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 路径统一由 paths.py 解析（本机 Windows 与云端 Linux 通用，支持环境变量覆盖）
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
from paths import BASE as ROOT, DATA, PROF_DIR  # noqa: E402

import afgi_pos as AP  # noqa: E402

BASE_FILE = os.path.join(DATA, "page_base.html")      # 模板（= 上一次发布成功的产品）
OUT_FILE = os.path.join(DATA, "pool_page.html")       # 输出（交给 import_html.py 上传）

NAV_FILE = os.path.join(DATA, "nav.csv")
HOLD_FILE = os.path.join(DATA, "holdings.csv")
RM_FILE = os.path.join(DATA, "removed.csv")
QUAL_FILE = os.path.join(DATA, "quality_top28.csv")
QUAL_RM_FILE = os.path.join(DATA, "quality_removed.csv")

# 盈利能力 Top40 组合由另一个项目（work/prof）产出，本地 nav.csv 不含该列；
# 这里直接读它的净值文件，供全量重算与日常延伸使用（文件缺失则退化为冻结）。
PROF_NAV_FILE = os.path.join(PROF_DIR, "prof", "prof_nav.csv")
EXTRA_NAV = {"盈利能力Top40": PROF_NAV_FILE}

N_SHOW_MOM = 8          # 4.1 展示期数，与线上保持一致（版本57 起为最近 8 个调仓日）
N_SHOW_QUAL = 8         # 4.2 质量 Top28 展示期数，与线上保持一致
L_MOM = 50              # 4.1 动量轮动每期持仓只数（2026-10-10 改版：12 → 50）

# 回测展示起点。2026-10-10 改版后 nav.csv 从 2019-05-06 起算，
# 模板里 BT.dates[0] 仍是旧的 2019-11-01，这里显式覆盖，否则前 5 个月会被裁掉。
PAGE_START = "2019-05-06"

# 组合更名（2026-10-08 改版）：整页字符串替换，幂等（替换后第二次运行无命中）
RENAMES = [
    ("盈利能力Top20等权", "盈利能力Top40"),
    # 「质量Top20等权组合」要先于「质量Top20等权」替换，否则会变成「质量Top28组合组合」
    ("质量Top20等权组合", "质量Top28组合"),
    ("质量Top20等权", "质量Top28组合"),
    ("质量 Top20 等权组合", "质量Top28组合"),
    ("质量 Top20 8 期", "质量 Top28 8 期"),
]

# 模板的序列 key → 本地 nav.csv 列（None = 本地无法重算，保持冻结）
LOCAL_COLS = {
    "策略": "策略",
    "动量轮动策略（等权）": "动量轮动策略（等权）",
    "质量Top28组合": "质量Top28组合",
    "沪深300": "沪深300",
    "创业板50": "创业板50",
    "科创50": "科创50",
}

# 页面上「动量×AFGI稳健联合」曲线在 var BT= 里的序列键。
# 2026-10-08 改版后线上键名为「联合仓位」，旧版本是「AFGI仓位」；
# 两者都必须识别，否则该曲线会因键名不匹配被整段跳过、悄悄冻结在旧日期。
AFGI_KEYS = ("联合仓位", "AFGI仓位")
AFGI_KEY = AFGI_KEYS[0]
INCEPTION = AP.INCEPTION          # 2023-02-09

# ── 调仓明细模块（4.1 / 4.2 / 4.3）──────────────────────────────────
# 「较上期 ±x.xx%」＝本组合净值相对上一调仓日的区间涨跌幅，取各组合自己的净值列：
#   4.1 动量轮动 → nav.csv「策略」；4.2 质量 Top28 → nav.csv「质量Top28组合」；
#   4.3 盈利能力 Top40 由该 project 自己生成，本脚本只同步<｜hy_place▁holder▁no▁813｜>样式，不改数值。
NAV_COL_41 = "策略"
NAV_COL_42 = "质量Top28组合"

# AFGI 状态徽章配色（五档，阈值同 afgi/config.py 的 STATE_BANDS）
AFGI_BADGE = {
    "极度恐惧": ("#dcfce7", "#14532d"),
    "恐惧":     ("#dcfce7", "#166534"),
    "中性":     ("#fef3c7", "#92400e"),
    "贪婪":     ("#fee2e2", "#b91c1c"),
    "极度贪婪": ("#fecaca", "#7f1d1d"),
    "未知":     ("#f3f4f6", "#6b7280"),
}


def resolve_afgi_key(order):
    """按优先级返回模板里真实存在的 AFGI 序列键；都没有则返回 None。"""
    for k in AFGI_KEYS:
        if k in order:
            return k
    return None

# SVG 几何参数，必须与页面脚本 draw() 完全一致
W0, W1, TOP, BOT = 56, 770, 24, 306

LOG: list = []


def log(msg):
    print(msg, flush=True)
    LOG.append(str(msg))


# ── 通用字符串/HTML 工具 ─────────────────────────────────────────────
def read_text(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_text(path, s):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def json_span(s, i):
    """给定 'var BT=' 起始下标 i，返回 JSON 对象 (body_start, end_after_brace)。"""
    j = s.index("{", i)
    depth, k, in_str, esc = 0, j, False, False
    while k < len(s):
        ch = s[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return j, k + 1
        k += 1
    raise RuntimeError("JSON 对象未闭合")


def tag_span(s, tag_re, start=0):
    """找到标签起点与其 '>' 的位置：返回 (open_start, open_end)。"""
    m = re.compile(tag_re).search(s, start)
    if not m:
        raise RuntimeError("未找到标签：" + tag_re)
    return m.start(), m.end()


def inner_span(s, tag_re, start=0):
    """返回某标签的内部区间 (content_start, content_end)；content_end 为 </tag 起点。"""
    m = re.compile(tag_re).search(s, start)
    if not m:
        raise RuntimeError("未找到标签：" + tag_re)
    tag = m.group(0).lstrip("<").split()[0].rstrip(">")
    close = re.compile(r"</%s\s*>" % re.escape(tag)).search(s, m.end())
    if not close:
        raise RuntimeError("未找到闭合标签：" + tag)
    return m.end(), close.start()


def replace_once(s, pattern, new, flags=0, name=""):
    rx = re.compile(pattern, flags)
    m = rx.search(s)
    if not m:
        raise RuntimeError("替换失败（%s）：%s" % (name or pattern[:40], pattern[:60]))
    repl = new(m) if callable(new) else new
    return s[:m.start()] + repl + s[m.end():]


def set_by_id(s, ident, text, name=""):
    """设置带 id 的元素文本，兼容平台注入的 <!--pnid:xxx--> 注释。"""
    return replace_once(s,
                        r'(<[a-z]+[^>]*\bid="%s"[^>]*>)(?:<!--[^>]*-->)?([^<]*)(</[a-z]+>)'
                        % re.escape(ident),
                        lambda m: m.group(1) + text + m.group(3),
                        name=name or ident)


def esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ── 1.5) 组合更名 + 规则文案（改版一次，幂等）───────────────────────
def apply_renames(html):
    """整页字符串更名：质量Top20等权 → 质量Top28组合、盈利能力Top20等权 → 盈利能力Top40。"""
    n = 0
    for old, new in RENAMES:
        c = html.count(old)
        if c:
            html = html.replace(old, new)
            n += c
            log("  · 更名 %s → %s（%d 处）" % (old, new, c))
    return html


def _replace_block(html, start, open_re, new_inner, name=""):
    """从 start 起找到第一个匹配 open_re 的元素，替换其内部内容。"""
    m = re.compile(open_re).search(html, start)
    if not m:
        raise RuntimeError("未找到区块：" + (name or open_re[:60]))
    tag = m.group(0).lstrip("<").split()[0].rstrip(">")
    close = re.compile(r"</%s\s*>" % re.escape(tag)).search(html, m.end())
    if not close:
        raise RuntimeError("未找到闭合标签：" + tag)
    return html[:m.end()] + new_inner + html[close.start():]


def update_rule_texts(html):
    """按 2026-10-08 改版后的调仓规则，改写三处说明文案。全部按唯一锚点定位，幂等。"""
    # ① 第三节：质量 Top28 选股 / 权重规则
    html = html.replace("舞弊调整质量因子得分降序取前 20 只",
                        "舞弊调整质量因子得分降序取前 28 只")
    html = html.replace("重新等权建仓；换仓同样权重滞后 1 日",
                        "重新建仓（排名前 3 名各 16%、其余 25 只各 2.08%）；"
                        "换仓同样权重滞后 1 日")
    html = html.replace("换仓并等权建仓", "换仓建仓")

    # ② 第三节：AFGI 仓位管理组合说明段（整段重写）
    mark = "AFGI 仓位管理组合"
    i = html.find(mark)
    if i >= 0:
        p0 = html.rfind("<p ", 0, i)
        if p0 < 0:
            raise RuntimeError("未定位 AFGI 说明段 <p>")
        pe = html.find("</p>", i)
        new_inner = (
            "<b>AFGI 仓位管理组合</b>（粉线）：选股与调仓与动量轮动策略完全一致，"
            "仅在其上叠加一个总仓位系数。<br><br>"
            "<b>1）目标权益仓位</b>：读取调仓日 t 的情绪指数 <b>AFGI</b> 数值 S"
            "（0~100，越高越贪婪），"
            "<b>P = 70% × clip((S − 40) / (80 − 40), 0, 1)</b>"
            " —— <b>S ≤ 40</b>（恐惧区及以下）→ <b>空仓</b>，全部持有现金；"
            "<b>S = 60</b>（中性偏贪婪）→ <b>35%</b>；<b>S ≥ 80</b>（极度贪婪）→ <b>70%</b> 上限。"
            "即：情绪越热仓位越高，情绪转冷立即降仓 —— 右侧顺势，不做逆势抄底。<br><br>"
            "<b>逐日扫描触发，于下一个调仓日生效</b>；调仓日之间不随情绪波动调整仓位。"
            "该组合自 AFGI 数据起点 <b>2023-02-09</b> 起算，起始仓位 <b>100%</b>，"
            "故其统计区间为 2023-02-09 至今。为便于与动量轮动策略直接比较，图中该曲线已按 "
            "<b>2023-02-09 当日动量轮动策略净值（2.53）</b> 定基，即两条曲线在该点"
            "（空心圆标记处）重合后开始分叉；定基只影响曲线纵坐标，不影响统计表中的收益率。")
        html = html[:p0] + "<p class=\"note\" style=\"margin-top:12px\">" \
            + new_inner + html[pe:]
        log("  · AFGI 仓位规则说明段已重写")
    return html


# ── 1) 重算净值序列 ─────────────────────────────────────────────────
def read_table_order(html, bt):
    """
    统计表的行也许与 BT.order 不同序（线上产物曾出现过：质量盈利/质量Top20 两行颠倒，
    导致 JS 按 BT.order 写回 r{i}_{c} 时张冠李戴）。这里以「表格实际行顺序」为准，
    用表首列文字反查出对应的序列 key，返回与表格一致的 order。
    """
    label2key = {}
    for k, lab in bt["label"].items():
        label2key.setdefault(lab, k)
    i = html.find("累计收益")
    if i < 0:
        return list(bt["order"])
    seg = html[i - 400: i + 40000]
    keys = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, flags=re.S) [:20]:
        cells = re.findall(r"<(?:td|th)[^>]*>(.*?)</(?:td|th)>", tr, flags=re.S)
        if len(cells) < 7:
            continue
        txt = htmllib.unescape(re.sub(r"<[^>]+>", "", cells[0]).strip())
        key = label2key.get(txt)
        if key and key not in keys:
            keys.append(key)
    if set(keys) != set(bt["order"]) or len(keys) != len(bt["order"]):
        return list(bt["order"])
    return keys


def load_extra_nav():
    """本地 nav.csv 之外的净值来源（盈利能力 Top40），{key: Series}。"""
    out = {}
    for key, path in EXTRA_NAV.items():
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, index_col=0)
        df.index = pd.to_datetime(df.index).strftime("%Y-%m-%d")
        out[key] = df.iloc[:, 0].astype(float).sort_index()
    return out


def local_nav_matrix(page_start):
    """本地净值按 page_start 定基为 1.0，返回 {date: {col: value}}。"""
    nav = pd.read_csv(NAV_FILE, index_col=0)
    nav.index = pd.to_datetime(nav.index).strftime("%Y-%m-%d")
    nav = nav.loc[nav.index >= page_start].astype(float)
    base = nav.iloc[0]
    return (nav / base), list(nav.index)


def build_series(bt, start_date=None, full=False):
    """返回新的 dates 列表与 {key: [value|None]}。

    full=True（规则改版 / 全量重算）时：所有日期一律取本地 nav.csv 的净值，
    不再沿用模板里的已发布数值 —— 调仓规则变更后历史曲线必须整体重算。
    """
    bt_dates = bt["dates"]
    bt_series = bt["series"]
    # 取本地净值与模板起点中较早者，保证 2019-05-06 起的全窗口都能画出来
    page_start = min(bt_dates[0], PAGE_START) if PAGE_START else bt_dates[0]

    nav_r, nav_dates = local_nav_matrix(page_start)
    extra = load_extra_nav()
    dates = nav_dates
    last_base = bt_dates[-1]

    out = {}
    frozen = []
    extended = []

    # 外源净值（盈利能力Top40）起点可能晚于本页起点（2019-05-06），
    # 定基必须用它自己的首个可交易日，否则整条曲线会被判成 None 而消失。
    extra_base = {}
    for key, s in extra.items():
        hit = [d for d in dates if d in s.index]
        extra_base[key] = float(s.loc[hit[0]]) if hit else None

    def _full_value(key, d):
        col = LOCAL_COLS.get(key)
        if col and col in nav_r.columns:
            return float(nav_r.loc[d, col]) if d in nav_r.index else None
        s = extra.get(key)
        if s is not None and d in s.index:
            b = extra_base.get(key)
            return (float(s.loc[d]) / b) if b else None
        return None

    def _extend_value(key, d):
        """用本地（或外部）净值把序列从 last_base 延伸到 d。"""
        col = LOCAL_COLS.get(key)
        s = extra.get(key)
        if col and col in nav_r.columns:
            if last_base not in nav_r.index or d not in nav_r.index:
                return None
            return last_val * float(nav_r.loc[d, col] / nav_r.loc[last_base, col])
        if s is not None and d in s.index and last_base in s.index:
            return last_val * float(s.loc[d] / s.loc[last_base])
        return None

    for key in bt["order"]:
        arr = {d: v for d, v in zip(bt_dates, bt_series[key])}
        last_val = None
        for d in reversed(bt_dates):
            if arr[d] is not None:
                last_val = arr[d]
                last_base = d
                break
        col = LOCAL_COLS.get(key)
        new = []
        for d in dates:
            if full:
                v = _full_value(key, d)
                new.append(None if v is None or pd.isna(v) else round(v, 6))
                continue
            if d in arr and d <= last_base:
                new.append(arr[d])
                continue
            if last_val is None:
                new.append(None)
                continue
            v = _extend_value(key, d)
            new.append(None if v is None or pd.isna(v) else round(v, 6))
        out[key] = new

        n_ext = sum(1 for d, v in zip(dates, new) if d > last_base and v is not None)
        if col is None and key not in extra:
            frozen.append(key)
        elif n_ext:
            extended.append((key, n_ext))

    if start_date:
        pass  # 预留：未来若需裁切区间

    # AFGI 仓位组合：实时计算
    key_afgi = resolve_afgi_key(bt["order"])
    if key_afgi:
        raw = AP.combo_nav(extend=True)            # {date: nav}，2023-02-09 = 1.0
        strat = AP.load_strategy_nav()             # 动量策略净值，2019-11-01 = 1.0
        factor = float(strat.loc[INCEPTION])       # 图上定基系数（2.526869…）
        newkey = []
        for d in dates:
            newkey.append(round(raw[d] * factor, 6) if d in raw else None)
        out[key_afgi] = newkey
        log("  %s：%s → %s（%d 日），重定基系数 %.6f"
            % (key_afgi, INCEPTION, dates[-1], len(dates), factor))
    else:
        factor = None

    for key in frozen:
        if key == key_afgi:
            continue
        log("  ! 冻结序列（本地无对应净值，无法延伸）：%s" % key)
    for key, n in extended:
        log("  · %s 新增延伸 %d 个交易日" % (key, n))

    return dates, out, factor


# ── 1b) v3 版式（2026-10-18 起）：CSFM/TSFM + 四、仓位建议 + 质量Top28 v2 ────
# v3 页面有 7 条曲线，其中 因子动量CSFM / 因子动量TSFM / B-score组合 由别的链路
# （fmf 因子动量、b-score 择时）维护，本脚本无权改写；它只负责自己产出的
# 「质量Top28组合」。所以 v3 分支不做「以本地日期为准」的整体重建 ——
# 否则 nav.csv 比模板短时会把别人的曲线尾部截断。只做：
#   · 在模板已有日期上就地覆盖质量Top28 的净值（定基都是 1.0，口径一致）
#   · 重写统计表 r2 行、5.3 持仓表、KPI 里的持仓只数
V3_SIGNS = ('id="posChart"', "四、CSFM 和 TSFM 历史仓位建议")
# v4 = 2026-10-19 起的新结构（数据包 + 整页重绘）：没有 var BT=、没有 svg#btChart，
# 净值全靠内联 JS 现画。本脚本的所有锚点都不存在，必须交棒给 scripts/republish_page.py。
V4_SIGNS = ('id="chart"', 'id="rng"', 'var D={"curve"', "申万三级行业各取前 5")
# v5 = 原版版式 + 2015-2026 新数据（官方中证800 逐期成分口径）。
# 结构与 v3 一模一样，靠这个显式标记区分 —— 否则下面的 v3 分支会拿 pool-core
# 自己的旧净值（2019-05 起、市值拟合股池）覆盖线上曲线与持仓表。
V5_MARK = "<!--page-engine:finchain-v5-->"
V3_LOCAL_KEYS = ("质量Top28组合",)
QUAL_STAT_ROW = 2                 # 统计表里质量Top28 的行号（r2_*）
QUAL_ANCHOR_V3 = r"5\.3[\s\u3000]*质量Top28组合"
QUAL_NEXT_V3 = r"5\.4[\s\u3000]"


def detect_layout(html):
    """v4 = 数据包+整页重绘（新结构）；v3 = 含仓位建议模块；否则旧版式 v2。"""
    if V5_MARK in html:
        return "v5"
    if all(s in html for s in V4_SIGNS):
        return "v4"
    return "v3" if all(s in html for s in V3_SIGNS) else "v2"


def nav_series(col, page_start=PAGE_START):
    """nav.csv 某列 → 定基 1.0 的 Series（键 YYYY-MM-DD）。"""
    if not os.path.exists(NAV_FILE):
        return None
    nav = pd.read_csv(NAV_FILE, index_col=0)
    nav.index = pd.to_datetime(nav.index).strftime("%Y-%m-%d")
    nav = nav.loc[nav.index >= page_start].astype(float).sort_index()
    if col not in nav.columns or nav.empty:
        return None
    s = nav[col].dropna()
    if s.empty:
        return None
    return s / float(s.iloc[0])


def refresh_series_v3(bt):
    """只覆盖质量Top28 的净值；日期轴与其它 6 条曲线一律保持模板原样。"""
    dates = list(bt["dates"])
    series = {k: list(v) for k, v in bt["series"].items()}
    pos = {d: i for i, d in enumerate(dates)}
    for key in V3_LOCAL_KEYS:
        if key not in series:
            log("  ! 模板无 %s 曲线，跳过" % key)
            continue
        s = nav_series(LOCAL_COLS.get(key, key))
        if s is None:
            log("  ! %s 无本地净值列，保持模板值" % key)
            continue
        n = 0
        for d, v in s.items():
            i = pos.get(d)
            if i is None:
                continue
            series[key][i] = round(float(v), 6)
            n += 1
        newer = [d for d in dates if d > s.index[-1]]
        log("  · %s 覆盖 %d 日（本地最新 %s；模板比之新 %d 日保持原值）"
            % (key, n, s.index[-1], len(newer)))
    return dates, series


def set_qual_stat_v3(html, series):
    """统计表 r2_* 用 backtest_summary 的质量Top28 行（与其它行同口径、同批次）。"""
    vals = None
    path = os.path.join(DATA, "backtest_summary.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, encoding="utf-8-sig")
        hit = df[df["组合"].astype(str).str.strip() == "质量Top28组合"]
        if not hit.empty:
            r = hit.iloc[0]
            vals = [float(r[c]) for c in ("累计收益", "年化收益", "年化波动",
                                          "最大回撤", "夏普比率", "卡玛比率")]
    if vals is None:
        arr = series.get("质量Top28组合")
        rng = stat_range(arr) if arr else None
        if rng is None:
            log("  ! 质量Top28 无统计来源，r2 行保持原值")
            return html
        vals = calc(arr, rng[0], rng[1])
        log("  · 无 backtest_summary，r2 行改用净值序列现算")
    for ci in range(6):
        html = set_by_id(html, "r%d_%d" % (QUAL_STAT_ROW, ci), fmt_cell(ci, vals[ci]))
    log("  ✓ 统计表 r%d 行（质量Top28）← %s"
        % (QUAL_STAT_ROW, " / ".join(fmt_cell(i, vals[i]) for i in range(6))))
    return html


# ── 2) 区间统计（与页面 JS calc() 严格一致）──────────────────────────
def calc(arr, k, j):
    import math
    eq, peak, mdd, mu, sq = 1.0, 1.0, 0.0, 0.0, 0.0
    vals = []
    n = 0
    for i in range(k, j + 1):
        if i == k:
            vals.append(0.0)
        else:
            vals.append(arr[i] / arr[i - 1] - 1.0)
        n += 1
    for r in vals:
        eq *= (1 + r)
        if eq > peak:
            peak = eq
        dd = eq / peak - 1
        if dd < mdd:
            mdd = dd
        mu += r
    mu /= n
    for r in vals:
        sq += (r - mu) * (r - mu)
    vol = math.sqrt(sq / n) * math.sqrt(252)
    ann = eq ** (252.0 / n) - 1
    return [eq - 1, ann, vol, mdd,
            (ann / vol) if vol else float("nan"),
            (ann / abs(mdd)) if mdd else float("nan")]


def first_valid(arr):
    for i, v in enumerate(arr):
        if v is not None:
            return i
    return 0


def last_valid(arr, k0=0):
    """最后一个非 None 的下标。

    存在 lag 序列（外源净值晚一天、或无本地净值可延伸）时，尾部会有 None，
    统计只能算到它自己的最后一个有效点，否则 calc() 会撞上 None 而崩溃。
    """
    j = len(arr) - 1
    while j >= k0 and arr[j] is None:
        j -= 1
    return j


def stat_range(arr):
    """返回该序列连续有效区间 (首, 尾)；全空返回 None。"""
    k0 = first_valid(arr)
    j0 = last_valid(arr, k0)
    return (k0, j0) if j0 > k0 else None


def fmt_cell(ci, v):
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    return ("%.2f%%" % (v * 100)) if ci < 4 else ("%.2f" % v)


# ── 3) 静态 SVG 兜底图（复刻 JS draw() 的全区间渲染）────────────────
def render_svg(dates, order, series, color, label, afgi_key=None):
    n = len(dates)
    k, j = 0, n - 1
    vmin, vmax = float("inf"), float("-inf")
    for key in order:
        for v in series[key]:
            if v is None:
                continue
            vmin = min(vmin, v)
            vmax = max(vmax, v)
    if not (vmin < vmax):
        vmin, vmax = 0.5, 2.0
    pad = (vmax - vmin) * 0.06 or 0.1
    vmin = max(0.01, vmin - pad)
    vmax = vmax + pad

    def Y(v):
        return BOT - (v - vmin) / (vmax - vmin) * (BOT - TOP)

    def X(i):
        return W0 if j == k else W0 + (i - k) / (j - k) * (W1 - W0)

    p = []
    for g in range(5):
        y = TOP + (BOT - TOP) * g / 4
        val = vmax - (vmax - vmin) * g / 4
        p.append("<line stroke='#e6e8eb' x1='%d' x2='%d' y1='%.1f' y2='%.1f'/>"
                 % (W0, W1, y, y))
        p.append("<text fill='#6b7280' font-size='11' text-anchor='end' x='48' "
                 "y='%.1f'>%.2f</text>" % (y + 4, val))
    for key in order:
        arr = series[key]
        pts = ["%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(arr) if v is not None]
        sw = 3 if key == afgi_key else 2
        if pts:
            p.append("<polyline fill='none' stroke='%s' stroke-width='%d' points='%s'/>"
                     % (color[key], sw, " ".join(pts)))
        sst = first_valid(arr)
        if sst > 0 and arr[sst] is not None:
            cx, cy = X(sst), Y(arr[sst])
            p.append("<circle cx='%.1f' cy='%.1f' r='4.5' fill='#fff' stroke='%s' "
                     "stroke-width='2'/>" % (cx, cy, color[key]))
            p.append("<line stroke='%s' stroke-width='1' stroke-dasharray='3 2' "
                     "x1='%.1f' x2='%.1f' y1='%.1f' y2='%.1f'/>"
                     % (color[key], cx, cx, cy - 6, cy - 13))
            p.append("<text fill='%s' font-size='10' font-weight='600' "
                     "text-anchor='middle' x='%.1f' y='%.1f'>%s 起算</text>"
                     % (color[key], cx, cy - 17, INCEPTION))
    for s, key in enumerate(order):
        ly = 42 + s * 22
        p.append("<line stroke='%s' stroke-width='3' x1='782' x2='800' y1='%d' y2='%d'/>"
                 % (color[key], ly, ly))
        p.append("<text fill='%s' font-size='12' font-weight='%s' x='806' y='%d'>%s</text>"
                 % (color[key] if key == afgi_key else "#374151",
                    "600" if key == afgi_key else "400", ly + 4, esc(label[key])))
    for t in range(4):
        ii = round(k + (j - k) * t / 3)
        x = W0 + (W1 - W0) * t / 3
        p.append("<text fill='#6b7280' font-size='11' text-anchor='middle' x='%.1f' "
                 "y='328'>%s</text>" % (x, dates[ii][2:7]))
    return "".join(p)


# ── 4) 4.1 持仓变动表 ───────────────────────────────────────────────
def pct_span(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return '<span class="mut">-</span>'
    col = "up" if v > 0 else ("dn" if v < 0 else "mut")
    sign = "+" if v > 0 else ""
    return '<span class="%s">%s%.2f%%</span>' % (col, sign, v * 100)


# ── 调仓明细模块：日期下方的竖向小方框 ───────────────────────────────
def _nav_series(col):
    """本地 nav.csv 某列 → Series(date → nav)，列不存在返回 None。"""
    nav = pd.read_csv(NAV_FILE, index_col=0)
    nav.index = pd.to_datetime(nav.index).strftime("%Y-%m-%d")
    nav = nav.astype(float).sort_index()
    return nav[col] if col in nav.columns else None


def nav_change(days_asc, col):
    """{调仓日: 相对上一调仓日的净值涨跌幅}（小数）。

    days_asc 必须是**升序**的完整调仓日序列（不是只取展示的若干期），
    否则首期拿不到它的上一期。首期或任一端缺失数据 → None（页面显示「—」）。
    """
    s = _nav_series(col)
    out, prev = {}, None
    for d in days_asc:
        if s is not None and prev is not None and d in s.index and prev in s.index:
            out[d] = float(s.loc[d] / s.loc[prev] - 1.0)
        else:
            out[d] = None
        prev = d
    return out


def pbox(cls, text, title=""):
    """日期下方的一枚胶囊小方框（竖向排列，配色由 cls 决定）。"""
    t = ' title="%s"' % esc(title) if title else ""
    return '<span class="pbox %s"%s>%s</span>' % (cls, t, text)


def nav_pbox(v):
    """较上期净值涨跌：涨红跌绿。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return pbox("b-nav fl", "较上期 —")
    c = "up" if v > 0 else ("dn" if v < 0 else "fl")
    return pbox("b-nav " + c, "较上期 %+.2f%%" % (float(v) * 100))


def afgi_pbox(v):
    """调仓决策日的 AFGI 读数；AFGI 数据起点之前无读数 → 显示「—」。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return pbox("b-afgi", "AFGI —", title="AFGI 数据起点（2023-02-09）之前无读数")
    v = float(v)
    return pbox("b-afgi", "AFGI %.2f" % v, title="%s（分档决定权益仓位）" % AP.afgi_state_of(v))


def build_hold_rows():
    hold = pd.read_csv(HOLD_FILE, dtype={"代码": str})
    hold["调仓日"] = hold["调仓日"].astype(str)
    rm = pd.read_csv(RM_FILE, dtype={"代码": str})
    rm["调仓日"] = rm["调仓日"].astype(str)
    pdf = AP.factor_at_rebalance(pct=True)          # {调仓日: 仓位%}
    afgi_rd = AP.afgi_reading_at_rebalance()        # {调仓日: AFGI 读数 or None}

    all_days = sorted(hold["调仓日"].unique())
    chg = nav_change(all_days, NAV_COL_41)          # {调仓日: 较上期净值涨跌}

    days = all_days[-N_SHOW_MOM:][::-1]
    rows = []
    for di, day in enumerate(days):
        h = hold[hold["调仓日"] == day].sort_values("次序")
        items, n_new = [], 0
        for _, r in h.iterrows():
            is_new = str(r.get("状态", "")) == "新增"
            n_new += int(is_new)
            cls = "nm-new" if is_new else "nm"
            w = r.get("权重")
            ws = "" if pd.isna(w) else '<span class="wt">%.2f%%</span>' % (float(w) * 100)
            items.append('<span class="%s">%s</span>%s' % (cls, esc(r["名称"]), ws))
        g = rm[rm["调仓日"] == day].sort_values("区间涨跌幅", ascending=False)
        # 剔除的股票沿用 4.2 质量 Top28 的样式：名称后标「建仓 xxxx-xx-xx」
        outs = ['<span class="nm-out">%s</span><span class="join">建仓 %s</span> %s'
                % (esc(r["名称"]), esc(r["建仓日"]), pct_span(r["区间涨跌幅"]))
                for _, r in g.iterrows()]
        tag = "最新一期" if di == 0 else "倒数第 %d 期" % (di + 1)
        pos = pdf.get(day)
        # 新版规则算出的仓位是连续值（如 43.25%），不再只是 100/30/10 三档
        if pos is None:
            pos_html = ""
        elif pos <= 1e-9:
            pos_html = pbox("b-pos", "仓位 0%（空仓）")
        else:
            pos_html = pbox("b-pos", "仓位 %.2f%%" % pos)
        rows.append(
            '<tr><td class="day">%s%s%s%s<span class="pill">%s</span></td>'
            '<td class="cell">%s<span class="cnt">%d 只 · 新增 %d</span></td>'
            '<td class="cell">%s<span class="cnt">%d 只</span></td></tr>'
            % (day, pos_html, afgi_pbox(afgi_rd.get(day)), nav_pbox(chg.get(day)),
               tag, "、".join(items), len(h), n_new,
               "、".join(outs) if outs else '<span class="mut">—</span>', len(g)))
    return "".join(rows)


# ── 4.2) 质量 Top28 组合持仓变动表 ──────────────────────────────────
def build_qual_rows():
    """质量 Top28：按因子得分降序（次序）排列，每只股票后标出建仓权重。"""
    hold = pd.read_csv(QUAL_FILE, dtype={"代码": str})
    hold["调仓日"] = hold["调仓日"].astype(str)
    rm = pd.read_csv(QUAL_RM_FILE, dtype={"代码": str})
    rm["调仓日"] = rm["调仓日"].astype(str)

    all_days = sorted(hold["调仓日"].unique())
    chg = nav_change(all_days, NAV_COL_42)          # {调仓日: 较上期净值涨跌}

    days = all_days[-N_SHOW_QUAL:][::-1]
    rows = []
    for di, day in enumerate(days):
        h = hold[hold["调仓日"] == day].sort_values("次序")
        items, n_new = [], 0
        for _, r in h.iterrows():
            is_new = str(r.get("状态", "")) == "新增"
            n_new += int(is_new)
            cls = "nm-new" if is_new else "nm"
            w = r.get("建仓权重")
            ws = "" if pd.isna(w) else '<span class="wt">%.2f%%</span>' % (float(w) * 100)
            items.append('<span class="%s">%s</span>%s' % (cls, esc(r["名称"]), ws))
        g = rm[rm["调仓日"] == day].sort_values("区间涨跌幅", ascending=False)
        outs = ['<span class="nm-out">%s</span><span class="join">建仓 %s</span> %s'
                % (esc(r["名称"]), esc(r["建仓日"]), pct_span(r["区间涨跌幅"]))
                for _, r in g.iterrows()]
        tag = "最新一期" if di == 0 else "倒数第 %d 期" % (di + 1)
        per = h["报告期"].iloc[0] if len(h) else ""
        rows.append(
            '<tr><td class="day">%s%s<span class="pill">%s</span><span class="cnt">%s</span></td>'
            '<td class="cell">%s<span class="cnt">%d 只 · 新增 %d</span></td>'
            '<td class="cell">%s<span class="cnt">%d 只</span></td></tr>'
            % (day, nav_pbox(chg.get(day)), tag, esc(per), "、".join(items), len(h), n_new,
               "、".join(outs) if outs else '<span class="mut">—</span>', len(g)))
    return "".join(rows)


def rebuild_qual_section(html, anchor_re=r"4\.2[\s\u3000]*质量Top28组合",
                         next_re=r"4\.3[\s\u3000]*盈利能力Top40"):
    """重建质量 Top28 整段（标题 / 说明 / 图例 / 表头 / 表体）。

    anchor_re / next_re 默认是 v2 版式（4.2 → 4.3）；v3 版式传 5.3 → 5.4。
    """
    m = re.search(anchor_re, html)
    if not m:
        raise RuntimeError("未找到质量Top28 小节锚点：%s" % anchor_re)
    a = m.start()
    m2 = re.search(next_re, html[a + 1:])
    if not m2:
        raise RuntimeError("未定位质量Top28 之后的下一小节：%s" % next_re)
    b = a + 1 + m2.start()
    seg = html[a:b]
    _h = pd.read_csv(QUAL_FILE, dtype={"代码": str})
    _n = int((_h["调仓日"] == _h["调仓日"].max()).sum())
    for _a in ("持仓 20 只", "持仓 28 只", "持仓 18 只", "持仓 19 只"):
        seg = seg.replace(_a, "持仓 %d 只" % _n)
    for _a in ("本期持仓（20 只）", "本期持仓（28 只）", "本期持仓（18 只）", "本期持仓（19 只）"):
        seg = seg.replace(_a, "本期持仓（%d 只）" % _n)
    seg = _replace_block(
        seg, 0, r'<div[^>]*class="note"[^>]*>',
        "调仓频率与第三节回测一致：<b>每个季度调仓一次</b>"
        "（调仓日＝报告期信息可得日后的首个交易日，如 2026 年中报 → 2026-09-01）。"
        "<b>选股</b>：当期股池内按舞弊调整质量因子得分降序，"
        "单个申万三级行业最多 2 只（出现第 3 只时跳过其中得分最低者并按序补录），取满 28 只为候选。"
        "<b>v2 三道筛</b>：① 剔除 20 日均成交额低于 5,000 万元的标的；"
        "② 计算换手率代理＝20 日均成交额 ÷ 总市值，在本期候选内排序，"
        "<b>剔除最拥挤的 1/3</b>；③ 权重 ∝ 1/(换手分位+0.15)，"
        "<b>单只限幅 2%~8%</b>（取代原「前 3 名各 16%」）。"
        "<b>季度买入持有</b>：只在季度股池更新日换仓建仓，"
        "同一季度内不再平衡，权重随价格自然漂移，直到下个季度重新建仓；"
        "换仓同样权重滞后 1 日。",
        name="4.2 note")
    seg = _replace_block(
        seg, 0, r'<div[^>]*class="legend"[^>]*>',
        '<span class="nm-new">红色</span> = 本期相较上期新纳入'
        '<span class="nm-out" style="margin-left:14px">绿色</span> = 本期被剔除；'
        '其后「建仓 xxxx-xx-xx」为加入持仓的调仓日，数字为「建仓日 → 剔除日」累计涨跌幅'
        '<span class="mut" style="margin-left:14px">（涨跌幅按 A 股习惯：红涨绿跌）</span>'
        '<span class="mut" style="margin-left:14px">股票名称后百分比＝建仓权重'
        '（按 1/(换手分位+0.15) 分配，单只限幅 2%~8%，合计 100%）</span>'
        '<span class="mut" style="margin-left:14px">调仓日下方「较上期 ±x.xx%」'
        '＝本组合净值相对上一调仓日的区间涨跌幅（红涨绿跌）</span>',
        name="4.2 legend")
    seg = seg.replace("本期剔除（较上期卖出 · 累计涨跌幅）",
                      "本期剔除（较上期卖出 · 建仓日 / 累计涨跌幅）")
    c0, c1 = inner_span(seg, r"<tbody[^>]*>")
    seg = seg[:c0] + build_qual_rows() + seg[c1:]
    log("  ✓ 质量Top28 持仓表已重建（%d 期）" % build_qual_rows().count("<tr>"))
    return html[:a] + seg + html[b:]


# ── 4.3) 盈利能力 Top40：同步 daytime 小方框样式 ─────────────────────
def sync_prof_style(html):
    """4.3 的较上期涨跌由另一个 project 生成（class="pchg up/dn"），数值不动，
    只把样式拉齐到与 4.1 / 4.2 一致的胶囊方框，保证三个模块观感统一。幂等。"""
    n = len(re.findall(r'class="pchg', html))
    if not n:
        log("  · 4.3 无 pchg 方框（可能尚未渲染），跳过样式同步")
        return html
    html = re.sub(r'(<span[^>]*\bclass=")pchg\s*([\w-]*)"',
                  lambda m: '%spbox b-nav %s"' % (m.group(1), m.group(2).strip()),
                  html)
    log("  ✓ 4.3 盈利能力Top40 较上期方框已同步 %d 处" % n)
    return html


# ── CSS：日期下方的胶囊方框 ─────────────────────────────────────────
PBOX_CSS = (
    ".pbox{display:table;margin-left:0;margin-top:3px;border-radius:999px;"
    "padding:2px 10px;font-size:12px;font-weight:600;font-variant-numeric:tabular-nums;"
    "white-space:nowrap}"
    ".pbox.b-pos{background:#eef2ff;color:#3730a3}"
    ".pbox.b-afgi{background:#f5f3ff;color:#6d28d9}"
    ".pbox.b-nav.up{background:#fdecec;color:#c0392b}"
    ".pbox.b-nav.dn{background:#e7f6ee;color:#128a53}"
    ".pbox.b-nav.fl{background:#f3f4f6;color:#6b7280}"
)


def inject_css(html):
    """把 .pbox 系列样式插到 .pchg 规则之后（幂等：已存在则跳过）。"""
    if ".pbox{" in html:
        log("  · .pbox 样式已存在，跳过注入")
        return html
    m = re.search(r"\.pchg\s*\{[^}]*\}\s*", html)
    if not m:
        m = re.search(r"\.pill\s*\{[^}]*\}\s*", html)
    if not m:
        raise RuntimeError("未找到 CSS 锚点（.pchg / .pill），无法注入 .pbox 样式")
    html = html[:m.end()] + PBOX_CSS + html[m.end():]
    log("  ✓ .pbox 方框样式已注入 CSS")
    return html


# ── 布局：把最下方「五/六、如何更新最新一季股池」收回 .wrap 容器 ──────────
# v2 版式是「五、」，v3（2026-10-18 起）多了「四、仓位建议」，该节顺延为「六、」。
WRAP_ANCHORS = ("五、如何更新最新一季股池", "六、如何更新最新一季股池")
WRAP_ANCHOR = WRAP_ANCHORS[0]     # 向后兼容（旧调用/自检）


def find_wrap_anchor(html):
    for t in WRAP_ANCHORS:
        i = html.find(t)
        if i >= 0:
            return i
    return -1


def div_depth_at(html, idx):
    """返回 idx 处的 <div> 嵌套深度（0 = 不在任何 div 内）。"""
    b = html.find("<body")
    if b < 0:
        b = 0
    depth = 0
    for m in re.finditer(r"<div\b[^>]*>|</div\s*>", html[b:idx]):
        depth += -1 if m.group(0).startswith("</") else 1
    return depth


def fix_wrap_scope(html):
    """把 .wrap 的闭合 </div> 从「五、…」之前挪到页脚之后。

    模板里那个 </div> 被误放在 <h2>五、如何更新最新一季股池</h2> 之前，
    导致这一节（含页脚免责声明）脱离 .wrap{max-width:1180px;margin:0 auto}
    容器，在宽屏上占满整幅宽度、与上方各节左右不对齐。

    幂等：该节已在 .wrap 内时原样返回。
    """
    a = find_wrap_anchor(html)
    if a < 0:
        return html
    hs = html.rfind("<h2", 0, a)               # 该 <h2> 标签的起点
    body = html.find("<body")
    if hs < 0 or body < 0 or body > hs:
        return html

    # 从 <body> 起扫描：深度首次回到 0 的那个 </div> 就是提前闭合的 .wrap
    depth, close_m = 0, None
    for m in re.finditer(r"<div\b[^>]*>|</div\s*>", html[body:hs]):
        if m.group(0).startswith("</"):
            depth -= 1
            if depth == 0 and close_m is None:
                close_m = m
        else:
            depth += 1
    if close_m is None or depth != 0:
        return html                            # 已在容器内 / 结构异常 → 不动
    if div_depth_at(html, hs) != 0:
        return html

    cs, ce = body + close_m.start(), body + close_m.end()
    html = html[:cs] + html[ce:]               # 摘掉这个提前闭合的 </div>
    end_body = html.rfind("</body>")
    if end_body < 0:
        return html
    html = html[:end_body] + "</div>\n" + html[end_body:]
    log("  ✓ 「五、」模块与页脚已收回 .wrap 容器（宽度与上方各节对齐）")
    return html


# ── 顶部 7 个 KPI 卡片 ──────────────────────────────────────────────
def kpi_span(html, label):
    """返回标签为 label 的 .kpi 卡片区间 (start, end)；找不到返回 None。"""
    for m in re.finditer(r'<div[^>]*\bclass="kpi"[^>]*>', html):
        i0 = m.start()
        i1 = html.find("</div>", m.end())
        if i1 < 0:
            continue
        seg = html[i0:i1]
        first = re.search(r"<span[^>]*>(?:<!--[^>]*-->\s*)*([^<]*)", seg)
        if first and first.group(1).strip() == label:
            return i0, i1 + 6
    return None


def set_kpi_inner(seg, open_re, text, name=""):
    """替换卡片内某元素的文本内容，**保留**原有的 <!--pnid:xxx--> 注释
    （节点映射用，删掉会让平台把节点当成新建）。返回 (new_seg, ok)。"""
    m = re.compile(open_re).search(seg)
    if not m:
        return seg, False
    cm = re.compile(r"\s*(?:<!--[^>]*-->\s*)*").match(seg, m.end())
    tag = m.group(0).lstrip("<").split()[0].rstrip(">")
    close = re.compile(r"</%s\s*>" % re.escape(tag)).search(seg, cm.end())
    if not close:
        return seg, False
    return seg[:cm.end()] + text + seg[close.start():], True


def update_kpi_cards(html, only=None):
    """把顶部 7 张 KPI 卡里的 AFGI 相关数值做成全数据驱动。

    · A股恐慌贪婪指数：数值 / 状态徽章（含配色）/ 截至日
    · 稳健联合当前仓位：AFGI 逆情绪规则算出的当期目标仓位 / 截至（最近调仓日）
    · 动量组合持仓 / 质量Top28组合持仓：最新一期的实际持仓只数
    · 其余三张（评分报告期 / 股池覆盖个股 / 申万三级行业）只在季度股池更新时变，
      由 update_latest.py 负责，本函数不动。
    """
    def _want(label):
        return True if not only else label in only

    done = []

    # ① A股恐慌贪婪指数
    rd = AP.latest_afgi_reading() if _want("A股恐慌贪婪指数") else None
    if rd:
        sp = kpi_span(html, "A股恐慌贪婪指数")
        if sp is None:
            log("  ! 未找到「A股恐慌贪婪指数」KPI 卡片")
        else:
            i0, i1 = sp
            seg = html[i0:i1]
            seg, ok1 = set_kpi_inner(seg, r"<b\b[^>]*>", "%.2f" % rd["afgi"], "AFGI 数值")
            st = str(rd.get("state") or AP.afgi_state_of(rd["afgi"]))
            bg, fg = AFGI_BADGE.get(st, AFGI_BADGE["未知"])
            seg = re.sub(r'(<span[^>]*\bclass="afgi-bd"[^>]*\bstyle=")[^"]*(")',
                         lambda m: '%sdisplay:inline-block; background:%s; color:%s; '
                                   'border-radius:999px; padding:1px 9px; font-size:12px; '
                                   'font-weight:600%s' % (m.group(1), bg, fg, m.group(2)),
                         seg, count=1)
            seg, ok2 = set_kpi_inner(seg, r'<span[^>]*\bclass="afgi-bd"[^>]*>', st, "AFGI 状态")
            seg, n_d = re.subn(r"截至\s*\d{4}-\d{2}-\d{2}", "截至 %s" % rd["date"], seg, count=1)
            if ok1 and ok2 and n_d:
                html = html[:i0] + seg + html[i1:]
                done.append("A股恐慌贪婪指数 → %.2f（%s，截至 %s）"
                            % (rd["afgi"], st, rd["date"]))
            else:
                log("  ! A股恐慌贪婪指数 卡片结构异常（b=%s 徽章=%s 日期=%s）"
                    % (ok1, ok2, n_d))

    # ② 稳健联合当前仓位（AFGI 组合当期目标仓位）
    try:
        if not _want("稳健联合当前仓位"):
            raise StopIteration
        pos = AP.current_position_pct()
        hold = pd.read_csv(HOLD_FILE, dtype={"代码": str})
        last_rb = sorted(set(hold["调仓日"].astype(str)))
        last_rb = [d for d in last_rb if d <= str(pd.Timestamp.today().date())] or last_rb
        asof = last_rb[-1] if last_rb else ""
        sp = kpi_span(html, "稳健联合当前仓位")
        if sp:
            i0, i1 = sp
            seg = html[i0:i1]
            seg, ok1 = set_kpi_inner(seg, r"<b\b[^>]*>", "%.0f%%" % pos, "联合仓位")
            seg, n_d = re.subn(r"截至\s*\d{4}-\d{2}-\d{2}", "截至 %s" % asof, seg, count=1)
            if ok1 and n_d:
                html = html[:i0] + seg + html[i1:]
                done.append("稳健联合当前仓位 → %.0f%%（截至 %s）" % (pos, asof))
    except StopIteration:
        pass
    except Exception as e:                      # KPI 失败不能阻断整页刷新
        log("  ! 稳健联合当前仓位 更新失败：%s" % e)

    # ③④ 两个组合的最新一期持仓只数
    for label, path, col in (("动量组合持仓", HOLD_FILE, None),
                             ("质量Top28组合持仓", QUAL_FILE, None)):
        if not _want(label):
            continue
        try:
            df = pd.read_csv(path, dtype={"代码": str})
            last = sorted(set(df["调仓日"].astype(str)))[-1]
            cnt = int((df["调仓日"].astype(str) == last).sum())
            sp = kpi_span(html, label)
            if sp:
                i0, i1 = sp
                seg, ok1 = set_kpi_inner(html[i0:i1], r"<b\b[^>]*>", str(cnt), label)
                if ok1:
                    html = html[:i0] + seg + html[i1:]
                    done.append("%s → %d 只" % (label, cnt))
        except Exception as e:
            log("  ! %s 更新失败：%s" % (label, e))

    for d_ in done:
        log("  ✓ KPI %s" % d_)
    return html


# ── v3 版式主流程 ────────────────────────────────────────────────────
def run_v3(html, bt, args):
    """只刷新质量Top28；CSFM/TSFM/B-score/仓位模块一律原样保留。"""
    dates, series = refresh_series_v3(bt)

    new_bt = {
        "dates": dates,
        "order": list(bt["order"]),
        "label": dict(bt["label"]),
        "color": dict(bt["color"]),
        "series": series,
    }
    i = html.index("var BT=")
    js, je = json_span(html, i)
    html = (html[:js]
            + json.dumps(new_bt, ensure_ascii=False, separators=(",", ":"))
            + html[je:])
    log("  ✓ var BT= 已替换（%d 条曲线 × %d 个交易日）"
        % (len(new_bt["order"]), len(dates)))
    log("  · 静态 SVG 兜底图跳过（v3 主图由页面 JS 按 BT 绘制，静态图仅作无脚本兜底）")

    html = set_qual_stat_v3(html, series)
    html = rebuild_qual_section(html, QUAL_ANCHOR_V3, QUAL_NEXT_V3)
    # v3 的 AFGI / 联合仓位由 AFGI 链路维护（本机 AFGI 数据可能比页面旧），只动持仓只数
    html = update_kpi_cards(html, only=("质量Top28组合持仓",))

    # ── 自检（v3 口径）─────────────────────────────────────────────
    ok = True
    checks = [
        ("var BT=", 1, True),
        ('id="posChart"', 1, True),
        ('id="posA"', 1, True),
        ('class="pbox b-ctrl"', 16, True),
        ('class="wt"', N_SHOW_QUAL * 8, False),
        ("排名前 3 名各 16%", 0, True),
        ('class="pchg', 0, True),
    ]
    for token, expect, exact in checks:
        got = html.count(token)
        bad = (got != expect) if exact else (got < expect)
        if bad:
            ok = False
        log("  %s %-18s 期望 %s%-4s 实际 %s"
            % ("!" if bad else "✓", token, "" if exact else "≥", expect, got))

    for key in ("因子动量CSFM", "因子动量TSFM", "B-score组合", "质量Top28组合"):
        if key not in series:
            ok = False
            log("  ! 缺少曲线：%s" % key)
    if len(dates) != len(bt["dates"]):
        ok = False
        log("  ! 日期轴被意外改变：%d → %d" % (len(bt["dates"]), len(dates)))
    miss = [d for d, v in zip(dates, series.get("质量Top28组合", [])) if v is None]
    if miss:
        ok = False
        log("  ! 质量Top28 有 %d 天缺值（首个 %s）" % (len(miss), miss[0]))
    log("  · 曲线 %d 条 / %d 个交易日（%s → %s）"
        % (len(new_bt["order"]), len(dates), dates[0], dates[-1]))

    if args.check:
        log("\n--check：仅自检，未写文件")
        return 0 if ok else 1

    write_text(args.out, html)
    log("\n已写出：%s（%s chars）" % (args.out, f"{len(html):,}"))
    return 0 if ok else 1


# ── 主流程 ──────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE_FILE, help="模板 HTML")
    ap.add_argument("--out", default=OUT_FILE, help="输出 HTML")
    ap.add_argument("--check", action="store_true", help="只自检，不写文件")
    ap.add_argument("--full", action="store_true",
                    help="全量重算：所有日期一律取本地净值，不沿用模板已发布数值")
    args = ap.parse_args()

    html = read_text(args.base)
    log("模板：%s（%s chars）" % (args.base, f"{len(html):,}"))

    layout = detect_layout(html)
    _what = {"v5": "v5 = 原版版式 + 2015-2026 新数据（finchain 链路），本脚本不适用",
             "v4": "v4 = 数据包 + 整页重绘（新结构），本脚本不适用",
             "v3": "v3 = CSFM/TSFM + 四、仓位建议 + 质量Top28 v2，只刷新质量Top28",
             "v2": "v2 = 动量轮动版式，整页数据区重建"}
    log("版式：%s（%s）" % (layout, _what.get(layout, layout)))

    # v4（2026-10-19 起的新结构）没有 var BT= / svg#btChart / td#r{i}_{c} 任何一个锚点，
    # 继续跑只会撞在下面的「var BT= 出现 0 次」防呆上、把每日任务标成失败。
    # 这里明确交棒：新结构的更新走 scripts/republish_page.py（数据包 → 整页重绘）。
    # 退 0 而不是退错 —— 它不是"坏了"，而是"不该由它做"。
    if layout in ("v4", "v5"):
        log("  → 线上页面由 finchain 新数据链路维护，跳过本脚本（不写文件）。")
        log("  → 页面更新请用：python scripts/finchain/rebuild_page.py --upload --publish")
        return 0

    html = apply_renames(html)
    html = inject_css(html)          # .pbox 胶囊方框样式（幂等）
    if layout == "v2":
        # v3 跳过：这段会把质量Top28 的口径文案改回旧的「前 3 名各 16%」
        html = update_rule_texts(html)
    html = fix_wrap_scope(html)      # 「五/六、」模块收回 .wrap 容器（幂等）

    # 防呆：var BT= 必须恰好 1 份，否则静态图与脚本会互相覆盖（历史踩过的坑）
    if html.count("var BT=") != 1:
        raise SystemExit("!! 模板中 var BT= 出现 %d 次（应为 1），存在重复脚本，已中止"
                         % html.count("var BT="))

    i = html.index("var BT=")
    js, je = json_span(html, i)
    bt = json.loads(html[js:je])
    log("模板净值：%s → %s，%d 个交易日，%d 条曲线"
        % (bt["dates"][0], bt["dates"][-1], len(bt["dates"]), len(bt["order"])))

    if layout == "v3":
        return run_v3(html, bt, args)

    # 1) 序列
    order_raw = read_table_order(html, bt)
    dates, series, factor = build_series(bt, full=args.full)
    order = [k for k in order_raw if k in series]
    order += [k for k in bt["order"] if k in series and k not in order]
    n = len(dates)
    if order_raw != list(bt["order"]):
        log("  · 统计表行序与 BT.order 不一致，已按表格行序重排：%s"
            % " / ".join(bt["label"][k] for k in order))
    log("重算完成：%s → %s，%d 个交易日，%d 条曲线"
        % (dates[0], dates[-1], n, len(order)))

    new_bt = {"dates": dates, "order": order,
              "label": {k: bt["label"][k] for k in order},
              "color": {k: bt["color"][k] for k in order},
              "series": {k: series[k] for k in order}}
    html = html[:i] + "var BT=" + json.dumps(new_bt, ensure_ascii=False,
                                             separators=(",", ":")) + html[je:]
    log("  ✓ var BT= 数据块已替换")

    # 2) 静态 SVG
    s0, s1 = inner_span(html, r"<svg\b[^>]*\bid=\"btChart\"[^>]*>")
    svg = render_svg(dates, order, series, bt["color"], bt["label"],
                     afgi_key=resolve_afgi_key(order))
    html = html[:s0] + svg + html[s1:]
    log("  ✓ 静态 SVG 兜底图已重建")

    # 3) 统计表单元格（脚本会再算一遍，这里保证无脚本时也正确）
    for si, key in enumerate(order):
        arr = series[key]
        rng = stat_range(arr)
        if rng is None:
            log("  ! %s 无有效净值，统计表留空" % key)
            v = None
        else:
            k0, j0 = rng
            if j0 < n - 1:
                log("  · %s 止于 %s（滞后 %d 个交易日），统计按其有效区间算"
                    % (key, dates[j0], n - 1 - j0))
            v = calc(arr, k0, j0)
        for ci in range(6):
            val = v[ci] if v is not None else None
            html = set_by_id(html, "r%d_%d" % (si, ci), fmt_cell(ci, val))
    log("  ✓ 统计表 %d 行已刷新" % len(order))

    # 4) 时间轴控件
    for tok in ("btA", "btB"):
        html = replace_once(html, r'(<input[^>]*\bid="%s"[^>]*?\bmax=")(\d+)(")' % tok,
                            lambda m: m.group(1) + str(n - 1) + m.group(3),
                            name=tok + ".max")
    html = replace_once(html, r'(<input[^>]*\bid="btB"[^>]*?\bvalue=")(\d+)(")',
                        lambda m: m.group(1) + str(n - 1) + m.group(3),
                        name="btB.value")
    html = set_by_id(html, "btTxt",
                     "%s → %s · %d 个交易日" % (dates[0], dates[-1], n))
    log("  ✓ 时间轴已同步到 %d 个交易日" % n)

    # 5) AFGI 说明段的重定基系数
    #    该说明段已随 2026-10-08 改版下线，模板里没有这段文案是常态：
    #    找不到就跳过，绝不能让它中断整页刷新。
    if factor:
        try:
            html = replace_once(html, r"当日动量轮动策略净值（[0-9.]+）",
                                lambda m: "当日动量轮动策略净值（%.2f）" % factor,
                                name="rebase-factor")
            log("  ✓ 重定基系数文案 → %.2f" % factor)
        except RuntimeError:
            log("  · 模板无 AFGI 重定基文案（说明段已下线），跳过")

    # 6) 4.1 持仓变动表
    anchor = html.index("4.1　动量轮动策略")
    c0, c1 = inner_span(html, r"<tbody[^>]*>", anchor)
    rows = build_hold_rows()
    html = html[:c0] + rows + html[c1:]
    log("  ✓ 4.1 持仓变动表已重建（%d 期）" % rows.count("<tr>"))

    # 7) 4.2 质量 Top28 组合持仓变动表
    html = rebuild_qual_section(html)

    # 8) 4.3 盈利能力 Top40：把较上期涨跌的样式拉齐（数值由该 project 生成，不动）
    html = sync_prof_style(html)

    # 9) 顶部 KPI 卡片（AFGI 数值 / 状态 / 截至日、联合仓位、两组合持仓只数）
    html = update_kpi_cards(html)

    # ── 自检 ─────────────────────────────────────────────────────
    # class="wt" 只校验下限：4.3（盈利能力 Top40）由另一个脚本生成，期数会随季报增加
    # 4.2 每期持仓只数已由 v2 规则决定（约 17~19 只），下限按 12 只/期保守估计
    wt_min = N_SHOW_MOM * L_MOM + N_SHOW_QUAL * 12
    checks = [
        ("var BT=", 1, True),
        ("btChart", 2, True),
        ("class=\"wt\"", wt_min, False),
        ('class="pbox b-pos"', N_SHOW_MOM, True),      # 4.1 仓位方框
        ('class="pbox b-afgi"', N_SHOW_MOM, True),     # 4.1 AFGI 读数方框
        ('class="pbox b-nav', N_SHOW_MOM + N_SHOW_QUAL, False),  # 4.1 + 4.2 较上期涨跌
        ('class="pchg', 0, True),                      # 4.3 旧样式已全部升级
    ]
    ok = True
    for token, expect, exact in checks:
        got = html.count(token)
        flag = "✓" if (got == expect if exact else got >= expect) else "!"
        if flag == "!":
            ok = False
        log("  %s %-14s 期望 %s%-4s 实际 %s"
            % (flag, token, "" if exact else "≥", expect, got))
    npoly = html.count("<polyline")
    log("  · polyline 静态 %d 条（含 2 个图例用的 <line> 不在此计数）" % npoly)

    # 布局自检：「五、」模块必须落在 .wrap 容器内，否则宽度会与上方各节不一致
    ia = html.find(WRAP_ANCHOR)
    if ia < 0:
        log("  · 模板无「五、」章节，跳过容器归属校验")
    elif div_depth_at(html, ia) != 1:
        ok = False
        log("  ! 「五、」模块不在 .wrap 容器内（深度 %d，应为 1）"
            % div_depth_at(html, ia))
    else:
        log("  ✓ 「五、」模块位于 .wrap 容器内（宽度对齐）")
    # AFGI 粉线已于 2026-10-08 从页面下线：基线里没有该曲线时不再要求它，
    # 有（历史版本）时才校验其存在，保证幂等且不阻断。
    key_afgi = resolve_afgi_key(bt["order"])
    if key_afgi and key_afgi not in html:
        ok = False
        log("  ! 缺少 %s 标记" % key_afgi)
    elif not key_afgi:
        log("  · 基线无 AFGI 仓位曲线（已下线），跳过该项校验")

    if args.check:
        log("\n--check：仅自检，未写文件")
        return 0 if ok else 1

    write_text(args.out, html)
    log("\n已写出：%s（%s chars）" % (args.out, f"{len(html):,}"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
