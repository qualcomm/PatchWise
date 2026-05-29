# Startup Workflow

This file is the startup path and source of truth for normal reviews. Read it
**before any tool action** instead of loading the full
`refs/orchestrator-workflow.md` upfront. Its goal is to get the run to the
first concrete artifacts quickly:
`<project_path>/tmp`, fetched/applied patches or commit list, per-patch test
artifacts, review packets, and the test summary table.

Validator and repair references for startup artifacts point here, not to the
later post-startup workflow.

Do **not** read `refs/orchestrator-workflow.md` during startup unless this file
explicitly tells you to. Defer the full workflow until startup artifacts are
ready and you are about to spawn per-patch subagents, enter sequential
main-agent fallback review, assemble HTML, or write the final report.

## Startup Scope

This startup workflow covers the **Mode A/B series path**:
- Step 0 — repo sync / branch setup
- Step 1 — obtain commits or patches
- Step 1b — optional memory lookup trigger routing
- Step 2 — unified per-patch extraction / build / DT / review packet prep
- Step 2.1 — dependency graph and group assignment
- Step 3 — test summary table generation

**Mode C** (single-file review) does not use this file at all — its Steps 0–3
live in `refs/mode-c-workflow.md`.

After Step 3 completes, switch to `refs/orchestrator-workflow.md` for:
- per-patch subagent prompt format
- block validation and retry rules
- HTML assembly and final save rules
- cleanup sequencing

## Startup Rules

- Act as the **orchestrator** only. Do not attempt patch-level review during
  startup.
- Prioritise creating concrete artifacts over reading long rule documents.
- Create `<project_path>/tmp` as soon as the selected mode is known and the
  target repo path is confirmed.
- Keep cleanup deferred until the daemon/runtime says it is safe.
- If this startup workflow conflicts with the later full workflow, follow this
  startup workflow until Step 3 completes, then switch to the full workflow.

## Mode Selection

Use the same mode mapping as `SKILL.md`:
- Mode A: `Project path` + commit count or revision range
- Mode B: `Project path` + `Message-ID`
- Mode C: `Project path` + file path

If the mode is unclear, stop and ask.

**Mode C is handled elsewhere.** This startup workflow covers the Mode A/B
series path only. When the selected mode is C (single-file review), read
`refs/mode-c-workflow.md` instead — it owns Mode C Steps 0–3 and hands off to
`refs/orchestrator-workflow.md` the same way this file does.

## Step 0 — Sync Repository and Create Review Branch

**Orchestrator initialization (mandatory — before any other action):**

Resolve `SKILL_DIR` — the directory containing this `SKILL.md` file. In
the active CLI runtime, this is the skill's install path (the directory from
which the skill was loaded). Set it once and use it throughout:

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

Keep these names stable throughout the run. If any later step changes HEAD,
restore `ORIGINAL_HEAD` during cleanup unless the user explicitly requested to
stay on the temporary review branch.

Before obtaining any commits, ensure the local repository is up to date and
checked out at a known-good base.

```bash
cd <project_path>
mkdir -p <project_path>/tmp

# Check for uncommitted changes BEFORE doing anything else (Modes A, B, C).
# The per-patch git checkout loop in Step 2 will fail or clobber a dirty tree.
git status --short
```

If `git status` shows any modified or staged files, **stop** and report:
"Working tree has uncommitted changes — please stash or commit them before
running the review." Do not proceed until the tree is clean.

```bash
# Fetch latest commits and tags from the tracked remote.
# For Modes A and C: a fetch failure is non-fatal — proceed with the local
# tree and note "git fetch failed: <error>" in the Test Results header.
# For Mode B: a fetch failure is fatal — stop and report the error.
git fetch --tags

# Mode B only: checkout the latest linux-next tag as the clean base for git am.
# Modes A and C must NOT checkout any tag here — their commits are already in
# the local tree and must remain reachable from the current HEAD. Changing
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
  proceeding. For `git fetch`, follow the mode-specific rule above: fatal for
  Mode B, non-fatal for Modes A/C with the failure recorded in Test Results.
- The review branch is created from this clean tag base: Mode B creates it
  with `git checkout -b` in Step 1 before applying patches via `git am`;
  Modes A and C do not require a dedicated branch.

## Step 1 — Obtain the Commits

### Mode A

**Slug derivation (mandatory):** Mode A uses a slug for all internal paths
(sidecar, test files, group assignment). Derive it as:
```
<slug> = <repo-basename>_last<count>
```
For example: reviewing the last 5 commits in a repo cloned to
`/home/user/linux-next` -> slug = `linux-next_last5`.
For revision-range reviews: `<slug> = <repo-basename>_<sanitized-range>`
where `<sanitized-range>` replaces non-alphanumeric characters with `_`
(e.g. `HEAD~5..HEAD` -> `HEAD_5__HEAD`).

```bash
cd <project_path>

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
  applied. Record the patch number and tag for every such line, for example:
  ```
  b4_collected_trailers = {
    2: ["Reviewed-by: Konrad Dybcio <konrad.dybcio@oss.qualcomm.com>"],
    5: ["Reviewed-by: Konrad Dybcio <konrad.dybcio@oss.qualcomm.com>"],
  }
  ```
  This record is used in Step 3e to suppress false tag-ordering findings
  (see Step 3e trailer-ordering mandatory check).

