# Master Bot - Major Updates Summary
## Applied Changes for Playbook Alignment

**Date:** 2026-08-03
**Reason:** Implement missing playbook features + risk management adjustment

---

## Changes Applied:

### 1. **Account Size & Risk Management**
- ACCOUNT_SIZE_USDT: 100 → **5962** (actual demo balance)
- RISK_PER_TRADE_PCT: 1% (same, but now on $5962)
- Daily stop-loss tracking: Now ACTUALLY tracks losing trades (previously broken)

### 2. **Max SL Distance Cap (2%)**
- If calculated SL > 2% from entry → **SKIP SIGNAL**
- Prevents loose SL that eat into profits via slippage/fees
- Applied in `compute_entry_sl_tp()` - returns None if violated

### 3. **Multi-Timeframe Cascade Detection**
- Added: `get_higher_tf_bias()` function
- Checks Daily/4H/1H timeframes for trend direction BEFORE entry
- **Signal only valid if:**
  - Entry timeframe (1H) matches higher timeframe bias
  - Prevents counter-trend entries
- Uses Binance data, separate `get_klines_for_tf()` helper

### 4. **Structure-Based TP Levels (Instead of Fixed %)**
- OLD: TP1=1R, TP2=2R, TP3=3R (hardcoded)
- NEW: TP levels = closest swing highs/lows from 20-candle lookback
- Algorithm:
  1. Scan last 20 candles for local highs/lows
  2. Find top 3 that are ABOVE entry (for LONG)
  3. Assign qty: 50% to nearest, 30% to 2nd, 20% to 3rd
  4. If swing levels insufficient, fallback to 1:2 ratio (safe)

### 5. **Institutional Candle Detection**
- Added: `detect_ifc_burst_candle()` 
- Checks for:
  - **IFC (Institutional Funding Candle):** Large wick + small body (Smart Money hunting stops)
  - **Burst Candle:** Sudden volume spike + rapid price move
  - Scores each, adds to VSA layer

### 6. **Advanced Order Block Types**
- Added: `detect_advanced_ob_types()`
- Detects:
  - **Mitigation Block:** Price bounced partway back (not full reversal)
  - **Breaker Block:** Failed OB that now works opposite direction
  - **Refine Block:** Smaller OB nested inside larger
  - **Rejection Block:** Heavy wick rejection
- Each type weighted differently in score

### 7. **Scale-Out Strategy (Section 12 Playbook)**
- Entry: 100% qty
- At 1:1 RR: Close 50%, move SL to breakeven
- At 2:1 RR: Close 30%, let 20% run unlimited (trailing SL on entry price)
- Implemented in `manage_open_trades()` with automatic execution

### 8. **Better VSA - Absorption Detection**
- Now tracks: high volume + small candle body (hands changing)
- Checks volume ratio (vol / 20-candle avg)
- Signals potential reversal if absorption + price rejects level

### 9. **Threshold Adjustment**
- OLD: 70 (too strict, few signals)
- NEW: **Configurable in .env via `SCORE_THRESHOLD`**
- Recommended starting: 50-55 (for more signals to backtest)
- Can adjust without restarting: edit `.env` + restart

### 10. **News Filter Improvement**
- Already added RSS-based filter
- Now also checks if MAJOR NEWS within last 30 min
- If yes → pause new trades for 1 hour (safe)

---

## Files Updated:
- `master_bot.py` — all of above
- `.env` — ACCOUNT_SIZE_USDT updated, SCORE_THRESHOLD exposed

## Files NOT Changed:
- `news_service.py` — working fine
- `backtest_smc_strategy.py` — will need manual update to match new logic
- `requirements.txt` — no new libraries needed

---

## Next Steps:

1. **Update `.env`:**
   ```
   ACCOUNT_SIZE_USDT=5962
   SCORE_THRESHOLD=55
   MAX_SL_PCT=2.0
   ```

2. **Test live signals** — monitor `bot_log.txt` for:
   - "Max SL exceeded" lines (means tight structures being rejected)
   - Multi-timeframe bias checks
   - Structure-based TP levels

3. **Backtest New Logic:**
   - Update `backtest_smc_strategy.py` to match new SL/TP logic
   - Re-run with new threshold
   - Expect: fewer trades, potentially higher quality

4. **Monitor for 2-4 weeks** before real account decision

---

## Risk Warnings:
- ✅ Max SL cap prevents runaway losses
- ✅ Multi-timeframe alignment reduces counter-trend entries
- ✅ Scale-out locks profits earlier (better for demo)
- ⚠️  Structure-based TP might miss extended moves (but safer)
- ⚠️  Lower threshold (55 vs 70) = more signals = higher backtest variance
