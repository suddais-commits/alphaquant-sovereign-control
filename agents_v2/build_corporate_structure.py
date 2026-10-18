"""
AlphaQuant Global Sovereign Fund - Corporate Structure Builder
Copies existing agents to new names and creates stub files for new agents.
Run once from the CryptoBot root directory.
"""
import os
import shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD_AGENTS = os.path.join(BASE, "agents")
V2 = os.path.join(BASE, "agents_v2")

DEPT1 = os.path.join(V2, "dept1_macro_intelligence")
DEPT2 = os.path.join(V2, "dept2_smc_strategy")
DEPT3 = os.path.join(V2, "dept3_order_flow_whale")
DEPT4 = os.path.join(V2, "dept4_risk_control")
COMMS = os.path.join(V2, "comms_ops")

# ── Existing file → New path  (None = create stub)
COPIES = {
    # Dept 1 CEO & GM
    "agent_02_btc_regime_sentinel.py":   (DEPT1, "CEO_Data_Intelligence.py"),
    "agent_01_market_data_feeder.py":    (DEPT1, "GM_Market_Stream_Feeder.py"),
    # Dept 2 CEO & GM
    "agent_05_enhanced_smc_ict_cascade.py": (DEPT2, "CEO_SMC_Strategy_Cascade.py"),
    "agent_04_smc_structure_fvg_engine.py": (DEPT2, "GM_Structure_Validation_Engine.py"),
    # Dept 2 employee cross-refs
    "agent_03_liquidity_sweep_detector.py": (DEPT2, "OM_21_Liquidity_BSL_Sweep_Detector.py"),
    "agent_20_candle_pattern_recognizer.py":(DEPT2, "OM_34_Engulfing_Candle_Confirmation.py"),
    # Dept 3 CEO & GM
    "board_committee_engine.py":         (DEPT3, "CEO_Whale_Order_Flow.py"),
    "agent_15_cvd_order_flow.py":        (DEPT3, "GM_Cumulative_Volume_Delta.py"),
    # Dept 3 employees
    "agent_14_whale_funding_analysis.py":(DEPT3, "OM_41_Whale_Binance_Top_Trader_Ratio.py"),
    "agent_16_support_resistance_mapper.py":(DEPT3,"OM_45_Volume_Profile_POC_Calculator.py"),
    "agent_21_institutional_research.py":(DEPT3, "OM_49_Shermin_Voshmgir_Tokenomics_Audit.py"),
    # Dept 4 CEO & GM
    "agent_08_position_sizer_risk_guard.py":(DEPT4, "CEO_Risk_Management_CRO.py"),
    "agent_18_portfolio_risk_monitor.py": (DEPT4, "GM_Portfolio_Exposure_Guard.py"),
    # Dept 4 employees
    "agent_22_equity_curve_circuit_breaker.py":(DEPT4,"OM_67_Consecutive_Loss_Streak_Halver.py"),
    "agent_09_binance_execution_engine.py":(DEPT4,"OM_73_Live_Order_Execution_Router.py"),
    "agent_10_trailing_sl_profit_locker.py":(DEPT4,"OM_75_LADDER_Multi_Stage_Profit_Locker.py"),
    # Comms/Ops
    "agent_11_notification_dispatcher.py":(COMMS, "MGR_Telegram_Dispatcher.py"),
    "agent_12_trade_journal_analytics.py":(COMMS, "MGR_Trade_Journal_CSV.py"),
    "guardian_watchdog.py":               (COMMS, "SUPERVISOR_Guardian_Watchdog.py"),
    "agent_23_news_sentiment_gatekeeper.py":(DEPT1,"OM_15_Black_Swan_Keyword_Gatekeeper.py"),
}

