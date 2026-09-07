"""OpenAI-compatible chat completions client for AI code review."""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, List, Optional

import requests

DEFAULT_MODEL = "gpt-4o"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


class AIClient:
    """Thin wrapper around an OpenAI-compatible chat completions endpoint.

    The base URL may be swapped for any compatible provider (Azure, a proxy, or
    a self-hosted gateway) as long as it exposes ``/chat/completions``.
    """

    def __init__(
        self,
        token: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 120,
        max_retries: int = 3,
    ) -> None:
        self.token = token
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4000,
    ) -> str:
        """Send a chat request and return the assistant's text content.

        Network/timeout errors are retried with exponential backoff; HTTP API
        errors (4xx/5xx) are raised immediately without retrying.
        """
        url = self.base_url
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.post(url, json=payload, timeout=self.timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = min(2 * (2 ** attempt), 16)
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"Network error calling OpenAI API: {exc}") from exc

            # HTTP-level error: include the body and do not retry.
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"OpenAI API error ({resp.status_code}): {resp.text[:500]}"
                )

            # 2xx/3xx but an empty body — usually the base URL path is wrong
            # (many gateways serve /v1/chat/completions, not /chat/completions).
            text = resp.text or ""
            if not text.strip():
                raise RuntimeError(
                    f"OpenAI API returned an empty body (HTTP {resp.status_code}) "
                    f"from {url}. Check OPENAI_API_BASE_URL — it may need a '/v1' path."
                )

            try:
                data = resp.json()
            except ValueError as exc:
                raise RuntimeError(
                    f"OpenAI API returned non-JSON (HTTP {resp.status_code}): {text[:500]}"
                ) from exc

            choices: List[Any] = data.get("choices") or []
            if not choices:
                raise RuntimeError("Invalid response format from OpenAI API")

            message: Dict[str, Any] = choices[0].get("message") or {}
            content: str = message.get("content") or ""

            usage = data.get("usage")
            if usage:
                self._log_usage(usage)

            return content.strip()

        raise RuntimeError(f"Failed to call OpenAI API after retries: {last_error}")

    @staticmethod
    def _log_usage(usage: Dict[str, Any]) -> None:
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        total = usage.get("total_tokens")
        print(
            f"  Tokens: {prompt} prompt + {completion} completion = {total} total",
            file=sys.stderr,
        )
