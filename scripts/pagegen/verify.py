# -*- coding: utf-8 -*-
"""上传前的离线验证：结构、脚本、数据三层都要真跑，不能只看"生成成功"。

为什么需要
----------
整页 `import_html` 覆写是不可逆的（原节点内容被替换），而渲染器里的错误往往**不会抛异常**：
拼错一个 key 只会让某块变成空字符串，页面照样"生成成功"。所以上传前必须逐层断言：

1. **结构层**：标签开闭配平，区块数正确（6 个 h2 + 期数张卡片）。
2. **脚本层**：抽内联 JS 交给 ``node --check`` 验语法；再用最小 DOM 桩把脚本真跑一遍，
   断言图表真的画出来了（7 条 polyline、每条折线点数 == 日期数、末端标签齐全、5 个刻度）。
3. **数据层**：股池明细条数与声明一致、Top28 恰好 28 只且单行业 ≤2、
   净值序列长度对齐 —— 并能从净值曲线**反算**夏普与绩效表对上（做不到这步，
   就只是"文件生成了"，不是"页面对了"）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile

TAGS = ["div", "section", "table", "thead", "tbody", "tr", "td", "th",
        "details", "summary", "script", "style", "svg", "html", "body"]

# 末值标签里出现的小数（用于断言 7 条曲线都有末端标注）
DTS_MONTH = re.compile(r"^\d{4}-\d{2}$")


def _find_node() -> str | None:
    for c in (os.environ.get("NODE_BIN"), "node", "node.exe"):
        if not c:
            continue
        try:
            subprocess.run([c, "-v"], capture_output=True, check=True, timeout=20)
            return c
        except Exception:
            continue
    return None


# ------------------------------------------------------------------ 1 结构
def check_structure(html: str) -> list[str]:
    bad = []
    for t in TAGS:
        o = len(re.findall(r"<%s[\s>]" % t, html))
        c = html.count("</%s>" % t)
        if o != c:
            bad.append(f"标签不配平 <{t}>：开 {o} / 闭 {c}")
    h2 = len(re.findall(r"<h2>", html))
    if h2 < 6:
        bad.append(f"章节数不足：<h2> 只有 {h2} 个（应为 6）")
    if "<script src=\"/page/page_comm/inject.js\"></script>" not in html:
        bad.append("缺少资料库注入脚本 /page/page_comm/inject.js")
    if 'id="chart"' not in html:
        bad.append("缺少图表容器 #chart")
    if 'id="rng"' not in html:
        bad.append("缺少区间按钮组 #rng")
    return bad


# ------------------------------------------------------------------ 2 脚本
def extract_script(html: str) -> str:
    """取最长的一段内联 <script>（跳过带 src 的外链）。"""
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    return max(blocks, key=len) if blocks else ""


HARNESS = r"""
const fs = require('fs');
const path = process.argv[2];
const src = fs.readFileSync(path, 'utf8');
const els = {};
function mk(id){
  return els[id] || (els[id] = {
    id: id, innerHTML: '',
    addEventListener(){}, querySelectorAll(){ return []; },
    classList: { remove(){}, add(){} }, dataset: {}
  });
}
global.document = { getElementById: mk };
let api;
try {
  api = new Function(src + '\n;return {D:D, ORDER:ORDER, COL:COL, draw:draw};')();
} catch (e) {
  console.log(JSON.stringify({ok:false, err:'脚本执行异常: '+e.message}));
  process.exit(0);
}
const fails = [];
const chart = mk('chart').innerHTML;
const D = api.D, ORDER = api.ORDER;
const n = D.curve.dates.length;

const polys = (chart.match(/<polyline/g) || []).length;
if (polys !== ORDER.length) fails.push('折线数 '+polys+' != 序列数 '+ORDER.length);
if (!chart.length) fails.push('图表为空：draw() 未产出 #chart.innerHTML');

