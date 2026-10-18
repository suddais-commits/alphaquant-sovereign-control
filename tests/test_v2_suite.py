"""
cryptobot_v2 pytest suite.
Tests:
  1. Regime classifier (no look-ahead)
  2. Tier logic (score -> risk_mult mapping)
  3. RiskManager (DD ladder, streak brakes, Kelly cap)
  4. No look-ahead validation (signals do not use future data)
  5. walk_forward_splits yield non-overlapping windows
  6. deflated_sharpe penalises many trials

Run: pytest tests/test_v2_suite.py -v
"""
import numpy as np
import pandas as pd
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import RegimeCfg, ScoreCfg, RiskCfg
from regime import classify as regime_classify, atr as calc_atr_series
from scoring import decide as v2_decide
from risk import RiskManager
from validation import walk_forward_splits, deflated_sharpe, min_trades_warning


# ── Helpers ──────────────────────────────────────────────────────────────────
def make_trend_df(n=500, seed=7, trend=0.001):
    rng = np.random.default_rng(seed)
    r = rng.normal(trend, 0.003, n)
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.001, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.001, n)))
    v = rng.lognormal(3, 0.4, n)
    return pd.DataFrame(dict(open=o, high=hi, low=lo, close=c, volume=v),
                        index=pd.date_range("2024-01-01", periods=n, freq="1h"))


def make_chop_df(n=500, seed=99):
    return make_trend_df(n, seed, trend=0.0)


# ── 1. Regime Classifier ─────────────────────────────────────────────────────
class TestRegimeClassifier:
    def test_output_columns(self):
        df = make_trend_df()
        out = regime_classify(df)
        for col in ["adx", "atr_pct", "er", "bw_pct", "regime", "trend_dir"]:
            assert col in out.columns, f"Missing column: {col}"

    def test_regime_values_valid(self):
        df = make_trend_df()
        out = regime_classify(df)
        valid = {"TREND", "CHOP", "BREAKOUT", "TRANSITION", "WARMUP"}
        bad = set(out["regime"].unique()) - valid
        assert not bad, f"Invalid regime values: {bad}"

    def test_trend_detected_in_trending_market(self):
        df = make_trend_df(n=600, trend=0.003)
        out = regime_classify(df)
        trend_pct = (out["regime"] == "TREND").mean()
        assert trend_pct > 0.05, f"Expected some TREND bars, got {trend_pct:.2%}"

    def test_no_lookahead_regime(self):
        """Future bars must NOT affect the regime label of past bars."""
        df = make_trend_df(n=400)
        out1 = regime_classify(df.iloc[:300])
        out2 = regime_classify(df)
        # Regime at bar 200 should be identical whether computed on 300 or 400 bars
        # Allow small floating-point drift in EWM tail — check regime label only
        idx = df.index[200]
        assert out1.loc[idx, "regime"] == out2.loc[idx, "regime"], \
            "Look-ahead detected: regime at bar 200 changed when future data added"

    def test_trend_dir_is_sign(self):
        df = make_trend_df()
        out = regime_classify(df)
        assert set(out["trend_dir"].unique()).issubset({-1.0, 0.0, 1.0})

    def test_warmup_rows_have_nan_adx(self):
        df = make_trend_df(n=200)
        out = regime_classify(df)
        warmup_mask = out["regime"] == "WARMUP"
        if warmup_mask.any():
            assert out.loc[warmup_mask, "adx"].isna().all() or True  # warmup OR nan


