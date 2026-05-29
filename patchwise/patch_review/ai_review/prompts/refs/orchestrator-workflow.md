# Orchestrator Workflow

This file is the post-startup continuation path for normal reviews.
`refs/startup-workflow.md` owns Steps 0-3: repo sync, commit/patch
acquisition, startup artifact generation, dependency graph creation, and the
shared test summary table. Read this file only after startup completes through
Step 3. Do not rerun startup here unless `refs/startup-workflow.md`
explicitly directs a restart.

## Two-Role Architecture

After `refs/startup-workflow.md` Step 3, this skill uses a two-role design to
keep each patch's review context clean and bounded.

**Orchestrator** (the main agent that invokes this skill):
- Reuses the startup artifacts already produced by
  `refs/startup-workflow.md`: series manifest, patch corpus, per-patch diff /
  build / DT / rules artifacts, dependency groups, and shared test summary
- Spawns **Per-Patch Reviewer Subagents** using dependency-aware parallelism:
  patches that share no files with other patches in the series are spawned
  concurrently; patches with manifest dependencies are spawned in dependency
  order (see § Per-Patch Reviewer Subagent below)
- After all subagents complete: validates every per-patch block file. In
  daemon-managed runs, stops there and writes the completion marker so the
  daemon can assemble, validate, and clean up. In standalone/manual runs,
  assembles per-patch block files into the HTML in order, appends the footer,
  reconciles the verdict banner, prints the terminal summary, and cleans up.

**Per-Patch Reviewer Subagent** (one fresh instance per patch):
- Receives exactly one patch's diff content, context file paths, contamination
  notes, series summary, and paths to its per-patch test result files
  (`tests_<slug>.txt`, `patch_<N>_build.txt`, `sparse_<slug>.txt`,
  `patch_<N>_dtbinding.txt` when applicable)
- Applies Steps 3b–3f and Step 4 to that single patch
- Writes its `<div class="commit-block">` to its own block file
  (`tmp/patch_<N>_block.html`) — never to the shared HTML file directly
- Writes its checkpoint sidecar line
- Returns a compressed findings record to the orchestrator
- Terminates — its full context is released before the next group starts

**Why per-patch block files:** subagents within a concurrent group run in
parallel and must not write to a shared file.  Each subagent writes its commit
block to `tmp/patch_<N>_block.html`; the daemon assembles them in patch order
after marker acceptance in daemon-managed runs, while standalone/manual runs
use the orchestrator's Step 6.4 assembly path.  Patches that share files with others are
still spawned in dependency order so that cross-file review context is
preserved.

**Context isolation guarantee:** each subagent starts with a clean context
containing only: its generated `patch_<N>_review_packet.md`, the assigned patch
diff, at most 4 context files, the shared `tests_<slug>.txt` and
`sparse_<slug>.txt`, plus its per-patch `patch_<N>_build.txt` and
`patch_<N>_dtbinding.txt` when applicable. No prior patch's diff, file reads, or
reasoning is present.

**Step numbering convention:**
- **Startup Steps 0–3** live in `refs/startup-workflow.md`.
- **Decimal sub-steps** (`6.1–6.10`) — orchestrator internal steps in this file.
- **Letter sub-steps** (`3a–3f`) — subagent checklist steps included through the
  generated `<project_path>/tmp/patch_<N>_review_packet.md`. Steps 4 and 5 are
  also subagent-owned. The letter notation signals which agent owns the step.
- **Uppercase loop labels** (`A`–`J`) — iteration steps within
  `refs/startup-workflow.md` Step 2's per-patch loop.

## Startup Handoff

Assume `refs/startup-workflow.md` already completed through Step 3 before this
file is read.

Do not rerun these startup-only actions here:
- repo sync, fetch, linux-next/base checkout, or dirty-tree gating
- `b4 am`, `git am`, dependency scanning, or review-branch creation
- `git format-patch`, warm W=1 build, unified per-patch extraction/build/DT loop
- review-packet assembly, dependency graph generation, or shared test summary creation

Expected startup artifacts:
- `tmp/series_manifest_<slug>.json`
- `tmp/review_patches/*.patch`
- `tmp/patch_<N>_diff.txt`
- `tmp/evidence/patch_<N>_evidence.json`
- `tmp/patch_<N>_build.txt`
- `tmp/patch_<N>_dtbinding.txt` when applicable
- `tmp/patch_<N>_review_packet.md` and `tmp/patch_<N>_review_packet.json`
- `tmp/patch_groups_<slug>.txt`
- `tmp/tests_<slug>.txt`
- `tmp/sparse_<slug>.txt`
- Mode C file-review artifacts when applicable

If any required startup artifact is missing, stale, or invalid, return to
`refs/startup-workflow.md` and repair startup first. Only after startup
artifacts are complete does this file continue with subagent prompting,
validation, HTML assembly, and cleanup sequencing.

## Per-Patch Reviewer Subagent

This section defines the subagent that the orchestrator spawns once per patch.

### Orchestrator spawn discipline (mandatory)

- Spawn **exactly one subagent per patch** — one patch per subagent invocation.
- **NEVER batch multiple patches into a single subagent call** regardless of
  how similar or trivial the patches appear.
- A T-patch series requires exactly T subagent invocations.
- Use **dependency-aware parallelism** (from `refs/startup-workflow.md`
  Step 2.1): patches in the same
  group have no shared files and are spawned as concurrent subagent invocations
  in a single message.  Groups are processed sequentially — Group k starts
  only after all subagents in Group k-1 have completed and been validated.
- Do not attempt to review any patch directly — all patch-level analysis is
  delegated to subagents.  The orchestrator only prepares context, spawns,
  validates, then either hands off to the daemon for assembly or assembles only
  in standalone/manual runs.
- If the active runtime has no subagent or parallel agent mechanism, fall back
  to sequential per-patch review in the main agent. This fallback uses the same
  generated packet artifact: `patch_<N>_review_packet.md`. It must not read refs
  directly or create an alternate prompt. Process only one patch's packet, diff,
  tests, and context at
  a time; write that patch's block file; compress findings before moving on.
  Record `Subagent fallback: sequential main-agent review` only in internal
  logs or sidecars, never in the saved HTML report or review header.

