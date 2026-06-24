# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Terminal UI for patchwise.

`events` is a tiny, dependency-free publish/subscribe bus the review pipeline
emits to; `dashboard` is the optional rich live dashboard that subscribes to it.
The review code only ever imports `events` and calls `events.emit(...)`; it never
imports rich or knows whether a UI is attached. With no subscriber (the default,
and under `--plain` / non-TTY), `emit` returns immediately, so existing runs are
unaffected."""
