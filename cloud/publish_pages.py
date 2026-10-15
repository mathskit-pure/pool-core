#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端统一发布器：把三个固定页面节点的最新编辑态重新发布为外部网页。

为什么需要它
------------
资料库「发布为外部网页」生成的是一份「冻结的公开快照」，与编辑态节点解耦。
各流水线（AFGI / 季度股池 / B-score）只通过 import_html 覆写编辑态，从不调用
publish，导致外部网页停留在上次手动发布的旧版本 —— 用户每次都得手动「同步」。

本脚本作为每日整链的最后一步，把三个固定节点的编辑态重新烤成公开快照，
保证外部网页每天自动跟上最新数据。重新发布是幂等的：多次发布无害，即使某天
页面内容没变也只是重烤一份相同快照。

用法
----
    python3 cloud/publish_pages.py          # 发布全部三个固定节点
    ONLY=AFGI python3 cloud/publish_pages.py  # 只发布某个（按简称模糊匹配）

依赖：WB_LIBRARY_SKILL 或标准候选路径能定位到资料库 library skill（同 AFGI 的
publish.py 那套候选路径）。需要对应节点的管理员权限（与手动发布一致）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 三个固定页面节点（覆写/发布目标，禁止新建）
NODES = {
    "AFGI":      "ddbJ1onUkhBUybcqWTrwG5",   # 市场情绪指数AFGI
    "POOL":      "iB8I58mCTooLicPQ0Kyq0M",   # 舞弊调整质量因子·季度动态股池
    "BSCORE":    "VLeP5CSpUchSY3qawGq88W",   # A股 B-score 择时信号看板
}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(msg: str) -> None:
    print(f"[publish-pages] {msg}", flush=True)


# ---------------------------------------------------------------------------
# 资料库 skill 路径探测（云端 Linux 与本地 Windows 都能用，与 AFGI publish.py 一致）
# ---------------------------------------------------------------------------
def find_library_skill() -> Path | None:
    cands: list[Path] = []
    env = os.environ.get("WB_LIBRARY_SKILL")
    if env:
        cands.append(Path(env))
    if os.name == "nt":
        cands.append(Path(os.path.expandvars(
            r"%LOCALAPPDATA%\Programs\WorkBuddy\resources\app.asar.unpacked"
            r"\resources\plugins\workbuddy-builtin\skills\library")))
    else:
        cands += [
            Path("/root/.codebuddy/skills/library"),
            Path("/root/.workbuddy/skills/library"),
            Path.home() / ".codebuddy/skills/library",
            Path.home() / ".workbuddy/skills/library",
        ]
    for c in cands:
        if (c / "page" / "import_html.py").exists():
            return c
    return None


def node_exists(skill: Path, node: str) -> bool:
    """上传/发布前探活：确认目标节点还在。节点被删后 publish 会失败而非新建，
    这里提前发现并跳过，避免任何误建行为。"""
    r = subprocess.run(
        [sys.executable, str(skill / "page" / "download_page_artifacts.py"),
         "--node-id", node],
        capture_output=True, timeout=300,
    )
    out = r.stdout.decode("utf-8", errors="replace")
    return "KS_ARTIFACTS_OK" in out


def publish_one(skill: Path, name: str, node: str) -> bool:
    if not node_exists(skill, node):
        log(f"!! {name} 节点 {node} 已不存在，跳过发布（避免误建替代页面）")
        return False
    try:
        r = subprocess.run(
            [sys.executable, str(skill / "page" / "publish_page.py"),
             "--node-id", node],
            capture_output=True, timeout=600,
        )
    except Exception as e:
        log(f"!! {name} 发布命令异常：{e}")
        return False
    out = r.stdout.decode("utf-8", errors="replace")
    if "KS_PAGE_PUBLISH" in out:
        log(f"✓ {name} 已重新发布（外部网页已同步）：{node}")
        return True
    log(f"!! {name} 发布未确认（rc={r.returncode}，未见 KS_PAGE_PUBLISH）：{out[-400:]}")
    return False


def main() -> int:
    only = (os.environ.get("ONLY") or "").strip().upper()
    skill = find_library_skill()
    if not skill:
        log("!! 找不到资料库 library skill（page/import_html.py / publish_page.py），"
            "无法发布；可用环境变量 WB_LIBRARY_SKILL 指定其路径")
        return 1
    log(f"library skill: {skill}")

    targets = {k: v for k, v in NODES.items() if not only or only in k}
    if not targets:
        log(f"!! ONLY={only} 未匹配到任何节点（可选：AFGI / POOL / BSCORE）")
        return 1

    ok = 0
    for name, node in targets.items():
        if publish_one(skill, name, node):
            ok += 1
    log(f"完成：{ok}/{len(targets)} 个页面已重新发布"
        + (f"（共 {len(NODES)} 个，跳过 {len(NODES) - len(targets)} 个）" if only else ""))
    # 单个页面发布失败不阻断其它页面，也不影响数据流水线；返回 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
