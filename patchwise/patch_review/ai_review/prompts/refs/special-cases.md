## Special Cases

### Merge commits
If the series contains a merge commit (i.e. `git show HEAD` shows two parent
hashes), write in its Code Logic Maps `<pre>` block:
`"Merge commit — no new code logic to review."`
Skip the detailed review checklists (3b–3f) but still write the commit block
with all mandatory sections present (Issues and Minor/Style may be empty).
The Step Completion Record must still be written with all mandatory steps
showing DONE (the maps note above satisfies step_3c).
Count merge commits in the total-patches number but exclude them from all
finding statistics.

### Revert patches
A `Revert "..."` commit has a well-known format.  Apply a short-circuit
checklist:
1. Confirm the reverted commit hash in the subject matches an actual commit
   in the tree.
2. Confirm the diff is the exact inverse of the reverted commit (no extra
   changes).
3. Confirm the commit body explains why the revert is necessary.
4. Skip control-flow / data-flow / state-machine maps — write "Revert patch;
   full logic maps not required." in the Code Logic Maps `<pre>` block.

### `include/uapi/` changes — ABI stability
Any patch that modifies files under `include/uapi/` introduces a kernel ABI
change visible to user space.  Flag as `[BUG]` (two-part gate does NOT
apply) any change that:
- Removes a struct, enum, or `#define` that user space may depend on.
- Changes the layout (size, field order, alignment) of an existing struct.
- Renames a field or changes its type in a way that alters ABI.
Additions of new fields at the end of a struct, new enum values, or new
`#define` constants are acceptable provided they do not change existing field
offsets.

### New Kconfig symbols
When a patch adds a new `Kconfig` option, verify:
- `help` text is present and explains what the option does.
- `default` is `n` (off) for new optional features unless there is a strong
  reason otherwise.
- `depends on` does not introduce unexpected bloat or circular dependencies.
- `select` is used only for library-like symbols (not drivers that should use
  `depends on`).
- If the new symbol controls a driver module, confirm `tristate` is used (not
  `bool`) unless the module cannot be built as a loadable module.

### Patches touching `kernel-parameters.txt`
If a patch adds a new kernel boot parameter, verify that
`Documentation/admin-guide/kernel-parameters.txt` is updated in the same
patch with a description of the parameter, its type, and its default value.

### `SYSCALL_DEFINE*` patches
If a patch introduces a new system call:
- Confirm a `SYSCALL_DEFINE*` macro is used (not a bare `asmlinkage` function).
- Confirm a `compat_*` variant is provided if the syscall takes pointers or
  `long` arguments that differ between 32-bit and 64-bit ABI.
- Flag as `[CONCERN]` if there is no corresponding `man-pages` notification
  note in the cover letter.

### Very large series (> 20 patches)
For series with more than 20 patches, consider splitting the review across
two invocations to avoid context exhaustion:
- Invocation 1: patches 1 – T/2, produce `review_<slug>_part1_<date>.html`.
- Invocation 2: patches T/2+1 – T, produce `review_<slug>_part2_<date>.html`.
Inform the user of this split before starting and confirm they agree.

### RFC patches (`[RFC PATCH]` prefix)
RFC (Request for Comments) patches signal that the author is seeking design
feedback, not final review.  Adjust the review posture:
- Still apply ALL mandatory steps (no step may be skipped).
- Still run all automated tools (checkpatch, build, sparse, dt_binding_check).
- Still apply the three-gate rule for findings.
- **Difference**: In the verdict banner, use the note: `"RFC series — findings
  are advisory; author is seeking design direction."`
- Do NOT relax severity — a [BUG] in an RFC is still a [BUG].
- Focus additional attention on architectural/design issues.

### Whitespace-only / formatting patches
Patches whose only purpose is reformatting (indentation, whitespace, line
wrapping) without any functional change:
- Still apply ALL mandatory steps — do not skip.
- Step 3c Code Logic Maps: write `"Whitespace-only change; no control-flow,
  data-flow, or behavioral change."` — this satisfies the non-empty requirement.
- Step 3b (coding style): apply in full.
- Findings are typically `[NIT]` unless the formatting change introduces a
  functional difference (e.g., macro continuation backslash misalignment that
  changes preprocessing → `[BUG]`).

### Documentation-only patches
Patches that modify only files under `Documentation/`, `*.rst`, `*.txt`
(documentation), or comment blocks within code:
- Still apply ALL mandatory steps — do not skip.
- Step 3c Code Logic Maps: write `"Documentation-only change; no executable
  code modified."` — satisfies the non-empty requirement.
- Step 3f (hardware engineering): write `N/A` — no hardware interaction.
- Focus on: accuracy of technical claims, correct RST/kernel-doc formatting.

### Stable/backport trailer checks
When a patch has `Fixes:` and/or `Cc: stable@vger.kernel.org` trailers:
- `Cc: stable` without `Fixes:` is NOT automatically an error.  Flag `[MINOR]`
  only when the diff clearly fixes a specific identifiable commit and the commit
  message gives no reason for omitting the `Fixes:` tag.
- `Fixes:` without `Cc: stable` is NOT automatically an error.  Flag `[MINOR]`
  only when the fixed commit is demonstrably in stable-supported history or the
  body explicitly asks for a stable backport but forgot the trailer.
- Do NOT flag either case when the commit message explains the exception (for
  example no single culprit commit, not suitable for stable, or dependency on a
  larger feature series).

### Mixed feature + bugfix series
When a series contains both new features and bug fixes:
- First ask whether the fix and feature are logically dependent, affect the same
  enabling path, or are documented as interdependent in the cover letter.
- If interdependent, accept the mixing; at most file `[MINOR]`:
  `"Consider splitting if the fix can stand alone."`
- If independent and the fix is backportable on its own, flag `[CONCERN] Patch
  Scope`: `"Bug fixes should be sent separately for independent backport."`
- For a `Fixes:` patch that depends on only *some* earlier patches in the series,
  ask which patches are strict prerequisites; request a separate minimal series
  containing only the fix and those prerequisites so stable can backport it
  cleanly.  Do not flag when every other patch is a required prerequisite (the
  series is one inseparable unit).

### Patch ordering / dependency violations
If a later patch uses a symbol only introduced by a later-still patch:
- This is a bisectability violation.
- Flag as `[CONCERN] Patch Scope` on the patch that uses the undefined symbol.
- If `patch_<N>_build.txt` confirms a build error: upgrade to `[BUG]`.

### Interdependent patch build failures
When patch N fails to build because of a defect in patch N-K:
- File the finding on **patch N-K** (the introducing patch).
- Add a cross-reference note on patch N.
- Do NOT file a duplicate [BUG] on patch N for the same root cause.

### Non-upstream-targeted patches
Unless the user explicitly states "skip upstream rules", all upstream
kernel.org rules apply regardless of the target tree.
