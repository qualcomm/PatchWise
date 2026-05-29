# Rule: readpath-widening-writer-locked

## Trigger

Patch widens a read path to dereference a cached pointer/field while sibling
teardown, work, IRQ, timer, HPD, or disconnect code writes/frees it under a lock.

## Must Check

- Did the patch add dereferences inside an existing `if (ctx->ptr)` or similar guard?
- Which writer/remover clears or frees that pointer, and under which lock?
- Does the widened read path hold the same lock/ref or otherwise pin lifetime?
- Can async work, IRQ, timer, hotplug, or disconnect race with the new dereference?

## Evidence Needed

- New dereference and old guard context.
- Writer/free site and its lock.
- Reader locking/refcount state and async entry points.

## Safe Dismissal

Dismiss only when reader and writer share locking, the object is refcounted/pinned,
or teardown is proven impossible while the read path runs.

## Finding Template

```text
[BUG] Read path dereferences writer-locked pointer without lifetime proof
File: <driver-path>:<new-deref>
Rule: readpath-widening-writer-locked
Evidence: <new deref, writer free site, and lock asymmetry>
Reasoning: <why guard does not prove pointer lifetime against teardown>
Impact: <UAF, NULL/stale dereference, or race on hotplug/disconnect>
Suggestion: <take writer lock, pin object, or restructure teardown/read path>
```

## Severity

Use `[BUG]` for reachable UAF/race; `[CONCERN]` when teardown reachability is not
fully proven but lock asymmetry is real.
