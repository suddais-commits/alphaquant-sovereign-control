"""
Gemini AI Analysis Service for CryptoBot.

Features:
- Strictly pinned to 'gemini-2.5-flash' model to prevent API blocks & unexpected deprecations.
- Robust exponential backoff retry handler with jitter for HTTP 429 (Too Many Requests / ResourceExhausted),
  HTTP 503 (Service Unavailable), 500, 504, and network connection drops.
- Local rate throttling to prevent burst rate-limit hits.
- Full proxy support (Webshare proxy compatibility).
- Graceful degradation: never crashes the trading bot if API is down or key is unconfigured.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from typing import Any, Dict, Optional

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass

try:
    from proxy_manager import get_proxy
except ImportError:
    def get_proxy():
        return None

log = logging.getLogger("gemini_service")

# ─── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Rate limiting governor
_last_gemini_call_time = 0.0
_MIN_REQUEST_INTERVAL = 1.0  # Minimum seconds between API requests


def get_gemini_api_key() -> str:
    """Retrieve GEMINI_API_KEY from environment."""
    return os.getenv("GEMINI_API_KEY", "").strip()


def is_gemini_configured() -> bool:
    """Returns True if GEMINI_API_KEY is present."""
    return bool(get_gemini_api_key())


def _throttle():
    """Ensure at least _MIN_REQUEST_INTERVAL seconds between calls."""
    global _last_gemini_call_time
    now = time.monotonic()
    elapsed = now - _last_gemini_call_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_gemini_call_time = time.monotonic()


def call_gemini_with_backoff(
    prompt: str,
    system_instruction: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    max_retries: int = 5,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    timeout: int = 25,
) -> Optional[str]:
    """
    Execute a Gemini API request with strict exponential backoff retry handler.
    Handles 429 (ResourceExhausted / Rate Limit), 503, 500, 504 and network errors.
    
    Strictly forces 'gemini-2.5-flash' unless specified.
    """
    api_key = get_gemini_api_key()
    if not api_key:
        log.debug("Gemini API key not configured. Skipping Gemini call.")
        return None

    target_model = model or DEFAULT_MODEL
    url = f"{API_BASE_URL}/{target_model}:generateContent?key={api_key}"

    # Build payload
    payload: Dict[str, Any] = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.8,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
        }
    }

    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }

    headers = {
        "Content-Type": "application/json",
    }

    proxies = get_proxy()
    delay = initial_delay

    for attempt in range(1, max_retries + 1):
        try:
            _throttle()
            log.debug("Gemini API call attempt %d/%d (model: %s)", attempt, max_retries, target_model)
            
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                proxies=proxies,
                timeout=timeout,
            )

            # Handle 429 Too Many Requests / Rate Limit
            if response.status_code == 429:
                jitter = random.uniform(0.1, 0.7)
                sleep_time = min(delay + jitter, max_delay)
                log.warning(
                    "Gemini API 429 Rate Limit hit (attempt %d/%d). Backing off for %.2fs...",
                    attempt, max_retries, sleep_time
                )
                time.sleep(sleep_time)
                delay *= backoff_factor
                continue

            # Handle 5xx Server Errors
            if response.status_code in (500, 502, 503, 504):
                jitter = random.uniform(0.1, 0.5)
                sleep_time = min(delay + jitter, max_delay)
                log.warning(
                    "Gemini API server error %d (attempt %d/%d). Retrying in %.2fs...",
                    response.status_code, attempt, max_retries, sleep_time
                )
                time.sleep(sleep_time)
                delay *= backoff_factor
                continue

            # Check other client errors
            if response.status_code != 200:
                log.error("Gemini API error (status %d): %s", response.status_code, response.text[:300])
                return None

            # Success: Parse response
            data = response.json()
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                if parts and "text" in parts[0]:
                    return parts[0]["text"]

            return None

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as net_err:
            jitter = random.uniform(0.2, 0.8)
            sleep_time = min(delay + jitter, max_delay)
            log.warning(
                "Gemini API network error: %s (attempt %d/%d). Retrying in %.2fs...",
                net_err, attempt, max_retries, sleep_time
            )
            time.sleep(sleep_time)
            delay *= backoff_factor
            continue
        except Exception as e:
            log.error("Unexpected error calling Gemini API: %s", e)
            return None

    log.error("Gemini API exhausted all %d retries. Proceeding with fallback.", max_retries)
    return None


# ─── Knowledge Base Integration ────────────────────────────────────────────────
_KNOWLEDGE_BASE_CACHE: Optional[dict] = None

def get_strategy_knowledge_base() -> dict:
    """Load and cache the strategy knowledge base extracted from classic trading books."""
    global _KNOWLEDGE_BASE_CACHE
    if _KNOWLEDGE_BASE_CACHE is not None:
        return _KNOWLEDGE_BASE_CACHE

    kb_path = os.path.join(os.path.dirname(__file__), "strategy_knowledge_base.json")
    if os.path.isfile(kb_path):
        try:
            with open(kb_path, "r", encoding="utf-8") as f:
                _KNOWLEDGE_BASE_CACHE = json.load(f)
                return _KNOWLEDGE_BASE_CACHE
        except Exception as e:
            log.warning("Could not load strategy_knowledge_base.json: %s", e)
    return {}


def evaluate_trade_setup(
    symbol_or_payload: Any = None,
    direction: str = "LONG",
    timeframe: str = "15m",
    score: float = 80.0,
    entry: Optional[float] = None,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    indicators: Optional[dict] = None,
    mtf_summary: Optional[dict] = None,
    **kwargs
) -> dict:
    """
    Evaluates a trading setup with Gemini AI using synthesized institutional rules.
    Fail-closed: Returns ai_confirmed=False if API key is missing or calls fail.
    Supports dictionary payload, positional arguments, or keyword arguments.
    """
    if not is_gemini_configured():
        return {
            "ai_confirmed": False,
            "ai_score": 0.0,
            "reason": "Gemini API key not configured (fail-closed)",
            "disqualifiers_triggered": ["API_KEY_UNCONFIGURED"],
            "model_used": DEFAULT_MODEL,
        }

    # Normalize input
    if isinstance(symbol_or_payload, dict):
        payload = symbol_or_payload
        symbol = str(payload.get("symbol", "UNKNOWN"))
        direction = str(payload.get("direction", "LONG"))
        timeframe = str(payload.get("timeframe", "15m"))
        score = float(payload.get("score", 80.0))
        entry_val = payload.get("entry")
        sl_val = payload.get("sl")
        tp_val = payload.get("tp")
        indicators = payload.get("indicators", payload)
        mtf_summary = payload.get("mtf_summary", payload.get("macro_bias", {}))
    else:
        symbol = str(symbol_or_payload or kwargs.get("symbol", "UNKNOWN"))
        direction = str(direction or kwargs.get("direction", "LONG"))
        timeframe = str(timeframe or kwargs.get("timeframe", "15m"))
        score = float(score if score is not None else kwargs.get("score", 80.0))
        entry_val = entry if entry is not None else kwargs.get("entry")
        sl_val = sl if sl is not None else kwargs.get("sl")
        tp_val = tp if tp is not None else kwargs.get("tp")
        indicators = indicators or kwargs.get("indicators", {})
        mtf_summary = mtf_summary or kwargs.get("mtf_summary", kwargs.get("cascade_data", {}))

    # Load system prompt from external file for easy updates
    try:
        prompt_path = os.path.join(os.path.dirname(__file__), "PATTERN_VALIDATION_GEMINI_PROMPT.txt")
        if not os.path.exists(prompt_path):
            prompt_path = os.path.join(os.path.dirname(__file__), "ANTIGRAVITY_MASTER_PROMPT.txt")
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except Exception as e:
        log.warning("Failed to load prompt: %s. Using built-in prompt.", e)
        system_prompt = "You are an elite Institutional Quantitative Risk & SMC/VSA Trading Specialist."

    user_prompt = f"""