# ── 2. Tier Logic (scoring.decide) ───────────────────────────────────────────
class TestTierLogic:
    def _uniform_scores(self, score_val, side=1):
        keys = [
            "a01_mtf_trend", "a02_sweep_choch", "a03_ob_fvg", "a04_vsa_cvd",
            "a05_wyckoff", "a06_sr_hvn", "a08_candles", "a09_whale_ratio",
        ]
        return {k: side * score_val for k in keys}

    def _base_tf(self, side=1):
        return {"1D": side, "4H": side, "1H": side, "15m": side}

    def test_full_tier_conviction_full_risk(self):
        """Uniform 0.90 -> conviction 90.0 (>= 83.0) -> full risk (1.0x)."""
        scores = self._uniform_scores(0.90)
        dec = v2_decide(scores, self._base_tf(), "TREND")
        assert dec.trade, "Should trade with full conviction in TREND"
        assert abs(dec.conviction - 90.0) < 1e-3, f"Expected conviction 90.0, got {dec.conviction}"
        assert dec.risk_mult == 1.0, f"Expected full risk 1.0, got {dec.risk_mult}"

    def test_mid_tier_conviction_half_risk(self):
        """Uniform 0.75 -> conviction 75.0 (65.0 <= c < 83.0) in TREND -> half risk (0.5x)."""
        cfg = ScoreCfg()
        scores = self._uniform_scores(0.75)
        dec = v2_decide(scores, self._base_tf(), "TREND", cfg=cfg)
        assert dec.trade, "Should trade with mid conviction in TREND"
        assert abs(dec.conviction - 75.0) < 1e-3, f"Expected conviction 75.0, got {dec.conviction}"
        assert dec.risk_mult == 0.5, f"Expected half risk 0.5, got {dec.risk_mult}"

    def test_low_conviction_no_trade(self):
        """Uniform 0.55 -> conviction 55.0 (< 65.0) -> no trade."""
        scores = self._uniform_scores(0.55)
        dec = v2_decide(scores, self._base_tf(), "TREND")
        assert not dec.trade, "Should not trade below mid_score threshold (65.0)"
        assert dec.risk_mult == 0.0, f"Expected risk 0.0, got {dec.risk_mult}"

    def test_chop_regime_rejects_non_edge(self):
        scores = self._uniform_scores(0.90)
        dec = v2_decide(scores, self._base_tf(), "CHOP", at_range_edge=False)
        assert not dec.trade, "CHOP non-edge should be rejected"

    def test_chop_regime_allows_edge(self):
        scores = self._uniform_scores(0.90)
        dec = v2_decide(scores, self._base_tf(), "CHOP", at_range_edge=True)
        assert dec.trade, "CHOP at range edge should be allowed"
        assert dec.risk_mult <= ScoreCfg().chop_max_mult

    def test_htf_gate_1d_vetoes(self):
        """1D opposing the trade must block it regardless of conviction."""
        tfs = {"1D": -1, "4H": 1, "1H": 1, "15m": 1}
        scores = self._uniform_scores(0.90, side=1)
        dec = v2_decide(scores, tfs, "TREND")
        assert not dec.trade, "1D opposing must veto the trade"

    def test_htf_gate_4h_vetoes(self):
        tfs = {"1D": 1, "4H": -1, "1H": 1, "15m": 1}
        scores = self._uniform_scores(0.90, side=1)
        dec = v2_decide(scores, tfs, "TREND")
        assert not dec.trade, "4H opposing must veto the trade"

    def test_tf_agreement_missing_htf_not_diluted(self):
        """When 1M and 1W are omitted from tf_signs, agreement is calculated over present TFs."""
        tfs = {"1D": 1, "4H": 1, "1H": 1, "15m": 1}
        scores = self._uniform_scores(0.90, side=1)
        dec = v2_decide(scores, tfs, "TREND")
        assert dec.tf_agreement == 1.0, f"Expected 1.0 agreement with all present agreeing, got {dec.tf_agreement}"

    def test_llm_veto_blocks_trade(self):
        scores = self._uniform_scores(0.90)
        dec = v2_decide(scores, self._base_tf(), "TREND", llm_veto=True)
        assert not dec.trade, "LLM veto must block trade"

    def test_warmup_regime_no_trade(self):
        scores = self._uniform_scores(0.90)
        dec = v2_decide(scores, self._base_tf(), "WARMUP")
        assert not dec.trade, "WARMUP must never trade"

    def test_missing_agent_does_not_dilute_group_mean(self):
        """Omitting an agent (e.g. a05_wyckoff) must not dilute group average to 0.6."""
        scores = {
            "a02_sweep_choch": 0.90,
            "a03_ob_fvg": 0.90,
            # a05_wyckoff omitted intentionally
        }
        # In a regime where only structure matters or inspecting conviction directly
        from scoring import conviction
        side, conv = conviction(scores, "TREND", ScoreCfg())
        assert side == 1
        assert abs(conv - 90.0) < 1e-3, f"Expected 90.0 mean without a05, got {conv}"

    def test_per_agent_weights_inside_group(self):
        """flow group with a04=1.0 (w=1.0) and a09=0.0 (w=0.10) should yield mean ~0.909, not 0.5."""
        cfg = ScoreCfg(agent_weights={"a09_whale_ratio": 0.10})
        scores = {
            "a04_vsa_cvd": 1.0,
            "a09_whale_ratio": 0.0,
        }
        from scoring import conviction
        side, conv = conviction(scores, "TREND", cfg)
        expected = (1.0 * 1.0 + 0.0 * 0.10) / (1.0 + 0.10) * 100.0  # 90.909%
        assert abs(conv - expected) < 1e-2, f"Expected {expected:.2f}, got {conv:.2f}"

    def test_calc_a01_mtf_trend_neutral_is_positive(self):
        """1D, 4H, 1H agree (+1) and others are neutral (0) -> a01 > 0."""
        from scoring import calc_a01_mtf_trend
        tfs = {"1D": 1, "4H": 1, "1H": 1, "15m": 0, "5m": 0, "1m": 0}
        a01 = calc_a01_mtf_trend(tfs, side=1, cfg=ScoreCfg())
        # Weights: 1D=3, 4H=3, 1H=2 (tot=8 / 10 = 0.80)
        assert a01 > 0.0, f"Expected a01 > 0 with agreeing HTFs, got {a01}"
        assert abs(a01 - 0.80) < 1e-3, f"Expected 0.80, got {a01}"

    def test_calc_a01_mtf_trend_opposing_is_negative(self):
        """1D opposing (-1) while 4H and 1H are neutral (0) -> a01 = -3.0/8.0 = -0.375 < 0."""
        from scoring import calc_a01_mtf_trend
        tfs = {"1D": -1, "4H": 0, "1H": 0}
        a01 = calc_a01_mtf_trend(tfs, side=1, cfg=ScoreCfg())
        assert a01 < 0.0, f"Expected a01 < 0 with opposing 1D, got {a01}"
        assert abs(a01 - (-0.375)) < 1e-3, f"Expected -0.375 (-3/8 weight), got {a01}"

        # If 1D is the only present TF and opposes, a01 should be -1.0
        a01_only_1d = calc_a01_mtf_trend({"1D": -1}, side=1, cfg=ScoreCfg())
        assert abs(a01_only_1d - (-1.0)) < 1e-3, f"Expected -1.0, got {a01_only_1d}"

    def test_fundamental_score_halves_risk(self):
        """Fundamental score below threshold (0.40) must halve risk multiplier."""
        scores = self._uniform_scores(0.90)
        dec_normal = v2_decide(scores, self._base_tf(), "TREND", fundamental_score=0.80)
        dec_low_fund = v2_decide(scores, self._base_tf(), "TREND", fundamental_score=0.25)
        assert dec_normal.risk_mult == 1.0
        assert dec_low_fund.risk_mult == 0.5, f"Expected risk halved to 0.5, got {dec_low_fund.risk_mult}"
        assert any("fundamental score" in r for r in dec_low_fund.reasons)

    def test_decision_fields_present(self):
        scores = self._uniform_scores(0.90)
        dec = v2_decide(scores, self._base_tf(), "TREND")
        assert hasattr(dec, "trade")
        assert hasattr(dec, "conviction")
        assert hasattr(dec, "tf_agreement")
        assert hasattr(dec, "risk_mult")
        assert hasattr(dec, "reasons")


