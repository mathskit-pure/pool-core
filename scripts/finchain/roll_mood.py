# -*- coding: utf-8 -*-
"""第六章《市场情绪展望》滚动更新器：刷股价 + 比对打标 + 存档。

分工说明（很重要）
------------------
研报内容（目标价区间、情绪档位、关键逻辑、风险提示）**没法自动抓**：
目标价散落在各家周报/深度里，还常常「只调盈利不调目标价」，得逐只核验。
那部分由定时任务里的模型检索后直接改写 data/mood_q28.json。

本脚本只做确定性工作，所以它可以被无脑重复执行：
  ① 把 T 日真实收盘价刷到最新（腾讯行情，不复权成交价——和行情软件看到的数字一致）
  ② 与上一份快照比对，情绪档位 / 目标价出现实质变化的行打 flag
  ③ 今天的快照存档到 data/mood_history/，供下次比对

为什不用 data/prices_full_v2.csv：那是**后复权**序列（sh600000 在 2019 年显示 105.62，
601991 显示 13.58），而页面要给用户看的是真实成交价（5.07）。两者差一个复权因子，
混用会让「目标价隐含空间」整列算错——这是本模块最容易出的致命错误，所以单列说明。

「重大变化」的判定（写死在这里，不随运行漂移）
--------------------------------------------
  情绪档位变化   bull/split/warn/none 任一改变          → 必标
  目标价变化     区间中值变动 ≥ TP_CHG_MIN，或从有变无 → 必标
  覆盖情况变化   由有覆盖转为零覆盖（或反向）           → 必标
  措辞变化       mood_level 文字变了但档位没变          → 只提示，不标红
  逻辑变化       模型在 json 里显式写 flag="logic"      → 优先，人工判断盖过自动

flag 会一直保留到「下一次变化」，或超过 --flag-days 天（默认 30）自动清除，
避免三个月后还顶着一个红标记误导人。

用法：
    python scripts/finchain/roll_mood.py                 # 刷价 + 比对 + 存档
    python scripts/finchain/roll_mood.py --dry-run       # 只看会改什么，不写文件
    python scripts/finchain/roll_mood.py --no-price      # 只比对（离线/补数据时用）
"""
import argparse
import glob
import json
import os
import sys
import urllib.request
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE  # noqa: E402

DEFAULT_JSON = os.path.join(BASE, "data", "mood_q28.json")
HISTORY_DIR = os.path.join(BASE, "data", "mood_history")

QTY_URL = "http://qt.gtimg.cn/q="

# 阈值：目标价区间中值变动超过这个幅度才算「重大」
TP_CHG_MIN = 5.0          # %
# flag 保留天数，超期视为已消化
FLAG_DAYS = 30

# 情绪档位严重度：数字越大越差。none（零覆盖）与 warn 同级——
# 覆盖消失是信息缺失，不是变差，硬判方向会误导读者。
SEV = {"bull": 0, "split": 1, "warn": 2, "none": 2}
CLS_NAME = {"bull": "三者对得上", "split": "行业看好·个股无锚",
            "warn": "买入但需拆穿", "none": "零覆盖"}


# --------------------------------------------------------------- 行情
def _prefixed(code):
    """6 位代码 → 腾讯行情前缀。已带前缀的原样返回。"""
    c = str(code).strip().lower()
    if c[:2] in ("sh", "sz", "bj"):
        return c
    if c[0] in "69":
        return "sh" + c
    if c[0] in "03":
        return "sz" + c
    return "bj" + c


def fetch_quotes(codes, timeout=10):
    """批量取最新价。返回 {6位代码: {name, price, chg, date, suspended}}。"""
    out = {}
    uniq = list(dict.fromkeys(str(c).strip().lower()[-6:] for c in codes))
    for i in range(0, len(uniq), 40):
        batch = uniq[i:i + 40]
        url = QTY_URL + ",".join(_prefixed(c) for c in batch)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
        try:
            txt = urllib.request.urlopen(req, timeout=timeout).read().decode("gbk", "replace")
        except Exception as e:                                   # noqa: BLE001
            print(f"  ! 行情批次失败（{len(batch)} 只）：{type(e).__name__} {e}", flush=True)
            continue
        for line in txt.splitlines():
            f = line.split("~")
            if len(f) < 33 or not f[2].isdigit():
                continue
            try:
                px, prev, chg = float(f[3]), float(f[4]), float(f[32])
            except ValueError:
                continue
            out[f[2]] = {
                "name": f[1], "price": px, "prev": prev, "chg": chg,
                "date": f[30][:8],                    # 20261023161443 → 20261023
                "suspended": px <= 0 or prev <= 0,    # 停牌时报价为 0
            }
    return out


