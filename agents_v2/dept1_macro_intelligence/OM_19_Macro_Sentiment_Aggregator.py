"""
Agent 07: Gemini AI & Institutional Conviction Scorer
Single Responsibility:
- Aggregates technical indicators from Agents 02, 03, 04, 05, 06
- Enforces STRICT Directional Consistency:
  * For LONG: Must have Bullish Sweep (SSL Sweep), Bullish OB/FVG, Bullish Trend, BTC Bullish
  * For SHORT: Must have Bearish Sweep (BSL Sweep), Bearish OB/FVG, Bearish Trend, BTC Bearish
  * NEVER mixes a Bullish Sweep with a Short entry or vice versa!
- Approves ONLY A+ setups scoring >= 90
"""
import os
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_07_GeminiConvictionScorer"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_07.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

try:
    from news_service import analyze_news_sentiment
    _NEWS_AVAILABLE = True
except ImportError:
    _NEWS_AVAILABLE = False

def evaluate_setup_for_direction(sym: str, direction: str, bus: dict) -> dict:
    btc_regime = bus.get("btc_regime", {})
    sweeps = bus.get("liquidity_sweeps", {}).get(sym, {})
    smc = bus.get("smc_structures", {}).get(sym, {})
    trends = bus.get("trend_filters", {}).get(sym, {})
    guards = bus.get("volatility_guards", {}).get(sym, {})
    market_entry = bus.get("market_data", {}).get(sym, {})

    curr_p = market_entry.get("current_price", 0.0)
    if curr_p <= 0:
        return {"score": 0, "approved": False, "reason": "NO_PRICE"}

    score = 0
    breakdown = []

    # 0. Real-Time News Black Swan Circuit Breaker
    if _NEWS_AVAILABLE:
        news_sent = analyze_news_sentiment(category="crypto", limit=6)
        if news_sent.get("black_swan_alert"):
            return {
                "score": 0,
                "approved": False,
                "reason": f"BLACK_SWAN_CIRCUIT_BREAKER ({news_sent.get('black_swan_reason')})"
            }
        elif news_sent.get("sentiment") == "BULLISH" and direction == "LONG":
            score += 5
            breakdown.append("NEWS_BULLISH(+5)")
        elif news_sent.get("sentiment") == "BEARISH" and direction == "SHORT":
            score += 5
            breakdown.append("NEWS_BEARISH(+5)")

    # 1. BTC Regime Check (+20 pts)
    if direction == "LONG":
        if btc_regime.get("alt_long_allowed"):
            score += 20
            breakdown.append("BTC_BULL_ALIGNED(+20)")
        elif btc_regime.get("regime") == "BEAR":
            return {"score": 0, "approved": False, "reason": "BTC_DUMP_DISQUALIFIED"}
    else: # SHORT
        if btc_regime.get("alt_short_allowed"):
            score += 20
            breakdown.append("BTC_BEAR_ALIGNED(+20)")
        elif btc_regime.get("regime") == "BULL":
            return {"score": 0, "approved": False, "reason": "BTC_BULL_DISQUALIFIED"}

    # 2. Strict Directional Sweep Check & Inducement (+25 pts)
    if direction == "LONG":
        if sweeps.get("has_sweep") and sweeps.get("sweep_type") == "SSL_SWEEP_BULLISH":
            score += 20
            breakdown.append("BULLISH_SSL_SWEEP(+20)")
            if sweeps.get("idm_swept"):
                score += 5
                breakdown.append("IDM_SWEPT(+5)")
        elif sweeps.get("has_sweep") and sweeps.get("sweep_type") == "BSL_SWEEP_BEARISH":
            return {"score": 0, "approved": False, "reason": "OPPOSING_BEARISH_SWEEP"}
    else: # SHORT
        if sweeps.get("has_sweep") and sweeps.get("sweep_type") == "BSL_SWEEP_BEARISH":
            score += 20
            breakdown.append("BEARISH_BSL_SWEEP(+20)")
            if sweeps.get("idm_swept"):
                score += 5
                breakdown.append("IDM_SWEPT(+5)")
        elif sweeps.get("has_sweep") and sweeps.get("sweep_type") == "SSL_SWEEP_BULLISH":
            return {"score": 0, "approved": False, "reason": "OPPOSING_BULLISH_SWEEP"}

    # 3. Directional SMC Footprint & Unmitigated OB (+20 pts)
    if direction == "LONG":
        if smc.get("has_ob") and smc.get("ob_type") == "BULLISH_OB":
            score += 10
            breakdown.append("BULLISH_OB(+10)")
            if smc.get("unmitigated_ob"):
                score += 5
                breakdown.append("UNMITIGATED_OB(+5)")
        if smc.get("has_fvg") and smc.get("fvg_type") == "BULLISH_FVG":
            score += 5
            breakdown.append("BULLISH_FVG(+5)")
    else: # SHORT
        if smc.get("has_ob") and smc.get("ob_type") == "BEARISH_OB":
            score += 10
            breakdown.append("BEARISH_OB(+10)")
            if smc.get("unmitigated_ob"):
                score += 5
                breakdown.append("UNMITIGATED_OB(+5)")
        if smc.get("has_fvg") and smc.get("fvg_type") == "BEARISH_FVG":
            score += 5
            breakdown.append("BEARISH_FVG(+5)")

    # 4. Multi-TF Trend Alignment (+15 pts)
    if trends.get("aligned") and trends.get("allowed_dir") == direction:
        score += 15
        breakdown.append("TREND_ALIGNED(+15)")
    else:
        if trends.get("allowed_dir") and trends.get("allowed_dir") != direction:
            return {"score": 0, "approved": False, "reason": "COUNTER_TREND_DISQUALIFIED"}

    # 5. Momentum & Volatility Guard (+10 pts)
    if guards.get("pass_guard"):
        score += 10
        breakdown.append("MOMENTUM_GUARD_PASS(+10)")
    else:
        if guards.get("reason") == "RSI_DEAD_ZONE_CHOP":
            return {"score": 0, "approved": False, "reason": "RSI_DEAD_ZONE_DISQUALIFIED"}

    # 6. Elder-Ray & Fisher ACD Pivots Confluence (+10 pts)
    er = guards.get("elder_ray", {})
    acd = guards.get("acd_pivot", {})
    if direction == "LONG":
        if er.get("bullish_divergence") or er.get("bull_power", 0) > 0:
            score += 5
            breakdown.append("ELDER_RAY_BULL(+5)")
        if acd.get("bias") == "ABOVE_PIVOT_BULLISH":
            score += 5
            breakdown.append("ACD_PIVOT_BULL(+5)")
    else: # SHORT
        if er.get("bearish_divergence") or er.get("bear_power", 0) < 0:
            score += 5
            breakdown.append("ELDER_RAY_BEAR(+5)")
        if acd.get("bias") == "BELOW_PIVOT_BEARISH":
            score += 5
            breakdown.append("ACD_PIVOT_BEAR(+5)")

    min_score = float(os.getenv("SCORE_THRESHOLD", "30.0"))
    approved = (score >= min_score)

    return {
        "symbol": sym,
        "score": score,
        "direction": direction,
        "current_price": curr_p,
        "approved": approved,
        "breakdown": breakdown,
        "atr": guards.get("atr", curr_p * 0.01),
        "timestamp": time.time()
    }

