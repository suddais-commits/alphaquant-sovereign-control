"""
edge_test5.py - can the DAILY Donchian55 system be improved? 3 pre-declared filters, tested fairly (same folder as edge_test.py ... edge_test3.py).
  BASE         : Donchian55 breakout, long + short                     (reference)
  LONG-ONLY    : only long breakouts
  BTC-ALIGNED  : trade only in the direction of BTC's 100-day trend (long if BTC > its 100-day average, short if below)
  VOLUME>1.5x  : breakout day volume > 1.5 x the previous 20-day average
Fair control: the random control draws random days from the SAME eligible days and the SAME allowed direction as the filter,
so we measure what the breakout adds ON TOP of the filter (not what the filter alone gives).
Exits: LADDER and TRAIL3 (stop 2 ATR, fees+slippage). Two coin groups: original 30 and 20 unseen coins.
A filter counts as an IMPROVEMENT only if, for the same exit, it PASSES in BOTH coin groups AND its signal-minus-random is larger than BASE in BOTH groups.
No other variants will be tried (more variants = more chances of a lucky result).
Run: python edge_test5.py     (no-internet check: python edge_test5.py --demo)     Output: edge_result5.txt
"""
import sys
import numpy as np, pandas as pd
import edge_test as E, edge_test2 as E2, edge_test3 as E3

E.ATR_MULT = 2.0
PARAM = 55
VARS = ["BASE", "LONG-ONLY", "BTC-ALIGNED", "VOLUME>1.5x"]

def prep_coin(df, bt_trend):
    a, sw = E.prep(df); side = E2.make_sides(df, a, sw, PARAM); n = len(df); allt = np.ones(n, bool)
    vol_ok = (df.volume > 1.5 * df.volume.shift(1).rolling(20).mean()).fillna(False).values
    bt = bt_trend.reindex(df.index).ffill().fillna(0).values.astype(int)
    return df.index, a, {"BASE": (side, allt, np.full(n, 2)),
                         "LONG-ONLY": (np.where(side > 0, side, 0), allt, np.full(n, 1)),
                         "BTC-ALIGNED": (np.where(side == bt, side, 0), bt != 0, bt),
                         "VOLUME>1.5x": (np.where(vol_ok, side, 0), vol_ok, np.full(n, 2))}

def evaluate(tag, coins, vname, mode):
    sig, sigt, n_coin = [], [], {}
    for sym, (ix, a, V) in coins.items():
        side = V[vname][0]; tr = E3.run(a, [(int(i), int(side[i])) for i in np.where(side != 0)[0]], mode); n_coin[sym] = len(tr)
        sig += [r for _, r in tr]; sigt += [ix[i].value for i, _ in tr]
    if len(sig) < 40: return f"{tag}: only {len(sig)} trades -> too few (FAIL)", False, float("nan")
    rnd, rndt = [], []
    for sd in E.SEEDS:
        rng = np.random.default_rng(sd)
        for sym, (ix, a, V) in coins.items():
            need = n_coin[sym]
            if need == 0: continue
            _, elig, allow = V[vname]; valid = np.where(elig[:len(a["c"]) - 5])[0]; valid = valid[valid >= 60]
            if len(valid) < 5: continue
            pick = np.sort(rng.choice(valid, size=min(len(valid), need * 4), replace=False))
            tr = E3.run(a, [(int(i), int(allow[i]) if allow[i] in (1, -1) else int(rng.choice([-1, 1]))) for i in pick], mode)
            if len(tr) > need: tr = [tr[k] for k in sorted(rng.choice(len(tr), size=need, replace=False))]
            rnd += [r for _, r in tr]; rndt += [ix[i].value for i, _ in tr]
    sig, rnd = np.asarray(sig), np.asarray(rnd); sigt, rndt = np.asarray(sigt, dtype="int64"), np.asarray(rndt, dtype="int64")
    mk = lambda t: np.array([str(pd.Timestamp(int(x)).to_period("M")) for x in t])
    s, r = E.stats(sig), E.stats(rnd); cut = int(np.median(sigt)); diff = s["mean"] - r["mean"]
    d1 = sig[sigt <= cut].mean() - rnd[rndt <= cut].mean(); d2 = sig[sigt > cut].mean() - rnd[rndt > cut].mean()
    lo, hi = E3.boot_diff(sig, mk(sigt), rnd, mk(rndt)); ok = s["mean"] > 0 and lo > 0 and d1 > 0 and d2 > 0
    return (f"{tag:<34} N={s['n']:<4} win={s['win']:.0f}% meanR={s['mean']:+.3f} PF={s['pf']:.2f} | random={r['mean']:+.3f} diff={diff:+.3f} "
            f"boot95=[{lo:+.3f},{hi:+.3f}] halves={d1:+.2f}/{d2:+.2f} -> {'PASS' if ok else 'FAIL'}"), ok, diff

def main(demo=False):
    syms1 = E.COINS if not demo else [f"D{i}" for i in range(4)]; syms2 = E3.NEW if not demo else [f"N{i}" for i in range(4)]
    btc = E2.demo_df(99, "1d") if demo else E2.download("BTCUSDT", "1d")
    bt_trend = np.sign(btc["close"] - btc["close"].rolling(100).mean()).fillna(0)
    groups = {"ORIGINAL 30": E3.load(syms1, demo), "UNSEEN 20": E3.load(syms2, demo, 50)}
    prepped = {g: {s: prep_coin(df, bt_trend) for s, df in d.items()} for g, d in groups.items()}
    out = ["", "=== DAILY DONCHIAN55: BASE vs 3 PRE-DECLARED FILTERS (fair control per filter) ==="]; res = {}
    for g, coins in prepped.items():
        out.append(f"\n--- {g}: {len(coins)} coins ---"); cc = {s: (ix, a, V) for s, (ix, a, V) in coins.items()}
        for v in VARS:
            for mode in ("ladder", "trail"):
                line, ok, diff = evaluate(f"{v} [{'LADDER' if mode=='ladder' else 'TRAIL3'}]", cc, v, mode)
                out.append(line); print(line, flush=True); res[(g, v, mode)] = (ok, diff)
    out.append("\n=== VERDICT (pre-declared rule: PASS in both groups AND better than BASE in both groups) ===")
    for v in VARS[1:]:
        for mode in ("ladder", "trail"):
            r1, r2, b1, b2 = (res.get((g, x, mode), (False, float("nan"))) for g, x in (("ORIGINAL 30", v), ("UNSEEN 20", v), ("ORIGINAL 30", "BASE"), ("UNSEEN 20", "BASE")))
            better = r1[1] > b1[1] and r2[1] > b2[1]
            out.append(f"{v:<14} {mode:<7} pass both groups: {'yes' if r1[0] and r2[0] else 'no':<3} | better than BASE in both: {'yes' if better else 'no':<3} -> {'IMPROVEMENT' if (r1[0] and r2[0] and better) else 'no improvement'}")
    out.append("\nIf nothing is an IMPROVEMENT, keep BASE. Do not try more variants after seeing this. Still only worth paper trading, not proven profit.")
    txt = "\n".join(out); open("edge_result5.txt", "w", encoding="utf-8").write(txt); print(txt)

if __name__ == "__main__":
    main("--demo" in sys.argv)
