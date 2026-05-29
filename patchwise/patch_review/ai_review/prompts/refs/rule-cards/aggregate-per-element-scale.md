# Rule: aggregate-per-element-scale

## Trigger

Code changes bandwidth/rate/clock/ICC/fabric calculations that divide or scale
an aggregate value by lane/port/path/channel count while per-element descriptors
also carry their own width/rate/count fields.

## Must Check

- Is the divided value aggregate or already per element?
- Are all elements homogeneous, or does each descriptor have its own width/rate/count?
- Does the code use the current element's field rather than a container/global width?
- Do DT bindings, match data, and provider arrays agree on lane/path counts?

## Evidence Needed

- Calculation site and source of aggregate/per-element values.
- Element descriptor fields and iteration context.
- Binding/match-data values for lane/path/width counts.

## Safe Dismissal

Dismiss only when source proves the value is truly aggregate and all elements
share the divisor, or the code uses per-element descriptors consistently.

## Finding Template

```text
[CONCERN] Aggregate scaling ignores per-element width/rate data
File: <driver-path>:<calculation-line>
Rule: aggregate-per-element-scale
Evidence: <aggregate value, divisor, and per-element descriptor field>
Reasoning: <why one divisor can mis-scale heterogeneous elements>
Impact: <wrong bandwidth, clock, ICC vote, or register programming>
Suggestion: <use per-element field or prove homogeneous aggregate semantics>
```

## Severity

Use `[BUG]` for deterministic wrong programming; `[CONCERN]` when hardware data
could be heterogeneous but needs confirmation.
