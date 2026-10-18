"""
Agent 19: Trading Session Time Filter
Single Responsibility:
- Detects which trading session is currently active (Asia / London / New York).
- London/NY overlap (13:00–17:00 UTC) = BEST liquidity → allow entries.
- London session (08:00–13:00 UTC) = GOOD → allow entries.
- NY session (13:00–21:00 UTC) = GOOD → allow entries.
- Asia session (01:00–08:00 UTC) = MEDIUM → allow entries only for Asia coins.
- Dead zone (21:00–01:00 UTC) = LOW LIQUIDITY → block new entries.
- Writes session_filter section to Pipeline Bus.
"""
import os
import sys
import time
import logging
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import update_bus_section, record_heartbeat

AGENT_NAME = "Agent_19_SessionTimeFilter"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_19.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# UTC session boundaries (hour, minute)
SESSIONS = {
    "DEAD_ZONE":    [(21, 0), (1, 0)],     # 21:00 - 01:00 UTC (block)
    "ASIA":         [(1, 0),  (8, 0)],     # 01:00 - 08:00 UTC
    "LONDON":       [(8, 0),  (13, 0)],    # 08:00 - 13:00 UTC (good)
    "LONDON_NY":    [(13, 0), (17, 0)],    # 13:00 - 17:00 UTC (BEST)
    "NEW_YORK":     [(17, 0), (21, 0)],    # 17:00 - 21:00 UTC (good)
}

# Liquidity scores per session
SESSION_QUALITY = {
    "LONDON_NY":    "PREMIUM",    # Allow all entries
    "LONDON":       "GOOD",       # Allow all entries
    "NEW_YORK":     "GOOD",       # Allow all entries
    "ASIA":         "MEDIUM",     # Allow with caution (only high-conviction)
    "DEAD_ZONE":    "LOW",        # Block new entries
}

MIN_SCORE_DEAD_ZONE = 92.0  # Only take trades in dead zone with very high conviction


def get_current_session() -> str:
    """Detect current UTC session."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    minute = now.minute
    current_minutes = hour * 60 + minute

    # Check each session
    if 21 * 60 <= current_minutes or current_minutes < 1 * 60:
        return "DEAD_ZONE"
    elif 1 * 60 <= current_minutes < 8 * 60:
        return "ASIA"
    elif 8 * 60 <= current_minutes < 13 * 60:
        return "LONDON"
    elif 13 * 60 <= current_minutes < 17 * 60:
        return "LONDON_NY"
    elif 17 * 60 <= current_minutes < 21 * 60:
        return "NEW_YORK"
    return "UNKNOWN"


def process_session_filter():
    now_utc = datetime.now(timezone.utc)
    session = get_current_session()
    quality = SESSION_QUALITY.get(session, "MEDIUM")

    entries_allowed = quality in ("PREMIUM", "GOOD")
    
    # In Asia and Dead Zone, require higher conviction score
    min_score_override = None
    if session == "DEAD_ZONE":
        entries_allowed = False
        min_score_override = MIN_SCORE_DEAD_ZONE
    elif session == "ASIA":
        min_score_override = 87.0  # Higher bar during Asia

    result = {
        "current_session": session,
        "session_quality": quality,
        "utc_hour": now_utc.hour,
        "utc_minute": now_utc.minute,
        "entries_allowed": entries_allowed,
        "min_score_override": min_score_override,
        "best_session": session == "LONDON_NY",
        "note": {
            "LONDON_NY": "🔥 Peak London/NY Overlap — Maximum Liquidity",
            "LONDON":    "✅ London Session — Good Liquidity",
            "NEW_YORK":  "✅ New York Session — Good Liquidity",
            "ASIA":      "⚠️ Asia Session — Medium Liquidity, Higher Score Required",
            "DEAD_ZONE": "🔴 Dead Zone — Low Liquidity, New Entries Blocked"
        }.get(session, "")
    }

    update_bus_section("session_filter", result)
    record_heartbeat(AGENT_NAME, f"HEALTHY | {session} | Quality: {quality}")
    logging.info(f"Session: {session} | Quality: {quality} | Entries Allowed: {entries_allowed}")


def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_session_filter()
        except Exception as e:
            logging.error(f"Error: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(60)  # Update every minute

if __name__ == "__main__":
    main()
