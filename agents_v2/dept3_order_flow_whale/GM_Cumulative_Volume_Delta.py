"""
Agent 15: CVD & Order Flow Delta Analyzer
Single Responsibility:
- Calculates Cumulative Volume Delta (CVD) per symbol using candles from pipeline_bus.
- Delta = Taker Buy Volume - Taker Sell Volume (or full volume if taker_buy unavailable).
- Positive CVD divergence vs price = institutional accumulation.
- Negative CVD divergence vs price = institutional distribution.
- Writes cvd_order_flow section to Pipeline Bus.

NOTE: No external HTTP requests. Candles are read from pipeline_bus["market_data"]
      published by agent_01_market_data_feeder.
"""
import os
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_15_CVD_OrderFlow"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_15.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

CANDLE_LIMIT = 20  # Number of recent candles to use for CVD


def calculate_cvd_from_candles(symbol: str, candles: list) -> dict:
    """
    Calculate CVD using candle data from the pipeline bus.
    Uses taker_buy_base if available (set by agent_01 from Binance klines field [9]),
    otherwise falls back to volume-weighted approximation by candle direction.
    """
    if not candles or len(candles) < 3:
        return {}

    try:
        recent = candles[-CANDLE_LIMIT:]  # Most recent candles only
        buy_vol = 0.0
        sell_vol = 0.0
        cvd_series = []
        running_cvd = 0.0

        for k in recent:
            volume = float(k.get("volume", 0.0))
            open_p = float(k.get("open", 0.0))
            close_p = float(k.get("close", 0.0))

            # Prefer actual taker_buy_base from Binance klines (index 9)
            taker_buy_base = k.get("taker_buy_base")
            if taker_buy_base is not None:
                taker_buy_base = float(taker_buy_base)
                taker_sell_base = volume - taker_buy_base
            else:
                # Approximate: bullish candle = all volume is buy, bearish = sell
                if close_p >= open_p:
                    taker_buy_base = volume
                    taker_sell_base = 0.0
                else:
                    taker_buy_base = 0.0
                    taker_sell_base = volume

            delta = taker_buy_base - taker_sell_base
            running_cvd += delta
            cvd_series.append(round(running_cvd, 4))
            buy_vol += taker_buy_base
            sell_vol += taker_sell_base

        # Signal classification based on price vs CVD direction
        last_price = float(recent[-1].get("close", 0.0))
        first_price = float(recent[0].get("close", 0.0))
        price_rising = last_price > first_price
        cvd_rising = cvd_series[-1] > cvd_series[0]

        if price_rising and cvd_rising:
            signal = "CONFIRMED_BULLISH"       # Price up + CVD up = real buyers
        elif price_rising and not cvd_rising:
            signal = "BEARISH_DIVERGENCE"      # Price up + CVD down = fake move
        elif not price_rising and not cvd_rising:
            signal = "CONFIRMED_BEARISH"       # Price down + CVD down = real sellers
        else:
            signal = "BULLISH_DIVERGENCE"      # Price down + CVD up = accumulation

        return {
            "symbol": symbol,
            "cvd_total": round(running_cvd, 2),
            "buy_volume": round(buy_vol, 2),
            "sell_volume": round(sell_vol, 2),
            "delta_ratio": round(buy_vol / sell_vol, 3) if sell_vol > 0 else 1.0,
            "signal": signal,
            "price_rising": price_rising,
            "cvd_rising": cvd_rising
        }

    except Exception as e:
        logging.warning(f"CVD calc error for {symbol}: {e}")
        return {}


def process_cvd_all():
    bus = read_bus()
    market_data = bus.get("market_data", {})
    symbols = list(market_data.keys())[:15]  # Top 15 active coins

    if not symbols:
        record_heartbeat(AGENT_NAME, "IDLE_NO_MARKET_DATA")
        return

    cvd_results = {}
    for sym in symbols:
        sym_data = market_data.get(sym, {})
        # agent_01 publishes candles under market_data[symbol]["candles"]
        candles = sym_data.get("candles", [])
        if not candles:
            # Fallback: try list format (some agents store raw list directly)
            if isinstance(sym_data, list):
                candles = sym_data
        result = calculate_cvd_from_candles(sym, candles)
        if result:
            cvd_results[sym] = result
            logging.info(f"CVD [{sym}]: {result['signal']} | Delta Ratio: {result['delta_ratio']}")

    update_bus_section("cvd_order_flow", cvd_results)
    record_heartbeat(AGENT_NAME, f"HEALTHY_{len(cvd_results)}_SYMBOLS")


def main():
    logging.info(f"{AGENT_NAME} started (bus-only mode, no external HTTP).")
    while True:
        try:
            process_cvd_all()
        except Exception as e:
            logging.error(f"Error: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(30)

if __name__ == "__main__":
    main()
