# Orchestrator Workflow

## Two-Role Architecture

Starting from Step 2, this skill uses a two-role design to keep each patch's
review context clean and bounded.

**Orchestrator** (the main agent that invokes this skill):
- Runs Steps 0–1: fetch, apply patches, dependency check
- Runs Step 2: unified per-patch loop — diff/context extraction, incremental
  W=1 build and DT-binding check in a single pass; runs sparse once post-loop
  at REVIEW_TIP scoped to all changed .c files; launches
  checkpatch and get_maintainer as background processes; builds the
  manifest-driven dependency graph (Step 2.1) and series structure summary
- Runs Step 3: compiles the test summary table from per-patch result files
- Spawns **Per-Patch Reviewer Subagents** using dependency-aware parallelism:
  patches that share no files with other patches in the series are spawned
  concurrently; patches with manifest dependencies are spawned in dependency
  order (see § Per-Patch Reviewer Subagent below)
- After all subagents complete: assembles per-patch block files into the HTML
  in order, appends the HTML footer, reconciles the verdict banner, prints
  terminal summary, cleans up

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
block to `tmp/patch_<N>_block.html`; the orchestrator assembles them in patch
order after all groups complete.  Patches that share files with others are
still spawned in dependency order so that cross-file review context is
preserved.

**Context isolation guarantee:** each subagent starts with a clean context
containing only: its generated rules brief, the assigned patch diff, at most 4
context files, the shared `tests_<slug>.txt` and `sparse_<slug>.txt`, plus its
per-patch `patch_<N>_build.txt` and `patch_<N>_dtbinding.txt` when applicable.
No prior patch's diff, file reads, or reasoning is present.

**Step numbering convention:**
- **Decimal sub-steps** (`2.1`, `6.1–6.9`) — orchestrator internal steps.
- **Letter sub-steps** (`3a–3f`) — subagent checklist steps included in the
  generated `<project_path>/tmp/patch_<N>_rules.md`.  Steps 4 and 5 are also
  subagent-owned.  The letter notation signals which agent owns the step.
- **Uppercase loop labels** (`A`–`I`) — iteration steps within the Step 2
  per-patch bash loop (e.g. `# A: move to patch N`, `# D — identify context files`).
  These are local to the loop body and are not cross-referenced outside Step 2.

## Step 0 — Sync Repository and Create Review Branch

**Orchestrator initialization (mandatory — before any other action):**

Resolve `SKILL_DIR` — the directory containing this `SKILL.md` file.  In
the active CLI runtime, this is the skill's install path (the directory from
which the skill was loaded).  Set it once and use it throughout:

```bash
# The orchestrator resolves the skill directory at the start of the run.
# It is the parent directory of the SKILL.md file that was loaded.
# Example: if SKILL.md is at /path/to/skills/review-commits/SKILL.md
# then SKILL_DIR=/path/to/skills/review-commits
SKILL_DIR="<resolved skill directory>"   # set by the skill loader
ORIGINAL_HEAD="$(git -C <project_path> rev-parse HEAD)"
REVIEW_BASE=""     # set in Step 1 for Mode B, or BASE_PARENT/range base for Mode A
REVIEW_TIP=""      # set after commits/patches are available
T=""               # total patch count for Modes A/B; unset for Mode C
slug=""            # mode-specific slug from Step 1
```

Keep these names stable throughout the run.  If any later step changes HEAD,
restore `ORIGINAL_HEAD` during cleanup unless the user explicitly requested to
stay on the temporary review branch.

Before obtaining any commits, ensure the local repository is up to date and
checked out at a known-good base.

```bash
cd <project_path>

# Check for uncommitted changes BEFORE doing anything else (Modes A, B, C).
# The per-patch git checkout loop in Step 2 will fail or clobber a dirty tree.
git status --short
```

If `git status` shows any modified or staged files, **stop** and report:
"Working tree has uncommitted changes — please stash or commit them before
running the review."  Do not proceed until the tree is clean.

```bash
# Fetch latest commits and tags from the tracked remote.
# For Modes A and C: a fetch failure is non-fatal — proceed with the local
# tree and note "git fetch failed: <error>" in the Test Results header.
# For Mode B: a fetch failure is fatal — stop and report the error.
git fetch --tags

# Mode B only: checkout the latest linux-next tag as the clean base for git am.
# Modes A and C must NOT checkout any tag here — their commits are already in
# the local tree and must remain reachable from the current HEAD.  Changing
# HEAD in Mode A would cause Step 1's "git log -N HEAD" and all subsequent
# "git checkout HEAD~k" commands in Step 2 to operate on linux-next tree commits
# instead of the user's local commits.
if [ "<mode>" = "B" ]; then
    latest_tag=$(git tag --sort=-version:refname | grep '^next-' | head -1)
    if [ -n "$latest_tag" ]; then
        echo "Checking out latest linux-next tag: $latest_tag"
        git checkout "$latest_tag"
    else
        # No linux-next tags available — fall back to pulling the tracked branch HEAD
        git pull
    fi
fi
```

- If `git checkout` or `git pull` reports errors (e.g., uncommitted local
  changes blocking the checkout), stop and report the exact error before
  proceeding.  For `git fetch`, follow the mode-specific rule above: fatal for
  Mode B, non-fatal for Modes A/C with the failure recorded in Test Results.
- The review branch is created from this clean tag base: Mode B creates it
  with `git checkout -b` in Step 1 before applying patches via `git am`;
  Modes A and C do not require a dedicated branch.

## Step 1 — Obtain the Commits

### Mode A

**Slug derivation (mandatory):** Mode A uses a slug for all internal paths
(sidecar, test files, group assignment).  Derive it as:
```
<slug> = <repo-basename>_last<count>
```
For example: reviewing the last 5 commits in a repo cloned to
`/home/user/linux-next` → slug = `linux-next_last5`.
For revision-range reviews: `<slug> = <repo-basename>_<sanitized-range>`
where `<sanitized-range>` replaces non-alphanumeric characters with `_`
(e.g. `HEAD~5..HEAD` → `HEAD_5__HEAD`).

```bash
cd <project_path>
mkdir -p <project_path>/tmp

# Count-based review:
COMMITS=$(git rev-list --reverse HEAD~<count>..HEAD)

# Revision-range review:
COMMITS=$(git rev-list --reverse <revision-range>)

T=$(printf "%s\n" "$COMMITS" | sed '/^$/d' | wc -l)
test "$T" -gt 0 || { echo "ERROR: no commits found for Mode A input"; exit 1; }
printf "%s\n" "$COMMITS" > <project_path>/tmp/commits_<slug>.txt
printf "%s\n" "$COMMITS" | while read -r hash; do git log --oneline -1 "$hash"; done
git show <hash>          # repeat for each commit when manual inspection is needed
```

### Mode B

```bash
cd <project_path>
b4 --version   # confirm b4 is available; print version for the record
               # if this fails, report the error and stop
               # This skill was written against b4 >= 0.14; older versions
               # may produce different output and cause parsing failures.
mkdir -p <project_path>/tmp
b4 am <message-id> 2>&1 | tee <project_path>/tmp/b4_output.txt
```

