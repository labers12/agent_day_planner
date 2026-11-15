"""Base agent — thin wrapper around Google Gemini (google-genai SDK)."""

from __future__ import annotations

import json
import logging
import re
import time

from src.config import GEMINI_API_KEY, GEMINI_MODEL

log = logging.getLogger(__name__)

_client = None


def get_gemini_client():
    """Lazily initialize Google Gemini client."""
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY не задан в .env или GitHub Secrets!")
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client



def parse_json_response(text: str) -> dict | list:
    """Strip optional ```json fences and parse JSON."""
    cleaned = text.strip()
    # Remove markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    cleaned = cleaned.strip()
    return json.loads(cleaned)


class BaseAgent:
    """Base class for all AI agents."""

    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt

    def ask(self, user_prompt: str, expect_json: bool = False) -> str | dict | list:
        """Send prompt to Gemini and return the response.

        If *expect_json* is True, the response is parsed as JSON.
        Retries once on transient errors.
        """
        client = get_gemini_client()
        contents = f"{self.system_prompt}\n\n---\n\n{user_prompt}"

        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=contents,
                )
                text = response.text.strip()

                if expect_json:
                    return parse_json_response(text)
                return text

            except Exception as e:
                log.warning("Gemini call attempt %d failed: %s", attempt + 1, e)
                if attempt == 0:
                    time.sleep(2)
                else:
                    raise

    async def ask_async(self, user_prompt: str, expect_json: bool = False) -> str | dict | list:
        """Async wrapper — delegates to sync ask() (Gemini SDK is sync)."""
        return self.ask(user_prompt, expect_json=expect_json)

