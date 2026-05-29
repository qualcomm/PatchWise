# Mode C Workflow — Single-File Review

This file is the complete startup path for **Mode C** (`Project path` + file
path): review one source file as-is in the working tree. It is separated from
`refs/startup-workflow.md` because Mode C shares almost none of the
series machinery (no `git am`, no per-patch loop, no subagents, no dependency
graph) used by the Mode A/B path.

Read this file instead of `refs/startup-workflow.md` Step 1/2/3 when the
selected mode is C. After the test summary table is built (Step 3 below), hand
off to `refs/orchestrator-workflow.md` exactly as the A/B startup path does —
the orchestrator's HTML assembly, validation, and cleanup sections are shared.

## Mode C Scope

Mode C reviews a single source file as-is. There are no patches, no diffs to
pre-extract, no `git am`, and no subagents to spawn. The review is structured
as a single **per-file block** (not per-commit).

Mode C applies review checklist Steps 3b–3d, 3f, and Step 4 (excluding the
Patch Scope column and Step 3e entirely — Mode C has no commits to review),
plus Step 5 output-format rules. The orchestrator applies them directly, not
via subagents.

## Step 0 — Sync Repository

Follow `refs/startup-workflow.md` Step 0 for `SKILL_DIR` resolution,
`ORIGINAL_HEAD` capture, `<project_path>/tmp` creation, and the dirty-tree
guard. Mode C does **not** check out any tag and does **not** create a review
branch — the file is reviewed in the current working tree.

```bash
cd <project_path>
mkdir -p <project_path>/tmp
git status --short
```

If `git status` shows modified or staged files, **stop** and report:
"Working tree has uncommitted changes — please stash or commit them before
running the review." A `git fetch` failure is non-fatal for Mode C — proceed
with the local tree and note "git fetch failed: <error>" in the Test Results
header.

## Step 1 — Read the File

```bash
cd <project_path>
cat <file_path>          # read the full file
wc -l <file_path>        # note total line count
```

- `<file_path>` may be absolute or relative to `<project_path>`.
- If the file does not exist, report the error and **stop**.
- Read the file in full before proceeding to Step 2.
- Also read related headers, Kconfig, and Makefile entries that reference the
  file (same context rules as the Mode A/B path).
- There are no commits to review; skip all commit-message and patch-scope
  checks (Step 3e, Step 4 Patch Scope column).

**Slug derivation:** `<slug> = <repo-basename>_<filename-no-ext>` (the same
slug used for the review filename in `refs/orchestrator-workflow.md` Step 6).

## Step 2 — Run Tools

Mode C runs its tools here directly (no per-patch loop). Run them before
proceeding to Step 3:

```bash
python3 "${SKILL_DIR}/scripts/run_w1_build.py" \
  --project <project_path> \
  --output <project_path>/tmp/review_<slug>_build.txt \
  --arch arm64 \
  --cross-compile aarch64-linux-gnu- \
  <dir>/ || {
    echo "ERROR: invalid Mode C W=1 build artifact"
    exit 1
  }
scripts/checkpatch.pl --strict -f <file_path>
yes "" | make ARCH=arm64 C=1 CF="-D__CHECK_ENDIAN__" -j99 <dir>/
# Save build output to <project_path>/tmp/review_<slug>_build.txt
# Save sparse output to <project_path>/tmp/review_<slug>_sparse.txt
# Run dt_binding_check / dtbs_check if applicable; save to
# <project_path>/tmp/review_<slug>_dtbinding.txt.
# For .dts/.dtsi files, resolve concrete DTB targets first and run
# "make CHECK_DTBS=1 <targets>" rather than a full-tree "make dtbs_check".
scripts/get_maintainer.pl -f <file_path>
```

Note: use `--no-tree` for checkpatch if it complains about missing tree context.

### Mode C rules sources

Mode C does not pre-assemble a rules brief. The orchestrator reads the
following refs directly when reviewing the file, scoped to triggers below:

