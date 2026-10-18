# CryptoBot v2 - regime gate, honest testing, safer risk

Run `python3 demo.py` (needs numpy + pandas). Demo uses SYNTHETIC data - it only proves the code runs.

## Files
| File | What it does | Book behind it |
|---|---|---|
| config.py | every threshold in one place (all are hypotheses to validate) | Pardo: fewer free parameters |
| regime.py | CHOP / TREND / BREAKOUT / TRANSITION from ADX, ATR percentile, efficiency ratio, BB squeeze + volume | Dalton, Steidlmayer (balance vs imbalance); Chan (regimes) |
| scoring.py | grouped agents, regime-based weights, weighted TF agreement, 1D/4H gate, LLM = veto only, tiered risk (>=83 full, 65-82 half in TREND/BREAKOUT only) | Lopez de Prado (correlated features), van Kervel (do not trust displayed liquidity) |
| risk.py | quarter-Kelly cap, drawdown ladder 10/15/20%, loss-streak brakes, size measured to the stop | Chan (half-Kelly max), Sinclair, Taleb (fat tails) |
| labeling.py | triple-barrier labels + meta-labels | Lopez de Prado ch.3 |
| validation.py | walk-forward splits, walk-forward efficiency, purged k-fold + embargo, deflated Sharpe, minimum-trades warning | Pardo ch.11, Lopez de Prado ch.7/14 |
| backtest.py | your exit ladder (2R/5R/runner) with fees + slippage, stop-first assumption | Harris, van Kervel (costs are real) |

## How to plug into your existing bot
1. In your pipeline, after the 12 agents produce scores in [-1, +1] (sign = direction), call
   `scoring.decide(agent_scores, tf_signs, regime, llm_veto, at_range_edge)`.
2. `regime` comes from `regime.classify(ohlcv_1h_or_4h)["regime"].iloc[-1]`.
3. Size with `RiskManager.position_size(decision.risk_mult, entry, stop)`.
4. Do NOT lower the score threshold to 35-45. `APPLY_FIXES.py` should be replaced by this tiered gate.

## Before any real money
- 6+ months of Binance data, at least one crash and one long chop.
- 100+ trades minimum. Test be_at_r = 1.0 / 1.5 / 2.0 and count every variant you try (feed the count to deflated_sharpe).
- Walk-forward: train 90 days / test 30 days. Watch walk-forward efficiency and out-of-sample drawdown vs in-sample.
- Then paper trade, then 0.25x size live.
