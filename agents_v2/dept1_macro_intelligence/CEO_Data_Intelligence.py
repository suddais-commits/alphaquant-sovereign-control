"""
Agent 02: BTC Market Regime Sentinel
Single Responsibility:
- Reads BTCUSDT 15m, 1H, 4H data from Pipeline Bus
- Evaluates BTC Macro Trend, Structure, and RSI
- Establishes Global Market Regime ('BULL', 'BEAR', 'CHOP') to protect altcoin trades
"""
import os
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_02_BTCRegimeSentinel"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_02.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

def calc_ema(closes: list, period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    multiplier = 2.0 / (period + 1.0)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = (c - ema) * multiplier + ema
    return ema

def calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * 13 + gains[i]) / 14
        avg_loss = (avg_loss * 13 + losses[i]) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def evaluate_btc_regime():
    bus = read_bus()
    m_data = bus.get("market_data", {})
    btc_entry = m_data.get("BTCUSDT")
    if not btc_entry:
        return

    k15 = btc_entry.get("klines_15m", [])
    k1h = btc_entry.get("klines_1h", [])
    k4h = btc_entry.get("klines_4h", [])
    curr_p = btc_entry.get("current_price", 0.0)

    if not k1h or not k4h:
        return

    c1h = [k["close"] for k in k1h]
    c4h = [k["close"] for k in k4h]

    ema20_1h = calc_ema(c1h, 20)
    ema50_1h = calc_ema(c1h, 50)
    ema50_4h = calc_ema(c4h, 50)
    rsi_1h = calc_rsi(c1h, 14)

    # Classification:
    # BULL: 4H price > EMA50 and 1H EMA20 > EMA50 and RSI > 48
    # BEAR: 4H price < EMA50 and 1H EMA20 < EMA50 and RSI < 52
    # CHOP: Mixed signals or RSI stuck in 45-55 zone
    if curr_p > ema50_4h and ema20_1h > ema50_1h and rsi_1h >= 48:
        regime = "BULL"
        alt_long_allowed = True
        alt_short_allowed = False
    elif curr_p < ema50_4h and ema20_1h < ema50_1h and rsi_1h <= 52:
        regime = "BEAR"
        alt_long_allowed = False
        alt_short_allowed = True
    else:
        regime = "CHOP"
        # In chop, only exceptional setups allowed
        alt_long_allowed = (curr_p > ema20_1h)
        alt_short_allowed = (curr_p < ema20_1h)

    btc_result = {
        "regime": regime,
        "btc_price": curr_p,
        "ema20_1h": round(ema20_1h, 2),
        "ema50_1h": round(ema50_1h, 2),
        "ema50_4h": round(ema50_4h, 2),
        "rsi_1h": round(rsi_1h, 2),
        "alt_long_allowed": alt_long_allowed,
        "alt_short_allowed": alt_short_allowed,
        "updated_at": time.time()
    }

    update_bus_section("btc_regime", btc_result)
    record_heartbeat(AGENT_NAME, f"HEALTHY_{regime}")
    logging.info(f"BTC Regime Updated: {regime} | Price: ${curr_p:.2f} | Long Allowed: {alt_long_allowed}")

def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            evaluate_btc_regime()
        except Exception as e:
            logging.error(f"Error evaluating BTC regime: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(15)

if __name__ == "__main__":
    main()