# Dept-1 Macro stub definitions (OM_01 to OM_20)
DEPT1_STUBS = [
    ("OM_01_BTC_15m_Trend_Scout.py",       "Scans BTC 15m candles for short-term trend direction using EMA crossovers. Publishes btc_15m_trend to bus."),
    ("OM_02_BTC_1H_Trend_Scout.py",        "Scans BTC 1H candles for medium-term trend direction. Publishes btc_1h_trend to bus."),
    ("OM_03_BTC_4H_Trend_Scout.py",        "Scans BTC 4H candles for macro trend direction. Publishes btc_4h_trend to bus."),
    ("OM_04_BTC_Daily_Macro_Scout.py",     "Scans BTC Daily candles for long-term macro trend. Publishes btc_daily_trend to bus."),
    ("OM_05_ETH_Correlation_Assessor.py",  "Measures ETH/BTC correlation coefficient. High correlation = risk-on; low = rotation signal."),
    ("OM_06_SOL_Velocity_Assessor.py",     "Measures SOL price velocity vs BTC. Detects altcoin season acceleration."),
    ("OM_07_ADX_Volatility_Quant.py",      "Calculates ADX(14) for regime detection. ADX<20=chop, ADX>25=trend. Publishes adx_regime to bus."),
    ("OM_08_Kaufman_Efficiency_Scorer.py", "Calculates Kaufman Efficiency Ratio (KER) to measure trend quality. KER>0.4=trending."),
    ("OM_09_Bollinger_Bandwidth_Squeeze.py","Detects Bollinger Band squeeze (bandwidth < 20th percentile). Signals explosive move incoming."),
    ("OM_10_RSS_CoinDesk_Scraper.py",      "Scrapes CoinDesk RSS feed. Extracts headlines and publishes sentiment_coindesk to bus."),
    ("OM_11_RSS_CoinTelegraph_Scraper.py", "Scrapes CoinTelegraph RSS feed. Extracts headlines and publishes sentiment_cointelegraph to bus."),
    ("OM_12_RSS_Yahoo_Finance_Macro.py",   "Scrapes Yahoo Finance RSS. Tracks DXY/macro headlines. Publishes macro_yahoo to bus."),
    ("OM_13_RSS_CNBC_Fed_Watch.py",        "Scrapes CNBC RSS for Fed/interest rate news. Publishes fed_watch_cnbc to bus."),
    ("OM_14_Twitter_X_Catalyst_Scanner.py","Monitors configured Twitter/X accounts for market-moving crypto catalysts."),
    # OM_15 already copied from agent_23
    ("OM_16_Fear_Greed_Contrarian_Scorer.py","Fetches Fear & Greed index from alternative.me. Contrarian: Extreme Fear=buy zone, Greed=sell zone."),
    ("OM_17_Binance_Vision_Fallback_API.py","Fallback kline/ticker data fetcher using data-api.binance.vision (no auth needed)."),
    ("OM_18_Alternative_Me_Index_Parser.py","Parses Alternative.me Crypto Fear & Greed API. Publishes fear_greed_score to bus."),
    ("OM_19_Macro_Sentiment_Aggregator.py","Aggregates all Dept-1 sentiment sub-scores into a single macro_sentiment_score for the CEO."),
    ("OM_20_Data_Pipeline_Bus_Writer.py",  "Consolidates all Dept-1 outputs and does a single atomic write to the pipeline bus."),
]

# Dept-2 SMC stubs (OM_21 already copied; OM_22 to OM_40)
DEPT2_STUBS = [
    ("OM_22_Liquidity_SSL_Sweep_Detector.py",  "Detects Stop-Side Liquidity sweeps below prior swing lows. Mirror of BSL detector."),
    ("OM_23_Market_Structure_BOS_Mapper.py",   "Maps Break of Structure (BOS) events. BOS above swing high = bullish, below = bearish."),
    ("OM_24_Structure_Shift_CHoCH_Mapper.py",  "Maps Change of Character (CHoCH) — first counter-trend BOS signaling reversal."),
    ("OM_25_Unmitigated_Order_Block_Finder.py","Finds unfilled institutional order blocks (last up-candle before down-move and vice versa)."),
    ("OM_26_Mitigated_OB_Liquidity_Finder.py","Identifies order blocks that have been partially filled — potential continuation zones."),
    ("OM_27_Fair_Value_Gap_Imbalance_Scanner.py","Scans for Fair Value Gaps (3-candle imbalance). Flags gaps that price is revisiting."),
    ("OM_28_Dixit_Vekariya_Inducement_Scout.py","Detects inducement liquidity pools (minor swing points that bait retail before real move)."),
    ("OM_29_Gwaidier_Fractal_POI_Nester.py",   "Nests smaller-TF POIs inside higher-TF order blocks (Gwaidier's fractal entry method)."),
    ("OM_30_Premium_Discount_Range_Quant.py",  "Calculates premium/discount range using swing high/low. Longs only in discount, shorts in premium."),
    ("OM_31_Fibonacci_Golden_Pocket_Pullback.py","Identifies 61.8%-70.2% Fibonacci golden pocket retracements for high-probability entries."),
    ("OM_32_Inside_Bar_Compression_Scanner.py","Detects inside bar patterns (compression before breakout). Higher TF = stronger signal."),
    ("OM_33_Pinbar_Hammer_Wick_Verifier.py",   "Verifies pin bar / hammer wick rejection candles at key S/R and OB zones."),
    # OM_34 already copied from agent_20
    ("OM_35_Multi_TF_Trend_Filter_1H_50EMA.py","Checks that price is above (LONG) or below (SHORT) 50 EMA on 1H chart as trend filter."),
    ("OM_36_Thomas_Bulkowski_Low_Vol_Trap.py", "Detects low-volume breakout traps per Bulkowski's statistics — flags false breakouts."),
    ("OM_37_VSA_Tom_Williams_No_Supply_Bar.py","Detects VSA 'No Supply' bar: narrow spread, low volume on down-bar = bullish."),
    ("OM_38_VSA_Tom_Williams_No_Demand_Bar.py","Detects VSA 'No Demand' bar: narrow spread, low volume on up-bar = bearish."),
    ("OM_39_VSA_Richard_Wyckoff_Stopping_Vol.py","Detects Wyckoff stopping volume: high volume + narrow spread after a trend = reversal alert."),
    ("OM_40_VSA_Climax_Trap_Rejection_Gate.py","Detects VSA climax bars (ultra-high volume, wide spread) that get immediately rejected."),
]