If no `Total patches:` line despite exit 0: report full output and **stop**.

**Cover-letter-as-patch-0 check**: b4 sometimes includes the cover letter as
patch 0 in the mbx (subject line `[PATCH 0/N]` or `[RFC 0/N]`). After
parsing `Total patches:`, check the first entry in the mbx: if its subject
matches `^\[.*0/`, it is the cover letter, not a code patch. Subtract 1
from the `Total patches:` count before comparing against the applied commit
count in the patch-count check below.

**Cover letter dependency check (mandatory — do this before applying patches):**

Read `./<slug>.cover` immediately after `b4 am` succeeds. Scan the cover
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
`Dependencies: none stated` in the header and proceed. Do **not** recommend
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
the slug is `v7_20260325_yingchao_deng_add_qualcomm_extended_cti_support`). This
is the same slug used for the review filename in Step 6.

If `git am` fails: run `git am --show-current-patch=diff` to identify the
exact failing hunk, then run `git am --abort`. Before stopping, diagnose
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

**IMPORTANT — still produce the standard HTML report.** Emit a CANNOT APPLY
report following the authoritative "Apply-failure variant" structure in
`refs/html-template.md` (verdict class `cannot-apply`, the apply-failure
diagnostic finding replacing per-patch findings, per-commit blocks omitted).
Do not re-describe that structure here — `refs/html-template.md` is the single
source of truth for it. The only review-specific content you supply is the
diagnostic analysis above (failing file/hunk, suspected cause, rebase need).

Do NOT fall back to reading patches from the mbx file directly and continuing
the review. Reading multiple patches in one batch collapses the per-patch
before/after boundary, making inter-patch bisectability violations invisible:
a write removed in patch N and restored in patch N+1 looks correct when both
are read together, but the tree is broken between them. The only safe review
path requires each patch applied as a discrete commit.

Note: `git am --abort` rolls back **all** patches that were successfully
applied before the failure, returning the branch to its pre-`git am` state.

Confirm with `git log --oneline HEAD~<N>..HEAD`, then proceed to Step 2.
**Patch count check (mandatory):** count the commits in that log output and
compare against `Total patches:` from `b4 am`. If the counts differ, `b4 am`
silently dropped patches (e.g. threaded replies misidentified as non-patches).
Stop, report the discrepancy with the exact counts, and ask the user how to
proceed — do not review a partial series as if it were complete.
Do **not** delete `.mbx` / `.cover` yet — they may be needed for context during
the review. Cleanup happens after the review file is written (see Step 6.10).

**Post-review branch cleanup (Mode B — mandatory after review file is
confirmed written):** delete the review branch to keep the repository tidy:
```bash
git checkout <base-commit-or-previous-HEAD>
git branch -D review/<slug>
```
This is done in Step 6.10 alongside mbx/cover file deletion.

### Mode C

Mode C (single-file review) is handled entirely in `refs/mode-c-workflow.md`.
Read that file instead and do not continue with Step 2 / Step 2.1 / Step 3
here.

## Step 2 — Startup Artifact Generation

This step is **mode-specific**. Follow only the branch that matches the
current mode.

---

### Mode B — Unified per-patch loop (extraction + build + DT-binding)

