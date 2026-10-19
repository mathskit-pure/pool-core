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

# ---------------------------------------------------------------------------
# 财报链（finchain）：四表 / 行情 / 中间面板 / 回测产物
# ---------------------------------------------------------------------------
# 「官方中证800 口径」的数据侧工作区：build_page_data.py 与 out15/ 产物所在目录。
# 页面渲染本身不依赖它（只吃 page_data.json），仅 --pack 时用来重跑数据打包。
WORK15 = Path(os.environ.get("POOL15_DIR") or (
    r"C:\Users\12066\WorkBuddy\2026-10-19-13-04-18\work"
    if os.name == "nt" else POOL_DATA / "work"
))

# 原始数据源在 Windows 上仍指向 qmj_fraud 工程（保证本机行为不变）；
# 云端统一落在 pool-core/data/finchain/ 下，由 cloud/fin_bootstrap.sh 冷启动重建。
# 注意：qmj_fraud 的路径含空格，必须用原始字符串，不能拼 Path 运算。
_QF_WIN = r"C:\Users\12066\WorkBuddy AI\2026-10-17-22-12-47\qmj_fraud\data"

FIN_ROOT = Path(os.environ.get("FINCHAIN_DIR") or (DATA / "finchain"))
FIN_FUND = Path(os.environ.get("FIN_FUND_DIR") or (
    Path(_QF_WIN) / "fund" if os.name == "nt" else FIN_ROOT / "fund"))
FIN_PX = Path(os.environ.get("FIN_PX_DIR") or (
    Path(_QF_WIN) / "px" if os.name == "nt" else FIN_ROOT / "px"))
FIN_MON = Path(os.environ.get("FIN_MON_DIR") or (
    Path(_QF_WIN) / "mon" if os.name == "nt" else FIN_ROOT / "mon"))
FIN_SW = Path(os.environ.get("FIN_SW_FILE") or (
    Path(_QF_WIN) / "sw3_map.csv" if os.name == "nt" else FIN_ROOT / "sw3_map.csv"))
# 中间面板（px_daily.pkl / fin_pit.pkl / 因子暴露）与回测产物
FIN_D15 = Path(os.environ.get("FIN_D15_DIR") or (
    WORK15 / "data15" if os.name == "nt" else FIN_ROOT / "data15"))
FIN_OUT = Path(os.environ.get("FIN_OUT_DIR") or (
    WORK15 / "out15" if os.name == "nt" else FIN_ROOT / "out15"))
# 行业映射（sw1/sw2/sw3），随代码入库
FIN_META = SCRIPTS / "meta.json"
# 渲染器读取的数据包（由 build_page_data.py 产出，入库）
PAGE_DATA = DATA / "page_data.json"

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
    print(f"WORK15    = {WORK15}")
    print(f"FIN_ROOT  = {FIN_ROOT}")
    print(f"FIN_FUND  = {FIN_FUND}")
    print(f"FIN_PX    = {FIN_PX}")
    print(f"FIN_MON   = {FIN_MON}")
    print(f"FIN_SW    = {FIN_SW}")
    print(f"FIN_D15   = {FIN_D15}")
    print(f"FIN_OUT   = {FIN_OUT}")
