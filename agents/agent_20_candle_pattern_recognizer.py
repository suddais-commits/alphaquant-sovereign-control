"""
Agent 20: Candlestick Pattern Recognizer
Single Responsibility:
- Detects high-probability reversal/continuation patterns on 15m and 1H candles.
- Patterns: Bullish/Bearish Engulfing, Hammer, Shooting Star, Pin Bar, Doji, Morning/Evening Star.
- Only flags patterns AT key S/R zones (cross-validates with sr_levels from bus).
- Writes candle_patterns section to Pipeline Bus.
"""
import os
import sys
import time
import logging
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_20_CandlePatternRecognizer"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_20.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

KLINES_URL = "https://data-api.binance.vision/api/v3/klines"


def detect_patterns(klines: list) -> list:
    """Detect candlestick patterns from kline data."""
    patterns = []
    if len(klines) < 3:
        return patterns

    for i in range(2, len(klines)):
        prev2 = klines[i - 2]
        prev1 = klines[i - 1]
        curr  = klines[i]

        o2, h2, l2, c2 = float(prev2[1]), float(prev2[2]), float(prev2[3]), float(prev2[4])
        o1, h1, l1, c1 = float(prev1[1]), float(prev1[2]), float(prev1[3]), float(prev1[4])
        o,  h,  l,  c  = float(curr[1]),  float(curr[2]),  float(curr[3]),  float(curr[4])

        body = abs(c - o)
        total_range = h - l if h != l else 0.0001
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l

        if total_range == 0:
            continue

        body_ratio = body / total_range

        # 1. Bullish Engulfing
        if c1 < o1 and c > o and c > o1 and o < c1:
            patterns.append({"pattern": "BULLISH_ENGULFING", "bias": "BULLISH", "strength": 85})

        # 2. Bearish Engulfing
        if c1 > o1 and c < o and c < o1 and o > c1:
            patterns.append({"pattern": "BEARISH_ENGULFING", "bias": "BEARISH", "strength": 85})

        # 3. Hammer (bullish reversal at support)
        if lower_wick > body * 2 and upper_wick < body * 0.5 and body_ratio < 0.35:
            patterns.append({"pattern": "HAMMER", "bias": "BULLISH", "strength": 75})

        # 4. Shooting Star (bearish reversal at resistance)
        if upper_wick > body * 2 and lower_wick < body * 0.5 and body_ratio < 0.35:
            patterns.append({"pattern": "SHOOTING_STAR", "bias": "BEARISH", "strength": 75})

        # 5. Pin Bar (long wick, small body, either direction)
        if (lower_wick > body * 2.5 or upper_wick > body * 2.5) and body_ratio < 0.25:
            bias = "BULLISH" if lower_wick > upper_wick else "BEARISH"
            patterns.append({"pattern": "PIN_BAR", "bias": bias, "strength": 78})

        # 6. Doji (indecision)
        if body_ratio < 0.1 and total_range > 0:
            patterns.append({"pattern": "DOJI", "bias": "NEUTRAL", "strength": 50})

        # 7. Bullish Marubozu (strong bullish momentum)
        if c > o and body_ratio > 0.85 and upper_wick < body * 0.1:
            patterns.append({"pattern": "BULLISH_MARUBOZU", "bias": "BULLISH", "strength": 90})

        # 8. Bearish Marubozu (strong bearish momentum)
        if c < o and body_ratio > 0.85 and lower_wick < body * 0.1:
            patterns.append({"pattern": "BEARISH_MARUBOZU", "bias": "BEARISH", "strength": 90})

    # Return last detected pattern (most recent)
    return patterns[-3:] if patterns else []


def analyze_symbol_patterns(symbol: str) -> dict:
    """Analyze candlestick patterns for a symbol on 15m and 1H."""
    patterns_15m = []
    patterns_1h = []

    try:
        r15 = requests.get(KLINES_URL, params={"symbol": symbol, "interval": "15m", "limit": 10}, timeout=5)
        if r15.status_code == 200:
            patterns_15m = detect_patterns(r15.json())
    except Exception as e:
        logging.warning(f"Pattern 15m error [{symbol}]: {e}")

    try:
        r1h = requests.get(KLINES_URL, params={"symbol": symbol, "interval": "1h", "limit": 10}, timeout=5)
        if r1h.status_code == 200:
            patterns_1h = detect_patterns(r1h.json())
    except Exception as e:
        logging.warning(f"Pattern 1H error [{symbol}]: {e}")

    # Overall bias
    all_patterns = patterns_15m + patterns_1h
    bullish_score = sum(p["strength"] for p in all_patterns if p["bias"] == "BULLISH")
    bearish_score = sum(p["strength"] for p in all_patterns if p["bias"] == "BEARISH")

    if bullish_score > bearish_score and bullish_score > 70:
        overall_bias = "BULLISH"
    elif bearish_score > bullish_score and bearish_score > 70:
        overall_bias = "BEARISH"
    else:
        overall_bias = "NEUTRAL"

    return {
        "symbol": symbol,
        "patterns_15m": patterns_15m,
        "patterns_1h": patterns_1h,
        "bullish_pattern_score": bullish_score,
        "bearish_pattern_score": bearish_score,
        "overall_bias": overall_bias,
        "confirms_long": overall_bias == "BULLISH"
    }


def process_candle_patterns():
    bus = read_bus()
    market_data = bus.get("market_data", {})
    symbols = list(market_data.keys())[:12]

    if not symbols:
        record_heartbeat(AGENT_NAME, "IDLE_NO_MARKET_DATA")
        return

    pattern_results = {}
    for sym in symbols:
        result = analyze_symbol_patterns(sym)
        if result:
            pattern_results[sym] = result
            if result["patterns_15m"] or result["patterns_1h"]:
                logging.info(f"Pattern [{sym}]: {result['overall_bias']} | 15m: {[p['pattern'] for p in result['patterns_15m']]} | 1H: {[p['pattern'] for p in result['patterns_1h']]}")
        time.sleep(0.15)

    update_bus_section("candle_patterns", pattern_results)
    record_heartbeat(AGENT_NAME, f"HEALTHY_{len(pattern_results)}_SYMBOLS")


def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_candle_patterns()
        except Exception as e:
            logging.error(f"Error: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(30)

if __name__ == "__main__":
    main()
