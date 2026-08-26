# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Content-addressed Redis cache for per-file tree-sitter parse results.

Each entry is keyed by the git blob SHA of the source file; the value is the
list of constructs returned by _parse_bytes().  A parse result is a pure
function of file bytes, so the cache never needs invalidation — stale entries
age out under the server's allkeys-lru policy.

SCHEMA_VERSION must be bumped whenever _TS_QUERY_SRC, _KIND_BY_NODE, or the
tree-sitter grammar changes, so old keys quietly age out instead of returning
wrong data.
"""
import json
import logging
from typing import Dict, List, Optional

import redis as redis_lib
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

from patchwise.utils.config import redis_address

SCHEMA_VERSION = 1

logger = logging.getLogger(__name__)


def key(blob_sha: str) -> str:
    return f"ts:v{SCHEMA_VERSION}:{blob_sha}"


class TsCache:
    """Thin wrapper over redis-py for tree-sitter construct caching."""

    def __init__(self) -> None:
        host, port = redis_address()
        self._client = redis_lib.Redis(
            host=host, port=port, decode_responses=True,
            # Generous read timeout to ride out big MGETs and snapshot fork pauses.
            socket_connect_timeout=1, socket_timeout=5,
            # Fail fast: `ensure_ts_cache_service` already waited for readiness,
            # so a long retry here would only stall every tool call.
            retry=Retry(ExponentialBackoff(base=0.1, cap=1), retries=2),
            retry_on_error=[redis_lib.ConnectionError, redis_lib.TimeoutError],
        )
        # Fail loud: raise immediately if Redis is unreachable.
        self._client.ping()

    def get(self, sha: str) -> Optional[List]:
        """Return the cached construct list for blob_sha, or None on miss."""
        raw = self._client.get(key(sha))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.debug("ts_cache: corrupt value for %s, treating as miss", sha)
            return None

    def mget(self, shas: List[str]) -> Dict[str, Optional[List]]:
        """Return {sha: constructs|None} for each sha in the list."""
        if not shas:
            return {}
        keys = [key(s) for s in shas]
        raws = self._client.mget(keys)
        result: Dict[str, Optional[List]] = {}
        for sha, raw in zip(shas, raws):
            if raw is None:
                result[sha] = None
            else:
                try:
                    result[sha] = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    logger.debug("ts_cache: corrupt value for %s, treating as miss", sha)
                    result[sha] = None
        return result

    def set(self, sha: str, constructs: List) -> None:
        """Store the construct list for blob_sha."""
        self._client.set(key(sha), json.dumps(constructs))

    def mset(self, constructs_by_sha: Dict[str, List]) -> None:
        """Store many construct lists in one round-trip."""
        if constructs_by_sha:
            self._client.mset(
                {key(s): json.dumps(c) for s, c in constructs_by_sha.items()}
            )

    def memory_bytes(self) -> int:
        """Return Redis used_memory in bytes."""
        return int(self._client.info("memory")["used_memory"])
