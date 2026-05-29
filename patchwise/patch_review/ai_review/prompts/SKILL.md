---
name: review-commits
description: |-
  Linux kernel review for local commits/ranges, lore.kernel.org b4 series,
  and single source files. Produces
  HTML reports with [BUG]/[CONCERN]/[MINOR]/[NIT] findings and READY TO APPLY,
  NEEDS FIXES, or NEEDS DISCUSSION verdicts. Uses checkpatch --strict, W=1
  builds, dt_binding_check/dtbs_check, sparse, get_maintainer, logic maps,
  DT/binding/DTS/of_match checks, commit-message/scope checks, hardware
  PM/IRQ/DMA/lifecycle/topology checks, and severity gates.
---

# Review Commits

Automated Linux kernel review for commits, patch series, or source files.
Detailed review logic lives in `refs/` and
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

**Conflict resolution**: if the user provides inputs that match more than one mode
(e.g. both a number of commits and a file path), ask the user to clarify before
proceeding.

**Default commit count for Mode A**: if the user specifies Mode A but omits
the number of commits, ask: "How many commits should I review? (e.g. 1, 5,
10)"  Do not default silently.

If none of the above is clear, ask the user before proceeding.

## Workflow

**MANDATORY startup path**: read `refs/startup-workflow.md` before taking any
tool action.  Do NOT load `refs/orchestrator-workflow.md` during startup unless
`refs/startup-workflow.md` explicitly tells you to.  The startup workflow is
the fast path for repo sync, patch/commit acquisition, `tmp/` creation, test
artifact generation, review-packet generation, and summary-table preparation.

**Mode C exception**: for a single-file review (Mode C), read
`refs/mode-c-workflow.md` instead of `refs/startup-workflow.md` — it owns the
Mode C Steps 0–3 (single-file read, tool runs, rules brief, test summary) and
hands off to `refs/orchestrator-workflow.md` the same way the A/B startup path
does.

**MANDATORY full workflow handoff**: once startup artifacts are ready and you
are about to spawn per-patch subagents, enter sequential main-agent fallback,
assemble HTML, or write the final report, read and follow
`refs/orchestrator-workflow.md`.  It remains the source of truth for subagent
prompt format, validation gates, HTML assembly, and cleanup.

Load other refs only when the startup or full workflow says to assemble/apply
them. Detailed rule prose arrives through the selected `refs/rule-cards/*`
bundled into each per-patch review packet, not through broad default refs; the
remaining orchestrator-side refs (`html-template.md`, `mode-c-workflow.md`) are
loaded only when the workflow directs it.

## Notes

- Never guess or fabricate file contents — read them from the repository.
- If a referenced file does not exist in the repo, say so.
- If `b4` or `git am` fails, report the exact error and stop.
- Prioritise bugs and safety over style.
- Always include file path and approximate line number when referencing code.
- Print the saved review file path as the last line of output.

The orchestrator uses `scripts/assemble_review_packet.py` to generate each
per-patch review packet, bundling the selected rule cards and patch evidence
the reviewer needs.
