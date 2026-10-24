from __future__ import annotations

import asyncio
import logging

from openai import OpenAI

from app.config import NEBIUS_API_KEY, NEBIUS_BASE_URL, NEBIUS_MODEL

logger = logging.getLogger(__name__)


class NebiusClient:
    def __init__(self) -> None:
        self.client = OpenAI(api_key=NEBIUS_API_KEY, base_url=NEBIUS_BASE_URL)

    async def respond(self, system: str, user: str) -> str:
        def call() -> str:
            response = self.client.chat.completions.create(
                model=NEBIUS_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.3,
                max_tokens=700,
            )
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("Nebius returned an empty response.")
            return content

        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                return await asyncio.to_thread(call)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Nebius request failed (attempt %d/2, model=%s, error_type=%s)",
                    attempt,
                    NEBIUS_MODEL,
                    type(exc).__name__,
                )
                if attempt < 2:
                    await asyncio.sleep(0.75)
        raise RuntimeError(
            "The Nebius model request failed after two attempts. "
            "Check the server logs and API configuration."
        ) from last_error
