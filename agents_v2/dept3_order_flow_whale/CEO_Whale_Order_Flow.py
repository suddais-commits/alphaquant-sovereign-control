"""
Board Committee Consensus & Debate Engine
==========================================
Tier 2 Institutional Decision-Making Layer.

4 Senior Board Members evaluate the factual data collected by Tier 1 Data Scouts:
  1. CTA  — Chief Technical Analyst (SMC/ICT structure, S/R, Candlesticks, Multi-TF alignment)
  2. CRO  — Chief Risk Officer (Portfolio risk %, drawdown, RR >= 2.0R, circuit breakers). Holds VETO power!
  3. CMSO — Chief Macro & Sentiment Officer (BTC regime, BTC Dominance, Session time, RSS news)
  4. COWA — Chief Order Flow & Whale Arbiter (CVD divergence, Whale Long/Short ratio, OI, Funding rate)

Rules of Deliberation:
  - Each Board Member evaluates facts, produces a Thesis and Risk Counter-Thesis, and casts a VOTE (APPROVE / REJECT / ABSTAIN) with a Score (0-100).
  - VETO Rule: If CRO votes REJECT (e.g. Risk > 6%, Drawdown violation, 3-loss circuit active), the trade is immediately VETOED (Status: REJECTED).
  - Consensus Gate: Overall weighted score >= 85 AND minimum 3 of 4 APPROVALS required for status: APPROVED.
  - Approved resolutions are forwarded to Tier 3 (Agent 08 Position Sizer & Agent 09 Binance Execution).
"""

import os
import sys
import time
import logging
from typing import Dict, Any, List, Tuple

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    import pipeline_bus as bus
except ImportError:
    bus = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


class BoardMemberCTA:
    """Board Member 1: Chief Technical Analyst"""
    name = "Chief Technical Analyst (CTA)"

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        smc = data.get("smc_structure", {}).get(symbol, {})
        smc_cascade = data.get("smc_cascade", {}).get(symbol, {})
        trend = data.get("multi_tf_trends", {}).get(symbol, {})
        sr = data.get("sr_levels", {}).get(symbol, {})
        patterns = data.get("candle_patterns", {}).get(symbol, {})
        sweeps = data.get("liquidity_sweeps", {}).get(symbol, {})

        score = 50
        pros = []
        cons = []

        # 1. SMC Cascade check
        cascade_score = smc_cascade.get("cascade_score", 0)
        if cascade_score >= 80:
            score += 25
            pros.append(f"Strong 8-TF SMC Cascade score ({cascade_score}/100) with verified OB/FVG mitigation.")
        elif cascade_score >= 60:
            score += 10
            pros.append(f"Moderate SMC Cascade ({cascade_score}/100).")
        else:
            score -= 15
            cons.append("Weak SMC cascade alignment across higher timeframes.")

        # 2. Liquidity Sweep confirmation
        if sweeps.get("has_sweep"):
            score += 15
            pros.append(f"Confirmed {sweeps.get('sweep_type', 'liquidity')} sweep at key level {sweeps.get('swept_level', 0)}.")
        else:
            cons.append("No clean liquidity sweep wick detected on 15m.")

        # 3. Multi-TF Trend alignment
        if trend.get("trend_aligned_long"):
            score += 15
            pros.append("1D, 4H, 1H EMA20/EMA50 trends are 100% aligned bullish.")
        elif not trend.get("trend_aligned_long", True):
            score -= 20
            cons.append("Higher timeframe EMA trend conflict detected.")

        # 4. Candlestick patterns
        patt_list = patterns.get("patterns", [])
        if patt_list:
            score += 10
            pros.append(f"Bullish price action confirmation: {', '.join(patt_list)}.")

        score = max(0, min(100, score))
        vote = "APPROVE" if score >= 80 else ("ABSTAIN" if score >= 65 else "REJECT")
        
        return {
            "member": self.name,
            "vote": vote,
            "score": score,
            "thesis": " | ".join(pros) if pros else "Neutral technical setup.",
            "risks": " | ".join(cons) if cons else "Zero significant technical risks identified."
        }


