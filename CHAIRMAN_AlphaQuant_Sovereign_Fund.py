"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   CHAIRMAN_AlphaQuant_Sovereign_Fund.py                                      ║
║   AlphaQuant Global Sovereign Fund Private Limited                           ║
║   ─────────────────────────────────────────────────────────────────────────  ║
║   Designation: Founder, Chairman & Chief Sovereign Allocator                 ║
║   Zimmedari : Poori fund management ka akela maalik.                         ║
║               Saare departmental CEOs se weighted metrics leta hai aur       ║
║               trades execute karne ka final order sign karta hai.            ║
║   Legacy    : Refactored from master_bot.py                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

REPORTING STRUCTURE:
  Chairman (this file)
    ├── CEO_Data_Intelligence        (Dept-1: Macro Intelligence)
    ├── CEO_SMC_Strategy_Cascade     (Dept-2: SMC & ICT Strategy)
    ├── CEO_Whale_Order_Flow         (Dept-3: Order Flow & Whale)
    └── CEO_Risk_Management_CRO      (Dept-4: Risk Control)

IMPORTANT: This file is the main entry point for the AlphaQuant v2 system.
           It delegates to the four departmental CEOs via pipeline_bus and
           makes the final trade execution decision.

NOTE: The original master_bot.py remains untouched in the root directory.
      This is the new v2 Chairman that will replace it once all departments
      are fully implemented (all STUB agents replaced with live logic).
