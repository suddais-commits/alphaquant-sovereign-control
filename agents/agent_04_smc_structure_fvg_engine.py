"""
Agent 04: SMC Structure & FVG Engine
Single Responsibility:
- Identifies Market Structure (CHoCH / BOS)
- Detects 3-candle Fair Value Gaps (FVG)
- Identifies Unmitigated Bullish & Bearish Order Blocks (OB)
- Publishes SMC structural footprints to Pipeline Bus
"""
import os
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_04_SMCStructureFVGEngine"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_04.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

def analyze_smc(klines: list) -> dict:
    if len(klines) < 15:
        return {
            "has_fvg": False, "has_ob": False, "structure": "NEUTRAL",
            "ob_price": 0.0, "fvg_gap": 0.0, "unmitigated_ob": False, "flip_zone": False
        }

    # 1. Detect Fair Value Gap (FVG) in last 5 candles
    has_fvg = False
    fvg_type = None
    fvg_gap = 0.0
    for i in range(len(klines) - 4, len(klines) - 1):
        c1 = klines[i - 1]
        c2 = klines[i]
        c3 = klines[i + 1]
        if c3["low"] > c1["high"]:
            has_fvg = True
            fvg_type = "BULLISH_FVG"
            fvg_gap = round(c3["low"] - c1["high"], 6)
            break
        elif c3["high"] < c1["low"]:
            has_fvg = True
            fvg_type = "BEARISH_FVG"
            fvg_gap = round(c1["low"] - c3["high"], 6)
            break

    # 2. Detect Unmitigated Order Block (OB)
    # Dixit Vekariya rule: An OB is valid ONLY if subsequent candles have not pierced & mitigated it
    has_ob = False
    ob_type = None
    ob_price = 0.0
    unmitigated_ob = False
    flip_zone = False

    for i in range(len(klines) - 6, len(klines) - 2):
        cand = klines[i]
        next_cand = klines[i + 1]
        subsequent = klines[i + 2:]
        # Bullish displacement (Down candle followed by strong green body break)
        if cand["close"] < cand["open"] and next_cand["close"] > cand["high"]:
            ob_low = cand["low"]
            ob_high = cand["high"]
            # Check if mitigated by any subsequent candle low dipping below ob_low
            is_mitigated = any(k["low"] < ob_low for k in subsequent) if subsequent else False
            has_ob = True
            ob_type = "BULLISH_OB"
            ob_price = ob_low
            unmitigated_ob = not is_mitigated
            break
        # Bearish displacement
        elif cand["close"] > cand["open"] and next_cand["close"] < cand["low"]:
            ob_low = cand["low"]
            ob_high = cand["high"]
            is_mitigated = any(k["high"] > ob_high for k in subsequent) if subsequent else False
            has_ob = True
            ob_type = "BEARISH_OB"
            ob_price = ob_high
            unmitigated_ob = not is_mitigated
            break

    # 3. Market Structure (True Body BOS vs Wick Sweep)
    highs = [k["high"] for k in klines[-10:]]
    lows = [k["low"] for k in klines[-10:]]
    recent = klines[-1]
    prev_swing_h = max(highs[:-2])
    prev_swing_l = min(lows[:-2])
    
    if recent["close"] > prev_swing_h:
        structure = "TRUE_BULLISH_BOS"  # Body closed above swing high
    elif recent["close"] < prev_swing_l:
        structure = "TRUE_BEARISH_BOS"  # Body closed below swing low
    elif recent["high"] > prev_swing_h:
        structure = "BULLISH_WICK_SWEEP"
    elif recent["low"] < prev_swing_l:
        structure = "BEARISH_WICK_SWEEP"
    else:
        structure = "RANGING"

    # 4. Flip Zone Detection (S2D / D2S)
    if has_ob and structure in ("TRUE_BULLISH_BOS", "TRUE_BEARISH_BOS"):
        flip_zone = True

    return {
        "has_fvg": has_fvg,
        "fvg_type": fvg_type,
        "fvg_gap": fvg_gap,
        "has_ob": has_ob,
        "ob_type": ob_type,
        "ob_price": ob_price,
        "unmitigated_ob": unmitigated_ob,
        "flip_zone": flip_zone,
        "structure": structure
    }

def process_smc_all():
    bus = read_bus()
    m_data = bus.get("market_data", {})
    if not m_data:
        return

    smc_results = {}
    valid_count = 0
    for sym, item in m_data.items():
        k15 = item.get("klines_15m", [])
        res = analyze_smc(k15)
        smc_results[sym] = res
        if res["has_fvg"] or res["has_ob"]:
            valid_count += 1

    update_bus_section("smc_structures", smc_results)
    record_heartbeat(AGENT_NAME, f"HEALTHY_SMC_{valid_count}")

def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_smc_all()
        except Exception as e:
            logging.error(f"Error in SMC engine: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(20)

if __name__ == "__main__":
    main()
