"""
Agent 11: Multi-Channel Notification Dispatcher
Single Responsibility:
- Reads pending alerts from the Notification Queue
- Dispatches instant alerts to Telegram & WhatsApp
- Anti-Spam Message Hash Deduplication: Prevents sending identical messages multiple times
- Flushes the queue and maintains broadcast delivery logs
"""
import os
import sys
import time
import hashlib
import logging
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat
from proxy_manager import get_proxy

AGENT_NAME = "Agent_11_NotificationDispatcher"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_11.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

from telegram_reliability_wrapper import TelegramReliabilityWrapper
_tg_wrapper = TelegramReliabilityWrapper(bot_token=TELEGRAM_TOKEN, chat_id=TELEGRAM_CHAT_ID)

# Deduplication cache: msg_hash -> sent_timestamp (15-minute suppression of duplicate texts)
_sent_message_hashes = {}
DEDUP_WINDOW_SEC = 900 # 15 minutes

def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.info(f"[SIMULATED TG BROADCAST]: {message[:80]}...")
        return True

    return _tg_wrapper.send_message_sync(message, parse_mode="HTML")

def send_whatsapp(message: str) -> bool:
    # Send to WhatsApp local backend webhook if running on 8001
    try:
        url = "http://127.0.0.1:8001/send_alert"
        requests.post(url, json={"text": message}, timeout=3)
        return True
    except Exception:
        return False

def process_notifications():
    global _sent_message_hashes
    bus = read_bus()
    queue = bus.get("notification_queue", [])
    if not queue:
        record_heartbeat(AGENT_NAME, "IDLE_QUEUE_EMPTY")
        return

    now = time.time()
    # Clean old hashes older than 15 mins
    _sent_message_hashes = {h: t for h, t in _sent_message_hashes.items() if now - t < DEDUP_WINDOW_SEC}

    delivered_count = 0
    remaining_queue = []

    for item in queue:
        msg = item.get("message", "")
        if msg:
            # Check hash to prevent repetitive spamming
            m_hash = hashlib.md5(msg.encode("utf-8")).hexdigest()
            if m_hash in _sent_message_hashes:
                logging.info(f"Suppressed duplicate alert: {item.get('title')}")
                continue

            tg_ok = send_telegram(msg)
            send_whatsapp(msg)
            if tg_ok:
                delivered_count += 1
                _sent_message_hashes[m_hash] = now
                logging.info(f"Delivered notification: {item.get('title')}")
            else:
                remaining_queue.append(item)
        time.sleep(0.5)

    update_bus_section("notification_queue", remaining_queue)
    record_heartbeat(AGENT_NAME, f"HEALTHY_DELIVERED_{delivered_count}")

def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_notifications()
        except Exception as e:
            logging.error(f"Error in notification dispatcher: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(5)

if __name__ == "__main__":
    main()
