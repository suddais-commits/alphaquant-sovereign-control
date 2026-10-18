"""
Agent 17: Correlation & BTC Dominance Filter
Single Responsibility:
- Fetches BTC Dominance from CoinGecko (free, no API key).
- Calculates ETH/BTC ratio trend.
- If BTC.D rising = altcoin risk HIGH → block altcoin longs.
- If BTC.D falling = altcoin season → allow altcoin longs.
- Writes correlation_filter section to Pipeline Bus.
"""
import os
import sys
import time
import logging
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_17_CorrelationFilter"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_17.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

KLINES_URL = "https://data-api.binance.vision/api/v3/klines"

# Cache to avoid hammering CoinGecko
_DOMINANCE_CACHE = {"value": None, "timestamp": 0}
DOMINANCE_CACHE_TTL = 300  # 5 minutes


def get_btc_dominance() -> float:
    """Fetch BTC dominance from CoinGecko global endpoint."""
    global _DOMINANCE_CACHE
    now = time.time()
    if _DOMINANCE_CACHE["value"] and (now - _DOMINANCE_CACHE["timestamp"] < DOMINANCE_CACHE_TTL):
        return _DOMINANCE_CACHE["value"]
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/global",
            timeout=8
        )
        if r.status_code == 200:
            data = r.json().get("data", {})
            dominance = data.get("market_cap_percentage", {}).get("btc", 50.0)
            _DOMINANCE_CACHE = {"value": round(dominance, 2), "timestamp": now}
            return round(dominance, 2)
    except Exception as e:
        logging.warning(f"CoinGecko dominance fetch failed: {e}")
    return _DOMINANCE_CACHE.get("value") or 50.0


def get_eth_btc_ratio_trend() -> dict:
    """
    Calculate ETH/BTC ratio from last 20 4H candles.
    Rising ETH/BTC = altcoin season incoming.
    Falling ETH/BTC = BTC dominance phase.
    """
    try:
        # ETH price
        r_eth = requests.get(KLINES_URL, params={"symbol": "ETHUSDT", "interval": "4h", "limit": 20}, timeout=5)
        r_btc = requests.get(KLINES_URL, params={"symbol": "BTCUSDT", "interval": "4h", "limit": 20}, timeout=5)

        if r_eth.status_code != 200 or r_btc.status_code != 200:
            return {"ratio_trend": "UNKNOWN", "eth_btc_ratio": 0.0}

        eth_closes = [float(k[4]) for k in r_eth.json()]
        btc_closes = [float(k[4]) for k in r_btc.json()]

        if not eth_closes or not btc_closes:
            return {"ratio_trend": "UNKNOWN", "eth_btc_ratio": 0.0}

        ratios = [e / b for e, b in zip(eth_closes, btc_closes)]
        current_ratio = ratios[-1]
        past_ratio = ratios[0]
        trend = "RISING" if current_ratio > past_ratio * 1.005 else ("FALLING" if current_ratio < past_ratio * 0.995 else "FLAT")

        return {
            "eth_btc_ratio": round(current_ratio, 6),
            "ratio_trend": trend,
            "altcoin_season": trend == "RISING"
        }
    except Exception as e:
        logging.warning(f"ETH/BTC ratio error: {e}")
        return {"ratio_trend": "UNKNOWN", "eth_btc_ratio": 0.0}


def process_correlation_filter():
    btc_dominance = get_btc_dominance()
    eth_btc = get_eth_btc_ratio_trend()

    # Decision logic
    # BTC.D > 58% = danger zone for altcoins
    # BTC.D < 52% = altcoin season
    btc_dominance_rising_risk = btc_dominance > 57.0
    altcoin_season = btc_dominance < 53.0 or eth_btc.get("altcoin_season", False)

    if btc_dominance_rising_risk:
        regime = "BTC_DOMINANCE_PHASE"
        alts_allowed = False
    elif altcoin_season:
        regime = "ALTCOIN_SEASON"
        alts_allowed = True
    else:
        regime = "NEUTRAL_TRANSITION"
        alts_allowed = True  # Allow but with caution

    result = {
        "btc_dominance_pct": btc_dominance,
        "eth_btc_ratio": eth_btc.get("eth_btc_ratio", 0.0),
        "eth_btc_trend": eth_btc.get("ratio_trend", "UNKNOWN"),
        "regime": regime,
        "altcoin_longs_allowed": alts_allowed,
        "btc_only_mode": btc_dominance_rising_risk
    }

    update_bus_section("correlation_filter", result)
    record_heartbeat(AGENT_NAME, f"HEALTHY | Regime: {regime} | BTC.D: {btc_dominance}%")
    logging.info(f"Correlation Filter: {regime} | BTC.D={btc_dominance}% | Alts Allowed: {alts_allowed}")


def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_correlation_filter()
        except Exception as e:
            logging.error(f"Error: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(300)  # Run every 5 minutes

if __name__ == "__main__":
    main()
