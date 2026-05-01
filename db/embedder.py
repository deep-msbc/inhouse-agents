import logging
import os
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

# Load .env BEFORE importing sentence_transformers / transformers so that
# TRANSFORMERS_OFFLINE=1 (and similar env vars) take effect before those
# libraries execute their module-level initialisation code.
load_dotenv()

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
DEFAULT_DIMENSIONS = 768

# ── Voyage AI model registry ──────────────────────────────────────────────────
# Native output dimensions for each Voyage model.
# voyage-code-3 / voyage-3 support matryoshka truncation to 256 / 512 / 1024.
_VOYAGE_NATIVE_DIMS: Dict[str, int] = {
    "voyage-code-3":         1024,
    "voyage-3":              1024,
    "voyage-3-lite":         512,
    "voyage-3.5":            1024,
    "voyage-3.5-lite":       512,
    "voyage-finance-2":      1024,
    "voyage-law-2":          1024,
    "voyage-multilingual-2": 1024,
    "voyage-code-2":         1536,
}

# Voyage AI embedding pricing (USD per 1 000 000 tokens, as of 2026)
_VOYAGE_PRICE_PER_M: Dict[str, float] = {
    "voyage-code-3":         0.18,
    "voyage-3":              0.06,
    "voyage-3-lite":         0.02,
    "voyage-3.5":            0.06,
    "voyage-3.5-lite":       0.02,
    "voyage-finance-2":      0.12,
    "voyage-law-2":          0.12,
    "voyage-multilingual-2": 0.06,
    "voyage-code-2":         0.12,
}

def _is_voyage(model_name: str) -> bool:
    return model_name in _VOYAGE_NATIVE_DIMS

# ── Model capability registries ───────────────────────────────────────────────
#
# These two dicts are HINT TABLES only.
# Any HuggingFace sentence-transformer model works even if it is NOT listed here.
#
# • If a model is NOT in _TRUST_REMOTE_CODE_MODELS → loads with trust=False (safe default).
# • If a model is NOT in _MODEL_PREFIXES            → text is embedded as-is (no prefix).
#   This is correct for most standard models (BGE, MiniLM, mpnet, gte, etc.).
#
# Add a model here only when it SPECIFICALLY requires one of these overrides.
# ─────────────────────────────────────────────────────────────────────────────

# Models that require trust_remote_code=True from HuggingFace.
# A model needs this flag when its HuggingFace repo ships custom Python
# modeling code (custom attention, pooling, tokenizer, etc.) that must be
# executed locally.  Standard transformer backbones (BERT, RoBERTa, …) do NOT
# need it and are safe to load with the default trust=False.
#
# Only add a model here when you have confirmed it loads with a "trust required"
# error or when the model card explicitly documents this requirement.
_TRUST_REMOTE_CODE_MODELS: frozenset = frozenset({
    # ── Nomic (custom FlashAttention / rotary-embedding kernel) ──────────
    "nomic-ai/nomic-embed-text-v1.5",
    "nomic-ai/nomic-embed-text-v1",

    # ── BAAI BGE-M3 (custom multi-vector pooling code) ────────────────────
    "BAAI/bge-m3",

    # ── Alibaba GTE-Qwen2 series (Qwen2 custom modeling code) ────────────
    "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
    "Alibaba-NLP/gte-Qwen2-7B-instruct",

    # ── Older Alibaba GTE-large-en-v1.5 (custom pooling) ─────────────────
    "Alibaba-NLP/gte-large-en-v1.5",
    "Alibaba-NLP/gte-base-en-v1.5",

    # ── Mistral / E5-Mistral (custom Mistral modeling code) ──────────────
    "intfloat/e5-mistral-7b-instruct",
})

# Per-model task prefix convention → (query_prefix, document_prefix)
# Leave a model out of this dict if it embeds raw text without any prefix.
_MODEL_PREFIXES: Dict[str, Tuple[str, str]] = {
    # ── Nomic (instruction-tuned, requires prefixes) ──────────────────────
    "nomic-ai/nomic-embed-text-v1.5": ("search_query", "search_document"),
    "nomic-ai/nomic-embed-text-v1":   ("search_query", "search_document"),

    # ── Microsoft E5 family (requires "query: " / "passage: " prefixes) ──
    "intfloat/e5-small-v2":           ("query", "passage"),
    "intfloat/e5-base-v2":            ("query", "passage"),
    "intfloat/e5-large-v2":           ("query", "passage"),
    "intfloat/multilingual-e5-small": ("query", "passage"),
    "intfloat/multilingual-e5-base":  ("query", "passage"),
    "intfloat/multilingual-e5-large": ("query", "passage"),
    "intfloat/e5-mistral-7b-instruct":("Instruct: Retrieve semantically similar text.\nQuery", ""),

    # ── BAAI BGE (query prefix only; documents get no prefix) ─────────────
    # Reference: https://huggingface.co/BAAI/bge-small-en-v1.5
    "BAAI/bge-small-en-v1.5":         ("Represent this sentence for searching relevant passages:", ""),
    "BAAI/bge-base-en-v1.5":          ("Represent this sentence for searching relevant passages:", ""),
    "BAAI/bge-large-en-v1.5":         ("Represent this sentence for searching relevant passages:", ""),
    "BAAI/bge-m3":                    ("Represent this sentence for searching relevant passages:", ""),


    # ── Models that use NO prefix at all (listed explicitly for clarity) ──
    # sentence-transformers/all-MiniLM-L6-v2  → no prefix needed
    # sentence-transformers/all-mpnet-base-v2 → no prefix needed
    # thenlper/gte-small / gte-base / gte-large → no prefix needed
    # These are intentionally left OUT of the dict so they receive raw text.
}


