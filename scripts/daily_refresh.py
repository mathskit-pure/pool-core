# -*- coding: utf-8 -*-
"""
每日收盘后增量刷新 —— 回测每日延伸、轮动持仓按 K=10 个交易日自动换仓。

⚠ 2026-10-10 口径切换：回测不再由 scripts/backtest.py 产出（那是已废止的
  旧口径 N=10/K=5/L=12 + 行业≤2 + 零成本），改由 mom_opt/scripts/rebuild.py
  用新引擎重算：N=15/K=10/L=50、无行业上限、T+1 开盘执行、涨停权重空置留现金、
  单边 10bp。若不切换，每日首刷会把已发布的 N15/K10/L50 结果整段回退。

用法：
    python scripts/daily_refresh.py                 # 增量行情 → 回测 → 生成页面 → 上传资料库
    python scripts/daily_refresh.py --no-import     # 不上传（只本地刷新）
    python scripts/daily_refresh.py --no-page       # 只到回测为止
    python scripts/daily_refresh.py --force         # 非交易日/无新数据时也重跑并上传

流程：
    1) 读 data/prices_full_v2.csv 的最新日期 last
    2) 用沪深300 探测 (last, 今天] 区间内是否已有新交易日；
       没有新交易日（节假日 / 数据未落地）→ 直接退出，不产生无谓的新版本
    3) 逐批增量拉取 560 只标的的 hfq 后复权日线（恒定 batch=2，限频只退避不降级）
    4) 增量刷新三大基准指数（沪深300 / 创业板50 / 科创50）
    5) 数据体检：非正价、涨跌停越界（主板 ±10.5%、创业板/科创 ±20.5%）
    5.5) 补齐原始不复权 OHLC（fetch_ohlc.py --incr）：涨停判定与 T+1 开盘价都在
         原始价格空间算，缺了它新引擎无法运行
    6) rebuild.py（新口径引擎）重跑回测（调仓日序列按 K=10 个交易日自动向下延伸）
    7) 生成 data/rebalance_signal.csv：最新一期持仓、本次换仓指令、距下次调仓天数
    8) refresh_page.py 就地刷新页面数据区（图表净值/统计表/4.1、4.2 持仓变动表
       /顶部 KPI 卡中的 AFGI 指数与当前仓位）
       —— 注意：AFGI 仓位管理的粉线组合已于 2026-10-08 下线，不再计算/回测/上线。
       —— 注意：不是 gen_page.py 全量重生成。线上页面含本地生成器产不出的内容
       （质量（盈利）Top20 组合、交互时间轴等），全量重生成会不可逆地抹掉它们；
       就地刷新只替换数据驱动区域，其余内容原样保留。
    9) import_html.py --node-block-id 覆写资料库页面节点
   10) 上传成功后把产物回写为 data/page_base.html，作为明天的刷新模板
       （保证模板永远与线上一致，并发编辑也不会丢失）

为什么调度他不单独做一个定时任务：
    A 股的交易日 ≠ 工作日（节假日会让"每 K 个工作日"与真实调仓节奏错位）。
    回测里的调仓日是由 K=5 在**真实交易日序列**上切出来的，所以本脚本每天跑一次，
    由脚本判断今天是不是调仓日并输出换仓指令，节奏才不会漂移。
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import date, timedelta

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 路径与环境差异统一交给 scripts/paths.py：本机 Windows 与云端 Linux 共用一份代码，
# 可用 POOL_BASE / MOM_OPT_DIR / WESTOCK_BIN / WB_LIBRARY_SKILL 等环境变量整体改写。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE, PY, WESTOCK as EXE, MOM_OPT, library_skill  # noqa: E402

DATA = os.path.join(BASE, "data")
PRICE_FILE = os.path.join(DATA, "prices_full_v2.csv")
BENCH_FILE = os.path.join(DATA, "bench_all.csv")
CODES_FILE = os.path.join(BASE, "scripts", "codes_pool.json")
PAGE_HTML = os.path.join(DATA, "pool_page.html")

PAGE_NODE = "iB8I58mCTooLicPQ0Kyq0M"          # 资料库页面节点（覆写目标）
PROBE = "sh000300"                             # 交易日探测器（沪深300）
BENCH = {"沪深300": "sh000300", "创业板50": "sz399673", "科创50": "sh000688"}

# ── 回测口径（2026-10-10 起，必须与 mom_opt/scripts/rebuild.py 完全一致）──
#   N=15 / K=10 / L=50、无申万三级行业上限、T+1 开盘执行、涨停权重空置留现金、
#   单边 10bp。旧口径 N=10/K=5/L=12（含行业 ≤2、零成本）已于 2026-10-10 废止。
K = 10         # 调仓间隔（交易日）
L = 50         # 动量组合持仓数
START = "2019-05-06"

# 重算脚本：不再用 scripts/backtest.py（那是已废止的旧口径，会把已发布的
# N15/K10/L50 结果整段回退）。新口径引擎在 mom_opt/scripts/engine.py，
# 入口 rebuild.py 一并产出 nav / holdings / removed / backtest_summary。
REBUILD = os.path.join(MOM_OPT, "scripts", "rebuild.py")
FETCH_OHLC = os.path.join(MOM_OPT, "scripts", "fetch_ohlc.py")
BATCH = 4      # 增量区间通常只有 1~5 天，响应很小，可以放大批次（长区间不可用）
LIMIT = {"主板": 0.105, "双创": 0.205}          # 涨跌停容差（含四舍五入）
SLEEP = 1.5    # 批间基础间隔

LOG = []


def log(msg):
    print(msg, flush=True)
    LOG.append(str(msg))


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, timeout=kw.pop("timeout", 1800))
    if r.returncode != 0:
        raise RuntimeError(f"命令失败: {' '.join(cmd[:3])}...\n"
                           f"{r.stdout.decode('utf-8', errors='replace')[-2000:]}\n"
                           f"{r.stderr.decode('utf-8', errors='replace')[-1000:]}")
    return r.stdout.decode("utf-8", errors="replace")


def parse_rows(txt, fallback=None):
    """解析 westock 表格输出。批量响应带 code 列；单只响应没有，用 fallback 回填。"""
    rows, hdr = [], None
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if hdr is None:
            hdr = cells
            continue
        if set("".join(cells)) <= set("- :"):
            continue
        if len(cells) == len(hdr):
            rows.append(dict(zip(hdr, cells)))
    if fallback and rows and "code" not in rows[0]:
        for r_ in rows:
            r_["code"] = fallback
    return rows


def probe_new_days(last):
    """探测 (last, 今天] 是否已有新交易日，返回新交易日列表。"""
    start = (last + timedelta(days=1)).strftime("%Y-%m-%d")
    end = date.today().strftime("%Y-%m-%d")
    if start > end:
        return []
    txt = run([EXE, "kline", PROBE, "--period", "day", "--start", start,
               "--end", end, "--fq", "qfq"], timeout=300)
    days = []
    for r_ in parse_rows(txt, fallback=PROBE):
        d = r_.get("date")
        if d and d[:2].isdigit():
            days.append(d)
    return sorted(set(days))


def fetch_prices(codes, start, end):
    """增量拉取个股 hfq 日线，返回 DataFrame[code, date, close]。

    分两轮：
      轮1  batch=4 批量请求 —— 增量窗口短，响应小，速度快；
           响应里的 code 集合必须是请求集合的子集（串码则整批丢弃重试）。
      轮2  轮1 里"没出现"的票逐只补 —— 批量请求会确定性漏票（历史踩过的坑），
           停牌票则本来就没有数据。单只响应没有 code 列，用 fallback 回填，
           不会错配。
    """
    got_rows, missing = [], []
    sleep_s = SLEEP
    todo = list(codes)
    t0 = time.time()
    while todo:
        retry = []
        i = 0
        while i < len(todo):
            chunk = todo[i:i + BATCH]
            try:
                txt = run([EXE, "kline", ",".join(chunk), "--period", "day",
                           "--start", start, "--end", end, "--fq", "hfq"], timeout=300)
            except Exception as e:                  # 超时/异常：退避重试
                log(f"  ! 批次异常 {chunk[0]}..{chunk[-1]}: {e} → 退避 {sleep_s:.0f}s")
                time.sleep(sleep_s)
                sleep_s = min(60.0, sleep_s * 1.5)
                retry.extend(chunk)
                i += BATCH
                continue
            rows = parse_rows(txt)
            if rows and "code" in rows[0]:
                seen = {r_["code"] for r_ in rows}
                if not seen.issubset(set(chunk)):    # 串码 → 整批丢弃重试
                    log(f"  ! 批次串码，重试 {chunk}")
                    time.sleep(sleep_s)
                    retry.extend(chunk)
                    i += BATCH
                    continue
                got_rows.extend(rows)
                miss = [c for c in chunk if c not in seen]
            else:                                    # 空响应 / 无 code 列 → 整批重试
                miss = list(chunk)
            # 缺失的先记下来，交给轮2 单只补（停牌票本来就没有数据）
            missing.extend(miss)
            i += BATCH
            sleep_s = max(SLEEP, sleep_s * 0.9)
            time.sleep(sleep_s)
        todo = retry
        if todo:
            log(f"  .. 轮1 重试队列 {len(todo)} 只")
            time.sleep(sleep_s)

    log(f"  轮1 完成 {len(got_rows)} 行 · {time.time() - t0:.0f}s · "
        f"待单只确认 {len(set(missing))} 只")

    if missing:
        sleep_s = SLEEP
        for c in sorted(set(missing)):
            try:
                txt = run([EXE, "kline", c, "--period", "day", "--start", start,
                           "--end", end, "--fq", "hfq"], timeout=300)
            except Exception:
                continue
            rows = parse_rows(txt, fallback=c)      # 单只响应没有 code 列
            got_rows.extend(rows)
            sleep_s = max(SLEEP, sleep_s * 0.9)
            time.sleep(sleep_s)
        log(f"  轮2 完成，累计 {len(got_rows)} 行 · {time.time() - t0:.0f}s")

    out = []
    for r_ in got_rows:
        c, d, v = r_.get("code"), r_.get("date"), r_.get("last") or r_.get("close")
        if not (c and d and d[:2].isdigit()):
            continue
        try:
            out.append({"code": c, "date": d, "close": float(v)})
        except (TypeError, ValueError):
            continue
    return pd.DataFrame(out)


def fetch_bench(start, end):
    """增量刷新三大基准指数。"""
    old = pd.read_csv(BENCH_FILE, index_col=0)
    old.index = pd.to_datetime(old.index)
    for name, code in BENCH.items():
        txt = run([EXE, "kline", code, "--period", "day", "--start", start,
                   "--end", end, "--fq", "qfq"], timeout=300)
        rows = parse_rows(txt, fallback=code)
        for r_ in rows:
            d = r_.get("date")
            v = r_.get("last") or r_.get("close")
            if not (d and d[:2].isdigit()):
                continue
            try:
                old.loc[pd.Timestamp(d), name] = float(v)
            except (TypeError, ValueError):
                continue
        log(f"  基准 {name}: +{len(rows)} 行")
    old = old.sort_index()
    old.to_csv(BENCH_FILE, encoding="utf-8-sig")
    return old


def health_check(px, new_days):
    """体检：非正价 + 涨跌停越界。

    为什么越界不直接判死：hfq 后复权的日收益是「含分红的总收益」，在除权除息日
    天然会略微越出涨跌停板（例：sz002074 2026-09-29 涨停 +10.01%，叠加当日除息
    后 hfq 收益 +10.87%）。历史全量数据里本来就有约 0.03% 的这类点。
    所以：非正价、越界率过高 → 判定为批量数据事故，阻断；
          零星越界 → 仅告警并记录，不阻断日常刷新。
    返回 (阻断级问题列表, 告警级问题列表)。
    """
    hard, soft = [], []
    if px.empty or not new_days:
        return hard, soft
    cols = px.columns
    n_point = 0
    for d in new_days:
        ts = pd.Timestamp(d)
        if ts not in px.index:
            continue
        cur = px.loc[ts]
        prev_rows = px.loc[:ts].iloc[:-1]
        prev = prev_rows.ffill().iloc[-1] if len(prev_rows) else pd.Series(index=cols, dtype=float)
        for c in cols:
            p1, p0 = cur.get(c), prev.get(c)
            if pd.isna(p1) or pd.isna(p0) or p0 <= 0:
                continue
            n_point += 1
            if p1 <= 0:
                hard.append(f"{ts.date()} {c} 非正价 {p1}")
                continue
            chg = p1 / p0 - 1
            lim = LIMIT["双创"] if (c.startswith("sz30") or c.startswith("sh688")) else LIMIT["主板"]
            if abs(chg) > lim:
                soft.append(f"{ts.date()} {c} 涨跌 {chg:+.2%} 越过 ±{lim:.0%}"
                            f"（多为除权除息日的总收益，非数据错误）")
    if n_point and len(soft) / n_point > 0.01:
        hard.append(f"涨跌停越界率 {len(soft)}/{n_point} = {len(soft) / n_point:.2%}，"
                    f"远超历史基线 0.03%，疑似复权因子或代码错配")
    return hard, soft


def rebalance_signal():
    """读回测产物，输出最新一期持仓 / 换仓指令 / 距下次调仓交易日数。"""
    px = pd.read_csv(PRICE_FILE, dtype={"code": str}, usecols=["code", "date"])
    dates = pd.DatetimeIndex(pd.to_datetime(pd.Series(px["date"].unique()))).sort_values()
    start_pos = int(dates.searchsorted(pd.Timestamp(START)))
    positions = list(range(start_pos, len(dates), K))
    last_pos = positions[-1]

    hold = pd.read_csv(os.path.join(DATA, "holdings.csv"))
    nav = pd.read_csv(os.path.join(DATA, "nav.csv"), index_col=0)

    cur_day = pd.Timestamp(dates[last_pos]).date()
    cur = hold[hold["调仓日"].astype(str) == str(cur_day)].copy()
    prev_day = pd.Timestamp(dates[positions[-2]]).date() if len(positions) > 1 else None
    prev = (hold[hold["调仓日"].astype(str) == str(prev_day)].copy()
            if prev_day else pd.DataFrame(columns=hold.columns))
    prev_codes = set(prev["代码"]) if len(prev) else set()

    cur["动作"] = cur["代码"].apply(lambda c: "买入" if c not in prev_codes else "持有")
    out_codes = prev_codes - set(cur["代码"])
    sells = prev[prev["代码"].isin(out_codes)][["代码", "名称", "申万三级"]].copy()
    sells["动作"] = "卖出"

    # 下次调仓位置固定是 last_pos + K；remain = 还需几个新交易日才到
    next_pos = last_pos + K
    remain = next_pos - (len(dates) - 1)
    next_day = (pd.Timestamp(dates[next_pos]).date()
                if next_pos < len(dates) else None)
    is_reb_day = (last_pos == len(dates) - 1)      # 最新交易日正好落在调仓日上

    sig = pd.concat([
        cur[["调仓日", "次序", "代码", "名称", "申万三级", "权重", "动作"]],
        sells.reindex(columns=["调仓日", "次序", "代码", "名称", "申万三级", "权重", "动作"])
    ], ignore_index=True)
    sig.to_csv(os.path.join(DATA, "rebalance_signal.csv"), index=False, encoding="utf-8-sig")

    return {
        "最新交易日": str(pd.Timestamp(dates[-1]).date()),
        "最新交易日为调仓日": "是（本期持仓已换仓）" if is_reb_day else "否",
        "最新调仓日": str(cur_day),
        "上期调仓日": str(prev_day) if prev_day else "-",
        "本次换仓": f"{int((cur['动作'] == '买入').sum())} 买 / {len(sells)} 卖 / "
                    f"{int((cur['动作'] == '持有').sum())} 持有",
        "距下次调仓": f"还需 {remain} 个新交易日"
                       + (f"（已排定 {next_day}）" if next_day else ""),
        "净值截止": str(nav.index[-1]),
        "策略累计": f"{nav['策略'].iloc[-1] - 1:+.1%}" if "策略" in nav.columns else "-",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-import", action="store_true", help="不上传资料库")
    ap.add_argument("--no-page", action="store_true", help="只跑到回测为止")
    ap.add_argument("--force", action="store_true", help="无新数据也重跑并上传")
    args = ap.parse_args()

    old = pd.read_csv(PRICE_FILE, dtype={"code": str})
    old["date"] = pd.to_datetime(old["date"])
    last = old["date"].max().date()
    log(f"本地行情最新日期：{last}  今天：{date.today()}")

    new_days = probe_new_days(last)
    if not new_days:
        log("未探测到新交易日（节假日 / 当日数据尚未落地）→ 跳过刷新")
        if not args.force:
            log("（如需强制重跑请加 --force）")
            return
        log("--force：无新数据也继续重跑")
    else:
        log(f"新交易日 {len(new_days)} 天：{new_days[0]} → {new_days[-1]}")
        start = (last + timedelta(days=1)).strftime("%Y-%m-%d")
        end = date.today().strftime("%Y-%m-%d")

        import json
        codes = sorted(json.load(open(CODES_FILE, encoding="utf-8")))
        log(f"增量拉取 {len(codes)} 只标的 {start}..{end}")
        inc = fetch_prices(codes, start, end)
        log(f"个股新增 {len(inc)} 行，覆盖 {inc['code'].nunique() if len(inc) else 0} 只")

        log("增量刷新基准指数")
        fetch_bench(start, end)

        merged = pd.concat([old, inc.assign(date=pd.to_datetime(inc["date"]))],
                           ignore_index=True)
        merged = merged.dropna(subset=["close"]).drop_duplicates(["code", "date"], keep="last")
        merged = merged.sort_values(["code", "date"])

        # 体检用：透视成价格矩阵，只看新增窗口
        px = merged.pivot(index="date", columns="code", values="close").sort_index()
        hard, soft = health_check(px, new_days)
        if soft:
            log(f"  体检告警 {len(soft)} 处（越界多为除权除息日总收益，不阻断）：")
            for p_ in soft[:10]:
                log("     " + p_)
            pd.DataFrame({"问题": soft}).to_csv(os.path.join(DATA, "daily_health.csv"),
                                                index=False, encoding="utf-8-sig")
        if hard:
            log(f"\n!! 发现 {len(hard)} 处阻断级异常，已中止（数据未写入、未上传）：")
            for p_ in hard[:20]:
                log("   " + p_)
            raise SystemExit("数据异常，已中止")
        log("数据体检通过（无非正价、无批量越界）")

        merged.to_csv(PRICE_FILE, index=False, encoding="utf-8")
        log(f"已写回 {PRICE_FILE}：{len(merged)} 行 / {merged['code'].nunique()} 只 "
            f"→ 最新 {merged['date'].max().date()}")

    log("\n=== 补齐原始 OHLC（涨停判定 / T+1 开盘价必需）===")
    run([PY, FETCH_OHLC, "--incr"], timeout=2400)

    log("\n=== 重跑回测（新口径引擎 N=15 / K=10 / L=50）===")
    out = run([PY, REBUILD], timeout=3600)
    log(out.strip().splitlines()[-6:] and "\n".join(out.strip().splitlines()[-6:]))

    info = rebalance_signal()
    log("\n=== 轮动状态 ===")
    for k_, v_ in info.items():
        log(f"  {k_}: {v_}")

    if args.no_page:
        log("\n--no-page：已跳过页面生成与上传")
        return

    log("\n=== 就地刷新页面数据区 ===")
    run([PY, os.path.join(BASE, "scripts", "refresh_page.py")], timeout=1800)
    log(f"页面已刷新：{PAGE_HTML}")

    if args.no_import:
        log("\n--no-import：已跳过上传")
        return

    log("\n=== 上传资料库 ===")
    out = run([PY, str(library_skill() / "page" / "import_html.py"), PAGE_HTML,
               "--node-block-id", PAGE_NODE], timeout=1800)
    line = [l for l in out.splitlines() if "KS_IMPORT_OK" in l]
    if not line:
        raise SystemExit("上传失败，未见到 KS_IMPORT_OK")
    log(line[0].strip())

    # 上传成功 → 本产物即为线上最新版，回写为明天的刷新模板
    import shutil
    shutil.copyfile(PAGE_HTML, os.path.join(DATA, "page_base.html"))
    log("已回写刷新模板：data/page_base.html")


if __name__ == "__main__":
    main()
