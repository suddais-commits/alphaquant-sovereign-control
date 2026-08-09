from binance.client import Client
import master_bot

client = Client()
symbol = 'NEARUSDT'
try:
    candles = master_bot.get_klines(client, symbol)
    structure = master_bot.check_structure(candles)
    print('structure=', structure)
    if structure:
        res = master_bot.compute_entry_sl_tp(structure, candles)
        if res is None:
            # compute and print diagnostics used by compute_entry_sl_tp
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
            print(f'entry={entry:.8f}, sl={sl:.8f}, risk={risk:.8f}, sl_distance_pct={sl_distance_pct:.4f}%, rr={rr:.4f}')
            print('CONFIG: MIN_SL_DISTANCE_PCT=', master_bot.MIN_SL_DISTANCE_PCT, 'MAX_SL_DISTANCE_PCT=', master_bot.MAX_SL_DISTANCE_PCT, 'MIN_RISK_REWARD_RATIO=', master_bot.MIN_RISK_REWARD_RATIO)
        else:
            entry, sl, tp1, tp2, tp3, rr, tp_levels = res
            sl_distance_pct = abs(entry-sl)/entry*100
            print('entry, sl, tp1, tp2, tp3, rr =', entry, sl, tp1, tp2, tp3, rr)
            print('sl_distance_pct=',sl_distance_pct)
except Exception as e:
    print('ERROR running diagnostic:', e)
