"""
Agent 06: Momentum & Volatility Guard
Single Responsibility:
- Calculates RSI(14) on 15m and 1H
- Filters out the Dead Zone Chop (RSI 46-54) and Extreme Overbought (>70) / Oversold (<30)
- Computes ATR(14) and ATR% for dynamic stop loss buffering
- Publishes momentum & volatility validations to Pipeline Bus
"""
import os
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_06_MomentumVolatilityGuard"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_06.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

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

def calc_atr(klines: list, period: int = 14) -> float:
    if len(klines) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(klines)):
        high = klines[i]["high"]
        low = klines[i]["low"]
        prev_close = klines[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period

import indicators_calc as ind

def evaluate_guard(k15: list, k1h: list, curr_p: float) -> dict:
    if not k15 or not k1h:
        return {
            "rsi_15m": 50.0, "rsi_1h": 50.0, "atr": 0.0, "atr_pct": 0.0,
            "pass_guard": False, "reason": "NO_DATA", "elder_ray": {}, "acd_pivot": {}
        }

    c15 = [float(k["close"]) for k in k15]
    h15 = [float(k["high"]) for k in k15]
    l15 = [float(k["low"]) for k in k15]
    c1h = [float(k["close"]) for k in k1h]

    rsi_15m = calc_rsi(c15, 14)
    rsi_1h = calc_rsi(c1h, 14)
    atr = calc_atr(k15, 14)
    atr_pct = (atr / curr_p * 100.0) if curr_p > 0 else 0.0

    # Elder-ray & ACD Pivot Range analysis
    elder_ray = ind.calc_elder_ray(h15, l15, c15, 13)
    acd_pivots = ind.calc_acd_pivot_range(h15, l15, c15, 24)

    # Dead Zone Chop Reject: RSI 46-54
    # Extreme Overbought: > 72, Extreme Oversold: < 28
    is_dead_zone = (46.0 <= rsi_1h <= 54.0) or (46.0 <= rsi_15m <= 54.0)
    is_overextended = (rsi_1h > 72.0 or rsi_1h < 28.0)
    
    # Healthy Volatility: ATR% between 0.3% and 3.5%
    is_volatility_healthy = (0.3 <= atr_pct <= 3.5)

    pass_guard = (not is_dead_zone) and (not is_overextended) and is_volatility_healthy

    reason = "PASS"
    if is_dead_zone:
        reason = "RSI_DEAD_ZONE_CHOP"
    elif is_overextended:
        reason = "RSI_OVEREXTENDED"
    elif not is_volatility_healthy:
        reason = "UNHEALTHY_VOLATILITY"

    return {
        "rsi_15m": round(rsi_15m, 2),
        "rsi_1h": round(rsi_1h, 2),
        "atr": round(atr, 6),
        "atr_pct": round(atr_pct, 2),
        "pass_guard": pass_guard,
        "reason": reason,
        "elder_ray": {
            "bull_power": elder_ray.get("latest_bull_power", 0.0),
            "bear_power": elder_ray.get("latest_bear_power", 0.0),
            "bullish_divergence": elder_ray.get("bullish_divergence", False),
            "bearish_divergence": elder_ray.get("bearish_divergence", False)
        },
        "acd_pivot": {
            "pivot": acd_pivots.get("pivot", curr_p),
            "bias": acd_pivots.get("bias", "NEUTRAL")
        }
    }

def process_volatility_all():
    bus = read_bus()
    m_data = bus.get("market_data", {})
    if not m_data:
        return

    guards = {}
    pass_count = 0
    for sym, item in m_data.items():
        k15 = item.get("klines_15m", [])
        k1h = item.get("klines_1h", [])
        curr_p = item.get("current_price", 0.0)
        res = evaluate_guard(k15, k1h, curr_p)
        guards[sym] = res
        if res["pass_guard"]:
            pass_count += 1

    update_bus_section("volatility_guards", guards)
    record_heartbeat(AGENT_NAME, f"HEALTHY_PASS_{pass_count}")

def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_volatility_all()
        except Exception as e:
            logging.error(f"Error in volatility guard: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(20)

if __name__ == "__main__":
    main()
