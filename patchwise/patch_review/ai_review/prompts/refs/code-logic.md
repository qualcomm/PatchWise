## Step 3c — Code Logic Mapping

Before writing findings, build a source-backed map for every added or modified C
function. Understand what the code does before judging correctness.

**Conditional sub-checklists (loaded only when the patch's diff matches the
trigger):** the always-included base below covers 3c.1 (Control-Flow), the 3c.2
header prose (data-flow audits, selector/cardinality, peer-dimension,
aggregate-vs-per-element, shared template mutation), 3c.5 (Before-vs-After
Delta), and 3c.6 (Subsystem Layering). The remaining 3c.2/3c.3/3c.4 specialised
sub-checklists live in `refs/code-logic-*.md` fragments. Each fragment lists
its own trigger; apply it on top of this base only when the diff matches.
When a fragment is not triggered, the corresponding hazard does not appear in
the patch and no finding is owed.

The on-demand source-read budget for Step 3c (and Step 3f) is
**budget: 6 targeted reads per patch**, with each read capped at the per-read
line limit recorded in `refs/review-constants.json`. Exhaustion does not lower the
evidence bar — record `unable to verify ... — source not in context files
(on-demand read attempted: <result>)` and downgrade reachability accordingly.

**Mandatory surrounding-code audit:** for every patch with function-level code
changes, Step 3c is incomplete until the review inspects and records:
- the entrypoint, callback registration, selector, descriptor table, or dispatch
  site that makes changed code reachable;
- callee/helper bodies whose failure contract or side effects matter;
- sibling or alternate paths that can still reach the same state, abstraction,
  or hardware mode; and
- lifecycle/workflow edges that enter or leave changed state, including paired
  callbacks, setup/teardown, enable/disable, open/release, prepare/unprepare,
  async callbacks, remove/shutdown, and all non-success return paths.

Record proof in the Code Logic Maps `<pre>` block with these exact labels:
`codebase audit: entrypoints ...`
`codebase audit: callees ...`
`codebase audit: siblings ...`
`state/lifecycle: ...`
Use `none` only after inspecting and proving the bucket truly does not exist;
"obvious from diff", "self-contained", and "reasonable assumption" are not
proof. Audit notes such as "verified safe", "for completeness", or "worth
verifying" are evidence only; do not emit finding-cards unless gate analysis
proves a present-tree defect or real local style issue.

**Source-aware lifecycle exploration baseline:** for function-level changes, do
not stop at the triggered rule card. Build a small edge matrix before any
safety dismissal:
- **entry edge**: every caller/dispatcher/callback/selector state that can reach
  the changed code;
- **callee edge**: each helper return value/side effect/ownership transfer used
  by the changed code;
- **exit edge**: every success, failure, early return, goto, and fallthrough path;
- **paired edge**: the matching cleanup/release/unprepare/disable/stop/remove
  path and the state token that proves it is the same session/resource;
- **concurrency edge**: IRQ/workqueue/timer/runtime-PM/remove paths that can
  observe or mutate the same state.

A `SAFE` dismissal is valid only when this matrix names the source-backed
guard or state token for the relevant edge. Configuration/state facts such as
`irq_enabled`, compatible strings, mode flags, or descriptor presence do not
prove session ownership unless the paired entry and exit paths both test the
same token. If an edge is unverified after the targeted-read budget, write
`unable to verify` and cap severity per the context limitation instead of
claiming safety.

### 3c.1 Control-Flow Picture

**Scope gate:** if the patch has no C function changes (pure DTS/YAML/Kconfig/
Makefile/comment-only), write `No function-level changes — N/A.` in Code Logic
Maps and skip 3c.1–3c.5. Do not trace control flow through DTS/YAML.

For each changed function, record:
- entry conditions, guard clauses, early returns, gotos, and happy path;
- every exceptional path: trigger, cleanup, and exit;
- loops: variable, termination, side effects, zero-iteration behavior;
- intentional `fallthrough` in `switch` statements;
- any `-Wswitch` warning in `tmp/patch_<N>_build.txt` for touched files as a
  correctness issue, not style;
- every `dev_err`/`dev_warn`/`pr_err` condition. If two diagnostics fire for the
  same triggering condition, file redundant logs as `[MINOR]`; if conditions
  differ, do not conflate them;
- Duplicate teardown/shutdown risk: for label chains, helper layering, and
  `switch` fallthrough, enumerate each release/unregister/disable and prove each
  reachable path runs it exactly once per resource instance;
