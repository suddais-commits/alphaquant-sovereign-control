"""
edge_test2.py - second, SMALL and PRE-DECLARED test (put it in the same folder as edge_test.py).
5 variants only (so we do not fish for a lucky result):
  4H Donchian20, 4H Donchian55, 1D Donchian20, 1D Donchian55  (trend breakouts, long+short)
  4H sweep-reclaim (reference)
Same rules as edge_test.py: fixed 1R, no risk brakes, same exit ladder, fees+slippage, matched random control (5 seeds),
but stop = 2.0 ATR for all of these (one fixed choice, not tuned).
A variant counts as "PASS" only if ALL are true:  signal mean R > 0,  signal-minus-random > 2 standard errors,
and the difference is > 0 in BOTH the first half and the second half of the period.
Run:  python edge_test2.py      (demo without internet: python edge_test2.py --demo)
Output: printed + edge_result2.txt
"""
import os, sys, time
import numpy as np, pandas as pd
import edge_test as E

E.ATR_MULT = 2.0
YEARS = {"4h": 4, "1d": 6}
VARIANTS = [("4H Donchian20", "4h", 20), ("4H Donchian55", "4h", 55),
            ("1D Donchian20", "1d", 20), ("1D Donchian55", "1d", 55), ("4H sweep-reclaim", "4h", "sweep")]

def download(sym, interval):
    import requests
    path = os.path.join(E.CACHE, f"{sym}_{interval}_{YEARS[interval]}y.csv")
    if os.path.exists(path): return pd.read_csv(path, index_col=0, parse_dates=True)
    os.makedirs(E.CACHE, exist_ok=True)
    start = int((time.time() - YEARS[interval] * 365 * 86400) * 1000); rows = []
    while True:
        data = None
        for h in E.HOSTS:
            try:
                r = requests.get(h + "/api/v3/klines", params=dict(symbol=sym, interval=interval, startTime=start, limit=1000), timeout=20)
                if r.status_code == 200: data = r.json(); break
            except Exception: pass
        if not data: break
        rows += data; start = data[-1][0] + 1
        if len(data) < 1000: break
        time.sleep(0.1)
    if len(rows) < 300: return None
    df = pd.DataFrame(rows).iloc[:, :6]; df.columns = ["t", "open", "high", "low", "close", "volume"]
    df.index = pd.to_datetime(df["t"], unit="ms"); df = df.drop(columns="t").astype(float).iloc[:-1]
    df.to_csv(path); return df

def demo_df(seed, interval):
    d = E.demo_df(seed)
    rule = "4h" if interval == "4h" else "1D"
    return d.resample(rule).agg(dict(open="first", high="max", low="min", close="last", volume="sum")).dropna()

def make_sides(df, a, sweep_side, param):
    if param == "sweep": return sweep_side
    hh = df.high.shift(1).rolling(param).max(); ll = df.low.shift(1).rolling(param).min()
    lg = (df.close > hh).values; sh = (df.close < ll).values
    s = np.where(lg & ~sh, 1, np.where(sh & ~lg, -1, 0)); s[:max(60, param + 5)] = 0
    return s

def evaluate(label, data, param):
    coins = {}
    for sym, df in data.items():
        a, sw = E.prep(df); coins[sym] = (df.index, a, make_sides(df, a, sw, param))
    sig, sigt, n_coin = [], [], {}
    for sym, (ix, a, side) in coins.items():
        tr = E.run_signals(a, [(int(i), int(side[i])) for i in np.where(side != 0)[0]]); n_coin[sym] = len(tr)
        sig += [r for _, r in tr]; sigt += [ix[i].value for i, _ in tr]
    if len(sig) < 30: return f"{label:<18} only {len(sig)} signal trades -> too few to judge (FAIL)"
    rnd, rndt = [], []
    for sd in E.SEEDS:
        rng = np.random.default_rng(sd)
        for sym, (ix, a, side) in coins.items():
            need = n_coin[sym]
            if need == 0: continue
            valid = np.arange(60, len(a["c"]) - 5)
            pick = np.sort(rng.choice(valid, size=min(len(valid), need * 4), replace=False))
            tr = E.run_signals(a, [(int(i), int(rng.choice([-1, 1]))) for i in pick])
            if len(tr) > need: tr = [tr[k] for k in sorted(rng.choice(len(tr), size=need, replace=False))]
            rnd += [r for _, r in tr]; rndt += [ix[i].value for i, _ in tr]
    sig, rnd = np.asarray(sig), np.asarray(rnd); sigt, rndt = np.asarray(sigt, dtype='int64'), np.asarray(rndt, dtype='int64')
    s, r = E.stats(sig), E.stats(rnd)
    se = lambda x: x["se2"] / 2
    diff = s["mean"] - r["mean"]; sed = np.hypot(se(s), se(r))
    cut = int(np.median(sigt)); d1 = sig[sigt <= cut].mean() - rnd[rndt <= cut].mean(); d2 = sig[sigt > cut].mean() - rnd[rndt > cut].mean()
    ok = s["mean"] > 0 and diff > 2 * sed and d1 > 0 and d2 > 0
    months = [str(pd.Timestamp(t).to_period("M")) for t in sigt]; ci = E.boot(sig, months, B=2000)
    return (f"{label:<18} signal N={s['n']} win={s['win']:.1f}% meanR={s['mean']:+.3f}+/-{s['se2']:.3f} PF={s['pf']:.2f} monthBoot95=[{ci[0]:+.3f},{ci[1]:+.3f}]\n"
            f"{'':<18} random N={r['n']} meanR={r['mean']:+.3f}+/-{r['se2']:.3f} | diff={diff:+.3f} (noise ~{sed:.3f}) | half1={d1:+.3f} half2={d2:+.3f}"
            f" -> {'PASS' if ok else 'FAIL'}")

def main(demo=False):
    syms = E.COINS if not demo else [f"DEMO{i}" for i in range(4)]
    cache, out = {}, ["", "=== TREND / HIGHER-TIMEFRAME TEST (5 pre-declared variants, stop 2.0 ATR) ==="]
    for label, tf, param in VARIANTS:
        if tf not in cache:
            cache[tf] = {}
            for k, s in enumerate(syms):
                df = demo_df(k, tf) if demo else download(s + "USDT", tf)
                if df is not None and len(df) > 150: cache[tf][s] = df
            print(tf, "coins loaded:", len(cache[tf]), flush=True)
        out.append(evaluate(label, cache[tf], param)); print(out[-1], flush=True)
    out.append("\nVariants tested: 5. A PASS only means 'worth paper trading', not 'profitable'. If all FAIL: no edge found here either.")
    txt = "\n".join(out); open("edge_result2.txt", "w", encoding="utf-8").write(txt); print(txt)

if __name__ == "__main__":
    main(demo="--demo" in sys.argv)
