"""
Technical Indicators Calculator — pure Python stdlib, zero dependencies.

All functions take a list of float closing prices (or OHLCV dicts)
and return computed indicator values.

Indicators:
  - EMA, SMA
  - RSI (Wilder's smoothing)
  - Bollinger Bands
  - MACD
  - ATR (Average True Range)
  - Supertrend
  - Donchian Channel
  - ADX (Average Directional Index)
"""
from __future__ import annotations

import math
from typing import Optional


# ─── EMA ──────────────────────────────────────────────────────────────────────

def calc_ema(closes: list[float], period: int) -> list[Optional[float]]:
    """Exponential Moving Average. First (period-1) values are None."""
    result: list[Optional[float]] = [None] * len(closes)
    if len(closes) < period:
        return result
    k = 2 / (period + 1)
    # seed with SMA
    sma = sum(closes[:period]) / period
    result[period - 1] = sma
    for i in range(period, len(closes)):
        result[i] = closes[i] * k + result[i - 1] * (1 - k)
    return result


# ─── SMA ──────────────────────────────────────────────────────────────────────

def calc_sma(closes: list[float], period: int) -> list[Optional[float]]:
    """Simple Moving Average."""
    result: list[Optional[float]] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        result[i] = sum(closes[i - period + 1 : i + 1]) / period
    return result


# ─── RSI ──────────────────────────────────────────────────────────────────────

def calc_rsi(closes: list[float], period: int = 14) -> list[Optional[float]]:
    """
    Relative Strength Index (Wilder's smoothing).
    First (period) values are None.
    """
    result: list[Optional[float]] = [None] * len(closes)
    if len(closes) < period + 1:
        return result

    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100 - (100 / (1 + rs))

    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0)
        loss = max(-diff, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100 - (100 / (1 + rs))

    return result


# ─── Bollinger Bands ──────────────────────────────────────────────────────────

def calc_bollinger(
    closes: list[float], period: int = 20, std_mult: float = 2.0
) -> dict[str, list[Optional[float]]]:
    """
    Bollinger Bands.
    Returns dict with 'upper', 'middle' (SMA), 'lower' lists.
    """
    middle = calc_sma(closes, period)
    upper: list[Optional[float]] = [None] * len(closes)
    lower: list[Optional[float]] = [None] * len(closes)

    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        mean = middle[i]
        variance = sum((x - mean) ** 2 for x in window) / period
        std = math.sqrt(variance)
        upper[i] = mean + std_mult * std
        lower[i] = mean - std_mult * std

    return {"upper": upper, "middle": middle, "lower": lower}


# ─── MACD ─────────────────────────────────────────────────────────────────────

def calc_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, list[Optional[float]]]:
    """
    MACD = EMA(fast) - EMA(slow).
    Signal = EMA(MACD, signal_period).
    Histogram = MACD - Signal.
    """
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)

    n = len(closes)
    macd_line: list[Optional[float]] = [None] * n
    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]

    # Signal line = EMA of MACD line (only over non-None values)
    signal_line: list[Optional[float]] = [None] * n
    histogram: list[Optional[float]] = [None] * n

    # Find first valid macd index
    macd_values = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    if len(macd_values) >= signal:
        # Compute EMA of macd values
        start_idx = macd_values[0][0]
        macd_only = [v for _, v in macd_values]
        sig_ema = calc_ema(macd_only, signal)
        for j, (orig_i, _) in enumerate(macd_values):
            if sig_ema[j] is not None:
                signal_line[orig_i] = sig_ema[j]
                histogram[orig_i] = macd_line[orig_i] - sig_ema[j]

    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


# ─── ATR (Average True Range) ─────────────────────────────────────────────────

