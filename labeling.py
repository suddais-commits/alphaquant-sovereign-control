"""Lopez de Prado ch.3: triple-barrier labels + meta-labeling. Use to LEARN when your SMC signal is worth taking."""
import numpy as np, pandas as pd

def triple_barrier(df, events, side, atr_series, pt_mult=2.0, sl_mult=1.0, max_bars=48):
    """events: index labels where a signal fired. side: Series of +1/-1 at those events.
    Barriers scale with ATR. Returns DataFrame[ret, label, t1, bars]. Conservative: if both barriers
    are hit in one bar, the STOP is assumed first."""
    idx = df.index; rows = []
    for t in events:
        i = idx.get_loc(t); s = int(side.loc[t]); entry = df["close"].iloc[i]; a = atr_series.iloc[i]
        if not np.isfinite(a) or a <= 0: continue
        pt = entry + s * pt_mult * a; sl = entry - s * sl_mult * a
        end = min(i + max_bars, len(df) - 1); label = 0; exit_i = end; exit_px = df["close"].iloc[end]
        for j in range(i + 1, end + 1):
            hi, lo = df["high"].iloc[j], df["low"].iloc[j]
            hit_sl = lo <= sl if s > 0 else hi >= sl
            hit_pt = hi >= pt if s > 0 else lo <= pt
            if hit_sl: label, exit_i, exit_px = -1, j, sl; break
            if hit_pt: label, exit_i, exit_px = 1, j, pt; break
        ret = s * (exit_px / entry - 1)
        if label == 0: label = int(np.sign(ret))          # vertical barrier: sign of return
        rows.append((t, ret, label, idx[exit_i], exit_i - i))
    return pd.DataFrame(rows, columns=["t0", "ret", "label", "t1", "bars"]).set_index("t0")

def meta_labels(tb: pd.DataFrame):
    """1 = the primary signal made money, 0 = it did not. Train a small classifier on this (features: regime,
    ADX, ATR pct, TF agreement, group scores) and take the trade only if P(1) is high."""
    return (tb["ret"] > 0).astype(int)
