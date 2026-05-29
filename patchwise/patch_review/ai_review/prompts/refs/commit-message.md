## Step 3e — Commit Message & Patch Scope Review

Apply this checklist to **every commit** in the series.  The upstream kernel
community enforces a strict one-patch-one-purpose rule; violations are a
common reason for patch rejection on the mailing list.

### 3e.1 Single-Responsibility Rule  ← most important

**Upstream policy: one patch = one purpose.**

Every patch submitted to the Linux kernel must have a single, clearly
stated purpose.  This is not a style preference — it is a hard upstream
requirement enforced by maintainers and documented in
`Documentation/process/submitting-patches.rst`:

> "Separate each **logical change** into a separate patch."
> "Each patch should do one thing and do it well."

A patch has exactly one purpose when it does **one** of the following and
nothing else:
- Fixes one specific, identified bug (one `Fixes:` tag, one root cause).
- Adds one new feature or driver.
- Performs one clean-up or refactor.
- Updates one piece of documentation or one binding.

**How to verify**: after reading the diff, write a single imperative
sentence that fully describes every change in the patch.  If you cannot
do so without using "and" to join two independent actions, the patch
violates this rule.

**Raise `[CONCERN] Patch Scope`** whenever a patch:
- Fixes two or more independent bugs in a single commit (each bug should be
  a separate patch, each with its own `Fixes:` tag).
- Combines a bug-fix with a clean-up or style change that touches **different files
  or subsystems**, or where the clean-up is large enough to obscure the fix.  A
  minor comment or whitespace correction in the same function being fixed is
  acceptable and must **not** be flagged.
- Adds a new feature and simultaneously fixes a pre-existing bug.
- Touches unrelated subsystems or files that have no logical dependency.
- Has a subject line that contains "and", "also", "plus", or lists multiple
  actions — a strong signal that the patch is doing more than one thing.
  **Before filing**: confirm the two things joined by "and" are logically
  independent; inseparable hardware features or multiple manifestations of
  a single root-cause bug are one purpose and must NOT be flagged.
- Has a body that describes two or more distinct problems being solved.
- Has a subject line that **understates** the actual diff scope — i.e. the
  subject describes only one of the things the patch does while the diff
  contains additional independent changes (e.g. subject says "Add X" but
  the diff also corrects pre-existing bug values unrelated to X).

**Acceptable combinations** (do NOT flag these):
- A bug-fix that must also update the corresponding documentation or binding
  in the same patch (tightly coupled change).
- A single-root-cause bug that manifests in multiple call sites may be fixed
  in one patch when all sites require the identical fix.  The subject may
  then say "fix X in all Y call sites" — this is one purpose, not many.
- A new driver split across multiple patches in a series where each patch
  adds one logical layer (e.g. patch 1: dt-binding, patch 2: core driver,
  patch 3: platform data).
- A preparatory refactor in patch N that is a prerequisite for the fix in
  patch N+1, as long as each patch is independently coherent.

### 3e.2 Subject Line Quality

- Imperative mood: "Add support for X", not "Adding" or "Added".
- ≤ 72 characters; no trailing period.
- Subsystem prefix matches the files changed:
  `subsystem: component: description`
  e.g. `dt-bindings: media: qcom,sm8550-iris: Add X1P42100 compatible`
- Does not contain "and" joining two independent actions.
- Does not use vague verbs: "fix issue", "update code", "misc changes",
  "improve", "cleanup", "refactor" (without specifying what was improved,
  cleaned, or refactored).
- **Accurately reflects all changes in the diff** — cross-check the subject
  against the actual diff: if the diff contains changes not described by
  the subject (e.g. bug-fix value corrections hidden inside a feature patch),
  flag it as `[MINOR]` subject understatement and as a secondary signal of
  a single-responsibility violation.

### 3e.3 Commit Body Quality

- Explains **why** the change is needed, not just what was changed.
- If fixing a bug: describes the root cause, the symptom, and how the patch
  resolves it.
- If adding a feature: describes the hardware/software requirement and how
  the implementation satisfies it.
- Does not describe two separate problems — if it does, the patch should be
  split.
- `Fixes:` tag present when the patch corrects a kernel regression or bug
  (with correct 12-char hash and quoted subject).
- `Cc: stable@vger.kernel.org` present only when the fix should be backported:
  first confirm the fixed commit is in stable-supported history or the body
  explicitly requests a stable backport.  Do **not** treat every `Fixes:` tag as
  automatically requiring `Cc: stable`.
- `Depends-on:` pseudo-tag in the body is discouraged — prefer a cover-letter
  note or co-submission.  Some subsystems (e.g. `drm/`) accept it; flag as
  `[NIT]` rather than `[CONCERN]` when the subsystem conventions are unclear.
- **Single-patch cover-letter guard**: do **not** raise a finding or
  suggestion asking for a cover letter solely because a standalone/`1/1` patch
  has no cover letter.  Upstream Linux does not normally require cover letters
  for one-patch submissions.  If required dependency or rationale context is
  missing, ask the author to put that context in the commit body, b4
  prerequisite trailers, or explicit dependency links; only recommend a cover
  letter for multi-patch series or when the author already has one.

**Mandatory per-commit body checks** — apply every item below to every commit:

1. **Missing body**: check whether the commit has a blank line after the subject
   followed by at least one body sentence.  A commit with a subject line only
   (no blank-line-separated body) must be flagged `[MINOR]` — upstream policy
   requires explaining *why* the change is needed, and an absent body provides
   no rationale for reviewers or future `git blame` readers.