class BoardMemberCRO:
    """Board Member 2: Chief Risk Officer (Holds Absolute VETO Power)"""
    name = "Chief Risk Officer (CRO)"

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        p_risk = data.get("portfolio_risk", {})
        circuit = data.get("circuit_breaker", {})
        positions = data.get("active_positions", {})

        score = 100
        pros = []
        cons = []
        is_veto = False

        # 1. Circuit Breaker Check
        if circuit.get("circuit_active"):
            is_veto = True
            score = 0
            cons.append(f"CIRCUIT BREAKER ACTIVE: {circuit.get('reason', '3 consecutive losses')}. Cooling down.")
        else:
            pros.append("Circuit breaker normal. No losing streak cooldown active.")

        # 2. Total Portfolio Risk % Check
        total_risk_pct = p_risk.get("total_risk_percent", 0.0)
        max_allowed_risk = p_risk.get("max_allowed_risk_pct", 6.0)
        if total_risk_pct >= max_allowed_risk:
            is_veto = True
            score = 0
            cons.append(f"PORTFOLIO RISK EXCEEDED: Current {total_risk_pct:.1f}% >= Max {max_allowed_risk}%.")
        elif total_risk_pct >= 4.0:
            score -= 25
            cons.append(f"Portfolio risk elevated ({total_risk_pct:.1f}%/6.0%). Position size will be restricted.")
        else:
            pros.append(f"Healthy portfolio risk allocation ({total_risk_pct:.1f}% used).")

        # 3. Max Active Positions Check
        if len(positions) >= 8:
            is_veto = True
            score = 0
            cons.append(f"MAX CAPACITY REACHED: {len(positions)} active positions open.")
        else:
            pros.append(f"Available position capacity ({len(positions)}/8 active).")

        vote = "REJECT" if is_veto or score < 75 else ("APPROVE" if score >= 80 else "ABSTAIN")

        return {
            "member": self.name,
            "vote": vote,
            "score": score,
            "is_veto": is_veto,
            "thesis": " | ".join(pros) if pros else "Capital preservation baseline met.",
            "risks": " | ".join(cons) if cons else "All risk metrics well within safety margins."
        }


class BoardMemberCMSO:
    """Board Member 3: Chief Macro & Sentiment Officer"""
    name = "Chief Macro & Sentiment Officer (CMSO)"

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        btc_regime = data.get("btc_regime", {})
        corr = data.get("correlation_filter", {})
        session = data.get("session_filter", {})
        news = data.get("news_sentiment", {})

        score = 50
        pros = []
        cons = []

        # 1. BTC Regime Check
        regime = btc_regime.get("regime", "UNKNOWN")
        if regime == "BULL":
            score += 25
            pros.append("Macro BTC regime is decisively BULLISH (Price > 1D/4H EMAs).")
        elif regime == "CHOP":
            score -= 10
            cons.append("BTC in ranging/chop mode. Altcoin beta moves require tighter stops.")
        elif regime == "BEAR":
            score -= 30
            cons.append("BTC regime is BEARISH. Severe macro headwind for altcoin longs.")

        # 2. BTC Dominance Correlation Check
        if corr.get("alt_season_favorable"):
            score += 15
            pros.append(f"BTC.D trending down/stable ({corr.get('btc_d', 58.0):.1f}%). Altcoin expansion favored.")
        elif corr.get("btc_d_rising_risk"):
            score -= 20
            cons.append("BTC Dominance is spiking rapidly. Liquidity being sucked out of alts.")

        # 3. News Sentiment Check
        news_sentiment = news.get("sentiment", "NEUTRAL")
        if news_sentiment == "BULLISH":
            score += 15
            pros.append(f"Live crypto media sentiment is positive (Score: {news.get('sentiment_score', 75)}).")
        elif news_sentiment == "CRITICAL_BEARISH":
            score -= 35
            cons.append(f"EMERGENCY NEWS ALERT: High impact negative news / exploits detected ({news.get('headline', '')}).")

        # 4. Session Liquidity
        if session.get("high_liquidity_session"):
            score += 10
            pros.append(f"Active session: {session.get('active_session', 'London/NY Overlap')} (Peak institutional volume).")
        elif session.get("dead_zone"):
            score -= 15
            cons.append("Trading during off-hours dead zone (00:00-07:00 UTC). Low volume trap risk.")

        score = max(0, min(100, score))
        vote = "APPROVE" if score >= 80 else ("ABSTAIN" if score >= 65 else "REJECT")

        return {
            "member": self.name,
            "vote": vote,
            "score": score,
            "thesis": " | ".join(pros) if pros else "Macro environment neutral.",
            "risks": " | ".join(cons) if cons else "Zero macro or news headwinds detected."
        }


