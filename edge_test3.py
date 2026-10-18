"""
edge_test3.py - compares TWO exit styles on the daily Donchian signals (same folder as edge_test.py and edge_test2.py).
  LADDER : your old v2 exit  (30% at 2R, break-even, 30% at 5R, runner trails EMA50)
  TRAIL3 : YOUR idea  - no fixed TP, no partial close, no break-even. Only the initial stop (2 ATR).
           Once price reaches +3R the stop starts trailing 3 ATR behind the best price. Trade ends only by a stop.
Each exit is compared with a RANDOM control that uses the SAME exit (the exit alone can add profit, so we only trust the difference).
Two coin groups: the 30 original coins, and 20 NEW coins the earlier tests never saw (fairer check).
PASS (pre-declared) = signal mean > 0  AND  month-bootstrap 95% interval of (signal - random) is above 0  AND  both halves of time positive.
Run:  python edge_test3.py      (no-internet check: python edge_test3.py --demo)      Output: edge_result3.txt
"""
import sys
import numpy as np, pandas as pd
import edge_test as E
import edge_test2 as E2

E.ATR_MULT = 2.0
ACT_R, TRAIL_K = 3.0, 3.0
NEW = ["TRX","BCH","XLM","HBAR","ALGO","VET","SAND","MANA","GRT","CRV","RUNE","STX","IMX","EGLD","THETA","AXS","CHZ","LDO","MKR","SNX"]
SIGNALS = [("1D Donchian20", 20), ("1D Donchian55", 55)]

def sim_trail(a, i, side):
    n = len(a["c"]); e = i + 1
    if e >= n - 1 or not np.isfinite(a["atr"][i]) or a["atr"][i] <= 0: return None
    entry = a["o"][e] * (1 + side * E.SLIP / 1e4); stop = a["c"][i] - side * E.ATR_MULT * a["atr"][i]; dist = abs(entry - stop)
    if dist <= 0 or (side > 0 and stop >= entry) or (side < 0 and stop <= entry): return None
    R = lambda px: side * (px - entry) / dist
    cur, best, active, ex, real, stopped = stop, entry, False, e, 0.0, False
    for j in range(e, min(e + E.MAX_BARS, n - 1) + 1):
        hi, lo = a["h"][j], a["l"][j]
        if (lo <= cur) if side > 0 else (hi >= cur):
            real = R(cur * (1 - side * E.SLIP / 1e4)); ex = j; stopped = True; break
        best = max(best, hi) if side > 0 else min(best, lo)
        if not active and R(best) >= ACT_R: active = True
        if active:
            new = best - side * TRAIL_K * a["atr"][j]
            if (side > 0 and new > cur) or (side < 0 and new < cur): cur = new
        ex = j
    if not stopped: real = R(a["c"][ex])
    return real - 2 * E.FEE / 1e4 * entry / dist, ex

def run(a, cand, mode):
    out, last = [], -1
    for i, s in cand:
        if i <= last: continue
        r = E.sim_one(a, i, s) if mode == "ladder" else sim_trail(a, i, s)
        if r is None: continue
        out.append((i, r[0])); last = r[1]
    return out

def boot_diff(sR, sM, rR, rM, B=2000):
    months = np.unique(np.concatenate([sM, rM])); rng = np.random.default_rng(1)
    gs = {m: sR[sM == m] for m in months}; gr = {m: rR[rM == m] for m in months}; res = []
    for _ in range(B):
        pick = months[rng.integers(0, len(months), len(months))]
        s = np.concatenate([gs[m] for m in pick]); r = np.concatenate([gr[m] for m in pick])
        if len(s) and len(r): res.append(s.mean() - r.mean())
    return np.percentile(res, [2.5, 97.5])

