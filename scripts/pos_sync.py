# -*- coding: utf-8 -*-
"""sync_pos.py —— 每日重算 CSFM/TSFM 建议仓位并回写股池页面（幂等，可本地/云端跑）

页面已有「四、CSFM 和 TSFM 历史仓位建议」模块时：只替换 var POS 数据、
刷新 5.1/5.2 持仓表里 16 个仓位方框的数值、更新图例里的「当前 xx%」，其余内容不动。
模块不存在时不插入（首次插入用 patch_pool.py），直接报错退出，避免误改。

用法：
    python sync_pos.py --page <html>                 # 只重算并写回本地文件
    python sync_pos.py --page <html> --upload        # 另上传资料库（覆写同一节点）
    python sync_pos.py --page <html> --upload --publish
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
NODE_ID = "iB8I58mCTooLicPQ0Kyq0M"
LIB = os.environ.get("WB_LIBRARY_SKILL") or (
    "C:/Users/12066/AppData/Local/Programs/WorkBuddy/resources/app.asar.unpacked/"
    "resources/plugins/workbuddy-builtin/skills/library")


def log(m):
    print(m, flush=True)


def positions_from_nav(dates, nav_cs, nav_ts, fbook: pd.Series | None):
    """R1 过热 / R2 均线 / R3 反馈强度门控（仅 TSFM），取最小值；T 日决策 → T+1 生效。"""
    idx = pd.DatetimeIndex(dates)

    def rules(nav):
        s = pd.Series(nav, index=idx, dtype=float)
        g60 = s / s.shift(60) - 1
        ma60 = s.rolling(60, min_periods=20).mean()
        r1 = pd.Series(1.0, index=idx)
        r1[g60 >= 0.5] = 0.6
        r1[g60 >= 0.8] = 0.4
        r2 = pd.Series(1.0, index=idx)
        r2[s < ma60] = 0.5
        return r1, r2, s

    r1, r2, _ = rules(nav_cs)
    g_cs = pd.concat([r1, r2], axis=1).min(axis=1)

    r1, r2, _ = rules(nav_ts)
    g_ts = pd.concat([r1, r2], axis=1).min(axis=1)
    if fbook is not None and len(fbook):
        fm = fbook.dropna().resample("ME").last().dropna()
        fz = (fm - fm.rolling(24, min_periods=12).mean()) / fm.rolling(24, min_periods=12).std()
        fzd = fz.reindex(idx, method="ffill")
        r3 = pd.Series(1.0, index=idx)
        r3[fzd >= 1.0] = 0.65
        r3[fzd >= 1.5] = 0.45
        g_ts = pd.concat([g_ts, r3], axis=1).min(axis=1)
    else:
        log("  ! 缺 fbook：TSFM 只用「过热+均线」两档，与已发布口径不一致")

    out = pd.DataFrame({
        "因子动量CSFM": g_cs.shift(1).fillna(g_cs.iloc[0]),
        "因子动量TSFM": g_ts.shift(1).fillna(g_ts.iloc[0]),
    })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True)
    ap.add_argument("--download", action="store_true", help="先拉取线上页面覆盖 --page")
    _fb = [os.path.join(HERE, "..", "cloud", "state", "fbook_monthly.csv"),
           os.path.join(HERE, "..", "data", "fbook_monthly.csv")]
    ap.add_argument("--fbook", default=next((p for p in _fb if os.path.exists(p)), _fb[0]))
    ap.add_argument("--out", default="")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args()

    if a.download:
        d = os.path.dirname(os.path.abspath(a.page))
        os.makedirs(d, exist_ok=True)
        r = subprocess.run([sys.executable, os.path.join(LIB, "page", "download_page_artifacts.py"),
                            "--node-id", NODE_ID, "--out-dir", d], capture_output=True, text=True)
        if r.returncode != 0:
            log("下载线上页面失败：" + (r.stdout or r.stderr)[-400:])
            return 3
        hs = [x for x in os.listdir(d) if x.lower().endswith((".html", ".htm"))]
        if len(hs) == 1:
            a.page = os.path.join(d, hs[0])
        log("  已拉取线上页面 → " + a.page)

    h = open(a.page, encoding="utf-8").read()
    if 'id="posChart"' not in h:
        log("页面里没有仓位建议模块，先用 patch_pool.py 做首次插入")
        return 2

    # ---- BT 净值
    i = h.find("var BT=") + len("var BT=")
    j = h.find(";;", i)
    bt = json.loads(h[i:j])
    dates = pd.to_datetime(bt["dates"])

    # ---- 持仓加权 F（月度，来自本金/云端同口径）
    fbook = None
    if os.path.exists(a.fbook):
        fb = pd.read_csv(a.fbook, index_col=0, parse_dates=True)
        col = fb.columns[0]
        fbook = fb[col]
        log("  fbook 覆盖 %s ~ %s，%d 个月" % (fbook.index.min().date(), fbook.index.max().date(), len(fbook)))
    pos = positions_from_nav(dates, bt["series"]["因子动量CSFM"], bt["series"]["因子动量TSFM"], fbook)

    # ---- 指数序列：本地 csv 优先，缺失时保留页面里的旧值
    zz = cyb = None
    cands = [lambda n: os.path.join(HERE, "..", "cloud", "state", n),
             lambda n: os.path.join(HERE, n), lambda n: os.path.join(HERE, "..", "data", n)]
    for fn, name in [("idx_932000.csv", "zz"), ("idx_399006.csv", "cyb")]:
        f = next((p for p in (c(fn) for c in cands) if os.path.exists(p)), "")
        if f:
            s = pd.read_csv(f, index_col=0, parse_dates=True)["close"].reindex(dates).ffill()
            if name == "zz":
                zz = s
            else:
                cyb = s
    m = re.search(r"var POS=(\{[\s\S]*?\});", h)
    old = json.loads(m.group(1))
    if zz is None:
        zz = pd.Series(old["zz"], index=dates)
        log("  · 中证2000 用页面旧值（未找到 idx_932000.csv）")
    if cyb is None:
        cyb = pd.Series(old["cyb"], index=dates)
        log("  · 创业板指 用页面旧值")

    data = {
        "dates": [d.strftime("%Y-%m-%d") for d in dates],
        "csfm": [int(round(x * 100)) for x in pos["因子动量CSFM"]],
        "tsfm": [int(round(x * 100)) for x in pos["因子动量TSFM"]],
        "zz": [round(float(x), 2) for x in zz],
        "cyb": [round(float(x), 2) for x in cyb],
    }
    blob = "var POS=%s;" % json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    h = h[:m.start()] + blob + h[m.end():]

    # ---- 图例里的当前仓位
    def set_cur(txt, val):
        return re.sub(r"(当前 )\d+%", r"\g<1>%d%%" % val, txt)

    seg_start = h.find("四、CSFM 和 TSFM 历史仓位建议")
    seg_end = h.find("五、持仓变动明细")
    seg = h[seg_start:seg_end]
    seg2 = re.sub(r"(CSFM 建议仓位（当前 )\d+%", r"\g<1>%d%%" % data["csfm"][-1], seg)
    seg2 = re.sub(r"(TSFM 建议仓位（当前 )\d+%", r"\g<1>%d%%" % data["tsfm"][-1], seg2)
    h = h[:seg_start] + seg2 + h[seg_end:]

    # ---- 持仓表里的仓位方框
    a1 = h.find("5.1\u3000因子动量·横截面 CSFM")
    a2 = h.find("5.2\u3000因子动量·时间序列 TSFM")
    a3 = h.find("5.3\u3000质量Top28组合")
    n = 0

    def fix2(seg, col):
        """按「仓位 xx%」文本定位，向前找最近的调仓日，替换数值（兼容 import 后新增的属性/注释）。"""
        nonlocal n
        out, last = [], 0
        for mm in re.finditer(r'(?:<!--pnid:[^>]*-->)?仓位 (\d+)%', seg):
            head = seg[max(0, mm.start() - 600): mm.start()]
            ds = re.findall(r'\d{4}-\d{2}-\d{2}', head)
            if not ds:
                continue
            d = pd.Timestamp(ds[-1])
            if d not in pos.index:
                continue
            v = int(round(pos.loc[d, col] * 100))
            out.append(seg[last:mm.start()])
            out.append(mm.group(0)[:mm.start(1) - mm.start()] + str(v) + "%")
            last = mm.end()
            n += 1
        out.append(seg[last:])
        return "".join(out)

    seg = fix2(h[a1:a2], "因子动量CSFM")
    h = h[:a1] + seg + h[a2:]
    a2 = h.find("5.2\u3000因子动量·时间序列 TSFM")
    a3 = h.find("5.3\u3000质量Top28组合")
    seg = fix2(h[a2:a3], "因子动量TSFM")
    h = h[:a2] + seg + h[a3:]

    out = a.out or a.page
    open(out, "w", encoding="utf-8").write(h)
    log("✓ 已更新：%d 个仓位方框；当前仓位 CSFM %d%% / TSFM %d%%；最新交易日 %s"
        % (n, data["csfm"][-1], data["tsfm"][-1], data["dates"][-1]))

    if a.upload:
        r = subprocess.run([sys.executable, os.path.join(LIB, "page", "import_html.py"), out,
                            "--file-name", os.path.basename(out), "--node-block-id", NODE_ID],
                           capture_output=True, text=True)
        log(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-400:])
    if a.publish:
        r = subprocess.run([sys.executable, os.path.join(LIB, "page", "publish_page.py"),
                            "--node-id", NODE_ID], capture_output=True, text=True)
        log("已重新发布：" + (r.stdout.strip().splitlines()[-1][:120] if r.stdout.strip() else r.stderr[-300:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