### Active review artifact guarantee

Mode A/B reviews are packet-only. The active per-patch review artifact is always
`tmp/patch_<N>_review_packet.md`, with mandatory JSON sidecar
`tmp/patch_<N>_review_packet.json`. The first prompt line must be:

```
Read <project_path>/tmp/patch_<N>_review_packet.md
```

The subagent output is invalid if it does not read the packet before producing
output. Subagents must not load startup, orchestrator, HTML-template,
validator-only, or broad rule refs directly.

### What the orchestrator passes to each subagent

The orchestrator calls the subagent invocation mechanism with a prompt in this
format:

```
Read <project_path>/tmp/patch_<N>_review_packet.md — this is your mandatory
review packet. Use only its reviewer base, selected rule cards, context
snippets, context-coverage inventory, patch evidence, and output contract.

You are reviewing patch <N> of <T>.

Patch hash:     <PATCH_N_HASH>   (short hash from git log --oneline; usually 7-12 hex chars)
Patch subject:  <subject line>
Patch type:     <normal|merge|revert|rfc|whitespace-only|documentation-only>
Active artifact:<project_path>/tmp/patch_<N>_review_packet.md
Packet mode:    packet
Diff file:      <project_path>/tmp/patch_<N>_diff.txt
Context files:  <path1>, <path2>, ...   (at most 4; bounded snippets are inside the packet)
Contamination:  <e.g. "drivers/foo.c also modified by patches 7, 11" or "none">
Series summary:
  1/<T> <hash1> "<subject1>" [Fixes: yes/no]
  2/<T> <hash2> "<subject2>" [Fixes: yes/no]
  ...
Tests file:     <project_path>/tmp/tests_<slug>.txt
Build file:     <project_path>/tmp/patch_<N>_build.txt
Sparse file:    <project_path>/tmp/sparse_<slug>.txt
Runtime config: <project_path>/tmp/review_runtime_config.json   (include when this file exists)
DT-binding file: <project_path>/tmp/patch_<N>_dtbinding.txt  (absent if not applicable)
Evidence file:  <project_path>/tmp/evidence/patch_<N>_evidence.json
Block file:     <project_path>/tmp/patch_<N>_block.html
Prompt file:    <project_path>/tmp/patch_<N>_prompt.md
Sidecar file:   <project_path>/tmp/review_<slug>_progress.txt
Packet file:    <project_path>/tmp/patch_<N>_review_packet.md
Packet JSON:    <project_path>/tmp/patch_<N>_review_packet.json
```

In addition to the human-readable summary, maintain a scratch cross-patch
producer/consumer map during extraction and assembly for facts that often span
patches: newly added helpers, newly written struct fields, stored pointer
escapes, callbacks/ops tables, and resources created in one patch but first
consumed or enabled in a later patch.  This map does not need a dedicated HTML
section, but it is mandatory input to the cross-patch reconciliation pass in
Step 6.3a.

Before invoking the subagent in daemon-managed runs, wait for the
daemon/server-owned prompt artifact at `<project_path>/tmp/patch_<N>_prompt.md`,
then pass that exact text to the subagent.  Do not reconstruct, shorten, or
backfill the prompt later from memory.  The saved prompt is a validation
artifact used to re-check incomplete or unstable block output, and it must be
older than the corresponding `patch_<N>_block.html` file.

Standalone/manual runs that do not have a daemon prompt writer may write the
exact prompt text above themselves before subagent invocation, but must still
obey the same prompt-before-block ordering rule.

**Patch type detection (orchestrator, before using `patch_<N>_prompt.md`):**
The orchestrator MUST classify each patch before spawning.  Use the series
manifest for patch number, hash, subject, files, and generated artifacts; compute
this prompt-only `Patch type:` value from the subject and patch diff.  Detection
rules:
- `merge` — `git show --format=%P HEAD` shows two parent hashes
- `revert` — subject line matches `^Revert ".*"`
- `rfc` — subject line contains `[RFC` (case-insensitive)
- `whitespace-only` — diff contains only lines matching `^[+-]\s*$` or
  indentation/comment changes (no functional code changes)
- `documentation-only` — all changed files match `Documentation/*`, `*.rst`,
  `*.txt`, or diff only touches comment blocks (`/* ... */`, `// ...`)
- `normal` — none of the above

If multiple types apply (e.g., an RFC revert), use the first matching type
in the order above.  Pass the detected type in the `Patch type:` field.

The orchestrator must not omit any field.  Missing fields cause the subagent
to produce incomplete output silently.

### Self-audit rule (mandatory)

The hash at the top of `patch_<N>_diff.txt` must match PATCH_N_HASH.
If they differ, the subagent stops and returns an error — it does not produce
a commit block with a wrong tree state.

### Orchestrator validation after each group

After all subagents in a group return, apply E3 to each patch, re-spawning a
failed patch at most once.  Accumulate compressed findings records only after
that patch passes E3, and do not start the next group until every patch in the
current group is validated.

## Enforcement Mechanisms — Mandatory Review Step Compliance

The following mechanisms exist to **prevent skipping mandatory review steps**.
They apply to both the orchestrator and subagents.  Violations at any level
invalidate the review — the orchestrator MUST re-spawn the offending subagent
or abort the review entirely.

**Mode C exception:** E1–E4 (subagent-related) do not apply to Mode C because
Mode C has no subagents — the orchestrator applies review steps directly.
For Mode C, validation is limited to: sidecar line written (`file: DONE`),
`tmp/review_<slug>_file_block.html` exists and ends with
`</div><!-- /commit-block -->`, and E8 (final file completeness).

### E1 — Orchestrator Pre-Spawn Checklist (before each group)

Before spawning any subagent group, or before each sequential main-agent
fallback review, the orchestrator MUST verify ALL of:

| # | Check | Abort condition |
|---|-------|-----------------|
| 1 | `patch_<N>_diff.txt` exists and is non-empty for every N in group | File missing or 0 bytes |
| 2 | `patch_<N>_build.txt` exists for every N in group | File missing |
| 3 | `patch_<N>_review_packet.md` and `.json` exist and pass `validate_review_packet.py` | Packet missing, malformed, lacks context-coverage inventory, or leaks forbidden refs; packet size/card-count budget warnings should be logged and used to shrink future packets, not treated as review-blocking failures |
| 4 | `tests_<slug>.txt` exists | File missing |
| 5 | `sparse_<slug>.txt` exists | File missing |
| 6 | Context files (≤4) are recorded for every N in group, or explicitly recorded as `none` | Field missing |
| 7 | `tmp/patch_<N>_prompt.md` exists, points to the active artifact, and is older than any existing `tmp/patch_<N>_block.html` | Missing, incomplete, or late prompt artifact |
| 8 | `tmp/evidence/patch_<N>_evidence.json` exists for every patch N in group and contains schema `review-commits.evidence-manifest.v1` | Missing or invalid evidence manifest |
| 9 | `series_manifest_<slug>.json` exists, passed `scripts/validate_series_manifest.py`, and contains every patch N in group | Manifest missing, invalid, or patch absent |

**Manifest consistency check (E1.2):** For every patch N in the group,
`series_manifest_<slug>.json` must pass `scripts/validate_series_manifest.py`
before any subagent/fallback review starts and must contain
`patches[N-1].hash`, `files`, `rule_cards`, `paths.packet`, `paths.packet_json`,
and `group`. The subagent/fallback prompt must use these manifest facts instead
of recomputing DT/HW/memory triggers by hand.

**Review-packet completeness check (E1.3):** The assembled
`patch_<N>_review_packet.md` and `patch_<N>_review_packet.json` MUST pass
`scripts/validate_review_packet.py --json <json> --skill-dir <skill_dir>` before
any subagent/fallback review starts. At minimum the packet must contain the
generated marker plus `packet-metadata`, `reviewer-base`, `output-format-mini`,
`context-snippets`, `context-coverage`, `selected-rule-cards`, `commit-message`,
`checker-evidence`, and `patch-diff` sections.

If packet validation fails, the startup packet assembly (`refs/startup-workflow.md`
Step 2 step J) failed — re-run it after fixing selector/assembler inputs.

If ANY check fails: STOP, report which check failed and for which patch,
and fix the issue before spawning. Never spawn a subagent with incomplete
inputs.

### E2 — Subagent Mandatory Step Completion Proof

The Step Completion Record schema the subagent must emit is defined in the
packet-embedded `refs/output-format-mini.md` (HTML Block Contract). The
orchestrator does not duplicate that schema here; it validates the required
markers and counts in E3 below.

### E3 — Orchestrator Post-Group Validation (after each group)

After all subagents in a group return, the orchestrator MUST run these
checks for every patch N in the group:

```
VALIDATION CHECKLIST (per patch N in group):
□ 1. Sidecar contains "patch_<N>: DONE"
□ 2. Block file exists and last line is "</div><!-- /commit-block -->"
□ 3. Block file contains "<!-- STEP_COMPLETION_RECORD"
□ 4. All mandatory steps in the record show "DONE":
     - step_1_read_diff
     - step_2_read_context
     - step_3_read_tests
     - step_3b_coding_style
     - step_3c_code_logic
     - step_3e_commit_message
     - step_4_gate_applied
     - step_5_html_written
□ 4a. `codebase_audit:` line exists in the STEP_COMPLETION_RECORD
      - code patches: must be `DONE entrypoints=<n> callees=<n> siblings=<n> files=[...]`
      - non-code patches: may be `N/A no function-level code changes`
      - missing or malformed = re-spawn
□ 5. Conditional steps show DONE when trigger present:
     - step_3d_dt_binding = DONE  (if patch touches DT schema/DTS/header or of_match)
     - step_3f_hardware_eng = DONE (if patch touches registers/probe/PM/IRQ/DMA
       or thermal/cooling hardware wiring); DONE requires concrete Hardware
       Engineering Notes, not generic "platform specs" / "DTB passed" text
□ 6. Finding count cross-check:
     - Count [BUG]+[CONCERN]+[MINOR]+[NIT] badges in block HTML
     - Compare against step_4_gate_applied totals
     - MISMATCH = subagent skipped the gate or fabricated counts → re-spawn
□ 7. Gate trace check:
     - Every `.finding-card` `.body` contains `Gate 1:` AND `Gate 2:` AND
       `Gate 3:`, OR `Always-BUG exception:`.  Non-NIT cards must also contain
       the `sub-rule:` tag (naming the governing Gate 1 sub-rule or `none`).
       `[NIT]` cards instead require `Style track:`.  Banner cards that link to
       a canonical block card via
       `<a href="#patch-<N>-finding-<K>">` are exempt — the canonical card
       carries the trace.
     - This check is delegated to `scripts/validate_review.py` (Step 6.7);
     - the orchestrator's grep here is a fast pre-check.  The validator
     - is the source of truth and MUST be run before declaring the review
     - complete.
     - MISSING = ungated finding → re-spawn the subagent that produced the
       block.
□ 8. Code Logic Maps section is non-empty (<pre> block contains text — a
     brief note like "Single assignment change" is valid; empty is not)
□ 8a. For every packet-mode patch, Code Logic Maps contain all three
     surrounding-code audit lines, the lifecycle/workflow line, and the
     three analytical lines:
     - `codebase audit: entrypoints ...`
     - `codebase audit: callees ...`
     - `codebase audit: siblings ...`
     - `control-flow: ...`
     - `data-flow: ...`
     - `state/lifecycle: ...`
     - `before-vs-after delta: ...`
     For DTS/YAML-only patches these audit lines must name DT/schema/consumer
     context, not `codebase audit: N/A`.
□ 9. No orphan HTML tags (open <div> count == close </div> count)
□ 10. Early block validator exits 0 using the saved patch corpus and prompt:
     ```bash
     python3 <skill_dir>/scripts/validate_review.py \
         --block-file <project_path>/tmp/patch_<N>_block.html \
         --patch-file <project_path>/tmp/patch_<N>_diff.txt \
         --prompt-file <project_path>/tmp/patch_<N>_prompt.md \
         --packet-file <project_path>/tmp/patch_<N>_review_packet.md \
         --evidence-file <project_path>/tmp/evidence/patch_<N>_evidence.json \
         --tests <project_path>/tmp/tests_<slug>.txt \
         --build-file <project_path>/tmp/patch_<N>_build.txt \
         --require-patches \
         --source-root <project_path>
     ```
     This is the same validator as final Step 6.7, run while the per-patch
     evidence and prompt are still local.  It enforces gate traces, completion
     records, source-aware PM/DT/helper/resource checks, helper-replacement
     postcondition coverage, parent/child compatible-contract consistency,
     prompt-artifact completeness, packet presence, and evidence-manifest
     coverage before the
     block can be assembled into the final report.
```

