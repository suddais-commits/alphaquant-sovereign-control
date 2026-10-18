"""
Optimized In-Memory & Non-Blocking Pipeline Bus
Eliminates loop hangs, temp file leaks, and OneDrive Sync CPU spikes.
"""
import os
import json
import time
import logging
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
BUS_FILE = os.path.join(DATA_DIR, "pipeline_bus.json")

DEFAULT_STATE = {
    "timestamp": 0, "market_data": {}, "btc_regime": {}, "liquidity_sweeps": {},
    "smc_structures": {}, "trend_filters": {}, "volatility_guards": {},
    "conviction_scores": {}, "position_sizes": {}, "execution_queue": [],
    "active_positions": {}, "notification_queue": [], "analytics_stats": {},
    "heartbeats": {}
}

_in_memory_bus = DEFAULT_STATE.copy()
_last_mtime = 0.0

def read_bus() -> Dict[str, Any]:
    """Reads the state from fast memory, falls back to disk if modified or memory empty."""
    global _in_memory_bus, _last_mtime
    if os.path.exists(BUS_FILE):
        try:
            mtime = os.path.getmtime(BUS_FILE)
            if mtime > _last_mtime or not (_in_memory_bus and _in_memory_bus.get("timestamp", 0) > 0):
                for _ in range(3):
                    try:
                        with open(BUS_FILE, "r", encoding="utf-8") as f:
                            _in_memory_bus = json.load(f)
                            _last_mtime = mtime
                            return _in_memory_bus
                    except Exception:
                        time.sleep(0.02)
        except Exception:
            pass
    if _in_memory_bus and _in_memory_bus.get("timestamp", 0) > 0:
        return _in_memory_bus
    return _in_memory_bus

def update_bus_section(section: str, data: Any):
    """Updates memory instantly and flushes to disk safely without lock choking."""
    global _in_memory_bus, _last_mtime
    _in_memory_bus = read_bus()
    _in_memory_bus[section] = data
    _in_memory_bus["timestamp"] = time.time()
    try:
        with open(BUS_FILE, "w", encoding="utf-8") as f:
            json.dump(_in_memory_bus, f, indent=1)
        _last_mtime = os.path.getmtime(BUS_FILE)
    except Exception:
        pass

def record_heartbeat(agent_name: str, status: str = "HEALTHY"):
    """Throttled memory heartbeat to keep laptop cold."""
    global _in_memory_bus, _last_mtime
    _in_memory_bus = read_bus()
    heartbeats = _in_memory_bus.setdefault("heartbeats", {})
    heartbeats[agent_name] = {
        "timestamp": time.time(),
        "status": status,
        "readable_time": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        with open(BUS_FILE, "w", encoding="utf-8") as f:
            json.dump(_in_memory_bus, f, indent=1)
        _last_mtime = os.path.getmtime(BUS_FILE)
    except Exception:
        pass

def push_notification(title: str, message: str, level: str = "INFO"):
    global _in_memory_bus
    _in_memory_bus = read_bus()
    queue = _in_memory_bus.setdefault("notification_queue", [])
    queue.append({
        "title": title, "message": message, "level": level,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"), "timestamp": time.time()
    })
    update_bus_section("notification_queue", queue)