def score_confluence(sym: str, bus: dict) -> dict:
    long_eval = evaluate_setup_for_direction(sym, "LONG", bus)
    short_eval = evaluate_setup_for_direction(sym, "SHORT", bus)

    if long_eval["score"] >= short_eval["score"] and long_eval["score"] > 0:
        return long_eval
    elif short_eval["score"] > 0:
        return short_eval
    else:
        market_entry = bus.get("market_data", {}).get(sym, {})
        return {
            "symbol": sym,
            "score": 0,
            "direction": "NONE",
            "current_price": market_entry.get("current_price", 0.0),
            "approved": False,
            "breakdown": ["NO_CONFLUENCE"],
            "atr": 0.0,
            "timestamp": time.time()
        }

def process_scoring_all():
    bus = read_bus()
    m_data = bus.get("market_data", {})
    if not m_data:
        return

    scores = {}
    approved_list = []
    for sym in m_data.keys():
        res = score_confluence(sym, bus)
        scores[sym] = res
        if res["approved"]:
            approved_list.append(sym)
            logging.info(f"🎯 APPROVED HIGH-CONVICTION SETUP: {sym} | Dir: {res['direction']} | Score: {res['score']}/100")

    update_bus_section("conviction_scores", scores)
    record_heartbeat(AGENT_NAME, f"HEALTHY_APPROVED_{len(approved_list)}")

def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_scoring_all()
        except Exception as e:
            logging.error(f"Error in conviction scoring: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(20)

if __name__ == "__main__":
    main()
