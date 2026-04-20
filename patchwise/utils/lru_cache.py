# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from typing import Any, Callable, Optional

from cachetools import LRUCache as _LRUCache


class LRUCache(_LRUCache):
    """cachetools.LRUCache with an eviction callback."""

    def __init__(
        self,
        maxsize: int,
        getsizeof: Optional[Callable[[Any], int]] = None,
        evict: Optional[Callable[[Any, Any], None]] = None,
    ) -> None:
        super().__init__(maxsize, getsizeof=getsizeof)
        self._evict = evict

    def popitem(self):
        key, val = super().popitem()
        if self._evict is not None:
            self._evict(key, val)
        return key, val
