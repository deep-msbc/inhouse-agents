"""
OpenAI LLM client for the requirement extractor.

Wraps LangChain ChatOpenAI with:
  - tiktoken token counting
  - JSON mode for supported models
  - Schema validation (jsonschema Draft202012) with retry on invalid output
  - Exponential-backoff retry on transient API failures
"""

import asyncio
import json
import logging
import re
from collections.abc import Callable
from typing import Any

import tiktoken
from jsonschema import Draft202012Validator
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings
from src.msbc.config import (
    API_RETRY_ATTEMPTS,
    API_RETRY_BASE_DELAY,
    JSON_MODE_SUPPORTED_PREFIXES,
    LLM_MAX_CONCURRENCY,
    MODEL_PRICING,
    RETRYABLE_STATUS_CODES,
    SCHEMA_VALIDATION_RETRIES,
)

logger = logging.getLogger(__name__)

# ── Global concurrency gate ──────────────────────────────────────────────────
# Caps the number of simultaneous OpenAI API calls across all background jobs.
# Default is 15 — enough for one full job (5 modules × 3 calls) with no queuing.
# Lazily initialized on first use so LLM_MAX_CONCURRENCY env-var overrides apply.
_llm_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Return (and lazily create) the module-level LLM concurrency semaphore."""
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENCY)
    return _llm_semaphore

# ── Tokenizer ─────────────────────────────────────────────────────────────────

def _get_encoder():
    """Return a tiktoken encoder. Falls back to cl100k_base if model not found."""
    try:
        return tiktoken.encoding_for_model(settings.LLM_MODEL)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count the number of tokens in *text* for the configured model."""
    return len(_get_encoder().encode(text))


# ── Cost tracking ─────────────────────────────────────────────────────────────

def _calculate_cost(model: str, input_tokens: int, output_tokens: int) -> dict[str, Any]:
    pricing = MODEL_PRICING.get(model, {"input": 0.0004, "output": 0.0016})
    input_cost  = (input_tokens  / 1_000) * pricing["input"]
    output_cost = (output_tokens / 1_000) * pricing["output"]
    return {
        "input_tokens":    input_tokens,
        "output_tokens":   output_tokens,
        "total_tokens":    input_tokens + output_tokens,
        "input_cost_usd":  round(input_cost,  6),
        "output_cost_usd": round(output_cost, 6),
        "total_cost_usd":  round(input_cost + output_cost, 6),
        "model":           model,
    }


