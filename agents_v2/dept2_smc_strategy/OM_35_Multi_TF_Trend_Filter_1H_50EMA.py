"""
Agent 05: Multi-Timeframe Trend & Wyckoff Filter
Single Responsibility:
- Evaluates 4H Macro Trend (EMA 50)
- Evaluates 1H Trend Alignment (EMA 20 vs EMA 50)
- Enforces strict Multi-Timeframe Confirmation (No counter-trend trades)
- Publishes trend alignments to Pipeline Bus
"""
import os
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_05_MultiTFTrendFilter"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_05.log"),
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

def check_trends(k1h: list, k4h: list, curr_p: float) -> dict:
    if not k1h or not k4h:
        return {"macro_4h": "NEUTRAL", "trend_1h": "NEUTRAL", "aligned": False, "allowed_dir": None}

    c1h = [k["close"] for k in k1h]
    c4h = [k["close"] for k in k4h]

    ema20_1h = calc_ema(c1h, 20)
    ema50_1h = calc_ema(c1h, 50)
    ema50_4h = calc_ema(c4h, 50)

    # 4H Macro
    macro_4h = "BULL" if curr_p >= ema50_4h else "BEAR"

    # 1H Micro Trend
    if ema20_1h > ema50_1h and curr_p >= ema20_1h:
        trend_1h = "BULL"
    elif ema20_1h < ema50_1h and curr_p <= ema20_1h:
        trend_1h = "BEAR"
    else:
        trend_1h = "NEUTRAL"

    # Strict Alignment
    aligned = (macro_4h == trend_1h and trend_1h != "NEUTRAL")
    allowed_dir = "LONG" if (aligned and trend_1h == "BULL") else ("SHORT" if (aligned and trend_1h == "BEAR") else None)

    return {
        "macro_4h": macro_4h,
        "trend_1h": trend_1h,
        "ema20_1h": round(ema20_1h, 4),
        "ema50_1h": round(ema50_1h, 4),
        "ema50_4h": round(ema50_4h, 4),
        "aligned": aligned,
        "allowed_dir": allowed_dir
    }

def process_trends_all():
    bus = read_bus()
    m_data = bus.get("market_data", {})
    if not m_data:
        return

    trends = {}
    aligned_count = 0
    for sym, item in m_data.items():
        k1h = item.get("klines_1h", [])
        k4h = item.get("klines_4h", [])
        curr_p = item.get("current_price", 0.0)
        res = check_trends(k1h, k4h, curr_p)
        trends[sym] = res
        if res["aligned"]:
            aligned_count += 1

    update_bus_section("trend_filters", trends)
    record_heartbeat(AGENT_NAME, f"HEALTHY_ALIGNED_{aligned_count}")

def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_trends_all()
        except Exception as e:
            logging.error(f"Error in trend filter: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(20)

if __name__ == "__main__":
    main()
