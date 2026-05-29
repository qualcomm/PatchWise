---
name: review-commits-subagent
description: |-
  Compatibility stub for review-commits subagent callers.
  Redirects per-patch reviewers to the generated packet-only review artifact.
---

# Per-Patch Reviewer Subagent — Compatibility Stub

This file is kept only for compatibility with callers that still reference
`SUBAGENT.md`. It is not the source of truth.

The migration target is a compact per-patch reviewer packet:

```
<project_path>/tmp/patch_<N>_review_packet.md
```

Read the reviewer packet first and use only its reviewer base, selected rule
cards, patch evidence, and output contract. Do not load startup, orchestrator,
HTML-template, validator-only, or broad rule refs.

For Mode C single-file reviews, the orchestration writes the complete per-file
rules brief to:

```
<project_path>/tmp/review_<slug>_file_rules.md
```

If no reviewer packet is provided for Mode A/B, stop and report a missing packet
artifact. Do not use this stub as review guidance.

Mode A/B rule sources are selected by `scripts/select_rule_cards.py` and bundled
by `scripts/assemble_review_packet.py`. Single-file rules-brief assembly for
Mode C has been removed; see `refs/mode-c-workflow.md` for the current
single-file path. The full page skeleton remains orchestrator-only
in `html-template.md`.
