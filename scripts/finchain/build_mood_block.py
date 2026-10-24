# -*- coding: utf-8 -*-
"""生成页面第六模块《市场情绪展望》的 HTML 片段。

数据源
------
data/mood_q28.json   人工研报检索后固化的快照：目标价区间、来源机构与日期、
                     情绪档位、关键逻辑、风险（这部分没法自动抓）
data/mood19_ext.json 自动补强（fetch_mood_ext.py 产出）：
                     ① 东财 F10 一致预期 → 26E/27E/28E 的 EPS 与 PE
                     ② 东财研报中心近 180 天个股研报明细（带 infoCode 原文链接）

产物：data/mood_block.html（由 patch_page.py 插到「如何更新股池」之前）

列结构（与「中证800 · 卖方目标价与情绪全景」页保持同一套读法）：
    个股（权重）· T 日股价 · 研报目标价范围 · 未来三年 EPS/PE · 市场情绪
点击个股名弹出右侧抽屉，逐条列出该股近 180 天研报（标题可点开东财原文），
并在抽屉底部给出四类数据源的可点入口。
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_JSON = os.path.join(BASE, "data", "mood_q28.json")
DEFAULT_EXT = os.path.join(BASE, "data", "mood19_ext.json")
DEFAULT_OUT = os.path.join(BASE, "data", "mood_block.html")
EM_RPT = "https://data.eastmoney.com/report/stock.jshtml"


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def rich(s):
    """转义后把 **关键句** 变成红色加粗。

    「不被表面文字蒙蔽」这件事没法靠脚本判断，但「哪一句是关键」可以让
    写数据的人（或滚动任务里的模型）用 ** 标出来，渲染层负责把它染红。
    这样标红位置始终跟着内容走，不会因为改文案而错位。
    """
    out = esc(s)
    return re.sub(r"\*\*(.+?)\*\*", r'<b class="hl">\1</b>', out)


# 变化类型 → (符号, 短语)。三种都用红色，靠符号区分方向：
# 用户要的是「重大变化就标红」，不区分好坏，但得让人一眼看出往哪边变。
FLAG_META = {
    "down": ("▼", "情绪下调"),
    "up": ("▲", "情绪上调"),
    "logic": ("⚡", "逻辑变化"),
    "none": ("○", "转为无覆盖"),
}


def pct(x):
    return f"{x:+.1f}%"


def implied(price, lo, hi):
    """隐含空间；返回 (文本, 方向类)"""
    if lo is None:
        return "—", "mut"
    if hi is None or abs(hi - lo) < 1e-9:
        v = (lo / price - 1) * 100
        return f"隐含 {pct(v)}", ("up" if v >= 0 else "dn")
    a = (lo / price - 1) * 100
    b = (hi / price - 1) * 100
    cls = "up" if (a + b) / 2 >= 0 else "dn"
    return f"隐含 {pct(a)} ~ {pct(b)}", cls


def tp_cell(r):
    lo, hi = r.get("tp_lo"), r.get("tp_hi")
    if lo is None:
        body = f'<span class="mut">未给出目标价</span>'
    elif hi is None or abs(hi - lo) < 1e-9:
        body = f'<b>{lo:.2f}</b> <span class="mut">{"单值" if r.get("tp_note") == "单值" else ""}</span>'
    else:
        body = f'<b>{lo:.2f} ~ {hi:.2f}</b>'
    imp, icls = implied(r["price"], lo, hi)
    return (f'{body}<br><span class="{icls} mood-imp">{imp}</span>'
            f'<div class="mood-src">{esc(r["tp_src"])}</div>')


def load_ext(path):
    """读 fetch_mood_ext.py 的产物；缺文件不报错，EPS 列降级为「无盈利预测」。"""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("stocks") or {}, d.get("meta") or {}
    except (OSError, ValueError):
        return {}, {}


def cons_of(st):
    c = (st or {}).get("cons") or {}
    n_org = c.get("n_org") or 0
    e = [c.get("e26"), c.get("e27"), c.get("e28")]
    return e, n_org


def eps_cell(r, st):
    """未来三年 EPS / PE。

    EPS 取东财 F10 一致预期「近六月平均」；PE 一律用 T 日收盘自算
    （东财那个 PE 是按它抓取时点的价，与本表口径不同，只用于核对）。
    EPS ≤ 0 时不给负 PE —— 负 PE 没有估值含义，会误导「看着便宜」。
    """
    e, n_org = cons_of(st)
    n_rep = len((st or {}).get("reports") or [])
    if not any(v is not None for v in e):
        hint = f"{n_rep} 份研报但无一致预期" if n_rep else "窗口内无个股研报"
        return f'<span class="mut">无盈利预测</span><div class="mood-src">{hint}</div>'

    price = r["price"]
    rows = []
    for lbl, v in zip(("26E", "27E", "28E"), e):
        pe = f"{price / v:.1f}×" if (v is not None and v > 0) else "—"
        rows.append(f'<span class="y">{lbl}</span>'
                    f'<b>{("—" if v is None else f"{v:.2f}")}</b><i>{pe}</i>')
    body = ('<div class="epsg" title="EPS 为东方财富 F10 一致预期「近六月平均」；'
            'PE = T 日收盘 / 该年 EPS；EPS ≤ 0 不显示负 PE">'
            '<span class="y hdr"></span><b class="hdr">EPS</b><i class="hdr">PE</i>'
            + "".join(rows) + "</div>")

    e26, e28 = e[0], e[2]
    if e26 is not None and e26 <= 0:
        foot = f'<span class="loss">26E 仍亏损</span><span>{n_org} 家</span>'
    elif e26 and e28 and e26 > 0 and e28 > 0:
        cagr = ((e28 / e26) ** 0.5 - 1) * 100
        cls = "up" if cagr >= 0 else "dn"
        foot = (f'<span>26→28 年化 <b class="{cls}">{cagr:+.1f}%</b></span>'
                f'<span>{n_org} 家</span>')
    else:
        foot = f'<span>26→28 年化 —</span><span>{n_org} 家</span>'
    return body + f'<div class="epsf">{foot}</div>'


def pack_js(rows, ext):
    """把表格与研报压成前端可用的紧凑结构（19 行 + 56 条，体积可忽略）。"""
    data, rep, orgs, rats = [], {}, [], [""]
    ri = {"": 0}
    for r in rows:
        st = ext.get(r["code"]) or {}
        e, n_org = cons_of(st)
        price = r["price"]
        pe = lambda v: (round(price / v, 1) if (v is not None and v > 0) else None)
        reps = st.get("reports") or []
        rep[r["code"]] = []
        for x in reps:                        # 已按日期倒序
            org = x.get("org") or ""
            if org not in orgs:
                orgs.append(org)
            for k in (x.get("rating"), x.get("last_rating")):
                if k and k not in ri:
                    ri[k] = len(rats)
                    rats.append(k)
            r2 = lambda v: None if v is None else round(v, 2)
            rep[r["code"]].append([
                x["date"][5:], orgs.index(org), ri.get(x.get("rating") or "", 0),
                ri.get(x.get("last_rating") or "", -1) if x.get("last_rating") else -1,
                x.get("tp_t"), x.get("tp_l"),
                r2(x.get("eps1")), r2(x.get("eps2")), r2(x.get("eps3")),
                (x.get("title") or "").strip(), x.get("ic") or "",
                x.get("researcher") or "",
            ])
        data.append({
            "c": r["code"], "n": r["name"], "w": r["weight"], "p": price,
            "chg": r["chg"], "tlo": r.get("tp_lo"), "thi": r.get("tp_hi"),
            "tps": r.get("tp_src") or "", "tier": r["mood_cls"],
            "lvl": r["mood_level"], "k": r["key"], "rk": r["risk"],
            "e26": e[0], "e27": e[1], "e28": e[2],
            "p26": pe(e[0]), "p27": pe(e[1]), "p28": pe(e[2]),
            "eo": n_org, "nr": len(reps),
        })
    return data, rep, orgs, rats


def flag_html(r):
    f = (r.get("flag") or "").strip()
    if not f:
        return ""
    icon, label = FLAG_META.get(f, ("●", "变化"))
    txt = esc(r.get("flag_txt") or "")
    at = esc(r.get("flag_at") or "")
    when = f'<u>{at}</u>' if at else ""
    return (f'<div class="mood-flag mf-{esc(f)}"><b>{icon} {label}</b>'
            f'{("　" + txt) if txt else ""}{when}</div>')


def row_html(r, ext):
    chg_cls = "up" if r["chg"] >= 0 else "dn"
    hot = " mood-hot" if (r.get("flag") or "").strip() else ""
    st = ext.get(r["code"]) or {}
    n_rep = len(st.get("reports") or [])
    tip = (f"查看 {r['name']} 近 180 天全部研报（{n_rep} 份）" if n_rep
           else f"查看 {r['name']}：研报库零覆盖")
    return f"""<tr class="{hot.strip()}">