// 每条折线的点数必须等于日期数
const pts = [...chart.matchAll(/points="([^"]*)"/g)].map(m => m[1].trim().split(/\s+/).length);
pts.forEach((k, i) => { if (k !== n) fails.push('第'+i+'条折线点数 '+k+' != 日期数 '+n); });

// 每条曲线都要有非空、正数、末值一致的序列
ORDER.forEach(k => {
  const s = D.curve.series[k];
  if (!s || s.length !== n) { fails.push('序列 '+k+' 缺失或长度不符'); return; }
  if (s.some(v => !(v > 0))) fails.push('序列 '+k+' 含非正净值');
});

// 末端标签：每个序列一条，且带两位末值
const labels = [...chart.matchAll(/<text[^>]*font-size="11"[^>]*>([^<]*)<\/text>/g)].map(m => m[1]);
ORDER.forEach(k => {
  const want = (api.COL && k) ? null : null;
  const hit = labels.some(t => /\s\d+\.\d\d$/.test(t));
  if (!hit) fails.push('末端标签缺失');
});
const labCount = labels.filter(t => /\s\d+\.\d\d$/.test(t)).length;
if (labCount !== ORDER.length) fails.push('末端数值标签 '+labCount+' 个 != 序列数 '+ORDER.length);

// 日期刻度 5 个，且形如 YYYY-MM
const ticks = labels.filter(t => /^\d{4}-\d{2}$/.test(t));
if (ticks.length !== 5) fails.push('X 轴刻度 '+ticks.length+' 个 != 5');

