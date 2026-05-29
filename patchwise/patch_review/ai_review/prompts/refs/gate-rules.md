## Step 4 — Review Each Commit

Evaluate every commit against these categories and cross-reference test results.

---

### THREE-GATE RULE — FINDING VALIDATION, MANDATORY, SEQUENTIAL, NON-BYPASSABLE

**Every non-cosmetic finding — `[BUG]`, `[CONCERN]`, or behavioral `[MINOR]` —
must pass the gates in order before it is written. `[NIT]` uses the separate
style track because it has zero runtime harm. Skipping the applicable track is a
self-audit failure and invalidates the finding.**

| Track | Required question | Result |
|---|---|---|
| Gate 1 — Reachability | Can I construct the exact call sequence or condition that reaches the bad state in the tree after the full series is applied? | If no, dismiss or use the future-risk path below. |
| Gate 2 — Harm | Does that reachable condition cause incorrect behavior, safety risk, or a real behavioral regression? | If no, dismiss; if only benign behavioral content remains, floor at `[MINOR]`. |
| Gate 3 — Severity | Given Gate 1 + Gate 2, which tier is correct: `[BUG]`, `[CONCERN]`, or `[MINOR]`? | Write the finding only at this calibrated tier. |
| Style track — NIT | Is the issue local, present, and purely cosmetic with zero behavioral content? | Write `[NIT]`; otherwise return to Gate 1. |

**Outcome rules**:
- All three gates pass → write the finding at the Gate 3 severity.
- Gate 1 fails → dismiss and record the invariant as a positive note, unless the
  future-risk rule below explicitly permits `[CONCERN]`.
- Gate 2 fails → apply the behavioral regression floor; if no behavioral content
  exists, dismiss.
- Gate 3 feels wrong → re-run Gate 1/Gate 2; Gate 3 does not bypass them.
- No "obvious finding" bypass exists: pattern memory can start Gate 1/style
  analysis, but cannot replace the applicable trace and proof.

#### Future-risk and patch attribution

**Patch-introduced reachability is NOT future-risk.** If this series adds the
platform, descriptor, compatible string, match-data entry, callback, route, or
other in-tree surface that makes the harmful path reachable, Gate 1 succeeds
after the full series is applied. Do not downgrade it to future-risk
`[CONCERN]`; apply Gate 2 and Gate 3 normally.

Use future-risk `[CONCERN]` only when Gate 1 cannot build a present-day path, but
all of the following are true: the current invariant is named, the patch expands
or exposes an API/descriptor/callback/dispatch surface that makes misuse worth
discussion, current table/descriptor/match-data/callback entries and call paths
are safe, and the concern is more than defensive style. Prefix the title with
`Future-risk:` and never file it as `[BUG]`.

Do **not** emit `[CONCERN]` for a merely hypothetical future table or match-data
entry when the review proves the current entries are complete and every current
path is safe. Downgrade that row to a note or local defensive-style suggestion
unless the patch exposes a real API/dispatch compatibility contract reviewers
must settle now.

Future-risk trace format:
```
(Gate 1: [sub-rule: <name or "none">] NOT reached in current tree —
  <invariant that holds today>;
  Gate 2: <hypothetical harm under named future change>;
  Gate 3: [CONCERN] — Future-risk gating per gate-rules §Future-risk.)
```

**Pre-existing issues and patch attribution**:
- If the patch does not worsen the issue or expand reachability, keep it as a
  patch-local `Pre-existing:` note only; do not emit it as a `.finding-card` and
  do not affect verdict, banner, or stats.
- If the patch materially worsens the behavior or makes an unchanged path newly
  reachable, required, or user-visible, report the regression against this patch
  with the before-vs-after reachability delta. Use
  `data-attribution="newly_exposed"`.
- Use `data-attribution="introduced"` for defects directly created by the patch.
- Never put `data-attribution="pre_existing_only"` on a `.finding-card`; that
  value exists so the validator can reject misclassified cards.

A reused legacy helper/setter/path becomes `newly_exposed` when the patch wires
it into a new control, platform/descriptor, bulk programming loop,
restore/resume/init path, or other newly active path that makes a dropped return,
silent no-op, or latent contract mismatch reachable or visible.