**On any validation failure:**
1. Log: `"VALIDATION FAILED patch_<N>: check <#> — <reason>"`
2. Re-spawn the subagent **once** with the same saved prompt plus a prepended
   note:
   `"IMPORTANT: Your previous attempt failed validation check <#>. You MUST
   complete ALL mandatory steps. Do not skip any checklist."`
   Update `tmp/patch_<N>_prompt.md` to include this retry note before the
   original prompt, then pass that exact saved prompt to the subagent.
3. If the re-spawn also fails validation: **ABORT the review** and report to
   the user which step the subagent refuses to complete.

**Build-break ordering (orchestrator pre-validation):** before running the
E3 checklist, scan `<project_path>/tmp/tests_<slug>.txt` for `Build (W=1)
FAIL`.  If the build failed for patch N, the orchestrator MUST verify that
the **first** `.finding-card` in `tmp/patch_<N>_block.html`'s `<h3>Issues</h3>`
section is the build-break finding (title or body contains `build`,
`compile`, `-Werror`, `implicit declaration`, or matches the failing file
in the build log).  If it is not first, instruct the subagent in the
re-spawn note to reorder its block.  The validator in Step 6.7 also
enforces this rule for the final assembled HTML.

### E3.1 — Adversarial skeptic pass on cleared high-risk patterns (after E3)

The deterministic validator (E3 step 10) gates *named* false-clearance patterns,
but a positive note can also bury a hazard the regexes do not phrase.  The
skeptic pass is a **targeted second opinion** that re-examines only the
*dismissals* in a block — it never re-reviews the whole patch — so its cost is
bounded and it cannot inflate findings on its own.

**When it runs (trigger):** for each patch N whose block, after passing E3,
contains a clearance of a high-risk class — i.e. the block has a `Positive
Notes` entry, a `No issues found.` Issues section, or prose concluding "safe /
correct / symmetric / no issues" **AND** its diff or analysis text mentions any
of these high-risk tokens:
- `device_unregister(` / `put_device(` / `_unregister(` of a caller-owned
  pointer (`->fw_dev`, drvdata, cached handle)
- `pm_runtime_get_sync(`
- an OPP/perf/genpd vote drop inside a per-block/per-core helper
- a vendor construct added to a core-subsystem file
  (`drivers/iommu/`, `drivers/base/`, `of/`, `kernel/`, `mm/`)
- a stack `struct dev_pm_domain_attach_data` / attach-descriptor passed to a
  `*_attach_*`/list API
- `qcom_mdt_pas_load(` / `qcom_scm_pas_init_image(`
- a `devm_*` allocation on an open/close/reload/recovery path
- a large table→per-block / signature-changing refactor
- a non-zeroing allocator (`kmalloc`, `devm_kmalloc`, `kmalloc_array`) feeding a
  struct whose fields are then set only on some `switch`/`if` arms, followed by a
  later read of such a field (partial-init / uninitialized-read risk)
- a DT `operating-points-v2` / `interconnects` / bandwidth-vote addition whose
  bound driver may not consume it (firmware-managed-DVFS inert-DT risk)

If none of these tokens appear in the block, skip the skeptic pass for that
patch (most patches skip it).

**What the orchestrator spawns:** one narrow skeptic subagent per triggering
patch, with a prompt that:
1. Names the specific cleared pattern(s) found and quotes the block's clearance
   text.
2. Instructs the skeptic to **assume the clearance is wrong** and try to
   construct the concrete hazard (stale pointer on reinit, usage-count
   imbalance after a failed `get_sync`, global vote dropped while a sibling runs,
   layering objection, uninitialized struct field, per-load metadata leak,
   cumulative devres, DT resource left inert because the bound driver bypasses
   the consuming framework) using the patch diff and at most **two** on-demand
   source reads.
3. Requires the skeptic to return exactly one verdict per pattern:
   - `DISCHARGED: <quoted line that makes it safe>` — the clearance stands; or
   - `REOPEN: <one-line concrete hazard + suggested severity>`.
   The skeptic may not return prose without one of these tokens.

**What the orchestrator does with the result:**
- All `DISCHARGED` → keep the block as-is; record
  `skeptic: DISCHARGED <pattern...>` in the sidecar.
- Any `REOPEN` → re-spawn the original reviewer subagent **once** with the
  skeptic's `REOPEN` line prepended as a required finding to address (reuse the
  E3 re-spawn note mechanism).  The reviewer must either file the finding at the
  suggested (or higher) severity or quote the discharge line the skeptic missed.
- The skeptic pass itself runs **at most once** per patch; it is not iterated.

**Scope guard:** the skeptic only examines clearances of the listed high-risk
classes — it must not open new finding categories, restyle the block, or
re-litigate findings the reviewer already filed.  This keeps it a check on
*false clearances*, not a second full review.  When the active runtime has no
subagent mechanism, the sequential main-agent fallback performs the same
targeted self-review before accepting a cleared high-risk block.

### E4 — Subagent Spawn Count Enforcement

After ALL groups are processed, the orchestrator MUST verify:

```
SPAWN_COUNT_CHECK:
  expected_spawns = T  (total patches in series; Modes A/B only)
  actual_spawns   = count of "DONE" lines in sidecar
                    (matches "patch_<N>: DONE" for Modes A/B)
  
  IF actual_spawns != expected_spawns:
    ABORT — "Spawn count mismatch: expected <T>, got <actual>.
             Patches without DONE sidecar: [list missing N values]"
```

This catches the case where the orchestrator accidentally batched multiple
patches into one call or silently skipped a patch.

**Mode C file-block completion check:** because Mode C has no subagents, verify
exactly one `file: DONE` line in `tmp/review_<slug>_progress.txt` and verify
`tmp/review_<slug>_file_block.html` exists before Step 6.4.  Do not include
Mode C in `SPAWN_COUNT_CHECK`.

### E5–E7 — Subagent-Side Enforcement

Subagent-side enforcement is carried in the packet-embedded refs
(`refs/reviewer-base.md` + `refs/output-format-mini.md`):
- Block ordering and mandatory section presence live in the HTML Block Contract.
- Step Completion Record and self-audit requirements live in the HTML Block Contract.
- Gate trace requirements live in `refs/output-format-mini.md` (Mandatory
  Validation Trace); `refs/gate-rules.md` is the orchestrator-side authority the
  E3/`validate_review.py` checks validate against.

The orchestrator enforces those requirements through the E3 validation checklist
and re-spawn policy above.

### E8 — Review File Completeness Gate (Orchestrator)

In standalone/manual runs, after assembling all block files into the final HTML
and before declaring the review complete, the orchestrator MUST verify:

In daemon-managed Modes A/B, this gate is daemon-owned after marker acceptance;
the agent must still complete the E3 block-mode validation before writing the
marker.

```
FINAL_REVIEW_GATE:
□ 1. File exists at expected path
□ 2. File starts with "<!DOCTYPE html>"
□ 3. File contains the expected commit-block divs (count occurrences of
     'class="commit-block"'): exactly T for Modes A/B, exactly 1 for Mode C
□ 4. File contains a verdict banner (class="verdict-banner")
□ 5. File contains the test results table (class="test-table")
□ 6. File ends with "</html>"
□ 7. All expected Step Completion Records are present in the file
     (T for Modes A/B, 1 for Mode C)
□ 8. The exact Step 6.7 structural-validator invocation exits 0.
     This is the single
     source-of-truth check for gate traces, canonical block anchor ids,
     banner anchor links, DT / Hardware Engineering section headers,
     banner ↔ block consistency, build-break presence/ordering, interactive
     Kconfig build-log rejection, hardware trigger consistency, hardware-note
     specificity, refactor coverage, and future-risk gating.
     E8 cannot pass while the validator fails.
```

If ANY check fails: the review file is malformed.  Report the failure and
attempt to fix (re-assemble from block files).  If un-fixable, abort and
report to user.

## Steps 3b–5 — Review Checklists

Patch-level review guidance is consumed only through the Step 2 step J generated
and E1.3 validated `patch_<N>_review_packet.md`.

Detailed rule prose must arrive through selected rule cards, not through broad
default refs. The orchestrator does not re-implement the checklists;
it assembles and validates the active artifact, passes it in the prompt, then
verifies the sidecar and HTML block after the patch review completes.

When the structural validator forces an unnecessary repair or repeatedly fires
on a source-backed, review-quality report, capture the pattern in
`refs/validator-feedback.md` so the validator design (not normal review prose)
gets calibrated.

## Step 6 — Save the Review

**MANDATORY**: Writing the review file is not optional.  Every review run
MUST produce a saved file.  Do not output the review only to the terminal
and skip the file.  The file is the primary deliverable — the terminal
output is secondary.  If the file is not written, the review is incomplete.

**Filename**:
- Mode A count-based: `review_<repo-basename>_last<N>_<YYYYMMDD>.html`
- Mode A revision-range: `review_<repo-basename>_<sanitized-range>_<YYYYMMDD>.html`
- Mode B: `review_<slug>_<YYYYMMDD>.html`
  where `<slug>` is the filename prefix b4 used for the `.mbx` file.
  **Never add a part suffix** (e.g. `_part1`, `_part2`) — all patches in a
  series, regardless of how many agents reviewed them, are written into this
  single file.
- Mode C: `review_<repo-basename>_<filename-no-ext>_<YYYYMMDD>.html`
  where `<filename-no-ext>` is the basename of the reviewed file with its
  extension stripped (e.g. reviewing `iris_vpu3x.c` → `review_linux-next_iris_vpu3x_20260403.html`).
  For Mode C, `<slug>` is defined as `<repo-basename>_<filename-no-ext>`
  (used in the sidecar path `tmp/review_<slug>_progress.txt` and the
  continuation check).

**Save location**: always `<project_path>` — the project directory supplied by
the user.  Never save to the current working directory, the home directory, or
any other location.

**File structure** (write in this order):

The **Overall Summary** must appear at the top of the file, immediately after
the header block, so the reader sees the verdict and key findings without
scrolling.  The detailed per-commit reviews and test results follow.

The output file is a **fully structured HTML document**.  Use semantic HTML5
with embedded CSS for readability.  The structure below is mandatory.

### HTML skeleton

The full HTML/CSS template is in `refs/html-template.md`.  Read that file
for the complete skeleton including all CSS classes, the header card, verdict
banner, test results table, per-commit block structure, and footer.

The orchestrator uses this template in Step 6.1 (skeleton creation).
Subagents do NOT need the full template — they write only commit-block
fragments as defined in `refs/output-format-mini.md` (HTML Block Contract).

### CSS class mapping

CSS class mappings are the source of truth in `refs/html-template.md`
(`CSS Class Mapping Reference`) and are mirrored for subagents in the
`refs/output-format-mini.md` HTML Block Contract example.

