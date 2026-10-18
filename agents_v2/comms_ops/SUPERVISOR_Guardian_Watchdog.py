"""
CryptoBot Self-Healing System Guardian
======================================
Automatically monitors all 4 core CryptoBot engines:
1. master_bot.py (Live Scanner & Execution Engine)
2. bot_api_server.py (FastAPI Local Backend - Port 8000)
3. telegram_ai_chat_bot.py (2-Way Telegram AI Bot)
4. whatsapp_ai_chat_bot.py (2-Way WhatsApp AI Engine - Port 8001)

If ANY window or process is accidentally closed or killed,
the Guardian automatically revives it immediately!
"""

import os
import sys
import time
import json
import logging
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "guardian.log")

handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
try:
    if sys.stdout is not None and hasattr(sys.stdout, "write"):
        sys.stdout.write("")
        handlers.append(logging.StreamHandler(sys.stdout))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=handlers
)
log = logging.getLogger("Guardian")

VENV_PYTHONW = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")
VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
RUNNER_EXE = VENV_PYTHONW if os.path.exists(VENV_PYTHONW) else (VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable)
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
PROCESS_FLAGS = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP

COMPONENTS = [
    {
        "name": "Live SMC/ICT Master Scanner (master_bot.py)",
        "script": "master_bot.py",
        "log_file": "bot_log.txt"
    },
    {
        "name": "12-Agent Pipeline (orchestrator_12_agents.py)",
        "script": "orchestrator_12_agents.py",
        "log_file": "orchestrator.log"
    },
    {
        "name": "FastAPI Server (bot_api_server.py)",
        "script": "bot_api_server.py",
        "log_file": "bot_api_server.log"
    },
    {
        "name": "Telegram AI Bot (telegram_ai_chat_bot.py)",
        "script": "telegram_ai_chat_bot.py",
        "log_file": "telegram_bot.log"
    },
    {
        "name": "WhatsApp AI Engine (whatsapp_ai_chat_bot.py)",
        "script": "whatsapp_ai_chat_bot.py",
        "log_file": "whatsapp_bot.log"
    },
    {
        "name": "On-Chain Coin Selector (agent_13_onchain_coin_selector.py)",
        "script": "agents/agent_13_onchain_coin_selector.py",
        "log_file": "agent_13.log"
    }
]

# How often (in guardian cycles) to update MASTER_STATE.md (60s cycle * 10 = 10 min)
MASTER_STATE_UPDATE_EVERY_N_CYCLES = 10
_cycle_counter = 0

def update_master_state_silent():
    """Silently refreshes MASTER_STATE.md with live pipeline data in-process (0 flashing windows)."""
    try:
        if os.path.exists(os.path.join(BASE_DIR, "update_master_state.py")):
            import update_master_state
            update_master_state.sync_master_state()
            log.info("[MASTER_STATE] MASTER_STATE.md auto-updated in-process.")
    except Exception as e:
        log.debug("[MASTER_STATE] Could not update MASTER_STATE.md: %s", e)

def get_running_python_scripts() -> list:
    """Returns all running python command lines using native psutil (0% CPU, instant)."""
    try:
        import psutil
        cmdlines = []
        for p in psutil.process_iter(['name', 'cmdline']):
            try:
                name = p.info.get('name') or ''
                if 'python' in name.lower():
                    cmd = p.info.get('cmdline') or []
                    cmdlines.append(" ".join(cmd).lower())
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return cmdlines
    except Exception as e:
        log.warning("Guardian psutil process check error: %s", e)
        return []

def check_and_revive_all():
    """Checks all 4 components and restarts any that are missing in 100% silent background mode."""
    running_cmds = get_running_python_scripts()
    if not running_cmds:
        time.sleep(2)
        running_cmds = get_running_python_scripts()

    combined_running_text = " ".join(running_cmds)
    
    revived_count = 0
    for comp in COMPONENTS:
        script_key = comp["script"].lower()
        if script_key in combined_running_text:
            log.debug("[OK] %s is active in background.", comp["name"])
        else:
            log.warning("[ALERT] %s is NOT running! Silently auto-reviving in background...", comp["name"])
            try:
                script_path = os.path.join(BASE_DIR, comp["script"])
                cmd = [RUNNER_EXE, "-u", script_path]
                log_path = os.path.join(LOG_DIR, comp.get("log_file", "component.log"))
                out_f = open(log_path, "a", encoding="utf-8")
                subprocess.Popen(
                    cmd,
                    cwd=BASE_DIR,
                    creationflags=PROCESS_FLAGS,
                    stdout=out_f,
                    stderr=subprocess.STDOUT
                )
                revived_count += 1
                time.sleep(2)
            except Exception as launch_err:
                log.error("Failed to revive %s: %s", comp["name"], launch_err)

    if revived_count == 0:
        log.info("[HEALTH CHECK] All 4 CryptoBot systems are 100%% healthy and running silently.")
    else:
        log.info("[HEALTH CHECK] Relaunched %d missing components silently in background.", revived_count)

def prevent_windows_sleep():
    """Instructs Windows Kernel to never suspend CPU / Network when locked or screen off."""
    try:
        if sys.platform == "win32":
            import ctypes
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ES_AWAYMODE_REQUIRED = 0x00000040
            flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
            log.debug("[POWER] Windows 24/7 Awake Lock active.")
    except Exception as e:
        log.warning("[POWER] Could not set Windows execution state: %s", e)

def run_daemon(interval_seconds: int = 60):
    """Runs guardian loop indefinitely."""
    global _cycle_counter
    log.info("CryptoBot Self-Healing Guardian started (Monitoring every %d seconds)...", interval_seconds)
    prevent_windows_sleep()
    
    # Trigger Startup Telegram Notification on first boot/guardian start
    try:
        import startup_telegram_notifier
        startup_telegram_notifier.run_startup_notification()
        log.info("[STARTUP] Startup Telegram notification check completed.")
    except Exception as start_notify_err:
        log.warning("[STARTUP] Startup notification error: %s", start_notify_err)

    while True:
        try:
            prevent_windows_sleep()
            check_and_revive_all()
            _cycle_counter += 1
            
            # Continuously maintain heartbeat so shutdown/sleep downtime is precisely tracked
            try:
                import startup_telegram_notifier
                startup_telegram_notifier.update_heartbeat()
            except Exception:
                pass

            # Update MASTER_STATE.md every N cycles (default: every 10 minutes)
            if _cycle_counter % MASTER_STATE_UPDATE_EVERY_N_CYCLES == 0:
                update_master_state_silent()
        except Exception as loop_err:
            log.error("Guardian loop error: %s", loop_err)
        time.sleep(interval_seconds)

def acquire_single_instance_lock():
    lock_file = os.path.join(LOG_DIR, "guardian.lock")
    try:
        if sys.platform == "win32":
            import msvcrt
            f = open(lock_file, "w")
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return f
    except Exception:
        log.warning("Another instance of Guardian is already running. Exiting duplicate.")
        sys.exit(0)
    return None

if __name__ == "__main__":
    try:
        _lock = acquire_single_instance_lock()
        if "--check" in sys.argv:
            check_and_revive_all()
        else:
            # Default daemon interval: 60 seconds (1 minute check)
            run_daemon(interval_seconds=60)
    except Exception as fatal_err:
        log.critical("Fatal Guardian error: %s", fatal_err, exc_info=True)


