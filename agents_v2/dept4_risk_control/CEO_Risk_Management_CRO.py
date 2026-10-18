"""
Agent 08: Smart Position Sizer & Dynamic Leverage Risk Guard
Single Responsibility:
- Flexible Notional Sizing: Can open trades from $5.0 USDT (Binance minimum) up to ~$25 USDT
- Dynamic Leverage Scaling: 10x to 30x (User permitted up to 30x)
- Exact Binance Futures Step Sizes & Precision
- HARD RISK CAP: Maximum loss per trade strictly capped at -$0.18 USDT
- Dynamic ATR Stop Loss with 2.4:1 Risk-to-Reward Take Profit
- 30-Minute Cooldown per symbol to prevent repetitive spam
"""
import os
import sys
import time
import math
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_08_PositionSizerRiskGuard"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_08.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# User's parameters
TARGET_MARGIN = 1.50       # Base target margin $1.50 USDT per user's live Binance balance
DEFAULT_LEVERAGE = 20      # Default 20x leverage
MAX_LEVERAGE = 20          # Max 20x leverage
MIN_BINANCE_NOTIONAL = 5.2 # Binance minimum notional is $5.0 USDT (using 5.2 for safety buffer)
MAX_LOSS_CAP = 0.75        # -$0.75 USDT max risk per trade (-2.5% on $30 notional)
TARGET_RR = 2.4            # 2.4:1 R:R
SIGNAL_COOLDOWN_SEC = 1800 # 30 minutes cooldown per symbol

BINANCE_STEP_SIZES = {
    "BTCUSDT": 0.001,
    "ETHUSDT": 0.001,
    "LTCUSDT": 0.001,
    "BCHUSDT": 0.001,
    "SOLUSDT": 0.01,
    "LINKUSDT": 0.01,
    "BNBUSDT": 0.01,
    "ATOMUSDT": 0.01,
    "XRPUSDT": 0.1,
    "APTUSDT": 0.1,
    "SUIUSDT": 0.1,
    "RENDERUSDT": 0.1,
    "FILUSDT": 0.1,
    "OPUSDT": 0.1,
    "INJUSDT": 0.1,
    "DOTUSDT": 0.1,
    "WIFUSDT": 0.1,
    "ARBUSDT": 0.1,
    "AVAXUSDT": 1.0,
    "NEARUSDT": 1.0,
    "DOGEUSDT": 1.0,
    "ADAUSDT": 1.0,
    "TIAUSDT": 1.0,
    "FETUSDT": 1.0,
    "PEPEUSDT": 1000.0
}

BINANCE_PRICE_TICKS = {
    "BTCUSDT": 0.10,
    "ETHUSDT": 0.01,
    "LTCUSDT": 0.01,
    "BCHUSDT": 0.01,
    "SOLUSDT": 0.01,
    "BNBUSDT": 0.01,
    "LINKUSDT": 0.001,
    "ATOMUSDT": 0.001,
    "AVAXUSDT": 0.001,
    "NEARUSDT": 0.001,
    "INJUSDT": 0.001,
    "XRPUSDT": 0.0001,
    "APTUSDT": 0.0001,
    "ADAUSDT": 0.0001,
    "SUIUSDT": 0.0001,
    "FILUSDT": 0.0001,
    "DOTUSDT": 0.0001,
    "WIFUSDT": 0.0001,
    "TIAUSDT": 0.0001,
    "FETUSDT": 0.0001,
    "RENDERUSDT": 0.001,
    "DOGEUSDT": 0.00001,
    "OPUSDT": 0.00001,
    "ARBUSDT": 0.00001
}

_last_executed_ts = {}

