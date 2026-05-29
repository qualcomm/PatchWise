## Step 3c — Code Logic Mapping

Before writing any review findings, build a complete picture of the logic
introduced or changed by the patch.  Do this for **every function** that is
added or modified.  The goal is to understand *what the code does* before
judging *whether it does it correctly*.

**Mandatory surrounding-code audit**: for every patch with function-level code
changes, Step 3c is not complete until the review has inspected and recorded
all of these beyond-the-diff facts:
- the concrete entrypoint, callback registration, selector, descriptor table,
  or dispatch site that makes the changed code reachable;
- the concrete callee/helper bodies whose failure contract or side effects the
  review relies on; and
- the sibling or alternate execution paths that can still reach the same state,
  abstraction, or hardware mode even if the diff touched only one path.

Record this proof in the Code Logic Maps `<pre>` block using these exact
labels:
`codebase audit: entrypoints ...`
`codebase audit: callees ...`
`codebase audit: siblings ...`
Write `none` only when you have inspected the surrounding code and verified the
bucket truly does not exist.  Statements such as "obvious from diff",
"self-contained", or "reasonable assumption" are not valid substitutes.

### 3c.1 Control-Flow Picture

**Scope gate (apply first)**: if the patch contains no C function changes
(e.g. pure DTS, YAML binding, Kconfig, Makefile, or comment-only patch),
write `"No function-level changes — N/A."` in the Code Logic Maps `<pre>` block
and skip 3c.1–3c.5 entirely.  Do not attempt to trace control flow through
DTS nodes or YAML properties.

For each changed function, trace every execution path through the diff:
- Identify all entry conditions and guard clauses (`if`, early `return`,
  `goto`).
- Map the happy path from entry to successful return.
- Map every error / exceptional path: what triggers it, what cleanup it
  performs, and where it exits.
- Note any loops: loop variable, termination condition, loop body side-effects,
  and whether the loop can run zero times.
- Note any `fallthrough` in `switch` statements and confirm it is intentional.
- **`switch` case coverage**: if `<project_path>/tmp/patch_<N>_build.txt` contains a
  `-Wswitch` warning for a file this patch touches, report it in the Issues
  section — a missing `default:` or unhandled enum value in new/changed
  `switch` code is a correctness issue, not style.
- **Diagnostic coverage check**: enumerate every `dev_err` / `dev_warn` /
  `pr_err` call site and the exact set of conditions that reaches it.  Apply
  Gate 1 first: confirm both call sites actually fire for the same triggering
  condition (not merely for related but distinct error scenarios).  If Gate 1
  passes, flag redundant diagnostics as `[MINOR]` — duplicate messages
  in `dmesg` are a real usability problem and harder to bisect; `[NIT]` understates
  the impact.
- **Static-analysis attribution gate**: for sparse/checkpatch/compiler warnings,
  compare the warning location with the changed lines and surrounding before/after
  context.  File the warning only when the patch introduces it, touches the
  warned code, or changes the API/struct contract that makes old code newly
  wrong.  If the warning is in unchanged legacy code, mention it only as context
  or false-positive evidence, not as a patch finding.

Produce a plain-text control-flow summary per function, e.g.:
```
foo_init():
  1. Validate args → return -EINVAL if NULL
  2. Allocate buf (kzalloc) → goto err_alloc on failure
  3. Register device → goto err_reg on failure
  4. Return 0
  err_reg:  free buf
  err_alloc: return -ENOMEM
```

**Annotation consistency rule (mandatory)**:
Inline severity labels written inside Code Logic Maps (`← BUG`,
`← MINOR`, `← NIT: see below`, etc.) and cross-reference phrases in
Hardware Engineering Notes (*"see bug below"*, *"see [MINOR] below"*)
must use the same severity class as the finding filed in the Issues
section for that commit.

**Important — analysis order vs. HTML order**: the HTML output places Code
Logic Maps *before* the Issues section, but the analysis must proceed in the
opposite order: finalize all finding severities first, then write the Code
Logic Maps annotations.  Never write severity annotations into the Code Logic
Maps prose before the Issues section severity is finalised.  A mismatch
between the inline annotation and the Issues card is a self-audit error and
must be corrected before the commit block is written to the file.

### 3c.2 Data-Flow Picture

For each changed function, trace how data moves:
- Identify all inputs (parameters, global/static state, hardware registers,
  user-space buffers).
