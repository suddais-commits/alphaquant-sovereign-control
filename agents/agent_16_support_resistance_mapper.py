"""
Agent 16: Support & Resistance Level Mapper
Single Responsibility:
- Identifies key 4H, 1H, 15m swing highs/lows as S/R zones.
- Detects where price is relative to these S/R levels.
- Flags if price is AT a key S/R (within 0.5% proximity).
- Writes sr_levels section to Pipeline Bus.

NOTE: No external HTTP requests. Candle data is read exclusively from
      pipeline_bus["market_data"] published by agent_01_market_data_feeder.
      Available timeframes: klines_15m, klines_1h, klines_4h.
"""
import os
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_16_SR_LevelMapper"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_16.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

PROXIMITY_PCT = 0.005  # 0.5% — "AT the level" threshold


def find_swing_highs_lows(candles: list) -> dict:
    """
    Find swing high/low pivot levels from a list of candle dicts.
    Candle dicts must have keys: high, low, close.
    Returns: {current_price, resistance_levels, support_levels, period_high, period_low}
    """
    if not candles or len(candles) < 5:
        return {}

    try:
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        closes = [float(c["close"]) for c in candles]

        # Pivot detection: local max/min over 5-candle window
        pivot_highs = []
        pivot_lows = []
        for i in range(2, len(highs) - 2):
            if (highs[i] > highs[i-1] and highs[i] > highs[i-2]
                    and highs[i] > highs[i+1] and highs[i] > highs[i+2]):
                pivot_highs.append(round(highs[i], 8))
            if (lows[i] < lows[i-1] and lows[i] < lows[i-2]
                    and lows[i] < lows[i+1] and lows[i] < lows[i+2]):
                pivot_lows.append(round(lows[i], 8))

        return {
            "current_price": closes[-1],
            "resistance_levels": sorted(set(pivot_highs), reverse=True)[:3],
            "support_levels": sorted(set(pivot_lows), reverse=True)[:3],
            "period_high": max(highs),
            "period_low": min(lows)
        }
    except Exception as e:
        logging.warning(f"Swing pivot error: {e}")
        return {}


def map_sr_levels(symbol: str, sym_data: dict) -> dict:
    """
    Map S/R from multiple timeframes using bus data and detect proximity.
    sym_data is the market_data[symbol] dict published by agent_01.
    """
    k4h = sym_data.get("klines_4h", [])
    k1h = sym_data.get("klines_1h", [])
    k15 = sym_data.get("klines_15m", [])

    four_h = find_swing_highs_lows(k4h)
    one_h  = find_swing_highs_lows(k1h)
    fifteen = find_swing_highs_lows(k15)

    # Need at least one valid timeframe
    primary = four_h or one_h or fifteen
    if not primary:
        return {}

    current_price = sym_data.get("current_price") or primary.get("current_price", 0)
    if not current_price:
        return {}

    # Merge resistance and support levels from all available timeframes
    all_resistance = []
    all_support = []
    for tf_data in [four_h, one_h, fifteen]:
        all_resistance.extend(tf_data.get("resistance_levels", []))
        all_support.extend(tf_data.get("support_levels", []))

    # Filter levels above and below current price
    resistances = sorted([r for r in all_resistance if r > current_price])[:4]
    supports = sorted([s for s in all_support if s < current_price], reverse=True)[:4]

    # Check proximity to nearest level
    nearest_resistance = resistances[0] if resistances else None
    nearest_support = supports[0] if supports else None

    at_resistance = False
    at_support = False
    if nearest_resistance:
        at_resistance = abs(current_price - nearest_resistance) / current_price < PROXIMITY_PCT
    if nearest_support:
        at_support = abs(current_price - nearest_support) / current_price < PROXIMITY_PCT

    zone_status = "AT_RESISTANCE" if at_resistance else ("AT_SUPPORT" if at_support else "MID_RANGE")

    return {
        "symbol": symbol,
        "current_price": current_price,
        "resistances": resistances,
        "supports": supports,
        "nearest_resistance": nearest_resistance,
        "nearest_support": nearest_support,
        "zone_status": zone_status,
        "safe_to_enter_long": not at_resistance,  # Don't buy AT resistance
    }


def process_sr_all():
    bus = read_bus()
    market_data = bus.get("market_data", {})
    symbols = list(market_data.keys())[:12]

    if not symbols:
        record_heartbeat(AGENT_NAME, "IDLE_NO_MARKET_DATA")
        return

    sr_results = {}
    for sym in symbols:
        sym_data = market_data.get(sym, {})
        result = map_sr_levels(sym, sym_data)
        if result:
            sr_results[sym] = result
            logging.info(
                f"S/R [{sym}]: {result['zone_status']} | "
                f"Near Res: {result['nearest_resistance']} | "
                f"Near Sup: {result['nearest_support']}"
            )

    update_bus_section("sr_levels", sr_results)
    record_heartbeat(AGENT_NAME, f"HEALTHY_{len(sr_results)}_SYMBOLS")


def main():
    logging.info(f"{AGENT_NAME} started (bus-only mode, no external HTTP).")
    while True:
        try:
            process_sr_all()
        except Exception as e:
            logging.error(f"Error: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(60)

if __name__ == "__main__":
    main()
