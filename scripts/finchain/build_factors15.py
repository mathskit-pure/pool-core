# -*- coding: utf-8 -*-
"""2015-2026 官方中证800 成分内的 10 因子月度暴露 / 因子多空收益 / 因子拥挤F / 个股F。
口径严格对齐 fmf/src/f1.py + f2.py：
  size=-ln(mcap) bm=te/mcap roa=np/ta accr=-(np-cfo)/ta cp=cfo/mcap
  ep=np/mcap illiq=Amihud20 turn=vol20*100/shares bab=-beta60 ivol=-ivol60
因子多空：池内 z 分数 top20% − bottom20%，等权
"""
import os
import sys
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# --- 路径统一由 scripts/paths.py 解析：本机 Windows 与云端 Linux 同一份代码 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import FIN_D15 as D15, FIN_MON  # noqa: E402
os.makedirs(D15, exist_ok=True)
FACTORS = ["size", "bm", "roa", "accr", "cp", "ep", "illiq", "turn", "bab", "ivol"]
START_ME = "2014-01-01"  # 2014-01 末交易日为 01-30（春节），门槛须早于月末


def zs(s):
    lo, hi = s.quantile(0.01), s.quantile(0.99)
    s = s.clip(lo, hi)
    sd = s.std(ddof=1)
    return (s - s.mean()) / sd if sd and np.isfinite(sd) and sd > 0 else s * np.nan


