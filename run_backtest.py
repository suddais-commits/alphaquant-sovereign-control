"""
Standalone Backtest Tool -- TradingView MCP se liya gaya
---------------------------------------------------------
Ye master_bot.py se ALAG chalta hai -- bot ki live scanning loop mein
kuch nahi karta, sirf aap manually chalate hain jab kisi coin/strategy
ko history par verify karna ho ("backtesting ka gap fill" wala tool).

Data source: Yahoo Finance (free, koi API key nahi chahiye). Crypto ke
liye symbol format "BTC-USD", "ETHUSDT" ka ETH-USD, "SOLUSDT" ka SOL-USD
waghera hota hai -- neeche USDT_TO_YAHOO helper khud convert kar deta hai.

9 strategies available: rsi, bollinger, macd, ema_cross, supertrend,
donchian, rsi_pullback, keltner_breakout, triple_ema

USAGE (Command Prompt mein, isi folder ke andar):

  # Ek coin par ek strategy test karo
  python run_backtest.py SOLUSDT ema_cross

  # Ek coin par SAARI 9 strategies compare karo (best/worst dikhayega)
  python run_backtest.py SOLUSDT --compare

  # Poore shortlist (Layer 0 jaisa) par best strategy dhoondo
  python run_backtest.py --shortlist BTCUSDT ETHUSDT SOLUSDT ADAUSDT --compare

  # Period/interval change karna ho
  python run_backtest.py SOLUSDT ema_cross --period 6mo --interval 1h
"""

import argparse
import json
import sys

from backtest_service import run_backtest, compare_strategies, walk_forward_backtest


def usdt_to_yahoo(symbol: str) -> str:
    """'SOLUSDT' -> 'SOL-USD' (Yahoo Finance ka crypto ticker format)."""
    symbol = symbol.upper().strip()
    if symbol.endswith("USDT"):
        base = symbol[:-4]
        return f"{base}-USD"
    if "-" in symbol:
        return symbol  # already Yahoo format
    return symbol


def print_single_result(res: dict):
    if "error" in res:
        print(f"  ERROR: {res['error']}")
        return
    print(f"  Symbol           : {res['symbol']}")
    print(f"  Strategy         : {res['strategy_label']}")
    print(f"  Period / Interval: {res['period']} / {res['interval']}")
    print(f"  Candles analyzed : {res['candles_analyzed']}  ({res['date_from']} -> {res['date_to']})")
    print(f"  Total return     : {res['total_return_pct']}%")
    print(f"  Buy & Hold return: {res['buy_and_hold_return_pct']}%  (vs strategy: {res['vs_buy_and_hold_pct']}%)")
    print(f"  Win rate         : {res['win_rate_pct']}%   Total trades: {res['total_trades']}")
    print(f"  Profit factor    : {res['profit_factor']}")
    print(f"  Sharpe ratio     : {res['sharpe_ratio']}")
    print(f"  Calmar ratio     : {res['calmar_ratio']}")
    print(f"  Max drawdown     : {res['max_drawdown_pct']}%")
    print(f"  Expectancy/trade : {res['expectancy_pct']}%")


def print_compare_result(res: dict):
    if "error" in res:
        print(f"  ERROR: {res['error']}")
        return
    print(f"  Symbol: {res['symbol']}   Period: {res['period']}/{res['interval']}   "
          f"Buy&Hold: {res['buy_and_hold_return_pct']}%")
    if res.get("warnings"):
        print(f"  NOTE: {res['warnings']}")
    print(f"  {'Rank':<5}{'Strategy':<22}{'Return%':<10}{'WinRate%':<10}{'Trades':<8}{'Sharpe':<8}{'Calmar':<8}{'MaxDD%'}")
    for r in res["ranking"]:
        print(f"  {r['rank']:<5}{r['strategy']:<22}{r['total_return_pct']:<10}{r['win_rate_pct']:<10}"
              f"{r['total_trades']:<8}{r['sharpe_ratio']:<8}{r['calmar_ratio']:<8}{r['max_drawdown_pct']}")
    print(f"  WINNER: {res['winner']}")


def main():
    parser = argparse.ArgumentParser(description="Standalone crypto backtest tool (TradingView MCP engine)")
    parser.add_argument("symbol", nargs="?", help="e.g. SOLUSDT (ya SOL-USD)")
    parser.add_argument("strategy", nargs="?", default=None,
                         help="rsi | bollinger | macd | ema_cross | supertrend | donchian | "
                              "rsi_pullback | keltner_breakout | triple_ema")
    parser.add_argument("--shortlist", nargs="+", default=None,
                         help="Multiple symbols ek saath test karne ke liye, e.g. --shortlist BTCUSDT ETHUSDT SOLUSDT")
    parser.add_argument("--compare", action="store_true", help="Ek symbol par saari 9 strategies compare karo")
    parser.add_argument("--walk-forward", action="store_true",
                         help="Overfitting check (train/test split) -- --strategy ke saath use karo")
    parser.add_argument("--period", default="1y", choices=["1mo", "3mo", "6mo", "1y", "2y"])
    parser.add_argument("--interval", default="1d", choices=["1d", "1h"])
    parser.add_argument("--capital", type=float, default=1000.0, help="Backtest ka starting capital (USD)")
    parser.add_argument("--json", action="store_true", help="Raw JSON output (agar aapko file mein save karna ho)")
    args = parser.parse_args()

    symbols = args.shortlist if args.shortlist else ([args.symbol] if args.symbol else [])
    if not symbols:
        parser.print_help()
        sys.exit(1)

    for raw_symbol in symbols:
        yahoo_symbol = usdt_to_yahoo(raw_symbol)
        print(f"\n=== {raw_symbol} ({yahoo_symbol}) ===")

        if args.walk_forward:
            if not args.strategy:
                print("  --walk-forward ke liye strategy naam bhi dein, e.g.: python run_backtest.py SOLUSDT ema_cross --walk-forward")
                continue
            res = walk_forward_backtest(yahoo_symbol, args.strategy, period=args.period,
                                         initial_capital=args.capital, interval=args.interval)
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(json.dumps(res, indent=2))  # walk-forward output structured hai, JSON hi readable hai
            continue

        if args.compare or not args.strategy:
            res = compare_strategies(yahoo_symbol, period=args.period, initial_capital=args.capital, interval=args.interval)
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print_compare_result(res)
        else:
            res = run_backtest(yahoo_symbol, args.strategy, period=args.period,
                                initial_capital=args.capital, interval=args.interval)
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print_single_result(res)

    print("\nDisclaimer: Past performance future ki guarantee nahi hai. Ye sirf research/education ke liye hai.")


if __name__ == "__main__":
    main()