#### Non-findings and safe clearances

Do not emit any severity as a `.finding-card` when the review's own reasoning
says the code is safe, correct as written, acceptable as-is, has no actual
mismatch, needs no code change, or is only worth verifying. Route those results
to `Positive Notes`, patch-local explanatory prose, or `Pre-existing Issues
(non-blocking)`; they must not affect verdict banner, stat chips, or totals.

**Positive-note evidence rule (MANDATORY).** A `Positive Notes` entry that
affirmatively certifies a hazardous invariant as safe — no use-after-free, no
leak, no race, no double-free, correct lock coverage, or correct scale/divisor —
must cite the specific discharge it relied on: the freeing/teardown path read,
the lifetime guarantee, the lock that covers every writer, or the per-element
field the calc used. A bare "X is correctly handled" / "prevents UAF" / "cleanup
is symmetric" about one of these hazardous classes is not allowed; either quote
the invariant (then keep the note) or drop the claim to silence. Certifying an
area safe is held to the same proof bar as dismissing a finding there — an
all-clear verdict that praises lifecycle/concurrency/scale safety without a
quoted invariant is a self-audit failure.

**Clearance-proof rule — dismissing a named hardware-eng obligation requires a
quoted discharge line, not prose (MANDATORY).** If one of these hazardous
patterns appears and the review clears it, the same commit block must quote the
exact source line or trace that discharges the obligation; generic "looks
correct" prose is invalid.

| Trigger | Required discharge proof | If proof is missing |
|---|---|---|
| `device_unregister()` / `put_device()` / `_unregister()` of a caller-owned object whose pointer (`->fw_dev`, drvdata, list entry, cached handle) can be observed later | exact `<ptr> = NULL` or equivalent reset after unregister on the same path | file `[BUG]` per `device_unregister() pointer hygiene` — stale pointer / UAF on reinit or teardown |
| OPP/perf/genpd/clock-rate vote drop (`dev_pm_opp_set_opp(dev, NULL)`, `*_set_rate(_, 0)`, `pm_runtime_put*`, perf-state→0) inside a per-block/per-core helper used by a multi-block sequence | full multi-block sequence naming every sibling and proving no sibling is still active when the global vote drops | file `[BUG]` per `Global vote scope vs per-block helpers` |
| `pm_runtime_get_sync()` (not `pm_runtime_resume_and_get`) on a register/MMIO path | exact `pm_runtime_put_noidle()` on the `< 0` edge, or migration to `pm_runtime_resume_and_get` | file `[BUG]` per `pm_runtime bracket`; `pm_runtime_put_sync()`/`put()` after failed `get_sync` does not discharge it |
| Cross-instance / cross-provider raw pointer (`node->links[]`, peer device object, shared-topology pointer) stored into a sibling that is independently unbindable | the lifetime guarantee that keeps the target alive past every deref: `.suppress_bind_attrs = true`, a refcount/`get_device()` on the target, a managed `device_link`, or a quoted framework path that nulls inbound pointers on destroy | file `[BUG]` per `Cross-instance raw pointer across independent unbind` (UAF); "devm handles it", "providers removed together", or "cross-fabric links correctly handled" is not a discharge |

**Build-break ordering (always-first rule).** Any `[BUG]` whose root cause is a
build failure — compile error, link error, `-Werror` warning, or implicit
declaration — must be the first `.finding-card` in that commit block's
`<h3>Issues</h3>` and the first card in the `verdict-banner`.

#### Mandatory validation trace

Every commit-block finding must include the applicable trace in its `.body`.

For `[BUG]`, `[CONCERN]`, and behavioral `[MINOR]`:
```
(Gate 1: [sub-rule: <name or "none">] reachable via <caller() → target() path
   or condition>;
 Gate 2: <concrete harm — e.g. "UAF on unbind", "data corruption">;
 Gate 3: <severity justification — why this tier and not higher/lower>)
```

For `[NIT]`:
```
(Style track: <style rule violated>; Runtime impact: none; Severity: [NIT].)
```

For always-`[BUG]` exceptions:
```
(Always-BUG exception: <category>; Reachability: [sub-rule: <name or "none">]
   <caller/path>; Scope/category check: <result>.)
```