"""
import os
import sys
import time
import logging

# --- Path Setup ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

CHAIRMAN_NAME = "CHAIRMAN_AlphaQuant_Sovereign_Fund"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "chairman.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ─────────────────────────────────────────────────────────────────────────────
# BOARD CONFIGURATION (read from config.yaml via config.py)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from config import CONFIG
    SCORE_THRESHOLD = CONFIG.system.score_threshold       # 70.0
    MIN_RR_RATIO    = CONFIG.setup.min_rr_ratio           # 3.0
    TP1_R           = CONFIG.execution.tp1_r              # 3.0
    LIVE_TRADING    = CONFIG.system.live_trading_enabled  # False (paper only)
except Exception as e:
    logging.warning(f"Config load failed: {e}. Using hardcoded defaults.")
    SCORE_THRESHOLD = 70.0
    MIN_RR_RATIO    = 3.0
    TP1_R           = 3.0
    LIVE_TRADING    = False

# ─────────────────────────────────────────────────────────────────────────────
# DEPT WEIGHTS — How much each CEO's score matters in final decision
# (Adjust as evidence from paper trading accumulates)
# ─────────────────────────────────────────────────────────────────────────────
DEPT_WEIGHTS = {
    "dept1_macro":    0.20,   # Macro Intelligence
    "dept2_smc":      0.35,   # SMC & ICT Strategy
    "dept3_whale":    0.25,   # Order Flow & Whale
    "dept4_risk":     0.20,   # Risk Control (acts as veto too)
}


def aggregate_dept_scores(bus: dict) -> dict:
    """
    Reads CEO-level score summaries from pipeline_bus and computes
    the Chairman's weighted conviction score.

    Each departmental CEO publishes a dict to bus under their key:
      dept1_macro_score, dept2_smc_score, dept3_whale_score, dept4_risk_score

    Returns: {
        'conviction_score': float (0-100),
        'risk_approved': bool,
        'direction': 'LONG' | 'SHORT' | 'FLAT',
        'dept_scores': dict
    }
    """
    dept_scores = {
        "dept1_macro":  bus.get("dept1_macro_score",  {}).get("score", 0.0),
        "dept2_smc":    bus.get("dept2_smc_score",    {}).get("score", 0.0),
        "dept3_whale":  bus.get("dept3_whale_score",  {}).get("score", 0.0),
        "dept4_risk":   bus.get("dept4_risk_score",   {}).get("score", 100.0),  # default ALLOW
    }

    # Weighted conviction score
    conviction = sum(
        dept_scores[dept] * weight
        for dept, weight in DEPT_WEIGHTS.items()
    )

    # Risk department can VETO (if risk score < 30, no trade regardless)
    risk_approved = dept_scores["dept4_risk"] >= 30.0

    # Direction: majority of depts must agree
    directions = {
        "dept2_smc":   bus.get("dept2_smc_score",   {}).get("direction", "FLAT"),
        "dept3_whale": bus.get("dept3_whale_score",  {}).get("direction", "FLAT"),
    }
    long_votes  = sum(1 for d in directions.values() if d == "LONG")
    short_votes = sum(1 for d in directions.values() if d == "SHORT")

    if long_votes > short_votes:
        direction = "LONG"
    elif short_votes > long_votes:
        direction = "SHORT"
    else:
        direction = "FLAT"

    return {
        "conviction_score": round(conviction, 2),
        "risk_approved": risk_approved,
        "direction": direction,
        "dept_scores": dept_scores,
    }


def chairman_decision_cycle():
    """Main decision loop: read bus → aggregate → decide → sign order."""
    bus = read_bus()
    market_data = bus.get("market_data", {})

    if not market_data:
        record_heartbeat(CHAIRMAN_NAME, "IDLE_NO_MARKET_DATA")
        return

    summary = aggregate_dept_scores(bus)
    conviction = summary["conviction_score"]
    direction  = summary["direction"]
    risk_ok    = summary["risk_approved"]

    log_msg = (
        f"Conviction={conviction:.1f} | Dir={direction} | "
        f"RiskApproved={risk_ok} | Threshold={SCORE_THRESHOLD}"
    )
    logging.info(f"[CHAIRMAN BOARD REVIEW] {log_msg}")

    # ── FINAL TRADE AUTHORIZATION ─────────────────────────────────────
    if conviction >= SCORE_THRESHOLD and direction != "FLAT" and risk_ok:
        if not LIVE_TRADING:
            logging.info(
                f"[CHAIRMAN SIGNS] PAPER ORDER: {direction} | "
                f"Score={conviction:.1f} | TP1={TP1_R}R | RR>={MIN_RR_RATIO}"
            )
            update_bus_section("chairman_signal", {
                "direction": direction,
                "conviction_score": conviction,
                "tp1_r": TP1_R,
                "min_rr": MIN_RR_RATIO,
                "status": "PAPER_AUTHORIZED",
                "timestamp": time.time(),
            })
        else:
            logging.warning(
                "[CHAIRMAN] LIVE_TRADING=True — "
                "live order routing NOT YET IMPLEMENTED in v2."
            )
    else:
        reasons = []
        if conviction < SCORE_THRESHOLD:
            reasons.append(f"conviction {conviction:.1f} < {SCORE_THRESHOLD}")
        if direction == "FLAT":
            reasons.append("direction=FLAT (no consensus)")
        if not risk_ok:
            reasons.append("risk dept VETO")
        logging.info(f"[CHAIRMAN PASSES] No trade. Reasons: {'; '.join(reasons)}")

    record_heartbeat(CHAIRMAN_NAME, f"SCORE={conviction:.1f}_DIR={direction}")


def main():
    logging.info(
        f"\n{'='*60}\n"
        f"  {CHAIRMAN_NAME}\n"
        f"  AlphaQuant Global Sovereign Fund Private Limited\n"
        f"  Score Threshold : {SCORE_THRESHOLD}\n"
        f"  Min R:R Ratio   : {MIN_RR_RATIO}\n"
        f"  TP1 Target      : {TP1_R}R\n"
        f"  Live Trading    : {LIVE_TRADING}\n"
        f"{'='*60}"
    )
    while True:
        try:
            chairman_decision_cycle()
        except Exception as e:
            logging.error(f"Chairman loop error: {e}")
            record_heartbeat(CHAIRMAN_NAME, f"ERROR: {e}")
        time.sleep(60)  # Board meeting every 60 seconds


if __name__ == "__main__":
    main()