# Dept-3 Whale stubs (OM_41,45,49 already copied; rest are stubs)
DEPT3_STUBS = [
    ("OM_42_Global_Retail_Long_Short_Ratio.py","Fetches global retail long/short ratio from Binance. Extreme longs=bearish, extreme shorts=bullish."),
    ("OM_43_Adverse_Funding_Rate_Filter.py",   "Blocks new LONG if funding rate > +0.1% (you pay). Blocks SHORT if funding < -0.05%."),
    ("OM_44_Favorable_Funding_Fee_Arbitrageur.py","Identifies funding fee arbitrage opportunities when rate is extreme and mean-reverting."),
    ("OM_46_Value_Area_High_Low_Mapper.py",    "Calculates Value Area High (VAH) and Value Area Low (VAL) from volume profile data."),
    ("OM_47_High_Volume_Node_HVN_Blocker.py",  "Identifies High Volume Nodes (HVN) that act as price magnets or strong S/R zones."),
    ("OM_48_Low_Volume_Node_LVN_Sniper.py",    "Identifies Low Volume Nodes (LVN) where price moves fast — ideal sniper entry zones."),
    ("OM_50_Circulating_Max_Supply_Assessor.py","Checks circulating vs max supply ratio. High ratio = less inflation risk."),
    ("OM_51_Fully_Diluted_Valuation_FDV_Ratio.py","Calculates FDV/Market Cap ratio. FDV > 3x MC = excessive dilution risk = skip."),
    ("OM_52_DefiLlama_TVL_Proxy_Scraper.py",  "Scrapes DeFiLlama for protocol TVL data. Rising TVL = fundamental demand."),
    ("OM_53_Arkham_Exchange_Inflow_Auditor.py","Monitors Arkham for large exchange inflows (bearish — whales depositing to sell)."),
    ("OM_54_Arkham_Whale_Wallet_Watcher.py",  "Watches known whale wallets via Arkham. Accumulation = bullish, distribution = bearish."),
    ("OM_55_Dr_Ernest_Chan_ZScore_Climax.py",  "Calculates Z-score of price relative to rolling mean. |Z|>2.5 = statistical climax — fade signal."),
    ("OM_56_Dr_Alexander_Elder_Ray_Bull_Power.py","Calculates Elder's Bull Power (High - EMA13). Positive and rising = bulls in control."),
    ("OM_57_Dr_Alexander_Elder_Ray_Bear_Power.py","Calculates Elder's Bear Power (Low - EMA13). Negative and rising = bears weakening."),
    ("OM_58_Mark_B_Fisher_ACD_Pivot_Range.py", "Calculates ACD Opening Range and A-up/A-down levels per Mark Fisher's methodology."),
    ("OM_59_Myles_Wilson_Walker_Elliott_CWave.py","Attempts Elliott Wave C-wave detection. C-wave = 1.618x of A-wave move typically."),
    ("OM_60_Order_Book_Imbalance_Pressure.py", "Measures order book bid/ask imbalance. Bid > Ask by 2x = buy pressure. Uses Binance depth API."),
]