One sequential loop replaces the former separate extraction and build loops,
reducing git checkouts from 3N -> N. Checkpatch and get_maintainer run as
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
SERIES_MANIFEST="<project_path>/tmp/series_manifest_${slug}.json"
RUNTIME_CONFIG="<project_path>/tmp/review_runtime_config.json"

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
#    Skip when w1_build_check is disabled in the runtime config (DTS-only / docs-only series).
W1_BUILD_ENABLED=1
DT_CHECK_ENABLED=1
if [ -f "${RUNTIME_CONFIG}" ]; then
    W1_BUILD_ENABLED=$(python3 - "${RUNTIME_CONFIG}" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(1 if payload.get("w1_build_check", True) else 0)
PY
)
    DT_CHECK_ENABLED=$(python3 - "${RUNTIME_CONFIG}" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(1 if payload.get("dt_check", True) else 0)
PY
)
fi
REVIEW_BASE=$(git rev-parse "${REVIEW_TIP}~${T}")
git checkout "${REVIEW_BASE}"
if [ "${W1_BUILD_ENABLED}" = "1" ]; then
    python3 "${SKILL_DIR}/scripts/run_w1_build.py" \
      --project <project_path> \
      --output /dev/null \
      --arch arm64 \
      --cross-compile aarch64-linux-gnu- \
      <all_affected_dirs>/ || {
        echo "ERROR: warm W=1 build failed or produced invalid interactive Kconfig output"
        exit 1
      }
fi
# run_w1_build.py always seeds `make ARCH=arm64 defconfig`, then runs
# `make ARCH=arm64 olddefconfig`, before refreshed W=1 builds. Captured build
# artifacts containing `Restart config...` are invalid because they are Kconfig
# prompt transcripts, not clean compiler/check output.
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

    # F — W=1 incremental build for this patch's affected dirs.
    # Skipped when w1_build_check=false in the runtime config.
    if [ "${W1_BUILD_ENABLED}" = "1" ]; then
        python3 "${SKILL_DIR}/scripts/run_w1_build.py" \
          --project <project_path> \
          --output <project_path>/tmp/patch_${N}_build.txt \
          --arch arm64 \
          --cross-compile aarch64-linux-gnu- \
          <affected_dirs_for_current_patch>/ || {
            echo "ERROR: invalid W=1 build artifact for patch ${N}"
            exit 1
          }
    else
        echo "(W=1 build skipped — w1_build_check disabled by config)" \
          > <project_path>/tmp/patch_${N}_build.txt
    fi
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

    # H — DT binding check (only when .dts/.dtsi files changed)
    # YAML binding (`Documentation/devicetree/bindings/*.yaml`) checks have
    # been hoisted out of this loop into a single series-level invocation —
    # see "Step 2.2 — Series-level dt_binding_check (hoisted)" below — because
    # a per-patch invocation re-pays the ~24s cold dtschema startup K times
    # for K DT-binding patches.  CHECK_DTBS for DTS/DTSI consumers stays
    # per-patch because each patch typically resolves to different DTBs.
    #
    # Safety contract: DT validation must be patch-scoped, bounded, and recorded
    # in tmp/patch_${N}_dtbinding.txt. Never run unscoped `make dt_binding_check`,
    # `make dtbs_check`, raw `dt-doc-validate`, or raw `dt-validate`; those can
    # fan out into full-tree schema validation and block packet generation.
    # Stdin contract: every `make` invocation below pipes `yes ""` so the
    # build-triggered Kconfig syncconfig (deliberately interactive in the
    # kernel top Makefile) accepts defaults non-interactively. Without this,
    # syncconfig hits EOF on prompts and dumps the entire arm64 errata
    # Kconfig walk into the dtbinding artifact instead of real check output.
    DT_CHECK_JOBS="${DT_CHECK_JOBS:-64}"
    DT_CHECK_TIMEOUT="${DT_CHECK_TIMEOUT:-600}"
    if [ "${DT_CHECK_ENABLED}" = "0" ]; then
        # DT binding/DTB checks disabled by config; skip this step.
        true
    elif <patch N touches .dts or .dtsi files>; then
        mapfile -t DTB_TARGETS < <(
            python3 "${SKILL_DIR}/scripts/resolve_dtb_targets.py" \
              --project <project_path> \
              --patch-file <project_path>/tmp/patch_${N}_diff.txt
        )
        if [ "${#DTB_TARGETS[@]}" -gt 0 ]; then
            {
                echo "Resolved DTB targets for patch ${N}: ${DTB_TARGETS[*]}"
                if yes "" | timeout "${DT_CHECK_TIMEOUT}" make ARCH=arm64 \
                  CROSS_COMPILE=aarch64-linux-gnu- CHECK_DTBS=1 -j"${DT_CHECK_JOBS}" \
                  "${DTB_TARGETS[@]}"; then
                    echo "DTB validation: PASS"
                else
                    status=$?
                    if [ "${status}" -eq 124 ]; then
                        echo "DTB validation: TIMEOUT after ${DT_CHECK_TIMEOUT}s — manual review required"
                    else
                        echo "DTB validation: FAIL status=${status}"
                    fi
                fi
            } >> <project_path>/tmp/patch_${N}_dtbinding.txt 2>&1
        else
            echo "(no concrete DTB targets resolved from touched .dts/.dtsi files — manual DT review required)" \
              >> <project_path>/tmp/patch_${N}_dtbinding.txt
        fi
    fi
    # Never run full-tree "make dtbs_check" or unscoped "make dt_binding_check"
    # for a single patch. Use DT_SCHEMA_FILES=<changed.yaml> for binding YAML,
    # or CHECK_DTBS=1 with resolved per-patch DTB targets for DTS/DTSI changes,
    # so DT validation stays scoped to touched files or concrete DTS consumers of
    # a changed DTSI. `resolve_dtb_targets.py` must emit only DTBs that are
    # actually declared by kernel DT Makefiles, rather than every top-level .dts
    # consumer it can find under arch/*/boot/dts.
    # If neither condition applies, do not create patch_${N}_dtbinding.txt.

    # I — series structure summary entry comes from SERIES_MANIFEST:
    # "<N>/<T> <short_hash> "<subject>" [Fixes: yes/no]".

    # J — Assemble the packet-only per-patch review artifact
    # SKILL_DIR is set by the orchestrator at the start of the review run
    # (see "Orchestrator initialization" in Step 0). The packet assembler loads
    # only reviewer-base, output-format-mini, selected rule cards, bounded context
    # snippets, evidence metadata, commit message, and patch diff. Do not
    # hand-concatenate refs or generate a per-patch rules brief for Mode A/B.
    PACKET_OUT="<project_path>/tmp/patch_${N}_review_packet.md"
    PACKET_JSON_OUT="<project_path>/tmp/patch_${N}_review_packet.json"
    python3 "${SKILL_DIR}/scripts/assemble_review_packet.py" \
      --skill-dir "${SKILL_DIR}" \
      --manifest "${SERIES_MANIFEST}" \
      --patch "${N}" \
      --project <project_path> \
      --output "${PACKET_OUT}" \
      --json-output "${PACKET_JSON_OUT}"
    python3 "${SKILL_DIR}/scripts/validate_review_packet.py" \
      "${PACKET_OUT}" \
      --skill-dir "${SKILL_DIR}" \
      --json "${PACKET_JSON_OUT}"
    # Packet size/card-count budget messages are warnings used to guide prompt
    # shrinking. Forbidden workflow leaks, missing refs, malformed JSON, and
    # missing context-coverage inventory remain hard validation failures.
    # If assembly or validation fails, stop and fix the selector/assembler
    # inputs; do not spawn a subagent with a manual fallback.
