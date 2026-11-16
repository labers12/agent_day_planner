"""Configuration — loads all settings from environment variables."""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass



def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def check_required_env():
    """Verify all critical environment variables are set."""
    missing = []
    for var in [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_USER_ID",
        "GEMINI_API_KEY",
        "TURSO_DATABASE_URL",
        "TURSO_AUTH_TOKEN",
    ]:
        if not os.environ.get(var):
            missing.append(var)
    if missing:
        raise RuntimeError(
            f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}.\n"
            f"Проверь .env или GitHub Repository Secrets."
        )


# ── Telegram ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = _get("TELEGRAM_BOT_TOKEN", "").strip()
try:
    TELEGRAM_USER_ID: int = int(_get("TELEGRAM_USER_ID", "0").strip())
except ValueError:
    TELEGRAM_USER_ID = 0

# ── Google Gemini AI ──────────────────────────────────────
GEMINI_API_KEY: str = _get("GEMINI_API_KEY", "")
GEMINI_MODEL: str = _get("GEMINI_MODEL", "gemini-2.0-flash")

# ── Turso Database ────────────────────────────────────────
TURSO_DATABASE_URL: str = _get("TURSO_DATABASE_URL", "local.db")
TURSO_AUTH_TOKEN: str = _get("TURSO_AUTH_TOKEN", "")

# ── Application Settings ─────────────────────────────────
TIMEZONE = "Asia/Tomsk"
TOMSK_UTC_OFFSET = 7
TSU_GROUP = "932604"

# Max Gemini API calls per polling cycle (budget guard)
MAX_LLM_CALLS_PER_CYCLE: int = int(_get("MAX_LLM_CALLS_PER_CYCLE", "10"))

