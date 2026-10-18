# AlphaQuant Global Sovereign Fund Private Limited
## Corporate Multi-Agent Hierarchy & Registry

### Executive HQ & Oversight
| Role / Designation | File / Module | Status | Function / Description |
|---|---|---|---|
| Founder & Sovereign Allocator | `CHAIRMAN_AlphaQuant_Sovereign_Fund.py` | Active (Paper) | Reads Dept scores, enforces risk veto (<30), authorises signals |
| System Cache Doctor | `CLEANER_System_Cache_Doctor.py` | Active | Rotates logs (>10MB), deletes `tmp_*.json`, cleans `__pycache__` |
| Comms Manager (Telegram) | `agents_v2/comms_ops/MGR_Telegram_Dispatcher.py` | Active | Dispatches Telegram trade notifications and alerts |
| Trade Journal Manager | `agents_v2/comms_ops/MGR_Trade_Journal_CSV.py` | Active | Records executed and paper trades to CSV |
| Operations Supervisor | `agents_v2/comms_ops/SUPERVISOR_Guardian_Watchdog.py` | Active | Monitors agent heartbeats and system health |

---

### Department 1: Macro Intelligence & Sentiment (`agents_v2/dept1_macro_intelligence/`)
* **CEO**: `CEO_Data_Intelligence.py` (Source: `agent_02_btc_regime_sentinel.py`) — Active
* **GM**: `GM_Market_Stream_Feeder.py` (Source: `agent_01_market_data_feeder.py`) — Active
* **OM_01 to OM_20 (Operational Specialists)**:
  * `OM_01_BTC_15m_Trend_Scout.py` [STUB] — Scans BTC 15m candles via EMA
  * `OM_02_BTC_1H_Trend_Scout.py` [STUB] — Scans BTC 1H medium-term trend
  * `OM_03_BTC_4H_Trend_Scout.py` [STUB] — Scans BTC 4H macro trend
  * `OM_04_BTC_Daily_Macro_Scout.py` [STUB] — Scans BTC Daily candles
  * `OM_05_ETH_Correlation_Assessor.py` [STUB] — ETH/BTC correlation coefficient
  * `OM_06_SOL_Velocity_Assessor.py` [STUB] — SOL price velocity vs BTC
  * `OM_07_ADX_Volatility_Quant.py` [STUB] — ADX(14) regime detection (<20 chop, >25 trend)
  * `OM_08_Kaufman_Efficiency_Scorer.py` [STUB] — Kaufman Efficiency Ratio (>0.4 trend)
  * `OM_09_Bollinger_Bandwidth_Squeeze.py` [STUB] — BB squeeze detection (<20th percentile)
  * `OM_10_RSS_CoinDesk_Scraper.py` [STUB] — CoinDesk RSS sentiment feed
  * `OM_11_RSS_CoinTelegraph_Scraper.py` [STUB] — CoinTelegraph RSS sentiment
  * `OM_12_RSS_Yahoo_Finance_Macro.py` [STUB] — Yahoo Finance DXY/macro feed
  * `OM_13_RSS_CNBC_Fed_Watch.py` [STUB] — CNBC Fed/interest rate tracker
  * `OM_14_Twitter_X_Catalyst_Scanner.py` [STUB] — Twitter catalyst scraper
  * `OM_15_Black_Swan_Keyword_Gatekeeper.py` [ACTIVE] — Source: `agent_23_news_sentiment_gatekeeper.py`
  * `OM_16_Fear_Greed_Contrarian_Scorer.py` [STUB] — Alternative.me contrarian scorer
  * `OM_17_Binance_Vision_Fallback_API.py` [STUB] — Unauthenticated fallback market data
  * `OM_18_Alternative_Me_Index_Parser.py` [STUB] — Fear & Greed API parser
  * `OM_19_Macro_Sentiment_Aggregator.py` [STUB] — Sentiment sub-score aggregation
  * `OM_20_Data_Pipeline_Bus_Writer.py` [STUB] — Atomic Dept-1 bus consolidation

---

