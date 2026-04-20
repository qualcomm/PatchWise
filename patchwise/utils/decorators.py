# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import functools
import logging
import time
from typing import Callable, Optional, Tuple, Type, Union

from patchwise.utils.lru_cache import LRUCache

logger = logging.getLogger(__name__)


def lru_cache_cb(
    maxsize: int,
    on_evict: Optional[Union[Callable, str]] = None,
) -> Callable:
    """Per-instance LRU cache decorator with an eviction callback.

    Note: The cache lives on ``self`` (one per instance).

    Args:
        maxsize: Maximum cached entries per instance.
        on_evict: Classs method, called on eviction.
    """

    def decorator(func: Callable) -> Callable:
        cache_attr = f"__lru_cache_{func.__name__}"

        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            cache = getattr(self, cache_attr, None)
            if cache is None:

                def _evict(key: tuple, value) -> None:
                    if on_evict is None:
                        return
                    if callable(on_evict):
                        on_evict(self, key, value)
                    else:
                        getattr(self, on_evict)(key, value)

                cache = LRUCache(maxsize, evict=_evict if on_evict else None)
                setattr(self, cache_attr, cache)

            if args in cache:
                return cache[args]
            result = func(self, *args, **kwargs)
            cache[args] = result
            return result

        return wrapper

    return decorator


def retry(
    max_retries: int,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None,
) -> Callable:
    """Retry a function/method up to *max_retries* times on specified exceptions.

    Args:
        max_retries:  Total number of attempts (>= 1).
        exceptions:   Exception types that trigger a retry.
        on_retry:     Callable invoked between retries with the same positional
                      and keyword arguments as the wrapped function.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max(1, max_retries)):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    logger.warning(
                        "%s failed (attempt %d/%d): %s",
                        func.__qualname__,
                        attempt + 1,
                        max_retries,
                        exc,
                    )
                    if attempt < max_retries - 1:
                        time.sleep(2**attempt)
                        if on_retry is not None:
                            on_retry(*args, **kwargs)
                    else:
                        logger.error(
                            "Giving up on %s after %d attempts: %s",
                            func.__qualname__,
                            max_retries,
                            exc,
                        )
                        raise

        return wrapper

    return decorator