- Follow each input through transformations (arithmetic, bitwise ops, casts,
  struct field assignments).
- Identify all outputs (return value, pointer writes, global/static state
  mutations, hardware register writes, callbacks invoked).
- Flag any input that reaches a sensitive sink (memory allocation size,
  array index, copy_to/from_user length, hardware register) without
  validation — these are prime correctness and security targets.

#### Register read data-flow checklist

Apply whenever a function reads or writes a hardware register via direct
MMIO (`readl_relaxed`, `readl`, `readq`, `writel_relaxed`, `writel`,
`writeq`, `ioread32`, `iowrite32`, etc.) **or** via `regmap`
(`regmap_read`, `regmap_write`, `regmap_update_bits`, and related
`regmap_*` calls).  Both access classes follow the same data-flow rules.

- **Width match**: is the local variable type wide enough for the register?
  Use `u32` for 32-bit registers, `u64` for 64-bit.  A narrower type
  silently truncates bits; a signed type (`int`) is a style violation and
  can cause subtle bugs if the value is later used in signed arithmetic or
  widened to a 64-bit signed type.
- **Sign match**: trace every use of the register value after the read.
  If the value is stored in a signed type, check whether it is ever:
  (a) used in signed arithmetic or a signed comparison, or
  (b) widened to a larger signed type (e.g. assigned to `long` or `s64`).
  If neither applies, the mismatch is a style issue (`[NIT]`), not a bug —
  C99 §6.3.1.3 guarantees that converting a negative `int` back to `u32`
  preserves the bit pattern.  Only file `[BUG]` if a signed intermediate
  value reaches signed arithmetic, a signed comparison, or sign-extension
  across a wider type.
- **Field extraction**: are `FIELD_GET()` / shift+mask used
  correctly?  Confirm the mask covers exactly the documented bit range and
  the shift matches.  (`BMVAL()` is a Qualcomm-internal macro not present in
  upstream kernel headers — flag its use in an upstream patch as `[CONCERN]`.)
- **Write-back (read-modify-write)**: confirm the read and write use the
  same register offset, and that reserved bits are preserved — masked off
  before OR-ing new values in, and not accidentally cleared when AND-ing a
  complement mask to clear target bits.  A wrong complement (e.g. wrong
  shift or mask width) silently corrupts adjacent fields.
- **Endianness**: confirm `readl_relaxed` / `writel_relaxed` (little-endian
  MMIO) is appropriate for the bus.  Flag if `__raw_readl` or `ioread32be`
  would be needed instead.
- **Raw regmap endianness**: when `regmap_raw_read()` / `regmap_bulk_read()`
  returns register words from a little-endian hardware or firmware protocol, do
  not let the caller treat the output buffer as CPU-endian `u16`/`u32`/`u64`.
  Require `__le16`/`__le32`/`__le64` temporaries and `leXX_to_cpu()` before the
  value feeds status decoding, bitfields, or API outputs.
- **Barrier sufficiency**: confirm `readl_relaxed` (no ordering guarantee)
  is appropriate at this call site, or whether `readl` (implicit barrier)
  is required.

#### Wire protocol struct checklist

Apply when a changed function sends a C struct to firmware, hardware, another
processor, USB/I2C/SPI/GLINK/RPMSG, or any packed on-wire protocol.

- **Zero-init before field assignment**: stack-allocated protocol structs with
  reserved members, implicit padding, or fields not assigned on every path must
  be initialized with `= {}`, `= {0}`, or `memset()` before individual fields are
  filled.  Sending uninitialized reserved bytes leaks stack data and can break
  strict firmware parsers.
- **Full-field coverage**: enumerate every member in the struct definition, not
  only the fields visible in the diff.  If any transmitted member is omitted,
  confirm it is intentionally zero, documented reserved space, or assigned by a
  helper before send.

#### Pointer-returning API call checklist

Apply to every call in the diff that stores a pointer return value, and to
helpers that write pointer-valued fields into caller-owned structs:

- **Determine the failure encoding first**: read the callee's return
  statements (or its kernel-doc).  Three cases exist:
  - Returns `NULL` on failure → check with `!ptr`.
  - Returns `ERR_PTR(errno)` on failure (never `NULL`) → check with
    `IS_ERR(ptr)`.
  - Can return both `NULL` and `ERR_PTR` (rare) → check with
    `IS_ERR_OR_NULL(ptr)`.
  Mixing any of these is always `[BUG]`.