# Dept-4 Risk stubs (OM_67,73,75 already copied; rest are stubs)
DEPT4_STUBS = [
    ("OM_61_Fractional_Kelly_Criterion_Sizer.py","Calculates fractional Kelly position size (25% Kelly) based on win rate and R:R ratio."),
    ("OM_62_Robert_Carver_Volatility_Scalar.py","Scales position size using Carver's volatility targeting. Reduces size when vol is high."),
    ("OM_63_Nassim_Taleb_Fat_Tail_Buffer.py",  "Adds Taleb-inspired fat-tail buffer: reduces size by 50% when VIX-equivalent is elevated."),
    ("OM_64_Drawdown_Ladder_10pct_Brake.py",   "Monitors equity. If drawdown hits 10%, reduces position sizing by 50%."),
    ("OM_65_Drawdown_Ladder_15pct_Brake.py",   "Monitors equity. If drawdown hits 15%, reduces position sizing by 75%."),
    ("OM_66_Drawdown_Ladder_20pct_Halt.py",    "Monitors equity. If drawdown hits 20%, halts all new trades until manual reset."),
    ("OM_68_Consecutive_Loss_Streak_Halter.py","If loss streak >= 5 consecutive trades, halts all trading until equity recovery."),
    ("OM_69_Binance_Precision_Step_Rounder.py","Rounds quantity to Binance's stepSize and price to tickSize for valid orders."),
    ("OM_70_Bybit_Precision_Lot_Rounder.py",   "Rounds quantity to Bybit's lot size requirements for valid order placement."),
    ("OM_71_Dynamic_Margin_Band_Calculator.py","Calculates dynamic min/max margin bands based on current account equity."),
    ("OM_72_Margin_Utilization_Cap_Enforcer.py","Blocks new trades if total margin utilization exceeds configured cap (default 40%)."),
    ("OM_74_Paper_Trading_Simulation_Router.py","Routes trade signals to paper trade simulation (no real orders). Logs to paper_trades.csv."),
    ("OM_76_TRAIL3_ATR_Trailing_Stop_Locker.py","Implements 3x ATR trailing stop-loss for the runner portion of a trade."),
    ("OM_77_Direction_Flip_Market_Closer.py",  "Closes open position immediately when signal flips direction (LONG→SHORT or vice versa)."),
    ("OM_78_Revenge_Trading_Cooldown_Timer.py","Enforces a 30-minute cooldown after a stop-loss hit to prevent revenge trading."),
    ("OM_79_Emergency_Global_Market_Flusher.py","Emergency kill-switch: closes ALL open positions on all exchanges immediately."),
    ("OM_80_Cloud_Cloudflare_Failover_Handler.py","Handles Cloudflare 403/429 blocks. Rotates proxy or waits with exponential backoff."),
]

STUB_HEADER = '''"""
{dept} | {title}
AlphaQuant Global Sovereign Fund Private Limited
{desc}

STATUS: STUB — Logic not yet implemented.
        This agent is registered in the corporate hierarchy.
        Implement run() and integrate with pipeline_bus when ready.
"""
import os, sys, time, logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "{name}"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, f"{{AGENT_NAME.lower()}}.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


def run() -> dict:
    """
    TODO: Implement {name} logic here.
    Return a dict with your agent's output to be written to the pipeline bus.
    """
    raise NotImplementedError(f"{{AGENT_NAME}} is a stub. Implement run() before use.")


def main():
    logging.info(f"{{AGENT_NAME}} started (STUB MODE — not implemented).")
    while True:
        try:
            record_heartbeat(AGENT_NAME, "STUB_NOT_IMPLEMENTED")
        except Exception as e:
            logging.error(f"Heartbeat error: {{e}}")
        time.sleep(300)  # 5-min heartbeat while stub


if __name__ == "__main__":
    main()
'''


def write_stub(folder: str, filename: str, dept: str, desc: str):
    name = filename.replace(".py", "")
    title = name.replace("_", " ")
    content = STUB_HEADER.format(dept=dept, title=title, desc=desc, name=name)
    path = os.path.join(folder, filename)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  STUB  → {filename}")
    else:
        print(f"  SKIP  → {filename} (already exists)")


def copy_agent(src_name: str, dest_folder: str, dest_name: str):
    # Try agents/ folder first, then root
    for src_base in [OLD_AGENTS, BASE]:
        src = os.path.join(src_base, src_name)
        if os.path.exists(src):
            dest = os.path.join(dest_folder, dest_name)
            shutil.copy2(src, dest)
            print(f"  COPY  → {dest_name}  (from {src_name})")
            return
    print(f"  MISS  → {src_name} not found — creating stub placeholder")
    # Write a note stub instead
    path = os.path.join(dest_folder, dest_name)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(f'"""Copied from {src_name} — source not found. Implement manually."""\n')


if __name__ == "__main__":
    print("\n=== AlphaQuant Corporate Structure Builder ===\n")

    print("\n[DEPT 1] Macro Intelligence — Copying existing agents...")
    for src, (folder, dst) in COPIES.items():
        copy_agent(src, folder, dst)

    print("\n[DEPT 1] Creating stubs...")
    for fname, desc in DEPT1_STUBS:
        write_stub(DEPT1, fname, "DEPT-1 Macro Intelligence", desc)

    print("\n[DEPT 2] SMC Strategy — Creating stubs...")
    for fname, desc in DEPT2_STUBS:
        write_stub(DEPT2, fname, "DEPT-2 SMC & ICT Strategy", desc)

    print("\n[DEPT 3] Order Flow Whale — Creating stubs...")
    for fname, desc in DEPT3_STUBS:
        write_stub(DEPT3, fname, "DEPT-3 Order Flow & Whale", desc)

    print("\n[DEPT 4] Risk Control — Creating stubs...")
    for fname, desc in DEPT4_STUBS:
        write_stub(DEPT4, fname, "DEPT-4 Risk Control", desc)

    print("\n[DONE] Corporate structure deployed.\n")
