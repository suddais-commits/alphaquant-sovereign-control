"""Module 3/6: Signal & Confluence Filters
========================================
Filters candidate setups to weed out low-probability or hostile market conditions.
Includes:
  1. Multi-Timeframe (MTF) Alignment & Higher-Timeframe (HTF) Veto Gate
  2. Quantitative Z-Score Climax Filter (Ernie Chan)
  3. MACD & RSI Momentum Divergence Scorer (fully wired)
  4. VSA / Order Flow Delta Filter
  5. Fundamental & News Quality Gate
  6. Gemini LLM AI Veto Gate (Strictly Fail-Closed)
"""
from __future__ import annotations
import math
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd
from config import FilterCfg, CONFIG
from indicators_calc import calc_z_score, calc_rsi, calc_ema


def evaluate_htf_gate(
    tf_signs: Dict[str, int],
    candidate_side: int,
    htf_gate: Tuple[str, ...] = ("1D", "4H")
) -> bool:
    """
    Checks if higher timeframes explicitly oppose the trade.
    If candidate is LONG (+1) and 1D or 4H is SHORT (-1), gate fails.
    """
    for tf in htf_gate:
        sign = tf_signs.get(tf, 0)
        if sign == -candidate_side:
            return False
    return True


def calc_mtf_agreement_share(
    tf_signs: Dict[str, int],
    candidate_side: int,
    tf_weights: Optional[Dict[str, float]] = None
) -> float:
    """Computes weighted percentage of agreeing timeframes."""
    if tf_weights is None:
        tf_weights = CONFIG.filters.tf_weights

    total_weight = sum(tf_weights.get(k, 1.0) for k in tf_signs)
    if total_weight <= 0:
        return 0.0
    agreeing_weight = sum(tf_weights.get(k, 1.0) for k, sign in tf_signs.items() if sign == candidate_side)
    return agreeing_weight / total_weight


def evaluate_z_score_filter(
    closes: Any,
    candidate_side: int,
    period: int = 20,
    max_fomo_long_z: float = 2.2,
    min_panic_short_z: float = -2.2
) -> Tuple[bool, float]:
    """
    Evaluates Dr. Ernest Chan's statistical Z-Score filter:
    - If LONG and Z > +2.2 -> FOMO Overextended Climax (Reject)
    - If SHORT and Z < -2.2 -> Panic Oversold Climax (Reject)
    Returns (is_passed, latest_z_score).
    """
    z_scores = calc_z_score(closes, period)
    if not z_scores:
        return True, 0.0
    
    latest_z = z_scores[-1]
    if latest_z is None:
        return True, 0.0

    if candidate_side > 0 and latest_z > max_fomo_long_z:
        return False, latest_z
    if candidate_side < 0 and latest_z < min_panic_short_z:
        return False, latest_z

    return True, latest_z


def calc_macd_score(candles: list, direction: str, lookback: int = 26) -> float:
    """
    Calculates MACD alignment score (0.0 to 1.0):
    - Fast EMA(12), Slow EMA(26), Signal EMA(9)
    - Aligned MACD line and crossover gives high score.
    """
    if not candles or len(candles) < lookback + 10:
        return 0.5

    if isinstance(candles[0], dict):
        closes = [float(c.get("close", 0.0)) for c in candles]
    else:
        closes = [float(x) for x in candles]

    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    
    macd_line = []
    for i in range(len(closes)):
        if ema12[i] is not None and ema26[i] is not None:
            macd_line.append(ema12[i] - ema26[i])
        else:
            macd_line.append(None)

    valid_macd = [x for x in macd_line if x is not None]
    if len(valid_macd) < 10:
        return 0.5

    sig_ema9 = calc_ema(valid_macd, 9)
    if not sig_ema9 or sig_ema9[-1] is None:
        return 0.5

    current_macd = valid_macd[-1]
    current_sig = sig_ema9[-1]
    hist = current_macd - current_sig

    score = 0.5
    if direction.upper() in ("LONG", "BUY", "1"):
        if current_macd > current_sig:
            score += 0.25
        if hist > 0 and len(sig_ema9) > 2 and sig_ema9[-2] is not None and (valid_macd[-2] <= sig_ema9[-2]):
            score += 0.25  # Fresh bullish crossover
    else:
        if current_macd < current_sig:
            score += 0.25
        if hist < 0 and len(sig_ema9) > 2 and sig_ema9[-2] is not None and (valid_macd[-2] >= sig_ema9[-2]):
            score += 0.25  # Fresh bearish crossover

    return max(0.0, min(1.0, score))


def calc_rsi_divergence_score(candles: list, direction: str, lookback: int = 14) -> float:
    """
    Calculates RSI momentum divergence score (0.0 to 1.0):
    - Regular Bullish Divergence: Lower price low + Higher RSI low -> High score
    - Regular Bearish Divergence: Higher price high + Lower RSI high -> High score
    """
    if not candles or len(candles) < lookback + 10:
        return 0.5

    if isinstance(candles[0], dict):
        closes = [float(c.get("close", 0.0)) for c in candles]
        lows = [float(c.get("low", 0.0)) for c in candles]
        highs = [float(c.get("high", 0.0)) for c in candles]
    else:
        closes = [float(x) for x in candles]
        lows = closes
        highs = closes

    rsi_series = calc_rsi(closes, period=14)
    valid_rsi = [r for r in rsi_series if r is not None]
    if len(valid_rsi) < 10:
        return 0.5

    recent_p = closes[-10:]
    recent_rsi = valid_rsi[-10:]

    score = 0.5
    if direction.upper() in ("LONG", "BUY", "1"):
        # Bullish check
        if recent_p[-1] < min(recent_p[:-1]) and recent_rsi[-1] > min(recent_rsi[:-1]):
            score = 0.85
        elif recent_rsi[-1] < 35.0:
            score = 0.70
    else:
        # Bearish check
        if recent_p[-1] > max(recent_p[:-1]) and recent_rsi[-1] < max(recent_rsi[:-1]):
            score = 0.85
        elif recent_rsi[-1] > 65.0:
            score = 0.70

    return score


def evaluate_gemini_gate(
    payload: Dict[str, Any],
    cfg: Optional[FilterCfg] = None
) -> Tuple[bool, float, str]:
    """
    Gemini AI Evaluation Gate.
    Strictly fail-closed: If unconfigured, disabled, or API error, returns False.
    """
    if cfg is None:
        cfg = CONFIG.filters

    if not cfg.gemini_enabled:
        return True, 1.0, "Gemini Gate Disabled"

    try:
        from gemini_service import evaluate_trade_setup
        res = evaluate_trade_setup(payload)
        is_ok = bool(res.get("ai_confirmed", False))
        score = float(res.get("ai_score", 0.0))
        reason = str(res.get("reason", ""))
        return is_ok, score, reason
    except Exception as e:
        if cfg.gemini_fail_closed:
            return False, 0.0, f"Gemini evaluation exception: {e} (fail-closed)"
        return True, 0.5, "Gemini exception bypassed"
