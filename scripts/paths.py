"""统一路径解析：让同一份代码既能在 Windows 本机跑，也能在 Linux 云端跑。

背景
----
原先各脚本把 ``C:\\Users\\...`` 写死在顶部（主项目 24/25 个 .py 都这样），
迁到云端（Linux /workspace）时必须逐个替换。这里集中成一处，全部支持环境变量覆盖。

云端默认布局（可用环境变量整体改写）：
    /workspace/pool-core     本工程
    /workspace/prof-model    PROF 盈利能力模型
    /workspace/mom-opt       动量轮动回测引擎
    /workspace/pool-data     季度股池数据侧
    /workspace/afgi_tdx      AFGI 情绪指数

优先级：环境变量 > 平台探测 > 相对布局推断。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 本工程根目录（scripts/ 的上一级）
BASE = Path(os.environ.get("POOL_BASE") or Path(__file__).resolve().parent.parent)

# Python 解释器：默认用当前解释器（自动化里显式指定了解释器，sys.executable 即它）
PY = os.environ.get("POOL_PY") or sys.executable

# westock CLI：跨平台 Go 二进制。Windows 上叫 westock.exe，Linux 上叫 westock。
# 云端由 bootstrap 装到 ~/.local/bin/westock 并加入 PATH。
if os.environ.get("WESTOCK_BIN"):
    WESTOCK = os.environ["WESTOCK_BIN"]
elif os.name == "nt":
    WESTOCK = str(Path.home() / ".local" / "bin" / "westock.exe")
else:
    WESTOCK = "westock"

DATA = BASE / "data"
SCRIPTS = BASE / "scripts"

# 兄弟工程：环境变量优先；其次按平台给默认。
#   Windows 本机 —— 沿用各工程既有的 WorkBuddy 目录，保证改造后本机行为完全不变；
#   Linux 云端   —— 由 bootstrap 统一克隆到同级目录（pool-core / prof-model /
#                   mom-opt / pool-data / afgi_tdx），故用兄弟推断即可。
_WIN_SIBLINGS = {
    "MOM_OPT_DIR": r"C:\Users\12066\WorkBuddy\2026-10-09-23-54-07\mom_opt",
    "PROF_DIR": r"C:\Users\12066\WorkBuddy\2026-10-07-14-39-28\work",
    "POOL_DATA_DIR": r"C:\Users\12066\WorkBuddy\2026-10-04-19-37-33",
    "AFGI_DIR": r"C:\Users\12066\WorkBuddy\2026-10-05-14-50-58\afgi_tdx",
}
_LINUX_NAMES = {
    "MOM_OPT_DIR": "mom_opt",
    "PROF_DIR": "prof-model",
    "POOL_DATA_DIR": "pool-data",
    "AFGI_DIR": "afgi_tdx",
}


def _sibling(env_var: str) -> Path:
    v = os.environ.get(env_var)
    if v:
        return Path(v)
    if os.name == "nt":
        return Path(_WIN_SIBLINGS[env_var])
    return BASE.parent / _LINUX_NAMES[env_var]


MOM_OPT = _sibling("MOM_OPT_DIR")
PROF_DIR = _sibling("PROF_DIR")
POOL_DATA = _sibling("POOL_DATA_DIR")
AFGI_DIR = _sibling("AFGI_DIR")

# 常用产物
PAGE_BASE = DATA / "page_base.html"
PRICES = DATA / "prices_full_v2.csv"
AFGI_TIMESERIES = AFGI_DIR / "output" / "afgi_timeseries.csv"
AFGI_LATEST = AFGI_DIR / "output" / "afgi_latest.json"


def library_skill() -> Path:
    """定位资料库 library skill（含 page/import_html.py）。

    云端 Linux 与本机 Windows 的候选路径不同，全部列出来逐个探测；
    也可用 WB_LIBRARY_SKILL 直接指定。
    """
    env = os.environ.get("WB_LIBRARY_SKILL")
    cands: list[Path] = []
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
    raise FileNotFoundError(
        "找不到资料库 library skill（page/import_html.py）。"
        "可用环境变量 WB_LIBRARY_SKILL 指定其路径。"
        f"已尝试：{[str(c) for c in cands]}"
    )


if __name__ == "__main__":
    print(f"BASE      = {BASE}")
    print(f"PY        = {PY}")
    print(f"WESTOCK   = {WESTOCK}")
    print(f"MOM_OPT   = {MOM_OPT}")
    print(f"PROF_DIR  = {PROF_DIR}")
    print(f"POOL_DATA = {POOL_DATA}")
    print(f"AFGI_DIR  = {AFGI_DIR}")
