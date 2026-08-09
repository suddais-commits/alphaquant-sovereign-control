"""
SMC / ICT Strategy Backtest -- aapke apne master_bot.py ki EXACT strategy
--------------------------------------------------------------------------
Ye script generic RSI/MACD wale backtest (run_backtest.py) se ALAG hai.
Ye seedha aapke `master_bot.py` se real functions IMPORT karta hai
(check_structure, detect_fvg, detect_order_block, vsa_score,
candle_confirmation, compute_entry_sl_tp, compute_final_score) -- matlab
jo logic live bot mein signal deta hai, WAHI logic yahan purane
(historical) data par test hota hai. Koi alag copy-paste wali strategy
nahi hai, 100% wahi hai.

IMPORTANT LIMITATION (transparency ke liye):
Layer 1 (fundamental) aur Layer 2 (onchain/Arkham) ke liye historical
data available nahi hota free mein (Arkham/CoinGecko sirf "abhi ka"
data dete hain, mahino purana whale-flow free mein nahi milta). Isliye
in dono layers ko is backtest mein NEUTRAL (0.5) maan liya gaya hai.
Baaki sab layers (structure, sweep, OB/FVG, VSA, candle, risk-reward)
100% wahi asli calculation use karte hain jo live bot karta hai.

Trade simulation kaise hoti hai:
  1. Har closed candle par check_structure() se signal dhoondo (jaisa live
     bot karta hai)
  2. Agar signal + score >= SCORE_THRESHOLD, to entry le lo (turant fill,
     jaisa "Market order" hota)
  3. Us candle ke baad wale candles mein dekho SL pehle touch hota hai ya
     TP1 (agar dono ek hi candle mein touch ho jayein, SAFE side lete
     hain aur SL ko pehle maante hain -- conservative estimate)
  4. Result note karo: WIN (TP1 hit) ya LOSS (SL hit)
  5. Jab tak ye trade open hai, us symbol par NAYA signal skip hota hai
     (jaisa live bot ka managed_trades wala rule hai)

USAGE (Command Prompt mein, CryptoBot folder ke andar):

  python backtest_smc_strategy.py SOLUSDT --days 90
  python backtest_smc_strategy.py --shortlist BTCUSDT ETHUSDT SOLUSDT ADAUSDT --days 60
  python backtest_smc_strategy.py SOLUSDT --days 90 --max-hold-bars 50
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from binance.client import Client

# --- Seedha master_bot.py se asli strategy functions import kar rahe hain ---
from master_bot import (
    check_structure,
    detect_fvg,
    detect_order_block,
    vsa_score,
    candle_confirmation,
    compute_entry_sl_tp,
    compute_final_score,
    SWING_LOOKBACK,
    SCORE_THRESHOLD,
    TIMEFRAME,
    MAX_SL_DISTANCE_PCT,
    MIN_SL_DISTANCE_PCT,
)

# master_bot.py ka VSA function har candle par "absorption/churning detected"
# jaisi INFO log lines print karta hai (live bot mein useful hai, lekin
# backtest mein 600+ signals ke saath screen bhar jaati hai) -- isliye
# yahan sirf WARNING+ level allow karte hain, output saaf rehta hai.
import logging
logging.getLogger("master_bot").setLevel(logging.WARNING)

# --- IMPORTANT FIX: news_clear() ko backtest ke liye neutral banate hain ---
# master_bot.compute_final_score() internally news_clear() call karta hai,
# jo LIVE RSS feeds (CoinDesk/CoinTelegraph) check karta hai -- "aaj" ki
# headlines, chahe backtest kisi 2025 ke purane candle ko score kar raha ho.
# Isse har backtest run ka result us waqt ki live news par depend karta
# tha (agar backtest chalate waqt koi risky keyword wali headline thi, to
# har trade ka score achanak 10 points (WEIGHTS["news"]) kam ho jaata tha
# -- jisse zyada threshold par sab trades achanak zero ho sakte the, jaisa
# humein dekhne mila). Backtest reproducible/historical rehna chahiye,
# isliye yahan master_bot module ke andar news_clear() ko monkeypatch
# karke hamesha True return karwate hain -- sirf is backtest script mein,
# LIVE bot (master_bot.py) ka news filter bilkul waisa hi chalta rehta hai.
import master_bot
master_bot.news_clear = lambda: True

load_dotenv()

NEUTRAL_SCORE = 0.5  # Layer1 (fundamental) + Layer2 (onchain) -- historical data available nahi


def fetch_historical_candles(client: Client, symbol: str, days: int, timeframe: str = None):
    """Binance se historical klines leta hai aur master_bot.py ke get_klines() jaise
    hi format mein candle dicts banata hai (volume sahit, VSA ke liye zaroori hai).
    timeframe diya na jaye to master_bot.py ka live TIMEFRAME (15m) use hota hai."""
    tf = timeframe or TIMEFRAME
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d %b %Y %H:%M:%S")
    raw = client.get_historical_klines(symbol, tf, start)
    return [
        {
            "open_time": k[0], "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]), "close_time": k[6],
            "volume": float(k[5]),
        }
        for k in raw
    ]


def simulate_trade(direction: str, entry: float, sl: float, tp1: float,
                    future_candles: list, max_hold_bars: int):
    """Entry ke baad wale candles mein walk karta hai -- SL ya TP1 jo pehle
    touch ho, wahi result hai. max_hold_bars ke andar kuch resolve na ho to
    'no_result' (timeout) maan liya jata hai."""
    for i, c in enumerate(future_candles[:max_hold_bars]):
        if direction == "LONG":
            hit_sl = c["low"] <= sl
            hit_tp = c["high"] >= tp1
        else:
            hit_sl = c["high"] >= sl
            hit_tp = c["low"] <= tp1

        if hit_sl and hit_tp:
            return "loss", i + 1  # dono ek hi candle mein -- conservative: SL pehle maano
        if hit_sl:
            return "loss", i + 1
        if hit_tp:
            return "win", i + 1

    return "timeout", max_hold_bars


def trade_cost_in_r(entry: float, sl: float, commission_pct: float, slippage_pct: float) -> float:
    """
    Fees + slippage ko R-multiple mein convert karta hai, taaki win/loss R se
    seedha subtract kiya ja sake -- taaki numbers 'net of cost' (realistic)
    ban jayein, sirf theoretical na rahein.
    Round-trip (entry + exit) dono taraf commission lagti hai, isliye 2x.
    """
    risk_pct_of_price = abs(entry - sl) / entry
    if risk_pct_of_price <= 0:
        return 0.0
    cost_pct_of_price = 2 * (commission_pct + slippage_pct) / 100
    return cost_pct_of_price / risk_pct_of_price


def backtest_symbol(client: Client, symbol: str, days: int, max_hold_bars: int, verbose: bool,
                     commission_pct: float, slippage_pct: float, timeframe: str = None,
                     min_score: float = None):
    # min_score diya gaya to master_bot.py ke live SCORE_THRESHOLD ko override
    # karta hai -- taaki live bot ko chhede bina hi alag-alag thresholds
    # (60, 65, 70, 75...) test kiye ja sakein.
    score_threshold = min_score if min_score is not None else SCORE_THRESHOLD
    candles = fetch_historical_candles(client, symbol, days, timeframe)
    if len(candles) < SWING_LOOKBACK + 3:
        print(f"  {symbol}: itna purana data nahi mila ({len(candles)} candles). Skip.")
        return None

    trades = []
    open_trade_until = -1  # index jahan tak trade "open" maani jayegi (managed_trades jaisa)

    # window size wahi jo live get_klines deta hai (SWING_LOOKBACK + 2), sliding
    window_size = SWING_LOOKBACK + 2
    for i in range(window_size, len(candles)):
        if i <= open_trade_until:
            continue  # pehle wali trade abhi "open" hai, naya signal skip (jaisa live bot)

        window = candles[i - window_size:i]  # candles[-1] discard ho jayega check_structure mein
        structure = check_structure(window)
        if not structure:
            continue

        test_idx = i - 2  # jo candle actually signal de rahi hai (window ka closed[-1])
        direction = structure["direction"]

        candle_ok = candle_confirmation(window, direction)
        ob_found = detect_order_block(window, direction)
        fvg_found = detect_fvg(window, direction)
        vsa = vsa_score(window, direction)
        result = compute_entry_sl_tp(structure)
        if result is None:
            continue  # SL cap ya min R:R fail -- backtest mein bhi skip karo, jaisa live bot karta hai
        entry, sl, tp1, tp2, tp3, rr, tp_levels = result

        sl_distance_pct = abs(entry - sl) / entry * 100
        if sl_distance_pct > MAX_SL_DISTANCE_PCT or sl_distance_pct < MIN_SL_DISTANCE_PCT:
            continue

        score = compute_final_score(NEUTRAL_SCORE, NEUTRAL_SCORE, structure, candle_ok, rr,
                                     ob_found or fvg_found, vsa)

        if score < score_threshold:
            continue

        future = candles[i:]
        result, bars_held = simulate_trade(direction, entry, sl, tp1, future, max_hold_bars)
        if result == "timeout":
            continue  # na win na loss -- skip, count nahi karte confusing hone se bachne ke liye

        cost_r = trade_cost_in_r(entry, sl, commission_pct, slippage_pct)
        gross_r = 1.0 if result == "win" else -1.0
        net_r = gross_r - cost_r  # fees+slippage ke baad ka asli R

        trades.append({
            "symbol": symbol, "direction": direction, "score": score,
            "result": result, "bars_held": bars_held, "r": net_r, "gross_r": gross_r,
            "entry_time": datetime.fromtimestamp(candles[test_idx]["close_time"] / 1000, tz=timezone.utc),
        })
        open_trade_until = i + bars_held  # is trade ke khatam hone tak naya signal skip

        if verbose:
            print(f"    {trades[-1]['entry_time'].strftime('%Y-%m-%d %H:%M')} | {direction:5s} | "
                  f"score {score:.1f} | {result.upper()} in {bars_held} candles")

    return trades


def print_summary(symbol: str, trades: list):
    if not trades:
        print(f"  {symbol}: koi qualified trade nahi mila is period mein "
              f"(SCORE_THRESHOLD={SCORE_THRESHOLD} ke saath).")
        return

    wins = [t for t in trades if t["result"] == "win"]
    losses = [t for t in trades if t["result"] == "loss"]
    win_rate = 100 * len(wins) / len(trades)
    total_gross_r = sum(t["gross_r"] for t in trades)
    total_net_r = sum(t["r"] for t in trades)
    avg_net_r = total_net_r / len(trades)

    print(f"  {symbol}:")
    print(f"    Total trades   : {len(trades)}")
    print(f"    Wins / Losses  : {len(wins)} / {len(losses)}")
    print(f"    Win Rate       : {win_rate:.1f}%")
    print(f"    Total R (gross, fees ke bina)  : {total_gross_r:+.1f}R")
    print(f"    Total R (net, fees+slippage ke baad) : {total_net_r:+.1f}R")
    print(f"    Avg net R / trade : {avg_net_r:+.3f}R")


def main():
    parser = argparse.ArgumentParser(description="Backtest aapki asli SMC/ICT strategy (master_bot.py se import karke)")
    parser.add_argument("symbol", nargs="?", help="e.g. SOLUSDT")
    parser.add_argument("--shortlist", nargs="+", default=None, help="Multiple symbols, e.g. --shortlist BTCUSDT ETHUSDT SOLUSDT")
    parser.add_argument("--days", type=int, default=90, help="Kitne din purana data (Binance 15m data ~1 saal tak available hota hai)")
    parser.add_argument("--max-hold-bars", type=int, default=50, help="Ek trade ko max kitne candles tak 'open' maanein SL/TP dhoondne ke liye")
    parser.add_argument("--commission-pct", type=float, default=0.055, help="Ek taraf (entry ya exit) ki commission %% -- Bybit taker ~0.055%%")
    parser.add_argument("--slippage-pct", type=float, default=0.03, help="Ek taraf ka estimated slippage %%")
    parser.add_argument("--timeframe", default=None,
                         help="Candle timeframe override, e.g. 1h, 4h, 15m (default: master_bot.py ka live TIMEFRAME, abhi 15m)")
    parser.add_argument("--verbose", action="store_true", help="Har individual trade dikhao, sirf summary nahi")
    parser.add_argument("--min-score", type=float, default=None,
                         help="master_bot.py ke live SCORE_THRESHOLD ko override karo, sirf is backtest run ke liye "
                              "(e.g. --min-score 70). master_bot.py mein kuch nahi badalta.")
    args = parser.parse_args()

    symbols = args.shortlist if args.shortlist else ([args.symbol] if args.symbol else [])
    if not symbols:
        parser.print_help()
        sys.exit(1)

    client = Client()  # public historical data ke liye API key zaroori nahi

    tf_display = args.timeframe or TIMEFRAME
    effective_threshold = args.min_score if args.min_score is not None else SCORE_THRESHOLD
    print(f"SMC/ICT Strategy Backtest -- SCORE_THRESHOLD={effective_threshold}"
          f"{' (override, live bot=' + str(SCORE_THRESHOLD) + ')' if args.min_score is not None else ''}, "
          f"timeframe={tf_display}, period={args.days} din")
    print("NOTE: Layer 1 (fundamental) aur Layer 2 (onchain) neutral (0.5) maan liye gaye hain -- "
          "historical whale/fundamental data free mein available nahi hota.\n")

    all_trades = []
    for symbol in symbols:
        print(f"\n=== {symbol} ===")
        trades = backtest_symbol(client, symbol, args.days, args.max_hold_bars, args.verbose,
                                  args.commission_pct, args.slippage_pct, args.timeframe,
                                  min_score=args.min_score)
        if trades is None:
            continue
        print_summary(symbol, trades)
        all_trades.extend(trades)

    if len(symbols) > 1 and all_trades:
        print("\n=== COMBINED (saare symbols) ===")
        print_summary("ALL", all_trades)

    print("\nDisclaimer: Backtest results future guarantee nahi dete. Live market mein slippage, "
          "spread, aur order-fill differences se real results alag ho sakte hain.")


if __name__ == "__main__":
    main()