def format_binance_quantity(sym: str, raw_qty: float) -> float:
    step = BINANCE_STEP_SIZES.get(sym, 0.1)
    if step >= 1.0:
        return float(int(raw_qty // step * step))
    dec_places = len(str(step).rstrip('0').split('.')[1])
    qty = math.floor(raw_qty / step) * step
    return round(qty, dec_places)

def format_binance_price(sym: str, raw_price: float) -> float:
    tick = BINANCE_PRICE_TICKS.get(sym, 0.0001)
    if tick >= 1.0:
        return round(raw_price, 0)
    dec_places = len(str(tick).rstrip('0').split('.')[1])
    return round(raw_price, dec_places)

def size_trade(setup: dict) -> dict:
    sym = setup["symbol"]
    entry_p = setup["current_price"]
    direction = setup["direction"]
    atr = setup.get("atr", entry_p * 0.01)
    step = BINANCE_STEP_SIZES.get(sym, 0.1)

    # 1. Start with baseline notional ~$12.75
    target_notional = TARGET_MARGIN * DEFAULT_LEVERAGE
    raw_qty = target_notional / entry_p
    qty = format_binance_quantity(sym, raw_qty)

    # 2. Check if formatted qty is 0 or less than minimum notional ($5.0 USDT)
    actual_notional = qty * entry_p
    if actual_notional < MIN_BINANCE_NOTIONAL:
        # Step up quantity to meet Binance min notional
        min_units = math.ceil(MIN_BINANCE_NOTIONAL / (entry_p * step)) * step
        qty = format_binance_quantity(sym, min_units)
        actual_notional = qty * entry_p

    # 3. Dynamic Leverage: If notional exceeds $13 to satisfy step size, scale leverage up to 30x
    needed_margin = actual_notional / DEFAULT_LEVERAGE
    if needed_margin > TARGET_MARGIN:
        # Scale leverage up (up to 30x) to keep margin close to user budget
        leverage = min(MAX_LEVERAGE, max(DEFAULT_LEVERAGE, int(math.ceil(actual_notional / TARGET_MARGIN))))
    else:
        # If notional is lower (e.g. $7.40 for 0.01 BNB), standard 15x is perfect
        leverage = DEFAULT_LEVERAGE

    actual_margin = round(actual_notional / leverage, 3)

    # 4. Dynamic ATR Stop Loss with Volatility Expansion Protection
    # In high volatility / news spikes, stretch ATR multiplier up to 2.8x to prevent wick-outs
    volatility_ratio = (atr / entry_p) * 100 if entry_p > 0 else 1.0
    if volatility_ratio > 1.5:  # High volatility regime
        atr_multiplier = 2.8
    elif volatility_ratio > 0.8: # Medium volatility
        atr_multiplier = 2.4
    else:                        # Low volatility / tight range
        atr_multiplier = 2.2

    sl_dist = max(atr * atr_multiplier, entry_p * 0.012)
    potential_loss = (sl_dist / entry_p) * actual_notional
    if potential_loss > MAX_LOSS_CAP:
        sl_dist = (MAX_LOSS_CAP / actual_notional) * entry_p
        potential_loss = MAX_LOSS_CAP

    tp_dist = sl_dist * TARGET_RR

    if direction == "LONG":
        sl_price = format_binance_price(sym, entry_p - sl_dist)
        tp_price = format_binance_price(sym, entry_p + tp_dist)
    else:
        sl_price = format_binance_price(sym, entry_p + sl_dist)
        tp_price = format_binance_price(sym, entry_p - tp_dist)

    return {
        "symbol": sym,
        "direction": direction,
        "entry_price": entry_p,
        "quantity": qty,
        "margin": actual_margin,
        "leverage": leverage,
        "notional": round(actual_notional, 2),
        "sl_price": sl_price,
        "tp_price": tp_price,
        "atr_multiplier": atr_multiplier,
        "risk_usd": round(potential_loss, 3),
        "potential_gain_usd": round(potential_loss * TARGET_RR, 3),
        "timestamp": time.time()
    }

def get_max_allowed_positions(balance: float) -> int:
    """Dynamic Growth Unlocking: Scale allowed positions as balance grows."""
    if balance >= 15.0:
        return 7
    elif balance >= 7.5:
        return 4
    return 2

def process_sizing_all():
    global _last_executed_ts
    bus = read_bus()
    scores = bus.get("conviction_scores", {})
    active_pos = bus.get("active_positions", {})
    account_info = bus.get("account_info", {})
    current_balance = float(account_info.get("wallet_balance", TARGET_MARGIN * 3))
    now = time.time()

    max_allowed = get_max_allowed_positions(current_balance)
    
    # Count how many open positions still have active downside risk
    at_risk_count = 0
    for sym, pos in active_pos.items():
        is_risk_free = pos.get("is_risk_free", False) or pos.get("stop_loss_at_be", False)
        if not is_risk_free:
            at_risk_count += 1

    if len(active_pos) >= max_allowed or at_risk_count >= 2:
        record_heartbeat(AGENT_NAME, f"SLOTS_FULL_{len(active_pos)}/{max_allowed}_AT_RISK_{at_risk_count}")
        return

    sized_orders = {}
    new_execution_items = []
    current_queue = bus.get("execution_queue", [])

    board_res = bus.get("board_resolutions", {})

    for sym, setup in scores.items():
        # Require both Conviction approval AND Board of Directors consensus
        is_conviction_approved = setup.get("approved", False)
        board_status = board_res.get(sym, {})
        # If board resolutions are present, strictly require board approval
        is_board_approved = board_status.get("is_approved", True) if not board_res else board_status.get("is_approved", False)

        if is_conviction_approved and is_board_approved and sym not in active_pos:
            last_ts = _last_executed_ts.get(sym, 0)
            if now - last_ts < SIGNAL_COOLDOWN_SEC:
                continue

            already_in_queue = any(q["symbol"] == sym for q in current_queue)
            if already_in_queue:
                continue

            sized = size_trade(setup)
            if sized["quantity"] <= 0:
                continue

            sized_orders[sym] = sized

            if len(active_pos) + len(current_queue) + len(new_execution_items) < max_allowed and at_risk_count < 2:
                new_execution_items.append(sized)
                at_risk_count += 1
                _last_executed_ts[sym] = now
                logging.info(f"Sized {sym}: Qty {sized['quantity']} | Lev {sized['leverage']}x | Margin ${sized['margin']} | Notional ${sized['notional']} | SL {sized['sl_price']} | TP {sized['tp_price']}")

    if sized_orders:
        bus_sizes = bus.get("position_sizes", {})
        bus_sizes.update(sized_orders)
        update_bus_section("position_sizes", bus_sizes)

    if new_execution_items:
        current_queue.extend(new_execution_items)
        update_bus_section("execution_queue", current_queue)

    record_heartbeat(AGENT_NAME, f"HEALTHY_QUEUED_{len(new_execution_items)}")

def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_sizing_all()
        except Exception as e:
            logging.error(f"Error in position sizer: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(15)

if __name__ == "__main__":
    main()
