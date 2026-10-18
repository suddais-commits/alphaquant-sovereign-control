"""Module 5/6: Execution Engine & Realistic Simulation
===================================================
Handles order lifecycle, cost accounting, and exit dynamics:
  - Taker Fees (4 bps per side = 8 bps round trip)
  - Slippage (5 bps = 0.05% per fill)
  - Funding Rates (0.01% per 8h = 0.03% per day)
  - Intra-bar worst-case collision: Stop loss assumed hit before target if both triggered in same bar
  - Exit Modes:
      A) BE + Trailing Stop (Break-even at 2R, trailing with 3x ATR)
      B) Multi-target TP Ladder (TP1 at 2R 30%, TP2 at 5R 30%, Runner 40%)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Any
import numpy as np
import pandas as pd
from config import ExecutionCfg, CostCfg, CONFIG
from setup import TradeSetup


@dataclass
class Position:
    symbol: str
    entry_bar: int
    entry_time: Any
    side: int              # +1 LONG, -1 SHORT
    entry_price: float
    current_stop: float
    initial_stop: float
    risk_r_dist: float
    risk_usd: float
    units: float
    mode: str              # "tp_ladder" or "be_trailing"
    
    # State tracking
    remaining_fraction: float = 1.0
    realized_r: float = 0.0
    is_be_active: bool = False
    tp_state: int = 0      # 0: none, 1: TP1 hit, 2: TP2 hit
    best_price: float = 0.0
    bars_held: int = 0
    is_closed: bool = False
    exit_price: float = 0.0
    exit_time: Any = None
    exit_reason: str = ""
    funding_paid_usd: float = 0.0
    fees_paid_usd: float = 0.0
    net_pnl_usd: float = 0.0
    final_r: float = 0.0


def simulate_trade_execution(
    setup: TradeSetup,
    df: pd.DataFrame,
    start_idx: int,
    risk_usd: float,
    units: float,
    mode: str = "tp_ladder",
    exec_cfg: Optional[ExecutionCfg] = None,
    cost_cfg: Optional[CostCfg] = None
) -> Position:
    """
    Simulates forward execution bar-by-bar from start_idx to exit or max_bars.
    Enforces honest worst-case execution rules:
      - Entry price adjusted for slippage
      - Stop loss hits assumed first if both high/low touch stop and target
      - Slippage applied on exits
      - Fees & 8-hour funding rates deducted
    """
    exec_cfg = exec_cfg or CONFIG.execution
    cost_cfg = cost_cfg or CONFIG.costs

    fee_rate = cost_cfg.fee_bps_per_side / 10000.0
    slip_rate = cost_cfg.slippage_bps / 10000.0
    funding_rate_per_bar = (cost_cfg.funding_rate_per_8h / 8.0) # approx per 1h bar

    # Apply entry slippage
    actual_entry = setup.entry_price * (1.0 + setup.side * slip_rate)
    initial_stop = setup.stop_loss
    risk_dist = abs(actual_entry - initial_stop)
    if risk_dist <= 0:
        risk_dist = actual_entry * 0.02

    pos = Position(
        symbol=setup.symbol,
        entry_bar=start_idx,
        entry_time=df.index[start_idx] if start_idx < len(df) else None,
        side=setup.side,
        entry_price=actual_entry,
        current_stop=initial_stop,
        initial_stop=initial_stop,
        risk_r_dist=risk_dist,
        risk_usd=risk_usd,
        units=units,
        mode=mode,
        best_price=actual_entry
    )

    # Initial entry fee
    pos.fees_paid_usd += (actual_entry * units) * fee_rate

    n_bars = len(df)
    for i in range(start_idx, min(start_idx + exec_cfg.max_bars, n_bars)):
        bar_high = float(df["high"].iloc[i])
        bar_low = float(df["low"].iloc[i])
        bar_close = float(df["close"].iloc[i])
        pos.bars_held += 1
        pos.funding_paid_usd += (actual_entry * units * pos.remaining_fraction) * funding_rate_per_bar

        # Check Stop Loss Hit (Conservative check first)
        is_stop_hit = (bar_low <= pos.current_stop) if pos.side > 0 else (bar_high >= pos.current_stop)
        
        if is_stop_hit:
            exit_px = pos.current_stop * (1.0 - pos.side * slip_rate)
            exit_r = pos.side * (exit_px - actual_entry) / risk_dist
            pos.realized_r += pos.remaining_fraction * exit_r
            pos.fees_paid_usd += (exit_px * units * pos.remaining_fraction) * fee_rate
            pos.remaining_fraction = 0.0
            pos.is_closed = True
            pos.exit_price = exit_px
            pos.exit_time = df.index[i]
            pos.exit_reason = "STOP_LOSS"
            break

        # Favorable excursion in bar
        fav_price = bar_high if pos.side > 0 else bar_low
        r_favorable = pos.side * (fav_price - actual_entry) / risk_dist
        pos.best_price = max(pos.best_price, bar_high) if pos.side > 0 else min(pos.best_price, bar_low)

        if mode == "tp_ladder":
            # 1. Break-Even Check
            if not pos.is_be_active and r_favorable >= exec_cfg.be_at_r:
                pos.current_stop = actual_entry
                pos.is_be_active = True

            # 2. TP1 Execution (30%)
            if pos.tp_state == 0 and r_favorable >= exec_cfg.tp1_r:
                pos.realized_r += exec_cfg.tp1_frac * exec_cfg.tp1_r
                pos.remaining_fraction -= exec_cfg.tp1_frac
                pos.fees_paid_usd += (setup.tp1_price * units * exec_cfg.tp1_frac) * fee_rate
                pos.tp_state = 1
                pos.current_stop = actual_entry  # Lock BE

            # 3. TP2 Execution (30%)
            if pos.tp_state == 1 and r_favorable >= exec_cfg.tp2_r:
                pos.realized_r += exec_cfg.tp2_frac * exec_cfg.tp2_r
                pos.remaining_fraction -= exec_cfg.tp2_frac
                pos.fees_paid_usd += (setup.tp2_price * units * exec_cfg.tp2_frac) * fee_rate
                pos.tp_state = 2
                # Trail stop to +2.5R for the remaining 40% runner
                pos.current_stop = actual_entry + (pos.side * exec_cfg.tp2_trail_to_r * risk_dist)

        elif mode == "be_trailing":
            # 1. Break-Even at 2R
            if not pos.is_be_active and r_favorable >= exec_cfg.trail_activation_r:
                pos.current_stop = actual_entry
                pos.is_be_active = True

            # 2. Dynamic ATR Trailing
            if pos.is_be_active:
                atr_val = setup.atr if setup.atr > 0 else actual_entry * 0.02
                new_trail_stop = pos.best_price - (pos.side * exec_cfg.trail_atr_mult * atr_val)
                if pos.side > 0 and new_trail_stop > pos.current_stop:
                    pos.current_stop = new_trail_stop
                elif pos.side < 0 and new_trail_stop < pos.current_stop:
                    pos.current_stop = new_trail_stop

        # Max Bars Time Barrier Exit
        if pos.bars_held >= exec_cfg.max_bars and not pos.is_closed:
            exit_px = bar_close * (1.0 - pos.side * slip_rate)
            exit_r = pos.side * (exit_px - actual_entry) / risk_dist
            pos.realized_r += pos.remaining_fraction * exit_r
            pos.fees_paid_usd += (exit_px * units * pos.remaining_fraction) * fee_rate
            pos.remaining_fraction = 0.0
            pos.is_closed = True
            pos.exit_price = exit_px
            pos.exit_time = df.index[i]
            pos.exit_reason = "TIME_BARRIER"
            break

    # Final PnL and R calculation
    pos.final_r = pos.realized_r
    gross_pnl_usd = pos.final_r * pos.risk_usd
    pos.net_pnl_usd = gross_pnl_usd - pos.fees_paid_usd - pos.funding_paid_usd
    return pos
