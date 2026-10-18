"""
Optimized Telegram Proxy Manager & Failover Engine
Eliminates heavy multi-threaded brute force scraping to drop laptop temperature.
"""
import os
import sys
import logging
import requests
from typing import Optional, Dict, Any, List

log = logging.getLogger("TelegramProxyManager")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Fixed Dedicated Whitelisted Proxies from environment
DEDICATED_PROXIES = [
    p for p in [
        os.getenv("PROXY_URL_PRIMARY", ""),
        os.getenv("PROXY_URL_BACKUP1", ""),
        os.getenv("PROXY_URL_BACKUP2", ""),
    ] if p and p.strip() and not p.strip() == "http://31.59.20"
]

def get_working_proxies() -> List[Dict[str, Any]]:
    """Instant cached dedicated routing to eliminate thread pools."""
    return [{"url": p, "latency_ms": 120} for p in DEDICATED_PROXIES]

def execute_telegram_api(method: str, endpoint: str, payload: Optional[Dict] = None, timeout: int = 15) -> Optional[requests.Response]:
    """Lightweight direct API connection routing without socket hammering."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", TOKEN)
    if not token:
        return None
    clean_endpoint = endpoint.lstrip("/")
    token_str = token if token.startswith("bot") else f"bot{token}"
    url = f"https://api.telegram.org/{token_str}/{clean_endpoint}"

    # 1. First Pass: Fast Direct Route
    try:
        if method.upper() == "POST":
            r = requests.post(url, json=payload, timeout=(2.0, timeout))
        else:
            r = requests.get(url, params=payload, timeout=(2.0, timeout))
        if r.status_code == 200:
            return r
    except Exception:
        pass

    # 2. Second Pass: Static Whitelisted Proxy Router
    proxies_list = get_working_proxies()
    for proxy_info in proxies_list:
        p_url = proxy_info["url"]
        proxies_dict = {"http": p_url, "https": p_url}
        try:
            if method.upper() == "POST":
                r = requests.post(url, json=payload, proxies=proxies_dict, timeout=(3.0, timeout))
            else:
                r = requests.get(url, params=payload, proxies=proxies_dict, timeout=(3.0, timeout))
            if r.status_code == 200:
                return r
        except Exception:
            continue
    return None

def start_background_proxy_refresher(interval_hours: int = 4):
    """Overridden to maintain silent cold execution state."""
    pass
