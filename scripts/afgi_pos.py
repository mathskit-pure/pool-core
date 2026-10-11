# -*- coding: utf-8 -*-
"""
AFGI 仓位管理 —— 公共计算模块（供 refresh_page.py / daily_refresh.py 调用，每日重算）

【规则】（v4 逆向风险预算 —— 与页面「动量×AFGI稳健联合」说明段一致）
  页面公示口径（2026-10-08 定稿，页面 v34/v35/v37 上线时落地的版本）：
    · 权益仓位由 AFGI **逆向**风险预算决定 —— 越恐惧越加仓、越贪婪越减仓：
          S ≤ 40            → 100%
          40 < S ≤ 55       → 84%
          55 < S ≤ 70       → 60%
          S > 70            → 35%
    · 叠加两道保护：
        (a) 沪深300 低于前 60 日均线时，总仓位上限降至 20%；
        (b) 按前 60 个交易日实现波动率 σ60 做 18% 年化目标缩放，且只降仓不加杠杆：
                P = min( 情绪分档上限, 18% / σ60 )
            （分档本身就是「不加杠杆」的上限，故不是相乘而是取小）
    · 仓位变化只在其底层动量轮动策略的既定调仓点生效（T 日决策、T+1 开盘执行），
      调仓日之间不随情绪波动调整；并对总仓位变化扣除单边 5bp 摩擦成本。
      ⚠ 2026-10-10 起调仓间隔 K 由 5 个交易日改为 10 个交易日（与底层策略同步）。

  ⚠ 历史事故（2026-10-09 修复）：本模块曾用 v3-sentiment-only
    「P = 70% × clip((S−40)/40, 0, 1)」——那是**顺势**（贪婪加仓、恐惧空仓），
    与页面公示的逆向规则相反，导致每日刷新把已发布的曲线（全区间 +51.84%、夏普 1.06）
    悄悄替换成 +20.24%、近 1 年 −1.60%。现改回逆向口径，RULE_TAG 同步升版以整段重算。

【口径校准】
  参数（60 日窗口、总体标准差 ddof=0、√252 年化）由页面 v38 的真实曲线反解标定：
  176 个调仓日反解仓位与公式值平均绝对误差 0.2pp，全区间复现 +53.4%
  （原发布值 +51.84%，差异来自此后 nav.csv 的行情回填）。

【边界】
  · 调仓日无可用 AFGI（如起算日 2023-02-09 早于 AFGI 首个交易日）时，
    取最保守档 35%，与历史发布曲线一致。

【历史口径约定】
  data/afgi_combo_nav.csv 是「动量轮动·AFGI仓位」组合的历史净值基准（2023-02-09 起，
  起算日 = 1.0）。规则版本写在 data/afgi_combo_rule.txt：版本不一致时整段重算，
  一致时只在其尾部追加新增交易日，历史部分永不重算，确保报告中的历史统计数字稳定。
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

ROOT = r"C:\Users\12066\WorkBuddy\2026-10-05-23-13-30"
AFGI_ROOT = r"C:\Users\12066\WorkBuddy\2026-10-05-14-50-58\afgi_tdx"

AFGI_FILE = os.path.join(AFGI_ROOT, "output", "afgi_timeseries.csv")
NAV_FILE = os.path.join(ROOT, "data", "nav.csv")
HOLD_FILE = os.path.join(ROOT, "data", "holdings.csv")
COMBO_FILE = os.path.join(ROOT, "data", "afgi_combo_nav.csv")
RULE_FILE = os.path.join(ROOT, "data", "afgi_combo_rule.txt")

INCEPTION = "2023-02-09"                 # AFGI 数据起点，也是该组合起算日
# 规则版本；变更此常量即触发历史整段重算。
# v5（2026-10-10）：底层动量轮动策略改版为 N=15/K=10/L50（无行业上限、T+1 开盘执行、
#   涨停权重空置、单边 10bp），调仓点由「每 5 个交易日」变为「每 10 个交易日」，
#   故调仓日序列与策略日收益都变了 → 必须整段重算，不能沿用 v4 的历史净值。
RULE_TAG = "v5-momentum-n15k10l50"

# ── 规则参数（逆向风险预算）────────────────────────────────────────
# 情绪分档：越恐惧仓位越高（逆向）。(S 上界, 目标仓位上限)
SENT_TIERS = ((40.0, 1.00), (55.0, 0.84), (70.0, 0.60), (float("inf"), 0.35))
VOL_TARGET = 0.18       # 年化波动率目标
VOL_WIN = 60            # 实现波动率窗口（交易日）
MA_WIN = 60             # 沪深300 均线窗口（交易日）
MA_CAP = 0.20           # 沪深300 低于均线时的总仓位上限
COST_BP = 0.0005        # 总仓位变化的单边摩擦成本
START_POS = 1.0         # 起算日仓位 100%


# ── 基础数据 ─────────────────────────────────────────────────────────
def load_afgi() -> pd.Series:
    df = pd.read_csv(AFGI_FILE, usecols=["date", "afgi"]).sort_values("date")
    return pd.Series(df["afgi"].astype(float).values,
                     index=df["date"].astype(str))


def load_nav() -> pd.DataFrame:
    """本地净值表（含动量策略与沪深300）"""
    nav = pd.read_csv(NAV_FILE, index_col=0)
    nav.index = pd.to_datetime(nav.index).strftime("%Y-%m-%d")
    return nav.sort_index().astype(float)


def load_strategy_nav() -> pd.Series:
    """动量轮动策略净值，2019-11-01 定基为 1.0（与页面统计口径一致）"""
    nav = load_nav()
    s = nav["策略"].astype(float)
    s = s[s.index >= "2019-11-01"]
    return s / s.iloc[0]


def rebalance_dates() -> list:
    """回测调仓日序列（权威来源：holdings.csv）"""
    hold = pd.read_csv(HOLD_FILE, dtype={"代码": str})
    return sorted(set(hold["调仓日"].astype(str)))


# ── 仓位计算 ─────────────────────────────────────────────────────────
def sentiment_cap(s: float) -> float:
    """情绪分档给出的仓位上限（逆向：恐惧 → 高仓位）。S 缺失时取最保守档 35%。"""
    if s is None or not np.isfinite(s):
        return SENT_TIERS[-1][1]
    for hi, pos in SENT_TIERS:
        if float(s) <= hi:
            return pos
    return SENT_TIERS[-1][1]


def target_position(s: float, sigma: float = None, below_ma: bool = False) -> float:
    """目标权益仓位（小数）。

    P = min( 情绪分档上限(S), 18% / σ60 )      —— 分档即不加杠杆的上限，只降仓
    再叠加：沪深300 低于前 60 日均线时 P = min(P, 20%)
    """
    p = sentiment_cap(s)
    if sigma is not None and np.isfinite(sigma) and sigma > 0:
        p = min(p, VOL_TARGET / float(sigma))
    if below_ma:
        p = min(p, MA_CAP)
    return float(max(0.0, p))


def _sigma_at(nav: pd.DataFrame, d: str, win: int = VOL_WIN) -> float:
    """截至（含）d 的动量策略前 win 个交易日实现波动率（年化，总体标准差）。"""
    i = nav.index.get_loc(d)
    r = nav["策略"].iloc[max(1, i - win + 1): i + 1].pct_change().dropna()
    if len(r) < 20:
        return float("nan")
    return float(r.std(ddof=0) * np.sqrt(252))


def _below_ma(nav: pd.DataFrame, d: str, win: int = MA_WIN) -> bool:
    """沪深300 是否低于其前 win 个交易日均线。"""
    i = nav.index.get_loc(d)
    if i < win - 1:
        return False
    return float(nav["沪深300"].iloc[i]) < float(nav["沪深300"].iloc[i - win + 1: i + 1].mean())


def build_position_states(afgi: pd.Series, strat: pd.Series):
    """
    返回 {调仓日: 目标仓位(小数)}。
    调仓日 t 读取当日（或此前最近一个交易日的）AFGI 数值 S，
    按逆向风险预算算出目标仓位，在 t+1 日起生效。
    """
    reb = [d for d in rebalance_dates() if d >= INCEPTION]
    keys = sorted(afgi.index)
    nav = load_nav()
    states = {}
    for d in reb:
        if d not in nav.index:
            continue
        prior = [k for k in keys if k <= d]
        s = float(afgi.loc[prior[-1]]) if prior else float("nan")
        states[d] = target_position(s, _sigma_at(nav, d), _below_ma(nav, d))
    return states


def effective_position(states: dict, start_override: float = START_POS):
    """
    返回函数 eff(day) → 当日生效仓位（小数）。

    · INCEPTION 之后第一个调仓日（含）之前：起始仓位 start_override（100%）
    · 此后：取「最近一个已过调仓日 t（t < day）」算出的仓位（T 日决策、T+1 执行）
    """
    reb = sorted(states.keys())

    def eff(d):
        prior = [t for t in reb if t < d]
        if not prior:
            return start_override
        return states[prior[-1]]
    return eff


def factor_series(states: dict, pct=True):
    if pct:
        return {d: round(v * 100, 2) for d, v in states.items()}
    return dict(states)


def afgi_reading_at_rebalance() -> dict:
    """每个调仓日读取到的 AFGI 原始读数 S（0–100）。

    取值口径与 build_position_states 完全一致：取「≤ 调仓日」的最后一个交易日读数。
    AFGI 数据起点（2023-02-09）之前无可用读数，返回 None（页面显示「—」）。
    """
    afgi = load_afgi()
    keys = sorted(afgi.index)
    out = {}
    for d in rebalance_dates():
        prior = [k for k in keys if k <= d]
        out[d] = float(afgi.loc[prior[-1]]) if prior else None
    return out


def afgi_state_of(s: float) -> str:
    """AFGI 数值 → 五档状态名，阈值与 afgi/config.py 的 STATE_BANDS 一致。"""
    if s is None or not np.isfinite(s):
        return "未知"
    if s <= 20:
        return "极度恐惧"
    if s <= 40:
        return "恐惧"
    if s <= 60:
        return "中性"
    if s <= 80:
        return "贪婪"
    return "极度贪婪"


def latest_afgi_reading():
    """最新一期 AFGI：{date, afgi, state, ma5, ma20, change}。

    优先读 output/afgi_latest.json（AFGI 定时任务每次运行都会覆写），
    文件缺失时回落到 afgi_timeseries.csv 末行。读不到返回 None。
    """
    latest_json = os.path.join(AFGI_ROOT, "output", "afgi_latest.json")
    if os.path.exists(latest_json):
        try:
            j = json.load(open(latest_json, encoding="utf-8"))
            d = str(j.get("trade_date", ""))
            if len(d) == 8:
                d = "%s-%s-%s" % (d[:4], d[4:6], d[6:])
            return {"date": d, "afgi": float(j.get("afgi")),
                    "state": j.get("state") or afgi_state_of(float(j.get("afgi"))),
                    "ma5": j.get("ma5"), "ma20": j.get("ma20"),
                    "change": j.get("change")}
        except Exception:
            pass
    try:
        df = pd.read_csv(AFGI_FILE)
        if not len(df):
            return None
        r = df.iloc[-1]
        v = float(r["afgi"])
        return {"date": str(r["date"]), "afgi": v, "state": str(r.get("afgi_state", "")),
                "ma5": r.get("afgi_ma5"), "ma20": r.get("afgi_ma20"),
                "change": r.get("afgi_change")}
    except Exception:
        return None


def factor_at_rebalance(pct=True) -> dict:
    """每个调仓日当天「应配置的总仓位」（%）= 该调仓日算出的最终仓位。
    2023-02-09 之前的调仓日返回 None（该组合尚未起算）。"""
    states = build_position_states(load_afgi(), load_strategy_nav())
    fac = factor_series(states, pct=pct)
    out = {}
    for d in rebalance_dates():
        out[d] = fac.get(d)
    return out


# ── 组合净值：冻结历史 + 增量延伸 ─────────────────────────────────────
def _rule_ok() -> bool:
    if not os.path.exists(RULE_FILE):
        return False
    try:
        return open(RULE_FILE, encoding="utf-8").read().strip() == RULE_TAG
    except Exception:
        return False


def _save_rule():
    with open(RULE_FILE, "w", encoding="utf-8") as f:
        f.write(RULE_TAG + "\n")


def load_combo_history() -> dict:
    if not os.path.exists(COMBO_FILE):
        return {}
    if not _rule_ok():
        print("  · AFGI 仓位规则已变更（%s），历史净值整段重算" % RULE_TAG, flush=True)
        return {}
    df = pd.read_csv(COMBO_FILE)
    return dict(zip(df["date"].astype(str), df["nav"].astype(float)))


def save_combo_history(series: dict):
    keys = sorted(series.keys())
    pd.DataFrame({"date": keys, "nav": [series[k] for k in keys]}).to_csv(
        COMBO_FILE, index=False, encoding="utf-8")
    _save_rule()


def combo_nav(extend=True, rebase_to=None):
    """
    返回 {date: nav}，起算日 = 1.0。

    extend=True 时：历史沿用 afgi_combo_nav.csv（规则版本一致才沿用），
    缺失的新交易日按「该日生效仓位 × 策略当日收益」追加，并写回 CSV。
    """
    strat = load_strategy_nav()
    dates = [d for d in strat.index if d >= INCEPTION]
    hist = load_combo_history()

    states = build_position_states(load_afgi(), strat)
    eff = effective_position(states)

    out, val, prev_p = {}, 1.0, START_POS
    for i, d in enumerate(dates):
        p = eff(d)
        if i == 0:
            out[d] = 1.0
            val = 1.0
            prev_p = p
            continue
        if hist and d in hist:
            out[d] = hist[d]
            val = hist[d]
            prev_p = p
            continue
        prev = dates[i - 1]
        r = strat[d] / strat[prev] - 1.0
        cost = COST_BP * abs(p - prev_p)        # 总仓位变化的单边摩擦成本
        val = val * (1.0 + p * r - cost)
        out[d] = val
        prev_p = p

    if extend and (not hist or dates[-1] != max(hist.keys())):
        save_combo_history({k: round(v, 8) for k, v in out.items()})

    if rebase_to:                    # 图上对齐用：乘以某日的动量策略净值
        out = {k: v * rebase_to for k, v in out.items()}
    return out


def rebase_factor() -> float:
    """画面曲线的重定基系数 = 动量策略在 AFGI 起算日的净值"""
    s = load_strategy_nav()
    if INCEPTION in s.index:
        return float(s.loc[INCEPTION])
    prior = [d for d in s.index if d <= INCEPTION]
    return float(s.loc[prior[-1]]) if prior else 1.0


def current_position_pct() -> float:
    """截至 AFGI 最新交易日，当前所处的目标仓位（%）"""
    afgi = load_afgi()
    strat = load_strategy_nav()
    states = build_position_states(afgi, strat)
    if not states:
        return 100.0
    return round(states[max(states.keys())] * 100, 2)


if __name__ == "__main__":
    afgi = load_afgi()
    print("AFGI：%s → %s，%d 个交易日" % (afgi.index[0], afgi.index[-1], len(afgi)))
    print("当前目标仓位：%.2f%%" % current_position_pct())
    print("当前 AFGI：%.2f" % float(afgi.iloc[-1]))
    print()
    fac = factor_at_rebalance()
    for d in rebalance_dates()[-5:]:
        v = fac.get(d)
        print("调仓日 %s → 仓位 %s" % (d, ("%.2f%%" % v) if v is not None else "—"))
    print()
    nav = combo_nav(extend=False)
    ks = sorted(nav.keys())
    print("组合净值：%s=%.4f → %s=%.4f（累计 %.2f%%）"
          % (ks[0], nav[ks[0]], ks[-1], nav[ks[-1]], (nav[ks[-1]] - 1) * 100))
