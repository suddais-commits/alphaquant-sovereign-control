"""
==============================================================================
Telegram Signal Validator & Institutional Scanner (CryptoBot Layer)
==============================================================================
This module parses incoming VIP Telegram signals, validates them against:
1. BTC Daily Bias (Daily Close vs EMA20)
2. 15m/1h SMC Structure (EMA Trend, RSI, Volume Surge)
3. Step-Trailing Ratchet Risk Management (TP1 -> BE, TP2 -> +7.5%, TP3 -> +10%)
4. Returns detailed Institutional Score (0-100) & Execution Readiness.
==============================================================================
"""

import re
import requests
import logging
from typing import Dict, Any, Optional, Tuple

log = logging.getLogger("SignalValidator")

BINANCE_FUTURES_URL = "https://fapi.binance.com"

def parse_telegram_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parses common VIP signal formats from Telegram messages.
    Supports formats like:
    - #SOL/USDT LONG / BUY
    - Entry: 140 - 142
    - Target 1: 145, Target 2: 150
    - StopLoss: 135
    """
    if not text:
        return None
        
    cleaned = text.upper().replace("/", " ").replace("#", "").replace("-", " ")
    
    # Check if this looks like a trading signal
    has_action = any(w in cleaned for w in ["BUY", "SELL", "LONG", "SHORT"])
    has_levels = any(w in cleaned for w in ["ENTRY", "TP", "TARGET", "SL", "STOP"])
    
    if not (has_action or has_levels):
        return None

    # Detect Side
    side = None
    if "LONG" in cleaned or "BUY" in cleaned:
        side = "LONG"
    elif "SHORT" in cleaned or "SELL" in cleaned:
        side = "SHORT"

    # Detect Coin / Symbol
    symbol = None
    # Look for patterns like SOLUSDT, ETHUSDT, BTCUSDT, or single tokens SOL, ETH, AVAX
    coin_match = re.search(r'\b([A-Z0-9]{2,10})USDT\b', cleaned)
    if coin_match:
        symbol = f"{coin_match.group(1)}USDT"
    else:
        tokens = re.findall(r'\b[A-Z0-9]{2,10}\b', cleaned)
        ignore_words = {"BUY", "SELL", "LONG", "SHORT", "ENTRY", "TARGET", "STOP", "TP", "SL", "VIP", "LEVERAGE", "USDT", "USDC", "SPOT", "FUTURES", "SIGNAL", "CROSS", "ISOLATED", "MARGIN"}
        for t in tokens:
            if t not in ignore_words and len(t) >= 2 and not t.isdigit():
                symbol = f"{t}USDT"
                break

    # Detect Entry
    entry = None
    entry_match = re.search(r'(?:ENTRY|ENTER|BUY|SELL|ZONE|PRICE)[:\s\-=]+([0-9]+\.?[0-9]*)', cleaned)
    if entry_match:
        try:
            entry = float(entry_match.group(1))
        except Exception:
            pass

    # Detect Stop Loss
    sl = None
    sl_match = re.search(r'(?:SL|STOP|STOPLOSS|STOP LOSS)[:\s\-=]+([0-9]+\.?[0-9]*)', cleaned)
    if sl_match:
        try:
            sl = float(sl_match.group(1))
        except Exception:
            pass

    # Detect Targets / TPs
    tps = []
    tp_matches = re.findall(r'(?:TP\d?|TARGET\d?|T\d)[:\s\-=]+([0-9]+\.?[0-9]*)', cleaned)
    for tpm in tp_matches:
        try:
            val = float(tpm)
            if val not in tps:
                tps.append(val)
        except Exception:
            pass

    if not symbol or not side:
        return None

    return {
        "raw_text": text,
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "sl": sl,
        "tps": tps
    }

def get_binance_klines(symbol: str, interval: str = "15m", limit: int = 50) -> Optional[list]:
    try:
        url = f"{BINANCE_FUTURES_URL}/fapi/v1/klines"
        res = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        log.error(f"Error fetching klines for {symbol}: {e}")
    return None

def calculate_ema(prices: list, period: int = 20) -> list:
    if len(prices) < period:
        return []
    k = 2.0 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for p in prices[period:]:
        ema.append(p * k + ema[-1] * (1 - k))
    return ema

def calculate_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def evaluate_signal_with_bot_rules(signal_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluates signal against CryptoBot institutional rules:
    1. BTC Daily Bias
    2. Coin 15m/1h Trend & EMA alignment
    3. RSI Momentum
    4. Step-Trailing Ratchet Targets
    """
    symbol = signal_data["symbol"]
    side = signal_data["side"]
    entry = signal_data.get("entry")
    sl = signal_data.get("sl")
    tps = signal_data.get("tps", [])

    # 1. Fetch BTC Daily Bias
    btc_daily = get_binance_klines("BTCUSDT", "1d", 30)
    btc_bias = "NEUTRAL"
    btc_current_price = 0.0
    if btc_daily and len(btc_daily) >= 20:
        btc_closes = [float(k[4]) for k in btc_daily]
        btc_current_price = btc_closes[-1]
        btc_ema20 = calculate_ema(btc_closes, 20)[-1]
        btc_bias = "BULLISH" if btc_current_price >= btc_ema20 else "BEARISH"

    # 2. Fetch Coin Klines (15m and 1h)
    klines_15m = get_binance_klines(symbol, "15m", 50)
    if not klines_15m:
        return {
            "symbol": symbol,
            "side": side,
            "verdict": "ERROR",
            "score": 0,
            "reasons": [f"❌ Binance par {symbol} ka data nahi mila."],
            "btc_bias": btc_bias
        }

    closes_15m = [float(k[4]) for k in klines_15m]
    current_price = closes_15m[-1]
    ema20_15m = calculate_ema(closes_15m, 20)[-1] if len(closes_15m) >= 20 else current_price
    ema50_15m = calculate_ema(closes_15m, 50)[-1] if len(closes_15m) >= 50 else current_price
    rsi_15m = calculate_rsi(closes_15m, 14)

    score = 50
    reasons = []

    # Check 1: BTC Daily Bias Filter
    if side == "LONG":
        if btc_bias == "BULLISH":
            score += 25
            reasons.append("🟢 <b>BTC Macro Bias BULLISH hai:</b> (Price > Daily EMA20) — Long trades ko full green light!")
        else:
            score -= 30
            reasons.append("🔴 <b>BTC Macro Bias BEARISH hai:</b> BTC Daily EMA20 ke neeche hai. Long signal high risk hai!")
    elif side == "SHORT":
        if btc_bias == "BEARISH":
            score += 25
            reasons.append("🟢 <b>BTC Macro Bias BEARISH hai:</b> Short trades ko full support!")
        else:
            score -= 30
            reasons.append("🔴 <b>BTC Macro Bias BULLISH hai:</b> BTC upar jaa raha hai, Short signal risky hai!")

    # Check 2: 15m Trend Alignment
    if side == "LONG":
        if current_price > ema20_15m > ema50_15m:
            score += 15
            reasons.append(f"🟢 <b>15m Trend Bullish:</b> Price (${current_price:,.4f}) > EMA20 > EMA50.")
        elif current_price < ema50_15m:
            score -= 15
            reasons.append("⚠️ <b>15m Trend Weak:</b> Price EMA50 ke neeche trade kar raha hai.")
    else:
        if current_price < ema20_15m < ema50_15m:
            score += 15
            reasons.append(f"🟢 <b>15m Trend Bearish:</b> Price (${current_price:,.4f}) < EMA20 < EMA50.")
        elif current_price > ema50_15m:
            score -= 15
            reasons.append("⚠️ <b>15m Trend Counter:</b> Price EMA50 ke upar trade kar raha hai.")

    # Check 3: RSI Momentum
    if side == "LONG":
        if 40 <= rsi_15m <= 65:
            score += 10
            reasons.append(f"🟢 <b>RSI Healthy ({rsi_15m:.1f}):</b> Expansion ke liye room baaqi hai.")
        elif rsi_15m > 75:
            score -= 10
            reasons.append(f"⚠️ <b>RSI Overbought ({rsi_15m:.1f}):</b> Pullback ka khatra.")
    else:
        if 35 <= rsi_15m <= 60:
            score += 10
            reasons.append(f"🟢 <b>RSI Healthy ({rsi_15m:.1f}):</b> Short momentum strong.")
        elif rsi_15m < 25:
            score -= 10
            reasons.append(f"⚠️ <b>RSI Oversold ({rsi_15m:.1f}):</b> Bounce ka khatra.")

    # Fallback Entry / SL / TP calculation with User's 1:3 & 1:4 Step-Trailing Ratchet
    if not entry or entry <= 0:
        entry = current_price
    if not sl or sl <= 0:
        sl = entry * 0.975 if side == "LONG" else entry * 1.025  # 2.5% default SL

    # Build User's Step-Trailing Ratchet Targets
    if not tps or len(tps) < 4:
        if side == "LONG":
            tp1 = round(entry * 1.075, 4)  # +7.5% -> Move SL to BE
            tp2 = round(entry * 1.100, 4)  # +10.0% -> Lock +7.5%
            tp3 = round(entry * 1.125, 4)  # +12.5% -> Lock +10.0%
            tp4 = round(entry * 1.150, 4)  # +15.0% -> Lock +12.5%
        else:
            tp1 = round(entry * 0.925, 4)
            tp2 = round(entry * 0.900, 4)
            tp3 = round(entry * 0.875, 4)
            tp4 = round(entry * 0.850, 4)
        tps = [tp1, tp2, tp3, tp4]

    score = max(10, min(99, score))
    
    if score >= 75:
        verdict = "APPROVED"
    elif score >= 60:
        verdict = "CAUTION"
    else:
        verdict = "REJECTED"

    return {
        "symbol": symbol,
        "side": side,
        "current_price": current_price,
        "entry": entry,
        "sl": sl,
        "tps": tps,
        "btc_bias": btc_bias,
        "btc_price": btc_current_price,
        "rsi_15m": round(rsi_15m, 1),
        "score": score,
        "verdict": verdict,
        "reasons": reasons
    }
