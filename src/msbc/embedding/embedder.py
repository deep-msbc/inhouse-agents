"""
OpenAI embedder for the embedding pipeline.

Wraps ``openai.AsyncOpenAI`` with:
  • Configurable model + dimensions (defaults from app settings).
  • Batch splitting — sends at most BATCH_SIZE texts per API call to stay within
    the OpenAI 2 048-input-per-request limit.  100 is the plan-specified safe default.
  • Exponential-backoff retry via ``app.utils.retry_utils.async_retry``.
  • Per-call and cumulative token usage + cost tracking.

Usage
-----
    embedder = OpenAIEmbedder()
    vectors, usage = await embedder.embed_texts(["hello world", "another text"])
    # vectors: list[list[float]]
    # usage:   {"total_tokens": int, "total_cost_usd": float, ...}
"""

from __future__ import annotations

import logging
from typing import Any

import openai
from openai import AsyncOpenAI

from app.core.config import settings
from app.utils.retry_utils import async_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum number of texts sent in a single API call.
# OpenAI allows up to 2 048, but 100 keeps individual request latency low.
BATCH_SIZE: int = 100

# OpenAI pricing for text-embedding-3-large (USD per 1M tokens, 2025).
_PRICE_PER_M_TOKENS: float = 0.13

# Retryable HTTP status codes for the OpenAI embedding endpoint.
_RETRYABLE_STATUS_CODES: set[int] = {429, 500, 502, 503, 504}

# Exception types that should trigger a retry.
_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
)


# ---------------------------------------------------------------------------
# Cost helper
# ---------------------------------------------------------------------------

def _compute_cost(total_tokens: int, price_per_m: float = _PRICE_PER_M_TOKENS) -> float:
    """Return the USD cost for *total_tokens* given *price_per_m* per 1M tokens."""
    return round((total_tokens / 1_000_000) * price_per_m, 6)


# ---------------------------------------------------------------------------
# OpenAIEmbedder
# ---------------------------------------------------------------------------

class OpenAIEmbedder:
    """
    Async OpenAI embedding client.

    Parameters
    ----------
    model : str, optional
        OpenAI embedding model name.  Defaults to ``settings.OPENAI_EMBEDDING_MODEL``.
    dimensions : int, optional
        Output vector dimensions.  Defaults to ``settings.EMBEDDING_DIMENSIONS``.
        For ``text-embedding-3-large`` this activates matryoshka truncation when
        set below the model's native 3 072-dim output.
    api_key : str, optional
        OpenAI API key.  Defaults to ``settings.OPENAI_API_KEY``.
    """

    def __init__(
        self,
        model: str | None = None,
        dimensions: int | None = None,
        api_key: str | None = None,
    ) -> None:
        self.model: str = model or settings.OPENAI_EMBEDDING_MODEL
        self.dimensions: int = dimensions or settings.EMBEDDING_DIMENSIONS
        _key: str = api_key or settings.OPENAI_API_KEY

        if not _key:
            raise ValueError(
                "OpenAI API key is required.  Set OPENAI_API_KEY in your .env file."
            )

        self._client = AsyncOpenAI(api_key=_key)
        logger.info(
            "OpenAIEmbedder initialised — model=%s dimensions=%d",
            self.model,
            self.dimensions,
        )

    # ------------------------------------------------------------------
    # Internal: single-batch API call (wrapped by retry)
    # ------------------------------------------------------------------

    async def _call_api(self, texts: list[str]) -> tuple[list[list[float]], int]:
        """
        Send one batch of *texts* to the OpenAI embeddings endpoint.

        Returns
        -------
        (vectors, prompt_tokens)
            vectors       : One float list per input text.
            prompt_tokens : Tokens consumed by this call (for cost tracking).
        """
        response = await self._client.embeddings.create(
            input=texts,
            model=self.model,
            dimensions=self.dimensions,
        )

        # OpenAI returns embeddings in the same order as input texts.
        vectors: list[list[float]] = [item.embedding for item in response.data]
        tokens: int = response.usage.prompt_tokens
        return vectors, tokens

    async def _call_api_with_retry(
        self, texts: list[str]
    ) -> tuple[list[list[float]], int]:
        """Wrapper around ``_call_api`` that applies exponential-backoff retry."""
        return await async_retry(
            self._call_api,
            texts,
            exception_types=_RETRYABLE_EXCEPTIONS,
            retryable_status_codes=_RETRYABLE_STATUS_CODES,
            max_attempts=3,
            base_delay=1.0,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def embed_batch(self, texts: list[str]) -> tuple[list[list[float]], dict[str, Any]]:
        """
        Embed a single batch of up to ``BATCH_SIZE`` texts in one API call.

        Parameters
        ----------
        texts : list[str]
            Texts to embed.  Length must not exceed ``BATCH_SIZE``.

        Returns
        -------
        (vectors, usage)
            vectors : One float list per input text.
            usage   : ``{"prompt_tokens": int, "cost_usd": float}``.

        Raises
        ------
        ValueError
            If *texts* is empty or exceeds ``BATCH_SIZE``.
        """
        if not texts:
            raise ValueError("embed_batch requires at least one text.")
        if len(texts) > BATCH_SIZE:
            raise ValueError(
                f"embed_batch received {len(texts)} texts; max is {BATCH_SIZE}. "
                "Use embed_texts() for larger inputs."
            )

        vectors, prompt_tokens = await self._call_api_with_retry(texts)
        usage: dict[str, Any] = {
            "prompt_tokens": prompt_tokens,
            "cost_usd": _compute_cost(prompt_tokens),
            "model": self.model,
            "dimensions": self.dimensions,
        }
        logger.debug(
            "embed_batch: %d texts → %d tokens ($%.6f)",
            len(texts),
            prompt_tokens,
            usage["cost_usd"],
        )
        return vectors, usage

    async def embed_texts(
        self, texts: list[str]
    ) -> tuple[list[list[float]], dict[str, Any]]:
        """
        Embed an arbitrarily large list of *texts*.

        Splits the input into batches of ``BATCH_SIZE``, calls ``embed_batch``
        for each, then concatenates the results.

        Parameters
        ----------
        texts : list[str]
            Texts to embed.

        Returns
        -------
        (vectors, usage)
            vectors : One float list per input text (same order as input).
            usage   : Cumulative ``{"total_tokens": int, "total_cost_usd": float,
                       "batch_count": int, "model": str, "dimensions": int}``.

        Raises
        ------
        ValueError
            If *texts* is empty.
        openai.OpenAIError
            Re-raised after all retry attempts are exhausted.
        """
        if not texts:
            raise ValueError("embed_texts requires at least one text.")

        all_vectors: list[list[float]] = []
        total_tokens: int = 0
        batch_count: int = 0

        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start: start + BATCH_SIZE]
            batch_vectors, batch_usage = await self.embed_batch(batch)
            all_vectors.extend(batch_vectors)
            total_tokens += batch_usage["prompt_tokens"]
            batch_count += 1

        cumulative_usage: dict[str, Any] = {
            "total_tokens": total_tokens,
            "total_cost_usd": _compute_cost(total_tokens),
            "batch_count": batch_count,
            "model": self.model,
            "dimensions": self.dimensions,
        }

        logger.info(
            "embed_texts complete: %d texts | %d batches | %d tokens | $%.6f",
            len(texts),
            batch_count,
            total_tokens,
            cumulative_usage["total_cost_usd"],
        )

        return all_vectors, cumulative_usage