### Department 2: SMC & ICT Quantitative Strategy (`agents_v2/dept2_smc_strategy/`)
* **CEO**: `CEO_SMC_Strategy_Cascade.py` (Source: `agent_05_enhanced_smc_ict_cascade.py`) — Active
* **GM**: `GM_Structure_Validation_Engine.py` (Source: `agent_04_smc_structure_fvg_engine.py`) — Active
* **OM_21 to OM_40 (Operational Specialists)**:
  * `OM_21_Liquidity_BSL_Sweep_Detector.py` [ACTIVE] — Source: `agent_03_liquidity_sweep_detector.py`
  * `OM_22_Liquidity_SSL_Sweep_Detector.py` [STUB] — Sell-side liquidity sweep detector
  * `OM_23_Market_Structure_BOS_Mapper.py` [STUB] — Break of Structure (BOS) mapper
  * `OM_24_Structure_Shift_CHoCH_Mapper.py` [STUB] — Change of Character (CHoCH) mapper
  * `OM_25_Unmitigated_Order_Block_Finder.py` [STUB] — Unfilled institutional order blocks
  * `OM_26_Mitigated_OB_Liquidity_Finder.py` [STUB] — Partially filled order blocks
  * `OM_27_Fair_Value_Gap_Imbalance_Scanner.py` [STUB] — 3-candle FVG imbalance scanner
  * `OM_28_Dixit_Vekariya_Inducement_Scout.py` [STUB] — Retail inducement liquidity pools
  * `OM_29_Gwaidier_Fractal_POI_Nester.py` [STUB] — Nested multi-TF POIs
  * `OM_30_Premium_Discount_Range_Quant.py` [STUB] — Premium/discount equilibrium filter
  * `OM_31_Fibonacci_Golden_Pocket_Pullback.py` [STUB] — 61.8%-70.2% golden pocket filter
  * `OM_32_Inside_Bar_Compression_Scanner.py` [STUB] — Inside bar compression detection
  * `OM_33_Pinbar_Hammer_Wick_Verifier.py` [STUB] — Rejection wick confirmation at POIs
  * `OM_34_Engulfing_Candle_Confirmation.py` [ACTIVE] — Source: `agent_20_candle_pattern_recognizer.py`
  * `OM_35_Multi_TF_Trend_Filter_1H_50EMA.py` [STUB] — 1H 50 EMA trend filter
  * `OM_36_Thomas_Bulkowski_Low_Vol_Trap.py` [STUB] — Low-volume false breakout filter
  * `OM_37_VSA_Tom_Williams_No_Supply_Bar.py` [STUB] — VSA No Supply detection
  * `OM_38_VSA_Tom_Williams_No_Demand_Bar.py` [STUB] — VSA No Demand detection
  * `OM_39_VSA_Richard_Wyckoff_Stopping_Vol.py` [STUB] — Stopping volume reversal alerts
  * `OM_40_VSA_Climax_Trap_Rejection_Gate.py` [STUB] — Climax volume rejection filter

---

### Department 3: Order Flow & Whale Intelligence (`agents_v2/dept3_order_flow_whale/`)
* **CEO**: `CEO_Whale_Order_Flow.py` (Source: `board_committee_engine.py`) — Active
* **GM**: `GM_Cumulative_Volume_Delta.py` (Source: `agent_15_cvd_order_flow.py`) — Active
* **OM_41 to OM_60 (Operational Specialists)**:
  * `OM_41_Whale_Binance_Top_Trader_Ratio.py` [ACTIVE] — Source: `agent_14_whale_funding_analysis.py`
  * `OM_42_Global_Retail_Long_Short_Ratio.py` [STUB] — Global retail sentiment positioning
  * `OM_43_Adverse_Funding_Rate_Filter.py` [STUB] — Funding rate penalty/gatekeeper
  * `OM_44_Favorable_Funding_Fee_Arbitrageur.py` [STUB] — Funding rate mean-reversion arb
  * `OM_45_Volume_Profile_POC_Calculator.py` [ACTIVE] — Source: `agent_16_support_resistance_mapper.py`
  * `OM_46_Value_Area_High_Low_Mapper.py` [STUB] — VAH and VAL calculator
  * `OM_47_High_Volume_Node_HVN_Blocker.py` [STUB] — HVN price magnet / block zones
  * `OM_48_Low_Volume_Node_LVN_Sniper.py` [STUB] — LVN slippage & fast-move zones
  * `OM_49_Shermin_Voshmgir_Tokenomics_Audit.py` [ACTIVE] — Source: `agent_21_institutional_research.py`
  * `OM_50_Circulating_Max_Supply_Assessor.py` [STUB] — Circulating vs max supply checker
  * `OM_51_Fully_Diluted_Valuation_FDV_Ratio.py` [STUB] — FDV / MC ratio risk filter
  * `OM_52_DefiLlama_TVL_Proxy_Scraper.py` [STUB] — On-chain TVL scraper
  * `OM_53_Arkham_Exchange_Inflow_Auditor.py` [STUB] — Whale exchange inflow auditor
  * `OM_54_Arkham_Whale_Wallet_Watcher.py` [STUB] — Whale wallet accumulation tracker
  * `OM_55_Dr_Ernest_Chan_ZScore_Climax.py` [STUB] — Statistical Z-score mean reversion
  * `OM_56_Dr_Alexander_Elder_Ray_Bull_Power.py` [STUB] — Elder Bull Power (High - EMA13)
  * `OM_57_Dr_Alexander_Elder_Ray_Bear_Power.py` [STUB] — Elder Bear Power (Low - EMA13)
  * `OM_58_Mark_B_Fisher_ACD_Pivot_Range.py` [STUB] — ACD opening range levels
  * `OM_59_Myles_Wilson_Walker_Elliott_CWave.py` [STUB] — Elliott Wave C-wave targeter
  * `OM_60_Order_Book_Imbalance_Pressure.py` [STUB] — L2 order book bid/ask pressure

