---
name: review-commits-subagent
description: |-
  Per-patch reviewer subagent for the review-commits skill.
  Reviews exactly one kernel patch: applies coding-style, code-logic,
  DT/DT-binding, commit-message, hardware-engineering checklists and the
  three-gate severity rule, then emits an HTML commit-block.
---

# Per-Patch Reviewer Subagent — Compatibility Stub

This file is kept only for compatibility with callers that still reference
`SUBAGENT.md`. It is not the source of truth.

The orchestrator writes the complete per-patch rules brief to:

```
<project_path>/tmp/patch_<N>_rules.md
```

If you are a subagent, or the main agent is running the sequential fallback,
read the rules file path given in the prompt as your first action. Do not use
this stub as review guidance.

Current rule sources are assembled by `scripts/assemble_rules.py` from
`skills/review-commits/refs/`: `core.md`, `coding-style.md`, `code-logic.md`,
`commit-message.md`, `gate-rules.md`, `special-cases.md`, conditional
`dt-binding.md` / `dt-driver.md` / `hardware-eng.md`, and only directly
relevant active memory entries. The full page skeleton remains
orchestrator-only in `html-template.md`.
