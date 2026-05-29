# Rule: dt-vmid-value-space

## Trigger

Use this card when a patch changes DT bindings, DTS, or dt-bindings headers for
VMID, destination-domain, memory protection domain, Qualcomm DSP/GPR/APM domain
routing, or secure memory ownership values.

## Must Check

- Does the binding describe the architectural VMID/domain value space rather
  than Linux-local enum values or driver-private array indexes?
- Are `minimum`, `maximum`, `enum`, and examples valid for real hardware and
  firmware ABI expectations?
- If a new property is added, is old-DTB/new-kernel behavior safe or explicitly
  documented?
- Are companion properties, required properties, and conditional schemas present
  when one domain value depends on another property?
- Do DTS examples and driver parsing agree on cell counts, value units, and
  error handling for absent or invalid values?

## Evidence Needed

- YAML binding property definition and constraints.
- DTS or example values.
- Driver parsing path that consumes the property.
- Firmware or SCM call path that interprets the value.
- Existing compatible/property behavior for old DTBs.

## Safe Dismissal

Dismiss only when the values are architectural, schema constraints match the
firmware/driver ABI, examples are valid, and old-DTB behavior is safe or
intentionally documented.

## Finding Template

```text
[BUG] DT VMID/domain binding uses the wrong value space
File: <binding-or-dts-path>:<line-or-property>
Rule: dt-vmid-value-space
Evidence: <changed property constraint/example/parser>
Reasoning: <why schema values do not match hardware/firmware ABI or old-DTB behavior>
Impact: <invalid DT accepted, valid DT rejected, or wrong memory/domain routing>
Suggestion: <fix constraints/examples/parser or document compatibility behavior>
```

## Severity

Use `[BUG]` for confirmed ABI/value-space mismatch or unsafe old-DTB behavior.
Use `[CONCERN]` when the binding introduces domain values but the packet lacks
firmware ABI evidence needed to prove the correct range.
