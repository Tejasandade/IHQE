import logging
import asyncio
import requests
import time
from typing import Dict

from config.settings import TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

class TelegramBot:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance
        
    def _init(self):
        self.enabled = TELEGRAM_ENABLED
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.last_sent: Dict[str, float] = {}
        self.url = f"https://api.telegram.org/bot{self.token}/sendMessage" if self.token else ""
        
        if self.enabled and (not self.token or not self.chat_id):
            logger.warning("Telegram is enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing. Alerts will not be sent.")
            
    def _send_sync(self, message: str) -> None:
        if not self.enabled:
            logger.info(f"[TELEGRAM (Disabled)] {message}")
            return
            
        if not self.token or not self.chat_id:
            logger.error("Failed to send Telegram alert: Missing credentials")
            return
            
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                # We do not use parse_mode="HTML" because the messages might contain unescaped chars like > or <
            }
            response = requests.post(self.url, json=payload, timeout=5.0)
            response.raise_for_status()
            logger.debug(f"Sent Telegram alert: {message}")
        except Exception as e:
            logger.error(f"Error sending Telegram alert: {e}")

    def send_alert(self, event_type: str, message: str) -> None:
        """
        Sends an alert asynchronously, subject to rate limits.
        event_type is used as a rate-limiting key.
        """
        now = time.time()
        last = self.last_sent.get(event_type, 0)
        
        if now - last < 60:
            logger.debug(f"Telegram alert '{event_type}' rate-limited. (Skipped)")
            return
            
        self.last_sent[event_type] = now
        
        # Fire and forget in a background thread so it never blocks the caller
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, self._send_sync, message)
        except RuntimeError:
            import threading
            threading.Thread(target=self._send_sync, args=(message,), daemon=True).start()

telegram_bot = TelegramBot()

def send_telegram_alert(event_type: str, message: str) -> None:
    telegram_bot.send_alert(event_type, message)
