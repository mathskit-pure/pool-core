# -*- coding: utf-8 -*-
"""
AFGI 定时任务结束后调用：把最新的 A 股恐慌贪婪指数同步到资料库页面顶部的 KPI 卡片。

为什么要有这么个独立脚本
------------------------
主页 daily_refresh.py 每天也会跑 refresh_page.py 并更新这 7 张 KPI 卡，
但 AFGI 定时任务是**另一条独立链路**（跑 afgi_tdx 的 run.py 写 afgi_latest.json），
两者并不耦合；若 AFGI 跑完没人通知页面，卡片就会停在旧值上（历史上就停过
2026-10-08 不肯动）。本脚本就是这条通知链路。

具体做什么
----------
1) 从资料库拉 **线上最新版** 页面当基底（不是拿本地 page_base.html 硬盖，
   避免把别人刚更新的内容回滚掉）；
2) 只改 KPI 卡片区：
      · A股恐慌贪婪指数 → 数值 / 状态徽章（含五档配色）/ 截至日
      · 稳健联合当前仓位 → AFGI 逆情绪规则算出的当期目标仓位 / 截至最近调仓日
      · 动量组合持仓 · 质量Top28组合持仓 → 最新一期实际持仓只数
3) 写 data/pool_page.html → 上传 → 成功后回写 data/page_base.html 当明天的模板。

用法
----
    python scripts/refresh_afgi_kpi.py                # 更新 + 上传
    python scripts/refresh_afgi_kpi.py --no-import    # 只本地更新，不上传（排错用）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = r"C:\Users\12066\WorkBuddy\2026-10-05-23-13-30"
SCRIPTS = os.path.join(BASE, "scripts")
DATA = os.path.join(BASE, "data")
sys.path.insert(0, SCRIPTS)

PY = r"C:\Users\12066\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
SKILL = (r"C:\Users\12066\AppData\Local\Programs\WorkBuddy\resources\app.asar.unpacked"
         r"\resources\plugins\workbuddy-builtin\skills\library")
PAGE_NODE = "iB8I58mCTooLicPQ0Kyq0M"        # 资料库页面节点（覆写目标）

import refresh_page as RP  # noqa: E402
import afgi_pos as AP      # noqa: E402


def log(msg):
    print(msg, flush=True)


def run(cmd, timeout=1800):
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("命令失败: %s\n%s"
                           % (" ".join(cmd[:3]),
                              r.stdout.decode("utf-8", errors="replace")[-1500:]))
    return r.stdout.decode("utf-8", errors="replace")


def pull_live_page(out_dir):
    """拉取线上最新版页面，返回入口 HTML 的本地路径。"""
    out = run([PY, os.path.join(SKILL, "page", "download_page_artifacts.py"),
               "--node-id", PAGE_NODE, "--out-dir", out_dir])
    line = [l for l in out.splitlines() if "KS_ARTIFACTS_OK" in l]
    if not line:
        raise RuntimeError("拉取线上页面失败，未见到 KS_ARTIFACTS_OK\n" + out[-800:])
    info = json.loads(line[0].split("KS_ARTIFACTS_OK", 1)[1].strip())
    return os.path.join(info["work_dir"], info["entry_html"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-import", action="store_true", help="只本地更新，不上传")
    args = ap.parse_args()

    rd = AP.latest_afgi_reading()
    if not rd:
        log("!! 读不到 AFGI 最新读数（afgi_latest.json / afgi_timeseries.csv 均不可用），中止")
        return 1
    log("AFGI 最新读数：%s → %.2f（%s）" % (rd["date"], rd["afgi"], rd["state"]))

    work = tempfile.mkdtemp(prefix="afgi-kpi-")
    try:
        entry = pull_live_page(work)
        html = RP.read_text(entry)
        log("线上基底：%s（%s chars）" % (entry, f"{len(html):,}"))

        before = html
        html = RP.fix_wrap_scope(html)          # 顺带修正「五、」模块的容器归属（幂等）
        layout_fixed = html != before
        before = html
        html = RP.update_kpi_cards(html)
        if html == before and not layout_fixed:
            log("· KPI 卡片已是最新读数，无需重复上传")
            return 0
        if layout_fixed:
            log("· 已修正「五、」模块的容器归属（宽度对齐），本次一并上传")

        out_html = os.path.join(DATA, "pool_page.html")
        RP.write_text(out_html, html)
        log("已写出：%s（%s chars）" % (out_html, f"{len(html):,}"))

        if args.no_import:
            log("--no-import：跳过上传")
            return 0

        log("=== 上传资料库 ===")
        out = run([PY, os.path.join(SKILL, "page", "import_html.py"), out_html,
                   "--node-block-id", PAGE_NODE])
        line = [l for l in out.splitlines() if "KS_IMPORT_OK" in l]
        if not line:
            raise RuntimeError("上传失败，未见到 KS_IMPORT_OK\n" + out[-800:])
        log(line[0].strip())

        # 上传成功 → 本产物即线上最新版，回写为下一次刷新的模板
        shutil.copyfile(out_html, os.path.join(DATA, "page_base.html"))
        log("已回写刷新模板：data/page_base.html")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
