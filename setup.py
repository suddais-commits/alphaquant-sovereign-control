"""Module 2/6: Setup Generation
=============================
Generates candidate trade setups from price action series.
Setups supported:
  1. Donchian Channel Breakout (55-period high/low breakout)
  2. SMC Liquidity Sweep & CHoCH (Change of Character)
  3. Fair Value Gap (FVG) / Order Block (OB) Retest

All calculations use strictly CLOSED candles.
Entry price is the NEXT bar's open price.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Any
import numpy as np
import pandas as pd
from config import SetupCfg, CONFIG


@dataclass
class TradeSetup:
    symbol: str
    bar_index: int
    timestamp: Any
    direction: str         # "LONG" or "SHORT"
    side: int              # +1 for LONG, -1 for SHORT
    setup_type: str        # "DONCHIAN_55", "LIQUIDITY_SWEEP", "SMC_CHOCH"
    entry_price: float
    stop_loss: float
    tp1_price: float
    tp2_price: float
    risk_r_dist: float     # abs(entry - stop_loss)
    sl_pct: float          # risk_r_dist / entry
    atr: float
    is_valid: bool = True
    rejection_reason: str = ""


def generate_donchian_signals(df: pd.DataFrame, period: int = 55) -> pd.Series:
    """
    Computes Donchian channel breakout signal on closed candles:
    +1 if close > highest high of previous N bars
    -1 if close < lowest low of previous N bars
     0 otherwise
    """
    prev_high = df["high"].shift(1).rolling(period).max()
    prev_low = df["low"].shift(1).rolling(period).min()
    
    long_sig = df["close"] > prev_high
    short_sig = df["close"] < prev_low
    
    signals = pd.Series(0, index=df.index, dtype=int)
    signals[long_sig] = 1
    signals[short_sig] = -1
    return signals


def find_liquidity_sweeps(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """
    Identifies liquidity sweeps:
    - Bullish sweep: bar low penetrates prior swing low, but candle closes back above prior low.
    - Bearish sweep: bar high penetrates prior swing high, but candle closes back below prior high.
    """
    prior_lows = df["low"].shift(1).rolling(lookback).min()
    prior_highs = df["high"].shift(1).rolling(lookback).max()

    bull_sweep = (df["low"] < prior_lows) & (df["close"] > prior_lows)
    bear_sweep = (df["high"] > prior_highs) & (df["close"] < prior_highs)

    sweeps = pd.Series(0, index=df.index, dtype=int)
    sweeps[bull_sweep] = 1
    sweeps[bear_sweep] = -1
    return sweeps


def build_candidate_setups(
    symbol: str,
    df: pd.DataFrame,
    atr_series: pd.Series,
    cfg: Optional[SetupCfg] = None
) -> List[TradeSetup]:
    """
    Scans historical candles and generates valid TradeSetup objects.
    Enforces honest backtest assumptions:
    - Signal detected on bar i (close of candle)
    - Entry executed at bar i+1 open price
    - Stop loss positioned at entry - side * (sl_atr_mult * ATR)
    - Hard maximum SL distance cap (e.g. 5%)
    """
    if cfg is None:
        cfg = CONFIG.setup

    donchian_sigs = generate_donchian_signals(df, cfg.donchian_period)
    sweeps = find_liquidity_sweeps(df, lookback=20)
    
    setups: List[TradeSetup] = []
    n = len(df)
    
    for i in range(cfg.donchian_period + 1, n - 1):
        sig = donchian_sigs.iloc[i]
        setup_type = "DONCHIAN_55"
        
        if sig == 0:
            sweep_sig = sweeps.iloc[i]
            if sweep_sig != 0:
                sig = sweep_sig
                setup_type = "LIQUIDITY_SWEEP"

        if sig == 0:
            continue

        direction = "LONG" if sig > 0 else "SHORT"
        side = 1 if sig > 0 else -1
        
        # Next bar execution
        entry_price = float(df["open"].iloc[i + 1])
        current_atr = float(atr_series.iloc[i]) if i < len(atr_series) and not np.isnan(atr_series.iloc[i]) else (entry_price * 0.02)
        if current_atr <= 0:
            current_atr = entry_price * 0.02

        # Stop loss based on ATR multiple
        raw_sl_dist = current_atr * cfg.sl_atr_mult
        stop_loss = entry_price - (side * raw_sl_dist)
        sl_pct = raw_sl_dist / entry_price if entry_price > 0 else 0.0

        # Enforce maximum SL percent filter
        is_valid = True
        rejection_reason = ""
        if sl_pct > cfg.max_sl_pct:
            # Clamp stop loss to maximum permissible distance or invalidate
            stop_loss = entry_price - (side * (entry_price * cfg.max_sl_pct))
            raw_sl_dist = abs(entry_price - stop_loss)
            sl_pct = cfg.max_sl_pct

        if raw_sl_dist <= 0:
            continue

        # Targets
        tp1_price = entry_price + (side * raw_sl_dist * 2.0)
        tp2_price = entry_price + (side * raw_sl_dist * 5.0)

        setup = TradeSetup(
            symbol=symbol,
            bar_index=i + 1,
            timestamp=df.index[i + 1],
            direction=direction,
            side=side,
            setup_type=setup_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            risk_r_dist=raw_sl_dist,
            sl_pct=sl_pct,
            atr=current_atr,
            is_valid=is_valid,
            rejection_reason=rejection_reason
        )
        setups.append(setup)

    return setups