Critically evaluate this crypto futures setup against the Multi-Book Strategy Knowledge Base:
Symbol: {symbol}
Direction: {direction}
Timeframe: {timeframe}
Score: {score}
Entry: {entry_val}
Stop Loss: {sl_val}
Take Profit: {tp_val}
Indicators: {json.dumps(indicators, default=str) if isinstance(indicators, dict) else str(indicators)}
MTF Summary: {json.dumps(mtf_summary, default=str) if isinstance(mtf_summary, dict) else str(mtf_summary)}

Should this trade be executed or disqualified? Output your JSON decision with fields: "confirmed" (bool), "score" (0.0-1.0), "reason" (str), "disqualifiers_triggered" (list).
"""
    raw_response = call_gemini_with_backoff(user_prompt, system_instruction=system_prompt, model=DEFAULT_MODEL)
    if not raw_response:
        return {
            "ai_confirmed": False,
            "ai_score": 0.0,
            "reason": "Gemini API request failed / exhausted retries (fail-closed)",
            "disqualifiers_triggered": ["API_UNAVAILABLE"],
            "model_used": DEFAULT_MODEL,
        }

    try:
        clean_text = raw_response.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()

        parsed = json.loads(clean_text)
        confirmed = bool(parsed.get("confirmed", False))
        ai_score = float(parsed.get("score", 0.0))
        return {
            "ai_confirmed": confirmed and ai_score >= 0.50,
            "ai_score": ai_score,
            "reason": str(parsed.get("reason", "Evaluated by Gemini Flash")),
            "disqualifiers_triggered": list(parsed.get("disqualifiers_triggered", [])),
            "model_used": DEFAULT_MODEL,
        }
    except Exception as parse_err:
        log.warning("Could not parse Gemini JSON response (%s): %s", parse_err, raw_response[:100])
        return {
            "ai_confirmed": False,
            "ai_score": 0.0,
            "reason": f"Gemini response parse failure ({parse_err}) (fail-closed)",
            "disqualifiers_triggered": ["JSON_PARSE_ERROR"],
            "model_used": DEFAULT_MODEL,
        }


# ─── AGENT 10: SELF-LEARNING LOSS ANALYTICS ENGINE ─────────────────────────────
def run_agent10_self_learning(trades: list) -> dict:
    """
    Agent 10: Evaluates 30-day trade logs using Gemini 2.5 Flash with AGENT10_SELF_LEARNING_PROMPT.txt.
    Returns quantitative performance audit, loss patterns, and actionable adaptive rules.
    """
    prompt_path = os.path.join(os.path.dirname(__file__), "AGENT10_SELF_LEARNING_PROMPT.txt")
    system_prompt = None
    if os.path.isfile(prompt_path):
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                system_prompt = f.read()
        except Exception as e:
            log.warning("Could not read AGENT10_SELF_LEARNING_PROMPT.txt: %s", e)

    if not system_prompt:
        system_prompt = (
            "You are AGENT 10: The Master Self-Learning & Auto-Improvement Intelligence. "
            "Analyze 30-day trade performance, identify loss patterns, and output JSON with keys: "
            "'analysis', 'patterns', 'improvements', 'newRules', 'autoApply'."
        )

    user_prompt = f"""
