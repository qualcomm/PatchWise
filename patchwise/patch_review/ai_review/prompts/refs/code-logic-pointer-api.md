<!-- Conditional fragment of code-logic.md — the diff shows pointer-returning API calls or helper-populated pointer fields in the
diff (ERR_PTR/IS_ERR/PTR_ERR/_get/_alloc returning pointer types). Apply on top
of refs/code-logic.md §3c.2 Data-Flow Picture base prose. -->

#### Pointer-returning API call checklist

Apply to every pointer-returning call in the diff and helpers that fill
caller-owned pointer fields.
- Determine failure encoding from callee source/kdoc: `NULL` → `!ptr`,
  `ERR_PTR(errno)` → `IS_ERR(ptr)`, both → `IS_ERR_OR_NULL(ptr)`. Mixing guards
  is always `[BUG]`.
- If an `ERR_PTR` callee is checked with `if (!ptr)`, the guard is false and the
  bad pointer propagates; flag `[BUG]`. Propagate with `PTR_ERR(ptr)`, not a
  hard-coded `-ENOMEM` or `0` unless deliberately translated.
- Unchecked use of an `ERR_PTR`-capable result is `[BUG]`.
- Helper-populated pointer fields: prove the field invariant after helper return
  (valid, `NULL`/valid, `ERR_PTR`/valid, or both), enumerate all downstream
  dereferences/API uses, and verify each guard matches the invariant. If one
  platform/firmware leaves a sentinel, prove that platform cannot reach every
  later use or file the first reachable bad use.
- Failure-tolerant getter swap: if a patch removes explicit get+abort and
  delegates to a helper that tolerates missing resources, the old precondition is
  gone. Sweep every execution/transfer/runtime mode and deep callee chain using
  that field; prove each consumer guards the exact sentinel or is unreachable at
  the entrypoint selector. A claim that a mode is safe must include grep/source
  proof for that routine and callees, not just the diff.
- Callee source not in context: if failure encoding is undocumented and source
  is absent, attempt one on-demand `Read` under `<project_path>` within the
  6-read budget. If found, apply full severity; if missing/oversize/budget
  exhausted, record `unable to verify failure encoding for <callee>() — source
  not in context files (on-demand read attempted: <result>)` and downgrade to
  `[CONCERN]` rather than `[BUG]`. Known encodings need no read: `kzalloc`,
  `kmalloc`, `devm_kzalloc`, `devm_kmalloc` return `NULL`; `devm_clk_get`,
  `devm_regulator_get`, `kthread_run`, `kthread_create`, `ERR_CAST`, and
  `ERR_PTR` family return `ERR_PTR`.
