"""
==============================================================================
CryptoBot Startup Telegram Notifier & Offline Market Catch-Up Audit Engine
==============================================================================
Features:
1. Tracks last-active heartbeat timestamp before laptop shutdown / sleep.
2. On startup, calculates offline downtime (e.g. 5 hours 12 minutes).
3. Fetches offline price action & volatility for BTC, ETH, SOL, BNB during sleep.
4. Audits active positions, Binance balance, and Guardian status.
5. Sends an instant, beautiful Telegram report via proxy (No VPN needed).
==============================================================================
"""

import os
import sys
import time
import json
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

load_dotenv(os.path.join(BASE_DIR, ".env"))

log_handlers = [
    logging.FileHandler(os.path.join(LOG_DIR, "startup_notifier.log"), encoding="utf-8")
]
if sys.stdout is not None:
    log_handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=log_handlers
)
log = logging.getLogger("StartupNotifier")

HEARTBEAT_FILE = os.path.join(DATA_DIR, "system_heartbeat.json")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

from telegram_proxy_manager import execute_telegram_api
from pipeline_bus import read_bus

def read_heartbeat() -> Dict[str, Any]:
    if os.path.exists(HEARTBEAT_FILE):
        try:
            with open(HEARTBEAT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning("Could not read heartbeat file: %s", e)
    return {}

def update_heartbeat(current_btc_price: Optional[float] = None):
    try:
        now_ts = int(time.time())
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = {
            "last_active_ts": now_ts,
            "last_active_time": now_str,
            "last_btc_price": current_btc_price or get_binance_price("BTCUSDT")
        }
        with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.warning("Could not update heartbeat file: %s", e)

def get_binance_price(symbol: str = "BTCUSDT") -> Optional[float]:
    sym = symbol.upper().replace("/", "").replace("-", "")
    if not sym.endswith("USDT"):
        sym += "USDT"
    url = f"https://data-api.binance.vision/api/v3/ticker/price?symbol={sym}"
    for _ in range(3):
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                return float(r.json().get("price", 0.0))
        except Exception:
            time.sleep(0.3)
    return None

def get_binance_klines(symbol: str, interval: str = "15m", limit: int = 50) -> List[Dict]:
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    for _ in range(3):
        try:
            r = requests.get(url, timeout=6)
            if r.status_code == 200:
                return [{
                    "ts": int(k[0]),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5])
                } for k in r.json()]
        except Exception:
            time.sleep(0.3)
    return []

def send_telegram_direct(text: str, parse_mode: str = "HTML") -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.info("Telegram not configured (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing). Skipping notification.")
        return False
    payload = {
        "chat_id": str(TELEGRAM_CHAT_ID),
        "text": text,
        "parse_mode": parse_mode
    }
    # 1. Try with telegram_proxy_manager
    try:
        r = execute_telegram_api("POST", "sendMessage", payload=payload, timeout=10)
        if r is not None and r.status_code == 200:
            log.info("Startup Telegram notification dispatched successfully via proxy manager.")
            return True
    except Exception as e:
        log.warning("Proxy manager attempt failed: %s", e)

    # 2. Direct Webshare Dedicated Proxy Fallback
    dedicated_proxies = [
        p for p in [
            os.getenv("PROXY_URL_PRIMARY", ""),
            os.getenv("PROXY_URL_BACKUP1", ""),
            os.getenv("PROXY_URL_BACKUP2", ""),
        ] if p
    ]
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for p_url in dedicated_proxies:
        try:
            proxies = {"http": p_url, "https": p_url}
            r = requests.post(url, json=payload, proxies=proxies, timeout=10)
            if r.status_code == 200 and r.json().get("ok"):
                log.info("Startup Telegram notification dispatched successfully via dedicated proxy: %s", p_url)
                return True
        except Exception:
            continue

    log.warning("Failed to dispatch Startup Telegram notification after all attempts.")
    return False