- **`IS_ERR` vs `!ptr` mismatch**: if the callee returns `ERR_PTR(...)`
  and the caller checks `if (!result)`, the guard is always false — an
  error pointer is non-NULL — so the error silently bypasses cleanup and
  the bad pointer propagates.  Flag `[BUG]`.
- **`PTR_ERR` extraction**: confirm the caller propagates the error code
  with `PTR_ERR(ptr)`, not a hard-coded `-ENOMEM` or `0`.  Hard-coded
  codes discard the real error and hide the root cause.
- **Unchecked use**: if the return of an `ERR_PTR`-capable function is
  used without any `IS_ERR()` guard, flag `[BUG]`.
- **Helper-populated pointer fields**: when a new or reused helper stores a
  pointer into a caller-owned struct field, ask:
  1. What values can the field hold after the helper returns: always valid,
     `NULL`-or-valid, `ERR_PTR`-or-valid, or `NULL`/`ERR_PTR`/valid?
  2. Which downstream paths dereference the field, call a method through it,
     or pass it to another API such as clock, regulator, PHY, DMA, or firmware
     helpers?
  3. Does each downstream path use the guard that matches the field invariant:
     `!field`, `IS_ERR(field)`, or `IS_ERR_OR_NULL(field)`?
  4. If one firmware type or platform may leave `NULL`/`ERR_PTR` in the field,
     what invariant prevents that same platform from reaching every later use?
  File `[BUG]` for the first reachable downstream use that can receive
  `NULL`/`ERR_PTR` where a valid pointer is required.
- **Failure-tolerant getter swap**: when a patch *removes* an explicit
  resource-get plus failure abort (e.g. `x = get_resource(); if (IS_ERR(x))
  return ...;`) and instead delegates acquisition to a helper that
  *intentionally tolerates* a missing resource on some platform (firmware-
  managed, ACPI, optional-by-design), the field is now `NULL`/`ERR_PTR` on
  that platform with no early abort.  Treat the removed guard as a deleted
  precondition: enumerate every later use of that field on the tolerated
  platform and confirm each one either re-checks the sentinel or is
  unreachable there.  A common trap is a downstream API that treats `NULL` as
  a no-op but dereferences `ERR_PTR` (or vice-versa) — verify the *exact*
  sentinel the helper leaves matches what every consumer guards against.
  Sweep *every* execution/transfer mode that touches the resource, not only
  the one the patch converts — parallel modes are independent consumers of
  the same helper and may reach it through a different routine.  Do not
  accept a "this mode does not use the resource / does not call the helper
  at all" claim unless you have grepped that routine and its callees for
  the helper and shown there is no nested call site; the absence must be
  proven, not assumed from the diff.  File
  `[BUG]` for the first reachable consumer that can receive the tolerated
  sentinel without a matching guard, even if the diff only touched the probe
  path and the consumer lives in an unchanged transfer/runtime path.
  **Deep callee tracing**: "consumer" includes indirect consumers reached
  through any chain of intermediate function calls — not only code that
  directly names the field.  When a function passes the field to a helper,
  and that helper forwards it again (e.g., resource → wrapper → low-level
  API), follow the chain until either a guard is found or an unguarded
  dereference is proven.  Use on-demand reads if the intermediate callee is
  outside context files.  A common pattern: probe delegates resource
  acquisition to a shared helper that tolerates absence, but a transfer-path
  routine passes the same field through multiple layers that assume validity.
- **Callee source not in context files**: if the callee's source is not
  among the provided context files and its failure encoding is not
  documented in kernel-doc, you MUST first attempt **one** on-demand
  `Read` of the callee's defining file under `<project_path>` (see
  `core.md` Step 2 budget: 6 targeted reads per patch).  If the read
  succeeds and reveals the failure encoding, apply the full
  `IS_ERR` / `!ptr` mismatch check at full severity (do not downgrade).
  Only when the file is missing, exceeds the size cap, or the budget is
  exhausted, note `"unable to verify failure encoding for
  <callee>() — source not in context files (on-demand read attempted:
  <result>)"` and treat the finding as `[CONCERN]` rather than `[BUG]`.
  Exception — the following well-known
  APIs have unambiguous failure encodings and do not require the source:
  `kzalloc`, `kmalloc`, `devm_kzalloc`, `devm_kmalloc` → return `NULL`;
  `devm_clk_get`, `devm_regulator_get`, `kthread_run`, `kthread_create`,
  `ERR_CAST`, `ERR_PTR` family → return `ERR_PTR`.  For these, apply the
  full `IS_ERR` / `!ptr` mismatch check as if the source were available.

