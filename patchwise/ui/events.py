# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""A minimal in-process event bus the review pipeline emits run progress to.

The pipeline publishes structured milestones (plan ready, critic round, each
finding, each verdict, engineer answer, maintainer round, …) by calling
``emit(kind, **fields)``. A UI (or a test) subscribes with ``subscribe(fn)`` to
receive ``fn(kind, fields)`` calls. The bus is deliberately tiny and has no
third-party dependencies so the producers stay UI-agnostic.

Design guarantees the producers rely on:
  * With no subscriber, ``emit`` returns immediately (the common case: library
    callers, ``--plain``, non-TTY). Emitting is therefore safe to sprinkle into
    hot paths.
  * A misbehaving subscriber can never break a review: subscriber exceptions are
    logged at debug and swallowed.
"""

import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)

# Event kinds (string constants — no enum, to keep this module dependency-free
# and the payloads trivially serialisable).
RUN_START = "run_start"          # pipeline, target, model
INDEX = "index"                  # phase (start|progress|done), done, total, files, seconds
PHASE = "phase"                  # name  (plan|execution|filter|engineer|maintainer)
ITERATION = "iteration"          # label, n, cap, tokens, budget, peak
TOOL_CALL = "tool_call"          # label, iter, name, args, ok
PLAN = "plan"                    # tasks: [{id, dimension, focus, files, symbols}]
CRITIC = "critic"                # round, material, feedback: [str]
FINDING = "finding"              # label, dimension, location, text
VERDICT = "verdict"              # label, finding, impact, verdict, reason
ENGINEER_ANSWER = "engineer_answer"  # label, text
MAINTAINER = "maintainer"        # round, refuted, questions: [str], reason
RUN_DONE = "run_done"            # summary: {...}

Listener = Callable[[str, Dict[str, Any]], None]

_listeners: List[Listener] = []


def subscribe(fn: Listener) -> None:
    """Register a listener to receive every subsequent ``emit``."""
    if fn not in _listeners:
        _listeners.append(fn)


def unsubscribe(fn: Listener) -> None:
    """Remove a previously registered listener (no-op if absent)."""
    if fn in _listeners:
        _listeners.remove(fn)


def has_subscribers() -> bool:
    """True when a UI is listening (e.g. the live dashboard is active). Producers
    use this to suppress direct console writes that would corrupt the display."""
    return bool(_listeners)


def emit(kind: str, **fields: Any) -> None:
    """Publish an event to all subscribers. Returns immediately when there are
    none. Subscriber exceptions are contained so a review never fails on UI."""
    if not _listeners:
        return
    for fn in list(_listeners):
        try:
            fn(kind, fields)
        except Exception as e:  # a UI bug must never break a review
            logger.debug(f"event subscriber {fn!r} raised on {kind}: {e}")
