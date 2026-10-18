"""
Agent 18: Portfolio Risk Monitor
Single Responsibility:
- Reads all active positions from Pipeline Bus.
- Calculates total portfolio risk in $ and %.
- If total risk > 6% of balance → signals RISK_HIGH to block new entries.
- Also monitors max drawdown from peak equity.
- Writes portfolio_risk section to Pipeline Bus.
"""
import os
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_18_PortfolioRiskMonitor"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_18.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

MAX_RISK_PCT = 6.0          # Block new entries above 6% total portfolio risk
MAX_DRAWDOWN_PCT = 15.0     # Circuit breaker if drawdown > 15% from peak

# Track peak equity for drawdown calculation
_peak_equity = {"value": 0.0}


def calculate_portfolio_risk(bus: dict) -> dict:
    """
    Calculate total at-risk $ across all active positions.
    Risk per position = distance from entry to stop-loss × position size.
    """
    active_positions = bus.get("active_positions", {})
    analytics = bus.get("analytics_stats", {})
    wallet_balance = analytics.get("wallet_balance", 4.81)

    total_risk_usd = 0.0
    position_risks = {}

    for symbol, pos in active_positions.items():
        entry_price = pos.get("entry_price", 0)
        stop_loss = pos.get("stop_loss", 0)
        qty = pos.get("quantity", 0)
        direction = pos.get("direction", "LONG")

        if entry_price > 0 and stop_loss > 0 and qty > 0:
            if direction == "LONG":
                risk_per_unit = entry_price - stop_loss
            else:
                risk_per_unit = stop_loss - entry_price

            risk_usd = abs(risk_per_unit) * qty
            total_risk_usd += risk_usd
            position_risks[symbol] = round(risk_usd, 4)

    total_risk_pct = (total_risk_usd / wallet_balance * 100) if wallet_balance > 0 else 0.0

    # Drawdown calculation
    current_equity = wallet_balance
    if current_equity > _peak_equity["value"]:
        _peak_equity["value"] = current_equity

    peak = _peak_equity["value"]
    drawdown_pct = ((peak - current_equity) / peak * 100) if peak > 0 else 0.0

    # Risk status
    if total_risk_pct > MAX_RISK_PCT or drawdown_pct > MAX_DRAWDOWN_PCT:
        risk_status = "RISK_HIGH"
        new_entries_allowed = False
    elif total_risk_pct > MAX_RISK_PCT * 0.7:
        risk_status = "RISK_ELEVATED"
        new_entries_allowed = True  # Allow but with caution
    else:
        risk_status = "RISK_SAFE"
        new_entries_allowed = True

    return {
        "total_risk_usd": round(total_risk_usd, 4),
        "total_risk_pct": round(total_risk_pct, 2),
        "max_risk_pct": MAX_RISK_PCT,
        "drawdown_pct": round(drawdown_pct, 2),
        "peak_equity": round(peak, 4),
        "wallet_balance": round(wallet_balance, 4),
        "risk_status": risk_status,
        "new_entries_allowed": new_entries_allowed,
        "position_risks": position_risks,
        "active_position_count": len(active_positions)
    }


def process_portfolio_risk():
    bus = read_bus()
    risk_data = calculate_portfolio_risk(bus)

    update_bus_section("portfolio_risk", risk_data)
    record_heartbeat(AGENT_NAME, f"HEALTHY | {risk_data['risk_status']} | Risk: {risk_data['total_risk_pct']}%")
    logging.info(
        f"Portfolio Risk: {risk_data['risk_status']} | "
        f"Total Risk: ${risk_data['total_risk_usd']} ({risk_data['total_risk_pct']}%) | "
        f"Drawdown: {risk_data['drawdown_pct']}% | "
        f"New Entries: {'YES' if risk_data['new_entries_allowed'] else 'BLOCKED'}"
    )


def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_portfolio_risk()
        except Exception as e:
            logging.error(f"Error: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(10)

if __name__ == "__main__":
    main()