- Managed-lifecycle helpers: when code uses driver-core managed objects or
  autoremove flags, read the helper contract before adding manual cleanup.
  Manual deletion of managed objects is a bug unless the API explicitly permits
  it for that object state;
- sparse/checkpatch/compiler warning attribution: file only when the patch
  introduces it, touches the warned code, or changes the API/struct contract
  that makes old code newly wrong. Legacy unchanged warnings are context only;
- series-exposed legacy bugs: adding a platform, compatible, selector, fallback,
  routing option, or resource count can make old helpers or error paths newly
  reachable/required. Report those as pre-existing issues exposed by this patch,
  not out-of-scope legacy code.

**Branch-precedence / condition-widening diversion (trigger: a patch adds a
disjunct to an `if`/`else if`/`switch` guard, or reorders branches, in a
multi-way chain whose arms have different side effects).** When a new term widens
a branch condition or a branch is moved earlier, an input that previously fell to
a later arm is now captured by the earlier arm. If the earlier (now-taken) arm
omits a side effect the bypassed arm performed — PHY/clock/power init, lock
acquisition, a state flag (`->enabled`, `->plugged`, `->started`), refcount, or
resource setup — the diverted input runs against state the bypassed arm was
responsible for establishing.

**Bad-pattern shape (subsystem-agnostic):**

    /* before: input X (neither A nor B) fell to the else arm, which inits */
    if (cond_A) {                 handle_A(ctx);
    } else if (cond_B) {          handle_B(ctx);
    } else {                      setup_and_init(ctx);   /* sets ctx->ready, powers hw */
    }

    /* after: condition widened with new disjunct, branch moved first */
    if (cond_B || new_extra_flag) {   /* X with new_extra_flag now matches HERE */
        handle_B(ctx);                /* reads ctx->ready / hw — never set for X */
    } else if (cond_A) {              handle_A(ctx);
    } else {                          setup_and_init(ctx);   /* X no longer reaches this */
    }

The widened term can be: a new enum/flag OR-ed into an existing equality test, a
status field added alongside a hardware-register compare, a newly-handled
event/mode, or a branch physically reordered to the top. The harm appears when
the taken arm assumes a precondition the bypassed arm used to establish.

**Decisive evidence (all three required):**
(1) the widened/reordered guard (quote the new disjunct or the moved branch, and
name the input value that newly matches it but did not before);
(2) the arm that input used to reach and the side effect it performed there
(quote the bypassed arm and the init/lock/flag/setup call);
(3) the taken arm's body showing it does NOT perform that side effect and instead
depends on it (quote the dependent read/call and the failure mode — `-ENXIO`,
NULL deref, unlocked access, uninitialized hardware).

**Valid dismissal proofs (cite source for each):**
- the new disjunct can never coincide with the bypassed-arm input — the two
  conditions are provably mutually exclusive at the source (quote the producer
  that sets them, not just an assertion they "differ"). The proof MUST name the
  NEW disjunct's operand (the identifier the `||` added), not merely the
  pre-existing branch values; "the old return values are mutually exclusive"
  does not clear the new term. If the producer parses the connect-status field
  and the diverted-flag field as INDEPENDENT bits of one notification (two
  `FIELD_GET(MASK, word)` calls of distinct state/irq masks from the same
  word, or two adjacent `:1` bitfields named for the two concepts), they CAN
  co-occur — name the producer line that COUPLES them (a guard that clears the
  flag when the state bit is set, a single shared bit, or an explicit
  either/or decode), or the mutual-exclusivity dismissal is refuted by source;
- the taken arm performs the same precondition setup itself (quote its init/lock
  line);
- the precondition is established unconditionally before the chain (quote the
  earlier setup that runs on every entry regardless of branch);
- the diverted input is unreachable for the new term (quote the caller proving
  the flag is only ever set together with the bypassed-arm condition).

**Disqualified dismissals:**
- "the original branch values are mutually exclusive" while ignoring the NEW
  disjunct — mutual exclusivity of the old equality cases says nothing about an
  OR-ed flag that is set on an independent path;
- "the reordering is logically correct / cleaner" without tracing an input that
  changes which arm it lands in;
- "both branches handle IRQ/the event" without proving the taken arm reaches the
  bypassed arm's init/lock/flag;
