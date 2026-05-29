## Step 3e — Commit Message & Patch Scope Review

Apply this checklist to every commit. Linux upstream expects one logical change
per patch; scope violations commonly cause rejection.

### 3e.1 Single-Responsibility Rule  ← most important

**Upstream policy: one patch = one purpose.** A valid patch does exactly one of
these and nothing independent: fixes one identified bug/root cause, adds one
feature/driver, performs one cleanup/refactor, or updates one document/binding.

**How to verify:** after reading the diff, write one imperative sentence that
fully describes the patch. If that sentence needs "and" for independent actions,
the patch likely violates scope.

**Raise `[CONCERN] Patch Scope`** when a patch:
- Fixes multiple independent bugs, each needing its own `Fixes:` tag.
- Mixes a bug fix with cleanup/style work in different files/subsystems, or with
  cleanup large enough to obscure the fix. Do not flag tiny local comment or
  whitespace cleanup in the same function.
- Adds a feature while fixing a pre-existing independent bug.
- Touches unrelated files/subsystems without a logical dependency.
- Uses a subject with "and", "also", "plus", or multiple actions after you
  confirm those actions are independent. Do not flag inseparable hardware
  features or multiple manifestations of one root cause.
- Describes two or more distinct problems in the body.
- Understates the diff scope, e.g. the subject says "Add X" but the diff also
  corrects unrelated pre-existing values.

**Do not flag** tightly coupled documentation/binding updates, one root-cause fix
applied identically to multiple call sites, a new driver split into logical
series layers, or a prerequisite refactor that remains independently coherent.

### 3e.2 Subject Line Quality

- Imperative mood, ≤72 characters, and no trailing period.
- Prefix matches changed files: `subsystem: component: description`, e.g.
  `dt-bindings: media: qcom,sm8550-iris: Add X1P42100 compatible`.
- Do not use vague verbs such as "fix issue", "update code", "misc changes",
  "improve", "cleanup", or "refactor" without saying what changed.
- Cross-check against the diff. If the subject omits independent diff content,
  flag `[MINOR]` subject understatement and treat it as scope evidence.
- If the subject/body claims a new error path, failure propagation, reset, retry,
  cleanup, or hardware mode handling, verify the diff implements that behavior.
  A commit message that promises returned failure while code only warns, ignores
  the return, or keeps a `void` helper is at least `[MINOR]`; escalate when the
  mismatch hides a reachable functional failure.

### 3e.3 Commit Body Quality

- Explain why the change is needed, not just what changed.
- For fixes, describe symptom, root cause, and resolution.
- For features, describe the hardware/software requirement and how the
  implementation satisfies it.
- Do not describe two separate problems; split the patch instead.
- Add `Fixes:` for kernel regressions/bugs, with a 12-char hash and quoted
  subject. Rely on `scripts/checkpatch.pl` for exact format enforcement, and
  flag `[MINOR]` if checkpatch reports a malformed `Fixes:` tag.
- Add `Cc: stable@vger.kernel.org` only when the fix should be backported: the
  fixed commit is in stable-supported history or the body explicitly requests a
  stable backport. Do not treat every `Fixes:` as requiring stable Cc.
- Avoid `Depends-on:` in the body; prefer cover-letter notes or co-submission.
  If subsystem convention is unclear, flag only `[NIT]`.
- **Single-patch cover-letter guard:** never ask for a cover letter solely
  because a standalone/`1/1` patch lacks one. Put missing dependency/rationale
  context in the commit body, b4 prerequisite trailers, or dependency links;
  recommend a cover letter only for multi-patch series or an existing cover.

**Mandatory per-commit checks:**
1. **Missing body:** a subject-only commit lacks reviewer/`git blame` rationale;
   flag `[MINOR]`.
2. **Two-problems test:** if the body describes multiple distinct goals/problems,
   confirm against the diff and flag `[CONCERN] Patch Scope`.
3. **Subject-vs-diff:** if hunks include independent changes not covered by the
   subject, flag `[MINOR]` subject understatement.
   Also flag independent behavior changes hidden in a related table update, such
   as enabling a dynamic control flag while the patch claims to add only a
   different control.
4. **Fixes symptom check:** with `Fixes:`, require symptom, root cause, and fix
   explanation; flag `[MINOR]` if any are absent.
5. **Grammar/spelling:** flag `[NIT]` for subject/body typos or grammar errors.
6. **Trailer ordering/semantics:** preferred order is `Fixes:`, `Cc:`,
   `Reported-by:`, `Suggested-by:`, `Co-developed-by:`, `Tested-by:`,
   `Acked-by:`, `Reviewed-by:`, `Signed-off-by:`, `Link:`. `Link:` is usually
   maintainer/bot-added after `Signed-off-by:` and must not be flagged merely
   for appearing last.
   - Do not flag trailer presence/absence mechanically. If `Cc: stable` appears
     without `Fixes:`, apply `refs/special-cases.md`; if `Fixes:` lacks stable
     Cc, flag `[MINOR]` only when stable eligibility is demonstrated.
   - **b4-collected trailer exemption (Mode B only):** `Reviewed-by:`,
     `Acked-by:`, `Tested-by:`, or `Link:` after the last `Signed-off-by:` may be
     appended by b4 from reply emails; exclude those from ordering findings.
   - **Absence of review tags is NOT a finding:** never flag missing
     `Reviewed-by:`, `Acked-by:`, or `Tested-by:` on a posted patch. Only check
     ordering for tags already present.
   - **Trailer semantics:** `Co-developed-by:` must name someone other than the
     `From:` author; flag `[MINOR]` if redundant. AI/tool disclosure should be
     prose or a documented bare trailer such as `Assisted-by: <tool>`; flag
     `[NIT]` for colon-chained values such as `Assisted-by: Tool:model`.

### 3e.4 Series-Level Scope Check

For multi-patch series:
- Each patch must be independently bisectable. Read
  `<project_path>/tmp/patch_<N>_build.txt` for each patch and flag `[CONCERN]`
  if an intermediate tree has touched-file `error:` or `warning:` lines.
- Boot bisectability is not mechanically proven. Flag `[CONCERN]` only when an
  intermediate patch is actively harmful/crash-prone, e.g. a DTS node is enabled
  before any in-series driver can handle its `compatible`. Do not flag merely
  incomplete intermediate functionality.
- Tightly coupled patches, such as binding plus driver, are acceptable in one
  series but must be dependency ordered, usually binding first.
- Do not bundle unrelated logical groups into one series for convenience.
- If fixes and feature/refactor work are mixed, determine whether the fix depends
  on the whole series or only a subset. Flag `[MINOR]` when an independently
  backportable fix is bundled with feature work; do not flag one inseparable fix
  unit or a cover-letter-explained dependency.