### 3c.3 State-Machine / Lifecycle Picture

Apply this sub-section when the patch adds or modifies any of the following:
(a) object init/exit or probe/remove paths,
(b) reference count operations (`kref_get/put`, `atomic_inc/dec`, `get_device/put_device`, `kobject_get/put`),
(c) state-flag writes or reads that gate a branch or an error return,
(d) lock acquisition/release sequences, or
(e) object allocation/free paths.
If none of (a)–(e) apply, write `"No lifecycle changes — N/A."` and skip this sub-section.

When the patch touches objects with a lifecycle (devices, buffers, locks,
reference counts, state flags):
- List all states the object can be in and the transitions the patch adds or
  modifies.
- Confirm every transition is guarded by the correct lock.
- Confirm reference counts are incremented before use and decremented on every
  exit path.
- Confirm no state transition is reachable from an uninitialised or
  already-freed object.
- **For every boolean/enum flag that gates an error return or a branch**:
  trace all writers of that flag across all functions and files, and confirm
  whether the flag can actually be in the assumed state at the call site in
  question.  Paired prepare/unprepare functions often enforce invariants
  implicitly (e.g. a store function returning `-EBUSY` while a flag is set),
  making certain error conditions unreachable.  Document the invariant
  explicitly rather than assuming the worst.  Then apply the two-part gate
  from the Gate Rules section: (1) is the condition reachable? (2) if reachable,
  is the resulting behavior actually harmful?  A no-op write or intentional
  omission managed by a per-instance field elsewhere is not a bug.
- **Sentinel/state validity**: if an error path writes a magic value (`-1`,
  `0xff`, `UINT_MAX`, `INVALID`, `SAFE`, etc.) to force a safe or invalid state,
  trace every downstream consumer before accepting the comment.  The sentinel
  must either be explicitly rejected before hardware/user-visible action or map
  to a documented no-op state; otherwise flag the first harmful consumer path.
  For pointer-dereference and missing-guard findings specifically: trace the
  full call chain from the public entry point (file operation, sysfs callback,
  interrupt handler) to the dereference site and confirm whether a prior gate
  in the chain (e.g. an open/prepare function that returns an error) makes the
  condition unreachable before filing.  A function that is only reachable after
  a successful open/prepare step does NOT need to repeat the same NULL or
  validity check that the open/prepare already enforces — the asymmetry is
  intentional and correct.  Only file a finding if no such entry-point gate
  exists, or if the function is reachable via a second call path that bypasses
  the gate.
- **Missing-lock findings — enumerate ALL exclusion mechanisms before filing**:
  Before concluding that a shared resource is accessed without adequate
  synchronisation, identify every mechanism — across all drivers and files
  involved — that could provide equivalent mutual exclusion.  Locks are not the
  only valid guard: a boolean flag set under a different lock, a device-mode or
  state constraint, a reference count that blocks concurrent entry, or an
  architectural invariant enforced by a prepare/unprepare pair can all provide
  the required exclusion.  Only file a [CONCERN] or [BUG] if, after tracing all
  such mechanisms, no adequate exclusion exists.  If a non-obvious guard is in
  place, document it as a positive design note instead.