- "the two are independent paths that both route correctly" / "prioritizes the
  event before replug" — asserting the routing is fine without tracing what
  happens to an input that is NOT a genuine IRQ (an initial connect carrying the
  new flag) when it lands in the IRQ arm instead of the plug arm;
- "the flag is only set for genuine events, never together with a fresh
  connect" without quoting the producer line that COUPLES the connect-status
  field to the diverted-flag field. If the producer parses the two as
  independent bits of one notification (e.g. two `FIELD_GET(MASK_A, word)` /
  `FIELD_GET(MASK_B, word)` calls, or two adjacent `:1` bitfields named for the
  two concepts), they CAN co-occur — the dismissal is refuted by source. To
  clear, name the producer's coupling check (a guard that clears `hpd_irq`
  when `hpd_state` is set, a single shared bit, or an explicit either/or
  decode), not just the consumer-side ternary;
- "the new path is rare / driver doesn't emit it yet" — frequency and
  not-yet-wired producers do not remove the hazard once any producer sets the
  flag;
- "same shape as upstream" without quoting upstream's equivalent precondition.

Severity: `[CONCERN]` when the diverted input lands in a functionally-wrong arm
(wrong handler, missing notification) without a crash; `[BUG]` when the bypassed
side effect was required for safety/correctness — skipped PHY/power init,
unacquired lock on shared-state mutation, or an unset flag that later code trusts
— producing AUX/IO failure, NULL deref, data race, or a dead device.

Record under `codebase audit: siblings`: the input value that changes arms, the
bypassed arm's side effect, and the proof (mutual-exclusivity producer, or the
taken arm's own setup) — naming the line, not asserting it.

**Annotation consistency rule (mandatory):** inline severities in Code Logic Maps
(`← BUG`, `← MINOR`, `← NIT: see below`, etc.) and cross-references in Hardware
Engineering Notes must match the final Issues card severity. Because HTML shows
Code Logic Maps before Issues, finalize Issues severities first, then write map
annotations; fix any mismatch before writing the commit block.

### 3c.2 Data-Flow Picture

For each changed function, trace inputs, transformations, and outputs:
parameters, globals/statics, hardware registers, userspace buffers, return
values, pointer writes, state mutations, register writes, and callbacks. Flag any
input reaching sensitive sinks (allocation size, array index, copy_to/from_user
length, hardware register) without validation.

**selector/cardinality audit:** enumerate every selector space and cardinality
contract touched: array indices, enums, DT binding IDs, pad/stream counts,
provider arrays, parent maps, and `*-names` lookups. When one surface expands or
reorders, compare every peer surface naming the same logical resource. Record
proof in `codebase audit: entrypoints ...` for dispatch/selector sites,
`codebase audit: callees ...` for provider/helper tables, and
`codebase audit: siblings ...` for alternate modes or sibling consumers. If a
peer surface is YAML/DTS, cite DT / DT-Binding Notes instead. Mismatched
count/order/meaning is reportable even when each file looks plausible.

**Peer-dimension admission audit:** if an admission/control path validates one
capacity or selector dimension, identify every peer dimension required for the
operation. File a finding when the patch checks only one axis while another
required axis remains unchecked.

**Role-typed endpoint audit:** when a helper takes a role-bearing argument
(producer/consumer, master/slave, source/sink, CPU-side/codec-side,
ingress/egress, parent/child, primary/secondary), prove the patch passes the
role the surrounding intent asks for — taken from flag/state names, commit
text, routes/widgets/ports, or peer drivers, not the variable name alone.
Also check secondary arguments (`clk_id`, direction, index, mode) and the
return. Concrete instance: ASoC `snd_soc_dai_set_sysclk()` choosing between
`cpu_dai` and `codec_dai`.

**Aggregate-vs-per-element scale audit:** when a per-element quantity (one
node's/channel's/lane's/port's bandwidth, length, count, or rate) is divided,
multiplied, or otherwise scaled by a width/size/count/stride, prove the scale
factor has the same granularity as the element being scaled.

**Bad-pattern shape (subsystem-agnostic).** This is a defect anywhere a
list-iteration uses a container-level scale factor while the element struct
exposes its own same-dimension field:

    list_for_each_entry(e, &container->elems, link) {
        u64 v = scale_op(per_element_quantity(e), container->scale);
                                                  ^^^^^^^^^^^^^^^^^^^^
                                                  WRONG — should use e->scale
        agg = combine(agg, v);
    }

    /* and the element table carries differing scales */
    static struct elem table[] = {
        { .scale = 4 },
        { .scale = 8 },
        { .scale = 16 },
    };

