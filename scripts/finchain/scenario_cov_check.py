# -*- coding: utf-8 -*-
"""覆盖度过滤效应的证伪检验（只算数，不碰页面）。

三个问题，缺一个结论都站不住：

  ① 改善是「研报覆盖」本身带来的，还是仅仅「少持有几只股票」带来的？
     → 每期随机剔除同样只数（同权重弃置口径），跑 1000 次，看情景 A 落在什么分位。
  ② 「覆盖厚度」是单调信号吗？
     → 加两条对照：只留 thick（剔 thin+none）、剔 none 但保留 thin（即情景 A 本身）。
  ③ 情景 A 归一后权重是否突破 2%~8% 的上限？
     → 统计超限的期数与幅度。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from paths import DATA, FIN_OUT as OUT  # noqa: E402
from daily_nav15 import NAV_START, build_nav, filt_tradable, perf_daily  # noqa: E402
import scenario_cov as S  # noqa: E402

N_SIM = 1000


def nav_of(reb, D):
    r, _ = filt_tradable(reb, D["C"])
    s = build_nav(r, D["R"], D["R"].index.max())
    s = s[s.index >= pd.Timestamp(NAV_START)]
    return s / s.iloc[0]


def main():
    D = S.load_inputs()
    lab = pd.read_csv(S.LABEL, dtype={"code": str})
    lab["code"] = lab["code"].str.zfill(6)
    lvl = dict(zip(lab["code"], lab["cov_level"]))
    none_code = {c for c, v in lvl.items() if v == "none"}

    base_raw = S.picks_q28(D, drop_none=False)

    # ── 情景 A：剔 none
    scA, dropA = S.drop_none_from_holdings(base_raw, D["has_cov"])
    navA = nav_of(scA, D)
    pA = perf_daily(navA)

    # ── 对照：只留 thick（剔 thin + none）
    keep_thick = {c for c, v in lvl.items() if v == "thick"}
    onlyThick = {d: (w.reindex([c for c in w.index if c in keep_thick]) /
                     w.reindex([c for c in w.index if c in keep_thick]).sum())
                 for d, w in base_raw.items()
                 if w.reindex([c for c in w.index if c in keep_thick]).sum() > 0}
    navT = nav_of(onlyThick, D)
    pT = perf_daily(navT)

    # ── 蒙特卡洛：每期随机剔除与情景 A 同只数
    rng = np.random.default_rng(20261023)
    n_drop = {d: sum(1 for c in w.index if c in none_code) for d, w in base_raw.items()}
    tot_drop = sum(n_drop.values())
    accs = []
    for it in range(N_SIM):
        reb = {}
        for d, w in base_raw.items():
            k = n_drop[d]
            codes = list(w.index)
            if k and len(codes) - k >= 5:
                drop = set(rng.choice(codes, size=k, replace=False))
                codes = [c for c in codes if c not in drop]
            ww = w.reindex(codes)
            reb[d] = ww / ww.sum()
        s = nav_of(reb, D)
        accs.append(float(s.iloc[-1] - 1))
        if (it + 1) % 200 == 0:
            print(f"      蒙特卡洛 {it+1}/{N_SIM}", flush=True)
    accs = np.array(accs)
    pctile = float((accs < pA["累计"]).mean())

    print("\n" + "=" * 74)
    print("① 与「随机剔除同样只数」比")
    print(f"   实际剔除 {tot_drop} 只次（平均每期 {tot_drop/len(base_raw):.2f} 只）")
    print(f"   情景A 累计 {pA['累计']:+.2%} · 年化 {pA['年化']:+.2%}")
    print(f"   随机剔除 {N_SIM} 次：中位 {np.median(accs):+.2%}，"
          f"5%~95% 分位 [{np.percentile(accs,5):+.2%}, {np.percentile(accs,95):+.2%}]")
    print(f"   → 情景A 位于随机分布的第 {pctile:.1%} 分位"
          f"（{'显著优于随机' if pctile > 0.95 else '与随机无区别' if pctile > 0.05 else '劣于随机'}）")

    print("\n" + "=" * 74)
    print("② 覆盖厚度是否单调")
    base_nav = nav_of(base_raw, D)
    pB0 = perf_daily(base_nav)
    print(f"   原 Q28（thick+thin+none）      累计 {pB0['累计']:7.2%}  年化 {pB0['年化']:6.2%}  夏普 {pB0['夏普']:.2f}")
    print(f"   剔 none（thick+thin）          累计 {pA['累计']:7.2%}  年化 {pA['年化']:6.2%}  夏普 {pA['夏普']:.2f}")
    print(f"   只留 thick（剔 thin+none）     累计 {pT['累计']:7.2%}  年化 {pT['年化']:6.2%}  夏普 {pT['夏普']:.2f}")

    # ── 权重上限诊断
    over = []
    for d, w in scA.items():
        m = float(w.max())
        if m > 0.0800001:
            over.append({"date": d.strftime("%Y-%m-%d"), "n": len(w), "wmax": m})
    print("\n" + "=" * 74)
    print("③ 归一后是否突破 8% 上限")
    if over:
        o = pd.DataFrame(over)
        print(f"   {len(o)}/{len(scA)} 期超限，最大 {o.wmax.max():.2%}，"
              f"超限期平均持仓 {o.n.mean():.1f} 只")
    else:
        print("   无超限")

    pd.DataFrame({"随机剔除累计": accs}).to_csv(
        os.path.join(DATA, "scenario_cov_mc.csv"), index=False)
    print(f"\n蒙特卡洛样本 → data/scenario_cov_mc.csv")


if __name__ == "__main__":
    main()