---

### Department 4: Risk Management & Fortress Control (`agents_v2/dept4_risk_control/`)
* **CEO**: `CEO_Risk_Management_CRO.py` (Source: `agent_08_position_sizer_risk_guard.py`) — Active
* **GM**: `GM_Portfolio_Exposure_Guard.py` (Source: `agent_18_portfolio_risk_monitor.py`) — Active
* **OM_61 to OM_80 (Operational Specialists)**:
  * `OM_61_Fractional_Kelly_Criterion_Sizer.py` [STUB] — 25% Kelly sizing
  * `OM_62_Robert_Carver_Volatility_Scalar.py` [STUB] — Carver volatility scaler
  * `OM_63_Nassim_Taleb_Fat_Tail_Buffer.py` [STUB] — Fat-tail buffer sizing discount
  * `OM_64_Drawdown_Ladder_10pct_Brake.py` [STUB] — 10% DD: reduce sizing by 50%
  * `OM_65_Drawdown_Ladder_15pct_Brake.py` [STUB] — 15% DD: reduce sizing by 75%
  * `OM_66_Drawdown_Ladder_20pct_Halt.py` [STUB] — 20% DD: complete trade halt
  * `OM_67_Consecutive_Loss_Streak_Halver.py` [ACTIVE] — Source: `agent_22_equity_curve_circuit_breaker.py`
  * `OM_68_Consecutive_Loss_Streak_Halter.py` [STUB] — 5-loss streak hard halt
  * `OM_69_Binance_Precision_Step_Rounder.py` [STUB] — Binance tick/step size formatter
  * `OM_70_Bybit_Precision_Lot_Rounder.py` [STUB] — Bybit lot size formatter
  * `OM_71_Dynamic_Margin_Band_Calculator.py` [STUB] — Dynamic margin limits by equity
  * `OM_72_Margin_Utilization_Cap_Enforcer.py` [STUB] — 40% total margin cap enforcer
  * `OM_73_Live_Order_Execution_Router.py` [ACTIVE] — Source: `agent_09_binance_execution_engine.py` (Gated: Live Disabled)
  * `OM_74_Paper_Trading_Simulation_Router.py` [STUB] — Dedicated paper order executor
  * `OM_75_LADDER_Multi_Stage_Profit_Locker.py` [ACTIVE] — Source: `agent_10_trailing_sl_profit_locker.py`
  * `OM_76_TRAIL3_ATR_Trailing_Stop_Locker.py` [STUB] — 3x ATR trailing stop implementation
  * `OM_77_Direction_Flip_Market_Closer.py` [STUB] — Signal reversal position flusher
  * `OM_78_Revenge_Trading_Cooldown_Timer.py` [STUB] — 30-minute post-loss cooldown
  * `OM_79_Emergency_Global_Market_Flusher.py` [STUB] — Emergency kill-switch close-all
  * `OM_80_Cloud_Cloudflare_Failover_Handler.py` [STUB] — Cloudflare 403/429 backoff & rotation

---

### Total Architecture Metrics
* **Total Dedicated Files**: 91 Python agent files + 2 Root executives (`CHAIRMAN`, `CLEANER`).
* **Active Copied Modules**: 18 files running live operational logic from tested modules.
* **Specialized Stubs Registered**: 62 files ready for incremental algorithmic implementation.