def apply_prices(d, quotes, dry=False):
    """把收盘价写回 rows。返回 (取到价的行数, T 日)。"""
    hit, tmax = 0, ""
    for r in d["rows"]:
        q = quotes.get(str(r["code"]).strip().lower()[-6:])
        if not q or q["suspended"]:
            continue
        hit += 1
        tmax = max(tmax, q["date"])
        if not dry:
            r["price"] = round(q["price"], 2)
            r["chg"] = round(q["chg"], 2)
    if tmax and not dry:
        d["meta"]["t_date"] = f"{tmax[:4]}-{tmax[4:6]}-{tmax[6:8]}"
        d["meta"]["source"] = (
            f'{d["meta"].get("report_from", "")} ~ {d["meta"].get("report_to", "")}'
            f' 券商研报；股价为 {d["meta"]["t_date"]} 收盘（不复权，腾讯行情）'
        ).lstrip(" ~")
    return hit, (f"{tmax[:4]}-{tmax[4:6]}-{tmax[6:8]}" if tmax else "")


# --------------------------------------------------------------- 比对
def _tp_mid(r):
    lo, hi = r.get("tp_lo"), r.get("tp_hi")
    if lo is None:
        return None
    return (lo + (hi if hi is not None else lo)) / 2


def _tp_str(r):
    lo, hi = r.get("tp_lo"), r.get("tp_hi")
    if lo is None:
        return "无"
    if hi is None or abs(hi - lo) < 1e-9:
        return f"{lo:.2f}"
    return f"{lo:.2f}~{hi:.2f}"


def auto_flag(prev, cur):
    """比对单只票的上一份快照，返回 (flag, 说明文本, 是否只提示不标红)。"""
    reasons, kind, soft = [], None, False
    pc, cc = prev.get("mood_cls") or "", cur.get("mood_cls") or ""
    pm, cm = _tp_mid(prev), _tp_mid(cur)

    # ① 覆盖状态优先判：零覆盖不是「变差」也不是「变好」，是信息本身没了，
    #    单列一类，避免被档位平移吞掉。（历史数据可能还留着旧的 tp，不能只看 tp）
    if cc == "none" and pc != "none":
        kind = "none"
        reasons.append(f"覆盖转空：{CLS_NAME.get(pc, pc)} → 无个股研报覆盖")
    elif pc == "none" and cc != "none":
        kind = "up"
        reasons.append(f"新增覆盖：{CLS_NAME.get(pc, pc)} → {CLS_NAME.get(cc, cc)}")
    elif pc and cc and pc != cc:
        if SEV.get(cc, 2) > SEV.get(pc, 0):
            kind = "down"
            reasons.append(f"情绪转弱：{CLS_NAME.get(pc, pc)} → {CLS_NAME.get(cc, cc)}")
        elif SEV.get(cc, 2) < SEV.get(pc, 0):
            kind = "up"
            reasons.append(f"情绪转强：{CLS_NAME.get(pc, pc)} → {CLS_NAME.get(cc, cc)}")
        else:
            kind = "logic"
            reasons.append(f"档位平移：{CLS_NAME.get(pc, pc)} → {CLS_NAME.get(cc, cc)}")

    # ② 目标价：只补说明，不覆盖①的方向（情绪变化比价位更靠近「逻辑」）
    if pm and cm:
        delta = (cm / pm - 1) * 100
        if abs(delta) >= TP_CHG_MIN:
            reasons.append(f"目标价 {_tp_str(prev)} → {_tp_str(cur)}（{delta:+.1f}%）")
            if kind is None:
                kind = "down" if delta < 0 else "up"
    elif pm and cm is None and kind is None:
        kind = "none"
        reasons.append(f"目标价撤销（原 {_tp_str(prev)}）")

    # ③ 措辞变了但档位没变：只做提示，不标红（多数是研报口径微调，不值得惊动）
    pl, cl = prev.get("mood_level") or "", cur.get("mood_level") or ""
    if not reasons and pl and cl and pl != cl:
        soft = True
        reasons.append(f"措辞调整：{pl} → {cl}")

    return kind, "；".join(reasons), soft


def days_between(a, b):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (ValueError, TypeError):
        return 10 ** 6


def mark(d, prev_doc, today, flag_days, dry=False):
    """按比对结果打 flag。返回变化清单 [(code, name, flag, txt)]。

    flag_src 用来区分「脚本自动判定」与「模型/人工写死的判断」：
    只有后者能在当天短路自动比对。否则同一天重复跑时，脚本会把自己刚打的标
    又当成「今天的新变化」报一遍，看起来像天天在变。
    """
    prev_by = {str(r["code"]).lower(): r for r in (prev_doc or {}).get("rows", [])}
    changes = []
    for r in d["rows"]:
        code = str(r["code"]).lower()
        p = prev_by.get(code)
        manual = (r.get("flag") or "").strip()
        src = (r.get("flag_src") or "").strip()
        # 「今天新写的人工判断」= 有 flag + 非脚本产出 + 日期是今天 + 上一份快照里没有同样的标。
        # 最后一条是关键：同一个判断在第二次运行时已经在快照里了，就不该再被当成新变化。
        prev_flag = (p or {}).get("flag") or ""
        prev_txt = (p or {}).get("flag_txt") or ""
        already = (prev_flag.strip() == manual
                   and prev_txt == (r.get("flag_txt") or ""))
        manual_today = (manual and src != "auto"
                        and (r.get("flag_at") or "") == today and not already)

        if manual_today:
            # 模型/人工今天刚写的判断优先——它读过研报原文，脚本只看得懂数字
            changes.append((r["code"], r["name"], manual, r.get("flag_txt") or ""))
            continue

        kind, txt, soft = auto_flag(p, r) if p else (None, "", False)

        if kind and not soft:
            if not dry:
                r["flag"], r["flag_txt"], r["flag_at"] = kind, txt, today
                r["flag_src"] = "auto"
            changes.append((r["code"], r["name"], kind, txt))
        elif manual:
            # 本轮没有新变化：旧标红继续留着，但超期就当作已消化
            if days_between(r.get("flag_at") or "", today) > flag_days:
                if not dry:
                    r["flag"], r["flag_txt"], r["flag_at"] = "", "", ""
                    r.pop("flag_src", None)
            else:
                changes.append((r["code"], r["name"], manual,
                                (r.get("flag_txt") or "") + "（往期变化，仍有效）"))
    return changes


