# -*- coding: utf-8 -*-
"""补拉 2019-01-01 → 2023-12-31 的股池个股前复权日线（把回测起点前移到 2019 年）。

与 scripts/fetch_prices.py 同一口径（qfq 前复权、逐日收盘价），
但写入独立文件 data/prices_hist.csv，避免污染已有的 2024 年至今数据；
抓取完成后由 scripts/merge_prices.py 合并去重。
"""
import subprocess, sys, os, json, time, csv

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
EXE = r"C:\Users\12066\.local\bin\westock.exe"
BASE = r"C:\Users\12066\WorkBuddy\2026-10-05-23-13-30"
OUT = os.path.join(BASE, "data", "prices_hist.csv")
PROG = os.path.join(BASE, "data", "price_hist_progress.json")
START = "2019-01-01"
END = "2023-12-31"


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
    print(f"total={len(codes)} todo={len(todo)}", flush=True)

    exists = os.path.exists(OUT) and os.path.getsize(OUT) > 0
    f = open(OUT, "a", encoding="utf-8", newline="")
    w = None
    batch, sleep_s = 5, 6.0
    i = 0
    cons_ok = 0
    t0 = time.time()
    while i < len(todo):
        chunk = todo[i:i + batch]
        try:
            r = subprocess.run([EXE, "kline", ",".join(chunk), "--period", "day",
                                "--start", START, "--end", END, "--fq", "qfq"],
                               capture_output=True, timeout=300)
            txt = r.stdout.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            txt = ""
        if "服务限频" in txt or not txt.strip():
            sleep_s = min(120.0, sleep_s * 1.5)
            cons_ok = 0
            if batch > 2:
                batch = max(2, batch - 2)
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
            sleep_s = max(3.0, sleep_s * 0.8)
        rate = len(done) / max(1e-9, (time.time() - t0) / 60)
        print(f"[ok] rows={n} done={len(done)}/{len(codes)} rate={rate:.1f}/min "
              f"eta={(len(codes) - len(done)) / max(1e-9, rate):.0f}min", flush=True)
        i += len(chunk)
        time.sleep(sleep_s)
    f.close()
    print("DONE", len(done), flush=True)


if __name__ == "__main__":
    main()
