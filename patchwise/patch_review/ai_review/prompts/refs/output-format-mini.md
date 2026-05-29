# Output Format Mini-Contract

Return a concise per-patch review result. Do not emit HTML unless the
orchestrator explicitly asks for an HTML block.

When the orchestrator asks you to write a block file, write exactly one complete
`<div class="commit-block">...</div><!-- /commit-block -->` fragment. The
`STEP_COMPLETION_RECORD ... -->` comment is part of that fragment and must stay
inside the outer `.commit-block`, immediately before its final closing
`</div><!-- /commit-block -->`. Do not close `.commit-block` before the step record,
and do not add a second closing `</div><!-- /commit-block -->`.

## HTML Block Contract

Use this order for block-file output:

```html
<div class="commit-block">
  <div class="commit-header">
    <span class="commit-hash">SHORT_HASH</span>
    <span class="commit-subject">PATCH SUBJECT</span>
  </div>
  <div class="commit-body">
    <p class="commit-summary">...</p>
    <h3>Code Logic Maps</h3>
    <pre><strong>codebase audit: entrypoints</strong> ...

<strong>codebase audit: callees</strong> ...

<strong>codebase audit: siblings</strong> ...

<strong>control-flow:</strong> per changed function, the branch/loop/return structure the diff alters

<strong>data-flow:</strong> how values/ownership/error encodings move across the changed boundary

<strong>state/lifecycle:</strong> workflow/ownership edge matrix for changed state, callbacks, setup/teardown, and failures

<strong>before-vs-after delta:</strong> behavior the patch removes vs adds, derived from the diff's -/+ lines

<strong>[optional] call-graph:</strong> ... (only when caller/callee reachability is non-obvious beyond the audit lines)

<strong>[optional] on-demand read:</strong> &lt;path&gt; — &lt;reason&gt; (one line per targeted source read)</pre>
    <h3>Hardware Engineering Notes</h3>
    <p>Not applicable, or concrete hardware/PM/IRQ/DMA/resource notes.</p>
    <h3>DT / DT-Binding Notes</h3>
    <p>Not applicable, or concrete binding/DTS/driver contract notes.</p>
    <h3>Rule Card Coverage</h3>
    <ul>
      <li><code>card-id</code>: checked/finding/inconclusive — one sentence of evidence.</li>
    </ul>
    <h3>Issues</h3>
    <!-- One canonical finding-card per finding; the validation trace lives in
         .body (never in .suggestion). For [NIT] use the Style track variant. -->
    <div class="finding-card concern" id="patch-N-finding-1">
      <span class="badge concern">[CONCERN]</span>
      <span class="title">Short finding title</span>
      <div class="body">What the changed code does and why it is a risk.
        (Gate 1: [sub-rule: none] reachable via &lt;caller() → target()&gt;;
         Gate 2: &lt;concrete harm&gt;; Gate 3: [CONCERN] — &lt;why this tier&gt;)</div>
      <div class="file-ref">path/to/file.c:line</div>
      <div class="suggestion">Minimal fix or required proof.</div>
    </div>
    <!-- or, when nothing is found: --> <p>No issues found.</p>
    <h3>Commit Message</h3>
    <p>...</p>
  </div>
  <!-- STEP_COMPLETION_RECORD
  step_1_read_diff: DONE
  step_2_read_context: DONE
  step_3_read_tests: DONE
  step_3b_coding_style: DONE
  step_3c_code_logic: DONE
  step_3d_dt_binding: DONE or N/A
  step_3e_commit_message: DONE
  step_3f_hardware_eng: DONE or N/A
  step_4_gate_applied: DONE bugs=N concerns=N minors=N nits=N
  step_5_html_written: DONE
  codebase_audit: DONE entrypoints=N callees=N siblings=N files=[path1,path2]
  rule_card_coverage: DONE cards=[card-id,...] missing=[] inconclusive=[card-id,...]
  evidence_manifest: DONE path=<Evidence file from prompt>
  on_demand_reads: N [path1,path2] or 0 []
  self_audit: PASS
  -->
</div><!-- /commit-block -->
```

Mandatory block rules:

