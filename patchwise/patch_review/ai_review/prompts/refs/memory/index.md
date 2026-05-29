# Review Memory Index

Use this directory as curated calibration memory for future Linux kernel
reviews. Do not load these files by default during a normal review.

## Lazy-Load Protocol

1. Inspect the changed file paths, commit subjects, and review categories.
2. Load only the smallest matching memory file from the table below.
3. Apply active entries as review heuristics, not as proof.
4. If no row matches, continue without loading memory.

| Topic | Load only when | Normal-review file |
|---|---|---|
| Patch scope | Judging one-patch-one-purpose, stable split, feature/fix mixing, or series organization | `active/patch-scope.md` via `--memory patch-scope` |
| Commit message | Judging subject/body wording, tags, `Fixes:`, `Cc: stable`, or cover-letter conventions | `active/commit-message.md` via `--memory commit-message` |
| DT bindings | Reviewing `Documentation/devicetree/bindings/`, DTS/DTSI, `of_match_table`, or `of_*` API usage | `active/dt-bindings.md` via `--memory dt-bindings` |
| Subsystem-specific | Reviewing maintainer preferences tied to a subsystem, driver family, or mailing list | `active/subsystem-specific.md` via `--memory subsystem-specific` |

## Directory Layout

Memory entries are split by lifecycle state first, then topic:

- `active/*.md`: entries eligible for normal Mode A/B/C rules briefs.
- `draft/*.md`: newly learned or weakly confirmed entries; excluded from normal reviews.
- `deprecated/*.md`: stale, contradicted, or risky entries retained temporarily for audit.
- `manifest.json`: generated index of entry IDs, lifecycle status, topic, path, update date, and content hash.

Use `scripts/assemble_rules.py` for normal reviews; it selects only active
entries by default.  Use `scripts/split_memory.py --check` to preview the
layout and `scripts/split_memory.py --apply` to create or refresh the split
layout and manifest while preserving entry content hashes.

## Lifecycle

Use memory as a post-review learning loop:

1. After maintainer/reviewer comments arrive, compare them against the saved
   review file.
2. Classify each difference as `confirmed`, `missed-by-us`, `false-positive`,
   `maintainer-preference`, or `subsystem-convention`.
3. Add or update only concise reusable patterns. Do not store raw email text.
4. Search existing entries before adding a new one; update duplicates instead.
5. Promote an entry to `active` only when it passes the deterministic gate in
   `scripts/promote_memory.py`: real `Maintainer evidence:` (a maintainer/bot
   name plus a lore link/message-id/date, or a `missed-by-us`/confirmed marker),
   non-empty real `False-positive guards:`, and `Confidence:` of `medium`/`high`
   (or a confirmed marker).  After writing or updating a `draft` entry, run
   `scripts/promote_memory.py --check` to preview candidates and
   `scripts/promote_memory.py --auto` to promote the ones that pass.
6. Demote an `active` entry back to `draft` (recoverable, not deleted) when a
   maintainer provides full evidence that overturns the finding the entry drove:
   add a contradiction note to the entry, then run
   `scripts/promote_memory.py --demote-check` to list flagged entries and
   `scripts/promote_memory.py --demote MEM-####` to move them.  Keep an entry
   `active` (only tightening its `False-positive guards:`) when the maintainer
   merely adds nuance rather than overturning it.
7. Move entries between lifecycle states with
   `scripts/move_memory_entry.py MEM-#### --status <active|draft|deprecated>`;
   this updates the `Status:` field, reruns `memory_lint.py`, and refreshes
   `manifest.json`.
8. Deprecate entries that are repeatedly contradicted, stale, too narrow, or
   causing false positives; reserve removal for entries with no remaining audit
   value.
9. Remove deprecated entries after they are no longer useful for audit.
10. Run `scripts/memory_lint.py` after every memory edit.  If editing manually,
   keep each entry's `Status:` equal to its parent lifecycle directory and run
   `scripts/split_memory.py --apply` afterward to refresh the manifest.

## Status Values

- `draft`: recorded from one data point; do not rely on it unless directly relevant.
- `active`: confirmed by maintainer feedback or repeated evidence; safe to use as a heuristic.
- `deprecated`: do not use for new reviews; retained temporarily for audit.

## Entry Format

```markdown
### MEM-0001: Short imperative or noun title

Status: active
Scope: general | subsystem:<name> | file-pattern:<glob>
Triggers:
- Concrete condition that makes this memory relevant

Maintainer evidence:
- Paraphrased feedback, with lore link/message-id if available

Review action:
- Concrete action to take in future reviews

False-positive guards:
- When not to apply this memory

Confidence: low | medium | high
Last updated: YYYY-MM-DD
```

Keep entries short. If an entry needs more than a few bullets, split it into a
specific rule plus a separate false-positive guard.
