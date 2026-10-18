"""
==============================================================================
CryptoBot - 24/7 Telegram All-Channels Auto-Listener & Scanner (Telethon)
==============================================================================
Features:
1. Listens to ALL joined VIP Channels, Groups, & Chats automatically in real-time.
2. Zero Manual Forwarding Needed - Intercepts posts instantly.
3. Filters every trade signal through:
   - BTC Daily Bias (Daily Close vs EMA20)
   - 15m/1h SMC Trend & RSI
   - 1:3 & 1:4 Step-Trailing Ratchet Risk Management
4. Dispatches instant analysis & alerts directly to your Personal Telegram Bot.
5. Auto-Executes trades if AUTO_EXECUTE is enabled.
==============================================================================
"""

import os
import sys
import asyncio
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("ChannelListener")

from telethon import TelegramClient, events
from telegram_signal_validator import parse_telegram_signal, evaluate_signal_with_bot_rules
from telegram_proxy_manager import execute_telegram_api
from pipeline_bus import read_bus, update_bus_section

# Telegram API Credentials (from my.telegram.org)
API_ID = os.getenv("TELEGRAM_API_ID", "")
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALERT_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
AUTO_EXECUTE = os.getenv("AUTO_EXECUTE_TELEGRAM_SIGNALS", "false").lower() == "true"

SESSION_FILE = os.path.join(BASE_DIR, "telethon_user_session")

def send_alert_to_bot(text: str):
    """Sends notification to user's Telegram AI Bot chat."""
    if not BOT_TOKEN or not ALERT_CHAT_ID:
        return
    payload = {
        "chat_id": str(ALERT_CHAT_ID),
        "text": text,
        "parse_mode": "HTML"
    }
    execute_telegram_api("POST", "sendMessage", payload=payload)

