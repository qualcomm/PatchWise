# Rule: hw-programming-sequence

## Trigger

Driver code changes a hardware bring-up/tear-down sequence — combined
clock/reset/regulator enable-disable ordering, memory barriers
(`wmb`/`dma_wmb`), DMA descriptor + doorbell writes, reset assert/deassert
timing, or recovery/quiesce steps.

## Must Check

- Does the enable sequence follow the required order (regulator → clock → deassert reset → register access) with no step omitted?
- Is the disable sequence the exact reverse, with hardware quiesced and DMA stopped before clocks/power are removed?
- Is a memory barrier (`wmb`/`dma_wmb`) present between descriptor writes and the doorbell/arm write so the device never sees a partial descriptor?
- Does recovery quiesce the hardware before publishing a fence/completion, so unexecuted work is not retired prematurely?
- Is a progress snapshot taken from a stable value, not a live-incrementing register, during capture/reset?

## Evidence Needed

- The old and new ordering of the sequence steps.
- Barrier placement relative to descriptor/doorbell writes.

## Safe Dismissal

Dismiss when source shows correct ordering, reverse teardown, and required
barriers, or the registers are documented as posted/ordered by the bus.

## Finding Template

```text
[BUG] Incorrect hardware programming sequence or missing barrier
File: <path>:<line>
Rule: hw-programming-sequence
Evidence: <ordering/barrier site in the diff>
Reasoning: <which ordering or barrier guarantee is violated>
Impact: <device sees partial descriptor, undefined reset state, lost/retired work>
Suggestion: <reorder steps, add wmb/dma_wmb before doorbell, quiesce before fence>
```

## Severity

`[BUG]` for a proven ordering/barrier hazard reaching hardware; `[CONCERN]` when
the register ordering guarantee is not confirmed from source/docs.
