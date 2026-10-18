"""
ENHANCED TELEGRAM WRAPPER: Reliability & Fallback
Fixes missing Telegram reliability issues in current bot

Features:
- Retry logic with exponential backoff
- Direct webhook fallback
- Message queue for offline periods
- Compression for large messages
- Multiple channel support
- Alert severity levels
"""

import asyncio
import aiohttp
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import deque
import os

logger = logging.getLogger(__name__)

class TelegramReliabilityWrapper:
    """
    Enhanced Telegram integration with multiple fallbacks and reliability features.
    """
    
    def __init__(self, bot_token: str, chat_id: str, webhook_url: Optional[str] = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.webhook_url = webhook_url
        self.telegram_api = f"https://api.telegram.org/bot{bot_token}"
        
        # Message queue for offline periods
        self.message_queue: deque = deque(maxlen=100)
        self.is_connected = True
        self.retry_count = 0
        self.max_retries = 3
        
        # Channel management
        self.channels = {
            "signals": chat_id,
            "alerts": chat_id,
            "errors": chat_id,
            "status": chat_id
        }
        
        # Alert rate limiting (don't spam)
        self.last_alert_time = {}
        self.alert_cooldown_seconds = 60
    
    async def send_signal(self, signal_data: Dict[str, Any], channel: str = "signals") -> bool:
        """
        Send trade signal with formatting.
        """
        
        message = self._format_signal_message(signal_data)
        
        return await self.send_message(
            message,
            parse_mode="HTML",
            channel=channel
        )
    
    async def send_alert(self, alert_text: str, severity: str = "INFO", 
                        channel: str = "alerts") -> bool:
        """
        Send alert with severity level and rate limiting.
        """
        
        # Rate limiting
        if not self._check_rate_limit(f"alert_{severity}"):
            logger.warning(f"Alert rate limited: {alert_text}")
            return False
        
        emoji_map = {
            "CRITICAL": "🚨",
            "WARNING": "⚠️",
            "INFO": "ℹ️",
            "SUCCESS": "✅"
        }
        
        emoji = emoji_map.get(severity, "ℹ️")
        formatted = f"{emoji} <b>[{severity}]</b>\n{alert_text}"
        
        return await self.send_message(
            formatted,
            parse_mode="HTML",
            channel=channel
        )
    
    async def send_message(self, text: str, parse_mode: str = "HTML", 
                          channel: str = "signals", use_fallback: bool = True) -> bool:
        """
        Send message with reliability features.
        """
        
        chat_id = self.channels.get(channel, self.chat_id)
        
        # Queue message for offline periods
        self.message_queue.append({
            "text": text,
            "parse_mode": parse_mode,
            "channel": channel,
            "timestamp": datetime.now().isoformat()
        })
        
        # Try sending
        try:
            success = await self._send_via_telegram(text, parse_mode, chat_id)
            
            if success:
                self.is_connected = True
                self.retry_count = 0
                return True
            
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
        
        # Fallback to webhook if Telegram fails
        if use_fallback and self.webhook_url:
            try:
                success = await self._send_via_webhook(text, parse_mode)
                if success:
                    logger.info("Message sent via webhook fallback")
                    return True
            except Exception as e:
                logger.error(f"Webhook fallback failed: {e}")
        
        # Mark as disconnected
        self.is_connected = False
        self.retry_count += 1
        
        return False
    
    async def _send_via_telegram(self, text: str, parse_mode: str, chat_id: str) -> bool:
        """
        Send message via Telegram API with retry logic.
        """
        
        # Compress large messages
        if len(text) > 4096:
            text = text[:4090] + "..."
        
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.telegram_api}/sendMessage",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        
                        if response.status == 200:
                            logger.debug(f"Telegram message sent successfully")
                            return True
                        
                        elif response.status == 429:  # Rate limited
                            retry_after = int(response.headers.get('Retry-After', 5))
                            await asyncio.sleep(retry_after)
                            continue
                        
                        elif response.status >= 500:  # Server error
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff
                            continue
                        
                        else:
                            error_text = await response.text()
                            logger.error(f"Telegram API error: {response.status} - {error_text}")
                            return False
            
            except asyncio.TimeoutError:
                logger.warning(f"Telegram timeout (attempt {attempt + 1}/{self.max_retries})")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
            
            except Exception as e:
                logger.error(f"Telegram connection error: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
    def send_message_sync(self, text: str, parse_mode: str = "HTML", channel: str = "signals") -> bool:
        """
        Synchronous proxy-aware sender with auto-failover and queue backup.
        """
        chat_id = self.channels.get(channel, self.chat_id)
        if not self.bot_token or not chat_id:
            logger.info(f"[SIMULATED TG]: {text[:80]}...")
            return True

        if len(text) > 4096:
            text = text[:4090] + "..."

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }

        # 1. Try via Telegram Proxy Manager if available
        try:
            from telegram_proxy_manager import execute_telegram_api
            r = execute_telegram_api("POST", "sendMessage", payload=payload, timeout=12)
            if r is not None and r.status_code == 200:
                self.is_connected = True
                return True
        except Exception as e:
            logger.warning(f"Telegram proxy manager fallback attempt: {e}")

        # 2. Try direct requests with retry
        import requests
        for attempt in range(self.max_retries):
            try:
                r = requests.post(f"{self.telegram_api}/sendMessage", json=payload, timeout=10)
                if r.status_code == 200:
                    self.is_connected = True
                    return True
            except Exception as ex:
                logger.warning(f"Direct TG send attempt {attempt+1} failed: {ex}")

        # 3. Try webhook fallback if configured
        if self.webhook_url:
            try:
                r = requests.post(self.webhook_url, json={"text": text, "parse_mode": parse_mode}, timeout=8)
                if r.status_code == 200:
                    return True
            except Exception:
                pass

        self.is_connected = False
        return False

    async def send_position_update(self, position_data: Dict[str, Any]) -> bool:
        """
        Send position update (entry/TP hit/SL hit).
        """
        
        status = position_data.get("status", "UNKNOWN")
        
        if status == "ENTRY":
            emoji = "📍"
            title = "Position Opened"
        elif status == "TP1":
            emoji = "💰"
            title = "TP1 Locked"
        elif status == "TP2":
            emoji = "💰💰"
            title = "TP2 Locked"
        elif status == "SL_HIT":
            emoji = "❌"
            title = "Stop Loss Hit"
        else:
            emoji = "❓"
            title = "Position Update"
        
        message = f"""
{emoji} <b>{title}</b>

<b>Pair:</b> {position_data.get('pair', 'N/A')}
<b>Entry:</b> ${position_data.get('entry_price', 0):.8f}
<b>Current:</b> ${position_data.get('current_price', 0):.8f}
<b>P&L:</b> <code>${position_data.get('pnl', 0):.4f}</code>
<b>P&L %:</b> <code>{position_data.get('pnl_percent', 0):.2f}%</code>

<i>{datetime.now().strftime('%H:%M:%S UTC')}</i>
        """
        
        return await self.send_message(
            message.strip(),
            channel="signals"
        )
    
    async def send_summary(self, summary_data: Dict[str, Any]) -> bool:
        """
        Send daily/weekly summary.
        """
        
        message = f"""
📊 <b>Daily Summary</b>

<b>Portfolio:</b> ${summary_data.get('portfolio_value', 0):.2f}
<b>Today's P&L:</b> ${summary_data.get('daily_pnl', 0):.2f} ({summary_data.get('daily_pnl_percent', 0):.2f}%)
<b>Month P&L:</b> ${summary_data.get('monthly_pnl', 0):.2f} ({summary_data.get('monthly_pnl_percent', 0):.2f}%)

<b>Trades:</b> {summary_data.get('trades_today', 0)} ({summary_data.get('win_rate', 0):.1f}% win)
<b>Active Positions:</b> {summary_data.get('active_positions', 0)}
<b>Margin Used:</b> {summary_data.get('margin_used', 0):.1f}%

<b>Status:</b> {'✅ Running' if summary_data.get('bot_running', False) else '❌ Offline'}
        """
        
        return await self.send_message(
            message.strip(),
            channel="status"
        )
    
    async def flush_queue(self) -> int:
        """
        Send all queued messages when reconnected.
        """
        
        sent_count = 0
        
        while self.message_queue and self.is_connected:
            try:
                msg = self.message_queue.popleft()
                
                success = await self.send_message(
                    msg['text'],
                    parse_mode=msg.get('parse_mode', 'HTML'),
                    channel=msg.get('channel', 'signals'),
                    use_fallback=False
                )
                
                if success:
                    sent_count += 1
                else:
                    # Put back in queue if failed
                    self.message_queue.appendleft(msg)
                    break
                
                await asyncio.sleep(0.5)  # Prevent rate limiting
            
            except Exception as e:
                logger.error(f"Error flushing queue: {e}")
                break
        
        return sent_count
    
    def _format_signal_message(self, signal_data: Dict[str, Any]) -> str:
        """Format signal data into readable Telegram message."""
        
        symbol = signal_data.get('symbol', 'UNKNOWN')
        signal = signal_data.get('signal', 'NEUTRAL')
        confidence = signal_data.get('confidence', 0)
        
        signal_emoji = {
            'BUY': '🟢',
            'SELL': '🔴',
            'NEUTRAL': '⚪'
        }.get(signal, '❓')
        
        message = f"""
{signal_emoji} <b>{signal} Signal - {symbol}</b>

<b>Entry:</b> ${signal_data.get('entry_price', 0):.8f}
<b>Stop Loss:</b> ${signal_data.get('stop_loss', 0):.8f}
<b>TP1:</b> ${signal_data.get('tp1', 0):.8f}
<b>TP2:</b> ${signal_data.get('tp2', 0):.8f}

<b>Risk/Reward:</b> {signal_data.get('rrr', 0):.2f}:1
<b>Confluence:</b> {confidence}/100
<b>Confidence:</b> {'🟢 High' if confidence > 80 else '🟡 Medium' if confidence > 60 else '🔴 Low'}

<i>{datetime.now().strftime('%H:%M:%S UTC')}</i>
        """
        
        return message.strip()
    
    def _check_rate_limit(self, alert_type: str) -> bool:
        """Check if alert type is rate limited."""
        
        now = datetime.now()
        last_time = self.last_alert_time.get(alert_type)
        
        if not last_time:
            self.last_alert_time[alert_type] = now
            return True
        
        time_since = (now - last_time).total_seconds()
        
        if time_since >= self.alert_cooldown_seconds:
            self.last_alert_time[alert_type] = now
            return True
        
        return False
    
    async def test_connection(self) -> bool:
        """Test Telegram connection."""
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.telegram_api}/getMe",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"Telegram bot connected: {data['result']['username']}")
                        self.is_connected = True
                        return True
                    else:
                        logger.error(f"Telegram connection failed: {response.status}")
                        self.is_connected = False
                        return False
        
        except Exception as e:
            logger.error(f"Telegram test failed: {e}")
            self.is_connected = False
            return False
    
    async def send_status_check(self) -> bool:
        """Periodic status check message."""
        
        bot_status = await self.test_connection()
        
        message = f"""
✅ <b>Bot Health Check</b>

<b>Telegram Status:</b> {'🟢 Connected' if bot_status else '🔴 Disconnected'}
<b>Queue Size:</b> {len(self.message_queue)} messages
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}

<i>Automated health check</i>
        """
        
        return await self.send_message(
            message.strip(),
            channel="status",
            use_fallback=True
        )


"""
USAGE EXAMPLE:

wrapper = TelegramReliabilityWrapper(
    bot_token="YOUR_TOKEN",
    chat_id="YOUR_CHAT_ID",
    webhook_url="https://your-webhook.com/telegram"
)

# Send signal
await wrapper.send_signal({
    'symbol': 'BTCUSDT',
    'entry_price': 45000,
    'stop_loss': 44500,
    'tp1': 46000,
    'tp2': 47000,
    'rrr': 2.5,
    'confidence': 87
})

# Send alert
await wrapper.send_alert(
    "Daily loss limit approaching",
    severity="WARNING"
)

# Flush queued messages
sent = await wrapper.flush_queue()
"""