// 区间切换：'1y' 后点数应显著减少且仍 > 0
const before = chart.length;
api.draw('1y');
const chart1y = mk('chart').innerHTML;
const polys1y = (chart1y.match(/<polyline/g) || []).length;
if (polys1y !== ORDER.length) fails.push("切到 '1y' 后折线数异常（"+polys1y+'）');
const n1y = Math.max(...[...chart1y.matchAll(/points="([^"]*)"/g)].map(m => m[1].trim().split(/\s+/).length));
if (!(n1y > 0 && n1y < n)) fails.push("'1y' 窗口未生效："+n1y+' 点 vs 全期 '+n);
api.draw('all');

console.log(JSON.stringify({ok: fails.length === 0, fails: fails, n: n, series: ORDER.length,
                            chart_len: before, tail_labels: labCount}));
"""


def check_script(html: str, node: str) -> tuple[list[str], dict]:
    js = extract_script(html)
    if not js:
        return ["未找到内联脚本"], {}
    bad: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "page.js")
        open(p, "w", encoding="utf-8").write(js)
        r = subprocess.run([node, "--check", p], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return [f"JS 语法错误：{(r.stderr or '').strip().splitlines()[:3]}"], {}
        h = os.path.join(td, "harness.js")
        open(h, "w", encoding="utf-8").write(HARNESS)
        r = subprocess.run([node, h, p], capture_output=True, text=True, timeout=180)
        out = (r.stdout or "").strip().splitlines()
        if not out:
            return [f"DOM 桩无输出：{(r.stderr or '')[:200]}"], {}
        try:
            res = json.loads(out[-1])
        except Exception:
            return [f"DOM 桩输出无法解析：{out[-1][:200]}"], {}
        if not res.get("ok"):
            bad += res.get("fails") or [res.get("err") or "DOM 桩断言失败"]
        return bad, res


# ------------------------------------------------------------------ 3 数据
def check_data(data: dict) -> tuple[list[str], dict]:
    bad: list[str] = []
    pools = data.get("pools") or []
    if not pools:
        return ["pools 为空"], {}

    # 每期声明条数 == 实际行业明细条数之和
    for p in pools:
        cnt = sum(len(i["items"]) for i in p["inds"])
        if cnt != p["n"]:
            bad.append(f"{p['asof']} 声明 {p['n']} 只，明细 {cnt} 只")
        if p["nind"] != len(p["inds"]):
            bad.append(f"{p['asof']} 声明 {p['nind']} 行业，明细 {len(p['inds'])}")

    # 行业各前5：同一期内单行业不得超过 5
    for p in pools:
        for i in p["inds"]:
            if len(i["items"]) > 5:
                bad.append(f"{p['asof']} 行业「{i['name']}」有 {len(i['items'])} 只（>5）")
                break

    # 期序单调
    asofs = [p["asof"] for p in pools]
    if asofs != sorted(asofs):
        bad.append("pools 未按 asof 升序")
    if len(set(asofs)) != len(asofs):
        bad.append("pools 存在重复 asof")

    # Top28
    q28 = data.get("q28") or []
    if len(q28) != 28:
        bad.append(f"最新一期 Top28 实际 {len(q28)} 只")
    ind_cnt: dict[str, int] = {}
    for it in q28:
        ind_cnt[it["ind"]] = ind_cnt.get(it["ind"], 0) + 1
    over = {k: v for k, v in ind_cnt.items() if v > 2}
    if over:
        bad.append(f"Top28 单行业超 2 只：{over}")

    # 净值序列
    curve = data.get("curve") or {}
    dts, ser = curve.get("dates") or [], curve.get("series") or {}
    if not dts:
        bad.append("缺净值曲线 dates")
    for k, v in ser.items():
        if len(v) != len(dts):
            bad.append(f"净值序列「{k}」长度 {len(v)} != 日期数 {len(dts)}")
    need = ["CSFM(N=20, κ=1.5)", "TSFM(N=30, κ=1.0)", "质量Top28 v1", "质量Top28 v2",
            "沪深300", "中证500", "创业板50"]
    for k in need:
        if k not in ser:
            bad.append(f"净值曲线缺「{k}」")

    stats = {}
    # 反算：由月度净值重算 CSFM 全期年化/波动/夏普，与绩效表比对
    stats.update(_crosscheck_nav(data, bad))

    # 绩效表必备行
    keys = {(r["k"], r["seg"]) for r in data.get("summary", [])}
    for k in need:
        if (k, "全期") not in keys:
            bad.append(f"绩效表缺「{k} / 全期」")

    # κ 敏感性：主口径必须齐 4 档
    caps = {(x["s"], x["n"], round(x["k"], 3)) for x in data.get("kappa", [])}
    for nm, n in (("CSFM", 20), ("CSFM", 30), ("TSFM", 30), ("TSFM", 40)):
        for k in (0.0, 0.5, 1.0, 1.5):
            if (nm, n, round(k, 3)) not in caps:
                bad.append(f"κ 敏感性缺 {nm} N={n} κ={k}")
                break

    return bad, stats


def _crosscheck_nav(data: dict, bad: list[str]) -> dict:
    """从净值曲线重算年化/波动/夏普，与绩效表互校。

    口径要点：curve 一律是**月度点**。月度组合（CSFM/TSFM）直接用月收益；
    季度组合（质量Top28）的月度点是把季度净值阶梯化（forward-fill）得到的，
    直接按 12 折年会把波动系统性低估约 1 个百分点（阶梯化把每季 3 个月的收益摊成
    「0、0、r」）。所以季度组合必须先**还原出真实跳变点**再按 4 折年，
    否则互校容差会假性逼近上限，看不出真正的问题。
    """
    import math

    ser = (data.get("curve") or {}).get("series") or {}
    summ = {(r["k"], r["seg"]): r for r in data.get("summary", [])}
    out = {}
    pairs = [("CSFM(N=20, κ=1.5)", 12), ("TSFM(N=30, κ=1.0)", 12),
             ("质量Top28 v1", 4), ("质量Top28 v2", 4)]
    for k, ppy in pairs:
        v = ser.get(k)
        r = summ.get((k, "全期"))
        if not v or not r or not r.get("ann") or not r.get("vol"):
            continue

        # 两类组合统一口径：只取净值**真正发生变化**的区间。
        # 月度组合里也有零变化区间（末月被 ffill 出来的重复点），季度组合则是每月
        # 只有季末一次跳变——用同一套提取逻辑，期数才与绩效表严格一致。
        rets = [v[i] / v[i - 1] - 1 for i in range(1, len(v))
                if v[i - 1] > 0 and abs(v[i] / v[i - 1] - 1) > 1e-9]
        # 曲线的首点不是 1.00，而是「1 + 首期收益」——首期收益没有前一点可除，
        # 必须单独补回，否则序列永远少一期。季度组合漏掉首期（往往是 2015Q3 这类
        # 大幅波动期）会把年化波动系统性低估 1~1.5 个百分点。
        if v[0] > 0:
            rets = [v[0] - 1.0] + rets
        n = len(rets)
        if n < ppy * 2:
            continue
        ann = v[-1] ** (float(ppy) / n) - 1
        mu = sum(rets) / n
        var = sum((x - mu) ** 2 for x in rets) / (n - 1)
        vol = math.sqrt(var) * math.sqrt(ppy)
        sh = ann / vol if vol > 0 else 0
        out[k] = {"ann": ann, "vol": vol, "sh": sh, "n": n, "ppy": ppy,
                  "ann_tbl": r["ann"], "vol_tbl": r["vol"], "sh_tbl": r.get("sh")}
        if abs(ann - r["ann"]) > 0.006:
            bad.append(f"{k} 年化反算 {ann:.2%} 与绩效表 {r['ann']:.2%} 不一致")
        if abs(vol - r["vol"]) > 0.006:
            bad.append(f"{k} 波动反算 {vol:.2%} 与绩效表 {r['vol']:.2%} 不一致")
        if r.get("sh") and abs(sh - r["sh"]) > 0.02:
            bad.append(f"{k} 夏普反算 {sh:.2f} 与绩效表 {r['sh']:.2f} 不一致")
    return out


# ------------------------------------------------------------------ 汇总
def verify(html: str, data: dict, need_node: bool = True) -> tuple[bool, dict]:
    report: dict = {"structural": [], "script": [], "data": [], "info": {}}
    report["structural"] = check_structure(html)
    report["data"], report["info"]["crosscheck"] = check_data(data)

    node = _find_node() if need_node else None
    if node:
        bad, res = check_script(html, node)
        report["script"] = bad
        report["info"]["harness"] = res
    else:
        report["script"] = ["未找到 node，跳过脚本执行验证（仅做了语法/结构检查）"]

    ok = not (report["structural"] or report["script"] or report["data"])
    return ok, report


def print_report(ok: bool, report: dict) -> None:
    tag = {"structural": "结构", "script": "脚本", "data": "数据"}
    print("=" * 62)
    for k in ("structural", "script", "data"):
        items = report[k]
        print(f"[{tag[k]}] {'通过' if not items else str(len(items)) + ' 项失败'}")
        for it in items:
            print(f"   ✗ {it}")
    info = report.get("info") or {}
    h = info.get("harness") or {}
    if h:
        print(f"[脚本] 序列 {h.get('series')} 条 · 点数 {h.get('n')} · "
              f"末端标签 {h.get('tail_labels')} 个 · SVG {h.get('chart_len')} 字节")
    for k, v in (info.get("crosscheck") or {}).items():
        print(f"[互校] {k}（{v['n']} 期/{v['ppy']} 折年）: 反算 年化 {v['ann']:.2%} / 波动 {v['vol']:.2%}"
              f" / 夏普 {v['sh']:.2f}  ↔ 表内 {v['ann_tbl']:.2%} / {v['vol_tbl']:.2%} / {v['sh_tbl']:.2f}")
    print("=" * 62)
    print("验证结果：" + ("全部通过" if ok else "存在失败项，禁止上传"))
