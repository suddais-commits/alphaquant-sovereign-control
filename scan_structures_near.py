from binance.client import Client
import master_bot
import time

client = Client()
symbol = 'NEARUSDT'
# fetch enough klines to slide: SWING_LOOKBACK + 50
limit = master_bot.SWING_LOOKBACK + 200
raw = client.get_klines(symbol=symbol, interval=master_bot.TIMEFRAME, limit=limit)
if not raw:
    print('No klines')
    exit()

candles = [
    {"open_time": k[0], "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "close_time": k[6], "volume": float(k[5])}
    for k in raw
]

found = []
window_size = master_bot.SWING_LOOKBACK + 2
for i in range(window_size, len(candles)):
    window = candles[i - window_size:i]
    structure = master_bot.check_structure(window)
    if not structure:
        continue
    # compute diagnostics
    result = master_bot.compute_entry_sl_tp(structure, window)
    ts = candles[i-2]["close_time"]
    ts_str = time.strftime('%Y-%m-%d %H:%M', time.gmtime(ts/1000))
    if result is None:
        swept = structure['swept_level']
        close = structure['close']
        buffer = abs(close) * 0.004
        if structure['direction'] == 'LONG':
            sl = swept - buffer
            entry = (close + swept) / 2
            risk = entry - sl
        else:
            sl = swept + buffer
            entry = (close + swept) / 2
            risk = sl - entry
        sl_distance_pct = (abs(risk) / entry) * 100
        tp2_estimate = entry + (risk * 2) if structure['direction']=='LONG' else entry - (risk*2)
        rr = abs(tp2_estimate - entry)/max(abs(risk),1e-9)
        found.append((ts_str, structure['direction'], 'validation_failed', entry, sl, round(sl_distance_pct,4), round(rr,4)))
    else:
        entry, sl, tp1, tp2, tp3, rr, tp_levels = result
        sl_distance_pct = abs(entry-sl)/entry*100
        found.append((ts_str, structure['direction'], 'ok', entry, sl, round(sl_distance_pct,4), round(rr,4)))

if not found:
    print('No structure detected in fetched range')
else:
    print('Detected structures:')
    for r in found:
        print(r)
