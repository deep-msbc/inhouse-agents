"""
Retry utilities (async).

Built on top of tenacity. All LLM calls and external API calls use
async_retry() to handle transient network/rate-limit failures uniformly.

Install: pip install tenacity
"""

import asyncio
import logging
from typing import Any, Callable, Set, Type

logger = logging.getLogger(__name__)


async def async_retry(
    func: Callable,
    *args: Any,
    exception_types: tuple[Type[Exception], ...] = (Exception,),
    retryable_status_codes: Set[int] | None = None,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> Any:
    """
    Retry an async callable with exponential back-off.

    Args:
        func:                  Async function to call.
        *args:                 Positional arguments forwarded to func.
        exception_types:       Exception types that trigger a retry.
        retryable_status_codes: HTTP status codes to treat as retryable
                               (inspected on exceptions that carry a
                               .response.status_code attribute).
        max_attempts:          Total attempts including the first (default 3).
        base_delay:            Seconds before first retry; doubles each time.
        **kwargs:              Keyword arguments forwarded to func.

    Returns:
        The return value of func on success.

    Raises:
        The last exception if all attempts are exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await func(*args, **kwargs)

        except exception_types as exc:
            last_exc = exc

            # Check whether the HTTP status code is retryable (if applicable)
            status_code: int | None = getattr(
                getattr(exc, "response", None), "status_code", None
            )
            if retryable_status_codes and status_code and status_code not in retryable_status_codes:
                logger.warning(
                    "Non-retryable HTTP %s from %s. Raising immediately.",
                    status_code,
                    func.__name__,
                )
                raise

            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "%s attempt %d/%d failed (%s). Retrying in %.1fs.",
                    func.__name__,
                    attempt,
                    max_attempts,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "%s failed after %d attempt(s): %s",
                    func.__name__,
                    max_attempts,
                    exc,
                )

    raise last_exc  # type: ignore[misc]