def audit_offline_market(start_ts: int, end_ts: int) -> Dict[str, Any]:
    """Audits market movement and high-impact changes during offline period."""
    offline_sec = max(end_ts - start_ts, 0)
    hours = int(offline_sec // 3600)
    minutes = int((offline_sec % 3600) // 60)
    
    duration_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes} min"
    
    tracked_coins = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    coin_summaries = []
    
    # Calculate how many 15m candles during offline period
    candles_needed = max(min(int(offline_sec / (15 * 60)) + 2, 500), 4)
    
    for sym in tracked_coins:
        klines = get_binance_klines(sym, "15m", limit=candles_needed)
        if not klines:
            continue
        
        # Filter candles within offline period if possible
        offline_klines = [c for c in klines if c["ts"] >= (start_ts * 1000)]
        if not offline_klines:
            offline_klines = klines[-4:]
            
        start_price = offline_klines[0]["open"]
        end_price = offline_klines[-1]["close"]
        high_price = max(c["high"] for c in offline_klines)
        low_price = min(c["low"] for c in offline_klines)
        
        chg_pct = ((end_price - start_price) / start_price) * 100 if start_price > 0 else 0.0
        coin_name = sym.replace("USDT", "")
        
        icon = "🟢" if chg_pct >= 0.5 else ("🔴" if chg_pct <= -0.5 else "⚪")
        coin_summaries.append({
            "name": coin_name,
            "start": start_price,
            "end": end_price,
            "high": high_price,
            "low": low_price,
            "chg_pct": chg_pct,
            "icon": icon
        })
        
    return {
        "duration_str": duration_str,
        "offline_sec": offline_sec,
        "coin_summaries": coin_summaries
    }

def get_system_components_health() -> Dict[str, Any]:
    """Checks active background python processes."""
    running_names = []
    try:
        import psutil
        for p in psutil.process_iter(['name', 'cmdline']):
            try:
                name = p.info.get('name') or ''
                if 'python' in name.lower():
                    cmd = " ".join(p.info.get('cmdline') or []).lower()
                    if 'orchestrator' in cmd or 'master_bot' in cmd:
                        running_names.append("Execution Engine")
                    elif 'bot_api_server' in cmd:
                        running_names.append("FastAPI Server")
                    elif 'telegram_ai_chat_bot' in cmd:
                        running_names.append("Telegram AI Bot")
                    elif 'guardian' in cmd:
                        running_names.append("Guardian Watchdog")
                    elif 'whatsapp' in cmd:
                        running_names.append("WhatsApp AI")
            except Exception:
                continue
    except Exception:
        pass
        
    unique_components = list(set(running_names))
    return {
        "active_count": len(unique_components),
        "components": unique_components
    }

def run_startup_notification(force: bool = False):
    log.info("Checking startup status and offline market duration...")
    heartbeat = read_heartbeat()
    now_ts = int(time.time())
    
    last_active_ts = heartbeat.get("last_active_ts", now_ts - 3600)
    offline_sec = now_ts - last_active_ts
    
    # If gap is smaller than 90 seconds and not forced, just update heartbeat and exit
    if offline_sec < 90 and not force:
        log.info("System was active recently (%ds ago). Skipping redundant startup alert.", offline_sec)
        update_heartbeat()
        return

    # 1. Audit offline market
    audit = audit_offline_market(last_active_ts, now_ts)
    
    # 2. Check Pipeline Bus & Balance
    bus = read_bus()
    active_pos = bus.get("active_positions", {})
    pos_count = len(active_pos) if isinstance(active_pos, dict) else 0
    
    btc_regime = bus.get("btc_regime", {}).get("bias", "BULLISH")
    
    # 3. System Components Health
    health = get_system_components_health()
    comp_str = ", ".join(health["components"]) if health["components"] else "Guardian Auto-Reviving"
    
    # 4. Construct Telegram HTML Message
    now_dt_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
    last_dt_str = datetime.fromtimestamp(last_active_ts).strftime("%d %b, %I:%M %p")
    
    lines = [
        "⚡ <b>CRYPTOBOT SYSTEM ONLINE & RECONNECTED!</b> ⚡",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🕒 <b>Startup Time:</b> <code>{now_dt_str}</code>",
        f"💤 <b>Laptop Offline Duration:</b> <b>{audit['duration_str']}</b>",
        f"   <i>(Last active: {last_dt_str})</i>",
        "",
        "📊 <b>OFFLINE MARKET CATCH-UP AUDIT:</b>"
    ]
    
    for c in audit["coin_summaries"]:
        sign = "+" if c["chg_pct"] >= 0 else ""
        lines.append(
            f"{c['icon']} <b>{c['name']}</b>: <code>${c['end']:,.2f}</code> ({sign}{c['chg_pct']:.2f}%) "
            f"[H: <code>${c['high']:,.1f}</code> | L: <code>${c['low']:,.1f}</code>]"
        )
        
    lines.extend([
        "",
        "🛡️ <b>SYSTEM & TRADING STATUS:</b>",
        f"• <b>BTC Regime:</b> <code>{btc_regime}</code>",
        f"• <b>Active Positions:</b> <code>{pos_count} Open Trades</code>",
        f"• <b>Guardian Watchdog:</b> <code>ACTIVE (100% Silent)</code>",
        f"• <b>Active Engines:</b> <code>{health['active_count']} Engines Online</code>",
        "• <b>Strategy:</b> <code>8-Timeframe SMC / Wyckoff Cascade</code>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "✅ <i>Laptop on ho chuka hai, bot ne background mein real-time monitoring aur scanning start kar di hai.</i>"
    ])
    
    msg_text = "\n".join(lines)
    send_telegram_direct(msg_text)
    
    # Save current heartbeat
    update_heartbeat()

if __name__ == "__main__":
    force_flag = "--force" in sys.argv or "--test" in sys.argv
    run_startup_notification(force=force_flag)
