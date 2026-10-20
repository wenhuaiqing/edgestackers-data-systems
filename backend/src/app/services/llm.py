"""OpenAI-protocol chat client for the triage agent (Gemini in the live deploy).

Degrades in a fixed order: the primary model, one short retry on a 429 when
the provider asks for a wait we can afford, then the fallback model on a 5xx
or a long rate limit. A timeout is not retried - the budget is spent. When
everything fails the caller falls back to the rules triager and says so on
screen; nothing degrades silently.

The client is synchronous; the router runs it in a worker thread so a slow
provider never stalls the pages.
"""

from __future__ import annotations

import logging
import re
import time
from functools import lru_cache
from typing import Any, Callable

from src.settings import settings

log = logging.getLogger(__name__)

_MAX_WAIT = 4.0


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI
    # max_retries=0: the SDK's own backoff can outlast the whole budget.
    return OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key.strip(),
                  timeout=settings.llm_timeout_seconds, max_retries=0)


def configured() -> bool:
    # Terraform stores an unset key as a single space (Key Vault refuses empty).
    return bool(settings.llm_base_url and settings.llm_api_key.strip())


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            header = response.headers.get("retry-after")
            if header:
                return float(header)
        except Exception:  # noqa: BLE001
            pass
    match = re.search(r"'retryDelay': '(\d+(?:\.\d+)?)s'", str(exc))
    return float(match.group(1)) if match else None


def call(fn: Callable[[str, Any], Any]) -> tuple[Any, str]:
    """Run fn(model, client); return (result, model actually used)."""
    from openai import APIStatusError, APITimeoutError, RateLimitError

    primary = settings.llm_chat_model
    fallback = settings.llm_fallback_model if settings.llm_fallback_model != primary else ""
    try:
        return fn(primary, _client()), primary
    except RateLimitError as exc:
        wait = _retry_after(exc)
        if (wait or 0) <= _MAX_WAIT:
            time.sleep(wait if wait is not None else 1.5)
            try:
                return fn(primary, _client()), primary
            except (RateLimitError, APIStatusError) as again:
                last: Exception = again
        else:
            last = exc
    except APITimeoutError:
        raise
    except APIStatusError as exc:
        if getattr(exc, "status_code", 500) < 500:
            raise
        last = exc
    if not fallback:
        raise last
    log.warning("%s unavailable (%s); trying %s", primary, type(last).__name__, fallback)
    return fn(fallback, _client()), fallback