For resource-leak always-`[BUG]` exceptions, `Scope/category check` must include
`object-lifetime check: <bounded|static/unbounded + rationale>`. The field is
mandatory: `bounded` means heap/per-operation/hotpluggable and the exception may
apply; `static/unbounded` means fixed SoC peripheral, statically registered
device, or system-uptime object and the exception does not apply. Missing
`sub-rule:` or missing `object-lifetime check:` invalidates the finding.
The object-lifetime check is a scope qualifier, not a fourth gate; once it says
the always-`[BUG]` shortcut does not apply, fall through to the normal gates.

**Sub-rule quick-reference** — cite one exact name, or `none` only after checking
that no trigger fits:

| Cite name | Use when the suspected hazard is… |
|---|---|
| `module-refcount` | a probe/remove vs data-path race |
| `fix-safety` | the proposed fix reorders "clear ops" vs "drain sessions" |
| `two-phase-teardown` | existing remove path has publish/drain/unpublish phases |
| `no-caller-in-series` | inside a new helper with no visible caller |
| `flag-setter` | gated on a flag/mode reaching a terminal value |
| `session-lifecycle` | a missing re-check of a precondition an entry point already validated |
| `global-dispatch` | only reachable while a global ops/hook/flag is installed |
| `topology/NULL-deref` | a NULL from a DTS/bus/topology lookup |
| `allocation-failure` | only triggered when a `GFP_KERNEL` allocation fails |
| `severity-upgrade` | being promoted `[CONCERN]` → `[BUG]` |

No bypass for severity upgrades: promoting `[CONCERN]` to `[BUG]` requires a new
Gate 1 pass for the stronger claim. If the upgrade relies on "callee can return
error → UAF/crash/corruption", read the callee implementation and enumerate
concrete return paths; function signatures or syntactic possibility are not
enough. If that source read has not happened, the finding stays `[CONCERN]`.

The always-`[BUG]` list is exhaustive. Those classes bypass only ordinary Gate 2
harm debate and Gate 3 calibration after reachability and scope/category are
proven; no other defect class bypasses any gate.

---

#### Gate 1 — Reachability

Answer: *"What is the exact call sequence that puts the system into the bad
state?"* Trace writers of every relevant flag/variable across functions/files,
locks, refcounts, state machines, and surrounding invariants. If no concrete
triggering scenario exists, dismiss and document the invariant. If reachability
is uncertain but plausible, file `[CONCERN]` with the exact hypothetical sequence
and ask the author to confirm.

**Gate 1 sub-rule order**: check `module-refcount` first. Check
`no-caller-in-series`, `flag-setter`, `session-lifecycle`, `global-dispatch`, and
`topology/NULL-deref` whenever their triggers fit. Check `fix-safety` and
`two-phase-teardown` for teardown findings. Apply `allocation-failure` when the
whole chain requires OOM. Apply `severity-upgrade` before any CONCERN→BUG
upgrade. If any sub-rule proves the bad state unreachable, dismiss.