If `b4 am` exits non-zero: print `<project_path>/tmp/b4_output.txt` and **stop**.

Parse `<project_path>/tmp/b4_output.txt` for:
- **Total patches** — integer after `Total patches:`
- **mbx filename** — filename on the `git am ./` line
- **Base commit** — hash on the `git checkout -b` line (use `HEAD` if absent); store as `REVIEW_BASE`
- **Cover letter** — read `./<slug>.cover` if it exists (context only)
- **b4-collected trailers (mandatory)** — scan the output for lines of the
  form `  + <TagName>: <value>` (leading spaces then a literal `+` prefix).
  These are trailers that b4 harvested from reply emails in the thread and
  will append after the author's own `Signed-off-by:` line when the mbx is
  applied.  Record the patch number and tag for every such line, for example:
  ```
  b4_collected_trailers = {
    2: ["Reviewed-by: Konrad Dybcio <konrad.dybcio@oss.qualcomm.com>"],
    5: ["Reviewed-by: Konrad Dybcio <konrad.dybcio@oss.qualcomm.com>"],
  }
  ```
  This record is used in Step 3e to suppress false tag-ordering findings
  (see Step 3e mandatory check item 5).

If no `Total patches:` line despite exit 0: report full output and **stop**.

**Cover-letter-as-patch-0 check**: b4 sometimes includes the cover letter as
patch 0 in the mbx (subject line `[PATCH 0/N]` or `[RFC 0/N]`).  After
parsing `Total patches:`, check the first entry in the mbx: if its subject
matches `^\[.*0/`, it is the cover letter, not a code patch.  Subtract 1
from the `Total patches:` count before comparing against the applied commit
count in the patch-count check below.

**Cover letter dependency check (mandatory — do this before applying patches):**

Read `./<slug>.cover` immediately after `b4 am` succeeds.  Scan the cover
letter for any stated external dependencies — these appear as any of:

- `Depends-on:` pseudo-tag followed by a Message-ID or URL
- `Prerequisite-patch-id:` pseudo-tag followed by a patch identifier
- Prose such as "this series depends on", "requires", "based on", "on top of",
  "prerequisite", or "applies after" followed by a series title, Message-ID,
  or lore.kernel.org URL
- A `Link:` or `https://lore.kernel.org/` reference in the cover letter body
  that is described as a prerequisite (not merely a related discussion)

For each dependency found:

1. **Extract the identifier** — Message-ID, commit hash, or lore URL.
2. **Check whether it is present in the tree:**
   ```bash
   # If a commit hash is extractable (preferred — most reliable):
   git merge-base --is-ancestor <dep-hash> HEAD && echo "present" || echo "MISSING"

   # If only a subject/description is available (lore URL without hash):
   git log --all --oneline --grep="<keyword from subject>" | head -5

   # Last resort — shallow recent-history scan:
   git log --oneline HEAD | head -50
   ```
   Never rely solely on `git log --oneline <base-commit> | head -20` — it
   only scans 20 commits and misses dependencies that landed earlier.
3. **If the dependency is present**: note it as satisfied in the review header
   and proceed normally.
4. **If the dependency is missing or cannot be verified**:
   - Record it as `DEPENDENCY MISSING` in the review header card (add a
     `Dependencies` row to the header table).
   - Add a `[CONCERN] Missing prerequisite` finding to the verdict banner
     with the dependency identifier and a note that findings in this review
     may be incorrect or incomplete until the prerequisite is applied.
   - Do **not** stop the review — continue and flag individual findings that
     appear to be caused by the missing dependency with the note
     `"May be resolved by prerequisite: <identifier>"`.
   - Do **not** dismiss real bugs just because a dependency is missing —
     only flag findings where the missing code is the direct cause.

If no cover letter exists or no dependencies are mentioned, record
`Dependencies: none stated` in the header and proceed.  Do **not** recommend
adding a cover letter merely because a standalone/`1/1` patch has dependency
context; for one-patch submissions, commit body text, b4 prerequisite trailers,
or explicit dependency links are acceptable places for that context.

Apply patches:
```bash
REVIEW_BASE=<base-commit-or-HEAD>
git checkout -b <branch> "$REVIEW_BASE"
git am ./<slug>.mbx
```

If the `git checkout -b` line is absent from `b4 am` output, use the branch name
`review/<slug>` where `<slug>` is the filename prefix b4 used for the `.mbx` and
`.cover` files (e.g. if b4 wrote `v7_20260325_yingchao_deng_add_qualcomm_extended_cti_support.mbx`,
the slug is `v7_20260325_yingchao_deng_add_qualcomm_extended_cti_support`).  This
is the same slug used for the review filename in Step 6.

If `git am` fails: run `git am --show-current-patch=diff` to identify the
exact failing hunk, then run `git am --abort`.  Before stopping, diagnose
the root cause:

```bash
# Show the failing hunk
git am --show-current-patch=diff

# Identify which upstream commits last touched the conflicting files
# (substitute actual file paths from the failing hunk)
git log --oneline <conflicting_file> | head -10
# If the above returns nothing (file may have been renamed), try:
git log --follow --oneline <conflicting_file> | head -10

# Abort the apply and delete the review branch
git am --abort
git checkout <base-commit>
git branch -D <branch>
```

In the diagnostic, determine:
1. The exact file and hunk that failed.
2. The upstream commit(s) that last modified those lines (from `git log`
   above) — these are the likely cause of the conflict.
3. Whether the conflict appears to be in code related to the stated
   missing prerequisite (if any) or in independently changed upstream
   code unrelated to the prerequisite.
4. That the series needs to be rebased on top of the current tree before
   it can be reviewed.

**IMPORTANT — still produce the standard HTML report** using the template
from `refs/html-template.md`.  Use verdict class `cannot-apply` with text
"CANNOT APPLY".  Include the header card, test results table (mark skipped
tests), the diagnostic analysis above, and the footer.  The report must
look like a normal review report — the only difference is the verdict and
that per-patch findings are replaced by the apply-failure analysis.

Do NOT fall back to reading patches from the mbx file directly and continuing
the review.  Reading multiple patches in one batch collapses the per-patch
before/after boundary, making inter-patch bisectability violations invisible:
a write removed in patch N and restored in patch N+1 looks correct when both
are read together, but the tree is broken between them.  The only safe review
path requires each patch applied as a discrete commit.

Note: `git am --abort` rolls back **all** patches that were successfully
applied before the failure, returning the branch to its pre-`git am` state.

Confirm with `git log --oneline HEAD~<N>..HEAD`, then proceed to Step 2.
**Patch count check (mandatory):** count the commits in that log output and
compare against `Total patches:` from `b4 am`.  If the counts differ, `b4 am`
silently dropped patches (e.g. threaded replies misidentified as non-patches).
Stop, report the discrepancy with the exact counts, and ask the user how to
proceed — do not review a partial series as if it were complete.
Do **not** delete `.mbx` / `.cover` yet — they may be needed for context during
the review.  Cleanup happens after the review file is written (see Step 6.9).

