# -*- coding: utf-8 -*-
"""季度股池页 · finchain 链路总入口。

五步产出原版版式的新页面（不改任何 UI 细节）：
    ① daily_nav15.py      选股 + 逐日净值展开
    ② pack_page.py        打包成 out15/page_content.json
    ③ roll_mood.py        第六章滚动：刷 T 日收盘价 + 与上次快照比对打标（标红）
    ④ build_mood_block.py 研报情绪片段（第六章）data/mood_block.html
    ⑤ patch_page.py       在 data/page_base.html 上原位替换内容

第六章还依赖 data/mood19_ext.json（三年一致预期 + 研报明细，供 EPS 列与研报抽屉使用）。
它由 fetch_mood_ext.py 抓取（全市场 180 天研报分页 + 19 只 F10 一致预期，约 40 秒），
不放进默认链路（每天重建没必要抓两遍网），需要更新时加 --refresh-ext。

之后可选上传（覆写固定节点编辑态）与发布（同步外部网页快照）。

用法：
    python scripts/finchain/rebuild_page.py                  # 只重建本地页面
    python scripts/finchain/rebuild_page.py --refresh-ext    # 先重抓第六章一致预期/研报明细
    python scripts/finchain/rebuild_page.py --upload         # 重建 + 覆写资料库节点
    python scripts/finchain/rebuild_page.py --upload --publish   # 再同步外部网页

注意：**不回写 data/page_base.html**。该文件是「原版版式的干净模板」，
patch_page.py 每次都从它出发；回写会让下一次在已替换过的内容上二次替换。
"""
import argparse
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE, DATA, FIN_OUT, PAGE_BASE, PY, library_skill  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(FIN_OUT, "pool_page_v5.html")
MOOD_JSON = os.path.join(DATA, "mood_q28.json")
CONTENT = os.path.join(FIN_OUT, "page_content.json")
NODE = "iB8I58mCTooLicPQ0Kyq0M"          # 季度股池页固定节点（只允许覆写）

# ── 上传门禁：与 scripts/daily_refresh.py 的 page_gate 同一套口径 ──
# （宁可当日不更新，也不能把旧版式 / 残缺页推到已发布的节点上）
GATE_REQUIRED = [
    ('id="btChart"', 1),
    ('id="posChart"', 1),
    ('id="posA"', 1),
    ('class="pbox b-ctrl"', 12),
    ("因子动量CSFM", 1),
    ("因子动量TSFM", 1),
    ("质量Top28组合", 1),
    ("六、市场情绪展望", 1),          # 研报情绪模块（data/mood_block.html 注入）
    ("七、如何更新最新一季股池", 1),   # 原六章后移，防止编号错位
    ('class="mood-stk"', 1),          # 行数由 data/mood_q28.json 决定，换期后同步即可
]
GATE_FORBIDDEN = [
    "三、动量轮动回测",
    "排名前 3 名各 16%",
    "前 3 名各 16%，其余 25 只各 2.08%",
]


def log(m):
    print(m, flush=True)


def run(args, timeout=3600):
    log("→ " + " ".join(str(a) for a in args[-3:]))
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    out = (p.stdout or "") + (p.stderr or "")
    for line in out.strip().splitlines()[-14:]:
        log("   " + line)
    if p.returncode != 0:
        raise SystemExit(f"! 失败（退出码 {p.returncode}）：{args[1]}")
    return out


def gate(path):
    try:
        with open(path, encoding="utf-8") as f:
            h = f.read()
    except OSError as e:
        return f"读不到页面产物：{e}"
    hit = [t for t in GATE_FORBIDDEN if t in h]
    if hit:
        return "产物命中旧版式/旧口径特征：" + "、".join(hit)
    miss = [f"{t}×{n}(实际{h.count(t)})" for t, n in GATE_REQUIRED if h.count(t) < n]
    if miss:
        return "产物缺少必需区块：" + "、".join(miss)
    return ""