- Always: `refs/reviewer-base.md`, `refs/output-format-mini.md`,
  `refs/gate-rules.md`, `refs/special-cases.md`, `refs/coding-style.md`.
- When the target file is a `.yaml`/`.dts`/`.dtsi` DT contract file or an
  `include/dt-bindings/*.h` header: also load `refs/dt-binding.md`,
  `refs/dt-binding-yaml.md`, and `refs/dt-binding-dts.md`.
- When the target file calls `of_match_table`/`of_*` driver API but is not
  itself a DT contract file: also load `refs/dt-driver.md`.
- When the file triggers Step 3f hardware review (register access, probe/
  remove, PM, IRQ, DMA, per-CPU, hotplug, topology): also load
  `refs/hardware-eng.md` and the hardware-eng-* family.

Pass both DT sets if a single file somehow qualifies for both (rare in Mode C,
since one file is reviewed at a time).

`SUBAGENT.md` is only a compatibility stub — Mode C is driven directly by the
orchestrator, not by a subagent prompt.

### Mandatory surrounding-code audit and targeted reads

Mode C reviews the file at its current working-tree state. When a finding's
correctness depends on surrounding-code facts not present in the file itself or
the related headers/Kconfig/Makefile already read, the orchestrator MUST
attempt **one** targeted `Read` of the relevant source file under
`<project_path>` before downgrading the finding to inconclusive or claiming
equivalence/safety.

Constraints (same as the Mode A/B path):
- Budget: up to **6 targeted reads** for the file under review.
- Read only the single file that contains the needed fact; do not follow
  `#include` chains or read whole subsystem trees.
- If the file exceeds 1500 lines, read only the function/section range relevant
  to the finding.
- Record each read as `"on-demand read: <path> — <reason>"` in the Code Logic
  Maps section.
- If the file is missing or oversized, fall back to the inconclusive path.

## Step 3 — Compile Test Summary

Tools were already run in Step 2. Results are in:
- `<project_path>/tmp/review_<slug>_build.txt`
- `<project_path>/tmp/review_<slug>_sparse.txt`
- `<project_path>/tmp/review_<slug>_dtbinding.txt` (if applicable)

Compile the test summary table from those files. Mark sparse `SKIP` only when
`which sparse` returns non-zero, or when an explicit daemon/runtime override
disables sparse for the run. In the runtime-disable case, do not run sparse;
write `<project_path>/tmp/review_<slug>_sparse.txt` with the single line
`(sparse disabled by config)` and use the summary note `disabled by config`.
Mark build `SKIP` only if `.config` generation also fails.

> **Manual runs:** outside the daemon, the sparse-disable override is enforced
> only by this instruction plus the post-review validator — there is **no**
> `make` wrapper intercepting `C=1` (that guard exists only on the daemon
> path). Honor the override yourself and write the sentinel exactly as above,
> or the validator will fail the report.

### 3.1 Test summary table

Output before the per-file review block:

```
| Test             | Result | Notes                                   |
|------------------|--------|-----------------------------------------|
| checkpatch       | PASS   | 0 errors, 2 warnings (see below)        |
| Build (W=1)      | PASS   | No new errors or warnings               |
| dt_binding_check | SKIP   | Not a .yaml/.dts file                   |
| sparse           | SKIP   | sparse not available                    |
| get_maintainer   | INFO   | To/Cc list (see below)                  |
```

List checkpatch findings in full beneath the table.

At the end of Step 3, Mode C startup is complete.

## Handoff To Full Workflow

Only now read `refs/orchestrator-workflow.md`. For Mode C the orchestrator
applies Steps 3b–3d, 3f, Step 4 (excluding the Patch Scope column and Step 3e),
and Step 5 output rules directly to the single per-file block, then continues
with HTML assembly and the final save. Mode C has no subagents and no
dependency graph.
