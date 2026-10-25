"""
daily_trend_paper.py - PAPER trading only (no real orders, no API keys needed).
Daily trend idea: Donchian-55 breakout on the last CLOSED daily candle, 48 liquid coins, long+short, entry at today's open.
Two paper books run side by side so we learn which exit is better with real data:
   D55-LADDER : 30% off at +2R (stop to break-even), 30% off at +5R, runner trails EMA50
   D55-TRAIL3 : no fixed TP, no partials; after +3R the stop trails 3 ATR behind the best price
Rules (same as the tests): stop 2 ATR, risk 0.5% of paper equity per trade, total open risk cap 4%, fees+slippage, funding 0.03%/day.
RUN ONCE PER DAY between 00:05 and 02:59 UTC (05:05-07:59 Pakistan time), e.g. with Windows Task Scheduler.
Files created in the same folder: paper_state.json (positions + equity), paper_trades.csv (closed trades).
Optional Telegram alerts: set env TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
Commands:  python daily_trend_paper.py            (normal daily run)
           python daily_trend_paper.py --force    (ignore the time-of-day guard)
           python daily_trend_paper.py --selftest (checks the engine against the tested backtest code, no internet)
"""
import os, sys, json, datetime as dt
import numpy as np, pandas as pd
import edge_test as E, edge_test2 as E2, edge_test3 as E3

E.ATR_MULT = 2.0
DON, RISK, CAP, FUND_DAY, START_EQ = 55, 0.005, 0.04, 0.0003, 1000.0
BOOKS = ["D55-LADDER", "D55-TRAIL3", "D55-C1DONCH20"]
STATE, TRADES = "paper_state.json", "paper_trades.csv"
UNIVERSE = E.COINS + E3.NEW

def fetch(sym):
    import requests
    for h in E.HOSTS:
        try:
            r = requests.get(h + "/api/v3/klines", params=dict(symbol=sym, interval="1d", limit=300), timeout=20)
            if r.status_code == 200 and len(r.json()) > 120:
                df = pd.DataFrame(r.json()).iloc[:, :6]; df.columns = ["t", "open", "high", "low", "close", "volume"]
                df.index = pd.to_datetime(df["t"], unit="ms"); return df.drop(columns="t").astype(float)
        except Exception: pass
    return None

def new_pos(book, sym, side, entry_time, entry_open, atr_sig, close_sig, equity):
    entry = entry_open * (1 + side * E.SLIP / 1e4); stop = close_sig - side * E.ATR_MULT * atr_sig; dist = abs(entry - stop)
    if dist <= 0 or (side > 0 and stop >= entry) or (side < 0 and stop <= entry): return None
    return dict(book=book, sym=sym, side=side, entry_time=str(entry_time), entry=entry, stop=stop, cur=stop, dist=dist,
                risk_amt=RISK * equity, state=0, be=False, rem=1.0, real=0.0, best=entry, active=False, exit_open=False, nbars=0, last_time=None)

