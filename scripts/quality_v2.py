# -*- coding: utf-8 -*-
"""质量 Top28 组合 v2 的选股与加权规则（纯函数，无 IO，便于单测）。

规则（依据见 2026-10 的因子归因报告）：
  1) 候选：当期股池内按 FAQ 得分降序、申万三级行业 ≤2 只，取满 LQ 只
  2) 流动性：20 日均成交额 < FLOOR 的剔除；剩余不足 MIN_KEEP 时放宽到 FLOOR_LOW
  3) 拥挤度：换手代理（20 日均成交额/总市值）在候选内部排序，剔除分位 > DROP_HI
  4) 权重：w ∝ 1/(换手分位 + TAU)，水位法限幅 [W_LO, W_HI]（严格不越界）
数据缺失时降级：没有换手数据的标的按中性分位（0.5）处理；整期无换手数据则退回 v1 权重。
"""
from __future__ import annotations

LQ = 28
MAX_PER_IND = 2
FLOOR = 5e7            # 5,000 万元
FLOOR_LOW = 3e7        # 3,000 万元（候选不足时的放宽值）
MIN_KEEP = 15          # 放宽判据：保留数低于此值才放宽
DROP_HI = 2 / 3
TAU = 0.15
W_LO, W_HI = 0.02, 0.08
MIN_FINAL = 8          # 过滤后少于 8 只 → 判定规则失效，退回 v1


def _cap_weights(w, lo=W_LO, hi=W_HI, iters=None):
    """限幅：水位法（water-filling），保证 Σ=1 且每只严格落在 [lo, hi]。

    旧实现是「限幅 → 归一」反复迭代 80 次，但**最后一次归一又把上限拉破**：
    19 只里若有 2 只触 8%、其余被压到 2%，此时 sum=0.92，末次归一给出
    0.08/0.92 = 8.6957%，承诺的 8% 上限直接失效（601138、600188 实测值）。

    水位法：先按比例分配；超上限的钉在上限、低于下限的钉在下限，扣掉已钉部分
    后把剩余权重按比例分给「未触限」的标的，循环直到全部入界。
    总和恒为 1，不需要最后再归一，因此不会二次越界。
    """
    n = len(w)
    if n == 0:
        return []
    s = float(sum(w))
    if not (s > 0):
        return [1.0 / n] * n
    x = [float(v) / s for v in w]
    # 可行性修正：n 只凑满 100%，单只上限至少 1/n、下限至多 1/n
    hi = max(float(hi), 1.0 / n)
    lo = min(float(lo), 1.0 / n)
    fixed, free, rem = {}, list(range(n)), 1.0
    while free:
        sfree = sum(x[i] for i in free)
        if not (sfree > 0):
            for i in free:
                fixed[i] = rem / len(free)
            break
        pend = {i: rem * x[i] / sfree for i in free}
        over = [i for i in free if pend[i] > hi + 1e-12]
        under = [i for i in free if pend[i] < lo - 1e-12]
        if not over and not under:
            for i in free:
                fixed[i] = pend[i]
            break
        if over:                                   # 先压上限（更常见的越界方向）
            for i in over:
                fixed[i] = hi
                rem -= hi
            free = [i for i in free if i not in set(over)]
        else:                                      # 再抬下限
            for i in under:
                fixed[i] = lo
                rem -= lo
            free = [i for i in free if i not in set(under)]
        if rem <= 1e-12:                           # 约束冲突 → 等权兜底
            eq = 1.0 / n
            return [min(max(eq, lo), hi) for _ in range(n)]
    return [fixed[i] for i in range(n)]


def select_v2(cands, sw3, turn_map, lq=LQ, max_per_ind=MAX_PER_IND,
              floor=FLOOR, floor_low=FLOOR_LOW, min_keep=MIN_KEEP,
              drop_hi=DROP_HI, tau=TAU, w_lo=W_LO, w_hi=W_HI):
    """cands: [(code, score)] 已按得分降序；turn_map: {code: (adv20, turn)}
    返回 (picked, meta)：
      picked = [(code, weight, turn_pct)]
      meta   = {"degrade": "ok"/"v1"/"no_turn", "floor": 实际使用的门槛, "n_final": ...}
    """
    # ① 行业约束下的候选
    base, cnt = [], {}
    for c, s in cands:
        if len(base) >= lq:
            break
        ind = sw3.get(c, "未分类")
        if cnt.get(ind, 0) >= max_per_ind:
            continue
        cnt[ind] = cnt.get(ind, 0) + 1
        base.append((c, s))
    if not base:
        return [], {"degrade": "v1", "floor": None, "n_final": 0}

    # ② 流动性门槛（逐级放宽）
    used_floor, pool = None, base
    for f in (floor, floor_low):
        cand_f = [(c, s) for c, s in base
                  if c in turn_map and turn_map[c][0] >= f]
        no_data = [(c, s) for c, s in base if c not in turn_map]
        cand_f = cand_f + no_data          # 缺数据的保留（不因缺数据被误杀）
        if len(cand_f) >= min_keep or f == floor_low:
            used_floor, pool = f, cand_f
            break

    # ③ 换手分位（有数据的按分位排序，缺数据的给中性 0.5）
    have = [(c, s) for c, s in pool if c in turn_map]
    if len(have) < MIN_FINAL:
        return base, {"degrade": "no_turn", "floor": used_floor, "n_final": len(base)}
    order = sorted(have, key=lambda x: turn_map[x[0]][1])
    pct = {c: (i + 0.5) / len(order) for i, (c, _) in enumerate(order)}
    rows = [(c, s, pct.get(c, 0.5)) for c, s in pool]
    rows = [r for r in rows if r[2] <= drop_hi]

    if len(rows) < MIN_FINAL:
        return base, {"degrade": "v1", "floor": used_floor, "n_final": len(rows)}

    # ④ 反换手加权
    raw = [1.0 / (r[2] + tau) for r in rows]
    w = _cap_weights(raw, w_lo, w_hi)
    picked = [(r[0], w[i], r[2]) for i, r in enumerate(rows)]
    return picked, {"degrade": "ok", "floor": used_floor, "n_final": len(picked)}


def weights_v1(n):
    """原方案权重：前 3 名各 16%，其余均分 52%"""
    if n <= 0:
        return []
    if n <= 3:
        return [1.0 / n] * n
    rest = (1.0 - 0.16 * 3) / (n - 3)
    return [0.16] * 3 + [rest] * (n - 3)
