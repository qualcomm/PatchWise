# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""litellm embedding wrapper with on-disk numpy cache."""

from __future__ import annotations

import hashlib
import logging
import os
import warnings
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "text-embedding-3-small"
_BATCH_SIZE = 50


def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
    api_base: str | None = None,
    cache_dir: Path,
) -> np.ndarray:
    """Return an (n, d) float32 array of L2-normalised embeddings.

    Results are cached per (model, text) on disk under *cache_dir*.
    """
    import httpx
    import litellm

    warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    litellm.client_session = httpx.Client(verify=False)

    if model is None:
        model = os.environ.get("PATCHWISE_EVAL_EMBEDDING_MODEL", DEFAULT_MODEL)

    vectors: list[np.ndarray] = []
    for text in texts:
        vec = _load_cached(text, model, cache_dir)
        if vec is not None:
            vectors.append(vec)
        else:
            vectors.append(None)  # type: ignore[arg-type]

    missing_indices = [i for i, v in enumerate(vectors) if v is None]
    n_cached = len(texts) - len(missing_indices)
    logger.info("embed_texts: %d texts, %d cached, %d to fetch (model=%s)", len(texts), n_cached, len(missing_indices), model)

    for batch_start in range(0, len(missing_indices), _BATCH_SIZE):
        batch_idx = missing_indices[batch_start : batch_start + _BATCH_SIZE]
        batch_texts = [texts[i] for i in batch_idx]
        logger.info("  fetching batch %d-%d of %d ...", batch_start + 1, batch_start + len(batch_idx), len(missing_indices))
        response = litellm.embedding(model=model, input=batch_texts, api_base=api_base)
        for local_i, global_i in enumerate(batch_idx):
            raw = np.array(response.data[local_i]["embedding"], dtype=np.float32)
            norm = np.linalg.norm(raw)
            if norm > 0:
                raw = raw / norm
            vectors[global_i] = raw
            _save_cached(texts[global_i], model, cache_dir, raw)
        logger.info("  batch done, dim=%d", vectors[batch_idx[0]].shape[0])

    return np.stack(vectors)


def _cache_path(text: str, model: str, cache_dir: Path) -> Path:
    key = hashlib.sha256((model + "\x00" + text).encode()).hexdigest()
    return cache_dir / f"{key}.npy"


def _load_cached(text: str, model: str, cache_dir: Path) -> np.ndarray | None:
    path = _cache_path(text, model, cache_dir)
    if path.exists():
        return np.load(str(path))
    return None


def _save_cached(text: str, model: str, cache_dir: Path, vec: np.ndarray) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(str(_cache_path(text, model, cache_dir)), vec)