def stale_mood():
    """第六章快照是否落后于最新一期持仓。返回提示语，一致则返回空串。

    研报目标价靠人工检索后固化在 data/mood_q28.json，不会随每日刷新自动变。
    换了调仓期而快照没更新时，表格里会出现「上一期的名单 + 新一期的股价」这种
    对不上的组合，所以这里必须显式告警（但不阻断：当日页面照常更新，
    只是把问题喊出来，免得静默错给用户看）。
    """
    if not os.path.exists(MOOD_JSON):
        return "缺 data/mood_q28.json（第六章会整块跳过）"
    try:
        m = json.load(open(MOOD_JSON, encoding="utf-8"))
        rebal = str(m["meta"]["rebal_date"])
    except (OSError, KeyError, ValueError) as e:
        return f"第六章快照读取失败：{e}"
    try:
        c = json.load(open(CONTENT, encoding="utf-8"))
        latest = str(c["periods"][-1]["asof"])       # 最新一期的财报可用日
    except (OSError, KeyError, IndexError, ValueError):
        return ""
    # 调仓日通常紧跟财报可用日（差 1~2 个交易日），落后超过 10 天即视为过期
    if rebal < latest:
        from datetime import date
        try:
            gap = (date.fromisoformat(latest) - date.fromisoformat(rebal)).days
        except ValueError:
            return ""
        if gap > 10:
            return (f"第六章快照 {rebal} 已落后最新一期 {latest}（差 {gap} 天）："
                    f"名单会与前六章对不上，需重跑研报检索并更新 data/mood_q28.json")
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true", help="覆写资料库节点（编辑态）")
    ap.add_argument("--publish", action="store_true", help="重新发布，同步外部网页快照")
    ap.add_argument("--skip-nav", action="store_true", help="跳过净值展开，直接用现有 out15 产物")
    ap.add_argument("--no-roll", action="store_true", help="跳过第六章股价刷新与变化比对")
    ap.add_argument("--refresh-ext", action="store_true",
                    help="先重抓第六章三年一致预期 + 研报明细（fetch_mood_ext.py，约 40 秒）")
    a = ap.parse_args()

    if not os.path.exists(PAGE_BASE):
        raise SystemExit(f"! 缺少原版模板：{PAGE_BASE}")

    if a.refresh_ext or os.environ.get("MOOD_REFRESH_EXT") == "1":
        # 云端由 lib.sh 导出 MOOD_REFRESH_EXT=1，每日顺带刷一次（约 40 秒，失败降级用库里的旧快照）。
        log("[0/5] 第六章外部数据：F10 一致预期 + 近 180 天研报明细")
        run([PY, os.path.join(HERE, "fetch_mood_ext.py")], timeout=1800)

    if not a.skip_nav:
        log("[1/5] 选股 + 日频净值")
        run([PY, os.path.join(HERE, "daily_nav15.py")])
    log("[2/5] 打包内容")
    run([PY, os.path.join(HERE, "pack_page.py")])

    # 第六章价格每天都要新，所以滚动放在链路里而不是靠人记得单独跑。
    # roll_mood 内部对行情接口失败是降级处理（保留原价、照常往下走），不会卡住建页。
    if os.path.exists(MOOD_JSON):
        if not a.no_roll:
            log("[3/5] 第六章滚动：刷收盘价 + 比对变化")
            run([PY, os.path.join(HERE, "roll_mood.py")])
        else:
            log("[3/5] 已跳过第六章滚动（--no-roll）")
        log("[4/5] 生成第六章（研报情绪）")
        run([PY, os.path.join(HERE, "build_mood_block.py")])
    else:
        log(f"[3/5] [4/5] 缺 {MOOD_JSON}，第六章将被跳过（门禁会因此拒绝上传）")
    log("[5/5] 原位替换内容")
    run([PY, os.path.join(HERE, "patch_page.py")])

    warn = stale_mood()
    if warn:
        log("   ⚠ " + warn)

    bad = gate(PAGE)
    if bad:
        raise SystemExit("! 页面完整性门禁未通过，已拒绝上传（线上保持原状）：\n  " + bad)
    log(f"✓ 页面：{PAGE}（{os.path.getsize(PAGE) / 1048576:.2f} MB，门禁通过）")

    if not a.upload:
        log("（未指定 --upload，仅保留本地产物）")
        return

    skill = library_skill()
    log("上传（覆写编辑态）")
    run([PY, skill / "page" / "import_html.py", PAGE, "--node-block-id", NODE], timeout=1800)
    log(f"✓ 已覆写节点 {NODE}")

    if a.publish:
        log("发布（同步外部网页）")
        run([PY, skill / "page" / "publish_page.py", "--node-id", NODE], timeout=1800)
        log(f"✓ 已重新发布：https://workbuddy.link/p/{NODE}")


if __name__ == "__main__":
    main()
