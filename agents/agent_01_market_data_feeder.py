"""
Agent 01: Market Data Feeder
Single Responsibility:
- Connects to Binance Futures via proxy
- Fetches real-time 15m, 1H, 4H OHLCV candles & ticker prices for all 25 watchlist pairs
- Publishes clean market data to the shared Pipeline Bus
"""
import os
import sys
import time
import logging
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import update_bus_section, record_heartbeat, read_bus
from proxy_manager import get_proxy

AGENT_NAME = "Agent_01_MarketDataFeeder"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_01.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
    "NEARUSDT", "APTUSDT", "SUIUSDT", "RENDERUSDT", "FETUSDT",
    "FILUSDT", "LTCUSDT", "TIAUSDT", "OPUSDT", "INJUSDT",
    "ATOMUSDT", "DOTUSDT", "WIFUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "PEPEUSDT", "BCHUSDT", "BNBUSDT", "ARBUSDT",
    "TRUMPUSDT", "ZECUSDT"
]

def get_active_watchlist():
    try:
        bus = read_bus()
        cs = bus.get("coin_selection", {})
        if cs and "watchlist" in cs and isinstance(cs["watchlist"], list) and len(cs["watchlist"]) >= 10:
            return cs["watchlist"]
    except Exception:
        pass
    return DEFAULT_WATCHLIST

def fetch_klines(symbol: str, interval: str, limit: int = 100):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    proxies = get_proxy()
    try:
        r = requests.get(url, proxies=proxies, timeout=10)
        if r.status_code == 200:
            raw = r.json()
            klines = []
            for item in raw:
                klines.append({
                    "open_time": int(item[0]),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                    "close_time": int(item[6])
                })
            return klines
    except Exception as e:
        logging.warning(f"Failed to fetch {symbol} {interval}: {e}")
    return []

def run_feeder_cycle():
    active_list = get_active_watchlist()
    logging.info(f"Starting ingestion cycle for {len(active_list)} symbols...")
    market_data = {}
    
    # Fast ticker prices fetch
    prices = {}
    try:
        p_url = "https://fapi.binance.com/fapi/v1/ticker/price"
        pr = requests.get(p_url, proxies=get_proxy(), timeout=8)
        if pr.status_code == 200:
            for p_item in pr.json():
                prices[p_item["symbol"]] = float(p_item["price"])
    except Exception as pe:
        logging.warning(f"Ticker price fetch warning: {pe}")

    for sym in active_list:
        k15 = fetch_klines(sym, "15m", 60)
        k1h = fetch_klines(sym, "1h", 60)
        k4h = fetch_klines(sym, "4h", 40)
        curr_price = prices.get(sym) or (k15[-1]["close"] if k15 else 0.0)
        
        if k15:
            market_data[sym] = {
                "symbol": sym,
                "current_price": curr_price,
                "klines_15m": k15,
                "klines_1h": k1h,
                "klines_4h": k4h,
                "updated_at": time.time()
            }
        time.sleep(0.08)

    if market_data:
        update_bus_section("market_data", market_data)
        record_heartbeat(AGENT_NAME, "HEALTHY")
        logging.info(f"Successfully published market data for {len(market_data)} symbols.")
    else:
        record_heartbeat(AGENT_NAME, "WARNING_NO_DATA")

def main():
    logging.info(f"{AGENT_NAME} started. Entering polling loop.")
    while True:
        try:
            run_feeder_cycle()
        except Exception as e:
            logging.error(f"Error in feeder cycle: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        # Poll every 30 seconds
        time.sleep(30)

if __name__ == "__main__":
    main()