Perform an Institutional Quantitative Audit and Loss Pattern Analysis on the following 30-day trade executions:
{json.dumps(trades, indent=2)}

Detect recurring structural mistakes, coin-specific weaknesses, toxic hours, and score distributions.
Formulate adaptive rules to optimize the system. Output your valid JSON response.
"""
    if not is_gemini_configured():
        log.info("Gemini API key unconfigured; executing Agent 10 algorithmic self-learning audit...")
        total_trades = len(trades)
        wins = sum(1 for t in trades if t.get("pnl_usdt", 0) > 0 or "WIN" in str(t.get("outcome", "")))
        losses = sum(1 for t in trades if t.get("pnl_usdt", 0) < 0 or "LOSS" in str(t.get("outcome", "")))
        bes = sum(1 for t in trades if t.get("pnl_usdt", 0) == 0 or "BREAKEVEN" in str(t.get("outcome", "")))
        win_rate = (wins / max(wins + losses, 1)) * 100.0

        # Loss clustering by symbol
        symbol_losses = {}
        for t in trades:
            s = t.get("symbol", t.get("coin", "UNKNOWN"))
            if "LOSS" in str(t.get("outcome", "")) or t.get("pnl_usdt", 0) < 0:
                symbol_losses[s] = symbol_losses.get(s, 0) + 1

        underperforming_coins = [s for s, count in symbol_losses.items() if count >= 3]

        try:
            from strategy_auto_optimizer import run_auto_optimization
            tuned = run_auto_optimization(quick_mode=True)
        except Exception as opt_err:
            tuned = {}

        return {
            "status": "success",
            "audit_type": "Algorithmic Quantitative Self-Learning",
            "analysis": {
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "breakevens": bes,
                "win_rate_pct": round(win_rate, 1),
            },
            "loss_clusters": {
                "toxic_underperforming_coins": underperforming_coins
            },
            "newRules": [
                f"Cap maximum stop loss distance to {tuned.get('max_sl_pct', 2.5)}%",
                f"Enforce dynamic ATR buffer multiplier of {tuned.get('atr_sl_multiplier', 0.8)}x ATR(14)",
                f"Enforce min rejection wick ratio of {int(tuned.get('min_wick_ratio', 0.35) * 100)}%"
            ],
            "autoApply": True,
            "tuned_parameters": tuned
        }

    raw_response = call_gemini_with_backoff(user_prompt, system_instruction=system_prompt, model=DEFAULT_MODEL)
    if not raw_response:
        return {}

    try:
        clean_text = raw_response.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()
        return json.loads(clean_text)
    except Exception as parse_err:
        log.warning("Agent 10 response JSON parse error: %s", parse_err)
        return {}


def call_gemini_api(
    prompt: str,
    system_instruction: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.4,
    max_tokens: int = 1024,
    timeout: int = 25
) -> Optional[str]:
    """Conversational / text generation endpoint for Gemini AI."""
    api_key = get_gemini_api_key()
    if not api_key:
        return None

    target_model = model or DEFAULT_MODEL
    url = f"{API_BASE_URL}/{target_model}:generateContent?key={api_key}"

    payload: Dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    headers = {"Content-Type": "application/json"}
    proxies = get_proxy()

    try:
        _throttle()
        res = requests.post(url, json=payload, headers=headers, proxies=proxies, timeout=timeout)
        if res.status_code == 200:
            data = res.json()
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                if parts and "text" in parts[0]:
                    return parts[0]["text"]
        else:
            log.warning("Gemini API call returned status %d: %s", res.status_code, res.text[:200])
    except Exception as e:
        log.warning("Gemini API call failed: %s", e)
    return None