The substitution mis-scales every element whose `.scale` differs from the
container value. The narrowest/widest elements are starved or over-served
while each line still looks plausible. **This is the bug REGARDLESS of how
the dismissal is framed; framing does not turn a same-dimension field into
something else.**

**Decisive evidence requirements.** This rule rests on three facts about
the patch and surrounding code; a finding or dismissal must produce all
three:

1. **Element has a same-dimension field** — name it (e.g. `e->scale`,
   `node->buswidth`, `chan->width`, `port->stride`).
2. **Element values are heterogeneous** — quote at least two differing
   values from the table or prove all values match.
3. **Scale factor source** — quote the diff line where the divisor/scale
   is read (`container->`, `desc->`, `provider->`, etc.).

**File a finding:** `[BUG]` when (1)+(2)+(3) hold and the mis-scale
changes a programmed hardware/clock/bandwidth value; `[CONCERN]` when the
differing-value element is plausible but not provable from context.

**A dismissal is valid ONLY by proving one of these, with citation:**

- **Homogeneity** — every element in the relevant table shares the same
  same-dimension value. Cite the value AND the count of elements checked
  (e.g. "all 47 entries have `.scale = 8`, verified by inspection of
  table at `path/to/file.c:NNNN`").
- **Single-element scope** — the calculation is not over a list/iteration;
  no aggregation; the scale factor and the element are the same object.
- **Field re-purposed at non-same-dimension** — the scaled-by field is a
  numerator multiplier, message-unit, encoding constant, or a different
  dimension entirely. To use this, **quote the reader site of the
  per-element field** showing it being used for a different purpose
  than the rule assumes; without the quote, this dismissal does not
  apply (a same-named, same-dimension field is presumed to play the
  same role until source proves otherwise).

**Disqualified dismissals.** A dismissal does NOT rescue the issue
when it relies on any of these patterns; if you find yourself writing
one of these, file the finding instead:

- **"Different purpose"** without quoting the reader site of the
  per-element field. A claim that the per-element field is "used for X"
  must be backed by a `grep`-able quote of the function/site where it is
  read, not by inference from the field's name or location.
- **"Matches subsystem convention"** without naming the convention
  function. Cite the in-tree reference function that implements the
  convention and quote the line where it performs the scale operation.
  A peer/sibling driver doing the same wrong thing is not a convention.
- **"Container value is the right scale for the aggregate result"** —
  this is the bug, not a discharge. The aggregate is built FROM
  per-element values; the per-element scale must apply BEFORE
  aggregation. If the framing claims otherwise, recheck the order:
  is it `aggregate(scale(elem))` (correct) or `scale(aggregate(elems))`
  (almost always wrong when elements differ)?
- **"The patch comment says it follows the convention"** — the patch's
  own commit message is not evidence. The reference function's source
  is.

**Required record format.** A discharge or finding for this rule must
include, under `codebase audit: callees ...`:

- the per-element field name and its observed value range (or proof of
  homogeneity);
- the diff line where the scale factor is read;
- for any dismissal, a **quoted line** from the cited reference function
  showing what the per-element field is actually used for, OR the
  homogeneity proof. Without one of these quotes, file the finding.

**Shared template mutation:** probe-time mutation of global/static templates,
descriptors, parent maps, or frequency tables needs proof of single-instance
exclusivity or exact restoration before another instance can observe it. Name the
writer, later readers, and invariant; otherwise file the shared-state defect.
If a static/global descriptor stores dynamically allocated framework objects,
every error path that frees those objects must also clear the retained pointer;
otherwise probe retry or rebind can reuse freed state.

### 3c.5 Before-vs-After Delta

For each changed function, state:
- what old code did from `-` and context lines; for new functions, write
  `Function did not exist; introduced by this patch.`;
- for renamed/moved functions, state `Function renamed from <old>() to <new>()`
  or `moved from <file_A> to <file_B>` and confirm logic is identical; mixed
  rename+logic changes are `[CONCERN] Patch Scope`;
- what new code does from `+` lines; and
- why the change is needed. If the commit message lacks the why, note that and
  cross-reference the 3e.3 body-quality `[MINOR]`; do not substitute your own
  inference as the author's explanation.

This delta is the foundation for every Gate Rules correctness finding.

**Relocated teardown / bookkeeping step audit.** When the diff *removes* a
teardown or bookkeeping statement from inside a helper function body — a
`list_del()` / list move, `*_free()` / `kfree()` / `dma_*free*()`, `*_put()` /
refcount decrement, `*_release()` / `*_del()` / `*_destroy()`, a pointer-NULL,
or a flag/counter reset — and relocates it into *some* call sites, audit
**every** caller of that helper from source. A second caller that still reaches
the helper and depended on the removed step now performs it nowhere, which
turns into a leak, double-free, stale-pointer, or use-after-free.

**Bad-pattern shape (subsystem-agnostic):**

    /* BEFORE: helper owned the unlink-then-free */
    helper(obj):
        do_remote_op(obj);
        list_del(&obj->node);   /* removed by the patch */
        free(obj);

    /* AFTER: patch moves list_del into ONE caller … */
    caller_A(obj):              /* e.g. the success path */
        list_del(&obj->node);
        helper(obj);

    /* … but caller_B still calls the helper directly */
    caller_B(obj):              /* e.g. an error/unwind path */
        list_add(&obj->node, &list);   /* obj is on the list */
        if (fail)
            goto err;
    err:
        helper(obj);            /* frees obj but never unlinks it → UAF */

This is exactly the misc/fastrpc v8 2/4 regression: `list_del()` was moved out
of `fastrpc_req_munmap_impl()` into `fastrpc_req_munmap()`, but
`fastrpc_req_mmap()`'s `err_assign:` path calls `fastrpc_req_munmap_impl()`
directly after the buffer is already on `fl->mmaps`, so the freed buffer stays
linked.

**Decisive evidence (all three required):**
(1) the removed teardown/bookkeeping line in the helper diff (quote it and name
the helper);
(2) the relocated copy in the caller(s) that regained it (quote each);
(3) at least one other caller that reaches the helper without performing the
step (quote the call site and show the object is in the state the removed step
was responsible for unwinding — on a list, holding a ref, non-NULL, etc.).

**Valid dismissal proofs (cite source for each):**
- the helper has exactly one caller (quote the single call site — nothing else
  depended on the step);
- every caller re-performs the step before/after the helper (quote each
  caller's copy);
- the helper still performs the step unconditionally by a different mechanism
  the patch added (quote it);
- the object the step acted on is provably not in that state at the other
  caller (e.g. never added to the list on that path — quote the path).

**Disqualified dismissals:**
- "the success-path caller handles it" without enumerating the error/unwind
  callers that also reach the helper;
- "the refactor just moves code" — moving a teardown step changes *which*
  callers perform it; relocation is not a no-op until every caller is checked;
- "the helper is only meant to be called from the new caller" without a source
  guarantee that no other path reaches it (grep the callers).

Severity: `[BUG]` when a reachable caller leaks, double-frees, or leaves a
freed object linked/dereferenceable; `[CONCERN]` when reachability of the
deficient caller is uncertain after reading the call graph.

### 3c.6 Subsystem Layering / Placement

A patch can be locally correct but wrong for upstream shape. Do not green-light
vendor/core coupling with a positive note; surface it as `[CONCERN] Layering`
when unclear so the verdict becomes NEEDS DISCUSSION.

Apply when a hunk:
- adds a driver/vendor entry to a core-subsystem global table/list (for example
  `&<vendor>_bus_type` in `iommu_buses[]`, bus/notifier/ops arrays in
  `drivers/iommu/`, `drivers/base/`, `drivers/of/`, `kernel/`, or `mm/`);
- includes a driver-private/vendor header in core code;
- registers driver functionality with `core_initcall`/`postcore_initcall`/
  `subsys_initcall` when it could otherwise be modular;
- exports a vendor-specific symbol from core, or adds `#ifdef CONFIG_<VENDOR>_*`
  inside a core framework file.

Ask whether a vendor-specific construct is being threaded into a generic
framework, whether subsystems become coupled, whether vmlinux is forced to carry
modular-driver code, and whether a generic mechanism (standard `platform_device`
child, existing bus type, or new generic framework facility) would solve it.
Clear only when placement is genuinely generic/reusable under a non-vendor name
or maintainer-acknowledged in-thread; say which. Otherwise file `[CONCERN]
Layering` and name the generic alternative. This is design discussion, not a
crash `[BUG]`; the validator check `core_table_vendor_entry_source_aware`
enforces that such hunks are not silently cleared.