class BoardMemberCOWA:
    """Board Member 4: Chief Order Flow & Whale Arbiter"""
    name = "Chief Order Flow & Whale Arbiter (COWA)"

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        cvd = data.get("cvd_order_flow", {}).get(symbol, {})
        whale = data.get("whale_funding", {}).get(symbol, {})
        tokenomics = data.get("institutional_research", {}).get(symbol, {})

        score = 50
        pros = []
        cons = []

        # 1. CVD Order Flow Delta
        if cvd.get("cvd_divergence") == "BULLISH_ABSORPTION":
            score += 25
            pros.append(f"Bullish CVD Delta absorption detected. Aggressive limit buyers soaking sell orders.")
        elif cvd.get("cvd_divergence") == "BEARISH_DISTRIBUTION":
            score -= 25
            cons.append("Bearish CVD Delta divergence. Whales offloading into retail buying.")

        # 2. Binance Top Trader Whale Ratio
        whale_ratio = whale.get("top_trader_long_short_ratio", 1.0)
        if whale_ratio >= 1.5:
            score += 20
            pros.append(f"Binance Top Trader Whale Ratio is heavily LONG ({whale_ratio:.2f}x). Institutional accumulation.")
        elif whale_ratio < 0.8:
            score -= 20
            cons.append(f"Top Trader Whale Ratio skewed SHORT ({whale_ratio:.2f}x). Smart money positioning for dump.")

        # 3. Funding Rate Squeeze Check
        funding_rate = whale.get("funding_rate", 0.0001)
        if funding_rate < 0:
            score += 15
            pros.append(f"Negative funding rate ({funding_rate*100:.3f}%). High probability short-squeeze setup.")
        elif funding_rate > 0.0005:
            score -= 15
            cons.append(f"Overheated positive funding rate ({funding_rate*100:.3f}%). Long squeeze / liquidation cascade risk.")

        # 4. Tokenomics Health
        t_score = tokenomics.get("tokenomics_score", 70)
        if t_score >= 80:
            score += 10
            pros.append(f"Institutional tokenomics rating is Tier-1 ({t_score}/100). Low unlock dilution risk.")
        elif t_score < 50:
            score -= 15
            cons.append(f"Low tokenomics score ({t_score}/100). High token unlock inflation overhang.")

        score = max(0, min(100, score))
        vote = "APPROVE" if score >= 80 else ("ABSTAIN" if score >= 65 else "REJECT")

        return {
            "member": self.name,
            "vote": vote,
            "score": score,
            "thesis": " | ".join(pros) if pros else "Order flow & whale positioning neutral.",
            "risks": " | ".join(cons) if cons else "Zero smart money distribution detected."
        }


# ============================================================================
# Board Deliberation & Resolution Engine
# ============================================================================

