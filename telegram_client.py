"""Minimal Telegram Bot API client — just enough to send a message."""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)


class TelegramClient:
    def __init__(self, token: str, chat_id: str, session: requests.Session | None = None):
        self.token = token
        self.chat_id = chat_id
        self.session = session or requests.Session()
        self.base = f"https://api.telegram.org/bot{token}"

    def send_message(self, text: str, *, parse_mode: str = "HTML", disable_preview: bool = False) -> bool:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview,
        }
        resp = self.session.post(f"{self.base}/sendMessage", json=payload, timeout=20)
        if not resp.ok:
            log.error("Telegram sendMessage failed (%s): %s", resp.status_code, resp.text)
            return False
        return True