<td class="mood-stk"><button class="stk" data-c="{esc(r['code'])}" title="{esc(tip)}">{esc(r['name'])}</button><span class="mood-code">{esc(r['code'])} · {r['weight']:.2f}%</span></td>
<td class="mood-px"><b>{r['price']:.2f}</b><span class="{chg_cls}">{r['chg']:+.2f}%</span></td>
<td class="mood-tp">{tp_cell(r)}</td>
<td class="mood-ep">{eps_cell(r, st)}</td>
<td class="mood-md">{flag_html(r)}<span class="mood-tag mt-{r['mood_cls']}">{esc(r['mood_level'])}</span>
<div class="mood-key">{rich(r['key'])}</div>
<div class="mood-risk"><b>风险</b>　{rich(r['risk'])}</div></td>
</tr>"""



def stats(rows):
    has = [r for r in rows if r.get("tp_lo") is not None]
    mids = []
    for r in has:
        lo = r["tp_lo"]
        hi = r["tp_hi"] if r.get("tp_hi") is not None else lo
        mids.append(((lo + hi) / 2 / r["price"] - 1) * 100)
    mids.sort()
    med = mids[len(mids) // 2] if len(mids) % 2 else (mids[len(mids) // 2 - 1] + mids[len(mids) // 2]) / 2
    none = [r for r in rows if r.get("tp_lo") is None]
    down = [r for r in rows if "下调" in (r.get("tp_src") or "")]
    flagged = [r for r in rows if (r.get("flag") or "").strip()]
    return {
        "n": len(rows), "n_has": len(has), "n_none": len(none),
        "median": med, "down": down, "mids": mids,
        "n_flag": len(flagged), "flagged": flagged,
    }


DWR_JS = r"""
/* ---------------- 第六章：个股研报抽屉 ---------------- */
(function(){
const esc0 = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const RK = {'买入':4,'强烈推荐':4,'推荐':4,'优于大市':4,'跑赢行业':4,'强推':4,
 '增持':3,'审慎增持':3,'谨慎推荐':3,'增仓':3,'中性':2,'持有':2,'观望':2,
 '减持':1,'弱于大市':1,'跑输行业':1,'卖出':0};
const DATA = __DATA__, REP = __REP__, ORGS = __ORGS__, RATS = __RATS__;
const EM = 'https://data.eastmoney.com/report/stock.jshtml';
const f1 = v => (v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%');
function pfmt(v){ if(v==null) return '—';
  return String(Number(v.toFixed(2))); }
function pre(c){ return (c[0]==='6'||c[0]==='9' ? 'SH' : 'SZ') + c; }

function openStock(code){
  const r = DATA.find(x => x.c === code); if(!r) return;
  const reps = REP[code] || [];
  /* 每家机构的上一条目标价：按时间升序推，再对齐回倒序 */
  const asc = reps.slice().reverse(), last = {};
  const prev = asc.map(x => {
    const p = (x[1] in last) ? last[x[1]] : null;
    if(x[4] != null) last[x[1]] = x[4];
    return p;
  }).reverse();

  const tpMain = (r.tlo == null) ? '无一家给价'
    : (r.thi == null || Math.abs(r.thi - r.tlo) < 1e-9 ? pfmt(r.tlo)
       : pfmt(r.tlo) + '~' + pfmt(r.thi));
  const tpMid = r.tlo == null ? null
    : ((r.thi == null ? r.tlo : (r.tlo + r.thi)/2) / r.p - 1) * 100;
  const epsRow = [['2026E', r.e26, r.p26], ['2027E', r.e27, r.p27], ['2028E', r.e28, r.p28]]
    .map(([y, e, p]) => `<div><span>${y}</span><b>${e == null ? '—' : e.toFixed(2)}</b>` +
      `<i>${p == null ? '—' : p.toFixed(1) + '×'}</i></div>`).join('');

  let h = `<div class="dw-h"><h2>${esc0(r.n)}<span>${r.c}</span></h2></div>
<div class="dw-sub">${esc0(r.lvl)} · 组合权重 ${r.w.toFixed(2)}% · 数据到 T 日收盘</div>

<div class="dw-kv">
 <div><span>T 日股价</span><b>${r.p.toFixed(2)}</b>
   <i><em class="${r.chg >= 0 ? 'up' : 'dn'}">${f1(r.chg)}</em></i></div>
 <div><span>研报目标价</span><b>${tpMain}</b><i>${tpMid == null ? '未给价位'
   : `隐含 <em class="${tpMid >= 0 ? 'up' : 'dn'}">${f1(tpMid)}</em>`}</i></div>
 <div><span>27E PE</span><b>${r.p27 == null ? '—' : r.p27.toFixed(1) + '×'}</b>
   <i>${r.e27 == null ? '' : 'EPS ' + r.e27.toFixed(2)}</i></div>
 <div><span>覆盖机构</span><b>${new Set(reps.map(x => x[1])).size} 家</b>
   <i>近 180 天 ${reps.length} 份研报${r.eo ? ` · ${r.eo} 家做盈利预测` : ''}</i></div>
</div>

<div class="dw-tier"><span class="mood-tag mt-${r.tier}">${esc0(r.lvl)}</span>
 <div class="dw-key">${esc0(r.k)}</div>
 <div class="dw-risk"><b>风险</b>　${esc0(r.rk)}</div>
</div>

<div class="dw-sec">三年一致预期<em>26E / 27E / 28E　EPS 与对应 PE（东财 F10「近六月平均」）</em></div>
<div class="dw-eps">${epsRow}</div>

<div class="dw-sec">研报明细<em>近 180 天共 ${reps.length} 份 · 按日期倒序 · 标题可点开原文</em></div>`;

  if(!reps.length){
    h += `<div class="dw-none">该股近 180 天在东方财富研报中心<b>没有任何个股研报</b>，
因此也没有评级与目标价可拆 —— 表格里的目标价来自更早的研报或行业周报点名。<br>
<a href="${EM}" target="_blank" rel="noopener">到东财研报中心按代码 ${r.c} 查更早的 →</a></div>`;
  } else {
    h += reps.map((x, i) => {
      const org = ORGS[x[1]] || '', rat = RATS[x[2]] || '', lrat = x[3] >= 0 ? RATS[x[3]] : '';
      let rmk = '';
      if(rat && lrat && RK[rat] != null && RK[lrat] != null && RK[rat] !== RK[lrat])
        rmk = RK[rat] > RK[lrat] ? `<em class="up">↑ 前次${lrat}</em>`
                                 : `<em class="dn">↓ 前次${lrat}</em>`;
      let tpm = '';
      const ptp = prev[i];
      if(x[4] != null && ptp != null && Math.abs(ptp - x[4]) > 1e-9){
        const pc = (x[4] / ptp - 1) * 100;
        tpm = `<i class="${pc > 0 ? 'up' : 'dn'}">${pc > 0 ? '↑' : '↓'} 前次 ${pfmt(ptp)} ${f1(pc)}</i>`;
      }
      const tpTxt = x[4] == null ? '<span class="rr-tp mut">未给目标价</span>'
        : `<span class="rr-tp">目标 ${pfmt(x[4])}${tpm}</span>`;
      const epsTxt = [x[6], x[7], x[8]].map(v => v == null ? '—' : v.toFixed(2)).join(' / ');
      const ttl = x[10]
        ? `<a class="rr-t" href="https://data.eastmoney.com/report/zw_stock.jshtml?infocode=${encodeURIComponent(x[10])}" target="_blank" rel="noopener">${esc0(x[9])}</a>`
        : `<span class="rr-t">${esc0(x[9])}</span>`;
      return `<div class="rr">
 <div class="rr-h"><span class="rr-d">${x[0]}</span><b>${esc0(org)}</b>` +
   (x[11] ? `<span class="rr-per">${esc0(x[11])}</span>` : '') +
   (rat ? `<span class="rr-rat">${rat}${rmk}</span>` : '') + tpTxt + `</div>
 ${ttl}
 <div class="rr-e">EPS ${epsTxt}　→　PE ${[x[6], x[7], x[8]].map((v, k) =>
   v && v > 0 ? (r.p / v).toFixed(1) + '×' : '—').join(' / ')}</div>
</div>`;
    }).join('');
  }

  h += `<div class="dw-src"><b>本行数据源</b>
① 目标价与情绪判断：人工逐份核验的券商研报（发布机构与日期已标在表格「研报目标价范围」列下方）；
② 研报明细与本页所有原文链接：<a href="${EM}" target="_blank" rel="noopener">东方财富研报中心</a>（reportapi，近 180 天）；
③ 三年一致预期：<a href="https://emweb.securities.eastmoney.com/PC_HSF10/ProfitForecast/Index?type=web&code=${pre(r.c)}" target="_blank" rel="noopener">东财 F10 盈利预测</a>（${r.c} 原始页面）；
④ T 日收盘：腾讯行情（不复权成交价）；⑤ 目标价口径另用通达信 F10 研报库抽样交叉核对。
</div>
<div class="dw-foot">研报标题可点击，跳转东方财富研报详情页（新窗口）；关闭本面板按 Esc 或点右上角 ×。<br>
EPS / PE 为该份研报原文口径（PE = T 日收盘 / 该年 EPS）；「前次」指同一机构上一份给出数值目标价的研报，非券商自述的上次目标价。</div>`;

  document.getElementById('drwb').innerHTML = h;
  document.getElementById('drw').classList.add('on');
  document.getElementById('drwm').classList.add('on');
  document.body.style.overflow = 'hidden';
  document.getElementById('drw').scrollTop = 0;
}

function closeDrw(){
  document.getElementById('drw').classList.remove('on');
  document.getElementById('drwm').classList.remove('on');
  document.body.style.overflow = '';
}

document.getElementById('drwm').onclick = closeDrw;
document.getElementById('drwx').onclick = closeDrw;
const tb = document.querySelector('table.mood');
if(tb) tb.addEventListener('click', function(e){
  const b = (e.target && e.target.closest) ? e.target.closest('.stk') : null;
  if(b && b.dataset && b.dataset.c) openStock(b.dataset.c);
});
document.addEventListener('keydown', function(e){ if(e.key === 'Escape') closeDrw(); });
window.__moodOpen = openStock;   /* 便于离线验证/调试，不影响页面行为 */
})();
"""

CSS = """
<style>
/*MOOD-CSS-BEGIN*/
.mood-note{background:#fbfcfd;border:1px solid var(--bd);border-left:3px solid var(--ac2);
 border-radius:8px;padding:10px 14px;font-size:13px;color:#4b5563;margin:10px 0 14px;line-height:1.72}
.mood-note b{color:var(--tx)}
.mood-kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.mood-kpi .k{border:1px solid var(--bd);border-radius:9px;padding:9px 12px;background:#fcfcfd}
.mood-kpi .k i{display:block;font-style:normal;font-size:12px;color:var(--mut);margin-bottom:3px}
.mood-kpi .k b{font-size:19px;font-variant-numeric:tabular-nums}
.mood-kpi .k u{display:block;text-decoration:none;font-size:11px;color:#9ca3af;margin-top:2px}
.mood-wrap{overflow-x:auto;border:1px solid var(--bd);border-radius:9px}
table.mood{width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed;min-width:1120px}
table.mood th{background:#f3f4f6;font-weight:600;text-align:left;padding:9px 11px;
 border-bottom:1px solid var(--bd);font-size:12.5px;color:#374151;white-space:nowrap}
table.mood th .thsub{display:block;font-weight:400;font-size:10.5px;color:#9ca3af;
 margin-top:1px;white-space:normal;line-height:1.35}
table.mood td{padding:11px;border-bottom:1px solid #eef0f2;vertical-align:top}
table.mood tr:last-child td{border-bottom:none}
table.mood tbody tr:hover td{background:#fafbfc}
.mood-stk b{font-size:14px;display:block;line-height:1.35}
/* 个股名做成超链按钮：点击开右侧研报抽屉（不是跳页，避免离开长页面）*/
.mood-stk .stk{display:inline-block;font-size:14px;font-weight:600;line-height:1.35;
 color:var(--ac2);background:none;border:0;padding:0;font-family:inherit;cursor:pointer;
 text-align:left;border-bottom:1px dashed #b9cde0;transition:color .12s,border-color .12s}
.mood-stk .stk:hover{color:#123a5c;border-bottom-color:#123a5c}
.mood-stk .stk::after{content:'\\203A';margin-left:3px;color:#c3c8d0;font-weight:400}
.mood-stk .stk:hover::after{color:#123a5c}
/* 三年 EPS / PE：三行网格，EPS 右对齐、PE 右对齐，都走等宽数字 */
.mood-ep{font-size:12px}
.epsg{display:grid;grid-template-columns:26px 1fr 1fr;gap:1px 4px;font-size:11.8px;
 font-variant-numeric:tabular-nums;align-items:baseline}
.epsg .y{color:#9ca3af;font-size:11px}
.epsg b{font-weight:600;text-align:right;color:var(--tx)}
.epsg i{font-style:normal;text-align:right;color:#4b5563}
.epsg .hdr,.epsg .hdr b,.epsg .hdr i{color:#b0b7c0;font-size:10.5px;font-weight:400}
.epsf{font-size:11.5px;color:#8a929e;margin-top:5px;display:flex;justify-content:space-between;
 gap:6px}
.epsf b{font-weight:600}
.loss{color:#a52a1e;font-weight:600;font-size:11.5px}
/* 数据源条：四个来源各给一个可点入口 */
.mood-srcbar{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin:0 0 12px;
 font-size:11.5px;color:#8a929e}
.mood-srcbar span.lb{font-weight:600;color:#6b7280}
.mood-srcbar a{display:inline-block;border:1px solid var(--bd);border-radius:6px;
 padding:2px 8px;color:#4b5563;text-decoration:none;background:#fcfcfd;line-height:1.7}
.mood-srcbar a:hover{border-color:#b9cde0;color:var(--ac2);background:#f5f9fd}
.mood-srcbar i{font-style:normal;color:#b0b6bf}
.mood-code{display:block;font-size:11.5px;color:#9ca3af;margin-top:3px;font-variant-numeric:tabular-nums}
.mood-px b{font-size:15px;display:block;font-variant-numeric:tabular-nums}
.mood-px span{display:block;font-size:12px;margin-top:2px;font-variant-numeric:tabular-nums}
.mood-tp b{font-variant-numeric:tabular-nums}
.mood-imp{display:block;font-size:12px;margin-top:2px;font-weight:600}
.mood-src{font-size:11.5px;color:#9ca3af;line-height:1.55;margin-top:5px}
.mood-tag{display:inline-block;border-radius:5px;padding:2px 8px;font-size:11.5px;
 font-weight:600;line-height:1.6;margin-bottom:6px}
.mt-bull{background:#fdecea;color:#c0392b;border:1px solid #f5c6c2}
.mt-split{background:#fff7ed;color:#b45309;border:1px solid #fde3c4}
.mt-warn{background:#eef2f7;color:#3f4a5a;border:1px solid #dbe3ec}
.mt-none{background:#f3f4f6;color:#6b7280;border:1px solid #e5e7eb}
.mood-key{font-size:12.5px;line-height:1.72;color:#374151}
.mood-risk{font-size:12px;line-height:1.62;color:#7b4a4a;margin-top:6px;
 padding-top:6px;border-top:1px dashed #eceef1}
.mood-risk b{color:#c0392b;font-weight:600}
.mood-sum{margin-top:16px;border:1px solid var(--bd);border-radius:9px;
 background:#fbfcfd;padding:12px 15px}
.mood-sum h4{margin:0 0 8px;font-size:13.5px;color:var(--tx)}
.mood-sum ol{margin:0;padding-left:20px;font-size:13px;line-height:1.85;color:#374151}
.mood-sum li{margin-bottom:5px}
.mood-sum li b{color:var(--tx)}
@media(max-width:760px){
 /* 窄屏不压扁：保持表格横向滚动。
    注意别在这里 display:none 隐藏某一列 —— table-layout:fixed + colgroup 下
    隐藏 th 会让后面的 th 依次错拿前一列宽度（实测第3列只剩 8.5%），表格列全部错位。 */
 table.mood{min-width:780px}}
/* 滚动更新：情绪或逻辑出现重大变化的那一行整体标红（红底 + 左侧红边 + 红色徽标）*/
.mood-kpi .k b.hotv{color:#c0392b}
.mood-hot td{background:#fffafa}
.mood-hot td:first-child{box-shadow:inset 3px 0 0 #c0392b}
.mood-hot:hover td{background:#fff5f3}
.mood-flag{display:block;font-size:11.5px;line-height:1.6;color:#c0392b;background:#fdf1ef;
 border:1px solid #f6cfc9;border-radius:5px;padding:4px 8px;margin-bottom:6px}
.mood-flag b{color:#a52a1e;font-weight:700}
.mood-flag u{text-decoration:none;color:#b06a60;margin-left:6px;font-variant-numeric:tabular-nums}
.mood-flag.mf-up{border-color:#f0b8b0}
.mood-flag.mf-up b{color:#c0392b}
b.hl{color:#c0392b;font-weight:700}
/* ---------- 个股研报抽屉（点个股名滑出） ---------- */
.drw-mask{position:fixed;inset:0;background:rgba(17,24,39,.40);opacity:0;pointer-events:none;
 transition:opacity .18s;z-index:60}
.drw-mask.on{opacity:1;pointer-events:auto}
.drw{position:fixed;top:0;right:0;height:100%;width:min(860px,96vw);background:#fff;z-index:61;
 box-shadow:-20px 0 54px rgba(15,23,42,.20);transform:translateX(101%);
 transition:transform .22s cubic-bezier(.32,.72,.28,1);display:flex;flex-direction:column}
.drw.on{transform:translateX(0)}
.drw-in{overflow-y:auto;padding:20px 26px 44px;flex:1}
.dw-x{position:absolute;top:14px;right:16px;width:30px;height:30px;border:1px solid var(--bd);
 background:#fff;border-radius:8px;font-size:17px;line-height:1;color:#6b7280;cursor:pointer}
.dw-x:hover{background:#f3f4f6;color:var(--tx)}
.dw-h{padding-right:44px}
.dw-h h2{margin:0;font-size:19px;letter-spacing:-.2px}
.dw-h h2 span{font-size:12.5px;color:var(--mut);font-weight:400;margin-left:8px;
 font-variant-numeric:tabular-nums}
.dw-sub{color:var(--mut);font-size:12px;margin-top:4px}
.dw-kv{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--bd);
 border:1px solid var(--bd);border-radius:9px;overflow:hidden;margin:14px 0 12px}
.dw-kv>div{background:#fbfcfd;padding:9px 12px}
.dw-kv span{display:block;font-size:11px;color:var(--mut)}
.dw-kv b{display:block;font-size:15px;font-variant-numeric:tabular-nums;letter-spacing:-.2px}
.dw-kv i{display:block;font-style:normal;font-size:11px;color:var(--mut);
 font-variant-numeric:tabular-nums;line-height:1.5}
.dw-kv i em{font-style:normal;font-weight:500}
.dw-tier{border:1px solid var(--bd);border-radius:9px;padding:11px 13px;margin-bottom:16px}
.dw-key{font-size:13px;margin-top:7px;line-height:1.75}
.dw-risk{font-size:12px;color:#6b7280;margin-top:6px;line-height:1.7}
.dw-risk b{color:#a52a1e;font-weight:600}
.dw-sec{font-size:13px;font-weight:600;margin:18px 0 9px;padding-bottom:6px;
 border-bottom:1px solid var(--bd);display:flex;align-items:baseline;gap:8px}
.dw-sec em{font-style:normal;font-weight:400;font-size:11.5px;color:var(--mut)}
.dw-eps{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.dw-eps>div{border:1px solid var(--bd);border-radius:8px;padding:8px 11px;background:#fbfcfd}
.dw-eps span{display:block;font-size:11px;color:var(--mut)}
.dw-eps b{font-size:14.5px;font-variant-numeric:tabular-nums}
.dw-eps i{font-style:normal;font-size:12px;color:#6b7280;margin-left:6px;
 font-variant-numeric:tabular-nums}
.dw-none{color:var(--mut);font-size:12.5px;padding:14px 2px;line-height:1.8}
.dw-none a{color:var(--ac2)}
.rr{border-bottom:1px solid #f0f1f3;padding:9px 2px 10px}
.rr:last-child{border-bottom:0}
.rr-h{display:flex;align-items:center;gap:9px;flex-wrap:wrap;font-size:12px;color:#4b5563}
.rr-d{font-variant-numeric:tabular-nums;color:var(--mut);font-size:11.5px}
.rr-h b{font-size:12.5px;color:var(--tx);font-weight:600}
.rr-per{color:#9ca3af;font-size:11px}
.rr-rat{background:#f3f4f6;border-radius:4px;padding:1px 6px;font-size:11px;color:#374151}
.rr-rat em{font-style:normal;margin-left:4px;font-size:10.5px}
.rr-tp{font-variant-numeric:tabular-nums;font-size:12px;color:#374151;flex-shrink:0;margin-left:auto}
.rr-tp i{font-style:normal;margin-left:5px;font-size:11px}
.rr-tp.mut{color:#b0b6bf;font-size:11.5px}
.rr-t{display:block;font-size:13px;color:var(--ac2);text-decoration:none;margin-top:5px;line-height:1.55}
a.rr-t:hover{text-decoration:underline}
.rr-t:not(a){color:var(--tx)}
.rr-e{font-size:11px;color:#9ca3af;margin-top:4px;font-variant-numeric:tabular-nums}
.dw-src{margin-top:18px;border:1px solid var(--bd);border-radius:9px;padding:10px 13px;
 background:#fbfcfd;font-size:11.5px;color:#6b7280;line-height:1.9}
.dw-src b{color:var(--tx);font-weight:600;display:block;margin-bottom:3px;font-size:12px}
.dw-src a{color:var(--ac2);text-decoration:none}
.dw-src a:hover{text-decoration:underline}
.dw-foot{margin-top:14px;font-size:11px;color:#9ca3af;line-height:1.8}
.up{color:#c0392b}.dn{color:#0f7b52}
@media(max-width:820px){.dw-kv{grid-template-columns:repeat(2,1fr)}
 .drw-in{padding:16px 15px 40px}.rr-tp{margin-left:0;width:100%}}
/*MOOD-CSS-END*/
</style>
"""


def build(d, ext=None, ext_meta=None):
    ext = ext or {}
    ext_meta = ext_meta or {}
    m = d["meta"]
    rows = d["rows"]
    s = stats(rows)
    n_eps = sum(1 for r in rows
                if any(v is not None for v in cons_of(ext.get(r["code"]))[0]))
    n_rep = sum(len((ext.get(r["code"]) or {}).get("reports") or []) for r in rows)

    kpis = [
        ("有明确目标价", f'{s["n_has"]} / {s["n"]}', "研报中写出的具体价位"),
        ("目标价中位隐含空间", pct(s["median"]), "按区间中值对 T 日收盘价"),
        ("三年一致预期", f'{n_eps} / {s["n"]}', "有 26E–28E 的 EPS 与对应 PE"),
        ("目标价较前次下调", f'{len(s["down"])} 只', "研报中括号内标注的前值更高"),
        ("无个股研报覆盖", f'{s["n_none"]} 只', "含无评级、有评级无价位、价位无法溯源"),
    ]
    if s["n_flag"]:
        kpis.insert(0, ("本期重大变化", f'{s["n_flag"]} 只',
                        "情绪或逻辑较上次更新有实质变动，行内标红"))
    kpi_html = "".join(
        f'<div class="k"><i>{esc(a)}</i><b{(" class=\'hotv\'" if a == "本期重大变化" else "")}>{esc(b)}</b><u>{esc(c)}</u></div>'
        for a, b, c in kpis)

    note = (
        f'本表列出质量 Top28 组合<b>最新一期（{m["rebal_date"]} 调仓）</b>的全部 {m["n_holdings"]} 只持仓，'
        f'股价为 <b>T 日 {m["t_date"]}</b> 收盘（不复权成交价）。目标价取自 <b>{m["report_from"]} ~ {m["report_to"]}</b>'
        f'（本次调仓前后一个完整季报窗口）券商研报中<b>写明的具体价位</b>，并保留其发布机构与日期。'
        f'<br>「未来三年 EPS / PE」为<b>东财 F10 一致预期</b>（近六月平均）的 26E / 27E / 28E，'
        f'PE 一律用 T 日收盘自算；EPS ≤ 0 不给负 PE，改标「仍亏损」。'
        f'<b>点个股名</b>可展开该股近 180 天的全部研报明细（机构、日期、评级、目标价、当时 EPS），'
        f'每条标题都能点开东财原文。'
        f'<br>「市场情绪」一列不复述研报标题，而是拆开看三件事：'
        f'<b>盈利预测往哪个方向改</b>、<b>目标价与现价的距离是否被上调/下调维持</b>、'
        f'<b>评级措辞与当期业绩之间有没有落差</b>。'
        f'标题写「买入」但盈利预测连降、或目标价隐含 70% 空间却三个月未动、'
        f'或买入评级建立在资产处置而非经营之上的，都在这一列点名。'
        f'<br><b>本表按交易日滚动更新</b>：股价每日刷新，研报与情绪判断随新研报重估。'
        f'某只票的<b>情绪档位</b>或<b>关键逻辑</b>较上一次更新出现实质变化时'
        f'（评级/目标价方向反转、盈利预测大幅修正、业绩与叙事背离、覆盖转空或转多），'
        f'该行整行标红，情绪列顶部给出变化说明与变化日期，关键句以<b class="hl">红色加粗</b>标出。'
        f'标红只表示「变了」，不表示好坏。'
    )

    srcbar = (
        '<div class="mood-srcbar"><span class="lb">数据源</span>'
        f'<a href="{EM_RPT}" target="_blank" rel="noopener">研报原文 · 东财研报中心</a>'
        '<i>三年一致预期 · 东财 F10「近六月平均」（逐只入口在个股抽屉里）</i>'
        '<i>行情 · 腾讯（T 日不复权收盘）</i>'
        '<i>目标价口径 · 人工逐份核验，另用通达信 F10 研报库抽样交叉核对</i></div>'
    )

    # 权重聚合：周期资源类（铝/煤/电/钨铟）
    cyc = {"601600", "000807", "000933", "601001", "600546", "601991", "600578", "600961", "600397"}
    cyc_w = sum(r["weight"] for r in rows if r["code"] in cyc)

    summary = f"""<div class="mood-sum">
<h4>看完 19 份研报后的四个判断</h4>
<ol>
<li><b>组合的卖方叙事高度集中在周期资源。</b>铝（中国铝业、云铝、神火）、煤（晋控煤业、山煤国际）、
电（大唐发电、京能电力）、钨铟（株冶、江钨）合计 {cyc_w:.1f}% 权重，超过一半。这解释了为什么
「目标价隐含空间」整体看着不错——它们吃的是同一条商品价格链，一旦商品转向，{len(rows)} 只里的这一半会同步回撤，
分散度远低于 19 只这个数字给人的感觉。</li>
<li><b>目标价整体在往下修，而不是往上修。</b>{len(s["down"])} 只明确下调（晋控煤业 24.12→21.65、
云铝 39.90→33.92、爱美客 26 年净利被砍 26%、隆鑫四家里三家在降），只有 2 只上调（京能 5.57→6.08、TCL 7.4→8.00）。
周期股的下调尤其值得注意：云铝是「业绩创历史最好、目标价反而降」，因为可比公司 PE 从 10 倍压到 8.5 倍——
盈利在涨、估值在缩，这类票的多头逻辑只能是业绩不能是估值。</li>
<li><b>有三只「买入评级」经不起对照。</b>大悦城两家买入/增持，但 26H1 归母 −7.23 亿、结算毛利率腰斩、
销售 −54.9%，买的是 REITs 出表的一次性收益；江钨装备被给「买入」，可上半年营收 −93.73%、归母仅 120 万，
赌的是尚未完成的 18.98 亿并购；株冶集团的「45 元一致目标价」在检索范围内找不到任何一篇研报可以溯源，
它的真实逻辑只是铟价，而铟的定价权不在国内冶炼厂手里。</li>
<li><b>真正「评级、目标价、当期业绩」三者对得上的只有三只。</b>滨江集团（净现金、融资成本 2.8%、
三家目标价 11.15~13.00 方向一致）、京能电力（Q2 在电价跌煤价涨下仅 −1.3%，被上调目标价）、
神火股份（前三季归母 +114.5%、PE 6~7 倍；但要注意 Q3 计提了 4.13 亿矿山减值）。
三只的共同点不是弹性大，而是<b>现金流与分红能落地</b>。</li>
</ol>
<div class="muted" style="margin-top:9px;font-size:12px">
口径提醒：券商目标价是 6~12 个月视角的卖方观点，且存在「只调盈利不调目标价」的滞后习惯；
本表把它们摆在一起是为了看<b>分歧方向</b>，不是当作价格预测。表中的三年 EPS 是<b>卖方一致预期</b>
而非公司指引，周期股的 28E 尤其容易随商品价格整体平移，看增速不如看 26E 的绝对水平与估值。
「无覆盖」不等于公司质地差，只代表当前没有卖方在做跟踪——这本身也是一种信息。</div>
</div>"""

    data_js, rep_js, orgs_js, rats_js = pack_js(rows, ext)
    js = (DWR_JS
          .replace("__DATA__", dump_js(data_js))
          .replace("__REP__", dump_js(rep_js))
          .replace("__ORGS__", dump_js(orgs_js))
          .replace("__RATS__", dump_js(rats_js)))

    return f"""{CSS}
<h2>六、市场情绪展望</h2>
<div class="card">
<div class="card-h"><h3>最新一期持仓 · 卖方目标价与情绪拆解</h3>
<span class="pill">{m["n_holdings"]} 只 · {m["rebal_date"]} 调仓 · T 日 {m["t_date"]}</span></div>
<div class="mood-note">{note}</div>
<div class="mood-kpi">{kpi_html}</div>
{srcbar}
<div class="mood-wrap"><table class="mood">
<colgroup><col style="width:14%"><col style="width:8.5%"><col style="width:20%"><col style="width:15%"><col style="width:42.5%"></colgroup>
<thead><tr><th>个股<span class="thsub">组合权重 · 点名称看研报</span></th><th>T 日股价<span class="thsub">不复权</span></th><th>研报目标价范围<span class="thsub">机构与日期可溯源</span></th><th>未来三年 EPS / PE<span class="thsub">26E–28E 一致预期</span></th><th>市场情绪<span class="thsub">{n_rep} 份研报逐条可查</span></th></tr></thead>
<tbody>
{"".join(row_html(r, ext) for r in rows)}
</tbody></table></div>
{summary}
</div>
<div class="drw-mask" id="drwm"></div>
<aside class="drw" id="drw"><button class="dw-x" id="drwx" title="关闭（Esc）">×</button><div class="drw-in" id="drwb"></div></aside>
<script>{js}</script>
"""


def dump_js(o):
    """内联进 <script> 的 JSON：避免 </script> 提前闭合，中文不转义省体积。"""
    return json.dumps(o, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=DEFAULT_JSON)
    ap.add_argument("--ext", default=DEFAULT_EXT)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()
    with open(a.json, encoding="utf-8") as f:
        d = json.load(f)
    ext, ext_meta = load_ext(a.ext)
    if not ext:
        print(f"! 缺 {a.ext}，EPS 列将全部显示「无盈利预测」（先跑 fetch_mood_ext.py）", flush=True)
    h = build(d, ext, ext_meta)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(h)
    s = stats(d["rows"])
    n_eps = sum(1 for r in d["rows"]
                if any(v is not None for v in cons_of(ext.get(r["code"]))[0]))
    print(f"OK -> {a.out}  ({len(h)} 字符, {s['n']} 行)")
    print(f"   有目标价 {s['n_has']} / 无 {s['n_none']} / 中位隐含 {s['median']:+.1f}% / 下调 {len(s['down'])}")
    print(f"   三年一致预期 {n_eps} / {s['n']}；研报明细 "
          f"{sum(len((ext.get(r['code']) or {}).get('reports') or []) for r in d['rows'])} 条")


if __name__ == "__main__":
    main()