def main():
    px = pd.read_pickle(os.path.join(D15, "px_daily.pkl"))
    fin = pd.read_pickle(os.path.join(D15, "fin_pit.pkl"))
    pit = pd.read_csv(os.path.join(D15, "official_csi800_pit_2015.csv"), dtype=str)
    pit["c"] = pit["code"].str[2:] if pit["code"].str[:2].isin(["sh", "sz"]).all() else pit["code"]
    pit["c"] = pit["code"].map(lambda x: x[2:] if x[:2] in ("sh", "sz") else x)
    member_by_asof = pit.groupby("asof")["c"].apply(set).to_dict()
    asofs = sorted(member_by_asof)

    px["code"] = px["code"].astype(str).str.zfill(6)
    px = px.sort_values(["code", "date"]).reset_index(drop=True)
    px["amount"] = px["amount"].replace(0, np.nan)

    ret = px.pivot(index="date", columns="code", values="ret")
    amt = px.pivot(index="date", columns="code", values="amount")
    vol = px.pivot(index="date", columns="code", values="volume")
    clo = px.pivot(index="date", columns="code", values="close")
    idxw = px.pivot(index="date", columns="code", values="idx")

    # 月末交易日
    dts = pd.Series(ret.index)
    me = pd.DatetimeIndex(dts.groupby([dts.dt.year, dts.dt.month]).max().values)
    me = me[me >= pd.Timestamp(START_ME)]
    print(f"[me] 月末 {len(me)} 个: {me[0]:%Y-%m-%d} ~ {me[-1]:%Y-%m-%d}", flush=True)

    # 市场代理（当期官方成分等权）
    mkt = ret.mean(axis=1)
    cov = ret.rolling(60, min_periods=40).cov(mkt)
    var = mkt.rolling(60, min_periods=40).var()
    beta = cov.div(var, axis=0)
    corr = ret.rolling(60, min_periods=40).corr(mkt)
    sd60 = ret.rolling(60, min_periods=40).std()
    ivol = np.sqrt((sd60 ** 2 * (1 - corr ** 2)).clip(lower=0))
    illiq20 = (ret.abs() / amt * 1e8).rolling(20, min_periods=10).mean()
    vol20 = vol.rolling(20, min_periods=10).mean()

    def melt(df, name):
        s = df.reindex(me).stack()
        s.index.names = ["date", "code"]
        return s.rename(name).reset_index()

    px_me = melt(clo, "close")
    for df, nm in [(illiq20, "illiq"), (beta, "beta"), (ivol, "ivol_d"), (vol20, "vol20")]:
        px_me = px_me.merge(melt(df, nm), on=["date", "code"], how="left")

    # 时点财务：avail <= 月末 取最近一期
    fin = fin.sort_values(["code", "avail"])
    fin["code"] = fin["code"].astype(str).str.zfill(6)
    codes = sorted(px["code"].unique())
    parts = []
    for d in me:
        sub = fin[fin["avail"] <= d]
        if sub.empty:
            continue
        latest = sub.drop_duplicates("code", keep="last")
        g = pd.DataFrame({"code": codes})
        parts.append(g.merge(latest, on="code", how="left").assign(date=d))
    base = pd.concat(parts, ignore_index=True)
    base = base.merge(px_me, on=["date", "code"], how="left")

    # 真实市值：用 qmj mon/ 的「未复权月收盘价」× 股本（覆盖 5256 只，含退市股，1991 起）
    import glob
    MON = str(FIN_MON)
    frs = []
    for p in glob.glob(os.path.join(MON, "*.csv")):
        c = os.path.basename(p)[:6]
        try:
            dd = pd.read_csv(p, dtype={"date": str})
        except Exception:
            continue
        if dd.empty or "close" not in dd.columns:
            continue
        dd["code"] = c
        frs.append(dd)
    mon = pd.concat(frs, ignore_index=True)
    mon["date"] = pd.to_datetime(mon["date"], errors="coerce")
    mon = mon.dropna(subset=["date"])
    mon["close"] = pd.to_numeric(mon["close"], errors="coerce")
    mon = mon[mon["close"] > 0]
    mon["ym"] = mon["date"].dt.to_period("M")
    mon_last = mon.sort_values("date").groupby(["code", "ym"], as_index=False).tail(1)
    mon_last = mon_last[["code", "ym", "close"]].rename(columns={"close": "close_raw"})
    base["ym"] = base["date"].dt.to_period("M")
    base = base.merge(mon_last, on=["code", "ym"], how="left")

    # 兜底：mon 缺失时用后复权价 ÷ 复权倍数（1%/99% 缩尾）
    sc = pd.read_csv(os.path.join(D15, "price_scale.csv"), dtype={"code": str})
    sc["code"] = sc["code"].str.zfill(6)
    last_px = px.sort_values("date").groupby("code")["close"].last().reset_index().rename(columns={"close": "px_hfq"})
    sc = sc.merge(last_px, on="code", how="left")
    sc["scale"] = np.where((sc["px_raw"] > 0) & (sc["px_hfq"] > 0), sc["px_hfq"] / sc["px_raw"], np.nan)
    lo, hi = sc["scale"].quantile(0.01), sc["scale"].quantile(0.99)
    sc["scale"] = sc["scale"].clip(lo, hi)
    base = base.merge(sc[["code", "scale"]], on="code", how="left")
    base["close_raw"] = base["close_raw"].fillna(base["close"] / base["scale"])
    base["mcap"] = base["close_raw"] * base["shares"]
    miss = base["mcap"].isna().mean()
    print(f"[mcap] 未复权价覆盖 {100*(1-miss):.1f}%，中位市值 {base['mcap'].median()/1e8:.0f} 亿", flush=True)
    base["size"] = -np.log(base["mcap"].where(base["mcap"] > 0))
    base["bm"] = base["te"] / base["mcap"]
    base["roa"] = base["np"] / base["ta"]
    base["accr"] = -(base["np"] - base["cfo"]) / base["ta"]
    base["cp"] = base["cfo"] / base["mcap"]
    base["ep"] = base["np"] / base["mcap"]
    base["turn"] = (base["vol20"] * 100.0) / base["shares"]
    base["bab"] = -base["beta"]
    base["ivol"] = -base["ivol_d"]
    base = base.dropna(subset=["mcap", "beta", "size"])
    base = base[base["mcap"] > 0].reset_index(drop=True)

    # 只保留"当期官方成分内"
    keep_mask = np.zeros(len(base), dtype=bool)
    for d, g in base.groupby("date"):
        # 取 asof <= d 的最近期成分
        cand = [a for a in asofs if pd.Timestamp(a) <= d]
        # 2014-01~04 无当期快照：用最早一期(2014-05，对应 2013-12 调样后成分)回填，PIT 正确
        mem = member_by_asof[cand[-1] if cand else asofs[0]]
        keep_mask[g.index] = g["code"].isin(mem).values
    base_in = base[keep_mask].copy()
    print(f"[pool] 成分内月度观测 {len(base_in):,} 行，均 {len(base_in)/len(me):.0f} 只/月", flush=True)

    # 池内 z 分数
    z = base_in.groupby("date")[FACTORS].transform(zs)
    z.columns = [f"z_{c}" for c in z.columns]
    out = pd.concat([base_in, z], axis=1)
    out.to_csv(os.path.join(D15, "expo_month_15.csv"), index=False)
    print(f"[expo] saved rows={len(out):,} 月={out['date'].nunique()}", flush=True)

    # 个股月度收益（t 月末 → t+1 月）
    idx_me = idxw.reindex(me)
    r_me = idx_me.shift(-1) / idx_me - 1.0
    lr = r_me.stack().rename("ret_next").reset_index()
    lr.columns = ["date", "code", "ret_next"]
    lr = lr.dropna().reset_index(drop=True)
    # 仅保留当期成分
    keep2 = np.zeros(len(lr), dtype=bool)
    for d, g in lr.groupby("date"):
        cand = [a for a in asofs if pd.Timestamp(a) <= d]
        # 2014-01~04 无当期快照：用最早一期(2014-05，对应 2013-12 调样后成分)回填，PIT 正确
        mem = member_by_asof[cand[-1] if cand else asofs[0]]
        keep2[g.index] = g["code"].isin(mem).values
    lr = lr[keep2]
    lr.to_csv(os.path.join(D15, "pool_ret_15.csv"), index=False)
    print(f"[ret] saved rows={len(lr):,}", flush=True)

    # 因子多空收益
    m = out[["date", "code"] + [f"z_{f}" for f in FACTORS]].merge(lr, on=["date", "code"], how="inner")

    def ls(g, col):
        k = max(1, int(len(g) * 0.2))
        return g.nlargest(k, col)["ret_next"].mean() - g.nsmallest(k, col)["ret_next"].mean()

    fr = pd.DataFrame({f: m.groupby("date").apply(lambda g, c=f"z_{f}": ls(g, c), include_groups=False)
                       for f in FACTORS})
    fr.index.name = "date"
    fr.to_csv(os.path.join(D15, "factor_ret_15.csv"))
    print(f"[fr] 因子收益 {fr.shape[0]} 月", flush=True)
    print(fr.describe().T[["mean", "std"]].to_string(), flush=True)


if __name__ == "__main__":
    main()