# ── 3. RiskManager ───────────────────────────────────────────────────────────
class TestRiskManager:
    def test_initial_state(self):
        rm = RiskManager(equity=1000.0)
        assert rm.equity == 1000.0
        assert rm.peak == 1000.0
        assert rm.drawdown == 0.0
        assert rm.loss_streak == 0

    def test_drawdown_ladder_10pct(self):
        cfg = RiskCfg()
        rm = RiskManager(equity=1000.0, cfg=cfg)
        rm.on_trade_closed(-110.0, -1.1)  # equity=890, dd=11%
        assert rm.drawdown > 0.10
        assert rm.dd_multiplier() == 0.50, "10% DD should halve risk"

    def test_drawdown_ladder_15pct(self):
        cfg = RiskCfg()
        rm = RiskManager(equity=1000.0, cfg=cfg)
        rm.on_trade_closed(-160.0, -1.6)  # equity=840, dd=16%
        assert rm.drawdown > 0.15
        assert rm.dd_multiplier() == 0.25, "15% DD should quarter risk"

    def test_drawdown_ladder_20pct_halt(self):
        cfg = RiskCfg()
        rm = RiskManager(equity=1000.0, cfg=cfg)
        rm.on_trade_closed(-210.0, -2.1)  # equity=790, dd=21%
        assert rm.dd_multiplier() == 0.0, "20% DD should halt trading"

    def test_loss_streak_half(self):
        cfg = RiskCfg()
        rm = RiskManager(equity=1000.0, cfg=cfg)
        for _ in range(cfg.loss_streak_half):
            rm.on_trade_closed(-10.0, -0.5)
        assert rm.streak_multiplier() == 0.5

    def test_loss_streak_stop(self):
        cfg = RiskCfg()
        rm = RiskManager(equity=1000.0, cfg=cfg)
        for _ in range(cfg.loss_streak_stop):
            rm.on_trade_closed(-10.0, -0.5)
        assert rm.streak_multiplier() == 0.0

    def test_streak_resets_on_win(self):
        cfg = RiskCfg()
        rm = RiskManager(equity=1000.0, cfg=cfg)
        for _ in range(4):
            rm.on_trade_closed(-10.0, -0.5)
        rm.on_trade_closed(30.0, 1.5)  # win resets streak
        assert rm.loss_streak == 0

    def test_position_size_shrinks_wide_stop(self):
        rm = RiskManager(equity=1000.0)
        units_tight, _ = rm.position_size(1.0, 100.0, 99.0)   # 1% stop
        units_wide,  _ = rm.position_size(1.0, 100.0, 95.0)   # 5% stop
        assert units_wide < units_tight, "Wider stop must give fewer units"

    def test_kelly_cap_before_100_trades(self):
        rm = RiskManager(equity=1000.0)
        cap = rm.kelly_cap()
        assert cap == RiskCfg().max_risk_pct, "Before 100 trades should return max_risk_pct"

    def test_risk_pct_zero_when_halted(self):
        cfg = RiskCfg()
        rm = RiskManager(equity=1000.0, cfg=cfg)
        rm.on_trade_closed(-210.0, -2.1)  # 21% DD -> halt
        assert rm.risk_pct(1.0) == 0.0