- The `Code Logic Maps` `<pre>` must contain the three `codebase audit:` lines,
  the mandatory `state/lifecycle:` workflow line, and the three analytical lines
  (`control-flow:`, `data-flow:`, `before-vs-after delta:`). The audit lines
  record which surrounding code you inspected; the analytical and lifecycle lines
  prove you understood what the diff changes and how every changed workflow edge
  enters/exits ownership. `call-graph:` and `on-demand read:` lines are optional —
  include them only when the trigger applies. For a trivial one-line change the
  analytical/lifecycle lines may be brief (e.g. `state/lifecycle: no changed
  state owner or paired cleanup`) but must still be present.
  Use only these line labels — `codebase audit:`, `control-flow:`, `data-flow:`,
  `state/lifecycle:`, `before-vs-after delta:`, and the optional `call-graph:`,
  `on-demand read:`. Do not invent ad-hoc labels (e.g. `cleanup-audit:`,
  `zero-operand-audit:`); fold such reasoning into the `data-flow:` or
  `state/lifecycle:` line so the map shape stays consistent across patches.
  Wrap each line's label in `<strong>...</strong>` (the label being everything up
  to and including the first `:`) and separate items with a single blank line so
  the rendered map is readable. Inline tags inside `<pre>` are honoured by browsers,
  and the literal label tokens (`codebase audit: entrypoints`, etc.) remain
  intact so the validator's label checks still pass.
  For DTS/YAML-only patches, do not write `codebase audit: N/A`; map
  `entrypoints` / `callees` / `siblings` to the relevant binding consumers,
  schema/property readers, parent or sibling DTSI/DTS files, examples, or board
  variants you checked.

- Include both `<h3>Hardware Engineering Notes</h3>` and
  `<h3>DT / DT-Binding Notes</h3>` in every block. Use `N/A` / `Not
  applicable` only after checking the packet evidence. If
  `step_3f_hardware_eng: DONE`, the Hardware Engineering Notes must cite
  concrete evidence from the patch/context instead of boilerplate. For
  thermal/cooling DTS, name values or wiring such as trip temperature,
  hysteresis, `#cooling-cells`, `tmd-names`, `cooling-device`, provider/
  consumer phandles, or QMI instance/service IDs.
- Keep `step_3f_hardware_eng` consistent with the section body: write `DONE`
  whenever the Hardware Engineering Notes contain real hardware findings
  (registers, IRQ/DMA, PM/clock/regulator, thermal/cooling wiring, QMI/firmware
  IDs, lifecycle). Use `N/A` ONLY when the body is exactly the "Not applicable:
  …" sentence. A block that marks `N/A` but writes substantive hardware notes
  is a self-audit failure.
- Format the Hardware Engineering Notes (and DT / DT-Binding Notes) for
  readability: when the section makes more than one distinct point, use a
  separate `<p>` per point with a bold lead-in
  (`<p><strong>Topic:</strong> …</p>`), or a `<ul><li>…</li></ul>` list — never a
  single multi-hundred-word `<p>` blob mixing unrelated facts. A single short
  `<p>` is fine when there is only one point.
- Start selected-card review from the packet's `focused-review-obligations`
  section, then inspect the matching hunks in `focused-rule-evidence`. Each
  obligation ID is a trigger-specific checklist item selected from the diff. Do
  not clear a card without visibly dispositioning every obligation ID for that
  card as `FINDING`, `SAFE`, or `INCONCLUSIVE` in Rule Card Coverage or the
  relevant Code Logic / DT / Hardware notes. A bare `checked`, `PASS`, or
  `No issues found` does not satisfy an obligation ID.
- Include `<h3>Rule Card Coverage</h3>` whenever the packet selects one or more
  rule cards. List every selected card ID exactly once, with one of these
  card-level statuses: `checked` only when all focused obligation IDs for the
  card are `SAFE` or already covered by a counted `FINDING`; `finding` when the
  card produced a finding; or `inconclusive` when packet context is missing.
  Each `checked` entry must cite concrete focused evidence from the packet, such
  as a file path, symbol, compatible string, register address, or property name,
  and name the obligation IDs it cleared. The list must use the exact card IDs
  from packet metadata; do not replace it with generic prose such as "all rules
  checked".
- Include `rule_card_coverage: DONE cards=[...] missing=[] inconclusive=[...]`
  in the step record whenever the packet selects rule cards. Put every selected
  card ID in `cards=[...]`; put skipped/absent card IDs in `missing=[...]`; put
  evidence-limited card IDs in `inconclusive=[...]`. If no cards were selected,
  write `rule_card_coverage: N/A no selected rule cards`.