def advance(pos, df, mode):
    """Feed CLOSED daily bars to a position. Returns (closed, net_R, exit_time, days_held). Same logic as the tested simulators."""
    a, _ = E.prep(df); ix = df.index; start = pd.Timestamp(pos["entry_time"]); side, entry, dist = pos["side"], pos["entry"], pos["dist"]
    R = lambda px: side * (px - entry) / dist
    for j in range(len(ix)):
        t = ix[j]
        if t < start or (pos["last_time"] and t <= pd.Timestamp(pos["last_time"])): continue
        hi, lo, cl = a["h"][j], a["l"][j], a["c"][j]; k = pos["nbars"]; pos["nbars"] += 1; pos["last_time"] = str(t); done = False
        
        # Signal exit scheduled for open of this bar (Donchian-20 exit)
        if pos.get("exit_open", False):
            open_px = a["o"][j] * (1 - side * E.SLIP / 1e4)
            pos["real"] += pos["rem"] * R(open_px); pos["rem"] = 0; pos["exit_open"] = False
            return True, pos["real"] - 2 * E.FEE / 1e4 * entry / dist, str(t), pos["nbars"] - 1

        if (lo <= pos["cur"]) if side > 0 else (hi >= pos["cur"]):
            pos["real"] += pos["rem"] * R(pos["cur"] * (1 - side * E.SLIP / 1e4)); pos["rem"] = 0; done = True
        else:
            fav = hi if side > 0 else lo
            if mode == "ladder":
                if not pos["be"] and R(fav) >= E.TP1: pos["cur"] = entry; pos["be"] = True
                if pos["state"] == 0 and R(fav) >= E.TP1: pos["real"] += E.TP1F * E.TP1; pos["rem"] -= E.TP1F; pos["state"] = 1
                if pos["state"] == 1 and R(fav) >= E.TP2: pos["real"] += E.TP2F * E.TP2; pos["rem"] -= E.TP2F; pos["state"] = 2; pos["cur"] = entry + side * E.TRAIL_R * dist
                if pos["state"] == 2:
                    tr = a["ema"][j - 1]
                    if (side > 0 and tr > pos["cur"]) or (side < 0 and tr < pos["cur"]): pos["cur"] = tr
            elif mode == "trail":
                pos["best"] = max(pos["best"], hi) if side > 0 else min(pos["best"], lo)
                if not pos["active"] and R(pos["best"]) >= E3.ACT_R: pos["active"] = True
                if pos["active"]:
                    new = pos["best"] - side * E3.TRAIL_K * a["atr"][j]
                    if (side > 0 and new > pos["cur"]) or (side < 0 and new < pos["cur"]): pos["cur"] = new
            elif mode == "donch20":
                if not pos["be"] and R(fav) >= 1.5:
                    if (side > 0 and pos["cur"] < entry) or (side < 0 and pos["cur"] > entry):
                        pos["cur"] = entry
                    pos["be"] = True
                if j >= 20:
                    hh20 = np.max(a["h"][j - 20:j])
                    ll20 = np.min(a["l"][j - 20:j])
                    if side > 0 and cl < ll20:
                        pos["exit_open"] = True
                    elif side < 0 and cl > hh20:
                        pos["exit_open"] = True
            if k >= E.MAX_BARS: pos["real"] += pos["rem"] * R(cl); pos["rem"] = 0; done = True
        if done: return True, pos["real"] - 2 * E.FEE / 1e4 * entry / dist, str(t), pos["nbars"] - 1
    return False, None, None, None

def alert(msg):
    print(msg)
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if tok and chat:
        try:
            import requests; requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data=dict(chat_id=chat, text=msg), timeout=15)
        except Exception: pass

def log_trade(pos, net, fund, pnl, exit_t, eq):
    row = dict(book=pos["book"], sym=pos["sym"], side=pos["side"], entry_time=pos["entry_time"], exit_time=exit_t, entry=pos["entry"],
               net_R=round(net, 3), funding_R=round(fund, 3), pnl_usd=round(pnl, 2), equity=round(eq, 2))
    pd.DataFrame([row]).to_csv(TRADES, mode="a", header=not os.path.exists(TRADES), index=False)

