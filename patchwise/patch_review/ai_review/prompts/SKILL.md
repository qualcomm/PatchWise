---
name: review-commits
description: |-
  Linux kernel review for local commits/ranges, lore.kernel.org b4 series,
  single source files, and maintainer-feedback memory calibration. Produces
  HTML reports with [BUG]/[CONCERN]/[MINOR]/[NIT] findings and READY TO APPLY,
  NEEDS FIXES, or NEEDS DISCUSSION verdicts. Uses checkpatch --strict, W=1
  builds, dt_binding_check/dtbs_check, sparse, get_maintainer, logic maps,
  DT/binding/DTS/of_match checks, commit-message/scope checks, hardware
  PM/IRQ/DMA/lifecycle/topology checks, and severity gates.
---

# Review Commits

Automated Linux kernel review for commits, patch series, source files, or
post-review feedback calibration. Detailed review logic lives in `refs/` and
is loaded only by the workflow.

Terminology used by refs: a **patch** is one git-am-able unit; Mode A patches
are commits, Mode B patches become commits after `git am`; a **series** is
patches `1..T` where `T` is the total count; `N` is the current 1-based patch index; `slug` is the
filesystem-safe run ID; the **orchestrator** coordinates one-patch
**subagents**, their `tmp/patch_<N>_block.html` block files, and the
`tmp/review_<slug>_progress.txt` sidecar.

## Mode Selection

| Inputs provided | Mode |
|---|---|
| `Project path` + `Number of commits` | **A** — review last `<count>` local commits |
| `Project path` + `Revision range` (e.g. `HEAD~5..HEAD`, `v6.8..mybranch`) | **A** — review commits in the given range |
| `Project path` + `Message-ID` | **B** — fetch, apply, and review a lore.kernel.org patch series |
| `Project path` + `File path` | **C** — review a single source file as-is in the working tree |
| `Saved review file` + maintainer/reviewer comments | **D** — calibrate memory for future reviews |

**Conflict resolution**: if the user provides inputs that match more than one mode
(e.g. both a number of commits and a file path), ask the user to clarify before
proceeding.

**Default commit count for Mode A**: if the user specifies Mode A but omits
the number of commits, ask: "How many commits should I review? (e.g. 1, 5,
10)"  Do not default silently.

If none of the above is clear, ask the user before proceeding.

## Workflow

**MANDATORY**: You MUST read `refs/orchestrator-workflow.md` before taking any
action beyond mode selection.  Do NOT attempt any review steps, tool runs, or
HTML output without first reading and following that file — it contains
validation gates that are not repeated here.

Treat it as the source of truth for repo sync, commit/patch acquisition, tests,
subagents/fallback, gates, HTML assembly, cleanup, and Mode D memory
calibration.

Load other refs only when that workflow says to assemble/apply them:
`core.md`, `coding-style.md`, `code-logic.md`, `dt-binding.md`, `dt-driver.md`,
`commit-message.md`, `hardware-eng.md`, `gate-rules.md`, `html-template.md`,
`special-cases.md`, and optional lazy-loaded `memory/*.md`.

## Mode D — Feedback Calibration

Use Mode D only after maintainer/reviewer comments arrive for a saved review.
It updates curated future-review memory; it does not revise the original
report.

Inputs:
- Saved review file path/text.
- Maintainer/reviewer comments, lore link, message ID, or copied email.
- Optional project path/series context if code cross-checking is needed.

Procedure:
- Read `refs/memory/index.md`, then follow Step 7 in
  `refs/orchestrator-workflow.md`.
- Do not run build, checkpatch, sparse, or normal patch review unless the user
  explicitly asks to re-review the code.

## Notes

- Never guess or fabricate file contents — read them from the repository.
- If a referenced file does not exist in the repo, say so.
- If `b4` or `git am` fails, report the exact error and stop.
- Prioritise bugs and safety over style.
- Always include file path and approximate line number when referencing code.
- Print the saved review file path as the last line of output.

Detailed special-case rules live in `refs/special-cases.md`; the orchestrator
uses `scripts/assemble_rules.py` to generate each per-patch rules brief.