async def main():
    if not API_ID or not API_HASH:
        log.error("❌ TELEGRAM_API_ID and TELEGRAM_API_HASH are not set in .env!")
        print("\n" + "="*70)
        print("⚠️ SETUP REQUIRED: Telegram API ID & Hash")
        print("="*70)
        print("1. Go to https://my.telegram.org and log in with your phone number.")
        print("2. Click 'API development tools' and copy your api_id and api_hash.")
        print("3. Add them to your .env file:")
        print("   TELEGRAM_API_ID=your_api_id")
        print("   TELEGRAM_API_HASH=your_api_hash")
        print("   TELEGRAM_PHONE=+923xxxxxxxxx")
        print("="*70 + "\n")
        return

    client = TelegramClient(SESSION_FILE, int(API_ID), API_HASH)
    await client.start(phone=PHONE if PHONE else None)
    
    me = await client.get_me()
    log.info(f"✅ Connected to Telegram Account: {me.first_name} (@{me.username or 'NoUser'})")
    
    send_alert_to_bot(
        f"🤖 <b>Telegram Auto-Listener Connected!</b>\n"
        f"Aapke Telegram Account (<b>{me.first_name}</b>) ke saare VIP Channels & Groups ab 24/7 monitor ho rahe hain.\n\n"
        f"• <b>Auto-Scan:</b> Active (BTC Daily Bias + SMC)\n"
        f"• <b>Auto-Execute:</b> {'Enabled 🟢' if AUTO_EXECUTE else 'Manual Confirmation Mode 🟡'}"
    )

    @client.on(events.NewMessage)
    async def message_handler(event):
        try:
            text = event.raw_text
            if not text:
                return
                
            chat = await event.get_chat()
            chat_title = getattr(chat, 'title', getattr(chat, 'first_name', 'Unknown Chat'))
            
            # Check if message is a trade signal
            sig = parse_telegram_signal(text)
            if sig:
                log.info(f"⚡ Intercepted Signal from [{chat_title}]: {sig['symbol']} {sig['side']}")
                
                # Run institutional evaluation
                eval_res = evaluate_signal_with_bot_rules(sig)
                
                sym = eval_res["symbol"]
                side = eval_res["side"]
                score = eval_res["score"]
                verdict = eval_res["verdict"]
                curr_p = eval_res["current_price"]
                sl = eval_res["sl"]
                tps = eval_res.get("tps", [])
                btc_bias = eval_res["btc_bias"]
                rsi = eval_res["rsi_15m"]
                reasons = eval_res["reasons"]
                
                verdict_badge = {
                    "APPROVED": "🟢 <b>APPROVED (High-Conviction Trade)</b>",
                    "CAUTION": "🟡 <b>CAUTION (Moderate Risk)</b>",
                    "REJECTED": "🔴 <b>REJECTED (Filter Blocked)</b>"
                }.get(verdict, "⚪ <b>UNKNOWN</b>")

                reasons_text = "\n".join([f"• {r}" for r in reasons])

                tp_text = ""
                if len(tps) >= 4:
                    tp_text = (
                        f"🎯 <b>Step-Trailing Ratchet Targets:</b>\n"
                        f"  • <b>TP1 (+7.5%):</b> <code>${tps[0]:,.4f}</code> <i>(Move SL -> BE)</i>\n"
                        f"  • <b>TP2 (+10%):</b> <code>${tps[1]:,.4f}</code> <i>(Lock +7.5% Profit)</i>\n"
                        f"  • <b>TP3 (+12.5%):</b> <code>${tps[2]:,.4f}</code> <i>(Lock +10.0% Profit)</i>\n"
                        f"  • <b>TP4 (+15%):</b> <code>${tps[3]:,.4f}</code> <i>(Lock +12.5% Profit)</i>\n"
                    )

                alert_msg = (
                    f"📡 <b>AUTO-INTERCEPTED SIGNAL</b> from <code>{chat_title}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🪙 <b>Coin:</b> <code>{sym}</code> | <b>Side:</b> <b>{side}</b>\n"
                    f"📊 <b>Score:</b> <b>{score}/100</b>\n"
                    f"🚦 <b>Verdict:</b> {verdict_badge}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👑 <b>BTC Macro Bias:</b> <code>{btc_bias}</code>\n"
                    f"📈 <b>15m RSI:</b> <code>{rsi}</code>\n"
                    f"💵 <b>Current Price:</b> <code>${curr_p:,.4f}</code>\n"
                    f"🛑 <b>Initial Stop-Loss:</b> <code>${sl:,.4f}</code> (-2.5%)\n\n"
                    f"{tp_text}\n"
                    f"📋 <b>Bot Filter:</b>\n"
                    f"{reasons_text}\n\n"
                )

                if verdict == "APPROVED":
                    if AUTO_EXECUTE:
                        # Auto execute on Binance
                        margin = 15.0
                        lev = 5
                        qty = round((margin * lev) / curr_p, 4)
                        order_payload = {
                            "symbol": sym,
                            "direction": side,
                            "quantity": qty,
                            "entry_price": curr_p,
                            "sl_price": round(sl, 4),
                            "tp_price": round(tps[0], 4) if tps else round(curr_p*1.075, 4),
                            "status": "APPROVED",
                            "score": score,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "strategy": "Step-Trailing Ratchet 1:4",
                            "margin": margin,
                            "leverage": lev
                        }
                        update_bus_section("execution_queue", [order_payload])
                        alert_msg += "⚡ <b>AUTO-EXECUTED:</b> Trade Binance execution queue mein bhej di gayi hai!"
                    else:
                        alert_msg += f"👉 <b>Execute karne ke liye likhein:</b> <code>/execute {sym} {side}</code>"
                else:
                    alert_msg += "🛡️ <b>Bot Protection:</b> Trade automatically skip kar di gayi hai."

                send_alert_to_bot(alert_msg)

        except Exception as e:
            log.error(f"Error processing message: {e}")

    log.info("🚀 Listening for signals across all Telegram channels...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