- **Error-path concerns — verify callee return-value reachability before filing**:
  Before filing a concern about an error branch (e.g. "fallthrough when callee
  returns non-zero"), read the callee's body and enumerate every return path.
  If all return paths return success, the error branch is unreachable dead code —
  do NOT file a concern.  Document the invariant explicitly and, if it aids
  future maintenance, suggest adding a comment in the code.  Apply this check to
  every callee whose return value gates a branch under review.
- **Module lifecycle mutual exclusion — check before filing races involving
  probe/remove and normal data-path operations**: Linux module reference
  counting makes probe/remove callbacks and active data-path operations
  *structurally mutually exclusive*.  `module->remove()` / `platform_remove()`
  only runs after the module refcount reaches zero (rmmod is proceeding with
  no users).  Any data-path operation that reaches a code path inside a module
  holds a module reference (`try_module_get()` via the driver core), keeping
  refcount > 0 and making rmmod return `-EBUSY`.  This applies broadly: any
  driver that installs a module-level global hook or ops pointer at probe time
  and clears it at module exit falls under this rule (e.g. input drivers
  registering event handlers, sound drivers registering PCM ops, USB drivers
  registering URB callbacks, platform drivers installing subsystem callbacks).
  **Before filing any [CONCERN] or [BUG] about a race between a remove/cleanup
  path and a new data-path caller:**
  1. Identify what the data-path operation requires in order to proceed (e.g.
     a device must be in an active/enabled state, a session must be open, a
     subsystem path must be established, an interface must be connected).
  2. Determine whether satisfying that requirement causes the Linux driver core
     to hold the module's reference count > 0 (e.g. an open() on the module's
     device node, an active pm_runtime reference, a subsystem framework holding
     the driver bound, a bus framework holding a device reference).
  3. Determine whether remove/cleanup requires the module to be inactive
     (refcount == 0).
  4. If (2) and (3) are both true, the two conditions are mutually exclusive —
     the race is structurally impossible.  Dismiss the finding and note the
     module-refcount protection as a positive design element instead.
  Note: this check is *additional* to, not a replacement for, the per-function
  flag/lock analysis.  It applies specifically to alleged concurrency between
  `probe`/`remove` and normal data-path paths, not to internal races within the
  data path itself.
  **Built-in drivers (`obj-y`) caveat**: this mutual-exclusion argument relies
  on module reference counting, which does not apply to built-in drivers.  For
  built-in code, there is no *module reference count* protection — but the
  `.remove` callback can still be triggered via sysfs driver unbind
  (`echo -n <device> > /sys/bus/platform/drivers/<driver>/unbind`), so the
  locking and flag analysis remains mandatory.  The `probe`/`remove` vs.
  data-path race analysis must rely solely on per-function locking and flag
  invariants rather than module-refcount protection.

### 3c.4 Interaction Picture

When the patch spans multiple functions or files:
- Draw the call graph for new/changed call sites (caller → callee chain).
  **Depth limit**: trace to depth 2 (direct callee and one level below).
  If a callee at any level is outside the provided context files, attempt
  **one** on-demand `Read` of its defining file under `<project_path>`
  (subject to the 6-read budget in `core.md` Step 2) before stopping.
  If the on-demand read succeeds, continue tracing within the same depth
  limit; if it fails (missing file, oversize, budget exhausted), stop and
  note `"call chain ends at <callee>() — source not in context files
  (on-demand read attempted: <result>)"`.
  Do not guess the behaviour of callees whose source remains unavailable.
- Identify shared data structures accessed by more than one function and
  confirm consistent locking.
- Note any callbacks, notifiers, or interrupt handlers introduced and confirm
  their context (process / softirq / hardirq) is compatible with the locks and
  APIs used inside them.  If the invocation context cannot be determined from
  the diff and the provided context files (e.g. a function pointer registered
  with a framework that can fire from variable contexts), flag `[CONCERN]` and
  ask the author to confirm the guaranteed invocation context.
- **Callback lock nesting**: when a callback is invoked while the caller holds a
  lock, verify the callback and every helper it calls do not acquire that same
  non-recursive lock.  For callbacks that dispatch to sibling clients, read the
  registration/invocation path and model caller-held locks before deciding the
  callback is safe.
