# Rule: cleanup-style-consistency

## Trigger

C code in a function uses both modern scope-based cleanup
(`__free(...)`, `scoped_guard(...)`, `guard(...)`, `DEFINE_FREE(...)`) and
traditional `goto err_*`/`goto out_*` unwinding for the same set of resources.

## Must Check

- Does each resource have exactly one ownership/cleanup mechanism within the
  function — either scope-based (`__free`/`scoped_guard`) or explicit goto
  unwinding — never both for the same pointer?
- Can a `goto err_*` jump *over* the declaration that introduced
  `__free(kfree)`-style cleanup, leaving an uninitialized scope-cleanup
  pointer in scope for the goto target?
- Could the same pointer be freed twice — once by `__free` on scope exit and
  once by an explicit `kfree`/`*_release` reached via `goto`?
- Is the choice consistent with neighbouring code in the same file/subsystem,
  so a future maintainer can reason about ownership at a glance?

## Evidence Needed

- The scope-cleanup declaration (`T *p __free(kfree) = ...`) and every
  `goto err_*`/`out_*` target in the same function.
- Any explicit free/release for the same pointer reachable via the goto.
- Surrounding-function style for comparable functions in the file.

## Safe Dismissal

Dismiss when source proves each resource has exactly one cleanup mechanism
(scope-based OR goto, not both), no goto skips a `__free` declaration, and the
mixed style is intentional (e.g. one resource scope-cleaned, a different
resource goto-cleaned, with no overlap).

## Finding Template

```text
[CONCERN] Mixed scope-based and goto-based cleanup for the same resource
File: <path>:<function>
Rule: cleanup-style-consistency
Evidence: <__free/scoped_guard decl + goto target with explicit free/release>
Reasoning: <which path can double-free, leak, or skip cleanup>
Impact: <double-free, leak, ambiguous ownership for future maintainers>
Suggestion: <pick one mechanism; if scope-based, drop the goto unwind for that resource>
```

## Severity

`[BUG]` for a proven double-free or use-after-free across the two cleanup
mechanisms; `[CONCERN]` for ambiguous ownership without a proven double-path;
`[MINOR]` for purely stylistic mixing with no resource overlap.