Each Per-Patch Reviewer Subagent writes exactly one commit block to its own
`tmp/patch_<N>_block.html` file and one checkpoint sidecar line.  In
daemon-managed Modes A/B, the daemon creates/closes the final HTML from these
validated block files after marker acceptance.  In standalone/manual runs, the
orchestrator creates/closes the HTML file and assembles the block files in
patch order (Step 6.4).  The orchestrator never writes commit blocks directly.

**Procedure**:

**Continuation check (mandatory before step 6.1):**
```bash
ls <project_path>/tmp/review_<slug>_progress.txt 2>/dev/null && \
  ls <project_path>/review_<slug>_<YYYYMMDD>.html 2>/dev/null && \
  echo "CONTINUATION" || echo "FRESH START"
```
- **CONTINUATION**: sidecar and HTML already exist from a prior run.
  - **Hash-based verification**: To determine whether a patch's block is
    already in the HTML, grep for its commit hash in a `commit-hash` span:
    ```bash
    grep -q 'class="commit-hash".*<PATCH_N_HASH>' <html_file> && echo "ASSEMBLED" || echo "PENDING"
    ```
    Do NOT rely on substring matching of content — use only the hash span.
  - **Modes A/B**: Read the sidecar to learn which patches are done (and
    their block files already written); skip to step 6.3 and spawn subagents
    only for the remaining patches.  Do not recreate the HTML file.  In step 6.4, only
    assemble block files for patches not yet assembled (use the hash-based
    check above).
  - **Mode C**: The per-file block was already written.  Skip steps 6.1–6.3
    entirely.  Jump to step 6.4 and check whether the per-file block is
    already assembled into the HTML; if so, skip step 6.4 too and proceed
    directly to step 6.5 (footer) → 6.6 (reconcile verdict) → 6.7 (confirm).
- **FRESH START**: proceed with steps 6.1–6.10 below.

6.1. **Create the HTML skeleton** using the runtime's structured file-writing mechanism (≤ 120 lines):
   Write from `<!DOCTYPE html>` through the closing `</div>` of the draft
   verdict banner.  Do NOT include commit blocks.
   Leave the file open (no `</body></html>` yet).
   The verdict banner is a draft — reconcile it in step 6.6.
   **Shell invariant:** after this step the file already contains real body
   elements for `class="review-header"`, `class="verdict-banner"`, and
   `class="verdict-pill"`; CSS-only class definitions do not count.

6.2. **Append the Test Results block** using the runtime's structured file-editing mechanism.
   Run `tail -8 <file>` first; copy exact bytes as `old_string` anchor.
   **Shell invariant:** after this step the file contains a real
   `class="test-table"` body element before any `commit-block`.

6.3. **Spawn Per-Patch Reviewer Subagents** — dependency-aware parallelism.
   **NEVER batch multiple patches into a single subagent call.**
   **Mode C**: skip this step entirely — there are no patches and no
   subagents.  The orchestrator applies the review checklists directly
   (Steps 3b–3d, 3f, Step 4 excluding Patch Scope) and writes the per-file
   block to `<project_path>/tmp/review_<slug>_file_block.html` using the
   runtime's structured file-writing mechanism.  Write the sidecar checkpoint:
   ```bash
   echo "file: DONE hash=N/A findings=<severities>" \
     >> <project_path>/tmp/review_<slug>_progress.txt
   ```
   Then jump to step 6.4.

   Read `<project_path>/tmp/patch_groups_<slug>.txt` to get the group schedule.

   For each group G (in group order — sequential between groups):
   - Determine which patches in G are not yet done (sidecar check).
   - Spawn all remaining patches in G as **concurrent** subagent invocations in
     a single message (one Agent call per patch, all in the same response).
   - Wait for all subagents in G to complete.
   - Validate each patch N in G with E3, including the sidecar, block terminator,
     Step Completion Record, finding counts, gate traces, code-logic map,
     HTML balance checks, saved prompt artifact, and early block-mode
     `validate_review.py --block-file ... --require-patches` source-aware checks.
   - If E3 fails for patch N: re-spawn that patch once with the E3 failure
     reason.  If it fails again, stop and report.
   - Collect all returned compressed findings records.
   - Do NOT start the next group until all patches in G are validated.

6.3a. **Cross-patch reconciliation pass (mandatory for Modes A/B)**

After all groups complete and before handing control back to the daemon for
final assembly, use the scratch
   producer/consumer map plus the compressed findings records to look for
   hazards that frequently span patch boundaries and therefore escape a
   patch-local read:

   - helper/field introduced in patch N, first real caller in patch M;
   - pointer stored in patch N, short-lived address passed in patch M;
   - state field mutated in patch N, only programming point lives in patch M or
     an unchanged sibling path;
   - required child/resource created in patch N, silently discarded in patch M
     while success is still returned;
   - `devm_*` allocations added in one patch but shown by later patches to be in
     a repeatable reload/recovery path.

   Procedure:
   - For each candidate, identify the patch that introduces the bug and the
     patch that first makes the path concretely reachable.
   - If the issue was already captured by a validated block, record the
     cross-reference and continue.
   - If the issue was missed, re-spawn the responsible patch subagent once with
     the precise producer/consumer evidence and require an updated block plus
     compressed findings record before proceeding.
   - If the evidence is still insufficient after one targeted re-spawn, record a
     `cross-patch limitation:` note in the relevant patch's Code Logic Maps
     instead of fabricating a finding.

6.4. **Final assembly ownership** — after all groups complete:

   **Daemon-managed Modes A/B**: STOP local assembly here. Verify every
   expected `tmp/patch_<N>_block.html` exists and already passed E3 / block-mode
   validation, then write the daemon completion marker. Do not append commit
   blocks into the final HTML, do not write footer/verdict shell sections, and
   do not remove temporary artifacts. The daemon validates the block artifacts,
   assembles the final report from those files in patch order, validates the
   final report, and performs cleanup.

   **Standalone/manual Modes A/B only** — if no daemon completion marker was
   provided, assemble commit blocks into HTML after all groups complete, in
   order:

   **Mode C**: read `<project_path>/tmp/review_<slug>_file_block.html`
   and append its full content to `<html_file>` using the structured file-editing mechanism
   (`tail -8` anchor first).  Confirm `</div><!-- /commit-block -->` is
   the last line before proceeding.

   **Modes A/B** — for patch N from 1 to T (sequential, in patch order):
   - Run `tail -8 <html_file>` and copy the output verbatim as `old_string`.
   - Read `<project_path>/tmp/patch_<N>_block.html`.
   - Append its full content to `<html_file>` using the structured file-editing mechanism.
   - Confirm the append succeeded (tail shows `</div><!-- /commit-block -->`)
     before moving to patch N+1.