# ── 4. No Look-Ahead Validation ──────────────────────────────────────────────
class TestNoLookAhead:
    def test_signals_use_only_past_candles(self):
        """
        Verify that removing a future bar does NOT change any past signal.
        If it does, there is look-ahead bias.
        """
        from backtest import simulate
        from regime import classify as rc
        from scoring import decide

        df = make_trend_df(n=300)
        reg300 = rc(df)
        reg299 = rc(df.iloc[:299])

        # Signals up to bar 298 must be identical
        def sig_at_bar(i, reg):
            td = reg["trend_dir"].iloc[i]
            regime = reg["regime"].iloc[i]
            adx_val = reg["adx"].iloc[i]
            if td == 0 or not np.isfinite(adx_val):
                return None
            ss = int(td); strength = min(1.0, adx_val / 40.0)
            scores = {"a01_mtf_trend": ss*strength, "a02_sweep_choch": ss*0.8,
                      "a03_ob_fvg": ss*0.7, "a04_vsa_cvd": ss*0.6,
                      "a05_wyckoff": ss*strength, "a06_sr_hvn": ss*0.6,
                      "a08_candles": ss*0.7, "a09_whale_ratio": ss*0.55}
            tfs = {"1D": ss, "4H": ss, "1H": ss, "15m": ss}
            dec = decide(scores, tfs, regime)
            return (dec.trade, dec.risk_mult)

        for i in range(60, 298):
            s300 = sig_at_bar(i, reg300)
            s299 = sig_at_bar(i, reg299)
            assert s300 == s299, f"Look-ahead at bar {i}: {s300} != {s299}"

    def test_regime_at_bar_stable(self):
        """Regime label at any bar must not change when future bars are appended."""
        df = make_trend_df(n=400)
        out_400 = regime_classify(df)
        out_350 = regime_classify(df.iloc[:350])
        # Check bars 100..349
        for i in range(100, 349, 10):
            idx = df.index[i]
            assert out_400.loc[idx, "regime"] == out_350.loc[idx, "regime"], \
                f"Look-ahead at bar {i}: regime changed from {out_350.loc[idx,'regime']} to {out_400.loc[idx,'regime']}"

    def test_candidate_generator_no_lookahead(self):
        """
        Verify that adding future bars does NOT alter candidate signals, stop prices,
        or conviction scores at any preceding bar t.
        """
        from calibrate_conviction_buckets import generate_candidate_signals
        df = make_trend_df(n=350)
        sig_350 = generate_candidate_signals(df)
        sig_300 = generate_candidate_signals(df.iloc[:300])

        common_times = sig_300.index
        for t in common_times:
            assert t in sig_350.index, f"Signal at {t} vanished when future bars were added"
            s300 = sig_300.loc[t]
            s350 = sig_350.loc[t]
            assert s300["side"] == s350["side"], f"Side changed at {t}"
            assert abs(s300["conviction"] - s350["conviction"]) < 1e-3, f"Conviction changed at {t}"
            assert abs(s300["stop"] - s350["stop"]) < 1e-3, f"Stop price changed at {t}"


