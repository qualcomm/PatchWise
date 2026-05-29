## Step 4 — Review Each Commit

Evaluate every commit against these categories (cross-reference test results).

---

### THREE-GATE RULE — FINDING VALIDATION, MANDATORY, SEQUENTIAL, NON-BYPASSABLE

**Every non-cosmetic finding — `[BUG]`, `[CONCERN]`, or behavioral
`[MINOR]` — must pass through the gates in order before being written to the
commit block.  `[NIT]` findings use the style-applicability track below
because they intentionally have zero runtime harm.  Bypassing the applicable
track, for any reason, is a self-audit failure that invalidates the finding.**

```
Gate 1 — Reachability  Can I construct the exact call sequence that
                       puts the system into the bad state?

Gate 2 — Harm          Does that reachable condition produce genuinely
                       incorrect or harmful behavior?

Gate 3 — Severity      Given Gate 1 + Gate 2 outcome, which severity
                       tier is correct: [BUG] / [CONCERN] / [MINOR]?

Style track — NIT      Is the cited style issue present, local, and purely
                       cosmetic with zero behavioral content?
```

**Outcomes:**

- **All three gates pass**: Write the finding at the Gate 3 severity.
- **Gate 1 fails**: Dismiss. Document the invariant that prevents the condition
  as a positive note.
- **Gate 2 fails**: Apply the behavioral regression floor. If no behavioral
  regression exists, dismiss.
- **Style track passes**: Write `[NIT]` only if the issue is purely cosmetic;
  otherwise return to Gate 1 and evaluate as `[MINOR]` or higher.
- **Gate 3 yields wrong tier**: Re-examine. Gate 3 always produces a verdict;
  if the result feels wrong, the error is in the Gate 1 or Gate 2 analysis, not
  Gate 3. Revisit.

**Future-risk findings (Gate 1 cannot construct a present-day call sequence)**:
when the harm scenario depends on a hypothetical future caller, future
refactor, or undocumented contract — i.e. Gate 1 fails for the **current**
code but the design is fragile — ask:
1. What exact invariant prevents the bad state in the current tree?
2. Did this patch expand or expose an API, descriptor, callback, or dispatch
   surface so the future misuse is plausible and worth reviewer attention?
3. Are all current table, descriptor, match-data, or callback entries complete,
   and are all current call paths safe?
4. Is the point merely defensive coding style, or is there a concrete future
   compatibility contract reviewers should discuss now?

**Critical distinction — patch-introduced reachability is NOT future-risk**:
when the patch series under review itself introduces a new platform,
descriptor, compatible string, or match-data entry that enables the harmful
path, Gate 1 SUCCEEDS — the path is reachable in the tree after applying
this series.  Do not downgrade such findings to future-risk `[CONCERN]`.
Apply the normal severity gates (Gate 2 → Gate 3) at full strength.  The
"future-risk" escape applies only when no in-tree caller/descriptor/platform
**after the full series is applied** can reach the path.

Do not file a normal behavioral finding when Gate 1 fails.  File future-risk
`[CONCERN]` only when question 2 is yes and the concern is not merely a
hypothetical incomplete future table entry.  Prefix the title with
`Future-risk:`.  Do **not** file as `[BUG]`.  If all current entries are
complete and every current call path is safe, dismiss with the current
invariant, or at most use `[NIT]`/`[MINOR]` for a local defensive-coding
suggestion supported by subsystem style.  Examples that belong here:
"Future-risk: callback dispatch under IRQ-disabled spinlock — current clients
only schedule_work; a future client that called regmap from this context would
deadlock", "Future-risk: API overload accepts NULL dev — no in-tree caller
passes NULL today, but the contract is fragile".  The Gate trace for these
findings reads:
`(Gate 1: [sub-rule: <name or "none">] NOT reached in current tree —
  <invariant that holds today>;
  Gate 2: <hypothetical harm under named future change>;
  Gate 3: [CONCERN] — Future-risk gating per gate-rules §Future-risk.)`

**Safe/no-action conclusions are not findings**: if the finding's own
reasoning concludes the current code is safe, has no behavioral regression, or
needs no code change, do not keep it as `[BUG]` or `[CONCERN]`.  Dismiss it,
record the invariant as a positive note, or restate it as a local
style/maintainability suggestion at the appropriate lower tier.

**Build-break ordering (always-first rule)**: any `[BUG]` whose root cause
is a build failure (compile error, link error, `-Werror`-promoted warning,
implicit declaration) MUST be the **first** `.finding-card` in its
commit-block's `<h3>Issues</h3>` section AND the first card in the verdict
banner.  Build breaks block bisectability, so they take priority over
correctness bugs in the same patch regardless of harm severity.  The
orchestrator enforces this in Step 6.6; `scripts/validate_review.py`
(Step 6.7) checks it on the assembled HTML.

**No bypass for "obvious" findings**: even a finding that appears
self-evidently correct must pass the applicable validation track explicitly.
Pattern recognition from prior reviews is a starting point for Gate 1 or
style-applicability analysis, not a substitute for it.  Writing a finding
without completing the applicable track is forbidden regardless of how clear
the issue appears.

**Trace requirement (MANDATORY for every finding)**: Every finding written to
the commit block MUST include a parenthetical validation trace in its `.body`
proving which track was applied and its outcome:

```
(Gate 1: [sub-rule: <name or "none">] reachable via <caller() → target() path
   or condition>;
 Gate 2: <concrete harm — e.g. "UAF on unbind", "data corruption">;
 Gate 3: <severity justification — why this tier and not higher/lower>)
```

The `Gate 1 sub-rule:` tag is **mandatory** and names which Gate 1 sub-rule
from the index below governed reachability — or `none` when the finding
matches no sub-rule.  This forces the dismissal sub-rules (which suppress
false positives) to be actively considered rather than skimmed.  When a
finding's pattern matches a sub-rule trigger (e.g. a missing-NULL-guard on a
topology lookup → `topology/NULL-deref`; a missing precondition re-check on a
downstream callee → `session-lifecycle`), you MUST cite that sub-rule and
state its outcome (passed → finding stands; failed → finding is dismissed and
not written).  Citing `none` while the body describes a pattern that clearly
matches a sub-rule is a self-audit failure.