**Post-review branch cleanup (Mode B — mandatory after review file is
confirmed written):** delete the review branch to keep the repository tidy:
```bash
git checkout <base-commit-or-previous-HEAD>
git branch -D review/<slug>
```
This is done in Step 6.9 alongside mbx/cover file deletion.

### Mode C

```bash
cd <project_path>
cat <file_path>          # read the full file
wc -l <file_path>        # note total line count
```

- `<file_path>` may be absolute or relative to `<project_path>`.
- If the file does not exist, report the error and **stop**.
- Read the file in full before proceeding to Step 2.
- Also read related headers, Kconfig, and Makefile entries that reference
  the file (same rules as Step 2 for Mode A/B).
- There are no commits to review; skip all commit-message and patch-scope
  checks (Steps 3e, 4 Patch Scope column).  Apply all other review steps
  (coding style, logic mapping, DT/DT-binding if applicable, build, sparse).
- The review is structured as a single **per-file block** (not per-commit).

## Step 1b — Optional Review Memory Lookup

Review memory is a lazy-loaded future-review aid. Do **not** load the memory
directory by default. Load at most the smallest relevant memory file when the
changed files or the user's request clearly match one of these routes:

| Trigger | Normal-review source |
|---|---|
| One-patch-one-purpose, stable split, feature/fix mixing, or series organization | `refs/memory/active/patch-scope.md` via `--memory patch-scope` |
| Subject/body wording, trailer order, `Fixes:`, `Cc: stable`, or cover-letter conventions | `refs/memory/active/commit-message.md` via `--memory commit-message` |
| DT bindings, DTS/DTSI, `of_match_table`, compatible strings, vendor prefixes, or `of_*` API usage | `refs/memory/active/dt-bindings.md` via `--memory dt-bindings` |
| Maintainer preferences tied to a driver family, subsystem, vendor tree, or mailing list | `refs/memory/active/subsystem-specific.md` via `--memory subsystem-specific` |

Rules:
- Do not load `refs/memory/index.md` during normal reviews unless memory needs
  to be added, updated, deprecated, or removed.
- Do not hand-load lifecycle memory files into prompts. Pass the matching
  `--memory` category to `scripts/assemble_rules.py`; it selects only
  `Status: active` entries by default and rejects Mode C patch-only categories.
- Treat memory entries as heuristics only. Every finding still requires direct
  evidence from the diff, code context, tests, or kernel documentation.
- Normal rules briefs include only `Status: active` memory entries selected by
  `scripts/assemble_rules.py`; draft/deprecated entries are for calibration and
  maintenance, not routine review prompts.
- Prefer false-positive guards from memory over blindly repeating an old
  concern.
- If a memory entry materially affects a finding, cite the memory ID inside
  the existing finding `.body` text or per-patch analysis notes. Do not add a
  new HTML section or change the required block structure only for memory.

## Step 2 — Pre-Extract Patch Content (Orchestrator)

This step is **mode-specific**.  Follow only the branch that matches the
current mode.

---

### Mode B — Unified per-patch loop (extraction + build + DT-binding)

One sequential loop replaces the former separate extraction and build loops,
reducing git checkouts from 3N → N.  Checkpatch and get_maintainer run as
background processes while the warmup build is in progress.

**Pre-loop setup:**

```bash
cd <project_path>

# Guard: confirm we are on the review branch.
git symbolic-ref HEAD >/dev/null 2>&1 || {
    echo "WARNING: detached HEAD — confirm REVIEW_TIP is correct"
    git log --oneline -1
}

REVIEW_TIP=$(git rev-parse HEAD)
mkdir -p <project_path>/tmp
SERIES_MANIFEST="<project_path>/tmp/series_manifest_${slug}.json"

python3 "${SKILL_DIR}/scripts/prepare_patch_series.py" \
  --project <project_path> \
  --mode B \
  --slug "${slug}" \
  --review-base "${REVIEW_BASE}" \
  --review-tip "${REVIEW_TIP}" \
  --total "${T}" \
  --output "${SERIES_MANIFEST}"

python3 "${SKILL_DIR}/scripts/validate_series_manifest.py" "${SERIES_MANIFEST}" \
  --project <project_path> \
  --mode B \
  --slug "${slug}" \
  --review-base "${REVIEW_BASE}" \
  --review-tip "${REVIEW_TIP}" \
  --total "${T}"

# 1. Generate patch files (needed for checkpatch and get_maintainer).
mkdir -p <project_path>/tmp/review_patches
git format-patch HEAD~${T}..HEAD \
  --output-directory <project_path>/tmp/review_patches/
ls <project_path>/tmp/review_patches/*.patch 2>/dev/null || {
    echo "ERROR: no patch files generated — check HEAD~${T}..HEAD range"; exit 1
}

# 2. Launch checkpatch and get_maintainer in the background.
#    They operate on patch files only — safe to run while git checkouts proceed.
(for patch in <project_path>/tmp/review_patches/*.patch; do
    scripts/checkpatch.pl --strict "$patch"
done) > <project_path>/tmp/checkpatch_out.txt 2>&1 &
CHECKPATCH_PID=$!

scripts/get_maintainer.pl \
    <project_path>/tmp/review_patches/*.patch \
    > <project_path>/tmp/getmaintainer_out.txt 2>&1 &
GETMAINTAINER_PID=$!

# 3. Warm the build cache at the base commit.
#    Identify the union of all affected subsystem dirs across the entire series.
REVIEW_BASE=$(git rev-parse "${REVIEW_TIP}~${T}")
git checkout "${REVIEW_BASE}"
python3 "${SKILL_DIR}/scripts/run_w1_build.py" \
  --project <project_path> \
  --output /dev/null \
  --arch arm64 \
  --cross-compile aarch64-linux-gnu- \
  <all_affected_dirs>/ || {
    echo "ERROR: warm W=1 build failed or produced invalid interactive Kconfig output"
    exit 1
  }
# The warmup output is discarded — its purpose is to prime object-file cache.
# checkpatch and get_maintainer are likely still running in the background here.
```

**Unified per-patch loop (sequential, patch 1 through T):**