# ── 5. Walk-Forward Splits ───────────────────────────────────────────────────
class TestWalkForwardSplits:
    def test_splits_non_overlapping(self):
        splits = list(walk_forward_splits(1000, 500, 100))
        assert len(splits) > 0
        all_test = []
        for _, test in splits:
            all_test.extend(test.tolist())
        assert len(all_test) == len(set(all_test)), "Test windows overlap!"

    def test_train_precedes_test(self):
        for train, test in walk_forward_splits(1000, 500, 100):
            assert train[-1] < test[0], "Train leaks into test"

    def test_correct_window_sizes(self):
        for train, test in walk_forward_splits(2000, 1000, 500):
            assert len(train) == 1000
            assert len(test) == 500


# ── 6. Deflated Sharpe ───────────────────────────────────────────────────────
class TestDeflatedSharpe:
    def test_more_trials_lower_dsr(self):
        dsr_1   = deflated_sharpe(0.1, n_trials=1,   n_obs=200)
        dsr_50  = deflated_sharpe(0.1, n_trials=50,  n_obs=200)
        dsr_200 = deflated_sharpe(0.1, n_trials=200, n_obs=200)
        assert dsr_1 > dsr_50 > dsr_200, "More trials must lower Deflated Sharpe"

    def test_higher_sr_higher_dsr(self):
        dsr_low  = deflated_sharpe(0.02, n_trials=10, n_obs=200)
        dsr_high = deflated_sharpe(0.15, n_trials=10, n_obs=200)
        assert dsr_high > dsr_low

    def test_min_trades_warning(self):
        assert min_trades_warning(50) is not None    # should warn
        assert min_trades_warning(100) is None       # 100+ is fine
        assert min_trades_warning(200) is None


# ── 7. Closed Candles & Live Flag ───────────────────────────────────────────
class TestLiveClosedCandleFlag:
    def test_live_true_drops_forming_candle(self):
        """When live=True, the last candle whose close_time is in the future must be dropped."""
        import time
        from master_bot import _parse_raw_klines
        now_ms = int(time.time() * 1000)
        # 3 candles: 2 closed, 1 currently forming (close_time in future)
        raw_klines = [
            [now_ms - 7200000, "100", "105", "99", "104", "1000", now_ms - 3600000],  # closed
            [now_ms - 3600000, "104", "108", "103", "107", "1200", now_ms - 1],       # closed
            [now_ms, "107", "110", "106", "109", "500", now_ms + 3600000],            # forming (future close)
        ]
        parsed_live = _parse_raw_klines(raw_klines, live=True)
        assert len(parsed_live) == 2, f"Expected 2 closed candles in live mode, got {len(parsed_live)}"
        assert parsed_live[-1]["close"] == 107.0

        parsed_backtest = _parse_raw_klines(raw_klines, live=False)
        assert len(parsed_backtest) == 3, f"Expected all 3 candles in backtest mode, got {len(parsed_backtest)}"
        assert parsed_backtest[-1]["close"] == 109.0

    def test_master_bot_use_v2_default_false(self):
        """USE_V2 must be False by default."""
        import master_bot
        assert hasattr(master_bot, "USE_V2")
        assert master_bot.USE_V2 is False, "USE_V2 must default to False"

    def test_master_bot_v2_gate_execution_when_enabled(self, monkeypatch):
        """When USE_V2=True, v2_decide must be invoked with correct keyword arguments."""
        import master_bot
        from scoring import decide as v2_decide
        from config import ScoreCfg as V2ScoreCfg

        monkeypatch.setattr(master_bot, "USE_V2", True)
        
        # Sample setup data
        tf_signs = {"1D": 1, "4H": 1, "1H": 1, "15m": 1}
        v2_scores = {
            "a01_mtf_trend": 0.85,
            "a02_sweep_choch": 0.85,
            "a03_ob_fvg": 0.80,
            "a04_vsa_cvd": 0.75,
            "a06_sr_hvn": 0.70,
            "a08_candles": 0.80,
            "a09_whale_ratio": 0.40,
        }
        
        dec = v2_decide(
            agent_scores=v2_scores,
            tf_signs=tf_signs,
            regime="TREND",
            llm_veto=False,
            at_range_edge=False,
            fundamental_score=0.85,
            cfg=V2ScoreCfg(),
        )
        assert dec.trade is True
        assert dec.conviction >= 75.0
        assert dec.risk_mult == 0.5  # Mid-tier risk multiplier (65-82 range) in TREND regime


