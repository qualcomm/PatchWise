# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

import hashlib
import litellm
import logging
from pathlib import Path

from patchwise.patch_review.ai_review.fp_tools.config import (
    DEFAULT_EMBEDDING_API_BASE,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_FP_DB_PATH,
    DEFAULT_FP_DB_SIMILARITY_THRESHOLD,
    DEFAULT_FP_DB_TOP_K,
    configure_litellm_client,
    litellm_kwargs,
)
from patchwise.utils.decorators import retry


logger = logging.getLogger(__name__)

VECTOR_DB_PATH = DEFAULT_FP_DB_PATH
_FP_DB_COLLECTION = "patchwise_false_positives"
_FP_DB_SIMILARITY_THRESHOLD = DEFAULT_FP_DB_SIMILARITY_THRESHOLD
_FP_DB_DEFAULT_TOP_K = DEFAULT_FP_DB_TOP_K


class IssueEmbeddingClient:
    """LiteLLM embedding wrapper used by FalsePositiveDB."""

    def __init__(self, model: str | None, api_base: str | None) -> None:
        self._model = model
        self._api_base = api_base

    @retry(
        max_retries=10,
        exceptions=(
            litellm.Timeout,
            litellm.RateLimitError,
            litellm.InternalServerError,
        ),
    )
    def embed(self, text: str) -> list[float] | None:
        try:
            configure_litellm_client()
            litellm.drop_params = True
            response = litellm.embedding(
                **litellm_kwargs(
                    model=self._model,
                    api_base=self._api_base,
                    model_config_key="ai.fp_tools.embedding_model",
                    model_option="--embedding-model",
                    input=[text],
                )
            )
            return response.data[0]["embedding"]
        except Exception as exc:
            logger.error("FalsePositiveDB: embedding failed: %s", exc)
            return None


