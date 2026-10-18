"""
Proxy Manager Service for tradingview-mcp.

Reads Webshare proxy credentials from ENVIRONMENT VARIABLES only.
Never hardcode credentials in this file.

Setup:
    export PROXY_HOST=p.webshare.io
    export PROXY_PORT=80
    export PROXY_USERNAME_PREFIX=hvfvdamo   # your username prefix
    export PROXY_PASSWORD=your_password_here

Or create a .env file (see .env.example) — never commit .env to git.

Usage:
    from tradingview_mcp.core.services.proxy_manager import get_proxy, build_opener_with_proxy

    proxies = get_proxy()                    # for requests library
    opener  = build_opener_with_proxy()      # for urllib
"""
from __future__ import annotations

import os
import random
import urllib.request
from typing import Optional

# Try loading .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    repo_env = os.path.join(os.path.dirname(__file__), ".env")
    cwd_env = os.path.join(os.getcwd(), ".env")
    if os.path.isfile(repo_env):
        load_dotenv(dotenv_path=repo_env, override=True)
    elif os.path.isfile(cwd_env):
        load_dotenv(dotenv_path=cwd_env, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    pass


# ─── Read config from env ─────────────────────────────────────────────────────

# ============================================================================
# PERMANENT HARDWIRED PROXIES — These are ALWAYS used as fallback.
# WiFi/ISP change karo — in proxies ka IP hamesha FIXED rahega.
# Binance whitelist mein yeh 3 IPs add hain:
#   45.38.107.97  (PRIMARY)
#   31.59.20.176  (BACKUP 1)
#   198.105.121.200 (BACKUP 2)
# ============================================================================
_WEBSHARE_FALLBACK_PROXIES = [
    p for p in [
        os.getenv("PROXY_URL_PRIMARY", ""),
        os.getenv("PROXY_URL_BACKUP1", ""),
        os.getenv("PROXY_URL_BACKUP2", ""),
    ] if p
]


def _cfg() -> dict:
    return {
        "host":     os.environ.get("PROXY_HOST", ""),
        "port":     os.environ.get("PROXY_PORT", ""),
        "prefix":   os.environ.get("PROXY_USERNAME_PREFIX", ""),
        "username": os.environ.get("PROXY_USERNAME", ""),
        "password": os.environ.get("PROXY_PASSWORD", ""),
        "enabled":  os.environ.get("PROXY_ENABLED", "false").lower() == "true",
        "is_static": os.environ.get("PROXY_IS_STATIC", "true").lower() == "true",
        "min":      int(os.environ.get("PROXY_SESSION_MIN", "1")),
        "max":      int(os.environ.get("PROXY_SESSION_MAX", "250")),
        "static_url": os.environ.get("STATIC_PROXY_URL", ""),
    }


def is_proxy_configured() -> bool:
    """Returns True only if all required env vars are set."""
    c = _cfg()
    if not c["enabled"]:
        return False
    if c["static_url"]:
        return True
    user = c["username"] or c["prefix"]
    return bool(user) and bool(c["password"])


def get_proxy_url() -> Optional[str]:
    """Build a proxy URL (Static Dedicated Proxy or Rotating Sticky Session). Returns None if not configured."""
    if not is_proxy_configured():
        return None
    c = _cfg()
    if c["static_url"]:
        return c["static_url"]

    user = c["username"] or c["prefix"]
    if c["is_static"] or not c["prefix"]:
        # Dedicated Static Proxy (No random session rotation)
        return f"http://{user}:{c['password']}@{c['host']}:{c['port']}"
    else:
        # Rotating sticky session proxy
        session_id = random.randint(c["min"], c["max"])
        return f"http://{user}-{session_id}:{c['password']}@{c['host']}:{c['port']}"


def get_working_proxy_url() -> Optional[str]:
    """
    Returns a working proxy URL if proxy is enabled and configured.
    If PROXY_ENABLED=false in .env, returns None immediately (direct connection).
    """
    c = _cfg()
    # ── Fast path: proxy disabled in .env ─────────────────────────────────────
    if not c["enabled"]:
        return None  # Direct connection — no proxy needed

    import requests as _req
    # Try .env primary proxy first, then hardwired fallbacks
    primary = get_proxy_url() if is_proxy_configured() else None
    candidates = ([primary] if primary else []) + _WEBSHARE_FALLBACK_PROXIES
    seen = []
    for url in candidates:
        if not url or url in seen:
            continue
        seen.append(url)
        try:
            r = _req.get(
                "https://api.binance.com/api/v3/ping",
                proxies={"http": url, "https": url},
                timeout=5,
            )
            if r.status_code == 200:
                return url
        except Exception:
            continue
    # If all proxies fail, fall back to direct connection
    return None


def get_hardwired_proxy() -> dict:
    """
    Returns proxy dict for Binance API calls.
    If PROXY_ENABLED=false, returns empty dict (direct connection).
    """
    url = get_working_proxy_url()
    if not url:
        return {}  # Empty dict = direct connection (no proxy)
    return {"http": url, "https": url}


def get_proxy() -> Optional[dict]:
    """
    Return proxy dict for the `requests` library.
    Returns None if PROXY_ENABLED=false (direct connection used).
    """
    url = get_working_proxy_url()
    if not url:
        return None
    return {"http": url, "https": url}


def build_opener_with_proxy(
    user_agent: str = "tradingview-mcp/0.5.0",
) -> urllib.request.OpenerDirector:
    """
    Build a urllib OpenerDirector with proxy if configured, plain opener otherwise.
    Services degrade gracefully when no proxy is set — no crashes.
    """
    opener = urllib.request.build_opener()
    opener.addheaders = [("User-Agent", user_agent)]

    if not is_proxy_configured():
        return opener

    proxy_url = get_proxy_url()
    c = _cfg()
    # Extract username from the full url for auth handler
    username = proxy_url.split("//")[1].split(":")[0]

    proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    pwd_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pwd_mgr.add_password(None, f"http://{c['host']}:{c['port']}", username, c["password"])
    auth_handler = urllib.request.ProxyBasicAuthHandler(pwd_mgr)

    opener = urllib.request.build_opener(proxy_handler, auth_handler)
    opener.addheaders = [("User-Agent", user_agent)]
    return opener


def check_proxy() -> dict:
    """Test proxy connectivity. Returns current exit IP, country, city."""
    import json

    status: dict = {
        "configured": is_proxy_configured(),
        "ok": False,
        "ip": None, "country": None, "city": None, "error": None,
    }

    if not is_proxy_configured():
        status["error"] = (
            "Proxy not configured. Set PROXY_HOST, PROXY_USERNAME_PREFIX, "
            "PROXY_PASSWORD in your environment or .env file."
        )
        return status

    try:
        proxy_url = get_proxy_url()
        handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener  = urllib.request.build_opener(handler)
        opener.addheaders = [("User-Agent", "tradingview-mcp/0.5.0")]
        req = urllib.request.Request("https://ipinfo.io/json")
        with opener.open(req, timeout=12) as resp:
            data = json.loads(resp.read())
        status.update(ip=data.get("ip"), country=data.get("country"),
                      city=data.get("city"), ok=True)
    except Exception as e:
        status["error"] = str(e)

    return status