- Include `evidence_manifest: DONE path=<Evidence file from prompt>` in every
  step record when the prompt names an Evidence file.
- Include `codebase_audit: ... files=[...]` and/or `on_demand_reads: ...` with
  every required source file you actually used from the packet/evidence
  manifest. If required evidence is missing, write an inconclusive check instead
  of silently clearing it.
- Include `self_audit: PASS` only after confirming the block has exactly one
  outer `.commit-block`, mandatory sections, valid finding-card ids, and the
  step record before the final close marker.
- Write sidecar progress separately; do not use it as a substitute for the
  embedded `STEP_COMPLETION_RECORD`.

## Finding Format

For each finding, use this shape:

```text
[LEVEL] Title
File: path/to/file:line-or-area
Rule: card-id or base-contract
Evidence: concrete changed code, property, API, or checker output
Reasoning: why the evidence proves the issue or credible risk
Impact: expected failure mode or maintenance risk
Suggestion: minimal fix, question, or required proof
```

Allowed levels are `[BUG]`, `[CONCERN]`, `[MINOR]`, and `[NIT]`.

## Mandatory Validation Trace

Every finding's body MUST end with the applicable parenthetical trace. A finding
without its trace is invalid and will be rejected. The three gates are sequential
and non-bypassable:

- **Gate 1 — Reachability:** can you construct the exact call sequence/condition
  that reaches the bad state in the tree *after the full series is applied*?
  (Patch-introduced reachability counts — it is not "future risk".)
- **Gate 2 — Harm:** does that reachable condition cause incorrect behavior,
  safety risk, or a real behavioral regression?
- **Gate 3 — Severity:** given Gate 1 + Gate 2, which tier is correct?

For `[BUG]`, `[CONCERN]`, and behavioral `[MINOR]` — include the
`[sub-rule: <name or "none">]` tag inside the Gate 1 clause:

```text
(Gate 1: [sub-rule: <name or "none">] reachable via <caller() → target() path or condition>;
 Gate 2: <concrete harm, e.g. "UAF on unbind", "data corruption">;
 Gate 3: <why this tier and not higher/lower>)
```

For `[NIT]` (style track — zero runtime harm, no gates):

```text
(Style track: <style rule violated>; Runtime impact: none; Severity: [NIT].)
```

For always-`[BUG]` exceptions (leak/double-free/UAF/stale-pointer categories):

```text
(Always-BUG exception: <category>; Reachability: [sub-rule: <name or "none">] <caller/path>; Scope/category check: <result>.)
```

For a resource-leak always-`[BUG]` exception, `Scope/category check` must include
`object-lifetime check: <bounded|static/unbounded + rationale>`; `static/unbounded`
(fixed SoC peripheral / statically-registered device) means the shortcut does NOT
apply — fall through to the normal three gates. Place the trace in the finding
body only, never in the suggestion.

## Inconclusive Check Format

If a selected card requires evidence not present in the packet, record it:

```text
[INCONCLUSIVE] card-id
Missing evidence: exact file/function/path/fact needed
Why it matters: short reason this evidence controls the rule decision
```

Also mark that card as `inconclusive` in the Rule Card Coverage section and in
the `rule_card_coverage:` step-record line.

## No-Finding Format

If no issues are found, return:

```text
No findings.
Rule coverage: card-id=checked(<focused evidence cited>), card-id=checked(<focused evidence cited>)
Inconclusive checks: none
```

Do not write `No findings` or `<p>No issues found.</p>` until every selected
rule card has a visible `checked`, `finding`, or `inconclusive` entry and the
step record names the same selected card IDs.

## Constraints

- Do not report unsupported findings.
- Do not hide required inconclusive checks.
- Do not downgrade a confirmed security, memory ownership, build, or ABI break
  because the patch appears small.
- **No defensive downgrade.** When a selected rule card's `Must Check` item
  fails AND the failing path is reachable on changed code AND the harm class
  is one of `{NULL/ERR_PTR dereference, use-after-free, double-free, memory
  corruption, kernel panic, kernel-info leak to userspace, ABI/DT contract
  break with deployment impact}`, file the finding at `[BUG]`. Downgrading
  Gate 3 to `[CONCERN]` because "the maintainer may know better" or "this is
  a v3 series so it has probably been reviewed" is not a valid path — file
  `[BUG]` with the gate trace; the maintainer can push back. The same rule
  applies to a corresponding always-`[BUG]` exception when one of those
  categories is named.
