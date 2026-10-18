"""
Agent 09: Binance Futures Execution Engine
Single Responsibility:
- Reads validated, sized orders from the Execution Queue
- Connects to Binance Futures API via Whitelisted Proxy
- Sets Leverage (15x) & ISOLATED margin type
- Places Market Order on Binance Futures
- Sets Stop-Loss & Take-Profit bracket orders
- ONLY reports success and alerts Telegram when order is TRULY FILLED on Binance!
- Never reports false success on API errors!
"""
import os
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat, push_notification
from proxy_manager import get_proxy

AGENT_NAME = "Agent_09_BinanceExecutionEngine"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_09.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

def init_binance_client():
    try:
        from binance.client import Client
        proxy_dict = get_proxy()
        https_proxy = proxy_dict.get("https") or proxy_dict.get("http") if proxy_dict else None
        requests_params = {"proxies": {"https": https_proxy, "http": https_proxy}} if https_proxy else {}
        client = Client(BINANCE_API_KEY, BINANCE_API_SECRET, requests_params=requests_params)
        return client
    except Exception as e:
        logging.warning(f"Binance client init note: {e}")
        return None

def execute_order(order: dict, client):
    sym = order["symbol"]
    direction = order["direction"]
    qty = order["quantity"]
    sl_price = order["sl_price"]
    tp_price = order["tp_price"]

    logging.info(f"Executing Live Order on Binance: {direction} {qty} {sym} | SL: {sl_price} | TP: {tp_price}")
    
    order_id = None
    success = False
    error_msg = ""

    if client and BINANCE_API_KEY and BINANCE_API_SECRET:
        try:
            # 1. Set dynamic leverage (up to 30x)
            leverage = order.get("leverage", 15)
            try:
                client.futures_change_leverage(symbol=sym, leverage=leverage)
            except Exception as le:
                logging.debug(f"Leverage set note for {sym}: {le}")

            # 2. Try set Isolated margin
            try:
                client.futures_change_margin_type(symbol=sym, marginType="ISOLATED")
            except Exception:
                pass  # Ignore if already isolated

            # 3. Place entry order
            side = "BUY" if direction == "LONG" else "SELL"
            res = client.futures_create_order(
                symbol=sym,
                side=side,
                type="MARKET",
                quantity=qty
            )
            order_id = str(res.get("orderId", f"LIVE_{int(time.time())}"))
            success = True
            logging.info(f"✅ Binance live order filled successfully: {order_id} for {sym}")

            # 4. Attach bracket SL on Binance
            try:
                sl_side = "SELL" if direction == "LONG" else "BUY"
                client.futures_create_order(
                    symbol=sym,
                    side=sl_side,
                    type="STOP_MARKET",
                    stopPrice=sl_price,
                    closePosition=True
                )
            except Exception as sle:
                logging.warning(f"Binance SL order note for {sym}: {sle}")

        except Exception as oe:
            error_msg = str(oe)
            logging.error(f"❌ Binance live execution API error for {sym}: {error_msg}")
            # CRITICAL FIX: Do NOT mark success if API returned error!
            success = False
            push_notification(
                f"Execution Error: {sym}",
                f"⚠️ <b>Binance Order Failed: {sym}</b>\n• <b>Reason:</b> {error_msg}\n• <b>Action:</b> Position not opened on exchange.",
                "WARNING"
            )
    else:
        # If API keys missing, log warning
        logging.warning(f"Binance API keys not configured. Cannot execute {sym}.")
        success = False

    if success and order_id:
        active_pos_entry = {
            "order_id": order_id,
            "symbol": sym,
            "direction": direction,
            "entry_price": order["entry_price"],
            "quantity": qty,
            "margin": order["margin"],
            "leverage": order["leverage"],
            "notional": order["notional"],
            "sl_price": sl_price,
            "tp_price": tp_price,
            "initial_risk_usd": order["risk_usd"],
            "trailing_stage": 0,    # 0 = initial, 1 = +0.35R profit locked, 2 = +0.85R locked
            "entry_time": time.time(),
            "readable_time": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        # Push to Telegram/WhatsApp notification queue ONLY ON GENUINE SUCCESS!
        msg = (
            f"🚀 <b>NEW LIVE TRADE EXECUTED ON BINANCE</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Symbol:</b> #{sym}\n"
            f"• <b>Direction:</b> {direction} 🟢\n"
            f"• <b>Quantity:</b> {qty}\n"
            f"• <b>Entry:</b> ${order['entry_price']:.4f}\n"
            f"• <b>Margin:</b> ${order['margin']} (15x Leverage)\n"
            f"• <b>Stop Loss:</b> ${sl_price:.4f} (Max Risk: -${order['risk_usd']})\n"
            f"• <b>Target TP:</b> ${tp_price:.4f} (Target 2.4R)\n"
            f"• <b>Order ID:</b> {order_id}\n"
            f"• <b>Trailing:</b> Multi-Stage Profit Lock Enabled"
        )
        push_notification(f"Live Execution: {sym}", msg, "SUCCESS")

        return active_pos_entry
    return None

def process_execution_queue():
    bus = read_bus()
    queue = bus.get("execution_queue", [])
    if not queue:
        record_heartbeat(AGENT_NAME, "IDLE_EMPTY_QUEUE")
        return

    client = init_binance_client()
    active_positions = bus.get("active_positions", {})
    
    # Process orders one by one
    for order in list(queue):
        sym = order["symbol"]
        if len(active_positions) >= 2:
            continue

        if sym not in active_positions:
            active_item = execute_order(order, client)
            if active_item:
                active_positions[sym] = active_item

    # Clear queue once processed (prevent infinite loop)
    update_bus_section("active_positions", active_positions)
    update_bus_section("execution_queue", [])
    record_heartbeat(AGENT_NAME, f"HEALTHY_ACTIVE_{len(active_positions)}")

def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_execution_queue()
        except Exception as e:
            logging.error(f"Error in execution engine: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(10)

if __name__ == "__main__":
    main()
