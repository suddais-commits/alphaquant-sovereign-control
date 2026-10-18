"""Walk-Forward 12-Month 1H Backtest Engine
===========================================
Strict Honest Testing Protocol:
  - 30 crypto pairs on 1H timeframe
  - Walk-forward 70/30 split (70% In-Sample, 30% Out-of-Sample)
  - Costs modeled: 4 bps/side fees, 5 bps slippage, 0.01%/8h funding
  - Closed candle signals, next-bar open execution
  - Intra-bar conservative rule: SL hit before TP if both touched in same bar
  - Compares:
      Mode A: Break-even + Trailing Stop (BE @ 2R, 3x ATR trail)
      Mode B: Multi-target TP Ladder (30% @ 2R, 30% @ 5R, 40% Runner trailing @ 2.5R)
"""
from __future__ import annotations
import os
import glob
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple

from config import load_config, CONFIG
from regime import classify_regime, calc_atr
from setup import build_candidate_setups, TradeSetup
from filters import evaluate_htf_gate, evaluate_z_score_filter
from risk import RiskManager
from execution import simulate_trade_execution, Position
from journal import calculate_metrics, PerformanceSummary, save_trades_to_csv


def load_all_1h_data(cache_dir: str = "edge_cache", max_bars: int = 8760) -> Dict[str, pd.DataFrame]:
    """Loads up to 12 months (8,760 1H bars) for all available coins."""
    files = glob.glob(os.path.join(cache_dir, "*_1h.csv"))
    data = {}
    for f in files:
        sym = os.path.basename(f).replace("_1h.csv", "")
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
            df = df.sort_index()
            # Clean numeric columns
            for col in ["open", "high", "low", "close", "volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna().tail(max_bars)
            if len(df) >= 1000:
                data[sym] = df
        except Exception as e:
            print(f"Error loading {f}: {e}")
    return data


def run_backtest_for_period(
    data: Dict[str, pd.DataFrame],
    mode: str = "tp_ladder",
    start_ratio: float = 0.0,
    end_ratio: float = 1.0,
    starting_equity: float = 1000.0,
    tag: str = "Test"
) -> Tuple[List[Position], PerformanceSummary]:
    """Runs realistic backtest on specified time slice across all coins."""
    risk_mgr = RiskManager(initial_equity=starting_equity, cfg=CONFIG.risk)
    all_closed_positions: List[Position] = []

    for sym, df in data.items():
        n_bars = len(df)
        start_idx = int(n_bars * start_ratio)
        end_idx = int(n_bars * end_ratio)
        
        slice_df = df.iloc[start_idx:end_idx].copy()
        if len(slice_df) < 100:
            continue

        # 1. Regime & ATR calculation
        reg_df = classify_regime(slice_df, CONFIG.regime)
        atr_s = reg_df["atr"]

        # 2. Setup generation
        setups = build_candidate_setups(sym, slice_df, atr_s, CONFIG.setup)

        # 3. Simulate sequential execution
        for setup in setups:
            if not setup.is_valid:
                continue

            bar_i = setup.bar_index
            if bar_i >= len(slice_df) - 1:
                continue

            # Z-Score climax filter
            closes_so_far = slice_df["close"].iloc[:bar_i].values
            z_ok, z_val = evaluate_z_score_filter(closes_so_far, setup.side)
            if not z_ok:
                continue

            # Position sizing
            units, risk_usd, eff_pct = risk_mgr.compute_position_size(
                entry_price=setup.entry_price,
                stop_loss_price=setup.stop_loss,
                current_atr=setup.atr,
                tier_multiplier=1.0
            )

            if units <= 0 or risk_usd <= 0:
                continue

            # Execute forward
            pos = simulate_trade_execution(
                setup=setup,
                df=slice_df,
                start_idx=bar_i,
                risk_usd=risk_usd,
                units=units,
                mode=mode,
                exec_cfg=CONFIG.execution,
                cost_cfg=CONFIG.costs
            )

            if pos.is_closed:
                risk_mgr.on_trade_closed(pos.net_pnl_usd, pos.final_r)
                all_closed_positions.append(pos)

    # Sort positions by entry time
    all_closed_positions.sort(key=lambda p: str(p.entry_time))
    summary = calculate_metrics(all_closed_positions, starting_equity=starting_equity, tag=tag)
    return all_closed_positions, summary


def main():
    print("=" * 80)
    print("CRYPTOBOT 12-MONTH 1H WALK-FORWARD BACKTEST (70/30 SPLIT)")
    print("Taker Fees: 4 bps/side | Slippage: 5 bps | Funding: 0.01%/8h")
    print("=" * 80)

    data = load_all_1h_data()
    print(f"Loaded {len(data)} coins with 1H data.")
    if not data:
        print("No 1H data found in edge_cache/. Exiting.")
        return

    results = []

    # 1. Break-Even + Trailing Stop
    print("\n[1/2] Running Mode: BE + Trailing Stop (BE @ 2R, 3x ATR Trail)...")
    is_pos_trail, is_sum_trail = run_backtest_for_period(data, mode="be_trailing", start_ratio=0.0, end_ratio=0.70, tag="BE+Trailing [In-Sample 70%]")
    oos_pos_trail, oos_sum_trail = run_backtest_for_period(data, mode="be_trailing", start_ratio=0.70, end_ratio=1.0, tag="BE+Trailing [Out-Of-Sample 30%]")

    # 2. Multi-Target Take-Profit Ladder
    print("\n[2/2] Running Mode: Multi-Target TP Ladder (30% @ 2R, 30% @ 5R, 40% Runner)...")
    is_pos_ladder, is_sum_ladder = run_backtest_for_period(data, mode="tp_ladder", start_ratio=0.0, end_ratio=0.70, tag="TP Ladder [In-Sample 70%]")
    oos_pos_ladder, oos_sum_ladder = run_backtest_for_period(data, mode="tp_ladder", start_ratio=0.70, end_ratio=1.0, tag="TP Ladder [Out-Of-Sample 30%]")

    # Print Comparative Report
    report_lines = [
        "",
        "==========================================================================================",
        "                                WALK-FORWARD TEST RESULTS                                 ",
        "==========================================================================================",
        f"{'Configuration / Sample':<35} | {'Trades':<6} | {'Win Rate':<8} | {'Mean R':<8} | {'PF':<5} | {'Net PnL':<10} | {'Max DD':<7} | {'Edge Pass'}",
        "-" * 106,
    ]

    for s in [is_sum_trail, oos_sum_trail, is_sum_ladder, oos_sum_ladder]:
        pnl_str = f"${s.net_pnl_usd:+0.2f}"
        edge_str = "PASS" if s.passed_statistical_edge else "FAIL"
        report_lines.append(
            f"{s.name:<35} | {s.total_trades:<6} | {s.win_rate_pct:>6.1f}% | {s.mean_r:>+7.3f}R | {s.profit_factor:>4.2f} | {pnl_str:>10} | {s.max_drawdown_pct:>5.1f}% | {edge_str}"
        )
        report_lines.append(
            f"   -> 95% Bootstrap CI: [{s.bootstrap_95_ci[0]:+.3f}R, {s.bootstrap_95_ci[1]:+.3f}R] | Halves (H1/H2): {s.halves_diff[0]:+.3f}R / {s.halves_diff[1]:+.3f}R"
        )
        report_lines.append("-" * 106)

    report_text = "\n".join(report_lines)
    with open("walkforward_backtest_results.txt", "w", encoding="utf-8") as f:
        f.write(report_text)

    try:
        print(report_text)
    except Exception:
        print("Results written to walkforward_backtest_results.txt successfully.")

    save_trades_to_csv(oos_pos_ladder, "trade_journal.csv")
    print("\nSaved detailed out-of-sample trades to trade_journal.csv and summary to walkforward_backtest_results.txt.")


if __name__ == "__main__":
    main()