| Sub-rule | Required check | Gate result |
|---|---|---|
| `module-refcount` | For probe/remove vs data-path races, apply Step 3c.3 module lifecycle mutual exclusion. If data-path requires active module refcount and remove requires refcount zero, conditions are mutually exclusive. | Gate 1 fails. |
| `fix-safety` | Before suggesting clearing global ops/hook before a drain loop, identify the drain exit condition, the teardown/unprepare path that sets it, and whether that path requires the ops/hook to be non-NULL. | If teardown is gated on the pointer, the proposed reorder can deadlock; do not suggest it. |
| `two-phase-teardown` | For signal + drain + ops-fence remove paths, prove users entering during phase 1 see the cleared flag and exit before free, and that phase 2's NULL ops/hook prevents new entrants. | If both hold, Gate 1 fails for TOCTOU/race claims; record as positive design. |
| `no-caller-in-series` | For a new helper/API with no visible caller in this patch/context, scan later series patches for a caller and record the limitation in Code Logic Maps. | Caller-dependent hazards are capped at `[MINOR]`; use `[CONCERN]` only for undocumented/unenforceable API contracts; use `[BUG]` only for unconditional harm. |
| `flag-setter` | For hazards requiring a flag/mode value, enumerate every writer and the complete sequence before the write. Ask whether all writers first stop hardware, drain operations, sync state, or otherwise neutralize the hazard. | If every reachable writer establishes the safe invariant first, Gate 1 fails; otherwise continue. |
| `session-lifecycle` | For missing re-check claims, identify every call path and entry point. Ask whether any reachable path bypasses the entry-point validation of the pointer/state. | If every path inherits the validated precondition, Gate 1 fails; downstream functions need not re-check. |
| `global-dispatch` | For code entered only through global ops/hook/flag, find the installation site, enumerate installation invariants, and test whether the hazardous state is compatible while the dispatch is active. | If installation invariants exclude the hazard, Gate 1 fails; cite the coupling. |
| `topology/NULL-deref` | For NULL from graph/bus/topology lookup, resolve against platform DTS, binding `required:` properties, every matched compatible's binding, or an immediate driver NULL guard. | If topology guarantees the connection or guards it, Gate 1 fails; if DTS/evidence is unavailable or optional/multi-platform, cap at `[CONCERN]` rather than `[BUG]`. |
| `allocation-failure` | When the entire chain is `GFP_KERNEL` allocation failure → corrupt state/crash/leak, identify allocation size, GFP flags, and failure-edge behavior. | Fixed small bounded `GFP_KERNEL` OOM may be reachable but caps at `[CONCERN]` unless the failure edge creates guaranteed persistent corruption, deadlock, UAF, bounded-lifetime leak, or another always-`[BUG]` class; diagnostics-only changes are `[MINOR]`; correct cleanup dismisses. |
| `severity-upgrade` | Before CONCERN→BUG on an error-return path, read the callee body, enumerate every concrete non-zero return, and apply call-site state/lifecycle/lock/refcount invariants. | If non-zero is unreachable in normal operation, keep `[CONCERN]`; if a concrete non-zero path exists, continue to Gate 2/Gate 3. |

`allocation-failure` does not cap user-controlled/unbounded allocations,
`GFP_ATOMIC`/`GFP_NOWAIT`, known-large allocations, or unconditional defects.
Unconditional defects still require Gate 2 or always-`[BUG]` scope analysis; a
leaked reference on a system-uptime object must pass the object-lifetime rule.

For `topology/NULL-deref`, do not file solely because C permits NULL. If DTS is
not available, use binding `required:`, compatible coverage, or immediate driver
guards as substitute evidence. If none applies, note the limitation and cap at
`[CONCERN]`.

#### Gate 2 — Harm

Answer: *"Does the reachable condition actually cause incorrect or harmful
behavior?"* Do not file merely because code looks asymmetric. Safe no-op writes,
correct cleanup on an error path, deliberately per-instance state, or behavior
handled by an equivalent subsystem mechanism are not bugs.

**Behavioral regression floor.** Gate 2 only separates `[BUG]`/`[CONCERN]` from
lower tiers. If a refactor removed or reordered a call on a path that previously
performed it, the issue has behavioral content even when today's practical
outcome is benign; floor it at `[MINOR]`. `[NIT]` is only for zero behavioral
content.

#### Gate 3 — Severity Calibration

After Gate 1 and Gate 2, ask: *"How certain and severe is the harm?"*

| Severity | Use when |
|---|---|
| `[BUG]` | Harm is guaranteed on a concrete reachable path: crash/panic/hang, data corruption, UAF/double-free/OOB, security violation, hardware left permanently broken, or unconditional invariant violation relied on by the kernel. Timing-dependent races are still `[BUG]` when the interleaving is concrete and no lock/refcount/lifetime rule excludes it. |
| `[CONCERN]` | Harm is plausible but conditional or unconfirmed: depends on platform/DTS/usage the reviewer cannot verify, race serialization needs author confirmation, or design relies on an unstated guarantee. Do not use as a placeholder for unverifiable naming/hardware intuition. |
| `[MINOR]` | Behavioral content exists but no concrete harmful outcome is reachable today, including benign error/teardown-path regressions. |
| `[NIT]` | Pure naming, whitespace, indentation, comment wording, or cosmetic style with zero runtime impact. |

