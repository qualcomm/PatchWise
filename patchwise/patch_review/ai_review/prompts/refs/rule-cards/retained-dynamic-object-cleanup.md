# Rule: retained-dynamic-object-cleanup

## Trigger

Code stores a dynamically allocated or framework-created object in a retained
static/global/descriptor/template pointer and changes cleanup, remove, or probe
retry paths.

## Must Check

- Is the object retained beyond the local probe/setup scope?
- Does every cleanup/error/remove path that frees or unregisters the object also clear the retained pointer?
- Can probe retry, rebind, or a second instance observe the stale pointer?
- Is ownership transferred to a framework that clears or invalidates the pointer for the driver?

## Evidence Needed

- Allocation/creation site and retained pointer assignment.
- Free/unregister/cleanup sites on error and remove paths.
- Re-probe/rebind path that tests or reuses the retained pointer.

## Safe Dismissal

Dismiss only when the retained pointer is cleared on every free path, ownership
is transferred and no stale pointer remains visible, or the object lifetime is
static and never freed.

## Finding Template

```text
[BUG] Cleanup frees retained dynamic object without clearing pointer
File: <driver-path>:<cleanup-or-assignment>
Rule: retained-dynamic-object-cleanup
Evidence: <allocation, retained store, free path, and missing clear>
Reasoning: <how retry/rebind/second instance reuses freed object>
Impact: <use-after-free, double free, or stale framework object>
Suggestion: <clear retained pointer on all cleanup paths or avoid retained dynamic storage>
```

## Severity

Use `[BUG]` for reachable retry/rebind stale pointer; `[CONCERN]` when reuse is
plausible but depends on framework sequencing.