**Sub-rule quick-reference** (full triggers + procedures in the Gate 1 sub-rule
index below — cite one of these exact names, or `none`):

| Cite name | Use when the suspected hazard is… |
|---|---|
| `module-refcount` | a probe/remove vs data-path race |
| `fix-safety` | the *proposed fix* reorders "clear ops" vs "drain sessions" |
| `two-phase-teardown` | existing remove path has publish/drain/unpublish phases |
| `no-caller-in-series` | inside a new helper with no visible caller |
| `flag-setter` | gated on a flag/mode reaching a terminal value |
| `session-lifecycle` | a missing re-check of a precondition an entry point already validated |
| `global-dispatch` | only reachable while a global ops/hook/flag is installed |
| `topology/NULL-deref` | a NULL from a DTS/bus/topology lookup |
| `allocation-failure` | only triggered when a `GFP_KERNEL` alloc fails |
| `severity-upgrade` | being promoted `[CONCERN]` → `[BUG]` |

If none of these patterns fit the finding, write `[sub-rule: none]` — but only
after checking the table; `none` is not a default to skip the analysis.

For `[NIT]` findings:
```
(Style track: <style rule violated>; Runtime impact: none; Severity: [NIT].)
```

For always-[BUG] exceptions (resource leaks, sleeping-in-atomic, copy_*_user):
```
(Always-BUG exception: <category>; Reachability: [sub-rule: <name or "none">]
   <caller/path>; Scope/category check: <result>.)
```
For resource-leak always-[BUG] exceptions, the scope/category check must include
`object-lifetime check: <bounded|static/unbounded + rationale>`.

The `object-lifetime check:` field is **mandatory** on always-[BUG]
resource-leak findings and must state the determination, not be omitted:
`bounded` (heap / per-operation / hotpluggable → always-[BUG] applies) or
`static/unbounded` (fixed SoC peripheral, statically-registered device →
always-[BUG] does NOT apply; fall through to full gate analysis).  This is the
dominant false-[BUG] guard for reference/resource leaks; a missing or empty
result is rejected by post-group validation.  Sleeping-in-atomic and unsafe
`copy_*_user()` always-[BUG] findings still require reachability and scope, but
not an object-lifetime field.

A finding without the applicable validation trace — including the mandatory
`sub-rule:` tag on non-NIT findings and the `object-lifetime check:` result on
always-[BUG] resource-leak findings — is **automatically invalid**: the
orchestrator's post-group validation will reject the block and re-spawn the
subagent.  There are no exceptions to this rule.

**No bypass for severity upgrades**: upgrading a finding from `[CONCERN]` to
`[BUG]` is a Gate 1 re-evaluation, not merely a Gate 2 or Gate 3 judgment.
A finding may have been initially filed as `[CONCERN]` precisely because
reachability was uncertain.  Before promoting it to `[BUG]`, Gate 1 must be
re-executed from scratch for the upgraded claim — not assumed to carry over.
In particular: if the upgrade is based on the harm of an error-return code
path (e.g. "callee X can return non-zero, triggering UAF chain Y"), you must
read the actual implementation of callee X and enumerate every concrete return
path to verify that non-zero is reachable in practice.  Syntactic possibility
— the function signature allows non-zero — is not sufficient.  The concrete
execution context (mode invariants, state machines, locks held, mode cleared
only in specific paths) determines whether the error path is actually
reachable.  If you have not read the callee's implementation, you cannot
upgrade to `[BUG]`; the finding stays at `[CONCERN]`.

**Exception — always-`[BUG]` list**: the defect classes listed under
"Exception — always `[BUG]`" below still require reachability and scope to be
proven.  Once reachable category membership is proven, they bypass only the
ordinary Gate 2 harm debate and Gate 3 calibration because severity is fixed at
`[BUG]` by definition.  **This exception is exhaustive: no other defect class
bypasses any gate.**

**Clarification — object-lifetime check is NOT a fourth gate**: The
"mandatory object-lifetime check" is a **scope qualifier**, not an extra gate —
it only decides whether the resource-leak always-[BUG] exception applies at all.
The full procedure (the YES / NO-or-not-proven branches) lives in the **STOP —
mandatory object-lifetime check** block inside the always-`[BUG]` list below;
apply it there.  Bounded lifetime → always-[BUG] applies; proven
unbounded/static lifetime → fall through to the full gate analysis.

---

**Gate 1 — Reachability**: Answer: *"What is the exact call sequence that puts
the system into the bad state?"*  Trace all writers of every flag or variable
involved, across all functions and files, and confirm the triggering condition
is actually reachable at that call site given the locks held and state
invariants enforced by the surrounding code (e.g. a store function returning
`-EBUSY` while a flag is set makes the corresponding error path unreachable).
If you cannot construct a concrete triggering scenario, dismiss the finding and
document the invariant that prevents it as a positive note instead.
If reachability is *uncertain* (e.g. depends on a race window or an unusual
caller), file as `[CONCERN]` — include the exact hypothetical sequence that
would trigger the condition and ask the author to confirm or deny reachability.

**Gate 1 sub-rule index and relationships:**

The following sub-rules are specialized applications of Gate 1 for common
kernel patterns.  When a finding matches multiple sub-rules, apply them in
this precedence order (first match that dismisses → finding is dismissed).
The **bold citation name** after each number is the exact string to write in
the `Gate 1 sub-rule:` trace tag.

1. **Module-refcount** — cite: `module-refcount`
   - Applies when: race between probe/remove and data-path.
   - Related sub-rules: overlaps with #6 (session-lifecycle). Module-refcount
     is coarser; if it dismisses, skip #6.
2. **Fix-safety** — cite: `fix-safety`
   - Applies when: fix reorders "clear ops" vs "drain sessions".
   - Related sub-rules: overlaps with #3 (two-phase teardown). Fix-safety is
     about the *proposed fix*; two-phase is about the *existing code*.
3. **Two-phase teardown** — cite: `two-phase-teardown`
   - Applies when: remove/cleanup has publish/drain/unpublish phases.
   - Related sub-rules: overlaps with #5 (flag-setter). Two-phase analyzes the
     full teardown; flag-setter focuses on one precondition.
