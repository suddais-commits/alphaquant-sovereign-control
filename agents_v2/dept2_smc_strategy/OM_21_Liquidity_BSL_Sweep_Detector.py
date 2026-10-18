"""
Agent 03: Liquidity Sweep & Fakeout Detector
Single Responsibility:
- Analyzes 15m & 1H candles across all watchlist pairs
- Detects Buy-Side Liquidity (BSL) & Sell-Side Liquidity (SSL) Sweeps
- Detects False Breakouts & Turtle Soup patterns
- Publishes sweep signals to Pipeline Bus
"""
import os
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_03_LiquiditySweepDetector"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_03.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

import indicators_calc as ind

def detect_sweep(klines: list) -> dict:
    if len(klines) < 20:
        return {"has_sweep": False, "sweep_type": None, "swept_level": 0.0, "idm_swept": False}

    # Reference swing high and swing low from previous 15 candles (excluding current 2)
    lookback = klines[-18:-2]
    prev_high = max(k["high"] for k in lookback)
    prev_low = min(k["low"] for k in lookback)

    recent = klines[-1]
    prev_candle = klines[-2]

    # Bullish Liquidity Sweep (SSL Sweep):
    # Price probed below prev_low, but closed back above it (wick rejection)
    is_ssl_sweep = (
        (recent["low"] < prev_low or prev_candle["low"] < prev_low) and
        recent["close"] > prev_low and
        (recent["close"] > recent["open"])
    )

    # Bearish Liquidity Sweep (BSL Sweep):
    # Price pierced above prev_high, but closed back below it
    is_bsl_sweep = (
        (recent["high"] > prev_high or prev_candle["high"] > prev_high) and
        recent["close"] < prev_high and
        (recent["close"] < recent["open"])
    )

    # Dixit Vekariya SMC Inducement (IDM) Sweep Check
    idm_long = ind.detect_smc_inducement(klines, direction="LONG")
    idm_short = ind.detect_smc_inducement(klines, direction="SHORT")

    if is_ssl_sweep or (idm_long.get("idm_swept") and recent["close"] > recent["open"]):
        return {
            "has_sweep": True,
            "sweep_type": "SSL_SWEEP_BULLISH",
            "direction": "LONG",
            "swept_level": prev_low if is_ssl_sweep else idm_long.get("idm_level", prev_low),
            "idm_swept": idm_long.get("idm_swept", False),
            "candle_time": recent.get("open_time", time.time())
        }
    elif is_bsl_sweep or (idm_short.get("idm_swept") and recent["close"] < recent["open"]):
        return {
            "has_sweep": True,
            "sweep_type": "BSL_SWEEP_BEARISH",
            "direction": "SHORT",
            "swept_level": prev_high if is_bsl_sweep else idm_short.get("idm_level", prev_high),
            "idm_swept": idm_short.get("idm_swept", False),
            "candle_time": recent.get("open_time", time.time())
        }

    return {"has_sweep": False, "sweep_type": None, "swept_level": 0.0, "idm_swept": False}

def process_all_sweeps():
    bus = read_bus()
    m_data = bus.get("market_data", {})
    if not m_data:
        return

    sweeps = {}
    found_count = 0
    for sym, item in m_data.items():
        k15 = item.get("klines_15m", [])
        sweep_res = detect_sweep(k15)
        sweeps[sym] = sweep_res
        if sweep_res["has_sweep"]:
            found_count += 1
            logging.info(f"Sweep detected on {sym}: {sweep_res['sweep_type']} @ {sweep_res['swept_level']}")

    update_bus_section("liquidity_sweeps", sweeps)
    record_heartbeat(AGENT_NAME, f"HEALTHY_SWEEPS_{found_count}")

def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_all_sweeps()
        except Exception as e:
            logging.error(f"Error in sweep detection: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(20)

if __name__ == "__main__":
    main()
