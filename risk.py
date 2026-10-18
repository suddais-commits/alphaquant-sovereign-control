"""Module 4/6: Risk Management & Position Sizing
===============================================
Institutional risk controls and capital preservation:
  1. Fractional Kelly Criterion (quarter-Kelly cap per Taleb & Ernie Chan)
  2. Robert Carver Systematic Volatility Scaling
  3. Drawdown Ladder Circuit Breakers
  4. Consecutive Loss Streak Brakes
  5. Maximum Portfolio Risk Exposure Guard
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
import math
import numpy as np
from config import RiskCfg, CONFIG
from indicators_calc import calc_carver_volatility_scalar


def calc_kelly_fraction(win_rate: float, avg_win_r: float, avg_loss_r: float = 1.0) -> float:
    """
    Computes full Kelly optimal fraction f* = (p*b - q)/b.
    Returns 0.0 if there is no statistical edge.
    """
    if avg_win_r <= 0 or avg_loss_r <= 0 or win_rate <= 0:
        return 0.0
    b = avg_win_r / avg_loss_r
    q = 1.0 - win_rate
    full_kelly = (win_rate * b - q) / b
    return max(0.0, full_kelly)


class RiskManager:
    """
    Dynamic institutional risk manager tracking portfolio equity, drawdowns,
    and applying defensive scalars.
    """
    def __init__(self, initial_equity: float = 1000.0, cfg: Optional[RiskCfg] = None):
        self.cfg = cfg or CONFIG.risk
        self.equity = float(initial_equity)
        self.peak_equity = float(initial_equity)
        self.loss_streak = 0
        self.realized_r_history: List[float] = []
        self.active_risk_usd = 0.0

    def on_trade_closed(self, pnl_usd: float, r_multiple: float):
        """Updates internal equity and loss streaks upon trade completion."""
        self.equity += pnl_usd
        self.peak_equity = max(self.peak_equity, self.equity)
        self.realized_r_history.append(r_multiple)
        if pnl_usd < 0:
            self.loss_streak += 1
        else:
            self.loss_streak = 0

    @property
    def current_drawdown(self) -> float:
        """Current equity drawdown fraction [0.0..1.0]."""
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, 1.0 - (self.equity / self.peak_equity))

    def get_drawdown_multiplier(self) -> float:
        """Applies drawdown ladder risk reduction."""
        dd = self.current_drawdown
        multiplier = 1.0
        for threshold_dd, mult in self.cfg.dd_ladder:
            if dd >= threshold_dd:
                multiplier = mult
        return multiplier

    def get_streak_multiplier(self) -> float:
        """Halves risk at 3 losses, completely halts at 5 losses."""
        if self.loss_streak >= self.cfg.loss_streak_stop:
            return 0.0
        if self.loss_streak >= self.cfg.loss_streak_half:
            return 0.50
        return 1.0

    def get_kelly_risk_cap(self) -> float:
        """
        Applies quarter-Kelly cap once 50+ trades are recorded,
        otherwise falls back to base_risk_pct.
        """
        if len(self.realized_r_history) < 50:
            return self.cfg.base_risk_pct

        wins = [r for r in self.realized_r_history if r > 0]
        losses = [-r for r in self.realized_r_history if r < 0]

        if not wins or not losses:
            return self.cfg.base_risk_pct

        win_rate = len(wins) / len(self.realized_r_history)
        avg_win = sum(wins) / len(wins)
        avg_loss = sum(losses) / len(losses)

        full_k = calc_kelly_fraction(win_rate, avg_win, avg_loss)
        fractional_k = full_k * self.cfg.kelly_fraction
        return max(0.002, min(self.cfg.max_risk_pct, fractional_k))

    def compute_position_size(
        self,
        entry_price: float,
        stop_loss_price: float,
        current_atr: float,
        tier_multiplier: float = 1.0
    ) -> Tuple[float, float, float]:
        """
        Calculates position units, risk in USD, and effective risk percentage.
        Takes into account Carver volatility scaling and drawdown brakes.
        Returns: (units, risk_usd, effective_risk_pct)
        """
        stop_distance = abs(entry_price - stop_loss_price)
        if stop_distance <= 0 or self.equity <= 0:
            return 0.0, 0.0, 0.0

        # Carver volatility scalar
        vol_scalar = calc_carver_volatility_scalar(
            current_price=entry_price,
            atr_value=current_atr,
            baseline_vol_pct=self.cfg.carver_baseline_vol
        )
        vol_scalar = max(self.cfg.carver_min_scalar, min(self.cfg.carver_max_scalar, vol_scalar))

        # Combine defensive multipliers
        dd_mult = self.get_drawdown_multiplier()
        streak_mult = self.get_streak_multiplier()
        kelly_cap = self.get_kelly_risk_cap()

        base_pct = self.cfg.base_risk_pct * tier_multiplier * vol_scalar * dd_mult * streak_mult
        effective_risk_pct = min(kelly_cap, base_pct)

        if effective_risk_pct <= 0:
            return 0.0, 0.0, 0.0

        risk_usd = self.equity * effective_risk_pct
        units = risk_usd / stop_distance

        return units, risk_usd, effective_risk_pct
