# -*- coding: utf-8 -*-
"""季度股池页的「全量重发布」入口 —— 替代已失效的 refresh_page.py（旧版式锚点替换）。

为什么换机制
------------
线上页面在 2026-10-19 换成「数据包 + 整页重绘」结构：净值全靠内联 JS 现画，股池按
行业分组嵌套渲染。``refresh_page.py`` 依赖的 ``var BT=`` / ``svg#btChart`` / ``td#r{i}_{c}``
一个都不存在了，它自己会报「var BT= 出现 0 次，已中止」并**不写文件**（这点是好的：
不会静默把新页面改回旧版），但也意味着季度更新彻底断链。

新机制把链路拆成四段，每段都能单独跑、单独验：

    ① pack    数据侧产出 page_data.json（只读 CSV → 单一 JSON 契约）
    ② render  只吃 JSON，整页重绘      —— 可在云端独立运行，不必带 CSV
    ③ verify  结构 / 脚本 / 数据三层真跑 —— 任一失败即拒绝上传
    ④ upload  import_html 覆写固定节点，可选 publish 同步外部网页

用法::

    # 只验证，不碰线上（默认）
    python scripts/republish_page.py

    # 本机：重跑数据打包 → 渲染 → 验证 → 上传 → 发布
    python scripts/republish_page.py --pack --upload --publish

    # 云端：只拿到数据包时
    python scripts/republish_page.py --data data/page_data.json --upload --publish

退出码：0 成功 / 2 数据包缺失 / 3 验证失败 / 4 上传失败 / 5 发布失败
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
from paths import BASE, DATA, WORK15, library_skill  # noqa: E402

from pagegen.render import build  # noqa: E402
from pagegen.verify import print_report, verify  # noqa: E402

NODE_DEFAULT = "iB8I58mCTooLicPQ0Kyq0M"
DEFAULT_DATA = DATA / "page_data.json"
DEFAULT_OUT = DATA / "pool_page.html"

# 上传门禁：低于这个体积的页面一定是渲染失败（正常 3.5~4MB）
MIN_BYTES = 800_000
# 必须出现的锚点标记，缺一个就说明渲染走错了分支
MUST_CONTAIN = ["舞弊调整质量因子", "季度股池", "id=\"chart\"", "质量Top28 v2", "page_comm/inject.js"]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------ ① pack
def do_pack(src_script: str | None) -> bool:
    """跑数据打包脚本，把产出的 page_data.json 拷进本工程 data/。"""
    if not WORK15 or not os.path.isdir(str(WORK15)):
        log(f"数据侧目录不存在：{WORK15}（可用环境变量 POOL15_DIR 指定）")
        return False
    script = src_script or os.path.join(str(WORK15), "build_page_data.py")
    if not os.path.exists(script):
        log(f"找不到数据打包脚本：{script}")
        return False
    log(f"① 数据打包：{script}")
    r = subprocess.run([sys.executable, script], cwd=os.path.dirname(script),
                       capture_output=True, text=True)
    if r.returncode != 0:
        log(f"打包失败（{r.returncode}）：{(r.stderr or r.stdout or '')[-800:]}")
        return False
    for line in (r.stdout or "").strip().splitlines()[-4:]:
        log("   " + line)
    produced = os.path.join(str(WORK15), "out15", "page_data.json")
    if not os.path.exists(produced):
        log(f"打包未产出 page_data.json：{produced}")
        return False
    DATA.mkdir(parents=True, exist_ok=True)
    shutil.copy2(produced, DEFAULT_DATA)
    log(f"   已同步到 {DEFAULT_DATA}（{os.path.getsize(DEFAULT_DATA)/1e6:.2f} MB）")
    return True


# ------------------------------------------------------------------ ④ upload
def do_upload(html_path: str, node: str, file_name: str) -> bool:
    lib = library_skill()
    imp = lib / "page" / "import_html.py"
    log(f"④ 上传：覆写节点 {node}")
    r = subprocess.run([sys.executable, str(imp), html_path,
                        "--node-block-id", node, "--file-name", file_name],
                       capture_output=True, text=True, timeout=900)
    tail = (r.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        log("   " + line)
    if r.returncode != 0:
        log(f"上传失败：{(r.stderr or '')[-600:]}")
        return False
    return True


def do_publish(node: str) -> bool:
    lib = library_skill()
    pub = lib / "page" / "publish_page.py"
    if not pub.exists():
        log("未找到 publish_page.py，跳过外部网页同步")
        return True
    log("⑤ 发布：同步外部网页快照")
    r = subprocess.run([sys.executable, str(pub), "--node-id", node],
                       capture_output=True, text=True, timeout=900)
    for line in (r.stdout or "").strip().splitlines()[-3:]:
        log("   " + line)
    if r.returncode != 0:
        log(f"发布失败：{(r.stderr or '')[-600:]}")
        return False
    return True


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description="季度股池页全量重发布")
    ap.add_argument("--data", default=None, help="数据包 JSON（默认 data/page_data.json）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出 HTML")
    ap.add_argument("--node-id", default=os.environ.get("PAGE_NODE", NODE_DEFAULT))
    ap.add_argument("--file-name", default="pool_page.html", help="资料库里保存的文件名")
    ap.add_argument("--pack", action="store_true", help="先重跑数据打包脚本")
    ap.add_argument("--pack-script", default=None, help="指定数据打包脚本路径")
    ap.add_argument("--upload", action="store_true", help="验证通过后覆写线上节点")
    ap.add_argument("--publish", action="store_true", help="上传后同步外部网页")
    ap.add_argument("--check-only", action="store_true", help="只做验证，强制不上传")
    ap.add_argument("--force", action="store_true", help="验证失败也上传（危险，需显式指定）")
    a = ap.parse_args()

    if a.check_only:
        a.upload = a.publish = False

    log(f"工程根目录 {BASE}")

    if a.pack:
        if not do_pack(a.pack_script):
            return 2

    data_path = a.data or str(DEFAULT_DATA)
    if not os.path.exists(data_path):
        alt = os.path.join(str(WORK15 or ""), "out15", "page_data.json")
        if os.path.exists(alt):
            log(f"默认数据包不存在，回退到数据侧产物：{alt}")
            data_path = alt
        else:
            log(f"数据包不存在：{data_path}（先跑 --pack，或用 --data 指定）")
            return 2

    data = json.load(open(data_path, encoding="utf-8"))
    log(f"② 渲染：{data_path} → {a.out}")
    try:
        doc = build(data)
    except Exception as exc:  # 渲染异常必须阻断，不能产出半成品
        log(f"渲染失败：{type(exc).__name__}: {exc}")
        return 3
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(doc)
    size = os.path.getsize(a.out)
    log(f"   {a.out} {size/1e6:.2f} MB · {len(data['pools'])} 期 · 最新 {data['pools'][-1]['label']}")

    log("③ 验证")
    ok, report = verify(doc, data)
    print_report(ok, report)

    # 上传门禁：体积 + 关键标记
    missing = [m for m in MUST_CONTAIN if m not in doc]
    if size < MIN_BYTES:
        ok = False
        print(f"   ✗ 页面仅 {size/1024:.0f} KB，低于 {MIN_BYTES/1024:.0f} KB 下限，判定渲染不完整")
    if missing:
        ok = False
        print(f"   ✗ 缺少关键标记：{missing}")

    if not ok and not a.force:
        log("验证未通过，已中止（未触碰线上页面）。确认是误报时可加 --force。")
        return 3
    if not ok and a.force:
        log("⚠ 验证未通过但指定了 --force，继续上传")

    if not a.upload:
        log("未指定 --upload，本次只生成并验证，线上页面保持不变。")
        return 0

    if not do_upload(a.out, a.node_id, a.file_name):
        return 4
    if a.publish and not do_publish(a.node_id):
        return 5
    log("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
