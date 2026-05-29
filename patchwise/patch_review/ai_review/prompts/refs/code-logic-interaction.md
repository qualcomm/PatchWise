<!-- Conditional fragment of code-logic.md (3c.4) — the diff shows multi-function/file patches with shared data, callbacks/notifiers/IRQs,
locking, or contract-changing refactors. Apply on top of refs/code-logic.md
base prose. -->

### 3c.4 Interaction Picture

For multi-function/file patches:
- Draw caller → callee chains to depth 2. If a callee is outside context files,
  attempt one on-demand `Read` under `<project_path>` within the budget: 6 targeted reads per patch;
  if unavailable, record `call chain ends at <callee>() — source not in context
  files (on-demand read attempted: <result>)` and do not guess behavior.
- Identify shared data accessed by multiple functions and confirm locking.
- Shared scratch objects: if paths construct commands/packets/descriptors in
  shared mutable storage, prove serialization covers both construction and
  handoff/submission; a lock only around the final queue write/doorbell is not
  enough.
- Alternate sources: if new route/PHY/lane/format state is set on the normal
  external-source path, also audit internal TPG, loopback, firmware-only, and
  synthetic-source paths. They must initialize/reset the new state and must not
  dereference sensor-only structures before proving a sensor-backed pipeline.
- Callbacks/notifiers/IRQs: confirm invocation context is compatible with locks
  and APIs. If context cannot be determined from diff/context files, file
  `[CONCERN]` asking for the guaranteed context.
- Callback lock nesting: if invoked while caller holds a lock, ensure callback
  and helpers do not reacquire the same non-recursive lock. For sibling-client
  dispatch, read registration/invocation path and model caller-held locks.

**Lock-coverage symmetry for a shared field.** When a patch adds or modifies a
field that is read or written under a lock on one path, audit *every* other
path that touches the same field — set, reset, clear, increment, decrement —
and prove each acquires the same lock, or that the unlocked access is provably
safe (single-threaded init, IRQs-off invariant, or the field is private to one
context). The recurring trap is set-under-lock / reset-without-lock asymmetry:
the success path mutates the field inside the lock, but an error/cleanup path
resets it without taking the lock.

**Bad-pattern shape (subsystem-agnostic):**

    spin_lock_irqsave(&ctx->lock, flags);
    ctx->flag = true;            /* set is serialized */
    ...
    spin_unlock_irqrestore(&ctx->lock, flags);
    ...
    return 0;
err_path:
    ctx->flag = false;          /* reset is NOT serialized — races the setter */
    return err;

This is exactly the misc/fastrpc v8 3/4 `cctx->audio_init_mem` case: set to
`true` under `spin_lock_irqsave(&cctx->lock)`, but reset to `false` at the
`err_invoke:` label with no lock, so a concurrent init on the same channel can
observe a torn first-send flag.

**Decisive evidence (all three required):**
(1) the locked access (quote the lock acquire + the field write/read it guards);
(2) the unlocked access to the *same* field on another path (quote the line and
its function/label, and show no matching lock acquire brackets it);
(3) a reachable concurrency: two threads / contexts that can hit the two paths
on the same object (name them — two userspace callers on one channel, IRQ vs
process, etc.).

**Valid dismissal proofs (cite source for each):**
- the unlocked path runs only in single-threaded init/teardown where no other
  context can touch the field (quote the serialization — single probe, bind
  mutex held by all callers, `suppress_bind_attrs`);
- the field is per-context/per-fd and never shared across the racing paths
  (quote the ownership);
- the unlocked site runs with the lock already held by its caller (quote the
  caller's acquire that brackets it);
- the field is only ever accessed with IRQs disabled / under the same single
  lock everywhere and this site is no exception (quote the invariant).

**Disqualified dismissals:**
- "the set path is correctly locked" without auditing the reset/clear path —
  locking one side of a field's mutation does not protect the other;
- "the reset is just cleanup" — cleanup racing a concurrent setter still tears
  the field;
- "concurrency is unlikely" — frequency does not remove the data race;
- "matches how the flag is set" without quoting a lock acquire on the reset
  path itself.

Severity: `[CONCERN]` when the torn field causes a logic error (lost
single-init guarantee, double-send, missed cleanup); `[BUG]` when it can drive
a NULL deref, double-free, or hardware misprogramming.


helpers with a helper, ops table, descriptor, or function pointer, prove:
- caller-visible contract changes: return/failure encoding, `NULL` vs `ERR_PTR`,
  side effects, ordering, resource ownership, cached state, PM/clock/ICC/OPP
  votes, DMA programming, platform capability handling;
- which old direct helpers remain and which indirect paths should use the new
  abstraction;
- all relevant paths checked: transfer/DMA modes, IRQ callbacks, probe/remove,
  runtime/system PM, error unwind, cached fast paths, and alternative execution
  modes;
- for each path, which descriptor/platform can reach it and whether the old
  helper remains valid;
- cached fast paths restore/revote/reprogram state the old code guaranteed;
- cross-patch stored pointers/ids/callback contexts name producer and first
  consumer patches before clearance.

Required call-path coverage matrix columns: `old helper`, `new abstraction`, `call path`,
`converted?`, `reason if not converted`, `affected descriptor/platform`. Include
every externally selectable mode, not only diff-visible paths. `N/A`,
`unchanged`, or `pre-existing` is valid only with proof that the new descriptor/
platform cannot reach that path or the old helper remains contract-compatible.
File `[BUG]` for the first reachable path using an incompatible old helper.

Matrix proof rules:
- Inspect both changed path and unchanged siblings/alternates; record source
  proof in `codebase audit: siblings ...`.
- For every alternative mode, name the concrete entrypoint routine and callees,
  or state the driver has no such routine. Generic "alternative path is safe"
  without a routine is a validator violation.
- A `not reached for <platform/descriptor>` row must name the selector proving
  unreachability (transfer-mode enum, capability bit, descriptor callback slot,
  `FIFO_IF_DISABLE`/`GENI_GPI_DMA`, etc.). Prove at entrypoint selection, not a
  downstream callee.
- A `not converted -> safe` row requires grepping the unconverted path for every
  abstracted-helper call, including nested calls. Prove safety per side effect,
  not per function; if any reachable side effect still depends on an
  incompatible old helper for the new platform, file `[BUG]`.

**Helper side-effect proof:** when claiming a replacement helper preserves,
restores, drops, or re-votes state, cite the exact call inside the helper body.
Do not infer from helper name, commit message, or sibling helper. If source/kdoc
says a side effect is intentionally omitted, treat the old caller's removed side
effect as missing unless another reachable path restores it before use.
**PM callback replacement:** replacing an entire suspend/resume body with one
helper requires an on-demand read of that helper source to verify every old side
effect still occurs. "Same series", "reasonable assumption", and helper-name
equivalence are not enough; if kdoc says a side effect is omitted (for example
performance-state restore), the caller must add the missing step.