done

git checkout "${REVIEW_TIP}"
```

**Step 2.2 — Series-level dt_binding_check (hoisted):**

YAML binding (`Documentation/devicetree/bindings/*.yaml`) checks are run once
across the whole series at REVIEW_TIP, not per-patch.  A per-patch invocation
re-pays the ~24s cold dtschema startup K times for K DT-binding patches; the
hoisted call validates all touched YAMLs in one make invocation and the helper
splits output back into the existing per-patch
`tmp/patch_<N>_dtbinding.txt` files so the consumer contract is unchanged.

```bash
if [ "${DT_CHECK_ENABLED:-1}" = "1" ]; then
    python3 "${SKILL_DIR}/scripts/hoist_dt_binding_check.py" \
      --project <project_path> \
      --manifest "${SERIES_MANIFEST}" \
      --arch arm64 \
      --jobs "${DT_CHECK_JOBS:-64}" \
      --timeout "${DT_CHECK_TIMEOUT:-600}" || {
        echo "WARNING: hoisted dt_binding_check returned non-zero — per-patch dtbinding files will reflect the failure"
    }
else
    echo "(dt_binding_check skipped — dt_check disabled by config)"
fi
```

The helper:
- reads `${SERIES_MANIFEST}` to find every patch that touched a binding YAML;
- runs `make ARCH=arm64 DT_SCHEMA_FILES=<a.yaml>:<b.yaml>:... dt_binding_check`
  with the same `yes ""` stdin contract used elsewhere in this workflow;
- routes each output line to the per-patch file(s) whose YAML(s) the line names;
- routes header/banner noise (`SCHEMA …`, `DTC …`) to every YAML-touching
  patch so per-patch readers see the same surrounding context;
- writes `DT binding check: PASS|FAIL|TIMEOUT` per file to match the previous
  per-patch verdict shape.

Patches that touched only `.dts/.dtsi` (no YAML) keep using the per-patch
CHECK_DTBS path inside the loop above; the hoisted helper does not touch
their `patch_<N>_dtbinding.txt`.

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
# in SERIES_MANIFEST. This replaces the former per-patch sparse runs (N x
# directory build -> 1 x targeted object build), saving N-1 full sparse
# compilations and preserving Mode A revision-range correctness.
SPARSE_TARGETS=$(python3 - "${SERIES_MANIFEST}" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
targets = sorted({path[:-2] + ".o" for patch in manifest["patches"] for path in patch["files"] if path.endswith(".c")})
print(" ".join(targets))
PY
)
RUNTIME_CONFIG="<project_path>/tmp/review_runtime_config.json"
SPARSE_ENABLED=1
if [ -f "${RUNTIME_CONFIG}" ]; then
    SPARSE_ENABLED=$(python3 - "${RUNTIME_CONFIG}" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(1 if payload.get("sparse_check", True) else 0)
PY
)
fi
if [ "${SPARSE_ENABLED}" = "0" ]; then
    echo "(sparse disabled by config)" \
      > <project_path>/tmp/sparse_<slug>.txt
elif [ -n "$SPARSE_TARGETS" ]; then
    yes "" | make ARCH=arm64 C=1 CF="-D__CHECK_ENDIAN__" -j99 $SPARSE_TARGETS \
      > <project_path>/tmp/sparse_<slug>.txt 2>&1
else
    echo "(no .c files changed — sparse skipped)" \
      > <project_path>/tmp/sparse_<slug>.txt
fi
```

**Series manifest and structure summary:** `SERIES_MANIFEST` is the source of
truth for patch number, hash, subject, files, DT/HW triggers, memory categories,
and generated artifact paths. Build the subagent `Series summary:` from
`manifest["patches"]` in this format:

```
1/<T> <short-hash> "<subject>" [Fixes: yes/no]
2/<T> <short-hash> "<subject>" [Fixes: yes/no]
...
```

---

### Mode A — Unified per-patch loop (local commits)

Mode A commits are already in the local tree. Build the ordered commit list in
Step 1 and use it as the source of truth for patch numbers, patch files, and
hash self-audits. Do not assume `HEAD~<count>..HEAD` when the user supplied a
revision range.

```bash
cd <project_path>

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
RUNTIME_CONFIG="<project_path>/tmp/review_runtime_config.json"

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
#    In loop step A, checkout PATCH_N_HASH from SERIES_MANIFEST. The same
#    manifest also drives DT/HW/memory rule flags and series summary text.
```

After the loop: `git checkout "${REVIEW_TIP}"`, then collect background results
and run sparse using the manifest-derived target list from the common post-loop
step above.

---

### Mode C — Single file, no patches

Mode C does not use this step. The single-file tool runs and rules-brief
assembly live in `refs/mode-c-workflow.md` Step 2. If the selected mode is C,
you should already be following that file instead of this one.

---

### Step D scope limit (applies to all modes)

The orchestrator must choose at most **4 context files per patch** to pass
to the subagent — headers, Kconfig, Makefile, and any `Documentation/ABI/`
file named in the diff. Do not follow `#include` chains. Never pass
pre-patch base-commit file contents — the diff context lines are sufficient.
When the patch changes executable logic, prefer context files that help the
mandatory surrounding-code audit succeed: the changed file, the immediate
dispatcher/selector/callback registration site, the most relevant helper body,
and any sibling/alternate mode file or wrapper schema that can still reach the
same abstraction.

### Step D' — Mandatory surrounding-code audit and targeted reads (applies to all modes)

The kernel tree is checked out at the patch's post-apply commit
(`PATCH_N_HASH`) at `<project_path>`. When a finding's correctness
depends on surrounding-code facts, the subagent MUST build a
surrounding-code audit before clearing the issue. For every packet-mode patch,
the visible Code Logic Maps audit must cover:
- entrypoints / dispatch / selectors into the changed logic;
- helper bodies / callee contracts / side effects relied upon by the review;
- sibling or alternate paths that can still reach the same abstraction or
  hardware mode after the patch;
- lifecycle/workflow edges for changed state, including entry, success, failure,
  early-return, paired cleanup, async, and remove/shutdown paths.

For DTS/YAML-only patches, do not replace these lines with `codebase audit: N/A`.
Map `entrypoints` to the relevant binding/DTS consumers, thermal/OF/schema
readers, or subsystem registration path; map `callees` to schema/property/
phandle interpretation; and map `siblings` to parent/sibling DTSI/DTS or schema
variants checked for compatibility and ordering; map `state/lifecycle` to
consumer-visible compatibility, ordering, and old/new tree behavior when no C
function lifecycle exists.

The subagent records this proof in the Code Logic Maps section using the
exact labels `codebase audit: entrypoints ...`, `codebase audit: callees ...`,
`codebase audit: siblings ...`, and `state/lifecycle: ...`.

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
patches can be reviewed concurrently. The manifest is generated by
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
   conservative model. Groups remain sequential — Group k starts only after
   all subagents in Group k-1 have completed and been validated.

**Example** (7-patch series):
```
Patch 1: drivers/foo.c, drivers/bar.c
Patch 2: Documentation/bindings/foo.yaml   <- no shared files -> Group 1
Patch 3: drivers/foo.c                     <- shares foo.c with patch 1 -> Group 2
Patch 4: arch/arm64/dts/qcom/soc.dtsi      <- no shared files -> Group 1
Patch 5: drivers/bar.c                     <- shares bar.c with patch 1 -> Group 2
Patch 6: drivers/baz.c                     <- no shared files -> Group 1
Patch 7: drivers/foo.c, drivers/bar.c      <- shares with 1, 3, 5 -> Group 3

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
This file drives the spawn schedule in `refs/orchestrator-workflow.md` Step 6.
If a manifest dependency reason looks overly conservative, keep the safer
sequential grouping; do not manually move patches earlier unless direct code
inspection proves independence.

**Mode C**: no patches — skip this step entirely.

## Step 3 — Compile Test Summary

By the end of Step 2's unified loop, all per-patch results are already saved:

| File | Contents |
|---|---|
| `tmp/tests_<slug>.txt` | checkpatch + get_maintainer (all patches) |
| `tmp/patch_<N>_build.txt` | W=1 build output at patch N's tree state |
| `tmp/sparse_<slug>.txt` | sparse output at REVIEW_TIP, all changed .c files |
| `tmp/patch_<N>_dtbinding.txt` | dt_binding_check + dtbs_check (only when applicable) |

Mark sparse `SKIP` only when `which sparse` returns non-zero, or when an
explicit daemon/runtime override disables sparse for the run. In the
runtime-disable case, do not run sparse; write
`<project_path>/tmp/sparse_<slug>.txt` with the single line
`(sparse disabled by config)` and use the summary note `disabled by config`.
Mark build `SKIP` only if `.config` generation also fails.

> **Manual runs:** when you invoke this skill directly (outside the daemon),
> the sparse-disable override is enforced only by this instruction plus the
> post-review validator — there is **no** `make` wrapper intercepting `C=1`
> (that PATH-injected guard exists only on the daemon path). So honor the
> override yourself: do not run sparse, and write the sentinel exactly as
> above, or the validator will fail the report.

**Do not clean up temporary patch files after the test summary table.**
`<project_path>/tmp/review_patches/*.patch` is a required validation artifact
for early block checks and final source-aware validation. Keep it until
`refs/orchestrator-workflow.md` Step 6.10 cleanup, and in daemon-managed runs
leave cleanup to the daemon-side post-validation path.

### 3.1 Test summary table

Output before the per-commit review. Build, sparse, and DT-binding rows show
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

List checkpatch findings in full beneath the table. Build findings for each
patch are reported in the per-commit block. Sparse findings are from the
shared post-loop run — each per-commit block reports findings filtered to
files that patch touches.

At the end of Step 3, startup is complete.

## Handoff To Full Workflow

Only now read `refs/orchestrator-workflow.md`, then continue with:
- per-patch subagent prompt generation and spawn
- fallback sequential main-agent review if needed
- block validation / retries
- HTML assembly and final save
- cleanup