Boundary checks:
- `[BUG]` vs `[CONCERN]`: guaranteed concrete harm vs conditional/unconfirmed
  harm.
- `[MINOR]` vs `[NIT]`: any behavioral content vs purely cosmetic.
- Crash/dereference-class findings that are currently reachable must be at least
  `[CONCERN]`; dropped restore/revote/reprogram regressions in resume/runtime-PM
  paths must be at least `[CONCERN]`.

Examples: missing `clk_disable_unprepare()` on a bounded error path is `[BUG]`;
unchecked `pm_runtime_get_sync()` may be `[CONCERN]` when platform PM behavior is
unverified; silent `-EINVAL` without diagnostics is `[MINOR]`; blank-line style
is `[NIT]`; `devm_ioremap()` followed by no manual `iounmap()` is dismissed.

**Justification verification rule (mandatory before writing a finding body).**
Every behavioral claim used for severity — e.g. "disable does not release",
"allocator is idempotent", "flag is never set here" — must be verified from the
diff, context, or source. Do not rely on the commit message alone. If the code is
not in the provided context, attempt one on-demand `Read` under `<project_path>`
(subject to the 6-read budget in `core.md` Step 2). If the read confirms the
property, file at full severity. If the read fails or the budget is exhausted,
state the limitation and cap at `[CONCERN]`; never assert unverified behavior as
fact. Resolve contradictions with Code Logic Maps before filing.

#### Exception — always `[BUG]` after reachability and scope are proven

The following are `[BUG]` once reachability and category/scope are proven:

- **Reachable resource leaks**: kernel memory, OF/fwnode references, kobjects,
  krefs, `struct device` references, file descriptors, DMA buffers, hardware IRQ
  lines, and similarly unambiguous kernel-managed resources. For
  subsystem-specific logical resources (trace IDs, session slots, policy-owned
  refcounts), read disable/teardown intent first; if the resource is
  intentionally retained and re-acquire is idempotent, Gate 2 fails.

  **STOP — mandatory object-lifetime check for reference-counted object leaks**:
  can this object be freed or unregistered during normal uptime on the target?
  `YES`/bounded (heap, per-operation, hotpluggable, dynamically created) →
  always-`[BUG]` may apply. `NO` or not proven bounded (fixed SoC peripheral,
  statically registered device, firmware node with no normal removal path) → the
  exception does not apply; fall through to full gates. Consider overlays,
  driver unbind, module unload, debug/refcount observability, and future reuse
  before downgrading or dismissing. This check is mandatory for OF nodes,
  fwnodes, kobjects, krefs, `struct device`, and similar references; it does not
  apply to inherently bounded heap allocations, file descriptors, IRQ lines, or
  DMA buffers.
- **Sleeping in atomic context**: any sleeping function (`mutex_lock()`,
  `msleep()`, `schedule()`, etc.) under spinlock, softirq/hardirq, or
  `local_irq_save()` / `local_irq_disable()`.
- **Unsafe user copy**: `__copy_to_user()` / `__copy_from_user()` without prior
  `access_ok()`. Safe `copy_to_user()` / `copy_from_user()` call `access_ok()`
  internally since kernel 5.0; absence of an explicit check before safe variants
  is not a bug. Any `copy_*_user()` variant under spinlock is `[BUG]`.

**Signed/unsigned register reads.** Apply the Step 3c.2 register-read data-flow
check before filing. A `u32` stored in `int` and immediately returned as `u32` is
safe (C99 §6.3.1.3 preserves the bit pattern); at most `[NIT]`. Escalate only if
the signed intermediate affects signed arithmetic/comparison or signed widening
that produces a wrong result.

### Review Category Checklist

- **Correctness**: wrong conditions, off-by-one, NULL checks, error paths,
  data-structure invariants, API contracts.
- **Locking & Concurrency**: lock type/initialisation/order, sleeping while
  atomic, RCU/refcount/lifetime, races with remove/hotplug.
- **Memory Management**: allocation failure checks, `devm_` lifetime, leaks,
  ownership transfer, bounds checks.
- **Error Handling**: complete unwinds, meaningful error codes, diagnostics,
  probe/remove/PM symmetry.
- **Kernel API Usage**: current APIs, correct variants, context constraints,
  helper contracts.
