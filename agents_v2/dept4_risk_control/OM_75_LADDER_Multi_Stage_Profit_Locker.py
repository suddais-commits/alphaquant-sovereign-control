"""
Agent 10: Dedicated Dynamic Step-Trailing Stop Loss & Profit Locker
Single Responsibility:
- Runs continuous monitoring of active positions
- Step-Trailing Ratchet Logic (100% Position Trailing Runner):
  * Target 1 (+7.5% / 1:3 R:R): Moves Stop-Loss to Break-Even ($0.00 Risk)
  * Target 2 (+10.0% / 1:4 R:R): Moves Stop-Loss to Target 1 (+7.5% Guaranteed Profit Locked)
  * Target 3 (+12.5% / 1:5 R:R): Moves Stop-Loss to Target 2 (+10.0% Guaranteed Profit Locked)
  * Target 4 (+15.0% / 1:6 R:R): Moves Stop-Loss to Target 3 (+12.5% Guaranteed Profit Locked)
- Real-time Stop-Loss & Trailing Profit Lock detection
- Dispatches closed trade logs to Agent 11 (Alerts) & Agent 12 (Journal)
"""
import os
import sys
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat, push_notification

AGENT_NAME = "Agent_10_TrailingSLProfitLocker"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_10.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

def evaluate_trailing_positions():
    bus = read_bus()
    active_positions = bus.get("active_positions", {})
    market_data = bus.get("market_data", {})
    
    if not active_positions:
        record_heartbeat(AGENT_NAME, "IDLE_NO_ACTIVE_TRADES")
        return

    remaining_positions = {}
    closed_trades = []

    for sym, pos in active_positions.items():
        m_entry = market_data.get(sym, {})
        curr_price = m_entry.get("current_price", pos["entry_price"])
        
        entry = pos["entry_price"]
        sl = pos["sl_price"]
        direction = pos["direction"]
        stage = pos.get("trailing_stage", 0)
        notional = pos.get("notional", 15.0)

        is_closed = False
        outcome = ""
        exit_reason = ""
        net_pnl = 0.0

        if direction == "LONG":
            profit_pct = (curr_price - entry) / entry

            # Step 4: +15.0% expansion -> Trail SL to +12.5%
            if profit_pct >= 0.150 and stage < 4:
                pos["sl_price"] = round(entry * 1.125, 4)
                pos["trailing_stage"] = 4
                logging.info(f"🔒 STAGE 4 LOCK: {sym} reached +15.0%! SL trailed to +12.5% (${pos['sl_price']})")
                push_notification(
                    f"SL Trailed: {sym}",
                    f"🏆 <b>MEGA PROFIT LOCKED (+12.5%)</b>\n• {sym} reached +15.0%\n• New SL: ${pos['sl_price']:.4f}",
                    "SUCCESS"
                )
            # Step 3: +12.5% expansion -> Trail SL to +10.0%
            elif profit_pct >= 0.125 and stage < 3:
                pos["sl_price"] = round(entry * 1.100, 4)
                pos["trailing_stage"] = 3
                logging.info(f"🔒 STAGE 3 LOCK: {sym} reached +12.5%! SL trailed to +10.0% (${pos['sl_price']})")
                push_notification(
                    f"SL Trailed: {sym}",
                    f"🔒 <b>PROFIT LOCKED (+10.0%)</b>\n• {sym} reached +12.5%\n• New SL: ${pos['sl_price']:.4f}",
                    "SUCCESS"
                )
            # Step 2: +10.0% expansion -> Trail SL to +7.5%
            elif profit_pct >= 0.100 and stage < 2:
                pos["sl_price"] = round(entry * 1.075, 4)
                pos["trailing_stage"] = 2
                logging.info(f"🔒 STAGE 2 LOCK: {sym} reached +10.0%! SL trailed to +7.5% (${pos['sl_price']})")
                push_notification(
                    f"SL Trailed: {sym}",
                    f"🔒 <b>PROFIT LOCKED (+7.5%)</b>\n• {sym} reached +10.0%\n• New SL: ${pos['sl_price']:.4f}",
                    "INFO"
                )
            # Step 1: +7.5% expansion (1:3 R:R) -> Move SL to BreakEven (Entry)
            elif profit_pct >= 0.075 and stage < 1:
                pos["sl_price"] = round(entry, 4)
                pos["trailing_stage"] = 1
                logging.info(f"🔒 STAGE 1 LOCK: {sym} reached +7.5%! SL moved to BreakEven ($0 Risk)")
                push_notification(
                    f"SL BreakEven: {sym}",
                    f"🛡️ <b>BREAKEVEN LOCKED ($0 Risk)</b>\n• {sym} reached +7.5% (1:3 R:R)\n• New SL: ${pos['sl_price']:.4f}\n• Risk eliminated!",
                    "INFO"
                )

            # Check SL / Trailing SL hit
            if curr_price <= pos["sl_price"]:
                is_closed = True
                net_pnl = round((pos["sl_price"] - entry) / entry * notional, 3)
                outcome = "WIN" if net_pnl > 0 else ("BREAKEVEN" if net_pnl == 0 else "LOSS")
                exit_reason = f"TRAILED_SL_STAGE_{stage}" if stage > 1 else ("BE_EXIT" if stage == 1 else "SL_HIT")

        else: # SHORT
            profit_pct = (entry - curr_price) / entry

            # Step 4: -15.0% drop -> Trail SL to -12.5%
            if profit_pct >= 0.150 and stage < 4:
                pos["sl_price"] = round(entry * 0.875, 4)
                pos["trailing_stage"] = 4
                push_notification(
                    f"SL Trailed: {sym}",
                    f"🏆 <b>MEGA PROFIT LOCKED (+12.5%)</b>\n• SHORT {sym} reached +15.0%\n• New SL: ${pos['sl_price']:.4f}",
                    "SUCCESS"
                )
            # Step 3: -12.5% drop -> Trail SL to -10.0%
            elif profit_pct >= 0.125 and stage < 3:
                pos["sl_price"] = round(entry * 0.900, 4)
                pos["trailing_stage"] = 3
                push_notification(
                    f"SL Trailed: {sym}",
                    f"🔒 <b>PROFIT LOCKED (+10.0%)</b>\n• SHORT {sym} reached +12.5%\n• New SL: ${pos['sl_price']:.4f}",
                    "SUCCESS"
                )
            # Step 2: -10.0% drop -> Trail SL to -7.5%
            elif profit_pct >= 0.100 and stage < 2:
                pos["sl_price"] = round(entry * 0.925, 4)
                pos["trailing_stage"] = 2
                push_notification(
                    f"SL Trailed: {sym}",
                    f"🔒 <b>PROFIT LOCKED (+7.5%)</b>\n• SHORT {sym} reached +10.0%\n• New SL: ${pos['sl_price']:.4f}",
                    "INFO"
                )
            # Step 1: -7.5% drop (1:3 R:R) -> Move SL to BreakEven
            elif profit_pct >= 0.075 and stage < 1:
                pos["sl_price"] = round(entry, 4)
                pos["trailing_stage"] = 1
                push_notification(
                    f"SL BreakEven: {sym}",
                    f"🛡️ <b>BREAKEVEN LOCKED ($0 Risk)</b>\n• SHORT {sym} reached +7.5% (1:3 R:R)\n• New SL: ${pos['sl_price']:.4f}",
                    "INFO"
                )

            if curr_price >= pos["sl_price"]:
                is_closed = True
                net_pnl = round((entry - pos["sl_price"]) / entry * notional, 3)
                outcome = "WIN" if net_pnl > 0 else ("BREAKEVEN" if net_pnl == 0 else "LOSS")
                exit_reason = f"TRAILED_SL_STAGE_{stage}" if stage > 1 else ("BE_EXIT" if stage == 1 else "SL_HIT")

        if is_closed:
            closed_item = {
                "symbol": sym,
                "direction": direction,
                "entry_price": entry,
                "exit_price": pos["sl_price"],
                "outcome": outcome,
                "exit_reason": exit_reason,
                "net_pnl": net_pnl,
                "entry_time": pos.get("entry_time", time.time()),
                "exit_time": time.time(),
                "duration_minutes": round((time.time() - pos.get("entry_time", time.time())) / 60, 1)
            }
            closed_trades.append(closed_item)
            icon = "✅" if net_pnl > 0 else ("🛡️" if net_pnl == 0 else "❌")
            msg = (
                f"{icon} <b>TRADE CLOSED: {sym}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Outcome:</b> {outcome} ({exit_reason})\n"
                f"• <b>Exit Price:</b> ${pos['sl_price']:.4f}\n"
                f"• <b>Net PnL:</b> {'+' if net_pnl >= 0 else ''}${net_pnl:.3f} USDT\n"
                f"• <b>Duration:</b> {closed_item['duration_minutes']} mins"
            )
            push_notification(f"Trade Closed: {sym}", msg, "SUCCESS" if net_pnl > 0 else ("INFO" if net_pnl == 0 else "WARNING"))
        else:
            remaining_positions[sym] = pos

    update_bus_section("active_positions", remaining_positions)

    if closed_trades:
        analytics = bus.get("analytics_stats", {})
        recent_closed = analytics.get("recent_closed_queue", [])
        recent_closed.extend(closed_trades)
        analytics["recent_closed_queue"] = recent_closed
        update_bus_section("analytics_stats", analytics)

    record_heartbeat(AGENT_NAME, f"HEALTHY_ACTIVE_{len(remaining_positions)}")

def main():
    logging.info(f"{AGENT_NAME} started with Step-Trailing Ratchet logic.")
    while True:
        try:
            evaluate_trailing_positions()
        except Exception as e:
            logging.error(f"Error in trailing SL worker: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(10)

if __name__ == "__main__":
    main()