class VoyageEmbeddingService:
    """
    Wraps the Voyage AI REST API for batch text embedding.

    Uses VOYAGE_API_KEY from the environment (or a .env file).
    Supports all voyage-* models: voyage-code-3, voyage-3, voyage-3-lite, etc.

    Voyage maps our internal task strings:
      "search_document"  →  input_type="document"
      "search_query"     →  input_type="query"
    """

    # Voyage batch limit per API call.
    # Free tier (VOYAGE_FREE_TIER=true): 3 RPM / 10K TPM → batch=8 + 21 s sleep.
    # Paid tier: 128 per call, no sleep needed.
    _BATCH_SIZE_FREE = 8
    _BATCH_SIZE_PAID = 128
    _FREE_TIER_SLEEP_S = 21  # seconds between API calls (keeps RPM ≤ 2.86)

    def __init__(
        self,
        model_name: str,
        dimensions: Optional[int] = None,
    ) -> None:
        import voyageai

        # Inject the OS certificate store so corporate MITM proxy certs are trusted.
        # This is a no-op on machines that don't have truststore installed.
        try:
            import truststore
            truststore.inject_into_ssl()
            logger.debug("truststore: OS certificate store injected into SSL.")
        except ImportError:
            logger.warning(
                "truststore is not installed — SSL may fail on corporate networks. "
                "Run: uv add truststore"
            )

        api_key = os.environ.get("VOYAGE_API_KEY", "")
        if not api_key:
            raise EnvironmentError(
                "VOYAGE_API_KEY is not set. "
                "Export it in your shell or add it to a .env file."
            )
        self._model_name = model_name
        self._dimensions = dimensions  # None = use native size
        self._tokens_used: int = 0     # cumulative tokens; reset via reset_token_count()
        self._wait_seconds: float = 0.0  # cumulative rate-limit sleep; reset via reset_wait_seconds()
        self._client = voyageai.Client(api_key=api_key)

        # Free-tier mode: hard rate limits of 3 RPM / 10 K TPM.
        _free_tier_str = os.environ.get("VOYAGE_FREE_TIER", "false").strip().lower()
        self._free_tier = _free_tier_str in ("1", "true", "yes")
        self._BATCH_SIZE = (
            self._BATCH_SIZE_FREE if self._free_tier else self._BATCH_SIZE_PAID
        )
        # Tracks when the last Voyage API call was made (monotonic seconds).
        # Used to enforce the per-minute gap *across* separate embed_texts() calls.
        self._last_voyage_call_time: float = 0.0
        if self._free_tier:
            logger.warning(
                "VOYAGE_FREE_TIER=true — using batch_size=%d with %ds gap between "
                "API calls. Ingest will be slow but within 3 RPM / 10 K TPM limits.",
                self._BATCH_SIZE,
                self._FREE_TIER_SLEEP_S,
            )
        logger.info(
            "Voyage embedding client ready: model=%s dims=%s",
            model_name,
            dimensions if dimensions else "native",
        )

    @property
    def tokens_used(self) -> int:
        """Total Voyage tokens consumed since the last reset_token_count() call."""
        return self._tokens_used

    def reset_token_count(self) -> None:
        """Reset the cumulative token counter (call before each query)."""
        self._tokens_used = 0

    @property
    def wait_seconds(self) -> float:
        """Total seconds spent sleeping due to free-tier rate limiting."""
        return self._wait_seconds

    def reset_wait_seconds(self) -> None:
        """Reset the cumulative wait-time counter (call before each query)."""
        self._wait_seconds = 0.0

    def cost_for_tokens(self, token_count: int) -> float:
        """Estimate USD cost for a given token count using this model's pricing."""
        price = _VOYAGE_PRICE_PER_M.get(self._model_name, 0.0)
        return round(token_count * price / 1_000_000, 8)

    def embed_texts(
        self, texts: List[str], task: str = "search_document"
    ) -> List[List[float]]:
        """
        Embed a list of texts via the Voyage AI API and return float vectors.

        Args:
            texts: input strings.
            task:  "search_document" for ingestion, "search_query" at query time.
        """
        if not texts:
            return []

        input_type = "query" if task == "search_query" else "document"
        all_embeddings: List[List[float]] = []

        # Voyage has a per-call batch limit; chunk if needed.
        import time
        batches = list(range(0, len(texts), self._BATCH_SIZE))
        for batch_idx, i in enumerate(batches):
            # Free-tier: enforce minimum gap before EVERY call (including the first
            # call of a new embed_texts() invocation, which may immediately follow
            # the last call from the previous invocation).
            if self._free_tier:
                elapsed = time.monotonic() - self._last_voyage_call_time
                wait = self._FREE_TIER_SLEEP_S - elapsed
                if wait > 0:
                    logger.info(
                        "Free-tier rate limit: sleeping %.1fs before Voyage API call "
                        "%d/%d …",
                        wait,
                        batch_idx + 1,
                        len(batches),
                    )
                    time.sleep(wait)
                    self._wait_seconds += wait

            batch = texts[i : i + self._BATCH_SIZE]
            try:
                result = self._client.embed(
                    batch,
                    model=self._model_name,
                    input_type=input_type,
                    output_dimension=self._dimensions,  # None = native size
                )
                self._last_voyage_call_time = time.monotonic()
                all_embeddings.extend(result.embeddings)
                if hasattr(result, "total_tokens") and result.total_tokens:
                    self._tokens_used += result.total_tokens
                logger.debug(
                    "Voyage batch %d/%d — %d texts, %d tokens so far",
                    batch_idx + 1,
                    len(batches),
                    len(batch),
                    self._tokens_used,
                )
            except Exception as exc:
                logger.error("Voyage embedding failed (batch %d): %s", i, exc)
                raise

        return all_embeddings