2. **Two-problems test**: read the body and count how many distinct problems
   or goals are described. If more than one, flag `[CONCERN] Patch Scope`
   and cross-reference the diff to confirm.
3. **Subject vs. diff cross-check**: compare the subject line against the
   actual diff hunks. If the diff contains changes not covered by the
   subject, flag `[MINOR]` subject understatement.
4. **Fixes: symptom check**: if a `Fixes:` tag is present, verify the body
   describes (a) the observable failure/symptom, (b) the root cause, and
   (c) how the patch resolves it. Flag `[MINOR]` if any of the three is
   absent.
5. **Grammar and spelling**: flag `[NIT]` for any grammar errors or typos
   in the subject or body.
6. **Tag ordering**: correct order is `Fixes:`, `Cc:`,
   `Reported-by:`, `Suggested-by:`, `Co-developed-by:`, `Tested-by:`,
   `Acked-by:`, `Reviewed-by:`, `Signed-off-by:`, `Link:`.
   Note: `Link:` is added by patchwork/maintainer bots *after* the author's
   `Signed-off-by:` when the patch lands in a maintainer tree; it is not an
   author-written trailer and always appears last.  Do not flag `Link:` at the
   bottom of the trailer block as a tag-ordering violation.
   Do **not** flag trailer presence/absence mechanically.  If
   `Cc: stable@vger.kernel.org` is present without `Fixes:`, apply the stable
   special case in `refs/special-cases.md`.  If `Fixes:` is present without
   `Cc: stable@vger.kernel.org`, flag `[MINOR]` only when the fixed commit is
   demonstrably in stable-supported history or the commit body explicitly says
   the fix needs a stable backport; otherwise leave it unreported or phrase it
   as an optional verification note, not a finding.
   **b4-collected trailer exemption (Mode B only)**: b4 appends trailers
   harvested from reviewer reply emails (`Reviewed-by:`, `Acked-by:`,
   `Tested-by:`, `Link:`) *after* the author's `Signed-off-by:` lines.  This
   is b4's own convention — the author did not write these trailers in that
   position.  Identify b4-collected trailers by position: any `Reviewed-by:`,
   `Acked-by:`, `Tested-by:`, or `Link:` trailer that appears **after the last
   `Signed-off-by:` line** in the commit message is b4-appended and must be
   excluded from the tag-ordering check.  Do NOT file a `[MINOR]` tag-ordering
   finding against such a trailer.  The author will incorporate collected
   trailers in the correct position in the next revision.
   **Absence of review tags is NOT a finding**: Do NOT flag the absence of
   `Reviewed-by:`, `Acked-by:`, or `Tested-by:` tags on any patch, regardless
   of how "core" or critical the patch is.  A patch series posted to the
   mailing list is a *request for review* — these tags are added by maintainers
   and contributors *after* they respond.  It is normal and expected for a
   freshly posted series to have none of these tags.  Filing a finding for
   missing review tags is a hallucination of an upstream convention that does
   not exist.  Only flag issues with the *ordering* of review tags that are
   already present in the trailer block.
   **Trailer semantics**: `Co-developed-by:` must name a contributor other than
   the `From:` author; if it repeats the author, flag `[MINOR]` and suggest
   removing the redundant trailer.  AI/tool disclosure should be plain prose or
   a documented bare trailer such as `Assisted-by: <tool>`; flag `[NIT]` for
   non-standard colon-chained trailer values such as `Assisted-by: Tool:model`.
7. **Fixes: format**: hash must be exactly 12 characters; subject must be
   quoted. `scripts/checkpatch.pl` enforces this rule — report its findings
   for `Fixes:` format rather than re-checking manually to avoid divergence
   if the checkpatch threshold changes.  Flag `[MINOR]` if malformed.

### 3e.4 Series-Level Scope Check

When reviewing a multi-patch series:
- Each patch in the series must be independently bisectable (the tree must
  build and boot after applying each patch individually).
  **Build bisectability is mechanically verified**: read `<project_path>/tmp/patch_<N>_build.txt`
  for each patch N and confirm the build was clean (no `error:` or `warning:`
  lines in files the series touches) at that intermediate tree state.  Flag
  `[CONCERN]` if any intermediate build is broken.
  **Boot bisectability cannot be mechanically verified**: flag `[CONCERN]`
  only when an intermediate patch makes the tree *actively harmful or
  crash-prone* on boot — for example, a DTS node with `status = "okay"`
  added before the kernel driver that handles its `compatible` string exists
  in the series (the kernel probes the device and may panic or deadlock
  depending on the driver model).  Do not flag patches that are merely
  functionally incomplete at an intermediate state (e.g. a register write
  that becomes meaningful only after a later patch adds the surrounding
  enable sequence) — incomplete functionality is acceptable in a series so
  long as the tree does not actively crash.
- Patches that are tightly coupled (e.g. binding + driver) are acceptable
  in the same series but must be in dependency order (binding first).
- A series must not bundle unrelated changes just for convenience — each
  logical group of changes should be a separate series.
- If the series mixes `Fixes:` patches with feature/refactor patches, first
  determine whether the fix depends on all surrounding patches or only a strict
  subset.  Flag `[MINOR]` when an independently backportable fix is bundled with
  feature work; request a separate minimal fix series containing only required
  prerequisites.  Do not flag when the entire series is one inseparable fix unit
  or the cover letter explains the dependency.
