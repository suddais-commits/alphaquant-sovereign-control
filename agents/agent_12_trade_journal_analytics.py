"""
Agent 12: Trade Journal & Performance Analytics Engine
Single Responsibility:
- Appends closed trade details to trade_journal.csv
- Calculates real-time system analytics:
  * Total Trades
  * Win Rate %
  * Total Net PnL (USDT)
  * Account Balance
  * Maximum Drawdown %
- Publishes up-to-date performance metrics to Pipeline Bus
"""
import os
import sys
import csv
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_12_TradeJournalAnalytics"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_12.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

JOURNAL_FILE = os.path.join(BASE_DIR, "trade_journal.csv")
STARTING_BALANCE = 4.56

def init_journal():
    if not os.path.exists(JOURNAL_FILE):
        with open(JOURNAL_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "exit_time", "symbol", "direction", "entry_price", "exit_price",
                "outcome", "exit_reason", "pnl_usdt", "balance_usdt", "duration_mins"
            ])

def append_trade_to_journal(trade: dict, new_balance: float):
    init_journal()
    with open(JOURNAL_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(trade.get("exit_time", time.time()))),
            trade.get("symbol"),
            trade.get("direction"),
            trade.get("entry_price"),
            trade.get("exit_price"),
            trade.get("outcome"),
            trade.get("exit_reason"),
            trade.get("net_pnl"),
            round(new_balance, 3),
            trade.get("duration_minutes", 0)
        ])

def recompute_metrics():
    init_journal()
    total_trades = 0
    wins = 0
    losses = 0
    total_pnl = 0.0
    balance = STARTING_BALANCE
    peak_balance = STARTING_BALANCE
    max_drawdown = 0.0

    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pnl = float(row.get("pnl_usdt", 0) or 0)
                outcome = row.get("outcome", "")
                total_trades += 1
                if outcome == "WIN":
                    wins += 1
                elif outcome == "LOSS":
                    losses += 1
                total_pnl += pnl
                balance += pnl
                if balance > peak_balance:
                    peak_balance = balance
                dd = (peak_balance - balance) / peak_balance * 100.0 if peak_balance > 0 else 0.0
                if dd > max_drawdown:
                    max_drawdown = dd
    except Exception as e:
        logging.warning(f"Journal read warning: {e}")

    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

    return {
        "starting_balance": STARTING_BALANCE,
        "current_balance": round(balance, 3),
        "total_pnl": round(total_pnl, 3),
        "roi_pct": round((total_pnl / STARTING_BALANCE) * 100.0, 2),
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 1),
        "max_drawdown_pct": round(max_drawdown, 2),
        "updated_at": time.time()
    }

def process_journal_queue():
    bus = read_bus()
    analytics = bus.get("analytics_stats", {})
    queue = analytics.get("recent_closed_queue", [])
    
    current_metrics = recompute_metrics()
    balance = current_metrics["current_balance"]

    if queue:
        for trade in queue:
            balance += trade.get("net_pnl", 0.0)
            append_trade_to_journal(trade, balance)
            logging.info(f"Journaled trade: {trade['symbol']} | PnL: ${trade['net_pnl']} | New Balance: ${balance:.3f}")
        
        # Clear queue and recompute
        analytics["recent_closed_queue"] = []
        current_metrics = recompute_metrics()

    analytics["metrics"] = current_metrics
    update_bus_section("analytics_stats", analytics)
    record_heartbeat(AGENT_NAME, f"HEALTHY_TRADES_{current_metrics['total_trades']}")

def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_journal_queue()
        except Exception as e:
            logging.error(f"Error in analytics engine: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(15)

if __name__ == "__main__":
    main()
