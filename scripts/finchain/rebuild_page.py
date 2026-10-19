# -*- coding: utf-8 -*-
"""季度股池页 · finchain 链路总入口。

三步产出原版版式的新页面（不改任何 UI 细节）：
    ① daily_nav15.py   选股 + 逐日净值展开
    ② pack_page.py     打包成 out15/page_content.json
    ③ patch_page.py    在 data/page_base.html 上原位替换内容

之后可选上传（覆写固定节点编辑态）与发布（同步外部网页快照）。

用法：
    python scripts/finchain/rebuild_page.py                  # 只重建本地页面
    python scripts/finchain/rebuild_page.py --upload         # 重建 + 覆写资料库节点
    python scripts/finchain/rebuild_page.py --upload --publish   # 再同步外部网页

注意：**不回写 data/page_base.html**。该文件是「原版版式的干净模板」，
patch_page.py 每次都从它出发；回写会让下一次在已替换过的内容上二次替换。
"""
import argparse
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE, FIN_OUT, PAGE_BASE, PY, library_skill  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(FIN_OUT, "pool_page_v5.html")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true", help="覆写资料库节点（编辑态）")
    ap.add_argument("--publish", action="store_true", help="重新发布，同步外部网页快照")
    ap.add_argument("--skip-nav", action="store_true", help="跳过净值展开，直接用现有 out15 产物")
    a = ap.parse_args()

    if not os.path.exists(PAGE_BASE):
        raise SystemExit(f"! 缺少原版模板：{PAGE_BASE}")

    if not a.skip_nav:
        log("[1/3] 选股 + 日频净值")
        run([PY, os.path.join(HERE, "daily_nav15.py")])
    log("[2/3] 打包内容")
    run([PY, os.path.join(HERE, "pack_page.py")])
    log("[3/3] 原位替换内容")
    run([PY, os.path.join(HERE, "patch_page.py")])

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
