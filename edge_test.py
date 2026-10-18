"""
edge_test.py  -  ONE script, no AI tokens needed.
Question it answers: does the raw sweep-reclaim signal beat RANDOM entries?
 - fixed 1R risk per trade, NO risk brakes (so nothing halts the test)
 - same exit ladder as v2 (BE @2R, 30% @2R, 30% @5R then stop +2.5R, runner trails EMA50), fees 4bps/side, slippage 5bps
 - one open trade per coin; random control has the SAME number of trades per coin (5 seeds)
 - month-level bootstrap because coins move together
Run:  pip install numpy pandas requests      then      python edge_test.py
Quick plumbing check without internet:  python edge_test.py --demo
Result is printed and saved to edge_result.txt (paste the last ~30 lines to Claude).
NOTE: the sweep-reclaim rule below is a simple version (15-bar sweep + close back inside, stop 1.5 ATR).
It may differ from your sweep_reclaim_signal.py.
"""
import os, sys, time
import numpy as np, pandas as pd

COINS = ["BTC","ETH","SOL","BNB","XRP","DOGE","AVAX","LINK","NEAR","SUI","ADA","LTC","DOT","APT","ARB",
         "OP","INJ","TIA","SEI","FET","RENDER","PEPE","SHIB","WIF","ATOM","UNI","ICP","AAVE","ETC","FIL"]
YEARS, LOOKBACK, ATR_MULT, MAX_BARS = 2, 15, 1.5, 400
FEE, SLIP = 4.0, 5.0                       # bps
TP1, TP1F, TP2, TP2F, TRAIL_R = 2.0, 0.30, 5.0, 0.30, 2.5
SEEDS = [42, 101, 777, 2024, 9999]
HOSTS = ["https://data-api.binance.vision", "https://api.binance.com"]
CACHE = "edge_cache"

def download(sym):
    import requests
    path = os.path.join(CACHE, f"{sym}_1h.csv")
    if os.path.exists(path):
        return pd.read_csv(path, index_col=0, parse_dates=True)
    os.makedirs(CACHE, exist_ok=True)
    start = int((time.time() - YEARS * 365 * 86400) * 1000); rows = []
    while True:
        data = None
        for h in HOSTS:
            try:
                r = requests.get(h + "/api/v3/klines", params=dict(symbol=sym, interval="1h", startTime=start, limit=1000), timeout=20)
                if r.status_code == 200: data = r.json(); break
            except Exception: pass
        if not data: break
        rows += data; start = data[-1][0] + 1
        if len(data) < 1000: break
        time.sleep(0.1)
    if len(rows) < 2000: return None
    df = pd.DataFrame(rows).iloc[:, :6]; df.columns = ["t","open","high","low","close","volume"]
    df.index = pd.to_datetime(df["t"], unit="ms"); df = df.drop(columns="t").astype(float)
    df = df.iloc[:-1]                                   # drop the forming candle
    df.to_csv(path); return df

def demo_df(seed):
    rng = np.random.default_rng(seed); n = 17000
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, n))); o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + abs(rng.normal(0, .002, n))); l = np.minimum(o, c) * (1 - abs(rng.normal(0, .002, n)))
    return pd.DataFrame(dict(open=o, high=h, low=l, close=c, volume=1.0), index=pd.date_range("2024-01-01", periods=n, freq="1h"))

def prep(df):
    pc = df["close"].shift(1)
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    a = dict(o=df.open.values, h=df.high.values, l=df.low.values, c=df.close.values,
             atr=tr.ewm(alpha=1/14, adjust=False).mean().values, ema=df.close.ewm(span=50, adjust=False).mean().values)
    pl = df.low.shift(1).rolling(LOOKBACK).min(); ph = df.high.shift(1).rolling(LOOKBACK).max()
    long_ = ((df.low < pl) & (df.close > pl)).values; short_ = ((df.high > ph) & (df.close < ph)).values
    side = np.where(long_ & ~short_, 1, np.where(short_ & ~long_, -1, 0))
    side[:60] = 0
    return a, side

def sim_one(a, i, side):
    n = len(a["c"]); e = i + 1
    if e >= n - 1 or not np.isfinite(a["atr"][i]) or a["atr"][i] <= 0: return None
    entry = a["o"][e] * (1 + side * SLIP / 1e4); stop = a["c"][i] - side * ATR_MULT * a["atr"][i]
    dist = abs(entry - stop)
    if dist <= 0 or (side > 0 and stop >= entry) or (side < 0 and stop <= entry): return None
    R = lambda px: side * (px - entry) / dist
    rem, real, cur, state, be, ex = 1.0, 0.0, stop, 0, False, e
    for j in range(e, min(e + MAX_BARS, n - 1) + 1):
        hi, lo = a["h"][j], a["l"][j]
        if (lo <= cur) if side > 0 else (hi >= cur):
            real += rem * R(cur * (1 - side * SLIP / 1e4)); rem = 0; ex = j; break
        fav = hi if side > 0 else lo
        if not be and R(fav) >= TP1: cur = entry; be = True
        if state == 0 and R(fav) >= TP1: real += TP1F * TP1; rem -= TP1F; state = 1
        if state == 1 and R(fav) >= TP2: real += TP2F * TP2; rem -= TP2F; state = 2; cur = entry + side * TRAIL_R * dist
        if state == 2:
            tr = a["ema"][j - 1]
            if (side > 0 and tr > cur) or (side < 0 and tr < cur): cur = tr
        ex = j
    if rem > 1e-9: real += rem * R(a["c"][ex])
    return real - 2 * FEE / 1e4 * entry / dist, ex

