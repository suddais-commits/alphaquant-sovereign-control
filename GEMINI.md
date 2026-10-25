# CryptoBot - Standing Rules for AI assistants (replaces the old AGENTS.md / GEMINI.md; save the same text as both)

## 1. Honest status of the strategies (from statistical tests with a random control)
- 1H sweep-reclaim signal (12,826 trades, 30 coins, 2 years): NO edge. Mean -0.119R vs random -0.063R.
- 1H swing engine entries (1,916 trades): NO edge. -0.116R vs random -0.028R.
- 1H/4H conviction score (83+ gate): no relation to results. 4H Donchian: no clear edge.
- Daily Donchian-55 trend breakout: the ONLY candidate. It beat random on the original 30 coins; on 18 unseen coins only 1 of 4 variants passed. It is NOT proven. It runs in PAPER mode only (daily_trend_paper.py).
- Old claims such as "75% win rate" came from a 7-day, 30-trade test and must not be repeated.
- Realistic expectation: about +12% to +18% per year at 0.5% risk per trade with 13-20% drawdowns. No system can deliver 3000% per month.

## 2. Rules for every AI assistant working in this folder
1. Never call a result "positive", "strong" or "profitable" unless it beats a random control with the same exit, in BOTH halves of time, with a month-level bootstrap interval above zero, on at least ~100 independent trades. Report plain numbers.
2. Never lower a threshold, relax a filter or tune a parameter just to get more trades or a better-looking result.
3. Do only what the user asked. Do not create, rewrite or regenerate files that were not requested. Do not read old chat history. Do not list directories or poll logs repeatedly. Do not run pytest unless asked. Keep replies short (the user pays for every token).
4. Never print, copy or commit secrets (API keys, bot tokens, proxy passwords). Credentials live ONLY in .env, read with os.getenv. If you find a hardcoded secret, tell the user and move it to .env.
5. Keep USE_V2=false and EXCHANGE_EXECUTION_ENABLED=false until the paper results justify otherwise AND the user explicitly says so. No real orders without explicit permission.
6. Backtests: use closed candles only, entry at the NEXT bar open, stop assumed hit before target in the same bar, fees (4 bps/side) and slippage (5 bps) always on. No "zero-slippage" assumption.
7. If a result looks too good, assume a bug first and test it (random-entry control, trade audit).

## 3. Files that matter now
- daily_trend_paper.py (paper trader with 3 books: D55-LADDER, D55-TRAIL3, D55-C1DONCH20; paper_state.json, paper_trades.csv, paper_run.log), paper_status.py / show_status.bat (status)
- donchian_backtest.py (full Binance portfolio backtester + sweep + stress tests for Donchian variants)
- edge_test.py ... edge_test4.py, signal_csv_test.py (honest tests), config.py/regime.py/scoring.py/risk.py (v2 modules, not wired live)
- master_bot.py and agents/ = old 1H system; no proven edge; do not trade real money with it.

## 4. Environment
- Run Python with the project venv: .venv\Scripts\python.exe
- PROXY_ENABLED=false when a system VPN is active.
