# -*- coding: utf-8 -*-
"""一次性迁移脚本：把硬编码的 Windows 路径换成 scripts/paths.py 解析。

保留此文件仅作改造留痕（记录每处改动），不参与运行时。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BOOT = ('# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---\n'
        'sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n')

PATCHES = {
    "faq_engine_15.py": [(
        'W = r"C:\\Users\\12066\\WorkBuddy\\2026-10-19-13-04-18\\work"\n'
        'D15 = os.path.join(W, "data15")\n'
        'FUND = r"C:\\Users\\12066\\WorkBuddy AI\\2026-10-17-22-12-47\\qmj_fraud\\data\\fund"\n'
        'META = r"C:\\Users\\12066\\WorkBuddy\\2026-10-05-23-13-30\\scripts\\meta.json"\n'
        'SW3MAP = r"C:\\Users\\12066\\WorkBuddy AI\\2026-10-17-22-12-47\\qmj_fraud\\data\\sw3_map.csv"',
        BOOT + 'from paths import (FIN_D15 as D15, FIN_FUND as FUND,  # noqa: E402\n'
        '                   FIN_META as META, FIN_SW as SW3MAP)\n'
        'os.makedirs(D15, exist_ok=True)'
    )],
    "build_px_fin.py": [(
        'W = r"C:\\Users\\12066\\WorkBuddy\\2026-10-19-13-04-18\\work"\n'
        'D15 = os.path.join(W, "data15")\n'
        'PX = r"C:\\Users\\12066\\WorkBuddy AI\\2026-10-17-22-12-47\\qmj_fraud\\data\\px"\n'
        'FUND = r"C:\\Users\\12066\\WorkBuddy AI\\2026-10-17-22-12-47\\qmj_fraud\\data\\fund"',
        BOOT + 'from paths import (FIN_D15 as D15, FIN_PX as PX,  # noqa: E402\n'
        '                   FIN_FUND as FUND)\n'
        'os.makedirs(D15, exist_ok=True)'
    )],
    "build_factors15.py": [
        ('W = r"C:\\Users\\12066\\WorkBuddy\\2026-10-19-13-04-18\\work"\n'
         'D15 = os.path.join(W, "data15")',
         BOOT + 'from paths import FIN_D15 as D15, FIN_MON  # noqa: E402\n'
         'os.makedirs(D15, exist_ok=True)'),
        ('    import glob\n'
         '    MON = r"C:\\Users\\12066\\WorkBuddy AI\\2026-10-17-22-12-47\\qmj_fraud\\data\\mon"\n'
         '    frs = []',
         '    import glob\n'
         '    MON = str(FIN_MON)\n'
         '    frs = []'),
    ],
    "backtest15.py": [(
        'W = r"C:\\Users\\12066\\WorkBuddy\\2026-10-19-13-04-18\\work"\n'
        'D15 = os.path.join(W, "data15")\n'
        'OUT = os.path.join(W, "out15")\n'
        'os.makedirs(OUT, exist_ok=True)',
        BOOT + 'from paths import FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402\n'
        'os.makedirs(OUT, exist_ok=True)'
    )],
    "backtest_quality15.py": [(
        'W = r"C:\\Users\\12066\\WorkBuddy\\2026-10-19-13-04-18\\work"\n'
        'D15 = os.path.join(W, "data15")\n'
        'OUT = os.path.join(W, "out15")',
        BOOT + 'from paths import FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402\n'
        'os.makedirs(OUT, exist_ok=True)'
    )],
    "build_page_data.py": [(
        'W = r"C:\\Users\\12066\\WorkBuddy\\2026-10-19-13-04-18\\work"\n'
        'D15 = os.path.join(W, "data15")\n'
        'OUT = os.path.join(W, "out15")',
        BOOT + 'from paths import FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402\n'
        'os.makedirs(OUT, exist_ok=True)'
    )],
    "perf_all.py": [(
        'W = r"C:\\Users\\12066\\WorkBuddy\\2026-10-19-13-04-18\\work"\n'
        'OUT = os.path.join(W, "out15")',
        BOOT + 'from paths import FIN_OUT as OUT  # noqa: E402'
    )],
    "build_pit_2015b.py": [(
        'OUT = r"C:\\Users\\12066\\WorkBuddy\\2026-10-19-13-04-18\\work\\data15"',
        BOOT + 'from paths import FIN_D15 as OUT  # noqa: E402\n'
        'OUT = str(OUT)\n'
        'os.makedirs(OUT, exist_ok=True)'
    )],
    "fetch_ext.py": [(
        'W = r"C:\\Users\\12066\\WorkBuddy\\2026-10-19-13-04-18\\work\\data15"',
        BOOT + 'from paths import FIN_D15  # noqa: E402\n'
        'W = str(FIN_D15)'
    )],
    "fetch_raw_price.py": [(
        'W = r"C:\\Users\\12066\\WorkBuddy\\2026-10-19-13-04-18\\work\\data15"',
        BOOT + 'from paths import FIN_D15  # noqa: E402\n'
        'W = str(FIN_D15)'
    )],
    "fetch_names.py": [(
        'W = r"C:\\Users\\12066\\WorkBuddy\\2026-10-19-13-04-18\\work"\n'
        'OUT = os.path.join(W, "out15", "name_map.json")',
        BOOT + 'from paths import FIN_OUT  # noqa: E402\n'
        'W = str(FIN_OUT)\n'
        'OUT = os.path.join(W, "name_map.json")'
    )],
    "fetch_bench.py": [(
        'OUT = r"C:\\Users\\12066\\WorkBuddy\\2026-10-19-13-04-18\\work\\out15\\bench_daily.csv"',
        BOOT + 'from paths import FIN_OUT  # noqa: E402\n'
        'os.makedirs(FIN_OUT, exist_ok=True)\n'
        'OUT = str(FIN_OUT / "bench_daily.csv")'
    )],
}


def main():
    for fn, subs in PATCHES.items():
        p = os.path.join(HERE, fn)
        s = open(p, encoding="utf-8").read()
        for old, new in subs:
            if old not in s:
                raise SystemExit(f"[FAIL] {fn}: 未命中\n{old[:120]}")
            if s.count(old) != 1:
                raise SystemExit(f"[FAIL] {fn}: 命中 {s.count(old)} 次\n{old[:120]}")
            s = s.replace(old, new)
        open(p, "w", encoding="utf-8").write(s)
        print(f"[OK] {fn}")


if __name__ == "__main__":
    main()