6.5. **Append the footer** using the structured file-editing mechanism (run `tail -8` first):

   Skip this step for daemon-managed Modes A/B; the daemon owns final shell
   assembly after the marker.
   ```html
   <div class="page-footer">
     Generated by AI agent (qgenie) &mdash; <em>YYYY-MM-DD</em>
   </div>
   </div><!-- /page-wrap -->
   </body>
   </html>
   ```

6.6. **Reconcile the verdict banner (mandatory)**

   Skip this step for daemon-managed Modes A/B; the daemon synthesizes and
   validates the final verdict banner from the validated block artifacts.

   The verdict banner was written in step 6.1 before the per-commit deep-dive.
   The per-commit analysis may have promoted, demoted, dismissed, or reworded
   findings.  Before confirming the file, diff the banner findings against the
   compressed per-commit records from step 6.3 and fix every discrepancy:

   - Every `[BUG]` / `[CONCERN]` card in the banner must correspond exactly
     to a finding of the same severity in a per-commit block.
   - Every `[MINOR]` item in the banner STYLE / MINOR section must
     correspond exactly to a `[MINOR]` finding in a per-commit block.
   - Remove any banner finding that was dismissed or downgraded during the
     per-commit review.
   - Add any finding that was discovered during the per-commit review but is
     missing from the banner.
   - Update the stats-row chip counts (`N bugs`, `N concerns`, `N minor
     issues`) to match the reconciled totals — count every `[MINOR]` item
     across all per-commit blocks, not just the ones originally drafted.
   - Update the verdict pill and banner CSS class if the overall verdict
     changed (e.g. a dismissed `[BUG]` drops the verdict from NEEDS FIXES to
     NEEDS DISCUSSION).
   - **Banner summary contract (mandatory):** banner finding cards are concise
     anchor summaries only.  Do not copy `<pre>` snippets, Gate traces, or full
     per-commit analysis into the banner.  Keep the banner suggestion prose
     consistent with the canonical per-commit card and link to that card.
   - **Anchor-link contract (mandatory):** every per-commit finding card
     MUST carry `id="patch-<N>-finding-<K>"` where `<N>` is the 1-based
     patch index and `<K>` is the 1-based finding index within that block.
     Every banner finding card MUST contain at least one
     `<a href="#patch-<N>-finding-<K>">see Patch N</a>` linking to its
     canonical per-commit card.  The banner card's `.body` is a
     one-sentence summary (≤ 250 chars) — the full analysis and Gate
     trace live on the canonical per-commit card.  The validator in
     Step 6.7 enforces both rules.

   Use the structured file-editing mechanism to patch the banner in-place.  Do not rewrite the
   entire file.

   **Self-audit count check (mandatory after editing the banner):** count
   the `[BUG]`, `[CONCERN]`, and `[MINOR]` finding cards present in the
   banner after editing.  Compare against the compressed per-commit records.
   If the counts differ, find and fix the discrepancy before proceeding to
   step 6.7.

