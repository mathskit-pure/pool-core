# -*- coding: utf-8 -*-
"""从 2017-01-01 起重算三组合回测（CSFM / TSFM / 质量Top28）。

为什么重算
--------------------------------
2015-2016 含股灾、熔断、千股停牌等极端结构，个股价格连续性与可交易性
严重失真（2015-09 建仓期有 25% 权重处于停牌）。把这两年留在净值里，
既拉低可解释性、也让「停牌记账」这类口径问题放大。因此按用户要求，
回测窗口改为 2017-01-01 → 最新交易日。

口径（与 fix_consistency15.py 完全一致，不放松任何一项）
--------------------------------
· 选股：直接复用 daily_nav15.csfm_tsfm_picks() / quality_picks() 的全期结果
  —— 2015-2016 的调仓日仍然计算，作为 2017 起的信号 warm-up 与期初持仓，
  只是**不参与净值统计**。这样 2017-01-01 的持仓 = 当时真实持仓，
  而不是「2017 年凭空建仓」。
· 调仓日可交易过滤：停牌/未上市的标的不买入、权重在可交易标的内重新归一
  （沿用 fix_consistency15.filt_tradable）。
· 段内 buy&hold：段净值 = Σ w_i · Π(1+r_i)；持仓停牌日收益记 0，
  复牌日一次性补涨/补跌。
· 成本：单边 10bp，按换手扣双边。
· 净值锚点：2017 年首个交易日 = 1.00（前置段净值用于定位持仓，不展示）。

输出
--------------------------------
out15/daily_nav_15_2017.csv     date × [CSFM, TSFM, Q28]（2017-01-01 起）
out15/perf_from2017.csv         绩效表（全期 + 2017-2018 + 2019-2026 + 基准）
out15/holdings_15_2017.csv      该窗口内的持仓明细
out15/rebase_compare_2017.csv   旧(2015起) vs 新(2017起)同段对照，用于核对
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from paths import FIN_D15 as D15, FIN_OUT as OUT  # noqa: E402

import daily_nav15 as DN                                    # noqa: E402
from fix_consistency15 import filt_tradable, build_nav, perf  # noqa: E402

START = pd.Timestamp("2017-01-01")
SEGS = [("2017-2018", "2017-01-01", "2018-12-31"),
        ("2019-2026", "2019-01-01", "2026-12-31")]
COMBOS = [("CSFM", "因子动量CSFM"), ("TSFM", "因子动量TSFM"), ("Q28", "质量Top28组合")]


def main():
    # ── 价格面板 ──
    px = pd.read_pickle(os.path.join(D15, "px_daily.pkl"))
    px["code"] = px["code"].astype(str).str.zfill(6)
    C = px.pivot(index="date", columns="code", values="close").sort_index()
    R = px.pivot(index="date", columns="code", values="ret").sort_index()
    last = R.index[-1]

    trade = C.index[C.index >= START]
    if len(trade) == 0:
        raise SystemExit("2017 之后无交易日")
    anchor = trade[0]          # 2017 年首个交易日
    print(f"[窗口] {anchor:%Y-%m-%d} → {last:%Y-%m-%d}  {len(trade)} 个交易日", flush=True)

    # ── 选股（全期，含 2015-2016 warm-up） ──
    picks = DN.csfm_tsfm_picks()
    picks["Q28"] = DN.quality_picks()

    navs_full, navs_win, holds_win = {}, {}, []
    for nm, _ in COMBOS:
        reb = picks[nm]
        reb2, _dup = filt_tradable(reb, C)
        s_full = build_nav(reb2, R, last)          # 全期净值（含 warm-up 段）
        # 裁剪到 2017 首个交易日并重新归一 → 该日 = 1.00
        s_win = s_full[s_full.index >= anchor]
        s_win = s_win / s_win.iloc[0]
        navs_full[nm] = s_full
        navs_win[nm] = s_win
        p = perf(s_win)
        print(f"  {nm:5} 调仓 {len(reb2)} 次 | 窗口内 {len(s_win)} 日  "
              f"累计{p['累计']:7.1%} 年化{p['年化']:6.2%} 回撤{p['最大回撤']:7.2%} "
              f"夏普{p['夏普']:5.2f}", flush=True)
        for d, w in reb2.items():
            if d >= anchor:
                for c, v in w.items():
                    holds_win.append({"rebal_date": d.strftime("%Y-%m-%d"), "combo": nm,
                                      "code": c, "weight": float(v)})

    N = pd.DataFrame(navs_win).sort_index()
    N.index.name = "date"
    N.to_csv(os.path.join(OUT, "daily_nav_15_2017.csv"))
    pd.DataFrame(holds_win).to_csv(os.path.join(OUT, "holdings_15_2017.csv"),
                                   index=False, encoding="utf-8-sig")
    print(f"\n✓ daily_nav_15_2017.csv  ({len(N)} 日 × {N.shape[1]})", flush=True)

    # ── 绩效表 ──
    bench = pd.read_csv(os.path.join(OUT, "bench_daily.csv"), parse_dates=["date"])

    def seg_perf(s, a, b):
        """分段绩效：先把该段锚回 1.00，否则 perf() 会把段末净值当累计倍数。"""
        seg = s[(s.index >= pd.Timestamp(a)) & (s.index <= pd.Timestamp(b))].dropna()
        if len(seg) < 20:
            return None
        return perf(seg / seg.iloc[0])

    rows = []
    for nm, label in COMBOS:
        s = N[nm].dropna()
        rows.append({"组合": label, "区间": "全期(2017起)", "口径": "日频", **perf(s)})
        for lab, a, b in SEGS:
            pp = seg_perf(s, a, b)
            if pp:
                rows.append({"组合": label, "区间": lab, "口径": "日频", **pp})
    for nm, g in bench.groupby("name"):
        s = g.set_index("date")["close"].sort_index().dropna()
        s = s[s.index >= anchor]
        if len(s) < 20:
            continue
        s = s / s.iloc[0]
        rows.append({"组合": nm, "区间": "全期(2017起)", "口径": "日频", **perf(s)})
        for lab, a, b in SEGS:
            pp = seg_perf(s, a, b)
            if pp:
                rows.append({"组合": nm, "区间": lab, "口径": "日频", **pp})
    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(OUT, "perf_from2017.csv"), index=False, encoding="utf-8-sig")

    fmt = lambda x: "—" if pd.isna(x) else f"{x*100:6.2f}%"
    print(f"\n{'组合':<16}{'区间':<14}{'累计':>9}{'年化':>9}{'波动':>8}{'夏普':>7}{'回撤':>9}{'卡玛':>7}")
    for _, r in T.iterrows():
        print(f"{r['组合']:<16}{r['区间']:<14}{fmt(r['累计']):>9}{fmt(r['年化']):>9}"
              f"{fmt(r['年化波动']):>8}{r['夏普']:7.2f}{fmt(r['最大回撤']):>9}{r['卡玛']:7.2f}")

    # ── 新旧对照：同一 2017-01-01 起窗口，旧文件 vs 新文件 ──
    cmp_rows = []
    oldp = os.path.join(OUT, "daily_nav_15_fixed.csv")
    if os.path.exists(oldp):
        OLD = pd.read_csv(oldp, index_col=0, parse_dates=True)
        for nm, label in COMBOS:
            if nm not in OLD.columns:
                continue
            so = OLD[nm].dropna()
            so = so[so.index >= anchor]
            if len(so) < 20:
                continue
            so = so / so.iloc[0]
            po, pn = perf(so), perf(N[nm].dropna())
            cmp_rows.append({"组合": label,
                             "旧(2015起_裁到2017)年化": po["年化"], "新(2017起)年化": pn["年化"],
                             "差异": pn["年化"] - po["年化"],
                             "旧回撤": po["最大回撤"], "新回撤": pn["最大回撤"]})
        pd.DataFrame(cmp_rows).to_csv(os.path.join(OUT, "rebase_compare_2017.csv"),
                                      index=False, encoding="utf-8-sig")
        print("\n=== 同一窗口（2017-01-01 起）新旧一致性核对 ===")
        for r in cmp_rows:
            print(f"  {r['组合']:<16} 旧 {r['旧(2015起_裁到2017)年化']:7.2%}  新 {r['新(2017起)年化']:7.2%}  "
                  f"差 {r['差异']*100:+5.2f}pct  "
                  f"回撤 旧{r['旧回撤']:7.2%} 新{r['新回撤']:7.2%}")
        print("  说明：两者应几乎相等（同一套调仓与价格，仅锚点不同）；若不等说明重算有偏差。")

    print("\n完成：daily_nav_15_2017.csv / perf_from2017.csv / holdings_15_2017.csv")


if __name__ == "__main__":
    main()