4. **No-caller-in-series** — cite: `no-caller-in-series`
   - Applies when: new helper has no visible caller.
   - Related sub-rules: independent; caps purely caller-dependent hazards at
     [MINOR] unless the API contract itself is ambiguous.
5. **Flag-setter preconditions** — cite: `flag-setter`
   - Applies when: hazard depends on a flag/mode value.
   - Related sub-rules: subset of #6 (session-lifecycle); handles simple
     single-flag cases.
6. **Session-lifecycle** — cite: `session-lifecycle`
   - Applies when: entry-point precondition is inherited by callees.
   - Related sub-rules: generalizes #1 and #5 for complex multi-flag state
     machines.
7. **Global-dispatch installation coupling** — cite: `global-dispatch`
   - Applies when: code path is entered only via global ops/hook/flag.
   - Related sub-rules: overlaps with #6 (session-lifecycle) and #8 (topology).
     Use when the invariant comes from the *installation site*, not from an
     entry-point check or the DTS alone.
8. **Topology/NULL-dereference** — cite: `topology/NULL-deref`
   - Applies when: NULL comes from topology/bus lookup.
   - Related sub-rules: independent; requires DTS or binding evidence.
9. **Allocation-failure** — cite: `allocation-failure`
   - Applies when: bug requires GFP_KERNEL allocation to fail.
   - Related sub-rules: independent; calibrates severity without dismissing
     valid fault-injection paths solely because the allocation is small.
10. **Severity-upgrade mandate** — cite: `severity-upgrade`
    - Applies when: promoting [CONCERN] → [BUG].
    - Related sub-rules: meta-rule; requires re-executing Gate 1 for the
      stronger claim.

**Application order**: Check #1 first (cheapest). If #1 does not apply, check
#4–#8 (independent, can be checked in any order). Check #2 and #3 only for
teardown-related findings. Apply #9 last (only when upgrading).

**Module-refcount sub-rule (applies to any alleged race between probe/remove
and a data-path caller)**: Before filing, apply the four-step check from
Step 3c.3 "Module lifecycle mutual exclusion".  If the data-path operation
requires the module to be active (refcount > 0) and the remove/cleanup path
requires the module to be inactive (refcount == 0), the two conditions are
mutually exclusive and Gate 1 fails — dismiss the finding.

