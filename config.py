"""Unified configuration loader for CryptoBot.
Loads parameters from config.yaml with typed dataclasses and fallback defaults.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

try:
    import yaml
except ImportError:
    yaml = None


@dataclass
class SystemCfg:
    live_trading_enabled: bool = False
    use_v2_gate: bool = False
    testing_mode: bool = True
    score_threshold: float = 70.0
    score_fallback_margin: float = 8.0


@dataclass
class CostCfg:
    fee_bps_per_side: float = 4.0        # Taker fee 4 bps/side
    slippage_bps: float = 5.0            # Slippage 5 bps
    funding_rate_per_8h: float = 0.0001  # 0.01% per 8h funding rate


@dataclass
class RegimeCfg:
    adx_n: int = 14
    adx_chop: float = 20.0
    adx_trend: float = 25.0
    er_n: int = 20
    er_chop: float = 0.25
    er_trend: float = 0.40
    atr_n: int = 14
    atr_rank_window: int = 100
    atr_chop_pct: float = 0.30
    bb_n: int = 20
    bb_k: float = 2.0
    squeeze_pct: float = 0.20
    squeeze_lookback: int = 5
    vol_surge: float = 1.5


@dataclass
class SetupCfg:
    donchian_period: int = 55
    reversal_atr_mult: float = 1.5
    require_closed_candles: bool = True
    min_rr_ratio: float = 3.0
    max_sl_pct: float = 0.05
    sl_atr_mult: float = 2.0


@dataclass
class FilterCfg:
    min_tf_agreement: float = 0.55
    htf_gate: tuple = ("1D", "4H")
    tf_weights: dict = field(default_factory=lambda: {
        "1M": 1.0, "1W": 2.0, "1D": 3.0, "4H": 3.0, "1H": 2.0, "15m": 1.0, "5m": 0.5, "1m": 0.5
    })
    gemini_enabled: bool = False
    gemini_model: str = "gemini-2.5-flash"
    gemini_fail_closed: bool = True
    gemini_min_score: float = 0.60
    min_quality_score: float = 0.40
    below_min_risk_mult: float = 0.50
    z_score_period: int = 20
    max_fomo_long_z: float = 2.2
    min_panic_short_z: float = -2.2


@dataclass
class ScoreCfg:
    full_score: float = 83.0
    mid_score: float = 65.0
    full_mult: float = 1.0
    mid_mult: float = 0.5
    chop_max_mult: float = 0.5
    min_tf_agreement: float = 0.55
    tf_weights: dict = field(default_factory=lambda: {
        "1M": 1.0, "1W": 2.0, "1D": 3.0, "4H": 3.0, "1H": 2.0, "15m": 1.0, "5m": 0.5, "1m": 0.5
    })
    htf_gate: tuple = ("1D", "4H")
    groups: dict = field(default_factory=lambda: {
        "structure": ["a02_sweep_choch", "a03_ob_fvg", "a05_wyckoff"],
        "flow":      ["a04_vsa_cvd", "a09_whale_ratio"],
        "trend":     ["a01_mtf_trend", "a06_sr_hvn"],
        "pattern":   ["a08_candles"],
    })
    agent_weights: dict = field(default_factory=lambda: {
        "a09_whale_ratio": 0.10,
    })
    group_weights_by_regime: dict = field(default_factory=lambda: {
        "TREND":      {"structure": 0.30, "flow": 0.25, "trend": 0.35, "pattern": 0.10},
        "BREAKOUT":   {"structure": 0.20, "flow": 0.40, "trend": 0.30, "pattern": 0.10},
        "CHOP":       {"structure": 0.45, "flow": 0.30, "trend": 0.05, "pattern": 0.20},
        "TRANSITION": {"structure": 0.35, "flow": 0.25, "trend": 0.25, "pattern": 0.15},
    })


@dataclass
class RiskCfg:
    base_risk_pct: float = 0.01       # 1% equity risk
    max_risk_pct: float = 0.02
    kelly_fraction: float = 0.25
    max_open_trades: int = 8
    max_portfolio_risk_pct: float = 0.08
    loss_streak_half: int = 3
    loss_streak_stop: int = 5
    dd_ladder: tuple = ((0.10, 0.50), (0.15, 0.25), (0.20, 0.0))
    carver_baseline_vol: float = 0.02
    carver_min_scalar: float = 0.50
    carver_max_scalar: float = 1.25


@dataclass
class ExecutionCfg:
    mode: str = "tp_ladder"            # "tp_ladder" or "be_trailing"
    max_bars: int = 400
    be_at_r: float = 2.0
    tp1_r: float = 3.0
    tp1_frac: float = 0.30
    tp2_r: float = 5.0
    tp2_frac: float = 0.30
    tp2_trail_to_r: float = 2.5
    runner_frac: float = 0.40
    trail_activation_r: float = 2.0
    trail_atr_mult: float = 3.0


@dataclass
class AppConfig:
    system: SystemCfg = field(default_factory=SystemCfg)
    costs: CostCfg = field(default_factory=CostCfg)
    regime: RegimeCfg = field(default_factory=RegimeCfg)
    setup: SetupCfg = field(default_factory=SetupCfg)
    filters: FilterCfg = field(default_factory=FilterCfg)
    scoring: ScoreCfg = field(default_factory=ScoreCfg)
    risk: RiskCfg = field(default_factory=RiskCfg)
    execution: ExecutionCfg = field(default_factory=ExecutionCfg)


def load_config(yaml_path: str = "config.yaml") -> AppConfig:
    """Loads configuration from YAML file, falling back to defaults if missing."""
    cfg = AppConfig()
    if not os.path.exists(yaml_path):
        return cfg

    if yaml is None:
        return cfg

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        if "system" in raw:
            s = raw["system"]
            cfg.system = SystemCfg(
                live_trading_enabled=s.get("live_trading_enabled", False),
                use_v2_gate=s.get("use_v2_gate", False),
                testing_mode=s.get("testing_mode", True),
                score_threshold=float(s.get("score_threshold", 83.0)),
                score_fallback_margin=float(s.get("score_fallback_margin", 8.0)),
            )

        if "costs" in raw:
            c = raw["costs"]
            cfg.costs = CostCfg(
                fee_bps_per_side=float(c.get("fee_bps_per_side", 4.0)),
                slippage_bps=float(c.get("slippage_bps", 5.0)),
                funding_rate_per_8h=float(c.get("funding_rate_per_8h", 0.0001)),
            )

        if "regime" in raw:
            r = raw["regime"]
            cfg.regime = RegimeCfg(
                adx_n=int(r.get("adx_period", 14)),
                adx_chop=float(r.get("adx_chop_threshold", 20.0)),
                adx_trend=float(r.get("adx_trend_threshold", 25.0)),
                er_n=int(r.get("er_period", 20)),
                er_chop=float(r.get("er_chop_threshold", 0.25)),
                er_trend=float(r.get("er_trend_threshold", 0.40)),
                atr_n=int(r.get("atr_period", 14)),
                atr_rank_window=int(r.get("atr_rank_window", 100)),
                atr_chop_pct=float(r.get("atr_chop_percentile", 0.30)),
                bb_n=int(r.get("bb_period", 20)),
                bb_k=float(r.get("bb_std", 2.0)),
                squeeze_pct=float(r.get("bb_squeeze_percentile", 0.20)),
                squeeze_lookback=int(r.get("squeeze_lookback", 5)),
                vol_surge=float(r.get("vol_surge_mult", 1.5)),
            )

        if "setup" in raw:
            st = raw["setup"]
            cfg.setup = SetupCfg(
                donchian_period=int(st.get("donchian_period", 55)),
                reversal_atr_mult=float(st.get("reversal_atr_mult", 1.5)),
                require_closed_candles=bool(st.get("require_closed_candles", True)),
                min_rr_ratio=float(st.get("min_rr_ratio", 2.0)),
                max_sl_pct=float(st.get("max_sl_pct", 0.05)),
                sl_atr_mult=float(st.get("sl_atr_mult", 2.0)),
            )

        if "risk" in raw:
            rk = raw["risk"]
            dd_list = tuple((float(x[0]), float(x[1])) for x in rk.get("drawdown_ladder", [[0.10, 0.50], [0.15, 0.25], [0.20, 0.0]]))
            carver = rk.get("carver", {})
            cfg.risk = RiskCfg(
                base_risk_pct=float(rk.get("base_risk_pct", 0.01)),
                max_risk_pct=float(rk.get("max_risk_pct", 0.02)),
                kelly_fraction=float(rk.get("kelly_fraction", 0.25)),
                max_open_trades=int(rk.get("max_open_trades", 8)),
                max_portfolio_risk_pct=float(rk.get("max_portfolio_risk_pct", 0.08)),
                loss_streak_half=int(rk.get("loss_streak_half", 3)),
                loss_streak_stop=int(rk.get("loss_streak_stop", 5)),
                dd_ladder=dd_list,
                carver_baseline_vol=float(carver.get("baseline_vol_pct", 0.02)),
                carver_min_scalar=float(carver.get("min_scalar", 0.50)),
                carver_max_scalar=float(carver.get("max_scalar", 1.25)),
            )

        if "execution" in raw:
            ex = raw["execution"]
            tpl = ex.get("tp_ladder", {})
            bet = ex.get("be_trailing", {})
            cfg.execution = ExecutionCfg(
                mode=str(ex.get("mode", "tp_ladder")),
                max_bars=int(ex.get("max_bars_in_trade", 400)),
                be_at_r=float(ex.get("be_at_r", 2.0)),
                tp1_r=float(tpl.get("tp1_r", 3.0)),
                tp1_frac=float(tpl.get("tp1_frac", 0.30)),
                tp2_r=float(tpl.get("tp2_r", 5.0)),
                tp2_frac=float(tpl.get("tp2_frac", 0.30)),
                tp2_trail_to_r=float(tpl.get("tp2_trail_to_r", 2.5)),
                runner_frac=float(tpl.get("runner_frac", 0.40)),
                trail_activation_r=float(bet.get("activation_r", 2.0)),
                trail_atr_mult=float(bet.get("trail_atr_mult", 3.0)),
            )

    except Exception as e:
        print(f"Warning: error loading {yaml_path}: {e}. Using defaults.")

    return cfg


# Global singleton instance
CONFIG = load_config()
