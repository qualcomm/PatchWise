# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import functools
import logging
import time
from typing import Callable, Optional, Tuple, Type

logger = logging.getLogger(__name__)


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