- **Contract-changing refactor audit**: when a patch replaces open-coded
  logic or direct helper calls with a helper, ops table, descriptor, or
  function pointer, ask these questions before accepting equivalence:
  1. What caller-visible contract changed: return/failure encoding,
     `NULL` vs `ERR_PTR`, side effects, ordering, resource ownership, cached
     state, PM/clock/ICC/OPP votes, DMA programming, or platform capability
     handling?
  2. Which old direct helper calls still exist after the patch, and which
     indirect paths should now use the new abstraction?
  3. Have all relevant call paths been checked: all transfer/DMA modes, IRQ
     callbacks, probe/remove, runtime PM, system PM, error unwind, cached
     fast paths, and any alternative transfer/execution modes the driver
     supports?
  4. For each path, which descriptor/platform can reach it, and is the old
     helper still valid for that descriptor/platform?
  5. If a cached fast path can skip work, who restores/revotes/reprograms the
     state that the old code guaranteed before the skip?
  Required evidence: record a call-path coverage matrix with `old helper`,
  `new abstraction`, `call path`, `converted?`, `reason if not converted`, and
  `affected descriptor/platform`.  The matrix is not complete until every
  externally selectable mode is covered (not just the path visible in the
  diff — every alternative execution path must appear as a row).  `N/A`,
  `unchanged`, or `pre-existing` is acceptable only when the row also proves
  the newly added descriptor/platform cannot reach that path or that the old
  helper remains contract-compatible for that descriptor/platform.  File
  `[BUG]` for the first reachable path that still uses an old helper
  incompatible with a newly supported platform, even when a sibling path was
  converted correctly.
  As part of the mandatory surrounding-code audit, the matrix must cross-check
  both the changed path and every unchanged sibling or alternate path that can
  still reach the same abstraction.  Do not clear a finding until the sibling
  paths have been inspected from source and recorded in the `codebase audit:
  siblings ...` line.
  For every alternative execution mode in scope, the matrix must name the
  concrete entry-point routine for that mode and its current callees, or
  explicitly declare that the driver has no such routine.  A generic
  "alternative path is safe" sentence without a named routine is a validator
  violation.
  A `not reached for <platform/descriptor>` row is only valid when it also
  names the selector that keeps the entry-point unreachable for that platform
  (for example a transfer-mode enum, capability bit, descriptor callback slot,
  or init-time condition such as `FIFO_IF_DISABLE` / `GENI_GPI_DMA`).  It is
  not enough to say the nested helper is "not called directly" or belongs to a
  "standard path" if the entry-point routine itself is still present and the
  new platform can select that mode.  Prove unreachability at the entry-point
  selection site, not at a downstream callee.
  A `not converted -> safe` row is only valid after you grep the *unconverted*
  path for **every** call site of the abstracted helper, not just the call the
  diff touched.  When a series routes one caller through a new abstraction but
  leaves a sibling caller on the old helper, that sibling is unsafe if it still
  reaches the old helper anywhere in its body — directly or through a nested
  call — and the new descriptor/platform can select it.  Prove safety per
  *side effect*, not per function: a row may show one concern (e.g. buffer or
  descriptor setup) is untouched while a different concern handled by the
  same old helper still runs the incompatible code.  Do not let "the
  alternative path is unchanged" stand in for "every side effect the old
  helper performed is unchanged."  If any
  reachable side effect of the unconverted path still depends on the old helper
  and the new platform can take that path, file `[BUG]`.
  (Example: a refactor converts one execution mode's setup routine to a new
  abstraction but leaves a sibling mode's setup routine calling the old
  helper, which fails on a newly supported platform variant.)
- **Helper side-effect proof**: when the report says a replacement helper
  preserves, restores, drops, or re-votes state, cite the exact call in the
  helper body that performs that side effect.  Do not infer behavior from the
  helper name, commit message, or sibling helper.  If the helper source says a
  state is intentionally not handled, treat the old caller's removed side effect
  as missing unless another reachable path restores it before use.
  **PM callback replacement**: when a patch replaces an entire suspend or
  resume function body with a single helper call, you MUST attempt an
  on-demand read of that helper's source to verify every side effect the
  old body performed is still present.  "Same series", "reasonable
  assumption", or "helper name implies equivalence" are not acceptable
  substitutes for reading the source.  If the helper's kdoc explicitly
  states a side effect is intentionally omitted (e.g. "does not restore
  performance state"), that omission is a regression unless the caller
  adds the missing step after the helper call.

### 3c.5 Before-vs-After Delta

For each changed function, explicitly state:
- **What the old code did** (one or two sentences, from `−` lines and
  surrounding context lines).
  For newly introduced functions that did not exist before, write:
  "Function did not exist; introduced by this patch."
  **Renamed or moved functions**: if a function is renamed or moved to a
  different file, state: "Function renamed from `<old>()` to `<new>()`" or
  "moved from `<file_A>` to `<file_B>`".  Confirm the logic is identical to
  the original; any logic change mixed into the rename is `[CONCERN] Patch
  Scope` (rename and logic change should be separate commits).
- **What the new code does** (one or two sentences, from `+` lines).
- **Why the change is needed** (from the commit message or inferred from the
  diff).  If the commit message does not state the *why* explicitly, note
  the absence here and cross-reference it as a 3e.3 body quality finding
  (`[MINOR]`) — do not silently substitute your own inference as if the
  author had explained it.

This delta is the foundation for every correctness finding in the Gate Rules section.
