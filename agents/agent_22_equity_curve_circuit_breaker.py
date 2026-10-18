"""
Agent 22: Equity Curve Circuit Breaker
Single Responsibility:
- Tracks running wins and losses from Trade Journal.
- If 3 CONSECUTIVE losses → auto-pause new entries for 2 hours.
- If 5 CONSECUTIVE wins → flag "HOT_STREAK" (allow slightly more aggressive sizing).
- Resets automatically after the pause window expires.
- Writes circuit_breaker section to Pipeline Bus.
"""
import os
import sys
import time
import logging
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat, push_notification

AGENT_NAME = "Agent_22_EquityCurveCircuitBreaker"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_22.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

CONSECUTIVE_LOSS_LIMIT = 3       # Pause after 3 consecutive losses
PAUSE_DURATION_SECONDS = 7200    # 2-hour cool-off after 3 losses
HOT_STREAK_THRESHOLD = 5         # 5 consecutive wins = hot streak

# Internal state
_pause_until = 0.0
_consecutive_losses = 0
_consecutive_wins = 0
_last_trade_count = 0


def analyze_trade_streak(bus: dict) -> dict:
    global _pause_until, _consecutive_losses, _consecutive_wins, _last_trade_count

    analytics = bus.get("analytics_stats", {})
    trade_history = analytics.get("trade_history", [])
    now = time.time()

    # Only re-analyze if new trades have been added
    current_trade_count = len(trade_history)
    if current_trade_count > _last_trade_count and trade_history:
        _last_trade_count = current_trade_count

        # Recalculate consecutive streak from the end of trade history
        _consecutive_losses = 0
        _consecutive_wins = 0

        for trade in reversed(trade_history[-10:]):  # Look at last 10 trades
            outcome = trade.get("outcome", "")
            if outcome == "WIN":
                if _consecutive_losses > 0:
                    break
                _consecutive_wins += 1
            elif outcome == "LOSS":
                if _consecutive_wins > 0:
                    break
                _consecutive_losses += 1
            else:
                break

        # Trigger circuit breaker
        if _consecutive_losses >= CONSECUTIVE_LOSS_LIMIT and _pause_until < now:
            _pause_until = now + PAUSE_DURATION_SECONDS
            pause_msg = (
                f"⚠️ <b>Circuit Breaker ACTIVATED</b>\n"
                f"3 consecutive losses detected.\n"
                f"New entries paused for 2 hours.\n"
                f"Resume at: {datetime.fromtimestamp(_pause_until, tz=timezone.utc).strftime('%H:%M UTC')}"
            )
            push_notification("CIRCUIT BREAKER", pause_msg, level="WARNING")
            logging.warning(f"CIRCUIT BREAKER ACTIVATED! 3 consecutive losses. Paused for 2 hours.")

    # Status
    is_paused = now < _pause_until
    time_remaining = max(0, _pause_until - now) / 60  # in minutes

    if is_paused:
        status = "CIRCUIT_BREAKER_ACTIVE"
    elif _consecutive_wins >= HOT_STREAK_THRESHOLD:
        status = "HOT_STREAK"
    elif _consecutive_losses == 2:
        status = "WARNING_1_LOSS_FROM_PAUSE"
    else:
        status = "NORMAL"

    return {
        "status": status,
        "circuit_breaker_active": is_paused,
        "new_entries_allowed": not is_paused,
        "consecutive_losses": _consecutive_losses,
        "consecutive_wins": _consecutive_wins,
        "pause_remaining_minutes": round(time_remaining, 1),
        "hot_streak": _consecutive_wins >= HOT_STREAK_THRESHOLD,
        "total_trades_tracked": current_trade_count
    }


def process_circuit_breaker():
    bus = read_bus()
    result = analyze_trade_streak(bus)

    update_bus_section("circuit_breaker", result)
    record_heartbeat(AGENT_NAME, f"HEALTHY | {result['status']}")
    logging.info(
        f"Circuit Breaker: {result['status']} | "
        f"Losses: {result['consecutive_losses']} | "
        f"Wins: {result['consecutive_wins']} | "
        f"Entries: {'ALLOWED' if result['new_entries_allowed'] else 'BLOCKED'}"
    )


def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_circuit_breaker()
        except Exception as e:
            logging.error(f"Error: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(15)

if __name__ == "__main__":
    main()
