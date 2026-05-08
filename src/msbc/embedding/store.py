"""
Qdrant store for the embedding pipeline.

Wraps ``qdrant_client.QdrantClient`` with:
  • Collection bootstrap — create if not exists, apply payload indexes.
  • Batched upsert (64 points per call) with progress logging.
  • Filter-based delete by ``file_path`` (used for incremental sync).
  • Full-collection scroll to retrieve ``{file_path: file_id}`` hashes
    (used to diff which files need re-embedding).

Both the toolkit and examples collections are managed by the same class —
the caller selects the collection by passing ``kind`` or the collection name.
"""

from __future__ import annotations

import logging
from typing import Literal

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings
from src.msbc.embedding.schema import (
    get_collection_name,
    get_examples_payload_indexes,
    get_toolkit_payload_indexes,
    get_vector_config,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum points per upsert call.  Qdrant recommends ≤ 100; we use 64 to
# leave headroom for large payloads.
UPSERT_BATCH_SIZE: int = 64

# Maximum points returned per scroll page.
SCROLL_PAGE_SIZE: int = 256


# ---------------------------------------------------------------------------
# QdrantStore
# ---------------------------------------------------------------------------

class QdrantStore:
    """
    Thin wrapper around ``QdrantClient`` for the embedding pipeline.

    Parameters
    ----------
    url : str, optional
        Qdrant server URL.  Defaults to ``settings.QDRANT_URL``.
    api_key : str, optional
        Qdrant API key (leave empty for local instances).
        Defaults to ``settings.QDRANT_API_KEY``.
    dimensions : int, optional
        Embedding vector size.  Defaults to ``settings.EMBEDDING_DIMENSIONS``.
    """

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        _url = url or settings.QDRANT_URL
        _key = api_key or settings.QDRANT_API_KEY or None  # pass None not ""
        self.dimensions: int = dimensions or settings.EMBEDDING_DIMENSIONS

        self._client = QdrantClient(url=_url, api_key=_key)
        logger.info("QdrantStore connected — url=%s dims=%d", _url, self.dimensions)

    # ------------------------------------------------------------------
    # Collection bootstrap
    # ------------------------------------------------------------------

    def ensure_collection(self, kind: Literal["toolkit", "examples"]) -> str:
        """
        Ensure the Qdrant collection for *kind* exists and has all payload indexes.

        Creates the collection if it does not exist, then applies the field indexes
        defined in ``schema.py``.  Both steps are idempotent — safe to call on
        every ingestor startup.

        Parameters
        ----------
        kind : "toolkit" | "examples"
            Which collection to bootstrap.

        Returns
        -------
        str
            The resolved collection name (e.g. ``"toolkit_openai_large_1536"``).
        """
        collection_name = get_collection_name(kind, self.dimensions)
        vector_config: VectorParams = get_vector_config(self.dimensions)

        # ── Create collection if absent ───────────────────────────────────────
        existing = {c.name for c in self._client.get_collections().collections}
        if collection_name not in existing:
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config=vector_config,
            )
            logger.info("Created Qdrant collection '%s'.", collection_name)
        else:
            logger.debug("Collection '%s' already exists, skipping creation.", collection_name)

        # ── Apply payload indexes ─────────────────────────────────────────────
        indexes = (
            get_toolkit_payload_indexes()
            if kind == "toolkit"
            else get_examples_payload_indexes()
        )

        for field_name, schema_type in indexes.items():
            try:
                self._client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=schema_type,
                )
            except UnexpectedResponse as exc:
                # Status 400 means the index already exists — safe to ignore.
                if exc.status_code == 400:
                    logger.debug(
                        "Payload index '%s' already exists on '%s'.",
                        field_name,
                        collection_name,
                    )
                else:
                    raise

        logger.info(
            "Collection '%s' ready with %d payload indexes.",
            collection_name,
            len(indexes),
        )
        return collection_name

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def upsert_batch(
        self,
        collection: str,
        points: list[PointStruct],
    ) -> None:
        """
        Upsert *points* into *collection* in batches of ``UPSERT_BATCH_SIZE``.

        Parameters
        ----------
        collection : str
            Target collection name.
        points : list[PointStruct]
            Points to upsert.  Each must have ``id``, ``vector``, and ``payload``.
        """
        if not points:
            return

        total = len(points)
        upserted = 0

        for start in range(0, total, UPSERT_BATCH_SIZE):
            batch = points[start: start + UPSERT_BATCH_SIZE]
            self._client.upsert(
                collection_name=collection,
                points=batch,
                wait=True,
            )
            upserted += len(batch)
            logger.debug(
                "Upserted %d/%d points into '%s'.",
                upserted,
                total,
                collection,
            )

        logger.info("Upserted %d points into '%s'.", total, collection)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_by_file_path(self, collection: str, file_path: str) -> None:
        """
        Delete all points in *collection* whose payload ``file_path`` matches
        *file_path* exactly.

        Used during incremental sync to remove stale chunks before re-upserting
        updated file content.

        Parameters
        ----------
        collection : str
            Target collection name.
        file_path : str
            The ``file_path`` payload value to match (exact, case-sensitive).
        """
        self._client.delete(
            collection_name=collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="file_path",
                            match=MatchValue(value=file_path),
                        )
                    ]
                )
            ),
            wait=True,
        )
        logger.debug("Deleted points for file_path='%s' from '%s'.", file_path, collection)

    # ------------------------------------------------------------------
    # Scroll / hash retrieval
    # ------------------------------------------------------------------

    def get_stored_file_hashes(self, collection: str) -> dict[str, str]:
        """
        Scroll the entire *collection* and return a mapping of
        ``{file_path: file_id}`` for every stored point.

        Used by ingestors to decide which files are new, changed, or deleted:
        - **New**:     ``file_path`` not in returned dict.
        - **Changed**: ``file_id`` (SHA-256 of content) differs from stored value.
        - **Deleted**: ``file_path`` in dict but no longer on disk.

        Only ``file_path`` and ``file_id`` payload fields are fetched to keep
        memory usage minimal even for large collections.

        Parameters
        ----------
        collection : str
            Source collection name.

        Returns
        -------
        dict[str, str]
            ``{file_path: file_id}`` for every unique file stored.
            If the collection does not exist yet, returns an empty dict.
        """
        # Guard: return empty dict if the collection doesn't exist yet.
        existing = {c.name for c in self._client.get_collections().collections}
        if collection not in existing:
            logger.debug(
                "Collection '%s' not found in get_stored_file_hashes — returning empty dict.",
                collection,
            )
            return {}

        hashes: dict[str, str] = {}
        offset = None  # None means start from the beginning

        while True:
            result, next_offset = self._client.scroll(
                collection_name=collection,
                with_payload=["file_path", "file_id"],
                with_vectors=False,
                limit=SCROLL_PAGE_SIZE,
                offset=offset,
            )

            for point in result:
                payload = point.payload or {}
                fp = payload.get("file_path")
                fid = payload.get("file_id")
                if fp and fid:
                    # Keep the first hash seen for each file_path.
                    # All chunks from the same file share the same file_id so
                    # the value is consistent; we only need it once per file.
                    hashes.setdefault(fp, fid)

            if next_offset is None:
                break
            offset = next_offset

        logger.info(
            "get_stored_file_hashes: found %d unique files in '%s'.",
            len(hashes),
            collection,
        )
        return hashes

    # ------------------------------------------------------------------
    # Retrieval helpers (used by code-generator agent)
    # ------------------------------------------------------------------

    def search(
        self,
        collection: str,
        query_vector: list[float],
        filters: dict | None = None,
        top_k: int = 15,
    ) -> list[dict]:
        """
        Vector similarity search with optional payload filters.

        Parameters
        ----------
        collection : str
            Target collection name.
        query_vector : list[float]
            Dense embedding vector to search against.
        filters : dict, optional
            Supported keys:
              - ``content_type``: str or list[str] — matched with MatchAny/MatchValue
              - ``language``:     str — matched with MatchValue
        top_k : int
            Maximum number of results to return.

        Returns
        -------
        list[dict]
            Each entry: ``{"id": str, "score": float, "payload": dict}``.
        """
        must: list = []

        if filters:
            ct = filters.get("content_type")
            if ct:
                if isinstance(ct, list):
                    must.append(FieldCondition(key="content_type", match=MatchAny(any=ct)))
                else:
                    must.append(FieldCondition(key="content_type", match=MatchValue(value=ct)))

            lang = filters.get("language")
            if lang:
                must.append(FieldCondition(key="language", match=MatchValue(value=lang)))

        search_filter = Filter(must=must) if must else None

        response = self._client.query_points(
            collection_name=collection,
            query=query_vector,
            query_filter=search_filter,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )

        return [
            {"id": str(r.id), "score": r.score, "payload": r.payload or {}}
            for r in response.points
        ]

    def scroll_by_file_path(self, collection: str, file_path: str) -> list[dict]:
        """Return all chunks for *file_path* from *collection*, sorted by chunk_index."""
        results: list[dict] = []
        offset = None

        while True:
            points, next_offset = self._client.scroll(
                collection_name=collection,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="file_path",
                            match=MatchValue(value=file_path),
                        )
                    ]
                ),
                with_payload=True,
                with_vectors=False,
                limit=SCROLL_PAGE_SIZE,
                offset=offset,
            )

            for point in points:
                payload = point.payload or {}
                results.append({"id": str(point.id), **payload})

            if next_offset is None:
                break
            offset = next_offset

        results.sort(key=lambda p: p.get("chunk_index", 0))
        logger.debug(
            "scroll_by_file_path: %d chunks for '%s' in '%s'.",
            len(results),
            file_path,
            collection,
        )
        return results

    def get_by_ids(self, collection: str, ids: list[str]) -> list[dict]:
        """Return exact Qdrant points by point IDs (used for Kuzu example chunks)."""
        if not ids:
            return []

        points = self._client.retrieve(
            collection_name=collection,
            ids=ids,
            with_payload=True,
            with_vectors=False,
        )

        results = [{"id": str(p.id), **(p.payload or {})} for p in points]
        logger.debug(
            "get_by_ids: retrieved %d/%d points from '%s'.",
            len(results),
            len(ids),
            collection,
        )
        return results
