"""Honest testing. Pardo: walk-forward + walk-forward efficiency. Lopez de Prado: purged CV with embargo, deflated Sharpe.
A single 7-day backtest proves nothing; this is the tooling that does."""
import numpy as np
from statistics import NormalDist

_N = NormalDist()

def walk_forward_splits(n, train, test, step=None):
    """Yield (train_idx, test_idx) rolling windows. e.g. train=90 days, test=30 days (in bars)."""
    step = step or test
    s = 0
    while s + train + test <= n:
        yield np.arange(s, s + train), np.arange(s + train, s + train + test)
        s += step

def walk_forward_efficiency(train_perf_annualised: float, test_perf_annualised: float):
    """Pardo: out-of-sample / in-sample performance. ~>0.5 fine, <0.3 or negative = overfit."""
    return np.nan if train_perf_annualised == 0 else test_perf_annualised / train_perf_annualised

def purged_kfold(n, t1_idx, k=5, embargo_pct=0.01):
    """t1_idx[i] = index where label i is resolved. Train samples whose label window overlaps the test fold are
    removed (purged), and an embargo follows each test fold. Yields (train_idx, test_idx)."""
    t1_idx = np.asarray(t1_idx); folds = np.array_split(np.arange(n), k); emb = int(n * embargo_pct)
    for f in folds:
        lo, hi = f[0], f[-1]
        test = f
        train = []
        for i in range(n):
            if lo <= i <= hi: continue
            if i < lo and t1_idx[i] >= lo: continue            # label leaks into test fold
            if hi < i <= hi + emb: continue                     # embargo
            train.append(i)
        yield np.array(train), test

def sharpe(returns, periods_per_year=365):
    r = np.asarray(returns, float)
    return 0.0 if r.std(ddof=1) == 0 or len(r) < 2 else r.mean() / r.std(ddof=1) * np.sqrt(periods_per_year)

def deflated_sharpe(sr_per_period, n_trials, n_obs, skew=0.0, kurt=3.0, sr_trials_var=None):
    """Probability the true Sharpe > 0 after correcting for how many variants you tried (Bailey & Lopez de Prado).
    sr_per_period: NON-annualised Sharpe of the chosen strategy. n_trials: how many configs/thresholds you tested.
    Below ~0.95 you should not trust the result."""
    g = 0.5772156649
    v = sr_trials_var if sr_trials_var is not None else 1.0 / n_obs
    sr0 = np.sqrt(v) * ((1 - g) * _N.inv_cdf(1 - 1.0 / n_trials) + g * _N.inv_cdf(1 - 1.0 / (n_trials * np.e))) if n_trials > 1 else 0.0
    denom = np.sqrt(max(1e-12, 1 - skew * sr_per_period + (kurt - 1) / 4.0 * sr_per_period ** 2))
    return _N.cdf((sr_per_period - sr0) * np.sqrt(n_obs - 1) / denom)

def min_trades_warning(n_trades, need=100):
    return None if n_trades >= need else f"only {n_trades} trades - need {need}+ before believing win rate / profit factor"