class EmbeddingService:
    """Wraps any SentenceTransformer model for batch text embedding."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        dimensions: Optional[int] = None,
    ) -> None:
        self._model_name = model_name
        trust = model_name in _TRUST_REMOTE_CODE_MODELS
        if model_name not in _MODEL_PREFIXES:
            logger.info(
                "Model '%s' is not in the prefix registry — "
                "text will be embedded as-is (no task prefix). "
                "This is correct for MiniLM, mpnet, GTE, and similar models.",
                model_name,
            )
        logger.info(
            "Loading embedding model: %s (dims=%s)",
            model_name,
            dimensions if dimensions else "native",
        )
        self._model: SentenceTransformer = SentenceTransformer(
            model_name,
            trust_remote_code=trust,
            truncate_dim=dimensions,   # None = keep model's native output size
            device="cpu",              # Always use CPU to avoid CUDA OOM in WSL
            model_kwargs={
                # Force SDPA (scaled dot-product attention) instead of
                # flash_attention_2 which requires CUDA and crashes on CPU.
                "attn_implementation": "sdpa",
            },
        )
        logger.info("Embedding model loaded.")

    def embed_texts(
        self, texts: List[str], task: str = "search_document"
    ) -> List[List[float]]:
        """
        Embed a list of texts and return float vectors.

        Args:
            texts: input strings.
            task:  "search_document" for ingestion, "search_query" at query time.
                   Applied as a prefix only for models that use task prefixes
                   (e.g. nomic-embed).  Other models receive raw text.
        """
        if not texts:
            return []
        q_pfx, d_pfx = _MODEL_PREFIXES.get(self._model_name, ("", ""))
        prefix = q_pfx if task == "search_query" else d_pfx
        prefixed = [f"{prefix}: {t}" if prefix else t for t in texts]
        try:
            embeddings = self._model.encode(
                prefixed,
                batch_size=8,          # Small batches to cap peak CPU RAM usage
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            return [emb.tolist() for emb in embeddings]
        except Exception as exc:
            logger.error("Embedding failed: %s", exc)
            raise


# ── Module-level keyed singletons ──────────────────────────────────────────
# Key: (model_name, dimensions) → one service instance per unique combination.
# This ensures expensive model loads (HF) or API clients (Voyage) are built once.
_instances: Dict[Tuple[str, Optional[int]], object] = {}


def get_embedder(
    model_name: str = DEFAULT_MODEL_NAME,
    dimensions: Optional[int] = None,
) -> "EmbeddingService | VoyageEmbeddingService":
    """
    Return a shared embedding service for the given model/dimension pair.

    Automatically selects the correct backend:
      • voyage-code-3, voyage-3, voyage-* → VoyageEmbeddingService (API)
      • everything else                   → EmbeddingService (SentenceTransformer)
    """
    key = (model_name, dimensions)
    if key not in _instances:
        if _is_voyage(model_name):
            _instances[key] = VoyageEmbeddingService(model_name, dimensions)
        else:
            _instances[key] = EmbeddingService(model_name, dimensions)
    return _instances[key]