class FalsePositiveDB:
    """Persistent vector database for confirmed false-positive findings."""

    def __init__(
        self,
        db_path: Path | None = None,
        embedding_model: str | None = None,
        embedding_api_base: str | None = None,
        top_k: int = _FP_DB_DEFAULT_TOP_K,
        threshold: float = _FP_DB_SIMILARITY_THRESHOLD,
    ) -> None:
        self._db_path = Path(db_path or VECTOR_DB_PATH).expanduser()
        self._embedding_model = embedding_model or DEFAULT_EMBEDDING_MODEL
        self._embedding_api_base = embedding_api_base or DEFAULT_EMBEDDING_API_BASE
        self._top_k = top_k
        self._threshold = threshold
        self._client = None
        self._collection = None
        self._ready = False
        self._embedder = IssueEmbeddingClient(
            model=self._embedding_model,
            api_base=self._embedding_api_base,
        )

    def initialize(self) -> None:
        try:
            import chromadb as _chromadb
        except ImportError:
            logger.warning("chromadb not installed; FalsePositiveDB unavailable")
            return

        if not self._embedding_model:
            logger.warning(
                "ai.fp_tools.embedding_model not set; FalsePositiveDB unavailable"
            )
            return

        self._db_path.mkdir(parents=True, exist_ok=True)
        try:
            self._client = _chromadb.PersistentClient(path=str(self._db_path))
        except Exception as exc:
            logger.error("Failed to initialize ChromaDB at %s: %s", self._db_path, exc)
            return

        self._collection = self._client.get_or_create_collection(
            name=_FP_DB_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._ready = True
        logger.debug(
            "FalsePositiveDB ready — model=%r db=%s entries=%d",
            self._embedding_model,
            self._db_path,
            self._collection.count(),
        )

    def is_available(self) -> bool:
        return self._ready and self._collection is not None

    def add_false_positive_issue(
        self,
        patch_title: str,
        code_snippet: str,
        issue_description: str,
        reason: str,
        issue_label: str = "",
        message_id: str = "",
    ) -> bool:
        if not self.is_available():
            logger.warning("FalsePositiveDB not initialized; skipping add_false_positive_issue")
            return False

        issue_description = (issue_description or "").strip()
        if not issue_description:
            raise ValueError("issue_description must not be empty")

        patch_title = (patch_title or "").strip()
        code_snippet = (code_snippet or "").strip()
        reason = (reason or "").strip()
        issue_label = (issue_label or patch_title).strip()
        if not issue_label:
            raise ValueError("issue_label or patch_title must not be empty")

        doc_text = _format_issue_embedding_document(issue_description, code_snippet)
        doc_id = _make_issue_record_id(issue_label)
        embedding = self._embedder.embed(doc_text)
        if embedding is None:
            return False

        self._collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[doc_text],
            metadatas=[
                {
                    "record_id": doc_id,
                    "patch_title": patch_title,
                    "issue_label": issue_label,
                    "code_snippet": code_snippet,
                    "issue_description": issue_description,
                    "reason": reason,
                    "message_id": message_id,
                }
            ],
        )
        logger.debug("FalsePositiveDB: stored %s", doc_id)
        return True

    def has_patch_issue_records(self, patch_title: str) -> bool:
        if not self.is_available():
            return False
        patch_title = (patch_title or "").strip()
        if not patch_title:
            return False
        result = self._collection.get(
            where={"patch_title": {"$eq": patch_title}},
            limit=1,
            include=[],
        )
        return len(result.get("ids", [])) > 0

    def has_review_message_id(self, message_id: str) -> bool:
        if not self.is_available():
            return False
        message_id = (message_id or "").strip()
        if not message_id:
            return False
        result = self._collection.get(
            where={"message_id": {"$eq": message_id}},
            limit=1,
            include=[],
        )
        return len(result.get("ids", [])) > 0

    def search_similar_issues(
        self,
        code_snippet: str,
        issue_text: str,
        top_k: int | None = None,
        threshold: float | None = None,
    ) -> list[dict]:
        if not self.is_available():
            return []

        issue_text = (issue_text or "").strip()
        if not issue_text:
            return []

        count = self._collection.count()
        if count == 0:
            return []

        top_k = top_k if top_k is not None else self._top_k
        threshold = threshold if threshold is not None else self._threshold
        if top_k <= 0:
            return []

        query_text = _format_issue_embedding_document(issue_text, (code_snippet or "").strip())
        embedding = self._embedder.embed(query_text)
        if embedding is None:
            return []

        n_results = min(max(top_k, 1), count)
        results = self._collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            include=["metadatas", "distances"],
        )

        output = []
        metadatas = results.get("metadatas") or [[]]
        distances = results.get("distances") or [[]]
        for issue_meta, distance in zip(metadatas[0], distances[0]):
            similarity = 1 - distance
            if similarity < threshold:
                continue
            output.append(
                {
                    "patch_title": issue_meta.get("patch_title", ""),
                    "issue_label": issue_meta.get("issue_label", ""),
                    "code_snippet": issue_meta.get("code_snippet", ""),
                    "issue_description": issue_meta.get("issue_description", ""),
                    "reason": issue_meta.get("reason", ""),
                    "record_id": issue_meta.get("record_id", ""),
                    "distance": round(distance, 4),
                }
            )

        return sorted(output, key=lambda item: item["distance"])[:top_k]

    def get_count(self) -> int:
        if not self.is_available():
            return 0
        return self._collection.count()

    def clear(self) -> None:
        if not self.is_available():
            return
        try:
            self._client.delete_collection(_FP_DB_COLLECTION)
        except ValueError:
            pass
        self._collection = self._client.get_or_create_collection(
            name=_FP_DB_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        logger.debug("FalsePositiveDB: collection cleared")


def _format_issue_embedding_document(issue_description: str, code_snippet: str) -> str:
    if code_snippet:
        return f"Issue: {issue_description}\n\nCode:\n{code_snippet}"
    return issue_description


def _make_issue_record_id(issue_label: str) -> str:
    hash_hex = hashlib.sha256(issue_label.encode()).hexdigest()[:16]
    return f"fp_{hash_hex}"


_FP_DB_INSTANCE: FalsePositiveDB | None = None


def get_fp_db() -> FalsePositiveDB:
    global _FP_DB_INSTANCE
    if _FP_DB_INSTANCE is None:
        _FP_DB_INSTANCE = FalsePositiveDB()
        _FP_DB_INSTANCE.initialize()
    return _FP_DB_INSTANCE


def main() -> None:
    from patchwise.patch_review.ai_review.fp_tools.false_positive_issue_db_cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