```bash
for N in $(seq 1 $T); do
    PATCH_N_HASH=$(python3 - "${SERIES_MANIFEST}" "$N" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
print(manifest["patches"][int(sys.argv[2]) - 1]["hash"])
    PY
)

    # ── A: move to patch N's tree state ──────────────────────────────────
    git checkout "${PATCH_N_HASH}"

    # B — self-audit: hash must match Step 1's log output and manifest.
    test "$(git rev-parse HEAD)" = "${PATCH_N_HASH}" || {
        echo "ERROR: patch ${N} hash mismatch against ${SERIES_MANIFEST}"; exit 1
    }
    git log --oneline -1

    # C — capture diff and deterministic evidence manifest
    git show HEAD > <project_path>/tmp/patch_${N}_diff.txt
    mkdir -p <project_path>/tmp/evidence
    python3 "${SKILL_DIR}/scripts/generate_evidence_manifest.py" \
      --patch-file <project_path>/tmp/patch_${N}_diff.txt \
      --patch-number "${N}" \
      --source-root <project_path> \
      --output <project_path>/tmp/evidence/patch_${N}_evidence.json

    # D — identify context files (orchestrator chooses ≤4)
    git show --format= --name-only HEAD
    # Choose from: headers, Kconfig, Makefile, Documentation/ABI/ referenced
    # in the diff. Record the ≤4 chosen paths.

    # E — compute inter-patch contamination notes
    # For each file F changed by patch N, find ALL other patches in the
    # series that also modify F (both earlier and later patches):
    git log --oneline "${REVIEW_TIP}~${T}"..${REVIEW_TIP} -- <F>
    # Filter out patch N itself from the results.
    # Format: "file <F> also modified by patches <M> ("<subject>"), <P> ("<subject>")"
    # If no cross-modifications (only patch N touches F): use "none".

    # F — W=1 incremental build for this patch's affected dirs
    python3 "${SKILL_DIR}/scripts/run_w1_build.py" \
      --project <project_path> \
      --output <project_path>/tmp/patch_${N}_build.txt \
      --arch arm64 \
      --cross-compile aarch64-linux-gnu- \
      <affected_dirs_for_current_patch>/ || {
        echo "ERROR: invalid W=1 build artifact for patch ${N}"
        exit 1
      }
    # For arch-neutral subsystems (not entirely under arch/arm64/), also run:
    # python3 "${SKILL_DIR}/scripts/run_w1_build.py" \
    #   --project <project_path> \
    #   --output <project_path>/tmp/patch_${N}_build.txt \
    #   --append \
    #   --no-refresh-config \
    #   <affected_dirs_for_current_patch>/ || {
    #     echo "ERROR: invalid arch-neutral W=1 build artifact for patch ${N}"
    #     exit 1
    #   }

    # G — sparse: runs once post-loop at REVIEW_TIP; nothing to do here.

    # H — DT binding check (only when .yaml or .dts/.dtsi files changed)
    if <patch N touches Documentation/devicetree/bindings/*.yaml>; then
        make ARCH=arm64 DT_SCHEMA_FILES=<changed.yaml> dt_binding_check -j99 \
          >> <project_path>/tmp/patch_${N}_dtbinding.txt 2>&1
    fi
    if <patch N touches .dts or .dtsi files>; then
        make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- dtbs_check -j99 \
          2>&1 | grep -E '(warning|error)' >> <project_path>/tmp/patch_${N}_dtbinding.txt
    fi
    # If neither condition applies, do not create patch_${N}_dtbinding.txt.

    # I — series structure summary entry comes from SERIES_MANIFEST:
    # "<N>/<T> <short_hash> "<subject>" [Fixes: yes/no]".

    # J — Assemble per-patch rules brief
    # SKILL_DIR is set by the orchestrator at the start of the review run
    # (see "Orchestrator initialization" in Step 0).  Use the deterministic
    # assembler; do not hand-concatenate refs or append whole memory files.
    mapfile -t MANIFEST_RULE_ARGS < <(python3 - "${SERIES_MANIFEST}" "$N" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
for arg in manifest["patches"][int(sys.argv[2]) - 1]["rule_args"]:
    print(arg)
PY
)
    RULES_OUT="<project_path>/tmp/patch_${N}_rules.md"
    RULE_ARGS=(--skill-dir "${SKILL_DIR}" --output "${RULES_OUT}" "${MANIFEST_RULE_ARGS[@]}")
    RULE_CHECK_ARGS=("${RULES_OUT}" "${MANIFEST_RULE_ARGS[@]}")

    python3 "${SKILL_DIR}/scripts/assemble_rules.py" "${RULE_ARGS[@]}"
    python3 "${SKILL_DIR}/scripts/validate_rules_brief.py" "${RULE_CHECK_ARGS[@]}"
    # Note: MANIFEST_RULE_ARGS includes repeated --scope-file <changed-path>
    # entries for memory-triggered patches. assemble_rules.py must use them to
    # filter scoped memory entries to the current patch instead of pasting the
    # entire topic file into every per-patch rules brief.
    # If assembly or validation fails, stop and fix the trigger/assembler
    # inputs; do not spawn a subagent with a manual fallback.
done

git checkout "${REVIEW_TIP}"
```

**Post-loop — collect background results and write shared test file:**

```bash
wait $CHECKPATCH_PID
wait $GETMAINTAINER_PID

{
  echo "=== checkpatch ==="
  cat <project_path>/tmp/checkpatch_out.txt
  echo "=== get_maintainer ==="
  cat <project_path>/tmp/getmaintainer_out.txt
} > <project_path>/tmp/tests_<slug>.txt

rm -f <project_path>/tmp/checkpatch_out.txt \
      <project_path>/tmp/getmaintainer_out.txt

# Run sparse once at REVIEW_TIP, scoped to the union of all .c files recorded
# in SERIES_MANIFEST.  This replaces the former per-patch sparse runs (N ×
# directory build → 1 × targeted object build), saving N-1 full sparse
# compilations and preserving Mode A revision-range correctness.
SPARSE_TARGETS=$(python3 - "${SERIES_MANIFEST}" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
targets = sorted({path[:-2] + ".o" for patch in manifest["patches"] for path in patch["files"] if path.endswith(".c")})
print(" ".join(targets))
PY
)
if [ -n "$SPARSE_TARGETS" ]; then
    make ARCH=arm64 C=1 CF="-D__CHECK_ENDIAN__" -j99 $SPARSE_TARGETS \
      > <project_path>/tmp/sparse_<slug>.txt 2>&1
else
    echo "(no .c files changed — sparse skipped)" \
      > <project_path>/tmp/sparse_<slug>.txt
fi
```

**Series manifest and structure summary:** `SERIES_MANIFEST` is the source of
truth for patch number, hash, subject, files, DT/HW triggers, memory categories,
and generated artifact paths.  Build the subagent `Series summary:` from
`manifest["patches"]` in this format:

```
1/<T> <short-hash> "<subject>" [Fixes: yes/no]
2/<T> <short-hash> "<subject>" [Fixes: yes/no]
...
```

---

### Mode A — Unified per-patch loop (local commits)

Mode A commits are already in the local tree.  Build the ordered commit list in
Step 1 and use it as the source of truth for patch numbers, patch files, and
hash self-audits.  Do not assume `HEAD~<count>..HEAD` when the user supplied a
revision range.

