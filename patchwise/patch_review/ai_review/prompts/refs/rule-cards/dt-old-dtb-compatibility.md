# Rule: dt-old-dtb-compatibility

## Trigger

Binding patch adds a compatible or makes a property/resource/count/enum/const
newly required or stricter.

## Must Check

- Would an old DTB that matched before still validate and probe with the new kernel?
- Which new compatible/property/resource creates the old-DTB risk?
- Does the driver keep a safe optional/default/legacy path for missing old-DTB data?
- Are in-tree DTS users updated, and is any intentional break documented?

## Evidence Needed

- Binding hunk for the new requirement or constraint.
- Driver probe/getter/match-data path that consumes it.
- Existing DTS or old compatible shape before the patch.
- Fallback/default path, same-series DTS update, or explicit breakage note.

## Mandatory Attestation Record

For every binding patch that adds/tightens a requirement, include in
DT / DT-Binding Notes:

```
old_dtb_audit:
  new_requirement: <property/resource added to required or enum narrowed>
  in_tree_users: <grep result — list .dts/.dtsi files using affected compatible, or "none">
  each_user_status: [<file: already has property | updated in this series | MISSING>]
  driver_fallback: <optional path exists | hard -ENODEV on absence | N/A>
  verdict: <safe — all users updated | CONCERN — old DTBs break | N/A — no users>
```

Omitting this record when a binding adds to `required:` or narrows constraints
is a review gap.

## Safe Dismissal

Dismiss only with source proof that old DTB shapes still work, all relevant users
are updated safely, or a documented ABI break is intentional.

## Finding Template

```text
[CONCERN] New DT requirement may break old DTBs
File: <path>:<line-or-property>
Rule: dt-old-dtb-compatibility
Evidence: <new requirement and old-DTB/probe path>
Reasoning: <why old DTB lacks data now required>
Impact: <probe failure or behavior change>
Suggestion: <make optional/fallback, keep legacy path, or document break>
```

## Severity

`[BUG]` for confirmed old-DTB breakage; `[CONCERN]` for credible risk; `[MINOR]`
only for missing docs after source proves behavior safe.