def merge_usage(usages: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge multiple per-call usage dicts into one total."""
    total_in  = sum(u.get("input_tokens",  0) for u in usages)
    total_out = sum(u.get("output_tokens", 0) for u in usages)
    model = usages[0]["model"] if usages else settings.LLM_MODEL
    return _calculate_cost(model, total_in, total_out)


# ── LangChain client factory ──────────────────────────────────────────────────

def _build_llm() -> ChatOpenAI:
    """Create a ChatOpenAI instance with json_object mode when supported."""
    supports_json = any(
        settings.LLM_MODEL.startswith(p) for p in JSON_MODE_SUPPORTED_PREFIXES
    )
    kwargs: dict[str, Any] = {
        "model":       settings.LLM_MODEL,
        "api_key":     settings.OPENAI_API_KEY,
        "temperature": 0.1,
        "timeout":     settings.LLM_TIMEOUT,
    }
    if supports_json:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return ChatOpenAI(**kwargs)


# ── Raw LLM call with retry ───────────────────────────────────────────────────

async def call_llm(
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, dict[str, Any]]:
    """
    Invoke the LLM with exponential-backoff retry on transient failures.

    Returns:
        (content_str, usage_dict)
    """
    async with _get_semaphore():
        llm = _build_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        last_exc: Exception | None = None
        for attempt in range(1, API_RETRY_ATTEMPTS + 1):
            try:
                # asyncio.wait_for enforces a hard wall-clock deadline independent
                # of httpx timeouts, which only apply per-read-chunk and can be
                # bypassed by slow-streaming responses.
                response = await asyncio.wait_for(
                    llm.ainvoke(messages),
                    timeout=settings.LLM_TIMEOUT,
                )
                content = response.content or ""
                usage_meta = response.response_metadata.get("token_usage", {})
                usage = _calculate_cost(
                    settings.LLM_MODEL,
                    usage_meta.get("prompt_tokens",
                                   count_tokens(system_prompt + user_prompt)),
                    usage_meta.get("completion_tokens", count_tokens(content)),
                )
                return content, usage

            except asyncio.TimeoutError:
                last_exc = RuntimeError(
                    f"LLM call timed out after {settings.LLM_TIMEOUT}s"
                )
                if attempt >= API_RETRY_ATTEMPTS:
                    raise last_exc
                delay = API_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "LLM call timed out (attempt %d/%d, limit=%ds) — retrying in %.1fs.",
                    attempt, API_RETRY_ATTEMPTS, settings.LLM_TIMEOUT, delay,
                )
                await asyncio.sleep(delay)

            except Exception as exc:
                last_exc = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                retryable = (status in RETRYABLE_STATUS_CODES) if status else True
                if not retryable or attempt >= API_RETRY_ATTEMPTS:
                    raise

                delay = API_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s — retrying in %.1fs.",
                    attempt, API_RETRY_ATTEMPTS, exc, delay,
                )
                await asyncio.sleep(delay)

        raise RuntimeError(
            f"LLM call failed after {API_RETRY_ATTEMPTS} attempts: {last_exc}"
        )


# ── JSON parsing ──────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict[str, Any]:
    """Strip optional markdown fences and parse the JSON string."""
    if not raw or not raw.strip():
        raise RuntimeError("LLM returned an empty response.")
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"LLM did not return valid JSON. Error: {exc}. "
            f"Raw (first 300 chars): {raw[:300]}"
        ) from exc


def _validate_schema(data: dict[str, Any], schema: dict[str, Any], name: str) -> None:
    """Raise RuntimeError with a readable message if *data* fails *schema*."""
    errors = sorted(
        Draft202012Validator(schema).iter_errors(data), key=lambda e: e.path
    )
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.path) or "<root>"
        raise RuntimeError(
            f"Schema validation failed for '{name}' at '{path}': {first.message}"
        )


# ── Schema-validated LLM call ─────────────────────────────────────────────────

async def call_llm_with_schema(
    system_prompt: str,
    user_prompt: str,
    schema: dict[str, Any],
    schema_name: str,
    normalizer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Call the LLM, parse JSON, and validate against *schema*.

    On parse/schema failure, retries up to SCHEMA_VALIDATION_RETRIES more
    times, appending the error to the user prompt each time.

    An optional *normalizer* callable is applied after JSON parsing and before
    schema validation on every attempt — use it to coerce the LLM's output
    into the expected structure without burning retry budget.

    Returns:
        (validated_dict, [usage_per_attempt])
    """
    usages: list[dict[str, Any]] = []
    prompt = user_prompt

    for attempt in range(1, SCHEMA_VALIDATION_RETRIES + 2):
        raw, usage = await call_llm(system_prompt, prompt)
        usages.append(usage)
        try:
            parsed = _parse_json(raw)
            if normalizer is not None:
                parsed = normalizer(parsed)
            _validate_schema(parsed, schema, schema_name)
            return parsed, usages
        except Exception as exc:
            if attempt > SCHEMA_VALIDATION_RETRIES:
                raise RuntimeError(
                    f"LLM output invalid for '{schema_name}' after "
                    f"{attempt} attempt(s): {exc}"
                ) from exc
            logger.warning(
                "Attempt %d/%d — invalid output for '%s': %s. Retrying.",
                attempt, SCHEMA_VALIDATION_RETRIES + 1, schema_name, exc,
            )
            prompt = (
                f"{user_prompt}\n\n"
                "IMPORTANT: Your previous response was invalid. "
                "Return ONLY valid JSON that satisfies the required schema. "
                f"Validation error: {exc}"
            )

    raise RuntimeError(  # unreachable but satisfies type checkers
        f"call_llm_with_schema: unreachable for '{schema_name}'"
    )
