# Rule: level-irq-reenable-without-clear

## Trigger

Driver IRQ code changes threaded IRQ handlers, `enable_irq*()`, IRQ masking,
level-triggered interrupt configuration, or defers/changes trigger selection in
a way that may enable edge-triggered operation for a status/aggregate IRQ line.

## Must Check

- Is the IRQ level-triggered by DT flags, request flags, or controller setup?
- If the IRQ can become edge-triggered, is the hardware source pulse-per-event,
  or is it an aggregate/status line that can stay asserted until all sources are
  cleared or drained?
- Before `enable_irq()` or handler return, is the hardware status/source cleared or masked?
- For aggregate/status IRQ lines, does the handler drain or re-read pending
  status after clearing so events arriving during the handler cannot be lost?
- Are posted writes flushed before re-enable when the clear uses MMIO/regmap?
- Can an error path skip the clear and still re-enable the line?
- Does threaded IRQ code avoid re-enabling from sleepable context before the source is deasserted?

## Evidence Needed

- IRQ request/DT trigger type and handler/thread function.
- Source signalling semantics: pulse-per-event edge, level/status aggregate, or
  unknown from the available source/hardware evidence.
- Status clear/ack/mask register write and any readback/flush.
- Drain/recheck loop, source masking, or proof that later events generate a new
  independent edge.
- Re-enable or return path after the clear.

## Safe Dismissal

Dismiss level-triggered cases only when the source is masked until cleared, or
every re-enable path follows a proven clear/ack with required flush.  Dismiss
edge-triggered cases only when source or hardware evidence shows pulse-per-event
signalling, the source is masked until drained, or the handler drains/rechecks
aggregate status until quiescent.  Do not treat `IRQF_TRIGGER_NONE` or a DT edge
cell alone as proof that no drain/recheck is needed.

## Finding Template

```text
[BUG] IRQ source can remain pending across handler return
File: <driver-path>:<handler-or-enable-line>
Rule: level-irq-reenable-without-clear
Evidence: <trigger type, source signalling semantics, return path, and missing clear/flush/drain>
Reasoning: <why asserted level source retriggers, or why edge/status aggregate can lose a later event>
Impact: <IRQ storm, missed interrupt, stuck threaded handler, or device unusable>
Suggestion: <clear/ack/mask source before enable_irq/return, flush posted writes, or drain/recheck aggregate status>
```

## Severity

Use `[BUG]` for reachable level-triggered re-enable without clear, or for a
documented edge-configured aggregate/status IRQ that can lose events without a
drain/recheck loop.  Use `[CONCERN]` when trigger polarity, source signalling,
or hardware deassertion is ambiguous.
