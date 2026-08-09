# Arkham + TradingView Backtest -- Integration Steps

## Part 1: Arkham (Layer 2 real on-chain data)

**Kya badla:** `master_bot.py` ka `onchain_score()` function ab pehle Arkham
se real whale/exchange flow data leta hai. Agar Arkham se data nahi mila
(key missing, coin untracked, ya API down), khud-ba-khud purana DefiLlama
fallback use ho jata hai -- bot kabhi crash nahi karega, chahe Arkham na ho.

### Steps:
1. **Free Arkham API key lein:**
   - https://intel.arkm.com/api par jayein
   - Account banayein / sign in karein
   - "Get API Access" par click karke apply karein (free tier available hai)
   - Key copy kar lein

2. **`.env` file mein daalein** (naye `.env.example` mein neeche ek naya
   line dikhega):
   ```
   ARKHAM_API_KEY=yahan_apni_key_paste_karein
   ```

3. **Naya `master_bot.py` purani file ki jagah paste karein** apne
   `C:\Users\HP\OneDrive\Desktop\CryptoBot` folder mein.

4. Bot normal tarike se chalayein (`run_bot.bat`). `bot_log.txt` mein ab
   ye line dikhegi jab Arkham se real data mile:
   ```
   SOLUSDT: onchain score from Arkham (real flow) = 0.72
   ```
   Agar ye line nahi dikhti kisi coin ke liye, matlab Arkham par wo coin
   track nahi hota (chhote/naye coins ke liye normal hai) -- fallback
   chal raha hai, koi error nahi.

### Rate limits:
Arkham free tier heavy endpoints (jo hum use kar rahe hain) 1 request/sec
allow karta hai. Code mein ye khud-ba-khud handle hota hai (thoda sa
`time.sleep` lagta hai agar zaroorat pade) -- aapko kuch karna nahi hai.

---

## Part 2: TradingView Backtest Tool (standalone)

**Important:** Ye bot ki live 5-minute scanning loop ka HISSA NAHI hai --
ek alag tool hai jo aap **manually** chalate hain jab kisi strategy ko
history data par test karna ho. Isse `SCORE_THRESHOLD` ya kisi live
setting par koi asar nahi padta.

### Naye files (isi CryptoBot folder mein daal dein):
- `run_backtest.py` -- jo command aap chalayenge
- `backtest_service.py` -- backtest engine
- `indicators_calc.py` -- RSI/MACD/EMA jaise indicators
- `proxy_manager.py` -- fallback connection helper

### Kaise chalayein (Command Prompt mein, CryptoBot folder ke andar):

```
# Ek coin, ek strategy test karo
python run_backtest.py SOLUSDT ema_cross

# Ek coin par saari 9 strategies compare karo (best/worst dikhayega)
python run_backtest.py SOLUSDT --compare

# Poore shortlist par best strategy dhoondo
python run_backtest.py --shortlist BTCUSDT ETHUSDT SOLUSDT ADAUSDT --compare

# Longer history, hourly candles
python run_backtest.py SOLUSDT ema_cross --period 2y --interval 1h

# Overfitting check (train/test split)
python run_backtest.py SOLUSDT ema_cross --walk-forward
```

### 9 available strategies:
`rsi`, `bollinger`, `macd`, `ema_cross`, `supertrend`, `donchian`,
`rsi_pullback`, `keltner_breakout`, `triple_ema`

### Note:
- Data source **Yahoo Finance** hai (free, koi key nahi chahiye) --
  crypto symbols khud `SOLUSDT` -> `SOL-USD` mein convert ho jate hain.
- Ye generic technical strategies test karta hai (RSI/MACD/EMA type) --
  aapke bot ka khud ka SMC/liquidity-sweep logic test nahi karta (wo
  alag cheez hai, agar chahiye to bata dein, alag se banega).
- Output se Sharpe ratio, Calmar ratio, win rate, max drawdown milta
  hai -- inse pata chalta hai koi bhi generic strategy is coin par
  historically kaisi perform karti thi.

---

## Requirements.txt
Koi naya Python package install nahi karna -- dono integrations
already-installed libraries (`requests`, stdlib) use karte hain.
