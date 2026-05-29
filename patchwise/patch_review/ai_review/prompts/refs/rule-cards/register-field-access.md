# Rule: register-field-access

## Trigger

C code constructs or extracts register fields with `FIELD_PREP`/`FIELD_GET`/
`GENMASK`/`BIT`, performs read-modify-write via `regmap_update_bits` or
`readl`+`writel`, or stores register values into typed variables.

## Must Check

- Does the storage type match the register width and signedness (e.g. `u32`/`u64`, not a signed or too-narrow type)?
- Do the `FIELD_PREP`/`FIELD_GET` mask and the value's bit range agree with the documented field position?
- Are packed fields combined with proper shift/`FIELD_PREP`, not OR-ed at bit 0?
- Does a read-modify-write preserve reserved/adjacent bits and use the correct mask/offset, rather than clobbering neighbours?
- Is `GENMASK(n-1,0)`/`BIT(n)` guarded against an out-of-range or zero `n`?

## Evidence Needed

- The field macro/mask, the register width, and the documented bit layout.
- The RMW read mask and write value.

## Mandatory Attestation Record

For every `FIELD_PREP`/`FIELD_GET`/`GENMASK`/`BIT`/RMW site in the diff,
include in Code Logic Maps:

```
register_field_audit:
  site: <function:line — the macro/RMW call>
  register_width: <u32|u64 — storage type>
  mask_range: <GENMASK(hi,lo) or BIT(n) — field position>
  value_source: <constant|variable — what's being prepped/extracted>
  rmw_preserves_neighbours: <YES|NO|N/A — for update_bits, is mask correct?>
  genmask_zero_guard: <N/A|GUARDED(quote check)|UNGUARDED — if n from DT/variable>
```

Omitting this record when register field macros appear in the diff is a
review gap.

## Safe Dismissal

Dismiss when source/datasheet shows matching width, mask, and field position and
the RMW preserves reserved bits.

## Finding Template

```text
[BUG] Register field width/mask/RMW mismatch
File: <path>:<line>
Rule: register-field-access
Evidence: <field macro/mask + register width or RMW site>
Reasoning: <width/sign mismatch, wrong mask, or clobbered adjacent bits>
Impact: <wrong value written/read, corrupted neighbouring field, hardware misconfig>
Suggestion: <match storage width, fix mask/shift, preserve reserved bits in RMW>
```

## Severity

`[BUG]` for a proven wrong-field write/read or clobbered bits; `[CONCERN]` when
the documented field layout is not confirmed.