```bash
cd <project_path>
mkdir -p <project_path>/tmp

# COMMITS is the newline-delimited oldest-to-newest list from Step 1.
# T is the number of commits in COMMITS.
FIRST_COMMIT=$(printf "%s\n" "$COMMITS" | sed -n '1p')
REVIEW_TIP=$(printf "%s\n" "$COMMITS" | sed -n '$p')
BASE_PARENT=$(git rev-parse "${FIRST_COMMIT}^" 2>/dev/null || true)
if [ -n "$BASE_PARENT" ]; then
    REVIEW_BASE="$BASE_PARENT"
    FORMAT_PATCH_RANGE="${REVIEW_BASE}..${REVIEW_TIP}"
else
    REVIEW_BASE="<root>"
    FORMAT_PATCH_RANGE="--root ${REVIEW_TIP}"
fi
SERIES_MANIFEST="<project_path>/tmp/series_manifest_${slug}.json"

python3 "${SKILL_DIR}/scripts/prepare_patch_series.py" \
  --project <project_path> \
  --mode A \
  --slug "${slug}" \
  --review-base "${REVIEW_BASE}" \
  --review-tip "${REVIEW_TIP}" \
  --commits-file <project_path>/tmp/commits_<slug>.txt \
  --output "${SERIES_MANIFEST}"

python3 "${SKILL_DIR}/scripts/validate_series_manifest.py" "${SERIES_MANIFEST}" \
  --project <project_path> \
  --mode A \
  --slug "${slug}" \
  --review-base "${REVIEW_BASE}" \
  --review-tip "${REVIEW_TIP}" \
  --total "${T}"

# 1. Generate patch files and launch background processes (same as Mode B).
mkdir -p <project_path>/tmp/review_patches
git format-patch ${FORMAT_PATCH_RANGE} \
  --output-directory <project_path>/tmp/review_patches/
(for patch in <project_path>/tmp/review_patches/*.patch; do
    scripts/checkpatch.pl --strict "$patch"
done) > <project_path>/tmp/checkpatch_out.txt 2>&1 &
CHECKPATCH_PID=$!
scripts/get_maintainer.pl \
    <project_path>/tmp/review_patches/*.patch \
    > <project_path>/tmp/getmaintainer_out.txt 2>&1 &
GETMAINTAINER_PID=$!

# 2. Warm build cache at REVIEW_BASE when available, then run the unified loop.
#    In loop step A, checkout PATCH_N_HASH from SERIES_MANIFEST.  The same
#    manifest also drives DT/HW/memory rule flags and series summary text.
```

After the loop: `git checkout "${REVIEW_TIP}"`, then collect background results
and run sparse using the manifest-derived target list from the common post-loop
step above.

---

### Mode C — Single file, no patches

Mode C reviews a single source file as-is.  There are no patches, no diffs
to pre-extract, and no subagents to spawn.

**Skip this step entirely for Mode C.**  Run tools for Mode C here instead,
before proceeding to Step 3:

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
make ARCH=arm64 C=1 CF="-D__CHECK_ENDIAN__" -j99 <dir>/
# Save build output to <project_path>/tmp/review_<slug>_build.txt
# Save sparse output to <project_path>/tmp/review_<slug>_sparse.txt
# Run dt_binding_check / dtbs_check if applicable; save to
# <project_path>/tmp/review_<slug>_dtbinding.txt
scripts/get_maintainer.pl -f <file_path>
```
Note: use `--no-tree` for checkpatch if it complains about missing tree context.

For Mode C, the orchestrator applies Steps 3b–3d, 3f, and Step 4 (excluding
the Patch Scope column and Step 3e entirely — Mode C has no commits to
review) plus Step 5 output format rules directly (not via subagents).
Assemble and validate one generated per-file rules brief instead of reading raw
refs directly:

```bash
RULES_OUT="<project_path>/tmp/review_<slug>_file_rules.md"
RULE_ARGS=(--skill-dir "${SKILL_DIR}" --output "${RULES_OUT}" --mode-c)
RULE_CHECK_ARGS=("${RULES_OUT}" --mode-c)

# Include the full DT schema/DTS checklist only when the file under review is
# itself a DT file (.yaml/.dts/.dtsi). For a driver source file that only calls
# the of_* API (no DT file), use --dt-driver instead, which loads just the
# driver of_* API rules (refs/dt-driver.md). Pass both if a single file somehow
# qualifies for both (rare in Mode C, since one file is reviewed at a time).
if <target file is a .yaml/.dts/.dtsi DT file>; then
    RULE_ARGS+=(--dt)
    RULE_CHECK_ARGS+=(--dt)
elif <target file calls of_match_table/of_* driver API>; then
    RULE_ARGS+=(--dt-driver)
    RULE_CHECK_ARGS+=(--dt-driver)
fi

# Include hardware rules only for register access/probe/remove/PM/IRQ/DMA/
# per-CPU/hotplug/topology review triggers.
if <file triggers Step 3f>; then
    RULE_ARGS+=(--hardware)
    RULE_CHECK_ARGS+=(--hardware)
fi

# Mode C has no patch scope or commit message.  Only DT/subsystem memory can be
# relevant, and only through active entries selected by the assembler.
if <file triggers Step 1b DT memory>; then
    RULE_ARGS+=(--memory dt-bindings)
    RULE_CHECK_ARGS+=(--memory dt-bindings)
fi
if <file triggers Step 1b subsystem-specific memory>; then
    RULE_ARGS+=(--memory subsystem-specific)
    RULE_CHECK_ARGS+=(--memory subsystem-specific)
fi

python3 "${SKILL_DIR}/scripts/assemble_rules.py" "${RULE_ARGS[@]}"
python3 "${SKILL_DIR}/scripts/validate_rules_brief.py" "${RULE_CHECK_ARGS[@]}"
```

Read `<project_path>/tmp/review_<slug>_file_rules.md` for the Mode C review
contract.  Do not hand-concatenate refs or append memory files.  `SUBAGENT.md`
is only a compatibility stub.

---

### Step D scope limit (applies to all modes)

The orchestrator must choose at most **4 context files per patch** to pass
to the subagent — headers, Kconfig, Makefile, and any `Documentation/ABI/`
file named in the diff.  Do not follow `#include` chains.  Never pass
pre-patch base-commit file contents — the diff context lines are sufficient.
When the patch changes executable logic, prefer context files that help the
mandatory surrounding-code audit succeed: the changed file, the immediate
dispatcher/selector/callback registration site, the most relevant helper body,
and any sibling/alternate mode file or wrapper schema that can still reach the
same abstraction.

### Step D' — Mandatory surrounding-code audit and targeted reads (applies to all modes)

The kernel tree is checked out at the patch's post-apply commit
(`PATCH_N_HASH`) at `<project_path>`.  When a finding's correctness
depends on surrounding-code facts, the subagent MUST build a
surrounding-code audit before clearing the issue.  For every patch with
function-level code changes, the audit must cover:
- entrypoints / dispatch / selectors into the changed logic;
- helper bodies / callee contracts / side effects relied upon by the review;
- sibling or alternate paths that can still reach the same abstraction or
  hardware mode after the patch.

The subagent records this proof in the Code Logic Maps section using the
exact labels `codebase audit: entrypoints ...`, `codebase audit: callees ...`,
and `codebase audit: siblings ...`.

When any audit bucket still depends on a fact not present in the diff context
lines or the 4 provided context files, the subagent MUST attempt **one**
targeted `Read` of the relevant source file under `<project_path>` before
downgrading the finding to inconclusive or claiming equivalence/safety.

Constraints:
- Budget: up to **6 targeted reads per patch** (in addition to the 4
  pre-passed context files).
- Read only the single file that contains the needed fact; do not follow
  `#include` chains or read whole subsystem trees.
- If the file exceeds 1500 lines, read only the function/section range
  relevant to the finding.
- Record each read as `"on-demand read: <path> — <reason>"` in the Code
  Logic Maps section.
- If the file is missing or oversized, fall back to the inconclusive path.