def run_signals(a, idx_side):
    out, last = [], -1
    for i, s in idx_side:
        if i <= last: continue
        r = sim_one(a, i, s)
        if r is None: continue
        out.append((i, r[0])); last = r[1]
    return out

def stats(R):
    R = np.asarray(R, float); n = len(R)
    if n < 2: return dict(n=n)
    w, l = R[R > 0].sum(), -R[R < 0].sum()
    return dict(n=n, win=(R > 0).mean() * 100, mean=R.mean(), se2=2 * R.std(ddof=1) / np.sqrt(n), pf=w / l if l > 0 else np.inf)

def boot(R, months, B=3000, seed=1):
    R = np.asarray(R); months = np.asarray(months); um = np.unique(months); rng = np.random.default_rng(seed)
    groups = {m: R[months == m] for m in um}; res = []
    for _ in range(B):
        pick = rng.choice(um, size=len(um), replace=True); v = np.concatenate([groups[m] for m in pick])
        res.append(v.mean())
    return np.percentile(res, [2.5, 97.5])

def fmt(name, s, ci=None):
    if s["n"] < 2: return f"{name:<22} N={s['n']}"
    t = f"{name:<22} N={s['n']:<6} win={s['win']:.1f}%  meanR={s['mean']:+.3f} +/-{s['se2']:.3f}  PF={s['pf']:.2f}"
    return t + (f"  monthBoot95=[{ci[0]:+.3f},{ci[1]:+.3f}]" if ci is not None else "")

def main(demo=False):
    coins = {}
    for k, sym in enumerate(COINS if not demo else [f"DEMO{i}" for i in range(6)]):
        df = demo_df(k) if demo else download(sym + "USDT")
        if df is None: print("skip", sym); continue
        coins[sym] = (df.index, *prep(df)); print("ok", sym, len(df), flush=True)
    sigR, sigM, per_coin_n = [], [], {}
    for sym, (ix, a, side) in coins.items():
        cand = [(i, int(side[i])) for i in np.where(side != 0)[0]]
        tr = run_signals(a, cand); per_coin_n[sym] = len(tr)
        sigR += [r for _, r in tr]; sigM += [str(ix[i].to_period("M")) for i, _ in tr]
    lines = ["", "=== RAW SWEEP-RECLAIM vs RANDOM (fixed 1R, no risk brakes) ==="]
    lines.append(fmt("Signal", stats(sigR), boot(sigR, sigM) if len(sigR) > 30 else None))
    allrR, allrM = [], []
    for sd in SEEDS:
        rng = np.random.default_rng(sd); rR, rM = [], []
        for sym, (ix, a, side) in coins.items():
            need = per_coin_n[sym]
            if need == 0: continue
            valid = np.arange(60, len(a["c"]) - 5)
            pick = np.sort(rng.choice(valid, size=min(len(valid), need * 4), replace=False))
            cand = [(int(i), int(rng.choice([-1, 1]))) for i in pick]
            tr = run_signals(a, cand)
            if len(tr) > need: tr = [tr[k] for k in sorted(rng.choice(len(tr), size=need, replace=False))]
            rR += [r for _, r in tr]; rM += [str(ix[i].to_period("M")) for i, _ in tr]
        lines.append(fmt(f"Random seed {sd}", stats(rR))); allrR += rR; allrM += rM
    lines.append(fmt("Random (all seeds)", stats(allrR), boot(allrR, allrM) if len(allrR) > 30 else None))
    s, r = stats(sigR), stats(allrR)
    if s["n"] > 1 and r["n"] > 1:
        lines.append(f"\nSignal minus random mean R = {s['mean'] - r['mean']:+.3f}   (noise level about +/-{s['se2']:.3f})")
        lines.append("VERDICT: " + ("signal looks better than random" if s["mean"] - r["mean"] > s["se2"] and s["mean"] > 0
                                    else "no clear edge over random"))
    lines.append("\nPer-coin trades: " + ", ".join(f"{k}:{v}" for k, v in per_coin_n.items()))
    txt = "\n".join(lines); print(txt); open("edge_result.txt", "w", encoding="utf-8").write(txt)

if __name__ == "__main__":
    main(demo="--demo" in sys.argv)
