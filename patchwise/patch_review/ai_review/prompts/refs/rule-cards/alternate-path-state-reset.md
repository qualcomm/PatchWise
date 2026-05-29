# Rule: alternate-path-state-reset

## Trigger

Patch assigns mode/type/source/format/configuration state on one operational path
while alternate paths such as TPG, loopback, internal source, bypass, virtual
pipeline, or error fallback can reach the same consumer.

## Must Check

- Which paths assign or reset the state field, and which paths skip assignment?
- Can an alternate path reach the consumer with stale state from a previous mode?
- Is the consumer guarded by current mode/source, or does it always trust the cached field?
- Are stop/reset/error paths clearing the field before the next start/stream/transfer?

## Evidence Needed

- New assignment and all consumers of the field.
- Alternate entry points and reset/stop/error paths.
- Mode/source guards before consumption.

## Safe Dismissal

Dismiss only when every alternate path either resets the state, cannot reach the
consumer, or the consumer is guarded by a source/mode check.

## Finding Template

```text
[BUG] Alternate path can reuse stale mode-dependent state
File: <driver-path>:<assignment-or-consumer>
Rule: alternate-path-state-reset
Evidence: <assigned field, alternate path, and missing reset/guard>
Reasoning: <how stale state from one mode reaches another path>
Impact: <wrong hardware programming, invalid stream config, or stale routing>
Suggestion: <reset on all paths or guard consumers by current mode/source>
```

## Severity

Use `[BUG]` for reachable stale-state programming; `[CONCERN]` when alternate
path reachability needs hardware/runtime confirmation.
