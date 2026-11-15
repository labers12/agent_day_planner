"""Telegram Bot API — thin async wrapper (httpx, polling mode)."""

from __future__ import annotations

import logging
try:
    import httpx
    _TIMEOUT = httpx.Timeout(40.0, connect=10.0)
except ImportError:
    httpx = None
    _TIMEOUT = None

from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_USER_ID

log = logging.getLogger(__name__)

API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"



# ── Sending ───────────────────────────────────────────────

async def send_message(
    text: str,
    parse_mode: str = "Markdown",
    reply_markup: dict | None = None,
    chat_id: int | None = None,
) -> dict:
    """Send a text message to the authorized user. Auto-splits long texts."""
    cid = chat_id or TELEGRAM_USER_ID
    chunks = _split_text(text, 4096)
    result = {}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        for chunk in chunks:
            payload: dict = {"chat_id": cid, "text": chunk}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            # Attach keyboard only to the last chunk
            if reply_markup and chunk is chunks[-1]:
                payload["reply_markup"] = reply_markup
            resp = await c.post(f"{API}/sendMessage", json=payload)
            result = resp.json()
            if not result.get("ok"):
                # Retry without parse_mode (Markdown can fail on special chars)
                payload.pop("parse_mode", None)
                resp = await c.post(f"{API}/sendMessage", json=payload)
                result = resp.json()
            log.debug("sendMessage ok=%s", result.get("ok"))
    return result


async def send_inline_keyboard(text: str, buttons: list[list[dict]]) -> dict:
    """Send a message with an inline keyboard.

    buttons example: [[{"text": "OK", "callback_data": "ok"}]]
    """
    markup = {"inline_keyboard": buttons}
    return await send_message(text, reply_markup=markup)


# ── Receiving ─────────────────────────────────────────────

async def get_updates(offset: int = 0, timeout: int = 5) -> list[dict]:
    """Long-poll Telegram for new updates."""
    params = {"timeout": timeout, "allowed_updates": '["message","callback_query"]'}
    if offset:
        params["offset"] = offset
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        resp = await c.get(f"{API}/getUpdates", params=params)
        data = resp.json()
    if not data.get("ok"):
        log.error("getUpdates error: %s", data)
        return []
    return data.get("result", [])


async def answer_callback_query(callback_query_id: str, text: str = "") -> dict:
    """Acknowledge an inline-keyboard button press."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        resp = await c.post(f"{API}/answerCallbackQuery", json=payload)
        return resp.json()


# ── Helpers ───────────────────────────────────────────────

def is_authorized(update: dict) -> bool:
    """Return True only if the update came from the owner."""
    uid = None
    if "message" in update:
        uid = update["message"].get("from", {}).get("id")
    elif "callback_query" in update:
        uid = update["callback_query"].get("from", {}).get("id")
    return uid == TELEGRAM_USER_ID


def extract_message_text(update: dict) -> str | None:
    """Pull plain text from a message update."""
    msg = update.get("message")
    if msg:
        return msg.get("text")
    return None


def extract_callback_data(update: dict) -> str | None:
    """Pull callback_data from a callback_query update."""
    cq = update.get("callback_query")
    if cq:
        return cq.get("data")
    return None


def get_callback_query_id(update: dict) -> str | None:
    cq = update.get("callback_query")
    if cq:
        return str(cq.get("id"))
    return None


def _split_text(text: str, limit: int) -> list[str]:
    """Split text into chunks ≤ limit characters, breaking at newlines."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to break at newline
        idx = text.rfind("\n", 0, limit)
        if idx == -1:
            idx = limit
        chunks.append(text[:idx])
        text = text[idx:].lstrip("\n")
    return chunks
