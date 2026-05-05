"""
Requirement Extractor — module-level constants.

Environment-variable settings (OPENAI_API_KEY, LLM_MODEL, etc.) live in
app.core.config.settings and are accessed from there.

This file contains only pure constants: token budgets, pricing tables,
allowed file types, valid modes. Nothing here requires env-var access.
"""

from app.core.config import settings  # FastAPI settings (env vars)

# ── Token budget ──────────────────────────────────────────────────────────────
# Hard cap on (system_prompt + user_prompt + doc_text) tokens per LLM call.
TOTAL_INPUT_TOKEN_LIMIT: int = 12000   # lower threshold triggers chunking sooner for large modules

# Maximum tokens reserved for system + user prompt templates (excluding doc text).
# Available for module text per call ≈ TOTAL_INPUT_TOKEN_LIMIT - PROMPT_MAX_TOKENS
PROMPT_MAX_TOKENS: int = 4000

# ── Retry ─────────────────────────────────────────────────────────────────────
API_RETRY_ATTEMPTS: int = 3         # 1 original + 2 retries
API_RETRY_BASE_DELAY: float = 1.0   # seconds; doubles each retry: 1 → 2 → 4
SCHEMA_VALIDATION_RETRIES: int = 2  # extra attempts when JSON / schema invalid

# HTTP status codes considered transient (worth retrying)
RETRYABLE_STATUS_CODES: set[int] = {429, 500, 502, 503, 504}

# ── File upload ───────────────────────────────────────────────────────────────
MAX_FILE_SIZE_BYTES: int = 20 * 1024 * 1024  # 20 MB

ALLOWED_EXTENSIONS: set[str] = {".docx", ".pdf"}

ALLOWED_CONTENT_TYPES: set[str] = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",  # some browsers send this for .docx
}

# ── Extraction modes ──────────────────────────────────────────────────────────
VALID_MODES: set[str] = {"frontend", "backend", "both"}

# ── Cost tracking ─────────────────────────────────────────────────────────────
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4.1-mini":  {"input": 0.000400, "output": 0.001600},
    "gpt-4.1":       {"input": 0.002000, "output": 0.008000},
    "gpt-4.1-nano":  {"input": 0.000100, "output": 0.000400},
    "gpt-4o-mini":   {"input": 0.000150, "output": 0.000600},
    "gpt-4o":        {"input": 0.002500, "output": 0.010000},
    "gpt-4-turbo":   {"input": 0.010000, "output": 0.030000},
    "gpt-3.5-turbo": {"input": 0.000500, "output": 0.001500},
}

# ── JSON mode support ─────────────────────────────────────────────────────────
# Models with these prefixes support response_format={"type": "json_object"}.
JSON_MODE_SUPPORTED_PREFIXES: tuple[str, ...] = (
    "gpt-4.1",             # gpt-4.1, gpt-4.1-mini, gpt-4.1-nano
    "gpt-4o",              # gpt-4o, gpt-4o-mini
    "gpt-4-turbo",
    "gpt-3.5-turbo-1106",
    "gpt-3.5-turbo-0125",
)

# ── LLM concurrency ──────────────────────────────────────────────────────────
# Global cap on simultaneous OpenAI API calls.
# Within a single job, up to (modules × calls_per_module) coroutines race the
# semaphore at once.  With 5 modules × 3 calls = 15 calls, a limit of 5 would
# force ~3 serial rounds, adding up to 2×avg_call_time of queue-wait to every
# late-starting module — causing MODULE_EXTRACTION_TIMEOUT to fire before the
# module’s calls even get a chance to run.
# Set to 15 so all calls within a typical single job (up to 5 modules) proceed
# in parallel.  For multi-job overlap protection raise LLM_MAX_CONCURRENCY or
# rely on OpenAI’s own rate-limiter (which returns 429, already retried).
try:
    import os as _os
    LLM_MAX_CONCURRENCY: int = int(_os.environ.get("LLM_MAX_CONCURRENCY", "15"))
except (ValueError, TypeError):
    LLM_MAX_CONCURRENCY = 15

# ── Per-module extraction timeout ────────────────────────────────────────────
# Hard deadline (seconds) for the entire extract_module_node coroutine,
# covering all parallel LLM calls (fe + be + summary) plus retries.
# With max_chunks raised to 20 and mode=both running Phase A then Phase B,
# worst-case per phase: ceil(20/LLM_MAX_CONCURRENCY) rounds × LLM_TIMEOUT(120s)
#   × SCHEMA_VALIDATION_RETRIES(3) ≈ 2 × 360s = 720s across both phases.
# Default raised to 900s to accommodate large modules without false timeouts.
try:
    MODULE_EXTRACTION_TIMEOUT: int = int(_os.environ.get("MODULE_EXTRACTION_TIMEOUT", "900"))
except (ValueError, TypeError):
    MODULE_EXTRACTION_TIMEOUT = 900

# ── Per-module extraction concurrency cap ─────────────────────────────────────
# The Send fan-out in build_slices_node fires all N modules in parallel.
# MODULE_BATCH_SIZE limits how many extract_module_node coroutines run at once,
# preventing the rate-limit cascade that causes timeouts on large documents.
# With MODULE_BATCH_SIZE=3 and Phase-4 sequential FE/BE (N+1 peak per module):
#   worst-case simultaneous LLM calls ≈ 3 × (N_chunks + 1) ≤ ~12 per batch.
try:
    MODULE_BATCH_SIZE: int = int(_os.environ.get("MODULE_BATCH_SIZE", "3"))
except (ValueError, TypeError):
    MODULE_BATCH_SIZE = 3

# ── Convenience re-exports from app-level settings ────────────────────────────
# Centralise access so other module files can import from one place.
LLM_API_KEY: str = settings.OPENAI_API_KEY
LLM_MODEL: str = settings.LLM_MODEL
LLM_TIMEOUT: int = settings.LLM_TIMEOUT