## Step 2.1 — Build Dependency Graph (Modes A and B only)

After the per-patch extraction loop, use `SERIES_MANIFEST` to determine which
patches can be reviewed concurrently.  The manifest is generated by
`scripts/prepare_patch_series.py` and records each patch's files, DT/HW triggers,
memory categories, dependency reasons, and assigned group.

**Algorithm implemented by `prepare_patch_series.py`:**

1. For each patch N, record the set of files it modifies.
2. Patch N depends on earlier patch M when any of these conservative conditions
   are true:
   - exact file overlap (`files(N) ∩ files(M) ≠ ∅`);
   - one patch changes `Kconfig`, `Kbuild`, or `Makefile` and the other patch
     changes files under that descriptor's directory;
   - both patches touch DT/DTS/binding files in the same DT/binding directory.
3. Dependency is transitive through group assignment: a patch is placed in one
   group after the maximum group of its dependencies.
4. Patches within the same group are safe to spawn concurrently under this
   conservative model.  Groups remain sequential — Group k starts only after
   all subagents in Group k-1 have completed and been validated.

**Example** (7-patch series):
```
Patch 1: drivers/foo.c, drivers/bar.c
Patch 2: Documentation/bindings/foo.yaml   ← no shared files → Group 1
Patch 3: drivers/foo.c                     ← shares foo.c with patch 1 → Group 2
Patch 4: arch/arm64/dts/qcom/soc.dtsi      ← no shared files → Group 1
Patch 5: drivers/bar.c                     ← shares bar.c with patch 1 → Group 2
Patch 6: drivers/baz.c                     ← no shared files → Group 1
Patch 7: drivers/foo.c, drivers/bar.c      ← shares with 1, 3, 5 → Group 3

Group 1 (concurrent): patches 1, 2, 4, 6
Group 2 (concurrent): patches 3, 5   (both depend on 1; independent of each other)
Group 3 (sequential): patch 7        (depends on 3, 5)
```

Save the group assignment from `SERIES_MANIFEST` to
`<project_path>/tmp/patch_groups_<slug>.txt`:

```bash
python3 - "${SERIES_MANIFEST}" > <project_path>/tmp/patch_groups_<slug>.txt <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
for group in manifest["groups"]:
    patches = ",".join(str(n) for n in group["patches"])
    print(f"group={group['group']} patches={patches}")
PY
```

Example output:
```
group=1 patches=1,2,4,6
group=2 patches=3,5
group=3 patches=7
```
This file drives the spawn schedule in Step 6.  If a manifest dependency reason
looks overly conservative, keep the safer sequential grouping; do not manually
move patches earlier unless direct code inspection proves independence.

**Mode C**: no patches — skip this step entirely.

## Step 3 — Compile Test Summary

By the end of Step 2's unified loop, all per-patch results are already saved:

| File | Contents |
|---|---|
| `tmp/tests_<slug>.txt` | checkpatch + get_maintainer (all patches) |
| `tmp/patch_<N>_build.txt` | W=1 build output at patch N's tree state |
| `tmp/sparse_<slug>.txt` | sparse output at REVIEW_TIP, all changed .c files |
| `tmp/patch_<N>_dtbinding.txt` | dt_binding_check + dtbs_check (only when applicable) |

**Mode C** — tools were already run in Step 2 above; results are in
`<project_path>/tmp/review_<slug>_build.txt`,
`<project_path>/tmp/review_<slug>_sparse.txt`, and
`<project_path>/tmp/review_<slug>_dtbinding.txt` (if applicable).
Compile the test summary table from those files.

Mark sparse `SKIP` only when `which sparse` returns non-zero.  Mark build
`SKIP` only if `.config` generation also fails.

**Do not clean up temporary patch files after the test summary table.**
`<project_path>/tmp/review_patches/*.patch` is a required validation artifact
for early block checks and final source-aware validation.  Keep it until Step
6.10 cleanup, and in daemon-managed runs leave cleanup to the daemon-side
post-validation path.

### 3.1 Test summary table

Output before the per-commit review.  Build, sparse, and DT-binding rows show
the **aggregate** result across all patches (PASS = all clean; FAIL/WARN = at
least one patch had issues — list the affected patch numbers in Notes):

```
| Test             | Result | Notes                                   |
|------------------|--------|-----------------------------------------|
| checkpatch       | PASS   | 0 errors, 2 warnings (see below)        |
| Build (W=1)      | PASS   | Per-patch incremental; all clean        |
| dt_binding_check | SKIP   | No .yaml/.dts files changed             |
| sparse           | SKIP   | sparse not available                    |
| get_maintainer   | INFO   | To/Cc list (see below)                  |
```

List checkpatch findings in full beneath the table.  Build findings for each
patch are reported in the per-commit block.  Sparse findings are from the
shared post-loop run — each per-commit block reports findings filtered to
files that patch touches.

## Per-Patch Reviewer Subagent

This section defines the subagent that the orchestrator spawns once per patch.

### Orchestrator spawn discipline (mandatory)

- Spawn **exactly one subagent per patch** — one patch per subagent invocation.
- **NEVER batch multiple patches into a single subagent call** regardless of
  how similar or trivial the patches appear.
- A T-patch series requires exactly T subagent invocations.
- Use **dependency-aware parallelism** (from Step 2.1): patches in the same
  group have no shared files and are spawned as concurrent subagent invocations
  in a single message.  Groups are processed sequentially — Group k starts
  only after all subagents in Group k-1 have completed and been validated.
- Do not attempt to review any patch directly — all patch-level analysis is
  delegated to subagents.  The orchestrator only prepares context, spawns,
  validates, and assembles.
- If the active runtime has no subagent or parallel agent mechanism, fall back
  to sequential per-patch review in the main agent. This fallback still uses the
  same Step J assembled and validated `patch_<N>_rules.md`; it must not read refs
  directly or create an alternate prompt. Process only one patch's rules file,
  diff, tests, and context at a time; write that patch's block file; compress
  findings before moving on. Record `Subagent fallback: sequential main-agent
  review` only in internal logs or sidecars, never in the saved HTML report or
  review header.

### Rule compliance guarantee

The subagent's **first action** must be to read its per-patch rules brief:
```
Read <project_path>/tmp/patch_<N>_rules.md
```
This file is assembled by the orchestrator in Step 2 (step J) and contains
the complete review rules — Steps 3b through 5 (coding style, code logic
maps, DT/DT-binding if applicable, commit message & patch scope, hardware
engineering if applicable, three-gate rule, HTML output format).  The
subagent must follow every rule in that file.  It may not skip checklists,
reduce severity without applying the three-gate rule, or produce HTML that
deviates from the format defined there.

The orchestrator must include the rules-file read instruction as the
**first line** of every subagent prompt.  If the subagent does not read
its rules file before producing any output, its output is invalid.

### What the orchestrator passes to each subagent

The orchestrator calls the subagent invocation mechanism with a prompt in this exact format:

```
Read <project_path>/tmp/patch_<N>_rules.md — these are your mandatory review
rules. Follow every rule precisely.

You are reviewing patch <N> of <T>.

Patch hash:     <PATCH_N_HASH>   (short hash from git log --oneline; usually 7-12 hex chars)
Patch subject:  <subject line>
Patch type:     <normal|merge|revert|rfc|whitespace-only|documentation-only>
Diff file:      <project_path>/tmp/patch_<N>_diff.txt
Context files:  <path1>, <path2>, ...   (at most 4)
Contamination:  <e.g. "drivers/foo.c also modified by patches 7, 11" or "none">
Series summary:
  1/<T> <hash1> "<subject1>" [Fixes: yes/no]
  2/<T> <hash2> "<subject2>" [Fixes: yes/no]
  ...
Tests file:     <project_path>/tmp/tests_<slug>.txt
Build file:     <project_path>/tmp/patch_<N>_build.txt
Sparse file:    <project_path>/tmp/sparse_<slug>.txt
DT-binding file: <project_path>/tmp/patch_<N>_dtbinding.txt  (absent if not applicable)
Evidence file:  <project_path>/tmp/evidence/patch_<N>_evidence.json
Block file:     <project_path>/tmp/patch_<N>_block.html
Prompt file:    <project_path>/tmp/patch_<N>_prompt.md
Sidecar file:   <project_path>/tmp/review_<slug>_progress.txt
```

Before invoking the subagent, write the exact prompt text above to
`<project_path>/tmp/patch_<N>_prompt.md`, then pass that same text to the
subagent.  Do not reconstruct the prompt later from memory.  The saved prompt
is a validation artifact used to re-check incomplete or unstable block output.

**Patch type detection (orchestrator, during Step 2 loop):**
The orchestrator MUST classify each patch before spawning.  Detection rules:
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
| 3 | `patch_<N>_rules.md` exists and contains all mandatory sections | File missing or incomplete |
| 4 | `tests_<slug>.txt` exists | File missing |
| 5 | `sparse_<slug>.txt` exists | File missing |
| 6 | Context files (≤4) are recorded for every N in group, or explicitly recorded as `none` | Field missing |
| 7 | Saved per-patch prompt path is planned as `tmp/patch_<N>_prompt.md` and will be written before spawn | Missing planned prompt artifact |
| 8 | `tmp/evidence/patch_<N>_evidence.json` exists for every patch N in group and contains schema `review-commits.evidence-manifest.v1` | Missing or invalid evidence manifest |
| 9 | `series_manifest_<slug>.json` exists, passed `scripts/validate_series_manifest.py`, and contains every patch N in group | Manifest missing, invalid, or patch absent |

**Manifest consistency check (E1.2):** For every patch N in the group,
`series_manifest_<slug>.json` must pass `scripts/validate_series_manifest.py`
before any subagent/fallback review starts and must contain
`patches[N-1].hash`, `files`, `rule_args`, and `group`.  The
subagent/fallback prompt must use these manifest facts instead of recomputing
DT/HW/memory triggers by hand.

**Rules-brief completeness check (E1.3):** The assembled `patch_<N>_rules.md`
MUST pass `scripts/validate_rules_brief.py` with the same `--dt`, `--dt-driver`,
`--hardware`, and `--memory` flags used for Step J assembly.  Mode C must
similarly validate
`review_<slug>_file_rules.md` with `--mode-c` plus the same conditional flags
used during Mode C assembly.  At minimum patch rules must contain the generated
marker and all of these unconditional section headers:
- `Generated by scripts/assemble_rules.py`
- `## Your procedure — 7 mandatory steps`
- `## CSS Class Mapping`
- `Step 3b` (from coding-style.md)
- `Step 3c` (from code-logic.md)
- `Step 3e` (from commit-message.md)
- `THREE-GATE RULE` (from gate-rules.md)
- `## Special Cases` (from special-cases.md)

Conditional sections (only checked when the patch triggers them):
- `Step 3d` — required (via `--dt`) when patch changes a .yaml/.dts/.dtsi DT file
- `Step 3d.3` — required (via `--dt-driver`) when patch changes driver code that
  calls the of_* API but no DT file
- `Step 3f` — required when patch touches registers/probe/remove/PM/IRQ/DMA

If the generated marker or any unconditional section is missing, the rules
assembly (Step J) failed — re-run it.  If a conditional section is missing when
its trigger is present, re-run Step J with the matching flag.

If ANY check fails: STOP, report which check failed and for which patch,
and fix the issue before spawning.  Never spawn a subagent with incomplete
inputs.

### E2 — Subagent Mandatory Step Completion Proof

The Step Completion Record schema and subagent-side rules are defined in
`refs/core.md` Step 5c.  The orchestrator does not duplicate that schema here;
it validates the required markers and counts in E3 below.

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
     - step_3d_dt_binding = DONE  (if patch touches .yaml/.dts/.dtsi/of_match)
     - step_3f_hardware_eng = DONE (if patch touches registers/probe/PM/IRQ/DMA)
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
□ 8a. For any patch with function-level code changes, Code Logic Maps contain
     all three surrounding-code audit lines:
     - `codebase audit: entrypoints ...`
     - `codebase audit: callees ...`
     - `codebase audit: siblings ...`
□ 9. No orphan HTML tags (open <div> count == close </div> count)
□ 10. Early block validator exits 0 using the saved patch corpus and prompt:
     ```bash
     python3 <skill_dir>/scripts/validate_review.py \
         --block-file <project_path>/tmp/patch_<N>_block.html \
         --patch-file <project_path>/tmp/patch_<N>_diff.txt \
         --prompt-file <project_path>/tmp/patch_<N>_prompt.md \
         --evidence-file <project_path>/tmp/evidence/patch_<N>_evidence.json \
         --tests <project_path>/tmp/tests_<slug>.txt \
         --build-file <project_path>/tmp/patch_<N>_build.txt \
         --require-patches \
         --source-root <project_path>
     ```
     This is the same validator as final Step 6.7, run while the per-patch
     evidence and prompt are still local.  It enforces gate traces, completion
     records, source-aware PM/DT/helper/resource checks, prompt-artifact
     completeness, and evidence-manifest coverage before the block can be
     assembled into the final report.
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

Subagent-side enforcement is defined in `refs/core.md`:
- Step 5 ordering and mandatory section presence live in Step 5b.
- Step Completion Record and self-audit requirements live in Step 5c.
- Gate trace requirements live in Step 5d.

The orchestrator enforces those requirements through the E3 validation checklist
and re-spawn policy above.

### E8 — Review File Completeness Gate (Orchestrator)

After assembling all block files into the final HTML and before declaring
the review complete, the orchestrator MUST verify:

```
FINAL_REVIEW_GATE:
□ 1. File exists at expected path
□ 2. File starts with "<!DOCTYPE html>"
□ 3. File contains exactly T commit-block divs (count occurrences of
     'class="commit-block"')
□ 4. File contains a verdict banner (class="verdict-banner")
□ 5. File contains the test results table (class="test-table")
□ 6. File ends with "</html>"
□ 7. All T Step Completion Records are present in the file
□ 8. `scripts/validate_review.py <html_path> --tests tests_<slug>.txt`
     exits 0 (Step 6.7 — structural validator).  This is the single
     source-of-truth check for gate traces, canonical block anchor ids,
     banner anchor links, DT / Hardware Engineering section headers,
     banner ↔ block consistency, build-break presence/ordering, interactive
     Kconfig build-log rejection, hardware trigger consistency, refactor
     coverage, and future-risk gating.
     E8 cannot pass while the validator fails.
```