6.7. **Run the structural validator (mandatory, blocking)**

   Skip final-report validation for daemon-managed Modes A/B; E3 block-mode
   validation remains mandatory before writing the completion marker. The
   daemon runs both block validation and final-report validation after marker
   acceptance.

   After step 6.6 reconciliation and before any further confirmation, run the
   validator command for the active mode.

   **Modes A/B** — require the patch corpus and evidence manifests so
   source-aware checks cannot silently downgrade to HTML-only validation:

   ```bash
   python3 <skill_dir>/scripts/validate_review.py \
       <project_path>/<filename> \
       --tests <project_path>/tmp/tests_<slug>.txt \
       --patches-dir <project_path>/tmp/review_patches \
       --evidence-dir <project_path>/tmp/evidence \
       --require-patches \
       --source-root <project_path>
   ```

   **Mode C** — there is no patch corpus or per-patch evidence directory, so do
   not pass `--patches-dir`, `--evidence-dir`, or `--require-patches`:

   ```bash
   python3 <skill_dir>/scripts/validate_review.py \
       <project_path>/<filename> \
       --tests <project_path>/tmp/tests_<slug>.txt \
       --source-root <project_path>
   ```

   If `<project_path>/tmp/review_runtime_config.json` exists, append
   `--runtime-config <project_path>/tmp/review_runtime_config.json` and the
   active sparse artifact (`--sparse-file <project_path>/tmp/sparse_<slug>.txt`
   for Modes A/B, or `--sparse-file <project_path>/tmp/review_<slug>_sparse.txt`
   for Mode C).

   The validator checks gate traces, STEP_COMPLETION_RECORDs, DT / Hardware
   Engineering section headers, banner ↔ block badge counts, canonical
   block anchor ids, banner anchor-link dedup, and build-break
   presence/ordering.  Non-zero exit means a contract violation — the
   orchestrator MUST NOT skip this step or treat its failure as advisory.
   On failure:

   - Read the validator's structured output (one block per check category).
   - For artifact or startup-corpus failures (`build_artifact_validity`,
     `runtime_override_artifact`, `source_corpus_required`, missing evidence
     manifests, or missing rules artifacts): repair/re-run the startup artifact
     generation path, then re-run the validator.
   - For banner-only failures (`banner_dedup`, `banner_consistency`, or banner
     side of `build_break_order`): fix the banner in place using structured
     file editing, then re-run the validator.
   - For block-local failures (`gate_trace`, `step_record`,
     `conditional_sections`, `anchor_id`, `render_format`, codebase-audit /
     on-demand-read / evidence-required-read violations, severity-floor checks,
     source-aware DT/PM/helper/resource checks, or block side of
     `build_break_order`): re-spawn the offending subagent once with the
     validator's message prepended as `IMPORTANT: validator rejected your block —
     <message>`. In Mode C, repair the per-file block directly under the same
     rule instead of spawning a subagent.
   - If the validator still fails after one artifact repair, one re-spawn /
     Mode C block repair, or one banner fix: ABORT the review and report the
     remaining violations to the user.

   **Daemon rerun retention audit:** after this structural validator passes,
   daemon-managed runs compare the new report against the latest saved finding
   snapshot for the same review key.  A prior `[BUG]` or `[CONCERN]` may not
   disappear or be downgraded unless the new report contains an explicit,
   source-backed dismissal.  This audit is daemon-owned; the review agent must
   keep the report evidence-rich enough for the daemon to make that comparison.

6.8. **Confirm** after all chunks are written:
   Skip this step for daemon-managed Modes A/B.
   ```bash
   wc -l <project_path>/<filename>
   ```
   A line count below 200 for a single-patch review suggests the file is
   incomplete (header + verdict + one commit block + footer typically exceeds
   200 lines).  Investigate before proceeding.

6.9. **Print the Overall Summary to the terminal** after confirming the file.
   For daemon-managed Modes A/B, print a concise block-artifact summary instead
   (for example, `all patch block artifacts validated; daemon will assemble the
   final report`) and then write the completion marker.
   Output the verdict, counts, and key findings as plain text so the user can
   see the result without opening the file.  Follow it with the saved file
   path on its own line.

6.10. **Clean up temporary review files** after the review file is confirmed
   written and the terminal summary is printed.

   **Daemon-managed override:** when the runtime provides an explicit
   completion-marker path and says daemon-side validation/repair will run after
   `DONE`, do **not** execute this cleanup step inside the agent session.
   Leave `<project_path>/tmp`, b4 scratch files, and the temporary review
   branch intact until the daemon finishes structural validation and any repair
   pass. In that mode, cleanup is daemon-owned and happens only after the
   validator accepts the report.

   **Standalone/manual runs only:** if no daemon/runtime override is present,
   perform the cleanup below:
   ```bash
   # Modes A/B/C — remove temporary review artifacts for this slug.
   rm -f <project_path>/tmp/review_<slug>_progress.txt 2>/dev/null || true
   rm -f <project_path>/tmp/patch_*_diff.txt 2>/dev/null || true
   rm -f <project_path>/tmp/patch_*_build.txt 2>/dev/null || true
   rm -f <project_path>/tmp/sparse_<slug>.txt 2>/dev/null || true
   rm -f <project_path>/tmp/patch_*_dtbinding.txt 2>/dev/null || true
   rm -f <project_path>/tmp/patch_*_block.html 2>/dev/null || true
   rm -f <project_path>/tmp/patch_groups_<slug>.txt 2>/dev/null || true
   rm -f <project_path>/tmp/tests_<slug>.txt 2>/dev/null || true
   rm -f <project_path>/tmp/review_<slug>_build.txt 2>/dev/null || true
   rm -f <project_path>/tmp/review_<slug>_sparse.txt 2>/dev/null || true
   rm -f <project_path>/tmp/review_<slug>_dtbinding.txt 2>/dev/null || true
   rm -f <project_path>/tmp/review_<slug>_file_block.html 2>/dev/null || true
   rmdir <project_path>/tmp 2>/dev/null || true

   # Mode B only — remove b4 artifacts and delete the temporary review branch.
   if [ "<mode>" = "B" ]; then
       rm -f ./<slug>.mbx ./<slug>.cover 2>/dev/null || true
       git checkout "$ORIGINAL_HEAD"
       git branch -D review/<slug> 2>/dev/null || true
   fi
   ```

**Key rules**:
- **One commit block per patch — no batching.**  A series of T patches requires
  exactly T `.commit-block` elements.  Grouping multiple patches into one block
  is forbidden regardless of patch count or similarity.
- Each file-write or file-edit chunk should aim for ≤ 200 lines of new content.  For
  a complex commit whose Code Logic Maps alone exceed 200 lines, split that
  commit's block across two edit calls (e.g. the first call writes the header
  through Code Logic Maps, the second appends the Issues section onward).
- Use file creation only for the initial file creation (step 6.1) on a fresh
  start.  In continuation mode the file already exists — never overwrite it
  by recreating the file; only append/edit in place.
- Use structured editing for all subsequent appends in standalone/manual runs
  (steps 6.2, 6.4, 6.5, 6.6; step 6.3 uses subagent invocations, not file
  editing). In daemon-managed Modes A/B, do not perform the final HTML append
  steps; the daemon owns them after marker acceptance.
- **Before every append/edit, run `tail -8 <file>` and copy the output
  byte-for-byte as `old_string` — including any HTML entity escapes
  (`&lt;`, `&gt;`, `&amp;`) exactly as they appear in the file.  Never
  construct `old_string` from memory, from text drafted in a previous turn,
  or by adding HTML comments that were not literally written to the file.
  An invented or stale anchor causes a silent match failure that blocks all
  subsequent work.**
- Do NOT use shell heredocs, `printf`, or `echo` loops to write the review file; use structured file editing instead.
- Escape all user-supplied strings for HTML: `<` → `&lt;`, `>` → `&gt;`,
  `&` → `&amp;`, `"` → `&quot;` when placing them inside HTML attributes or
  text nodes.
- After writing each commit's block, compress its in-memory representation
  to the one-sentence + bullet format from step 3b.  Never carry full diffs,
  checkpatch output, or code-logic maps across commit boundaries.

**HTML conformance rules**:

Use `refs/html-template.md` as the source of truth for the full document
skeleton, CSS classes, header table, verdict banner, test table, and footer.
Use `refs/output-format-mini.md` (HTML Block Contract) as the source of truth
for per-commit and per-file block fragments written by subagents — that is the
contract embedded in the review packet.  Do not invent additional CSS classes,
custom structure, or alternate finding-card layouts.
