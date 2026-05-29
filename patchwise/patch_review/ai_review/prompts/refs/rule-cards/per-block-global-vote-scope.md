# Rule: per-block-global-vote-scope

## Trigger

Driver code moves, splits, or adds a helper that drops a global OPP,
performance-state, interconnect, genpd, or clock-rate vote to zero/NULL from a
per-block, per-core, per-stream, per-port, per-pipe, or per-link path.

## Must Check

- Identify whether the vote is global to the device/controller rather than local
  to the individual stream/block/link being disabled.
- Trace the full disable/off/power-down sequence and name every sibling block or
  stream that could still be active when the vote is dropped.
- Prove the drop runs only on the last active sibling, or that hardware/driver
  state prevents concurrent sibling activity.
- Do not clear the pattern with local symmetry alone: `on()` sets the vote and
  `off()` drops it is insufficient if `off()` is now per-block while the vote is
  global.

## Evidence Needed

- The exact vote drop site and whether its device/clock/domain object is shared.
- Callers of the new or modified off/disable helper.
- Sibling stream/block/link activity state and last-user tracking, if any.
- The matching vote-raise path and the sequencing that pairs it with teardown.

## Safe Dismissal

Dismiss only by quoting source evidence that no sibling remains active when the
vote drops: a last-stream refcount, a global modeset/bridge disable invariant,
a single-stream hardware guarantee for the current patch, or a caller sequence
that disables all siblings before the global vote is reduced.

## Finding Template

```text
[BUG] Global performance vote dropped from per-block teardown
File: <driver-path>:<vote-drop-line>
Rule: per-block-global-vote-scope
Evidence: <vote drop site, per-block caller, and active sibling path>
Reasoning: <why a sibling can still need the global vote after this helper runs>
Impact: <under-clocked/ungated active stream, transfer/display failure, or power-domain collapse>
Suggestion: <move the drop to last-user teardown or add/quote last-active gating>
```

## Severity

Use `[BUG]` when a sibling can remain active while the global vote is dropped.
Use `[CONCERN]` only when sibling concurrency or last-user sequencing is not
proven from the available source/context.