If ANY check fails: the review file is malformed.  Report the failure and
attempt to fix (re-assemble from block files).  If un-fixable, abort and
report to user.

## Steps 3b–5 — Review Checklists (Rules Brief Only)

Patch-level review rules are consumed only through the Step J generated and
E1.3 validated `patch_<N>_rules.md`.  Subagents and sequential main-agent
fallbacks read that file first, then apply the included coding-style, logic,
DT/DT-binding when triggered, commit-message/scope, hardware when triggered,
three-gate, output-format, and special-case rules.

The orchestrator does not re-implement these checklists.  Its responsibility is
to assemble and validate the rules brief, pass it in the prompt, then verify the
sidecar and HTML block after the patch review completes.

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
fragments as defined in `refs/core.md` Step 5b.

### CSS class mapping

CSS class mappings are the source of truth in `refs/html-template.md`
(`CSS Class Mapping Reference`) and are mirrored for subagents in
`refs/core.md` (`CSS Class Mapping`).

The orchestrator creates and closes the HTML file.  Each Per-Patch Reviewer
Subagent writes exactly one commit block to its own
`tmp/patch_<N>_block.html` file and one checkpoint sidecar line.  After all
subagents in a group complete, the orchestrator assembles the block files into
the HTML in patch order (Step 6.4).  The orchestrator never writes commit
blocks directly.

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
- **FRESH START**: proceed with steps 6.1–6.9 below.

6.1. **Create the HTML skeleton** using the runtime's structured file-writing mechanism (≤ 120 lines):
   Write from `<!DOCTYPE html>` through the closing `</div>` of the draft
   verdict banner.  Do NOT include the Test Results section or commit blocks.
   Leave the file open (no `</body></html>` yet).
   The verdict banner is a draft — reconcile it in step 6.6.

6.2. **Append the Test Results block** using the runtime's structured file-editing mechanism.
   Run `tail -8 <file>` first; copy exact bytes as `old_string` anchor.

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

6.4. **Assemble commit blocks into HTML** — after all groups complete, in order:

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
   ```html
   <div class="page-footer">
     Generated by AI agent (qgenie) &mdash; <em>YYYY-MM-DD</em>
   </div>
   </div><!-- /page-wrap -->
   </body>
   </html>
   ```

6.6. **Reconcile the verdict banner (mandatory)**

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

   After step 6.6 reconciliation and before any further confirmation, run:

   ```bash
   python3 <skill_dir>/scripts/validate_review.py \
       <project_path>/<filename> \
       --tests <project_path>/tmp/tests_<slug>.txt \
       --patches-dir <project_path>/tmp/review_patches \
       --evidence-dir <project_path>/tmp/evidence \
       --require-patches \
       --source-root <project_path>
   ```

   The validator checks gate traces, STEP_COMPLETION_RECORDs, DT / Hardware
   Engineering section headers, banner ↔ block badge counts, canonical
   block anchor ids, banner anchor-link dedup, and build-break
   presence/ordering.  Non-zero exit means a contract violation — the
   orchestrator MUST NOT skip this step or treat its failure as advisory.
   On failure:

   - Read the validator's structured output (one block per check category).
   - For `gate_trace` / `step_record` / `conditional_sections` /
     `anchor_id` violations:
     re-spawn the offending subagent once with the validator's message
     prepended as `IMPORTANT: validator rejected your block — <message>`.
   - For `banner_dedup` / `banner_consistency` violations: fix the banner in
     place using the structured file-editing mechanism, then re-run the
     validator. For `build_break_order` violations, fix the offending block
     or banner depending on the validator location, then re-run it.
   - If the validator still fails after one re-spawn / one banner fix:
     ABORT the review and report the remaining violations to the user.

   **Daemon rerun retention audit:** after this structural validator passes,
   daemon-managed runs compare the new report against the latest saved finding
   snapshot for the same review key.  A prior `[BUG]` or `[CONCERN]` may not
   disappear or be downgraded unless the new report contains an explicit,
   source-backed dismissal.  This audit is daemon-owned; the review agent must
   keep the report evidence-rich enough for the daemon to make that comparison.

6.8. **Confirm** after all chunks are written:
   ```bash
   wc -l <project_path>/<filename>
   ```
   A line count below 200 for a single-patch review suggests the file is
   incomplete (header + verdict + one commit block + footer typically exceeds
   200 lines).  Investigate before proceeding.

6.9. **Print the Overall Summary to the terminal** after confirming the file.
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
   rm -f ./<slug>.mbx ./<slug>.cover 2>/dev/null || true
   git checkout "$ORIGINAL_HEAD"
   git branch -D review/<slug> 2>/dev/null || true
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
- Use structured editing for all subsequent appends (steps 6.2, 6.4, 6.5, 6.6;
  step 6.3 uses subagent invocations, not file editing).
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

## Step 7 — Feedback Calibration Memory

Run this step only in Mode D, or when the user explicitly asks to update memory
after maintainer/reviewer comments become available.

### 7.1 Compare Feedback Against Saved Review

For each maintainer/reviewer comment:
- Map it to the patch, file, function, category, and review finding when
  possible.
- Classify the relationship as `confirmed`, `related`, `missed-by-us`,
  `false-positive`, `maintainer-preference`, or `subsystem-convention`.
- Treat maintainer comments as calibration evidence for future reviews, not as
  proof that an unrelated current finding is correct.

### 7.2 Decide Memory Action

- **Add** an entry when feedback reveals a reusable rule, common maintainer
  expectation, or repeated review miss.
- **Update** an entry when feedback refines triggers, review action, confidence,
  scope, or false-positive guards.
- **Deprecate** an entry when later feedback contradicts it, it is too narrow,
  it causes false positives, or it is stale.
- **Remove** deprecated entries only after they are no longer useful for audit.

### 7.3 Write Curated Memory Only

- Store distilled patterns under `refs/memory/`; do not store raw email text or
  long lore excerpts.
- Search existing `MEM-####` entries before adding a new one; avoid duplicates.
- Use the entry format from `refs/memory/index.md` exactly.
- Start one-off observations as `draft`; promote to `active` only after direct
  maintainer feedback or repeated evidence.
- Include false-positive guards for every active entry.
- Run `scripts/memory_lint.py` after every memory edit and fix reported issues.

### 7.4 Report Calibration Result

Summarize what changed:
- Added, updated, deprecated, or removed memory IDs.
- Which maintainer feedback motivated each change.
- How future reviews should load and apply the changed memory.

**HTML conformance rules**:

Use `refs/html-template.md` as the source of truth for the full document
skeleton, CSS classes, header table, verdict banner, test table, and footer.
Use `refs/core.md` Step 5b as the source of truth for per-commit and per-file
block fragments written by subagents.  Do not invent additional CSS classes,
custom structure, or alternate finding-card layouts.
