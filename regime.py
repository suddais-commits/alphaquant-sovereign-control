"""Module 1/6: Regime Detection
==============================
Classifies market state into CHOP, TREND, BREAKOUT, TRANSITION, or WARMUP.
Grounding:
  - Dalton & Steidlmayer: Auction Market Theory (Balance / Chop vs Imbalance / Trend)
  - Kaufman: Efficiency Ratio (ER)
  - Wilder: Average Directional Index (ADX)
  - John Bollinger: Bandwidth Compression & Volatility Squeeze
"""
from __future__ import annotations
import math
from typing import Optional, Union, Dict, Any
import numpy as np
import pandas as pd
from config import RegimeCfg, CONFIG


def calc_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """True Range Wilder Exponential Smoothing."""
    pc = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"] - pc).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def calc_adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average Directional Index (ADX)."""
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = calc_atr(df, n)
    pdi = 100.0 * pd.Series(plus, index=df.index).ewm(alpha=1.0 / n, adjust=False).mean() / a.replace(0, np.nan)
    mdi = 100.0 * pd.Series(minus, index=df.index).ewm(alpha=1.0 / n, adjust=False).mean() / a.replace(0, np.nan)
    denom = (pdi + mdi).replace(0, np.nan)
    dx = 100.0 * (pdi - mdi).abs() / denom
    return dx.ewm(alpha=1.0 / n, adjust=False).mean()


def calc_efficiency_ratio(close: pd.Series, n: int = 20) -> pd.Series:
    """Kaufman Efficiency Ratio (Directional Net Change / Total Absolute Path)."""
    net_change = (close - close.shift(n)).abs()
    total_path = close.diff().abs().rolling(n).sum().replace(0, np.nan)
    return net_change / total_path


def calc_bb_bandwidth(close: pd.Series, n: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bandwidth: (Upper - Lower) / Middle."""
    mid = close.rolling(n).mean()
    std = close.rolling(n).std()
    upper = mid + k * std
    lower = mid - k * std
    bw = (2.0 * k * std) / mid.replace(0, np.nan)
    return bw, upper, lower


def calc_percentile_rank(s: pd.Series, window: int = 100) -> pd.Series:
    """Trailing window percentile rank of the latest value [0.0..1.0]."""
    return s.rolling(window).apply(lambda x: (x[:-1] < x[-1]).mean() if len(x) > 1 else np.nan, raw=True)


def classify_regime(df: pd.DataFrame, cfg: Optional[RegimeCfg] = None) -> pd.DataFrame:
    """
    Classifies candle dataframe into market regimes using past data only.
    Returns dataframe with computed metrics and 'regime' column.
    """
    if cfg is None:
        cfg = CONFIG.regime

    out = pd.DataFrame(index=df.index)
    out["adx"] = calc_adx(df, cfg.adx_n)
    atr_series = calc_atr(df, cfg.atr_n)
    out["atr"] = atr_series
    out["atr_pct"] = calc_percentile_rank(atr_series / df["close"], cfg.atr_rank_window)
    out["er"] = calc_efficiency_ratio(df["close"], cfg.er_n)

    bw, upper, lower = calc_bb_bandwidth(df["close"], cfg.bb_n, cfg.bb_k)
    out["bw_pct"] = calc_percentile_rank(bw, cfg.atr_rank_window)

    # Volatility Squeeze & Surge
    squeeze = (out["bw_pct"] < cfg.squeeze_pct).astype(float)
    recent_squeeze = squeeze.rolling(cfg.squeeze_lookback).max().shift(1).fillna(0) > 0
    vol_ma20 = df["volume"].rolling(20).mean()
    vol_surge = df["volume"] > cfg.vol_surge * vol_ma20
    outside_bb = (df["close"] > upper.shift(1)) | (df["close"] < lower.shift(1))

    breakout = recent_squeeze & vol_surge & outside_bb
    trend = (out["adx"] > cfg.adx_trend) & (out["er"] > cfg.er_trend)
    chop = (out["adx"] < cfg.adx_chop) & (out["atr_pct"] < cfg.atr_chop_pct) & (out["er"] < cfg.er_chop)

    reg = pd.Series("TRANSITION", index=df.index)
    reg[chop] = "CHOP"
    reg[trend] = "TREND"
    reg[breakout] = "BREAKOUT"
    reg[out["adx"].isna() | out["atr_pct"].isna() | out["er"].isna()] = "WARMUP"
    out["regime"] = reg

    # Moving Average Direction
    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    out["trend_dir"] = np.sign(ema20 - ema50).fillna(0).astype(int)

    return out