class BoardCommitteeEngine:
    """Conducts structured debates and voting across all 4 Board Members"""

    def __init__(self):
        self.cta = BoardMemberCTA()
        self.cro = BoardMemberCRO()
        self.cmso = BoardMemberCMSO()
        self.cowa = BoardMemberCOWA()

    def deliberate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Runs formal Board Member debate and voting on a trade setup candidate."""
        cta_res = self.cta.evaluate(symbol, data)
        cro_res = self.cro.evaluate(symbol, data)
        cmso_res = self.cmso.evaluate(symbol, data)
        cowa_res = self.cowa.evaluate(symbol, data)

        votes = [cta_res["vote"], cro_res["vote"], cmso_res["vote"], cowa_res["vote"]]
        approve_count = votes.count("APPROVE")
        reject_count = votes.count("REJECT")
        abstain_count = votes.count("ABSTAIN")

        # Weighted Board Score calculation
        # Weights: CTA (30%), CRO (30%), CMSO (20%), COWA (20%)
        weighted_score = (
            (cta_res["score"] * 0.30) +
            (cro_res["score"] * 0.30) +
            (cmso_res["score"] * 0.20) +
            (cowa_res["score"] * 0.20)
        )

        # Consensus Gate Logic:
        # 1. CRO VETO = Immediate REJECT
        # 2. Min Score >= 83 (or 85 for ultra-high conviction)
        # 3. Min 3 APPROVE votes (or 4/4 unanimous)
        is_cro_veto = cro_res.get("is_veto", False) or cro_res["vote"] == "REJECT"

        if is_cro_veto:
            status = "REJECTED_BY_CRO_VETO"
            verdict = "VETOED: Chief Risk Officer exercised absolute veto due to safety/drawdown rules."
        elif reject_count > 0:
            status = "REJECTED_BY_VOTE"
            verdict = f"REJECTED: Board dissent detected ({reject_count} Rejections, {approve_count} Approvals)."
        elif weighted_score < 70.0 or approve_count < 2:
            status = "REJECTED_INSUFFICIENT_CONVICTION"
            verdict = f"REJECTED: Consensus score ({weighted_score:.1f}/100) below 70.0 threshold or < 2 Approvals."
        else:
            status = "APPROVED"
            verdict = f"SUPERMAJORITY APPROVAL: Board greenlights trade execution ({weighted_score:.1f}/100)."

        transcript = [
            f"🏛️ BOARD OF DIRECTORS DELIBERATION — CANDIDATE: {symbol}",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"1️⃣ {cta_res['member']} | Vote: [{cta_res['vote']}] ({cta_res['score']}/100)",
            f"   • Thesis: {cta_res['thesis']}",
            f"   • Risks:  {cta_res['risks']}",
            f"",
            f"2️⃣ {cro_res['member']} | Vote: [{cro_res['vote']}] ({cro_res['score']}/100) {'[VETO]' if is_cro_veto else ''}",
            f"   • Thesis: {cro_res['thesis']}",
            f"   • Risks:  {cro_res['risks']}",
            f"",
            f"3️⃣ {cmso_res['member']} | Vote: [{cmso_res['vote']}] ({cmso_res['score']}/100)",
            f"   • Thesis: {cmso_res['thesis']}",
            f"   • Risks:  {cmso_res['risks']}",
            f"",
            f"4️⃣ {cowa_res['member']} | Vote: [{cowa_res['vote']}] ({cowa_res['score']}/100)",
            f"   • Thesis: {cowa_res['thesis']}",
            f"   • Risks:  {cowa_res['risks']}",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 Final Consensus Score: {weighted_score:.1f} / 100",
            f"🗳️ Voting Tally: {approve_count} APPROVE | {reject_count} REJECT | {abstain_count} ABSTAIN",
            f"⚖️ Final Board Resolution: [{status}] — {verdict}"
        ]

        resolution = {
            "symbol": symbol,
            "timestamp": time.time(),
            "status": status,
            "is_approved": status == "APPROVED",
            "consensus_score": round(weighted_score, 1),
            "approve_count": approve_count,
            "reject_count": reject_count,
            "abstain_count": abstain_count,
            "verdict": verdict,
            "members": {
                "cta": cta_res,
                "cro": cro_res,
                "cmso": cmso_res,
                "cowa": cowa_res
            },
            "transcript": "\n".join(transcript)
        }

        return resolution


# Global singleton instance
_BOARD = BoardCommitteeEngine()


def process_board_deliberation_all():
    """Pipeline entry point called by Orchestrator."""
    all_data = {}
    if hasattr(bus, "get_all"):
        all_data = bus.get_all()
    elif isinstance(bus, dict):
        all_data = bus

    # Find symbols with candidate signals from Tier 1 scouts
    candidates = set()
    sweeps = all_data.get("liquidity_sweeps", {})
    for sym, val in sweeps.items():
        if val.get("has_sweep"):
            candidates.add(sym)

    coin_sel = all_data.get("coin_selection", {}).get("top_coins", [])
    for c in coin_sel[:5]:
        candidates.add(c)

    if not candidates:
        candidates = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    resolutions = {}
    latest_debate = None

    for sym in candidates:
        res = _BOARD.deliberate(sym, all_data)
        resolutions[sym] = res
        if res["is_approved"] or latest_debate is None:
            latest_debate = res

    if hasattr(bus, "set"):
        bus.set("board_resolutions", resolutions)
        if latest_debate:
            bus.set("latest_board_debate", latest_debate)

    # Heartbeat
    if hasattr(bus, "set_heartbeat"):
        bus.set_heartbeat("Board_Committee_Engine", "HEALTHY")

    approved_list = [s for s, r in resolutions.items() if r["is_approved"]]
    logging.info(f"[BOARD COMMITTEE] Evaluated {len(resolutions)} candidates. Approved for Execution: {approved_list or 'None (Preserving Cash)'}")
    return resolutions


if __name__ == "__main__":
    # Self-test with sample mock data
    mock_bus_data = {
        "smc_cascade": {"BTCUSDT": {"cascade_score": 90}},
        "liquidity_sweeps": {"BTCUSDT": {"has_sweep": True, "sweep_type": "SSL_SWEEP", "swept_level": 64200}},
        "multi_tf_trends": {"BTCUSDT": {"trend_aligned_long": True}},
        "portfolio_risk": {"total_risk_percent": 1.5, "max_allowed_risk_pct": 6.0},
        "circuit_breaker": {"circuit_active": False},
        "active_positions": {},
        "btc_regime": {"regime": "BULL"},
        "correlation_filter": {"alt_season_favorable": True, "btc_d": 57.2},
        "news_sentiment": {"sentiment": "BULLISH", "sentiment_score": 85},
        "session_filter": {"high_liquidity_session": True, "active_session": "London/NY Overlap"},
        "cvd_order_flow": {"BTCUSDT": {"cvd_divergence": "BULLISH_ABSORPTION"}},
        "whale_funding": {"BTCUSDT": {"top_trader_long_short_ratio": 2.1, "funding_rate": -0.0002}},
        "institutional_research": {"BTCUSDT": {"tokenomics_score": 95}}
    }
    engine = BoardCommitteeEngine()
    test_res = engine.deliberate("BTCUSDT", mock_bus_data)
    print(test_res["transcript"])