def calc_atr(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> list[Optional[float]]:
    """
    Average True Range — measures market volatility.
    True Range = max(H-L, |H-prevC|, |L-prevC|)
    ATR = Wilder's smoothed average of TR.
    """
    n = len(closes)
    result: list[Optional[float]] = [None] * n
    if n < period + 1:
        return result

    trs = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    # Seed with simple average
    atr = sum(trs[:period]) / period
    result[period] = atr
    for i in range(period + 1, n):
        atr = (atr * (period - 1) + trs[i - 1]) / period
        result[i] = atr

    return result


# ─── Supertrend ───────────────────────────────────────────────────────────────

def calc_supertrend(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    atr_period: int = 10,
    multiplier: float = 3.0,
) -> dict[str, list]:
    """
    Supertrend indicator.
    Returns dict with:
      'direction': 1 (bullish) or -1 (bearish) per candle (None before warmup)
      'upper': upper band values
      'lower': lower band values
    """
    n = len(closes)
    atr = calc_atr(highs, lows, closes, atr_period)

    direction: list[Optional[int]] = [None] * n
    upper: list[Optional[float]] = [None] * n
    lower: list[Optional[float]] = [None] * n

    # prev values for smoothing
    prev_upper = None
    prev_lower = None
    prev_dir   = None

    for i in range(1, n):
        if atr[i] is None:
            continue

        hl2  = (highs[i] + lows[i]) / 2.0
        u    = hl2 + multiplier * atr[i]
        l    = hl2 - multiplier * atr[i]

        # Adjust bands to avoid widening
        if prev_upper is not None:
            u = min(u, prev_upper) if closes[i - 1] < prev_upper else u
            l = max(l, prev_lower) if closes[i - 1] > prev_lower else l

        upper[i] = u
        lower[i] = l

        # Determine direction
        if prev_dir is None:
            direction[i] = 1 if closes[i] > u else -1
        elif prev_dir == 1:
            direction[i] = 1 if closes[i] >= l else -1
        else:
            direction[i] = -1 if closes[i] <= u else 1

        prev_upper = u
        prev_lower = l
        prev_dir   = direction[i]

    return {"direction": direction, "upper": upper, "lower": lower}


# ─── Donchian Channel ─────────────────────────────────────────────────────────

def calc_donchian(
    highs: list[float], lows: list[float], period: int = 20
) -> dict[str, list[Optional[float]]]:
    """
    Donchian Channel.
    Returns dict with 'upper' (highest high), 'lower' (lowest low), 'middle'.
    """
    n = len(highs)
    upper: list[Optional[float]] = [None] * n
    lower: list[Optional[float]] = [None] * n
    middle: list[Optional[float]] = [None] * n

    for i in range(period - 1, n):
        u = max(highs[i - period + 1 : i + 1])
        l = min(lows[i - period + 1 : i + 1])
        upper[i]  = u
        lower[i]  = l
        middle[i] = (u + l) / 2

    return {"upper": upper, "lower": lower, "middle": middle}


# ─── Dr. Ernest Chan: Quantitative Z-Score (Mean Reversion & Climax Filter) ───

def calc_z_score(closes: Any, period: int = 20) -> list[Optional[float]]:
    """
    Computes mathematical Z-Score of price relative to its moving average:
    Z = (Price - Mean) / Standard_Deviation
    - Z > +2.2: Extreme Overextended Climax (Do not FOMO Long per Chan / Bulkowski)
    - Z < -2.2: Extreme Oversold Climax (Do not Panic Short)
    - -1.5 <= Z <= +1.5: Healthy Trend Extension Zone
    """
    if closes is None:
        return []
    
    clean_closes: list[float] = []
    if hasattr(closes, "tolist"):
        clean_closes = [float(x) for x in closes.tolist() if x is not None and not (isinstance(x, float) and math.isnan(x))]
    elif isinstance(closes, list):
        if len(closes) > 0 and isinstance(closes[0], dict):
            clean_closes = [float(c.get("close", 0.0)) for c in closes if c.get("close") is not None]
        else:
            clean_closes = [float(x) for x in closes if x is not None and not (isinstance(x, float) and math.isnan(x))]
    else:
        try:
            clean_closes = [float(x) for x in list(closes)]
        except Exception:
            return []

    n = len(clean_closes)
    result: list[Optional[float]] = [None] * n
    if n < period:
        return result

    for i in range(period - 1, n):
        window = clean_closes[i - period + 1 : i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        std = math.sqrt(variance)
        if std > 1e-9:
            result[i] = (clean_closes[i] - mean) / std
        else:
            result[i] = 0.0
    return result


# ─── Robert Carver: Systematic Volatility Scalar ──────────────────────────────

def calc_carver_volatility_scalar(
    current_price: Any,
    atr_value: Any = None,
    baseline_vol_pct: float = 0.02,
    target_vol: float = 0.20
) -> float:
    """
    Calculates Robert Carver's dynamic volatility position scaling factor:
    Scalar = Baseline_Volatility / Asset_Current_Volatility
    - When ATR/Volatility is high, Scalar scales down (e.g., 0.6x - 0.8x) to protect capital.
    - When ATR/Volatility is calm, Scalar scales up to 1.0x (capped at 1.25x).
    """
    if isinstance(current_price, (list, tuple)):
        candles = current_price
        if not candles:
            return 1.0
        if isinstance(candles[-1], dict):
            price = float(candles[-1].get("close", 0.0))
            highs = [float(c.get("high", 0.0)) for c in candles]
            lows = [float(c.get("low", 0.0)) for c in candles]
            closes = [float(c.get("close", 0.0)) for c in candles]
            atr_list = calc_atr(highs, lows, closes, 14)
            atr = atr_list[-1] if atr_list and atr_list[-1] is not None else 0.0
        else:
            price = float(candles[-1])
            atr = 0.0
        current_price = price
        atr_value = atr

    try:
        cp = float(current_price)
        av = float(atr_value) if atr_value is not None else 0.0
        if cp <= 0 or av <= 0:
            return 1.0
        current_vol_pct = av / cp
        if current_vol_pct <= 0:
            return 1.0
        scalar = baseline_vol_pct / max(current_vol_pct, 0.005)
        return max(0.50, min(1.25, round(scalar, 2)))
    except Exception:
        return 1.0


# ─── Trader Dale & Forthmann: Volume Profile & Value Area (POC, VAH, VAL) ────

def calc_volume_profile(
    klines: list[dict],
    bins: int = 24
) -> dict:
    """
    Computes Session/Range Volume Profile, Point of Control (POC),
    Value Area High (VAH), and Value Area Low (VAL) covering 70% of total volume.
    Also identifies High Volume Nodes (HVN) and Low Volume Nodes (LVN).
    """
    if not klines or len(klines) < 5:
        return {
            "poc": 0.0,
            "vah": 0.0,
            "val": 0.0,
            "total_volume": 0.0,
            "hvn": [],
            "lvn": [],
            "status": "INSUFFICIENT_DATA"
        }

    highs = [float(k.get("high", k.get("h", 0.0))) for k in klines]
    lows = [float(k.get("low", k.get("l", 0.0))) for k in klines]
    volumes = [float(k.get("volume", k.get("v", 0.0))) for k in klines]
    closes = [float(k.get("close", k.get("c", 0.0))) for k in klines]

    min_p = min(lows)
    max_p = max(highs)

    if max_p <= min_p:
        return {
            "poc": closes[-1],
            "vah": max_p,
            "val": min_p,
            "total_volume": sum(volumes),
            "hvn": [closes[-1]],
            "lvn": [],
            "status": "FLAT_RANGE"
        }

    bin_size = (max_p - min_p) / bins
    bin_volumes = [0.0] * bins
    bin_centers = [min_p + (i + 0.5) * bin_size for i in range(bins)]

    # Distribute volume across candle price range
    for k, vol in zip(klines, volumes):
        kh = float(k.get("high", k.get("h", 0.0)))
        kl = float(k.get("low", k.get("l", 0.0)))
        span = max(kh - kl, 1e-9)
        for i in range(bins):
            b_low = min_p + i * bin_size
            b_high = b_low + bin_size
            # Overlap between candle [kl, kh] and bin [b_low, b_high]
            overlap = max(0.0, min(kh, b_high) - max(kl, b_low))
            if overlap > 0:
                bin_volumes[i] += vol * (overlap / span)

    total_vol = sum(bin_volumes)
    if total_vol <= 0:
        return {
            "poc": closes[-1],
            "vah": max_p,
            "val": min_p,
            "total_volume": 0.0,
            "hvn": [],
            "lvn": [],
            "status": "NO_VOLUME"
        }

    # Point of Control (POC) = bin with max volume
    max_bin_idx = max(range(bins), key=lambda i: bin_volumes[i])
    poc = bin_centers[max_bin_idx]

    # Value Area = expand outward from POC until 70% of total volume is captured
    target_va_vol = total_vol * 0.70
    accum_vol = bin_volumes[max_bin_idx]
    lower_idx = max_bin_idx
    upper_idx = max_bin_idx

    while accum_vol < target_va_vol and (lower_idx > 0 or upper_idx < bins - 1):
        vol_below = bin_volumes[lower_idx - 1] if lower_idx > 0 else -1.0
        vol_above = bin_volumes[upper_idx + 1] if upper_idx < bins - 1 else -1.0
        if vol_above >= vol_below and upper_idx < bins - 1:
            upper_idx += 1
            accum_vol += bin_volumes[upper_idx]
        elif lower_idx > 0:
            lower_idx -= 1
            accum_vol += bin_volumes[lower_idx]
        else:
            break

    vah = bin_centers[upper_idx] + bin_size * 0.5
    val = bin_centers[lower_idx] - bin_size * 0.5

    # High Volume Nodes (HVN) & Low Volume Nodes (LVN)
    avg_bin_vol = total_vol / bins
    hvn = [round(bin_centers[i], 5) for i in range(bins) if bin_volumes[i] >= avg_bin_vol * 1.5]
    lvn = [round(bin_centers[i], 5) for i in range(bins) if bin_volumes[i] <= avg_bin_vol * 0.4]

    return {
        "poc": round(poc, 5),
        "vah": round(vah, 5),
        "val": round(val, 5),
        "total_volume": round(total_vol, 2),
        "hvn": hvn[:5],
        "lvn": lvn[:5],
        "current_position_relative_to_poc": "ABOVE_POC" if closes[-1] > poc else "BELOW_POC",
        "inside_value_area": (val <= closes[-1] <= vah),
        "status": "SUCCESS"
    }


# ─── Dr. Alexander Elder: Elder-Ray Bull Power & Bear Power (13 EMA) ──────────

def calc_elder_ray(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 13
) -> dict[str, list[Optional[float]]]:
    """
    Dr. Alexander Elder's Elder-ray Indicator:
    - 13 EMA represents the consensus value of the market.
    - Bull Power = High - 13 EMA (Buyers' strength to push above consensus).
    - Bear Power = Low - 13 EMA (Sellers' strength to push below consensus).
    - Detects Bullish Divergences (Price lower low + Bear Power higher low = Buy trigger).
    """
    n = len(closes)
    ema13 = calc_ema(closes, period)
    bull_power: list[Optional[float]] = [None] * n
    bear_power: list[Optional[float]] = [None] * n

    for i in range(n):
        if ema13[i] is not None:
            bull_power[i] = round(highs[i] - ema13[i], 5)
            bear_power[i] = round(lows[i] - ema13[i], 5)

    # Detect divergences over last 15 bars
    bullish_divergence = False
    bearish_divergence = False

    if n >= 15 and bear_power[-1] is not None and bear_power[-5] is not None:
        # Price made lower low but Bear Power made higher low
        if closes[-1] < min(closes[-15:-5]) and bear_power[-1] > bear_power[-5] and bear_power[-1] < 0:
            bullish_divergence = True
        # Price made higher high but Bull Power made lower high
        if closes[-1] > max(closes[-15:-5]) and bull_power[-1] < bull_power[-5] and bull_power[-1] > 0:
            bearish_divergence = True

    return {
        "bull_power": bull_power,
        "bear_power": bear_power,
        "latest_bull_power": bull_power[-1] if n > 0 else 0.0,
        "latest_bear_power": bear_power[-1] if n > 0 else 0.0,
        "bullish_divergence": bullish_divergence,
        "bearish_divergence": bearish_divergence
    }


# ─── Mark B. Fisher: The Logical Trader (ACD Rolling Pivot Range) ────────────

def calc_acd_pivot_range(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    lookback: int = 24
) -> dict:
    """
    Mark B. Fisher's ACD Rolling Pivot Range:
    - Pivot = (High + Low + Close) / 3
    - Differential D = High - Low
    - Pivot Range = [Pivot - D/2, Pivot + D/2]
    - Acts as dynamic institutional equilibrium zone.
    """
    if not closes or len(closes) < 3:
        p = closes[-1] if closes else 0.0
        return {"pivot": p, "pivot_high": p, "pivot_low": p, "differential": 0.0, "bias": "NEUTRAL"}

    sub_h = highs[-lookback:]
    sub_l = lows[-lookback:]
    sub_c = closes[-lookback:]

    h = max(sub_h)
    l = min(sub_l)
    c = sub_c[-1]

    pivot = (h + l + c) / 3.0
    differential = (h - l) * 0.25  # 25% rolling width buffer
    pivot_high = pivot + differential
    pivot_low = pivot - differential

    curr = closes[-1]
    if curr > pivot_high:
        bias = "ABOVE_PIVOT_BULLISH"
    elif curr < pivot_low:
        bias = "BELOW_PIVOT_BEARISH"
    else:
        bias = "INSIDE_PIVOT_CHOP"

    return {
        "pivot": round(pivot, 5),
        "pivot_high": round(pivot_high, 5),
        "pivot_low": round(pivot_low, 5),
        "differential": round(differential * 2, 5),
        "bias": bias,
        "current_price": curr
    }


# ─── Myles Wilson Walker: Elliott Wave C-Wave & Fibonacci Calculator ─────────

def calc_fibonacci_c_wave(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    direction: str = "LONG",
    lookback: int = 30
) -> dict:
    """
    Myles Wilson Walker C-Wave Fibonacci Engine:
    - Wave A: Initial impulse wave.
    - Wave B: Corrective pullback (38.2% - 61.8% Golden Pocket).
    - Wave C: High velocity impulse expansion (1.0x - 1.618x Wave A).
    """
    if len(closes) < 15:
        cp = closes[-1] if closes else 0.0
        return {
            "in_golden_pocket": False,
            "wave_a_origin": cp,
            "wave_a_peak": cp,
            "fib_382": cp,
            "fib_500": cp,
            "fib_618": cp,
            "c_wave_target_100": cp,
            "c_wave_target_1618": cp
        }

    sub_h = highs[-lookback:]
    sub_l = lows[-lookback:]
    curr_p = closes[-1]

    if direction.upper() == "LONG":
        origin = min(sub_l[:len(sub_l)//2])
        peak = max(sub_h[len(sub_h)//2:])
        wave_height = max(peak - origin, 1e-9)

        fib_382 = peak - (wave_height * 0.382)
        fib_500 = peak - (wave_height * 0.500)
        fib_618 = peak - (wave_height * 0.618)
        in_golden_pocket = (fib_618 <= curr_p <= fib_382)

        # C-Wave expansion from current retrace
        target_100 = curr_p + wave_height
        target_1618 = curr_p + (wave_height * 1.618)

        return {
            "in_golden_pocket": in_golden_pocket,
            "wave_a_origin": round(origin, 5),
            "wave_a_peak": round(peak, 5),
            "fib_382": round(fib_382, 5),
            "fib_500": round(fib_500, 5),
            "fib_618": round(fib_618, 5),
            "c_wave_target_100": round(target_100, 5),
            "c_wave_target_1618": round(target_1618, 5)
        }
    else: # SHORT
        origin = max(sub_h[:len(sub_h)//2])
        trough = min(sub_l[len(sub_l)//2:])
        wave_height = max(origin - trough, 1e-9)

        fib_382 = trough + (wave_height * 0.382)
        fib_500 = trough + (wave_height * 0.500)
        fib_618 = trough + (wave_height * 0.618)
        in_golden_pocket = (fib_382 <= curr_p <= fib_618)

        target_100 = curr_p - wave_height
        target_1618 = curr_p - (wave_height * 1.618)

        return {
            "in_golden_pocket": in_golden_pocket,
            "wave_a_origin": round(origin, 5),
            "wave_a_trough": round(trough, 5),
            "fib_382": round(fib_382, 5),
            "fib_500": round(fib_500, 5),
            "fib_618": round(fib_618, 5),
            "c_wave_target_100": round(target_100, 5),
            "c_wave_target_1618": round(target_1618, 5)
        }


# ─── Dixit Vekariya: SMC Inducement (IDM) & Mitigation Detector ──────────────

def detect_smc_inducement(
    klines: list[dict],
    direction: str = "LONG"
) -> dict:
    """
    Dixit Vekariya Smart Money Concept Inducement (IDM) Detector:
    - Identifies intermediate Inducement level (first internal pullback).
    - Checks whether Inducement was swept by price to validate high-conviction Order Block.
    """
    if len(klines) < 12:
        return {"has_inducement": False, "idm_swept": False, "idm_level": 0.0}

    lows = [float(k.get("low", k.get("l", 0.0))) for k in klines]
    highs = [float(k.get("high", k.get("h", 0.0))) for k in klines]
    closes = [float(k.get("close", k.get("c", 0.0))) for k in klines]

    if direction.upper() == "LONG":
        # Internal low formed before the recent high
        idm_level = min(lows[-8:-3])
        recent_min_low = min(lows[-3:])
        idm_swept = (recent_min_low < idm_level) and (closes[-1] > idm_level)
        return {
            "has_inducement": True,
            "idm_level": round(idm_level, 5),
            "idm_swept": idm_swept,
            "action": "INDUMENT_SWEPT_VALID_OB" if idm_swept else "AWAIT_IDM_SWEEP"
        }
    else: # SHORT
        idm_level = max(highs[-8:-3])
        recent_max_high = max(highs[-3:])
        idm_swept = (recent_max_high > idm_level) and (closes[-1] < idm_level)
        return {
            "has_inducement": True,
            "idm_level": round(idm_level, 5),
            "idm_swept": idm_swept,
            "action": "INDUMENT_SWEPT_VALID_OB" if idm_swept else "AWAIT_IDM_SWEEP"
        }


# ─── Average True Range (ATR) ──────────────────────────────────────────────────

def calc_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[Optional[float]]:
    n = len(closes)
    result: list[Optional[float]] = [None] * n
    if n < period + 1:
        return result
    tr_list = [highs[0] - lows[0]]
    for i in range(1, n):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
    atr = sum(tr_list[:period]) / period
    result[period - 1] = atr
    for i in range(period, n):
        atr = (atr * (period - 1) + tr_list[i]) / period
        result[i] = atr
    return result


# ─── Average Directional Index (ADX) ──────────────────────────────────────────

def calc_adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[Optional[float]]:
    n = len(closes)
    result: list[Optional[float]] = [None] * n
    if n < 2 * period:
        return result
    
    tr_list = []
    dm_plus_list = []
    dm_minus_list = []
    
    for i in range(1, n):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
        
        tr_list.append(tr)
        dm_plus_list.append(plus_dm)
        dm_minus_list.append(minus_dm)
        
    if len(tr_list) < period:
        return result
        
    smoothed_tr = sum(tr_list[:period])
    smoothed_plus_dm = sum(dm_plus_list[:period])
    smoothed_minus_dm = sum(dm_minus_list[:period])
    
    dx_list = []
    for i in range(period, len(tr_list)):
        smoothed_tr = smoothed_tr - (smoothed_tr / period) + tr_list[i]
        smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm / period) + dm_plus_list[i]
        smoothed_minus_dm = smoothed_minus_dm - (smoothed_minus_dm / period) + dm_minus_list[i]
        
        di_plus = (smoothed_plus_dm / smoothed_tr * 100) if smoothed_tr > 1e-9 else 0.0
        di_minus = (smoothed_minus_dm / smoothed_tr * 100) if smoothed_tr > 1e-9 else 0.0
        
        di_sum = di_plus + di_minus
        dx = (abs(di_plus - di_minus) / di_sum * 100) if di_sum > 1e-9 else 0.0
        dx_list.append(dx)
        
    if len(dx_list) >= period:
        adx = sum(dx_list[:period]) / period
        start_idx = 2 * period
        if start_idx < n:
            result[start_idx] = adx
            idx = start_idx + 1
            for j in range(period, len(dx_list)):
                if idx < n:
                    adx = (adx * (period - 1) + dx_list[j]) / period
                    result[idx] = adx
                    idx += 1
    return result


# ─── Claude 3-Tier Adaptive Market Regime Detector ────────────────────────────

def detect_market_regime(highs: list[float], lows: list[float], closes: list[float]) -> dict:
    """
    Claude 3-Tier Adaptive Market Regime Detector:
    - CHOP_SHIELD (ADX < 20): Tight stops, half size, preserved capital
    - NORMAL (ADX 20-35): Standard 100% position, swing targets
    - BREAKOUT (ADX > 35): Explosive expansion, 1.15x position, extended runners
    """
    if len(closes) < 30:
        return {"regime": "NORMAL", "adx": 25.0, "min_score": 55.0, "pos_multiplier": 1.0, "tp_scale": 1.0, "min_rrr": 1.5, "max_daily_signals": 5}
        
    adx_series = calc_adx(highs, lows, closes, 14)
    valid_adx = [x for x in adx_series if x is not None]
    last_adx = valid_adx[-1] if valid_adx else 25.0
    
    if last_adx < 20.0:
        return {
            "regime": "CHOP_SHIELD",
            "adx": round(last_adx, 1),
            "min_score": 42.0,
            "pos_multiplier": 0.5,
            "tp_scale": 0.8,
            "min_rrr": 2.0,
            "max_daily_signals": 2
        }
    elif last_adx > 35.0:
        return {
            "regime": "BREAKOUT",
            "adx": round(last_adx, 1),
            "min_score": 48.0,
            "pos_multiplier": 1.15,
            "tp_scale": 1.25,
            "min_rrr": 1.8,
            "max_daily_signals": 8
        }
    else:
        return {
            "regime": "NORMAL",
            "adx": round(last_adx, 1),
            "min_score": 55.0,
            "pos_multiplier": 1.0,
            "tp_scale": 1.0,
            "min_rrr": 1.8,
            "max_daily_signals": 5
        }