def evaluate(tag, coins, mode):
    sig, sigt, n_coin = [], [], {}
    for sym, (ix, a, side) in coins.items():
        tr = run(a, [(int(i), int(side[i])) for i in np.where(side != 0)[0]], mode); n_coin[sym] = len(tr)
        sig += [r for _, r in tr]; sigt += [ix[i].value for i, _ in tr]
    if len(sig) < 40: return f"{tag}: only {len(sig)} trades -> too few (FAIL)"
    rnd, rndt = [], []
    for sd in E.SEEDS:
        rng = np.random.default_rng(sd)
        for sym, (ix, a, side) in coins.items():
            need = n_coin[sym]
            if need == 0: continue
            valid = np.arange(60, len(a["c"]) - 5)
            pick = np.sort(rng.choice(valid, size=min(len(valid), need * 4), replace=False))
            tr = run(a, [(int(i), int(rng.choice([-1, 1]))) for i in pick], mode)
            if len(tr) > need: tr = [tr[k] for k in sorted(rng.choice(len(tr), size=need, replace=False))]
            rnd += [r for _, r in tr]; rndt += [ix[i].value for i, _ in tr]
    sig, rnd = np.asarray(sig), np.asarray(rnd); sigt, rndt = np.asarray(sigt, dtype="int64"), np.asarray(rndt, dtype="int64")
    mk = lambda t: np.array([str(pd.Timestamp(int(x)).to_period("M")) for x in t])
    s, r = E.stats(sig), E.stats(rnd); cut = int(np.median(sigt))
    d1 = sig[sigt <= cut].mean() - rnd[rndt <= cut].mean(); d2 = sig[sigt > cut].mean() - rnd[rndt > cut].mean()
    lo, hi = boot_diff(sig, mk(sigt), rnd, mk(rndt)); ok = s["mean"] > 0 and lo > 0 and d1 > 0 and d2 > 0
    wins = sig[sig > 0]; loss = sig[sig < 0]
    return (f"{tag:<34} signal N={s['n']} win={s['win']:.1f}% meanR={s['mean']:+.3f} PF={s['pf']:.2f} avgWin={wins.mean():+.2f} avgLoss={loss.mean():+.2f}\n"
            f"{'':<34} random meanR={r['mean']:+.3f} | diff={s['mean']-r['mean']:+.3f}  monthBoot95(diff)=[{lo:+.3f},{hi:+.3f}]  half1={d1:+.3f} half2={d2:+.3f} -> {'PASS' if ok else 'FAIL'}")

def load(syms, demo, offset=0):
    d = {}
    for k, s in enumerate(syms):
        df = E2.demo_df(k + offset, "1d") if demo else E2.download(s + "USDT", "1d")
        if df is not None and len(df) > 150: d[s] = df
    return d

def main(demo=False):
    groups = {"ORIGINAL 30 coins": load(E.COINS if not demo else [f"D{i}" for i in range(4)], demo),
              "NEW 20 coins (unseen)": load(NEW if not demo else [f"N{i}" for i in range(4)], demo, 50)}
    out = ["", "=== DAILY: LADDER exit vs YOUR TRAIL3 exit (each vs a random control with the same exit) ==="]
    for gname, data in groups.items():
        out.append(f"\n--- {gname}: {len(data)} coins loaded ---")
        for label, param in SIGNALS:
            coins = {}
            for sym, df in data.items():
                a, sw = E.prep(df); coins[sym] = (df.index, a, E2.make_sides(df, a, sw, param))
            for mode in ("ladder", "trail"):
                out.append(evaluate(f"{label} [{'LADDER' if mode=='ladder' else 'TRAIL3'}]", coins, mode)); print(out[-1], flush=True)
    out.append("\nCaveat: coin lists are coins that exist TODAY (survivorship), and coins move together, so even a PASS = 'worth paper trading', not 'profitable'.")
    txt = "\n".join(out); open("edge_result3.txt", "w", encoding="utf-8").write(txt); print(txt)

if __name__ == "__main__":
    main("--demo" in sys.argv)
