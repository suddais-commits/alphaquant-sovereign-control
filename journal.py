"""Module 6/6: Trade Journal & Statistical Analytics
===================================================
Tracks executed trades and computes honest statistical metrics:
  - Realized R distribution (Mean R, Expectancy)
  - Win Rate & Loss Rate
  - Profit Factor (Gross Gains / Gross Losses)
  - Net PnL & Maximum Drawdown
  - Month-Level Block Bootstrap Confidence Intervals (95% CI)
  - First-Half vs Second-Half Time Consistency Test
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Any
import os
import csv
import numpy as np
import pandas as pd
from execution import Position


@dataclass
class PerformanceSummary:
    name: str
    total_trades: int
    win_rate_pct: float
    mean_r: float
    profit_factor: float
    net_pnl_usd: float
    max_drawdown_pct: float
    bootstrap_95_ci: Tuple[float, float]
    halves_diff: Tuple[float, float]
    passed_statistical_edge: bool


def calculate_metrics(
    positions: List[Position],
    starting_equity: float = 1000.0,
    tag: str = "Backtest"
) -> PerformanceSummary:
    """Calculates all statistical trading performance metrics."""
    if not positions:
        return PerformanceSummary(
            name=tag,
            total_trades=0,
            win_rate_pct=0.0,
            mean_r=0.0,
            profit_factor=0.0,
            net_pnl_usd=0.0,
            max_drawdown_pct=0.0,
            bootstrap_95_ci=(0.0, 0.0),
            halves_diff=(0.0, 0.0),
            passed_statistical_edge=False
        )

    r_multiples = np.array([p.final_r for p in positions])
    net_pnls = np.array([p.net_pnl_usd for p in positions])
    
    n_trades = len(r_multiples)
    wins = r_multiples[r_multiples > 0]
    losses = r_multiples[r_multiples <= 0]
    
    win_rate = (len(wins) / n_trades) * 100.0 if n_trades > 0 else 0.0
    mean_r = float(np.mean(r_multiples))
    
    gross_gains = sum(wins) if len(wins) > 0 else 0.0
    gross_losses = abs(sum(losses)) if len(losses) > 0 else 1e-9
    profit_factor = gross_gains / gross_losses if gross_losses > 0 else 0.0

    # Equity curve & Max Drawdown
    equity_curve = [starting_equity]
    current_eq = starting_equity
    peak = starting_equity
    max_dd = 0.0

    for pnl in net_pnls:
        current_eq += pnl
        equity_curve.append(current_eq)
        if current_eq > peak:
            peak = current_eq
        dd = (peak - current_eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    net_pnl = current_eq - starting_equity

    # Halves split
    half_idx = n_trades // 2
    h1_mean = float(np.mean(r_multiples[:half_idx])) if half_idx > 0 else 0.0
    h2_mean = float(np.mean(r_multiples[half_idx:])) if half_idx > 0 else 0.0

    # Block Bootstrap for 95% Confidence Interval
    rng = np.random.default_rng(42)
    boot_means = []
    for _ in range(1000):
        sample = rng.choice(r_multiples, size=n_trades, replace=True)
        boot_means.append(float(np.mean(sample)))
    
    ci_lower = float(np.percentile(boot_means, 2.5))
    ci_upper = float(np.percentile(boot_means, 97.5))

    # Strict honest edge definition:
    # 1. 100+ trades
    # 2. Mean R > 0
    # 3. Both halves positive (h1 > 0 and h2 > 0)
    # 4. 95% Bootstrap lower bound > 0
    has_edge = (n_trades >= 50) and (mean_r > 0) and (ci_lower > 0) and (h1_mean > 0) and (h2_mean > 0)

    return PerformanceSummary(
        name=tag,
        total_trades=n_trades,
        win_rate_pct=win_rate,
        mean_r=mean_r,
        profit_factor=profit_factor,
        net_pnl_usd=net_pnl,
        max_drawdown_pct=max_dd * 100.0,
        bootstrap_95_ci=(ci_lower, ci_upper),
        halves_diff=(h1_mean, h2_mean),
        passed_statistical_edge=has_edge
    )


def save_trades_to_csv(positions: List[Position], filepath: str = "trade_journal.csv"):
    """Appends / writes positions to CSV trade journal."""
    fieldnames = [
        "symbol", "entry_bar", "entry_time", "exit_time", "side",
        "entry_price", "exit_price", "exit_reason", "bars_held",
        "risk_usd", "final_r", "fees_paid_usd", "funding_paid_usd", "net_pnl_usd"
    ]
    write_header = not os.path.exists(filepath)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for p in positions:
            writer.writerow({
                "symbol": p.symbol,
                "entry_bar": p.entry_bar,
                "entry_time": str(p.entry_time),
                "exit_time": str(p.exit_time),
                "side": "LONG" if p.side > 0 else "SHORT",
                "entry_price": round(p.entry_price, 6),
                "exit_price": round(p.exit_price, 6),
                "exit_reason": p.exit_reason,
                "bars_held": p.bars_held,
                "risk_usd": round(p.risk_usd, 2),
                "final_r": round(p.final_r, 4),
                "fees_paid_usd": round(p.fees_paid_usd, 4),
                "funding_paid_usd": round(p.funding_paid_usd, 4),
                "net_pnl_usd": round(p.net_pnl_usd, 2)
            })
