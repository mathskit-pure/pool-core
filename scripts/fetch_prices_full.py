# -*- coding: utf-8 -*-
"""重拉股池个股全区间（2019-01-01 → 最新交易日）后复权日线。

为什么改用 hfq：qfq 以前复权基准（最新日）折算历史价，对长期高分红个股会把
2019-2022 年的价格折成负数（如 sh600039 四川路桥 2019-01 为 -0.23、sh600188
兖矿能源出现 531 个负价），用 pct_change 会得到荒谬收益。hfq 以后复权锚定
起点，历史价格恒为正且日收益即「含分红的总回报」，适合长周期回测。

同时一次性覆盖 2019→最新，避免两段不同复权基准拼接产生的断点跳空。
"""
import subprocess, sys, os, json, time, csv
from datetime import date

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
EXE = r"C:\Users\12066\.local\bin\westock.exe"
BASE = r"C:\Users\12066\WorkBuddy\2026-10-05-23-13-30"
OUT = os.path.join(BASE, "data", "prices_full.csv")
PROG = os.path.join(BASE, "data", "price_full_progress.json")
START = "2019-01-01"
END = date.today().strftime("%Y-%m-%d")


def parse(txt):
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
    return rows


def main():
    codes = json.load(open(os.path.join(BASE, "scripts", "codes_pool.json"), encoding="utf-8"))
    prog = json.load(open(PROG, encoding="utf-8")) if os.path.exists(PROG) else {"done": []}
    done = set(prog["done"])
    todo = [c for c in codes if c not in done]
    print(f"total={len(codes)} todo={len(todo)} range={START}..{END}", flush=True)

    exists = os.path.exists(OUT) and os.path.getsize(OUT) > 0
    f = open(OUT, "a", encoding="utf-8", newline="")
    w = None
    # 单次 2 只 × 约 1880 个交易日 ≈ 3740 行，实测可完整返回；批量再大会被截断
    batch, sleep_s = 2, 4.0
    i = 0
    cons_ok = 0
    t0 = time.time()
    while i < len(todo):
        chunk = todo[i:i + batch]
        try:
            r = subprocess.run([EXE, "kline", ",".join(chunk), "--period", "day",
                                "--start", START, "--end", END, "--fq", "hfq"],
                               capture_output=True, timeout=300)
            txt = r.stdout.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            txt = ""
        if "服务限频" in txt or not txt.strip():
            sleep_s = min(120.0, sleep_s * 1.5)
            cons_ok = 0
            if batch > 1:
                batch = max(1, batch - 1)
            print(f"[fail] batch={batch} sleep={sleep_s:.1f} done={len(done)}", flush=True)
            time.sleep(sleep_s)
            continue
        rows = parse(txt)
        if not rows:
            i += len(chunk)
            continue
        if w is None:
            w = csv.DictWriter(f, fieldnames=["code", "date", "close"], extrasaction="ignore")
            if not exists:
                w.writeheader()
        n = 0
        for r_ in rows:
            d = r_.get("date") or r_.get("Date")
            c = r_.get("last") or r_.get("close") or r_.get("Close")
            if not d or not c:
                continue
            w.writerow({"code": r_.get("code"), "date": d, "close": c})
            n += 1
        got = {r_.get("code") for r_ in rows if r_.get("code")}
        for c in (got or set(chunk)):
            done.add(c)
        prog["done"] = sorted(done)
        json.dump(prog, open(PROG, "w", encoding="utf-8"), ensure_ascii=False)
        f.flush()
        cons_ok += 1
        if cons_ok >= 3:
            cons_ok = 0
            sleep_s = max(3.0, sleep_s * 0.85)
        rate = len(done) / max(1e-9, (time.time() - t0) / 60)
        print(f"[ok] rows={n} done={len(done)}/{len(codes)} rate={rate:.1f}/min "
              f"eta={(len(codes) - len(done)) / max(1e-9, rate):.0f}min", flush=True)
        i += len(chunk)
        time.sleep(sleep_s)
    f.close()
    print("DONE", len(done), flush=True)


if __name__ == "__main__":
    main()
