#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把线上页面节点的最新版本拉下来，作为主刷新 refresh_page.py 的模板。

为什么需要它：data/page_base.html 是「上次发布成功的产物」，是 refresh_page.py
整页重建的模板。它有 10MB 且每天变化，不进 Git；云端首次初始化时必须从资料库
直接取线上最新版——这也是唯一权威来源（比从本机拷贝更不会出错）。

用法：
    python3 cloud/seed_page_base.py [--node-id <id>] [--force]

退出码：0 成功 / 6 节点不存在或拉取失败
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from paths import BASE, DATA, library_skill  # noqa: E402

DEFAULT_NODE = "iB8I58mCTooLicPQ0Kyq0M"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--node-id", default=DEFAULT_NODE)
    ap.add_argument("--force", action="store_true", help="已存在模板时也强制重新拉取")
    a = ap.parse_args()

    page_base = DATA / "page_base.html"
    if page_base.exists() and not a.force:
        print(f"[seed] 模板已存在，跳过：{page_base}（{page_base.stat().st_size:,} 字节）")
        return 0

    skill = library_skill()
    work = Path(os.environ.get("WB_WORKSPACE", "/workspace")) / "_seed" / a.node_id
    work.mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, str(skill / "page" / "download_page_artifacts.py"),
           "--node-id", a.node_id, "--out-dir", str(work)]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    out = r.stdout.decode("utf-8", errors="replace")
    line = [ln for ln in out.splitlines() if "KS_ARTIFACTS_OK" in ln]
    if not line:
        print("[seed] 拉取线上页面失败：", out[-600:] or r.stderr.decode("utf-8", "replace")[-600:])
        return 6
    info = json.loads(line[0].split("KS_ARTIFACTS_OK", 1)[1].strip())
    entry = Path(info["work_dir"]) / info["entry_html"]
    if not entry.exists():
        print(f"[seed] 入口文件不存在：{entry}")
        return 6

    DATA.mkdir(parents=True, exist_ok=True)
    if page_base.exists():
        shutil.copyfile(page_base, str(page_base) + ".bak")
    shutil.copyfile(entry, page_base)

    # 线上页面含第六章《市场情绪展望》，但模板必须是「干净原版」：
    # patch_page.insert_mood_block 每次都从 MOOD_BLOCK 片段重新注入，
    # 模板里若残留一份，会让第六章变成「模板旧内容 + 注入新内容」两套。
    # 这里只摘正文与样式，不动其它任何结构（seed 的定位就是搬运，不是编辑）。
    txt = page_base.read_text(encoding="utf-8", errors="replace")
    n0 = len(txt)
    for bgn, end in (("<!--MOOD-SEC-BEGIN-->", "<!--MOOD-SEC-END-->"),
                     ("/*MOOD-CSS-BEGIN*/", "/*MOOD-CSS-END*/")):
        while bgn in txt:
            a = txt.find(bgn)
            b = txt.find(end, a)
            if b < 0:
                break
            txt = txt[:a] + txt[b + len(end):]
    if len(txt) != n0:
        page_base.write_text(txt, encoding="utf-8")
        stripped = n0 - len(txt)

    print(f"[seed] 模板已就位：{page_base}（{page_base.stat().st_size:,} 字节）"
          f" ← 节点 {a.node_id}"
          + (f"（已摘除残留六章 {stripped:,} 字符）" if len(txt) != n0 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
