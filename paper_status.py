"""paper_status.py - prints a short status of the paper trader. Run via show_status.bat (double-click) and copy the text to Claude."""
import os, json
import pandas as pd
if not os.path.exists("paper_state.json"):
    print("No paper_state.json yet - the paper trader has not run in this folder.")
else:
    st = json.load(open("paper_state.json"))
    tr = pd.read_csv("paper_trades.csv") if os.path.exists("paper_trades.csv") else pd.DataFrame()
    for book, b in st["books"].items():
        print(f"\n{book}: paper equity {b['equity']:.2f} ({(b['equity']/1000-1)*100:+.1f}% from 1000) | open trades {len(b['open'])} | last bar checked {b['last_bar']}")
        for p in b["open"]:
            print(f"   open {p['sym']} {'LONG' if p['side']>0 else 'SHORT'} entry {p['entry']:.6g} current stop {p['cur']:.6g} since {str(p['entry_time'])[:10]}")
        if len(tr):
            t = tr[tr["book"] == book]
            if len(t):
                r = t["net_R"] - t["funding_R"]
                print(f"   closed trades {len(t)} | win rate {(r>0).mean()*100:.0f}% | average R after funding {r.mean():+.2f} | total pnl {t['pnl_usd'].sum():+.2f}")
    if len(tr): print("\nLast closed trades:\n" + tr.tail(5)[["book", "sym", "side", "exit_time", "net_R", "pnl_usd"]].to_string(index=False))
    if os.path.exists("paper_run.log"):
        print("\nLast lines of paper_run.log:"); print("".join(open("paper_run.log", encoding="utf-8", errors="ignore").readlines()[-4:]))
