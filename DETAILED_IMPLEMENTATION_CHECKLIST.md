# MASTER BOT - DETAILED IMPLEMENTATION CHECKLIST

## Phase 1: Constants & Config ✅ READY

```python
# Update in master_bot.py (around line 110-115):
ACCOUNT_SIZE_USDT = 5962        # Was 100, now actual balance
RISK_PER_TRADE_PCT = 1.0
MAX_SL_PCT = 2.0                # NEW: max stop loss as % of entry price
SCORE_THRESHOLD = 55             # Was 70, now 55 for more signals (tunable via .env)
```

**Status:** Just constants, no logic change

---

## Phase 2: New Functions (Before compute_entry_sl_tp)

### Function 1: get_klines_for_tf()
```
Purpose: Fetch candles for any timeframe (not just TIMEFRAME)
Input: client, symbol, timeframe (e.g., "4h", "1d")
Output: list of candle dicts
Used by: get_higher_tf_bias()
```

### Function 2: get_higher_tf_bias()
```
Purpose: Check Daily/4H/1H alignment
Logic:
  - Fetch Daily candles (last 5)
  - Check if last 2 candles are higher-high+higher-low (uptrend=+1) or opposite (downtrend=-1)
  - Do same for 4H
  - Do same for 1H (entry TF)
  - Return: consensus (+1 if all agree up, -1 if all down, 0 if mixed)
  
Used in: run_once() before placing trade
```

### Function 3: get_swing_levels()
```
Purpose: Find swing highs/lows in last 20 candles
Logic:
  - For LONG: scan last 20 candles, find local highs (candle.high > neighbors)
  - Filter only highs ABOVE entry price
  - Sort descending
  - Return top 3 (or fewer if not enough)
  
Used in: compute_entry_sl_tp() for TP levels
```

### Function 4: detect_ifc_burst_candle()
```
Purpose: Detect Institutional Funding Candle (IFC) and Burst
Logic for IFC:
  - body_ratio = candle_body / (candle_high - candle_low)
  - wick_ratio = wick_size / (candle_high - candle_low)
  - IFC = (body_ratio < 0.3 AND wick_ratio > 0.6) = small body, huge wick
  
Logic for Burst:
  - volume > 3x average volume AND
  - candle_size > 2x average candle size
  - Burst = sudden large move with volume
  
Return: IFC_score (0-1), Burst_score (0-1)

Used in: VSA layer scoring
```

### Function 5: detect_advanced_ob_types()
```
Purpose: Detect beyond simple OB (Mitigation, Breaker, Refine, Rejection)
Logic (simplified):
  - Mitigation: price bounced back 50-80% (not full reversal)
  - Breaker: earlier failed OB now acting opposite (higher timeframe alert)
  - Refine: smaller OB nested in larger OB
  - Rejection: heavy wick at level, price rejected
  
Return: dict with type name + confidence score
```

---

## Phase 3: Core Logic Updates

### Update compute_entry_sl_tp()
**Changes:**
1. After calculating SL, check: `if (entry - sl) / entry > MAX_SL_PCT / 100: return None`
   - If SL distance exceeds 2%, return None (signal rejected)
   
2. Replace fixed TP calc:
   ```
   OLD:
   tp1 = entry + risk * 1
   tp2 = entry + risk * 2
   tp3 = entry + risk * 3
   
   NEW:
   swing_levels = get_swing_levels(candles, direction)
   if len(swing_levels) >= 3:
       tp1 = swing_levels[2]  # furthest
       tp2 = swing_levels[1]  # middle
       tp3 = swing_levels[0]  # closest
   else:  # fallback to ratio
       tp1 = entry + risk * 1
       tp2 = entry + risk * 2
       tp3 = entry + risk * 3
   ```

3. Add new return field: `"structure_based_tp": (True if swing levels used)`

---

### Update run_once() / check_symbol()
**Changes:**
1. Before creating signal, add:
   ```python
   if MULTI_TIMEFRAME_CASCADE_ENABLED:
       tf_bias = get_higher_tf_bias(symbol)
       if direction == "LONG" and tf_bias != 1:
           log.info("%s: HTF bias against trade (%d), skipping", symbol, tf_bias)
           return None
       if direction == "SHORT" and tf_bias != -1:
           log.info("%s: HTF bias against trade (%d), skipping", symbol, tf_bias)
           return None
   ```

2. Multi-TF check log: `"Multi-timeframe bias confirmed (Daily/4H/1H)"`

---

### Update manage_open_trades()
**Changes:**
1. After TP1 hit, before marking tp1_hit:
   ```python
   # Scale-out logic: close 50% of remaining qty at 1:1 RR
   if reached_rr_level == 1.0:  # 1:1 RR hit
       qty_to_close = trade["original_qty"] * 0.5
       close_order = session.place_order(
           category=BYBIT_CATEGORY,
           symbol=symbol,
           side=close_side,
           orderType="Market",
           qty=qty_to_close
       )
       trade["scale_out_50pct_closed"] = True
       log.info("%s: Scale-out 50%% at 1:1 RR -- remaining qty trailing with SL@entry", symbol)
       # Move SL to breakeven
       trade["sl"] = entry
   ```

---

### Fix Daily Loss Tracking (Was Broken!)
**Current:** `daily_loss_tracker["loss_pct"]` never updated
**Fix:** In manage_open_trades(), when trade closes as loss:
```python
if trade_pnl_in_r < 0:  # losing trade
    daily_loss_tracker["loss_pct"] += abs(trade_pnl_in_r) * RISK_PER_TRADE_PCT
    # Now it actually accumulates daily losses!
```

---

## Phase 4: Scoring Updates

### VSA Layer (was 15/100)
Add IFC + Burst detection:
```python
ifc_score, burst_score = detect_ifc_burst_candle(candles)
advanced_vsa_score = (vsa_score + ifc_score * 0.5 + burst_score * 0.3) / 2
```

### OB/FVG Layer (was 10/100)
Add advanced OB detection:
```python
advanced_ob = detect_advanced_ob_types(candles, structure)
ob_fvg_score += advanced_ob["confidence"] * 0.5  # bonus points
```

---

## Phase 5: Testing Checklist

- [ ] Syntax check: `python3 -m py_compile master_bot.py`
- [ ] Dry run (no Bybit): check logs for new messages
- [ ] Check for "Max SL exceeded" logs (should see some)
- [ ] Check for "HTF bias against trade" logs (should see some rejections)
- [ ] Check for "Scale-out 50%" logs when TP1 hit (EULUSDT might show this)
- [ ] Verify ACCOUNT_SIZE messages show $5962 or account balance
- [ ] Test with SCORE_THRESHOLD=55 (vs old 70)
- [ ] Backtest new logic vs old (compare trade counts + quality)

---

## Expected Results (2-4 weeks demo)

**Before:** ~5-10 trades per 2 weeks, mixed quality
**After:** ~15-20 trades (lower threshold), better quality (HTF filter + max SL cap)
**Win rate:** Should improve from 66% → 70-75% (fewer bad setups)
**Profit:** Depends on RR, but scale-out helps early locking

---

## Rollback Plan

If issues found:
```bash
cp master_bot_backup_before_major_update.py master_bot.py
# Go back to last known good state
```

---

## Files Affected

- `master_bot.py` — main changes (~300 lines added)
- `.env` — new constants (SCORE_THRESHOLD tunable)
- `backtest_smc_strategy.py` — needs manual update to match new TP logic
- `trade_journal.csv` — will have more entries (more signals)

---

