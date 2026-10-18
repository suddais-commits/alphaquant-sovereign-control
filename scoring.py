"""Decision gate: agent scores -> conviction -> tier -> risk multiplier.
Key changes vs v1:
 * agents are GROUPED (correlated agents no longer triple-count one idea)
 * group weights depend on the regime
 * timeframe agreement is WEIGHTED, and 1D/4H can veto
 * LLM (Gemini) agent is a VETO only - it is not reproducible, so it cannot be backtested or scored
 * threshold is NOT lowered; instead a 65-82 score gets half risk, and only in TREND/BREAKOUT
"""
from dataclasses import dataclass
import numpy as np
from config import ScoreCfg, FundamentalCfg

@dataclass
class Decision:
    trade: bool
    side: int              # +1 long, -1 short, 0 none
    conviction: float      # 0..100
    risk_mult: float       # 0, 0.5, 1.0
    regime: str
    tf_agreement: float
    reasons: list

def tf_agreement(tf_signs: dict, side: int, cfg: ScoreCfg):
    """tf_signs: {'1D': +1/-1/0, ...}. Returns weighted agreement share and whether HTF gate passes."""
    tot = sum(cfg.tf_weights.get(k, 0) for k in tf_signs)
    agree = sum(cfg.tf_weights.get(k, 0) for k, s in tf_signs.items() if s == side)
    share = agree / tot if tot else 0.0
    gate_ok = all(tf_signs.get(k, 0) != -side for k in cfg.htf_gate)
    return share, gate_ok

def calc_a01_mtf_trend(tf_signs: dict, side: int, cfg: ScoreCfg = ScoreCfg()) -> float:
    """
    Computes a01_mtf_trend as a weighted signed average over present timeframes.
    Neutral (0) TFs contribute 0 to the numerator, preventing false negative penalties.
    Returns value in [-1.0, +1.0] where positive supports candidate side and negative opposes candidate side.
    """
    tot_w = sum(cfg.tf_weights.get(k, 0.0) for k in tf_signs)
    if tot_w == 0:
        return 0.0
    signed_sum = sum(cfg.tf_weights.get(k, 0.0) * tf_signs.get(k, 0) for k in tf_signs)
    return (signed_sum / tot_w) * side

def conviction(agent_scores: dict, regime: str, cfg: ScoreCfg):
    """agent_scores: {'a02_sweep_choch': -1..+1 (sign=direction, size=confidence)}. Returns (side, 0..100)."""
    gw = cfg.group_weights_by_regime.get(regime, cfg.group_weights_by_regime["TRANSITION"])
    num = den = 0.0
    for g, members in cfg.groups.items():
        # Calculate intra-group weighted mean using per-agent weights (default 1.0)
        vals = [(agent_scores[m], cfg.agent_weights.get(m, 1.0)) for m in members if m in agent_scores]
        if not vals:
            continue
        g_num = sum(score * weight for score, weight in vals)
        g_den = sum(weight for _, weight in vals)
        g_mean = g_num / g_den if g_den > 0 else 0.0
        num += gw[g] * g_mean
        den += gw[g]
    if den == 0:
        return 0, 0.0
    s = num / den
    return int(np.sign(s)), abs(s) * 100.0

def decide(agent_scores: dict, tf_signs: dict, regime: str, llm_veto: bool = False,
           at_range_edge: bool = False, fundamental_score: float | None = None,
           cfg: ScoreCfg = ScoreCfg(), f_cfg: FundamentalCfg = FundamentalCfg()) -> Decision:
    reasons = []
    side, conv = conviction(agent_scores, regime, cfg)
    if side == 0:
        return Decision(False, 0, conv, 0.0, regime, 0.0, ["no direction"])
    share, gate_ok = tf_agreement(tf_signs, side, cfg)
    if regime == "WARMUP":
        return Decision(False, side, conv, 0.0, regime, share, ["indicators warming up"])
    if not gate_ok:
        return Decision(False, side, conv, 0.0, regime, share, ["1D/4H oppose the trade"])
    if share < cfg.min_tf_agreement:
        return Decision(False, side, conv, 0.0, regime, share, [f"TF agreement {share:.2f} < {cfg.min_tf_agreement}"])
    if llm_veto:
        return Decision(False, side, conv, 0.0, regime, share, ["LLM veto"])
    mult = 0.0
    if conv >= cfg.full_score:
        mult = cfg.full_mult
    elif conv >= cfg.mid_score and regime in ("TREND", "BREAKOUT"):
        mult = cfg.mid_mult
    else:
        reasons.append("score too low for this regime")
    if regime == "CHOP" and mult > 0:
        if not at_range_edge:
            return Decision(False, side, conv, 0.0, regime, share, ["CHOP and not at range edge (VAH/VAL)"])
        mult = min(mult, cfg.chop_max_mult)
        reasons.append("CHOP: risk capped")
    if mult > 0 and fundamental_score is not None and fundamental_score < f_cfg.min_quality_score:
        mult *= f_cfg.below_min_risk_mult
        reasons.append(f"fundamental score {fundamental_score:.2f} < {f_cfg.min_quality_score}: risk halved")
    return Decision(mult > 0, side if mult > 0 else 0, conv, mult, regime, share, reasons or ["ok"])
