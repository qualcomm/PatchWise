# Rule: stored-stack-address-escape

## Trigger

A helper stores a caller-provided pointer or the address of a local/compound
literal into a device object, callback context, work item, timer, notifier,
`platform_data`, or any structure that outlives the current stack frame.

## Must Check

- Is the stored pointer the address of a stack local, function-local array, or compound literal that dies at return?
- Does any deferred consumer (workqueue, timer, IRQ, notifier, DMA, framework callback, deferred probe) read it after the frame is gone?
- If helper and consumer are in different patches/functions, is reachability proven via the series summary plus one targeted read?
- Is there an immediate deep copy or a proven longer lifetime (heap/devm/static) for the pointee?

## Evidence Needed

- The assignment storing the address and the lifetime of the pointee.
- The earliest consumer that reads the stored pointer.

## Safe Dismissal

Dismiss when the pointee is heap/devm/static, or the value is fully consumed
before the storing frame returns, or a deep copy is made.

## Finding Template

```text
[BUG] Short-lived address stored in longer-lived state
File: <path>:<line>
Rule: stored-stack-address-escape
Evidence: <address-of-local stored into long-lived field + consumer site>
Reasoning: <why the pointee is dead when the consumer runs>
Impact: <use-after-scope/stack UAF, corruption when consumer dereferences>
Suggestion: <deep-copy the data or store a heap/devm-owned pointer>
```

## Severity

`[BUG]` for a reachable consumer of a dead stack address; `[CONCERN]` when
consumer reachability spans patches and is not fully proven.
