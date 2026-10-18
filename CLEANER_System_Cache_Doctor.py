"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   CLEANER_System_Cache_Doctor.py                                              ║
║   AlphaQuant Global Sovereign Fund Private Limited                            ║
║   ─────────────────────────────────────────────────────────────────────────   ║
║   Designation : The Office Boy / System Safai Wala                            ║
║   Zimmedari   : Har loop cycle ke baad:                                       ║
║                 1. tmp_*.json files delete karta hai                          ║
║                 2. pipeline_bus stale entries refresh karta hai               ║
║                 3. Log files ko 10MB se zyada hone par rotate karta hai       ║
║                 4. Python __pycache__ dirs clean karta hai                    ║
║                 Taake aapka laptop 24 ghante thanda chal sake.                ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
import os
import sys
import time
import glob
import shutil
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

CLEANER_NAME = "CLEANER_System_Cache_Doctor"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "cleaner.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
CLEAN_INTERVAL_SEC  = 300          # Run every 5 minutes
MAX_LOG_SIZE_BYTES  = 10_000_000   # 10 MB — rotate logs above this
MAX_LOG_LINES       = 5_000        # Keep last 5000 lines when rotating
TMP_PATTERNS        = [            # Glob patterns for temp files to delete
    "tmp_*.json",
    "*.tmp",
    ".~lock.*",
]
PYCACHE_ENABLED     = True         # Delete __pycache__ dirs
BUS_STALE_SECONDS   = 600          # Bus entries older than 10 min = stale


def clean_tmp_files() -> int:
    """Delete tmp_*.json and *.tmp files from project root."""
    deleted = 0
    for pattern in TMP_PATTERNS:
        for f in glob.glob(os.path.join(BASE_DIR, pattern)):
            try:
                os.remove(f)
                deleted += 1
                logging.debug(f"Deleted tmp: {f}")
            except Exception as e:
                logging.warning(f"Cannot delete {f}: {e}")
    return deleted


def clean_pycache() -> int:
    """Remove __pycache__ directories to free disk space."""
    if not PYCACHE_ENABLED:
        return 0
    removed = 0
    for root, dirs, _ in os.walk(BASE_DIR):
        for d in dirs:
            if d == "__pycache__":
                path = os.path.join(root, d)
                try:
                    shutil.rmtree(path)
                    removed += 1
                    logging.debug(f"Removed pycache: {path}")
                except Exception as e:
                    logging.warning(f"Cannot remove pycache {path}: {e}")
    return removed


def rotate_large_logs() -> int:
    """Truncate log files that exceed MAX_LOG_SIZE_BYTES, keeping last MAX_LOG_LINES."""
    rotated = 0
    for log_file in glob.glob(os.path.join(LOG_DIR, "*.log")):
        # Don't rotate our own log while writing to it
        if "cleaner" in os.path.basename(log_file):
            continue
        try:
            size = os.path.getsize(log_file)
            if size > MAX_LOG_SIZE_BYTES:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                keep = lines[-MAX_LOG_LINES:]
                with open(log_file, "w", encoding="utf-8") as f:
                    f.write(f"[CLEANER] Log rotated at {time.strftime('%Y-%m-%d %H:%M:%S')} "
                            f"— kept last {MAX_LOG_LINES} lines of {len(lines)} total.\n")
                    f.writelines(keep)
                rotated += 1
                logging.info(f"Rotated log: {os.path.basename(log_file)} ({size/1e6:.1f}MB → kept {MAX_LOG_LINES} lines)")
        except Exception as e:
            logging.warning(f"Log rotation error for {log_file}: {e}")
    return rotated


def clean_stale_bus_entries():
    """
    Remove stale entries from pipeline_bus that haven't been updated
    in BUS_STALE_SECONDS. Prevents stale data from influencing decisions.
    """
    try:
        from pipeline_bus import read_bus
        import time as t
        now = t.time()
        bus = read_bus()

        # Check heartbeats section for stale agents
        heartbeats = bus.get("heartbeats", {})
        stale_agents = []
        for agent_name, hb in heartbeats.items():
            last_seen = hb.get("timestamp", 0)
            if isinstance(last_seen, (int, float)) and (now - last_seen) > BUS_STALE_SECONDS:
                stale_agents.append(agent_name)

        if stale_agents:
            for agent in stale_agents:
                logging.info(f"Stale agent heartbeat detected: {agent}")
        # (We log stale agents but don't remove their data — other agents may need it)
    except Exception as e:
        logging.debug(f"Bus cleanup skipped: {e}")


def run_cleaning_cycle():
    """Execute one full cleaning cycle."""
    start = time.time()

    tmp_deleted   = clean_tmp_files()
    cache_removed = clean_pycache()
    logs_rotated  = rotate_large_logs()
    clean_stale_bus_entries()

    elapsed = time.time() - start
    summary = (
        f"Cycle done in {elapsed:.2f}s | "
        f"tmp_deleted={tmp_deleted} | "
        f"pycache_removed={cache_removed} | "
        f"logs_rotated={logs_rotated}"
    )
    logging.info(f"[CLEANER] {summary}")
    return summary


def main():
    logging.info(f"{CLEANER_NAME} started. Interval={CLEAN_INTERVAL_SEC}s.")
    print(f"[{CLEANER_NAME}] Running every {CLEAN_INTERVAL_SEC}s. Logs -> {LOG_DIR}")
    while True:
        try:
            summary = run_cleaning_cycle()
            print(f"[{CLEANER_NAME}] {summary}")
        except Exception as e:
            logging.error(f"Cleaner error: {e}")
        time.sleep(CLEAN_INTERVAL_SEC)


if __name__ == "__main__":
    main()