- **Style & Maintainability**: checkpatch-clean names, comments, formatting,
  simple structure.
- **Documentation & ABI**: new sysfs/debugfs/trace/uapi ABI docs, stable ABI
  compatibility.
- **Kconfig / Build**: placement, minimal `depends on`, correct `Makefile`, W=1
  clean builds.

Dedicated refs own their domains; apply them only when assembled in the brief:
`refs/coding-style.md` (Step 3b), `refs/code-logic.md` (Step 3c),
`refs/dt-binding.md` / `refs/dt-driver.md` (Step 3d / Step 3d.3),
`refs/hardware-eng.md` (Step 3f), and `refs/commit-message.md` (Step 3e).

## Step 5 — Output Format

All output is HTML. The authoritative block structure (`.commit-header`,
`.commit-summary`, Code Logic Maps, DT / DT-Binding Notes, Hardware Engineering
Notes, Issues, Minor / Style, Positive Notes, and exact
`Not applicable: ...` text) is defined in Step 5b of `refs/core.md`; follow it
and map findings to the CSS classes below.

### Overall Summary / Verdict Banner

Rendered as `<div class="verdict-banner [class]">` immediately after the header
card. It contains the verdict pill (`READY TO APPLY` / `NEEDS FIXES` /
`NEEDS DISCUSSION`), stat chips for commits reviewed / bugs / concerns / minor
issues, and key findings grouped by `.findings-category` dividers with
`.finding-card` elements.

**Verdict criteria**:
- `READY TO APPLY` — zero findings, or only `[MINOR]` and/or `[NIT]`; nothing
  blocks merging. `[NIT]` affects the verdict class but is not shown as an
  individual banner card and is excluded from stat chips.
- Platform-enablement / "Add support" guard: when a series adds a SoC,
  compatible, platform, descriptor, route, or other in-tree reachability and
  touches probe/remove, PM, clocks/resets, PHYs, resources, or media/PCIe-style
  routing, do not leave `READY TO APPLY` unless the review explicitly exercised
  lifecycle cleanup, compatibility fallback, routing/cardinality, and the normal
  evidence locations: `codebase audit: entrypoints ...`, `codebase audit: callees ...`,
  `codebase audit: siblings ...`, plus applicable DT / DT-Binding Notes or
  Hardware Engineering Notes. Generic "looks consistent" prose is
  under-justified; reopen analysis. The green verdict must specifically cover
  lifecycle cleanup/unwind proof, compatibility fallback / old-DTB proof, and
  selector/cardinality proof when those surfaces are in scope.
- `NEEDS DISCUSSION` — one or more `[CONCERN]` findings and no `[BUG]`.
- `NEEDS FIXES` — one or more `[BUG]` findings.

Pre-existing issues do not affect verdict/banner/stats unless newly exposed or
materially worsened by this patch. Document pre-existing-only issues outside
finding cards with a `Pre-existing:` prefix and the reason the current patch did
not introduce them.

The verdict label is `READY TO APPLY` (not `READY`) everywhere.

**Verdict-banner dedup rule**: every banner `.finding-card` is a concise summary
(≤ 250 visible chars) that includes the patch subject and an
`<a href="#patch-<N>-finding-<K>">see Patch N</a>` link to the canonical
per-commit card. Full description, file reference, suggestion, and Gate trace
live only in the per-commit card.

Severity levels: `[BUG]` · `[CONCERN]` · `[MINOR]` · `[NIT]`

**Severity scope definitions**:
- `[BUG]` — definite correctness or safety defect with certain reachability and
  concrete harm; always appears in the verdict banner as an individual card.
- `[CONCERN]` — potential correctness/design issue with uncertain reachability
  or author-confirmation dependency; always appears in the verdict banner as an
  individual card. Do not escalate hypothetical scenarios to `[BUG]`.
- `[MINOR]` — real low-impact issue or behavioral regression that does not
  block merging; counted in the `minors` stat chip and listed under STYLE /
  MINOR in the banner.
- `[NIT]` — purely cosmetic issue with zero behavioral content; appears only in
  per-commit Minor / Style sections, excluded from banner findings and all stat
  chips. Do not use `[NIT]` for any behavioral change.
