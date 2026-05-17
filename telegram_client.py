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

    def send_message(self, text: str, *, parse_mode: str = "HTML", disable_preview: bool = False, chat_id: str | int | None = None) -> bool:
        payload = {
            "chat_id": chat_id if chat_id is not None else self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview,
        }
        resp = self.session.post(f"{self.base}/sendMessage", json=payload, timeout=20)
        if not resp.ok:
            log.error("Telegram sendMessage failed (%s): %s", resp.status_code, resp.text)
            return False
        return True

    def get_updates(self, offset: int | None = None, timeout: int = 0, allowed_updates: list[str] | None = None) -> list[dict]:
        """Long-poll for new updates. Returns the list of update dicts."""
        params: dict = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        if allowed_updates is not None:
            import json
            params["allowed_updates"] = json.dumps(allowed_updates)
        # HTTP timeout must exceed the long-poll timeout.
        resp = self.session.get(f"{self.base}/getUpdates", params=params, timeout=timeout + 10)
        if not resp.ok:
            log.error("Telegram getUpdates failed (%s): %s", resp.status_code, resp.text)
            return []
        body = resp.json()
        if not body.get("ok"):
            log.error("Telegram getUpdates not ok: %s", body)
            return []
        return body.get("result", [])

    def set_my_commands(self, commands: list[tuple[str, str]]) -> bool:
        """Register the slash-command list shown in Telegram's UI."""
        import json
        payload = {
            "commands": json.dumps([{"command": c, "description": d} for c, d in commands]),
        }
        resp = self.session.post(f"{self.base}/setMyCommands", data=payload, timeout=20)
        return resp.ok
