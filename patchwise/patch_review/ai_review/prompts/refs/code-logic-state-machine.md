<!-- Conditional fragment of code-logic.md (3c.3) — the diff shows state-machine / lifecycle / refcount / lock / kobject patterns. Apply on
top of refs/code-logic.md base prose. -->

### 3c.3 State-Machine / Lifecycle Picture

Apply when a patch changes object init/exit or probe/remove, refcounts
(`kref_*`, `atomic_*`, `get_device`/`put_device`, `kobject_*`), state flags,
locks, allocation/free, or lifecycle transitions. If none apply, write
`No lifecycle changes — N/A.` and skip this subsection.

For lifecycle objects, list states/transitions, locks, refcount get/put balance,
and whether any transition reaches uninitialized or freed objects. Then apply:
- **Flag reachability:** for boolean/enum flags gating branches or errors, trace
  all writers across files and prove the assumed state is reachable. Paired
  prepare/unprepare often makes error branches impossible; document invariants
  and apply the two gate questions: reachable, then harmful.
- **Sentinel/state validity:** magic safe/invalid values (`-1`, `0xff`,
  `UINT_MAX`, `INVALID`, `SAFE`, etc.) must be rejected before hardware/user
  action or map to a documented no-op. For pointer/missing-guard findings, trace
  from public entrypoint to dereference and honor prior open/prepare gates; a
  downstream function need not repeat a check if only reachable after that gate,
  unless another path bypasses it.
- **Missing-lock proof:** enumerate all exclusion mechanisms before filing:
  locks, flags under other locks, mode/state constraints, refs blocking entry,
  and prepare/unprepare architecture. File `[CONCERN]`/`[BUG]` only after all
  guards fail; otherwise record the non-obvious guard as positive evidence.
- **RCU / lockless lifetime:** when a patch touches `rcu_dereference`,
  `rcu_assign_pointer`, `list_for_each_entry_rcu`, `kfree_rcu`,
  `synchronize_rcu`, lockless lists, or comments claiming lockless access, prove
  readers hold `rcu_read_lock()` or another documented protection, writers use
  the matching publication primitive, and freeing waits for readers. File `[BUG]`
  for reachable use-after-free or unprotected dereference; otherwise record the
  exact protection and do not speculate.
- **Refcount/kobject/device lifetime:** for `refcount_t`, `kref`, `atomic_t` used
  as a lifetime counter, `get_device`/`put_device`, `kobject_get`/`put`, and
  release callbacks, prove a reference is acquired before publication/use and
  dropped on every exit. Prefer `refcount_t`/`kref` over raw `atomic_t` for
  object lifetime unless source proves saturation/overflow is impossible. Never
  free a kobject/device directly after final put; ownership must end in the
  release callback.
- **Error-branch reachability:** before filing on a callee's non-zero return,
  read that callee and enumerate returns. If it always succeeds, the branch is
  unreachable; do not file, though a comment may be suggested.
- **Success without required resource:** if init/probe/setup creates or expects a
  required child/resource, tears it down or finds it absent, and still returns
  success, trace consumers. If later code falls back to a broader/default device,
  skips required secure setup, or continues degraded, file `[BUG]`.
- **Stale software mirrors:** after unregister/free/invalidate, clear mirrors
  (`ptr = NULL`, state reset, count decrement) unless a stronger invariant proves
  no later observer. Stale mirrors steering reload/error/teardown are bugs even
  for devm-managed hardware resources.