def main(force=False):
    now = dt.datetime.now(dt.timezone.utc)
    if now.hour >= 3 and not force:
        print("Run this between 00:05 and 02:59 UTC (05:05-07:59 Pakistan time). Use --force to override."); return
    state = json.load(open(STATE)) if os.path.exists(STATE) else dict(books={})
    data = {s: d for s in UNIVERSE if (d := fetch(s + "USDT")) is not None}
    if len(data) < 20: print("Too few coins downloaded (", len(data), "). Binance not reachable? Stop."); return
    closed = {s: d.iloc[:-1] for s, d in data.items()}; fresh = {s: d for s, d in data.items() if d.index[-1].date() == now.date()}
    bar = max(c.index[-1] for c in closed.values()); print(f"{len(data)} coins loaded, last closed daily bar: {bar.date()}, entries possible for {len(fresh)} coins")
    
    # BTC 200 EMA check for C1
    btc_bull, btc_bear = True, True
    if "BTC" in closed and len(closed["BTC"]) >= 200:
        btc_c = closed["BTC"]["close"]
        btc_ema200 = btc_c.ewm(span=200, adjust=False).mean().iloc[-1]
        btc_bull = btc_c.iloc[-1] > btc_ema200
        btc_bear = btc_c.iloc[-1] < btc_ema200

    for book in BOOKS:
        if "LADDER" in book: mode = "ladder"
        elif "TRAIL3" in book: mode = "trail"
        else: mode = "donch20"

        b = state["books"].setdefault(book, dict(equity=START_EQ, open=[], last_bar=None))
        closed_now = set()   # coins that closed a trade on the last bar: no same-bar re-entry
        for pos in list(b["open"]):
            if pos["sym"] not in closed: continue
            done, net, xt, days = advance(pos, closed[pos["sym"]], mode)
            # If exit_open was triggered by yesterday's close, exit at today's open price
            if not done and pos.get("exit_open", False) and pos["sym"] in fresh:
                open_px = fresh[pos["sym"]]["open"].iloc[-1] * (1 - pos["side"] * E.SLIP / 1e4)
                R = lambda px: pos["side"] * (px - pos["entry"]) / pos["dist"]
                pos["real"] += pos["rem"] * R(open_px); pos["rem"] = 0; pos["exit_open"] = False; done = True
                net = pos["real"] - 2 * E.FEE / 1e4 * pos["entry"] / pos["dist"]
                xt = str(fresh[pos["sym"]].index[-1]); days = pos["nbars"]

            if done:
                fund = days * FUND_DAY * pos["entry"] / pos["dist"]; pnl = (net - fund) * pos["risk_amt"]; b["equity"] += pnl; b["open"].remove(pos)
                log_trade(pos, net, fund, pnl, xt, b["equity"])
                if xt == str(bar): closed_now.add(pos["sym"])
                alert(f"[{book}] CLOSED {pos['sym']} {'LONG' if pos['side']>0 else 'SHORT'}  {net-fund:+.2f}R  paper equity {b['equity']:.0f}")
        if b["last_bar"] != str(bar):
            cands = []
            for s, c in closed.items():
                if s not in fresh or s in closed_now or any(p["sym"] == s for p in b["open"]): continue
                a, sw = E.prep(c)
                if mode == "donch20":
                    if len(c) < DON + 5: continue
                    hh = c["high"].shift(1).rolling(DON).max().iloc[-1]
                    ll = c["low"].shift(1).rolling(DON).min().iloc[-1]
                    cl = c["close"].iloc[-1]
                    atr_v = a["atr"][-1]
                    sd = 0
                    if cl > hh + 0.25 * atr_v and btc_bull: sd = 1
                    elif cl < ll - 0.25 * atr_v and btc_bear: sd = -1
                else:
                    sd = int(E2.make_sides(c, a, sw, DON)[-1])
                if sd != 0 and c.index[-1] == bar: cands.append((s, sd, a["atr"][-1], c["close"].iloc[-1]))
            np.random.default_rng(int(bar.strftime("%Y%m%d"))).shuffle(cands)
            for s, sd, atr, cl in cands:
                if (len(b["open"]) + 1) * RISK > CAP + 1e-12: print(f"[{book}] {s}: signal skipped (risk cap)"); continue
                p = new_pos(book, s, sd, fresh[s].index[-1], fresh[s]["open"].iloc[-1], atr, cl, b["equity"])
                if p: b["open"].append(p); alert(f"[{book}] NEW {s} {'LONG' if sd>0 else 'SHORT'} entry {p['entry']:.6g} stop {p['stop']:.6g} risk {RISK*100:.1f}% (paper)")
            b["last_bar"] = str(bar)
        print(f"[{book}] paper equity {b['equity']:.2f} | open positions {len(b['open'])}")
    json.dump(state, open(STATE, "w"), indent=1)

def selftest():
    checked, bad = 0, 0
    for k in range(6):
        df = E2.demo_df(k, "1d"); a, sw = E.prep(df); side = E2.make_sides(df, a, sw, DON); ix = df.index
        for mode in ("ladder", "trail"):
            last = -1
            for i in np.where(side != 0)[0]:
                i = int(i)
                if i <= last: continue
                r = E.sim_one(a, i, int(side[i])) if mode == "ladder" else E3.sim_trail(a, i, int(side[i]))
                if r is None: continue
                net, ex = r; last = ex
                if ex >= len(df) - 2: continue
                pos = new_pos("t", "x", int(side[i]), ix[i + 1], df["open"].iloc[i + 1], a["atr"][i], df["close"].iloc[i], 1000.0)
                if pos is None: continue
                res = (False,)
                for j in range(i + 1, len(df)):
                    res = advance(pos, df.iloc[:j + 1], mode)
                    if res[0]: break
                checked += 1
                if not res[0] or abs(res[1] - net) > 1e-6: bad += 1; print("MISMATCH", k, mode, i, round(net, 4), res)
    print(f"SELFTEST: {checked} trades compared bar-by-bar with the backtest simulators, mismatches = {bad} -> {'PASS' if bad == 0 and checked > 50 else 'FAIL'}")

if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main("--force" in sys.argv)