**Fix-safety sub-rule (applies whenever a proposed fix reorders a "clear
global ops/hook pointer" call relative to a "drain active sessions" loop)**:
This sub-rule applies to any driver that installs a module-level global ops,
callback pointer, or hook at probe/open time and clears it at remove/close.
Before suggesting that the ops/hook pointer be cleared *before* a drain loop
that waits for in-flight users to exit, verify:
  (a) What exit condition does the drain loop wait for (e.g. an
      `active_sessions` refcount reaching zero, a `session_active` flag
      reaching false, a completion being signalled)?
  (b) Which teardown or unprepare path is responsible for setting that
      condition to its terminal value (e.g. a release callback, a close or
      unprepare function called from the user-facing file release path)?
  (c) Is that teardown/unprepare path gated on the global ops/hook pointer
      being non-NULL (i.e. does it check the pointer before executing)?
  If (c) is true, moving the ops/hook clear before the drain creates a
  deadlock: in-flight users will skip the teardown/unprepare path because ops
  is NULL, the terminal condition will never be set, and the remove function
  will wait forever.  Do not propose this reordering without confirming (a)–(c).

**Two-phase teardown completeness sub-rule (applies whenever a remove/cleanup
path uses a "signal + drain + ops fence" sequence)**:
This sub-rule applies broadly to any driver whose remove path implements:
  Phase 1 — drain active users: a shared flag (e.g. `enabled`, `active`) is
  cleared under appropriate locking, waiters are woken, and the drain loop
  waits until all in-flight users have exited their critical section (e.g. an
  `in_use` refcount drains to zero, a `session_active` flag clears).
  Phase 2 — entry fence: a global ops or hook pointer is set to NULL,
  permanently preventing new callers from entering the code path that
  accesses the data structure about to be freed.
  Before filing a TOCTOU finding about a new user starting after phase 1's
  per-user check but before phase 2's ops fence, answer both questions:
  (a) If a new user entered during the phase 1 window (i.e. after the
      drain loop's per-user check but before the ops fence), does the
      shared flag cleared in phase 1 cause that user to exit cleanly
      *before* the data structure is freed?  Trace the exact code path:
      flag cleared → wakeup → user-space loop exit → unprepare/teardown
      path → drain wait unblocks.
  (b) After the ops fence is set (phase 2), can any new user reach the
      data structure through the ops path?  Once the ops/hook pointer is
      NULL, no new caller can enter the protected code path, so any access
      through that path is impossible after phase 2 completes.
  If (a) is yes — any user who entered during the phase 1 window exits
  safely before free — and (b) is yes — the ops fence is the authoritative
  gate after phase 2 — then the two-phase design is sound and complete.
  Gate 1 fails; dismiss the finding and note the two-phase teardown as a
  positive design element instead.  Do not file a race finding based solely
  on the existence of a window *between* the two phases; that window is
  covered by phase 1's flag signal, not by a lock.

**No-caller-in-series sub-rule (applies whenever a new function introduced by
this patch has no caller visible in this patch's diff or context files)**:
When a new helper or API function is added by the current patch and no call
site for it exists in this patch's diff or context files, the function's
caller-side preconditions are not yet visible.  Gate 1 cannot be fully
evaluated without knowing what invariants the caller will enforce.

Before filing any `[CONCERN]` or `[BUG]` about a code path inside that
function (e.g. an error branch that modifies shared state, a cleanup path that
frees a resource, a state transition that looks destructive):

1. **Scan the series summary** for a call site in a later patch.  If one
   exists, the caller's preconditions are simply not visible in the current
   patch's context window.

2. **Record the limitation** in the Code Logic Maps section if no caller is
   visible: `"Note: <function>() has no visible caller in this patch —
   caller-side preconditions cannot be verified.  Safety assessment is
   conditional on what the caller guarantees."`

3. **Avoid premature high-severity findings** for any finding whose Gate 1
   outcome depends entirely on what the future caller does.  If a later patch
   in the same series introduces the caller, defer the final reachability
   judgment to that caller patch and cross-reference the helper as context.
   If no caller is visible anywhere in the available series/context, cap the
   finding at `[MINOR]` for a purely conditional hazard and state the
   conditionality explicitly in the finding body: `"If the caller enforces
   <precondition>, this path is unreachable and this finding should be
   dismissed.  Re-evaluate when the caller patch is reviewed."`

   Use `[CONCERN]` instead of `[MINOR]` only when the helper exposes a new API
   whose required preconditions are undocumented or unenforceable by callers,
   making the interface itself ambiguous even before a caller exists.  Do not
   use `[BUG]` unless the hazard is unconditional under item 4.

4. **Exception — unconditional hazards**: if the code path is harmful
   regardless of any caller precondition (e.g. an unconditional memory leak,
   or sleeping in a context that is always atomic irrespective of caller mode),
   file at the appropriate severity.

**Flag-setter preconditions sub-rule (applies whenever a suspected hazard
requires a flag to hold a particular value at the same time as a dangerous
resource or hardware state)**: When a code path is gated on a flag (e.g.
`enabled`, `active`, `running`, a mode field) reaching a terminal value
(e.g. `false`, `0`, a disabled state), do not stop at identifying the writers
of that flag.  A common false-positive pattern is to observe that the gated
code path accesses a shared resource that would be unsafe while the resource
is still live, without verifying whether the flag can actually be set while
that resource is in the dangerous state.  For each writer of the flag, ask:

  (a) What is the *complete sequence of operations* that precedes the flag
      write on that code path?
  (b) Do those preceding operations establish invariants — e.g. stopping
      hardware, draining in-flight operations, syncing shared state — that
      neutralize the apparent hazard before the flag is written?
  (c) Is there any writer that can set the flag WITHOUT first establishing
      those invariants (i.e. while the dangerous resource state is still live)?

If (c) is false — every writer in the relevant operating context first
establishes the neutralizing invariants — the co-occurrence the hazard
requires is structurally impossible.  Gate 1 fails; dismiss the finding.
Document the invariant chain in the Code Logic Maps section (e.g.
"<flag>=<value> is only set by path X after Y completes — the resource is
always in a safe state when the gated code path executes").

If (c) is true — at least one writer can set the flag while the resource
is in the dangerous state — Gate 1 passes.  Proceed to Gate 2.

Note: a writer may be restricted to a specific operating context (e.g. a
teardown path that only runs when the device is inactive, or a stop function
that guards against running while a session is open).  Always confirm that
the writer is reachable in the exact mode the hazard requires before
concluding that (c) is true.  This sub-rule applies to both teardown paths
and normal disable/stop paths.

**Session-lifecycle precondition inheritance sub-rule (applies whenever a
function omits a NULL or state guard that an upstream function in the same
call-sequence already performs)**: When a function is only reachable via a
specific entry-point call chain (e.g. a file `.read` handler reachable only
after `.open` succeeds, a runtime data path reachable only after
`probe`/`init`, a consumer operation reachable only after a
`prepare`/`start` function), any precondition check performed by the entry
function is *inherited* by all downstream functions in the same session.  A
downstream function that omits a re-check of an already-validated pointer or
state is correct by design — not a missing guard.  Before filing a
missing-NULL-guard or missing-precondition finding:

  (a) Identify every call path that reaches the function under review.
  (b) For each path, determine whether the path's entry point validates the
      precondition (e.g. returns an error or refuses to open if the pointer
      is NULL or the state is invalid).
  (c) Ask: is there any reachable call path that bypasses the entry-point
      check?

If (c) is false — every reachable path goes through a validated entry point
that enforces the precondition — the precondition is structurally guaranteed
at the call site.  Gate 1 fails; dismiss the finding.  Document the
invariant in the Code Logic Maps section (e.g. "<entry>() validates
<precondition> before any caller can reach <function>() — re-check is
unnecessary").

The asymmetry between entry functions (which check) and downstream functions
(which do not re-check) is intentional and correct — flagging it as a bug is
a false positive.

**Global-dispatch installation-coupling sub-rule (applies whenever a potential
hazard lies inside a code path that is only entered through a globally-installed
dispatch mechanism — ops table, function pointer, capability flag, or feature
hook)**: A code path gated by a global dispatch pointer or flag can only be
active while that pointer/flag is set.  Gate 1 must therefore evaluate
reachability at the *calling-context level* — not at the *callee level* in
isolation.  Do not ask "can this function return NULL / can this condition
occur?" in isolation; ask "can it occur *while this dispatch is active*?"

Three steps are mandatory before filing any finding inside such a code path:

1. **Identify the installation site.** Find where the global ops pointer,
   hook, or feature flag transitions from absent/disabled to
   present/enabled (e.g. a `WRITE_ONCE`, a `register_*` call, a capability
   bit set during `probe`).

2. **Enumerate the installation invariants.** What preconditions must hold
   for installation to succeed?  Common invariants: probe completed (hardware
   initialized), DT topology links established (all connections described in
   DT are visible to topology-walk functions), hardware resources allocated
   and valid, a specific device count or mode reached.

3. **Test for incompatibility.** Does the potential hazardous condition
   (e.g. a topology lookup returning NULL, a resource being uninitialized,
   a hardware feature absent) require a state that is *excluded* by the
   installation invariants?  If the bad state is incompatible with what must
   be true for the dispatch to be active, the condition is unreachable while
   the dispatch is active.

If step 3 shows the installation invariants exclude the hazardous condition:
**Gate 1 fails — dismiss the finding.**  Document the coupling:
*"The global &lt;ops/flag&gt; is only installed after &lt;precondition&gt;,
which guarantees &lt;invariant&gt; — &lt;hazardous condition&gt; is
unreachable while &lt;ops/flag&gt; is active."*  A missing defensive null
check in this context is at most `[NIT]`.

If the installation invariants do **not** exclude the hazardous condition
(e.g. the ops are installed globally but the bad state can arise for a
specific device instance not covered by the installation preconditions),
Gate 1 passes — continue to Gate 2.

**Relationship to session-lifecycle sub-rule (#6)**: Sub-rule #6 applies
when a downstream function omits a re-check of a precondition already
validated by the *entry point* in the same call chain.  This sub-rule (#7)
applies when the precondition was not checked at the entry point but was
established earlier at the *dispatch installation site*.  Both lead to Gate
1 failing, but from different invariant sources.

**Relationship to topology sub-rule (#8)**: Sub-rule #8 establishes that a
topology-lookup returning NULL is unreachable when the DTS guarantees the
connection.  This sub-rule adds that when the dispatch is *also* only
installed after the topology is established, the NULL is excluded on
installation-invariant grounds alone — even without a direct DTS read in
the context files.  When both sub-rules apply, either is sufficient to
dismiss; cite the more directly verifiable one.

**Topology/graph/bus-lookup NULL-dereference sub-rule (applies whenever a
suspected NULL dereference originates from a function that looks up a
connection in a hardware topology described by the DTS)**: Any function that
walks a hardware topology graph, bus fabric, or device-linkage structure and
returns NULL when the requested connection does not exist in that topology
can only return NULL if the platform DTS omits or makes optional that
connection.  The topology is defined by the DTS — not by the C code alone.
Before filing a NULL-dereference concern on a pointer returned by such a
function:

  (a) If the platform DTS is available — either as one of the provided
      context files or within this patch's diff — read it to determine
      whether every device that invokes the lookup is always wired to the
      expected topology partner on all supported platforms.
  (b) If the DTS shows that all relevant devices are always interconnected on
      every targeted platform, the NULL return is architecturally unreachable.
      Gate 1 fails; dismiss the `[CONCERN]` / `[BUG]` and document the
      invariant: `"<lookup-function>() returns non-NULL for every <device> in
      the target platform DTS — NULL path is topology-unreachable."`.  A
      missing defensive NULL check in this context is at most `[NIT]`.
  (c) If the platform DTS is not available (not among the provided context
      files and not in this patch's diff), the binding marks the connection
      as optional (i.e. the property is not listed under `required:`), or the
      driver targets multiple platforms where the connection is not guaranteed,
      the NULL path may be reachable.  In that case Gate 1 passes — continue
      to Gate 2 and file at the appropriate severity.

Do NOT file `[CONCERN]` solely because the C code permits NULL — always
resolve reachability against the hardware topology encoded in the DTS before
escalating.  If the DTS is unavailable, note the limitation and cap the
finding at `[CONCERN]` rather than `[BUG]`.

**Alternative evidence for DTS-unavailable cases**: When the DTS is not in the
context files, the following alternative evidence MAY substitute for a direct
DTS read to determine reachability:
- **Binding schema `required:` list**: If the DT binding YAML lists the
  property/phandle under `required:`, it is guaranteed present on all compliant
  platforms → NULL is unreachable → Gate 1 fails.
- **Driver `of_device_id` compatible strings**: If every compatible the driver
  matches has a binding that requires the connection, NULL is unreachable.
- **Driver code guards**: If the driver itself checks for NULL immediately after
  the lookup and handles it gracefully (returns error, skips optional feature),
  the dereference is guarded → Gate 1 fails for the dereference finding
  (though a separate [MINOR] for "function returns error but caller doesn't
  check" may apply).

If none of these alternatives apply and the DTS is unavailable: cap at
`[CONCERN]` as stated above.

**Allocation-failure severity sub-rule (applies whenever the entire bug
trigger chain requires a `GFP_KERNEL` allocation to fail)**: A `GFP_KERNEL`
allocation whose size is **compile-time bounded** — meaning it is a fixed
constant or `sizeof(struct X)` where the struct size is not controlled by
user input or runtime state (e.g. a single small struct, a fixed-size array
of a few dozen elements, or a handful of pointers — typically ≤ 512 bytes)
is unlikely during normal operation, but it is still a valid kernel error path
and may be reachable under memory pressure or fault injection.  Do not dismiss
an issue solely because the allocation is small.

Before filing any finding whose entire trigger chain is "allocation X fails →
state Y is corrupt → crash/leak Z", ask: *"What is the allocation size and
gfp flag, and what exactly happens on the failure edge?"*  If the answer is a
fixed small size with `GFP_KERNEL`, Gate 1 may pass, but Gate 3 is capped at
`[CONCERN]` unless the failure edge itself creates a guaranteed persistent
corruption, leak of a bounded-lifetime resource, deadlock, UAF, or other
always-`[BUG]` class.  If the failure edge only changes diagnostics or returns
a less precise error, use `[MINOR]`.  If cleanup remains correct, dismiss.

This sub-rule does **NOT** apply when:
- The allocation size is user-controlled or unbounded (e.g. `kmalloc(len)`
  where `len` comes from user space, a firmware blob, a DMA coherent buffer).
- The allocation uses `GFP_ATOMIC`, `GFP_NOWAIT`, or any flag that may
  legitimately fail even for small sizes.
- The allocation is known large at the call site (e.g. allocating a full
  page, a large ring buffer, a scatter-gather table).
- The defect is unconditional — it occurs on every successful code path, not
  only on the allocation-failure branch (e.g. a counter incremented on every
  probe, not just on OOM).  Note: unconditional defects still require Gate 2
  or always-[BUG] scope analysis to pass — a leaked reference on a kernel
  object that appears permanent during the reviewed target's uptime must be
  evaluated under the object-lifetime rule rather than automatically filed as
  `[BUG]` or automatically dismissed.

**Severity-upgrade reachability mandate (applies whenever a finding is being
promoted from `[CONCERN]` to `[BUG]` on the basis of an error-return code
path)**: A `[CONCERN]` finding that was filed because reachability was
uncertain does NOT automatically satisfy Gate 1 when its severity is
reconsidered.  Gate 1 must be re-executed for the upgraded claim.

The specific check that is mandatory before any CONCERN→BUG upgrade driven
by "callee can return error → harmful UAF/crash/corruption chain":

1. **Read the actual implementation** of the callee whose non-zero return
   drives the upgrade.  Do not rely on the function signature, the call-site
   pattern, or the harm chain alone.  Open and read the function body.

2. **Enumerate every concrete return path** in that implementation.
   Identify which paths are reachable given:
   - The subsystem state invariants in force at the call site (e.g. a device
     state flag, a registration state, an open/close counter, a power state)
     and which of those invariants are *preserved* — not altered — by the
     code that runs between the last state assignment and the call site.
   - Lifecycle serialization: if the state can only transition on a specific
     path (e.g. device remove, session close, event stop, driver disable) and
     that path cannot execute concurrently with the call site, any guard
     based on that state is unreachable from the call site.
   - Any lock, reference count, or other serialization that prevents the
     relevant state from changing between the surrounding context and the
     callee.

3. **If the only non-zero return path requires a condition that the state
   invariants or lifecycle constraints make unreachable in normal
   operation**, Gate 1 fails for the upgraded `[BUG]` claim.  The finding
   stays at `[CONCERN]` (structural latent gap) — do not promote to `[BUG]`.
   Document in the finding body: *"The non-zero return path of `<callee>()` is
   not reachable in normal operation because `<invariant>` — filing as
   [CONCERN] (structural gap) rather than [BUG]."*

4. **If a concrete reachable non-zero return path exists**, Gate 1 passes for
   the `[BUG]` claim; continue to Gate 2 and Gate 3 as normal.

*Example of this rule applied*: A callee has exactly one non-zero return
path — a state-flag guard (`if (state != ACTIVE) return -EINVAL`).  The
flag is set during session open and cleared only during session close.
Between a pause and a resume of the same session, close cannot be called —
the session is still active.  Therefore the guard cannot fire in that window,
Gate 1 fails for the `[BUG]` upgrade, and the finding stays at `[CONCERN]`.

**Gate 2 — Harm**: Even when the condition is reachable, ask: *"Does the
resulting behavior actually cause incorrect or harmful outcomes?"*  A no-op
write to an already-`false` flag, a safe cleanup on an error path, or an
omitted state update that is intentionally managed by a different per-instance
field are not bugs.  Consider whether the omission is deliberate: does the
subsystem manage equivalent state elsewhere (e.g. a per-instance flag vs. a
shared flag)?  Only file the finding if you can show the fallthrough or missing
update leads to genuinely incorrect behavior — not merely to code that looks
asymmetric or incomplete.

**Behavioral regression floor (mandatory — applies when Gate 2 fails)**:
Gate 2 governs only the [BUG] / [CONCERN] threshold.  When Gate 2 fails
(no concrete harm), do NOT automatically downgrade to [NIT].  Ask: *"Did
a refactor remove or reorder a call on a code path that previously made
it?"*  If yes, the finding has behavioral content — it is a regression in
the error handler even when the practical outcome is unchanged today.  The
floor for such findings is **[MINOR]**.  [NIT] is reserved for purely
cosmetic issues with zero behavioral content (naming, whitespace, comment
wording).  Never use Gate 2's failure result to downgrade a behavioral
regression below [MINOR].

**Gate 3 — Severity Calibration (mandatory — applies after Gate 1, and after
Gate 2 for non-exception correctness findings)**:
Once Gate 1 (reachable) and Gate 2 (harmful or behavioral-regression) have
been evaluated, determine the severity by asking: *"How certain and how
severe is the harm?"*

- **`[BUG]`** — the harm is **guaranteed** on a concrete, reachable path:
  system crash, panic, or hang; data corruption (hardware registers, kernel
  data structures, or user data); use-after-free, double-free, or
  out-of-bounds memory access; security violation (privilege escalation,
  unauthorized information disclosure); hardware left in a permanently broken
  state; or an unconditional invariant violation that the rest of the kernel
  depends on.

- **`[CONCERN]`** — the harm is **conditional or unconfirmed**: incorrect
  behavior is plausible but depends on a platform configuration, DTS topology,
  or usage pattern the reviewer cannot verify from the diff and context files
  alone; a race condition whose interleaving is plausible but whose lack of
  serialization requires author confirmation; or a design whose safety depends
  on a guarantee the author should state explicitly but has not.

  Do not downgrade a proven race solely because it is timing-dependent.  If a
  concrete interleaving is reachable, no lock/refcount/lifetime rule excludes
  it, and the outcome is UAF, corruption, deadlock, or another definite safety
  failure, classify it as `[BUG]`.

- **`[MINOR]`** — **behavioral content exists** but no concrete harmful outcome
  is reachable today: a refactor introduced asymmetry on an error or teardown
  path that previously handled the condition correctly — the behavioral
  regression is real even if the allocator or surrounding code makes the
  practical outcome benign on current hardware.

- **`[NIT]`** — **zero behavioral content**: naming, whitespace, indentation,
  comment wording, or cosmetic style violations with no runtime impact.

**The two key distinctions:**
- `[BUG]` vs `[CONCERN]` — is the harm *guaranteed* on a concrete path, or
  *conditional* on something the reviewer cannot confirm from available context?
- `[MINOR]` vs `[NIT]` — does the finding have *any behavioral content* (even
  benign), or is it purely cosmetic?

**Concrete examples for each boundary:**

- **NULL dereference on every call to `foo_remove()` when device was probed**
  - Severity: `[BUG]`
  - Reasoning: Guaranteed crash on a concrete, reachable path (unbind).
- **Possible race between `foo_read()` and `foo_remove()` — UAF if remove can
  run without the expected module/session reference**
  - Severity: `[CONCERN]`
  - Reasoning: Harm would be real, but the reviewer has not confirmed whether
    lifecycle serialization excludes the interleaving; author should confirm.
- **Missing `clk_disable_unprepare()` on error path after line 342**
  - Severity: `[BUG]`
  - Reasoning: Resource leak — always-BUG exception. Object-lifetime check:
    clock is bounded-lifetime, obtained per-probe.
- **`pm_runtime_get_sync()` return value unchecked — device may be off**
  - Severity: `[CONCERN]`
  - Reasoning: Harm depends on platform PM behavior; not all SoCs enforce
    runtime PM.
- **Error path skips `mutex_unlock()` — deadlock on next call**
  - Severity: `[BUG]`
  - Reasoning: Guaranteed deadlock on reachable error path.
- **Lock ordering inconsistency between `foo_open()` and `foo_ioctl()`**
  - Severity: `[CONCERN]`
  - Reasoning: Deadlock requires concurrent open+ioctl from different threads;
    plausible but unconfirmed.
- **`kfree(ptr)` on error path where `ptr` is also freed by `devm_*`**
  - Severity: `[BUG]`
  - Reasoning: Double-free guaranteed on device unbind after probe error.
- **Missing `of_node_put()` after `of_find_node_by_name()` in probe — but device
  is platform_device with static DT node**
  - Severity: `[CONCERN]`
  - Reasoning: Refcount leak on a node that appears static in the reviewed
    target; not always-BUG without bounded-lifetime proof, but still worth
    discussion unless overlays/unbind/refcount observability are ruled out.
- **`return -EINVAL` without printing any diagnostic**
  - Severity: `[MINOR]`
  - Reasoning: Behavioral; silent failure is harder to debug, but no incorrect
    outcome.
- **Missing blank line between variable declarations and first statement**
  - Severity: `[NIT]`
  - Reasoning: Pure style — zero runtime impact.
- **`s/recieve/receive/` in user-visible error string**
  - Severity: `[MINOR]`
  - Reasoning: Behavioral content; affects grep-ability and user experience.
- **Tab vs spaces inconsistency in switch case**
  - Severity: `[NIT]`
  - Reasoning: Pure formatting — no behavioral impact.
- **Unused variable `ret` in function that always returns 0**
  - Severity: `[NIT]`
  - Reasoning: Cosmetic; compiler may warn but no runtime effect.
- **Error path `goto` skips `iounmap()` — but region was mapped with
  `devm_ioremap()`**
  - Severity: Dismissed
  - Reasoning: Gate 1 fails; `devm_*` handles cleanup automatically. Document
    as positive note.

**Relationship to named patterns**: the specific rules throughout this file —
the always-`[BUG]` list, the behavioral regression floor, per-pattern severity
caps (no-caller-in-series → `[MINOR]`, uncertain reachability → `[CONCERN]`,
context-file limitation → `[CONCERN]`) — are all applications of this gate to
common patterns.  They do not override Gate 3; they instantiate it.  When a
finding matches a named pattern, use that pattern's verdict directly.  When it
does not match any named pattern, apply Gate 3 to determine severity.

**Justification verification rule (mandatory — applies before writing any
finding body)**:
Every behavioral claim used as evidence for a severity decision — *"the
disable path also does not release"*, *"the allocator is idempotent"*,
*"this flag is never set at this point"* — must be verified by reading
the relevant code before it is written into the finding body.  Do not cite
claims that appear only in the commit message without confirming them in
the diff or surrounding code.  A justification that contradicts the Code
Logic Maps written in the same review is a self-audit failure: resolve the
contradiction before filing the finding.  If the relevant code is not among
the provided context files, you MUST first attempt **one** on-demand `Read`
of the relevant file under `<project_path>` (subject to the 3-read budget
in `core.md` Step 2) before downgrading.  If the read succeeds and confirms
the property, file the finding at full severity.  Only when the read fails
(missing file, oversize, or budget exhausted), explicitly note the limitation
and cap the finding at `[CONCERN]` rather than stating the claim as verified
fact — do not assert a behavioral property you cannot confirm from the
available diff, context files, and one on-demand read.

**Exception — always `[BUG]` after reachability and scope are proven**: the
following classes of defect are correctness violations regardless of whether the
resulting behavior "looks" harmless in a specific code path:
- Reachable resource leaks: kernel memory (`kzalloc` without matching `kfree`
  on all error paths), OF node references (`of_find_*` / `of_get_*` without
  `of_node_put()`), kobject references (`kobject_get()` without `kobject_put()`),
  kref references (`kref_get()` without `kref_put()`), device references
  (`get_device()` without `put_device()`), file descriptors, hardware IRQ lines.
  **Scope of this exception**: it applies to kernel-managed resources whose
  ownership semantics are unambiguous (every successful alloc requires exactly
  one free).  For subsystem-specific logical resources — trace IDs, reference
  counts, software-session slots, or any allocation whose lifecycle is governed
  by documented subsystem policy — the full validation rule applies instead of
  the always-[BUG] shortcut.  Before filing, read the corresponding **disable /
  teardown path** to establish the design intent: if the subsystem intentionally
  keeps the resource allocated across disable cycles (e.g. for post-session
  observability) and the allocator is idempotent on re-acquire, then Gate 2
  (harm) fails and the finding must be dismissed or downgraded.

  > **STOP — mandatory object-lifetime check (answer before filing any
  > reference-counted object leak as [BUG]):**
  >
  > *"Can this specific object be freed or unregistered during normal system
  > operation on the target platform?  Consider: is it statically allocated,
  > a fixed SoC peripheral, or hardware that is never hotplugged?"*
  >
  > - **YES** (object has a bounded lifetime — it can be freed during
  >   system uptime, e.g. a dynamically-created device, a hotpluggable
  >   peripheral, a heap allocation) → proceed with always-[BUG].
  > - **NO / NOT PROVEN BOUNDED** (object appears to live for system uptime,
  >   e.g. a fixed ACPI/DT SoC peripheral, a statically-registered device, or
  >   a firmware node with no normal removal path in the reviewed target) → the
  >   always-[BUG] exception does not apply.  Fall through to the full gate
  >   analysis.  Consider overlays, driver unbind, module unload, debug/refcount
  >   observability, and future platform reuse before dismissing.  Downgrade to
  >   `[MINOR]` or `[CONCERN]` only when those checks show no concrete bounded
  >   lifetime or harmful outcome; dismiss only with an explicit invariant.
  >
  > This check is **mandatory** for all reference types in the list above
  > (OF nodes, fwnodes, kobjects, krefs, `struct device`, etc.).  It does
  > NOT apply to resources with inherently bounded lifetimes (heap
  > allocations, file descriptors, IRQ lines, DMA buffers) where the
  > object is expected to be freed independently of platform topology.
- Sleeping in atomic context: `mutex_lock()`, `msleep()`,
  `schedule()`, or any function that may sleep, called in any atomic
  context — including while a spinlock is held (`spin_lock()`,
  `spin_lock_bh()`, `spin_lock_irqsave()`), from a softirq or hardirq
  handler, or within a section guarded by `local_irq_save()` /
  `local_irq_disable()`.
- `__copy_to_user()` / `__copy_from_user()` (unsafe variants that bypass
  the internal `access_ok()` check) called without a prior `access_ok()`
  check.  Note: the safe variants `copy_to_user()` / `copy_from_user()`
  call `access_ok()` internally since kernel 5.0 — do NOT file a `[BUG]`
  for absence of an explicit `access_ok()` before the safe variants.
  Any `copy_*_user()` variant called while holding a spinlock is `[BUG]`
  regardless of the safe/unsafe distinction.
After reachability and scope/category membership are proven, file these as
`[BUG]` directly; do not relitigate ordinary Gate 2 harm or Gate 3 severity.

**Signed/unsigned type mismatches on register reads** — apply the register
read data-flow checklist from Step 3c.2 before filing any finding.  A
`u32` value stored in an `int` local and immediately returned as `u32` is
safe (C99 §6.3.1.3 preserves the bit pattern); file at most `[NIT]` for
the style violation.  Only escalate to `[BUG]` if the signed intermediate
value is demonstrably used in signed arithmetic, a signed comparison, or
widened to a larger signed type in a way that produces a wrong result.

### Review Category Checklist

- **Correctness**: Logic errors, off-by-one, wrong conditions, NULL checks,
  integer overflow, use-after-free, uninitialised variables.
- **Locking & Concurrency**: Correct lock type, initialisation, consistent
  protection, lock ordering, IRQ-safe variants, sleeping in spinlocks.
- **Memory Management**: Allocation failure checks, `devm_` usage, leaks on
  error paths, correct `sizeof`.
- **Error Handling**: All paths handled, meaningful error codes, appropriate
  `WARN_ON`/`BUG_ON`:
  - Prefer `WARN_ON` for recoverable invariant violations.
  - Use `BUG_ON` only when continuing would corrupt kernel state.
  - Flag unconditional `BUG_ON` in driver code as `[CONCERN]`.
- **Kernel API Usage**: Correct API use, deprecated APIs avoided, correct
  memory barriers.
- **Style & Maintainability**: checkpatch-clean, clear names, accurate
  comments, no magic numbers, well-formed commit message (≤72 chars,
  imperative mood).
- **Documentation & ABI**: New sysfs/debugfs nodes in `Documentation/ABI/`,
  new DT bindings in `.yaml`, `MAINTAINERS` updated.
- **Kconfig / Build**: Correct placement, minimal `depends on`, correct
  `Makefile` entry, clean W=1 build.

The remaining categories are owned by their dedicated checklists and are
applied only when the corresponding step ref is present in this brief.  Apply
each from its own ref — do not duplicate its rules here:

- **Kernel Coding Style** — Step 3b (`refs/coding-style.md`).
- **Code Logic** — Step 3c (`refs/code-logic.md`).
- **DT / DT-Binding** — Step 3d (`refs/dt-binding.md`) and the driver `of_*`
  rules in Step 3d.3 (`refs/dt-driver.md`); apply only when triggered.
- **Hardware / Platform** — Step 3f (`refs/hardware-eng.md`); apply only when
  triggered.
- **Patch Scope** — Step 3e (`refs/commit-message.md`).

## Step 5 — Output Format

All output is written as **HTML**.  The authoritative per-commit and per-file
block structure — `.commit-header`, `.commit-summary`, the `Code Logic Maps`,
`DT / DT-Binding Notes`, `Hardware Engineering Notes`, `Issues`, `Minor / Style`,
and `Positive Notes` sections, including the exact `Not applicable: ...` bodies
and the Mode C per-file variant — is defined once in **Step 5b of
`refs/core.md`**.  Do not restate it here; follow that structure and map each
element to the CSS classes below.

### Overall Summary / Verdict Banner

Rendered as `<div class="verdict-banner [class]">` at the top of the page
(immediately after the header card).  Contains:
- The verdict pill (`READY TO APPLY` / `NEEDS FIXES` / `NEEDS DISCUSSION`).
- Stats row chips: commits reviewed, bugs, concerns, minor issues.
- Key findings grouped by category using `.findings-category` dividers and
  `.finding-card` elements.

**Verdict criteria**:
- `READY TO APPLY` — zero findings, or only `[MINOR]` and/or `[NIT]`
  findings; nothing blocks merging.  `[NIT]` findings count toward this
  verdict class but are **not** shown as individual cards in the banner —
  they appear only in the per-commit Minor / Style sections.
- `NEEDS DISCUSSION` — one or more `[CONCERN]` findings; no `[BUG]`
  findings.
- `NEEDS FIXES` — one or more `[BUG]` findings.

The verdict label used in the pill element and the frontmatter description is
`READY TO APPLY` (not `READY`).  Use this string consistently throughout.

**Verdict-banner dedup rule**: every `.finding-card` in the verdict banner is
a short summary that includes the patch subject line and an
`<a href="#patch-<N>-finding-<K>">see Patch N</a>` link to the canonical
per-commit card.  Do not duplicate full analysis in the banner: the canonical
per-commit card carries the full description, file reference, suggestion, and
Gate trace.  Banner card body text must stay concise (≤ 250 visible chars).

Severity levels: `[BUG]` · `[CONCERN]` · `[MINOR]` · `[NIT]`

**Severity scope definitions**:
- `[BUG]` — definite correctness or safety defect where reachability is
  certain and harm is concrete; always appears in the verdict banner as an
  individual finding card.  Use `[BUG]` when the exact triggering call
  sequence can be described and the outcome is unambiguously wrong.
- `[CONCERN]` — potential correctness or design issue where reachability is
  uncertain (depends on a race window, an unusual caller, or a design
  decision only the author can confirm) and needs discussion before merging;
  always appears in the verdict banner as an individual finding card.  Cross-
  reference Step 4 Gate 1: *"if reachability is uncertain, file as
  `[CONCERN]`"* — do not escalate to `[BUG]` when the triggering scenario
  is hypothetical.
- `[MINOR]` — real but low-impact issue (behavioral regression in an error
  path, style violation flagged by checkpatch, commit message problem) worth
  addressing but does not block merging; counted in the `minors` stat chip
  and listed under the STYLE / MINOR section of the verdict banner.
- `[NIT]` — purely cosmetic issue with zero behavioral content (naming,
  whitespace, comment wording, unnecessary parentheses); appears **only**
  in the per-commit Minor / Style sections.  Excluded from the verdict
  banner findings section and from all stat chips.  Do not use [NIT] for
  any finding that describes a behavioral change, however harmless.