- **Alternate-path state reset:** when a patch adds or modifies a field that is
  set on one operational path (e.g. sensor-linked, external-source, mode-A) and
  a different operational path (e.g. internal test-pattern generator, loopback,
  mode-B, fallback) can also reach the consumer of that field, prove the alternate
  path either (a) resets the field to its default/safe value, or (b) the consumer
  is guarded by a check that the field is valid for the current path.

  **Bad-pattern shape (subsystem-agnostic):**

      /* Path A sets mode-dependent state */
      link_setup(sensor_pad):
          ctx->mode_field = derive_from_sensor(cfg);  /* e.g. PHY type, lane count, format */

      /* Path B (alternate source) does NOT touch ctx->mode_field */
      link_setup(alt_pad):
          ctx->lane_count = ...;
          /* mode_field retains Path-A's value from a previous stream session */

      /* Consumer reads mode_field unconditionally */
      configure_hw():
          reg |= ctx->mode_field << HW_BIT;  /* stale if current path is B */

  The alternate path can be: internal test/pattern generator, loopback,
  diagnostic mode, firmware-fallback, a different PHY type (e.g. mode-A vs
  mode-B), a different bus (SPI fallback from QSPI), or any mutually-exclusive
  operational mode that shares the same hardware configuration register set.

  **Decisive evidence (all three required):**
  (1) the field written on path A (name it, quote the assignment);
  (2) the alternate path B that can reach the consumer without going through
  path A's assignment (quote the path-B entry point and show it does not write
  the field);
  (3) the consumer that reads the field and acts on it (quote the read site and
  the hardware/software effect).

  **Valid dismissal proofs (cite source for each):**
  - the field is zero-initialized at allocation time (`devm_kzalloc` / `= {}`)
    AND zero is the correct value for path B (quote both the allocator and the
    consumer's behaviour when the field is zero — zero being "the default" is
    not enough if the default is path-A's mode);
  - path B explicitly resets the field (quote the reset line);
  - the consumer is gated by a path check (e.g. `if (is_sensor_linked)`) that
    prevents the read when path B is active (quote the guard);
  - the two paths are mutually exclusive at the hardware level and a mode switch
    requires a full re-initialization that zeroes all state (quote the re-init
    call on mode switch).

  **Disqualified dismissals:**
  - "the field defaults to zero" without showing zero is correct for path B —
    if path A previously set it to non-zero and then path B is selected, the
    field is NOT zero (it retains path A's value); only fresh allocation zeros it;
  - "path B is rarely used" — frequency does not affect correctness; the hardware
    register is written regardless of how often the path runs;
  - "the driver doesn't support that alternate path yet" — if the code under
    review adds the field to a consumer that IS reachable from path B (even if
    path B was pre-existing), the stale-read hazard exists;
  - "same as existing driver" without quoting the existing driver's reset site.

  Severity: `[CONCERN]` when the stale value programs incorrect hardware state
  (wrong PHY type, wrong lane count, wrong DMA channel, wrong clock mode) even
  if no crash results; `[BUG]` when the stale value can cause a NULL deref,
  out-of-bounds access, or hardware lockup on the alternate path.
- **Failed-start / failed-resume state contamination:** if start/resume/activate
  updates cached rates, enabled flags, ownership, counters, or accounting before
  all setup succeeds, trace failure exit and next fast path. If later code trusts
  stale state and skips real restore/start, file `[BUG]`.
- **Lifecycle workflow matrix:** whenever a patch changes a lifecycle entry or
  exit path (`probe/remove`, `open/release`, `prepare/unprepare`,
  `start/stop`, `enable/disable`, `alloc/free`, `register/unregister`,
  `runtime_resume/runtime_suspend`, IRQ/workqueue/timer setup/teardown, or a
  callback dispatch wrapper), build a matrix before writing `SAFE`:
  (1) every entry outcome (success, busy/no-op, each non-success return,
  fallback/default path); (2) the state/resource/session owner established by
  that outcome; (3) the paired exit/cleanup path that must run; and (4) the
  guard that selects that exit path. A cleanup path may early-return only when it
  proves it owns the same session/resource that the entry path acquired. File
  `[BUG]` when any entry outcome can acquire or fall back to owner B while the
  paired exit can return through owner A, leaving B's flag, ref, lock, wake IRQ,
  buffer, DMA mapping, clock/PM vote, or registration uncleared.

  **Required proof for dismissals:** quote the source-backed ownership token used
  by both sides (for example `drvdata->reading`, `foo->prepared`, a stored
  backend selector, a refcount, or a resource pointer) and show every relevant
  entry outcome reaches the matching cleanup. Configuration facts such as
  `irq_enabled`, mode flags, compatible strings, ops-pointer presence, descriptor
  presence, or DT resource availability are not ownership proof unless both entry
  and exit paths test that same fact as the session/resource owner.

  **Paired callback backend subtype:** if an open/prepare/start wrapper first
  tries an optional backend callback and then falls back to the normal backend on
  a nonfatal error, the paired release/unprepare/stop wrapper must choose cleanup
  from the same per-session backend state. Do not clear this by saying the pair is
  "protected by a flag" unless the flag is the same session owner used by both
  wrappers. Valid dismissals must quote either the per-session backend selector
  or the optional backend's `!prepared`/`!reading` rejection path that forces
  normal cleanup to run for sessions the optional backend did not prepare.
- **Driver/firmware synchronization:** if a field selects firmware-visible state
  (core, queue owner, mode, region, stream id, etc.) and can change after its
  one-time programming point without reprogramming, file `[BUG]`.
- **Early-return / fallback unwind audit:** for probe, parse, and helper setup,
  name acquisition, publication into cleanup/device/provider lists, and every
  return between them. Cleanup that walks only published objects does not cover
  unpublished locals. For new parser → legacy fallback flows, release or reuse
  first-parser resources before fallback. Record relied-on helper bodies under
  `codebase audit: callees ...`; Step 3f may reuse reads, but Step 3c must prove
  ownership handoff. Dismiss only when each early return releases exactly once or
  transfers ownership to a named later cleanup path.
- **Async teardown before free:** when changed state is reachable from
  workqueues, delayed work, timers, hrtimers, tasklets, completions, kthreads,
  threaded IRQs, or callbacks, prove teardown cancels/drains/stops the async
  source (`cancel_work_sync`, `del_timer_sync`, `hrtimer_cancel`, `tasklet_kill`,
  `kthread_stop`, completion handoff, framework unregister, etc.) before freeing
  handler-reachable state. File `[BUG]` for reachable UAF; dismiss only with the
  cancel/drain site and ordering proof.
- **Module lifecycle mutual exclusion:** before alleging a race between
  probe/remove cleanup and normal data path, identify the data-path precondition,
  whether it holds a module/device/framework reference, and whether remove needs
  refcount zero. If active data path implies refcount > 0 and remove needs zero,
  the race is structurally impossible; note the module-refcount protection. This
  does not replace per-function lock/flag analysis and does not apply to internal
  data-path races. Built-in (`obj-y`) drivers lack module-refcount protection;
  sysfs unbind can still trigger `.remove`, so rely on locks/flags only.
