# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Build a ChromaDB collection of all kernel commits since a given date.

Usage:
    python -m tests.eval.build_db \
        --since 2026-03-26 \
        --kernel-path tests/linux \
        --chroma-path tests/eval/chroma \
        --embedding-model openai/stella_en_400M_v5 \
        --embedding-provider https://qpilot-api.qualcomm.com/v1

The collection is named "commits" and stored persistently under --chroma-path.
Re-running is safe: already-embedded SHAs are skipped.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_KERNEL_PATH = _REPO_ROOT / "tests" / "linux"
_DEFAULT_CHROMA_PATH = _REPO_ROOT / "tests" / "eval" / "chroma"
_DEFAULT_SCOPE_REF = "patchwise-linux-next-stable"
_BATCH_SIZE = 50
COLLECTION_NAME = "commits"


def build_db(
    *,
    since: str,
    kernel_path: Path,
    chroma_path: Path,
    scope_ref: str,
    embedding_model: str,
    embedding_provider: str | None,
    cache_dir: Path,
) -> None:
    import chromadb
    from .embed import embed_texts

    # collect all commit SHAs + subjects since the cutoff date
    logger.info("Listing commits in %s since %s ...", scope_ref, since)
    result = subprocess.run(
        ["git", "-C", str(kernel_path), "log", scope_ref,
         f"--after={since}", "--no-merges", "--format=%H\x1f%s\x1f%b\x1e"],
        capture_output=True, text=True, check=True,
    )

    commits: list[tuple[str, str]] = []  # (sha, text)
    for record in result.stdout.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split("\x1f", 2)
        if len(parts) < 2:
            continue
        sha, subject = parts[0].strip(), parts[1].strip()
        body = parts[2].strip() if len(parts) > 2 else ""
        if not sha:
            continue
        text = subject + ("\n\n" + body if body else "")
        commits.append((sha, text))

    logger.info("Found %d commits to embed", len(commits))

    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    # find which SHAs are already in the collection
    all_shas = [sha for sha, _ in commits]
    existing_ids: set[str] = set()
    for i in range(0, len(all_shas), 1000):
        batch = all_shas[i:i + 1000]
        existing_ids.update(collection.get(ids=batch)["ids"])

    missing = [(sha, text) for sha, text in commits if sha not in existing_ids]
    logger.info("%d already embedded, %d to embed", len(existing_ids), len(missing))

    from tqdm import tqdm
    batches = range(0, len(missing), _BATCH_SIZE)
    for batch_start in tqdm(batches, desc="Embedding commits", unit="batch"):
        batch = missing[batch_start:batch_start + _BATCH_SIZE]
        shas = [sha for sha, _ in batch]
        texts = [text for _, text in batch]
        vecs = embed_texts(texts, model=embedding_model, api_base=embedding_provider,
                           cache_dir=cache_dir)
        collection.upsert(ids=shas, embeddings=vecs.tolist(), documents=texts)

    logger.info("Done. Collection '%s' now has %d commits.", COLLECTION_NAME, collection.count())


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build ChromaDB commit collection.")
    p.add_argument("--since", required=True, help="Include commits after this date (e.g. 2026-03-26)")
    p.add_argument("--kernel-path", type=Path, default=_DEFAULT_KERNEL_PATH)
    p.add_argument("--chroma-path", type=Path, default=_DEFAULT_CHROMA_PATH)
    p.add_argument("--scope-ref", default=_DEFAULT_SCOPE_REF)
    p.add_argument("--embedding-model", default="text-embedding-3-small")
    p.add_argument("--embedding-provider", default=None)
    p.add_argument("--cache-dir", type=Path, default=_DEFAULT_CHROMA_PATH / "embed_cache")
    return p.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args()
    build_db(
        since=args.since,
        kernel_path=args.kernel_path,
        chroma_path=args.chroma_path,
        scope_ref=args.scope_ref,
        embedding_model=args.embedding_model,
        embedding_provider=args.embedding_provider,
        cache_dir=args.cache_dir,
    )