# --------------------------------------------------------------- 存档
def latest_snapshot(hist_dir, before):
    """取历史目录里日期 < before 的最新一份。"""
    files = sorted(glob.glob(os.path.join(hist_dir, "*.json")))
    cand = [f for f in files if os.path.basename(f)[:10] < before]
    return cand[-1] if cand else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=DEFAULT_JSON)
    ap.add_argument("--history-dir", default=HISTORY_DIR)
    ap.add_argument("--prev", help="显式指定对比基准（默认取 history 里最新一份）")
    ap.add_argument("--no-price", action="store_true", help="跳过行情刷新")
    ap.add_argument("--flag-days", type=int, default=FLAG_DAYS)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    with open(a.json, encoding="utf-8") as f:
        d = json.load(f)
    today = date.today().isoformat()

    # ① 刷股价
    if not a.no_price:
        q = fetch_quotes([r["code"] for r in d["rows"]])
        hit, t = apply_prices(d, q, a.dry_run)
        n = len(d["rows"])
        flag = "✓" if hit == n else "!"
        print(f"[price] {flag} {hit}/{n} 只取到收盘价，T 日 {t or '(无)'}")
        if hit < n:
            miss = [f'{r["name"]}({r["code"]})' for r in d["rows"]
                    if r["code"].lower()[-6:] not in q or q[r["code"].lower()[-6:]]["suspended"]]
            print(f"        未取到：{'、'.join(miss)}（停牌或代码异常，保留原价）")

    # ② 读基准快照
    prev_path = a.prev or latest_snapshot(a.history_dir, d["meta"]["t_date"])
    prev_doc, new_period = None, False
    if prev_path and os.path.exists(prev_path):
        with open(prev_path, encoding="utf-8") as f:
            prev_doc = json.load(f)
        if prev_doc.get("meta", {}).get("rebal_date") != d["meta"].get("rebal_date"):
            print(f"[diff] 基准快照属于另一期（{prev_doc['meta'].get('rebal_date')}），"
                  f"本期是新调仓，不做跨期比对")
            prev_doc, new_period = None, True
    base_name = os.path.basename(prev_path)[:10] if prev_doc else "无"

    # ③ 打标
    if prev_doc is None:
        if new_period:
            # 换期：上一期的标红全部作废（名单都换了，留着只会误导）
            stale = [r for r in d["rows"] if (r.get("flag") or "").strip()]
            for r in stale:
                if not a.dry_run:
                    r["flag"], r["flag_txt"], r["flag_at"] = "", "", ""
                    r.pop("flag_src", None)
            print(f"[diff] 新一期，清掉 {len(stale)} 处上期标红；本日作为基线")
        else:
            # 只是本地没有历史快照（例如云端首次运行）——**不清标红**：
            # 那些 flag 是上一次滚动算出来、随 Git 一起过来的，清了等于丢信息。
            keep = sum(1 for r in d["rows"] if (r.get("flag") or "").strip())
            print(f"[diff] 本地无历史基准，保留 Git 带来的 {keep} 处标红；本日作为基线")
        changes = []
    else:
        changes = mark(d, prev_doc, d["meta"]["t_date"], a.flag_days, a.dry_run)
        hard = [c for c in changes if "往期变化" not in c[3]]
        print(f"[diff] 基准 {base_name} → 本期 {d['meta']['t_date']}："
              f"{len(hard)} 只出现重大变化")
        icon = {"down": "▼", "up": "▲", "logic": "⚡", "none": "○"}
        for code, name, kind, txt in changes:
            print(f"  {icon.get(kind, '●')} {code} {name}  {txt}")

    # ④ 存档（只存一份基线：同一天重复跑覆盖，不堆文件）
    if not a.dry_run:
        os.makedirs(a.history_dir, exist_ok=True)
        out = os.path.join(a.history_dir, f'{d["meta"]["t_date"]}.json')
        with open(out, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print(f"[archive] {out}")

        d["meta"]["last_roll"] = today
        d["meta"]["n_flag"] = sum(1 for r in d["rows"] if (r.get("flag") or "").strip())
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print(f"[write] {a.json}（标红 {d['meta']['n_flag']} 只）")
    else:
        print("[dry-run] 未写入任何文件")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
