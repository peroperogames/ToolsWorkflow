"""OpenAI-compatible chat completions client for AI code review."""

from __future__ import annotations

import os
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
        timeout: int = 180,
        max_retries: int = 5,
        fallback_model: Optional[str] = None,
    ) -> None:
        self.token = token
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = int(os.environ.get("OPENAI_TIMEOUT", timeout))
        self.max_retries = int(os.environ.get("OPENAI_MAX_RETRIES", max_retries))
        self.fallback_model = (
            fallback_model or os.environ.get("OPENAI_API_MODEL_FALLBACK", "")
        ).strip()
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
        max_tokens: Optional[int] = None,
    ) -> str:
        """Send a chat request and return the assistant's text content.

        Tries the primary model first; if it fails (timeout, 429, 5xx, or any
        other error) and a fallback model is configured, retries with that.
        """
        models = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            models.append(self.fallback_model)

        last_error: Optional[Exception] = None
        for index, model in enumerate(models):
            try:
                return self._chat_with_model(model, messages, temperature, max_tokens)
            except RuntimeError as exc:
                last_error = exc
                if index + 1 < len(models):
                    print(
                        f"  Model '{model}' failed ({exc}); "
                        f"falling back to '{models[index + 1]}'...",
                        file=sys.stderr,
                    )
                    continue
                raise

        raise last_error or RuntimeError("No model configured")

    def _chat_with_model(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: Optional[int],
    ) -> str:
        """Run the request/retry loop for a single model."""
        url = self.base_url
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.post(url, json=payload, timeout=self.timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                # With a fallback model configured, fail over quickly instead
                # of burning many retries on a slow/hanging primary model.
                limit = 1 if self.fallback_model else self.max_retries
                if attempt < limit:
                    delay = min(2 * (2 ** attempt), 16)
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"Network error calling OpenAI API: {exc}") from exc

            # Rate limit (429) and transient server errors (5xx): retry with
            # backoff. TPM windows reset every minute, so wait longer for 429.
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = RuntimeError(
                    f"OpenAI API error ({resp.status_code}): {resp.text[:200]}"
                )
                if attempt < self.max_retries:
                    delay = min(30 * (2 ** attempt), 120)
                    print(
                        f"  Transient OpenAI error ({resp.status_code}), "
                        f"retrying in {delay}s ({attempt + 1}/{self.max_retries + 1})...",
                        file=sys.stderr,
                    )
                    time.sleep(delay)
                    continue
                raise last_error

            # Other HTTP errors (4xx): no retry.
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
            # DeepSeek / reasoning models may put the actual output in
            # reasoning_content when content is empty.
            if not content:
                content = message.get("reasoning_content") or ""

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
