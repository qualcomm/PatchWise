# Rule: dt-binding-example-completeness

## Trigger

YAML binding changes `examples:`, resource properties, interrupts, phandles, or
provider/consumer relationships.

## Must Check

- Is there a minimal complete `examples:` block?
- Do phandles resolve or use valid placeholders?
- Do demonstrated resources include required `*-names` companions?
- Do interrupt/provider specifier cell counts match the parent binding?
- Would the example pass `dt_binding_check`?

## Evidence Needed

- Example block and changed resource properties.
- Companion/resource/provider-cell requirements.
- Relevant `dt_binding_check` output if supplied.

## Safe Dismissal

Dismiss only when examples are complete, minimal, schema-valid, and consistent
with resource companions and provider cell counts.

## Finding Template

```text
[MINOR] DT binding example is incomplete or inconsistent
File: <binding-path>:examples
Rule: dt-binding-example-completeness
Evidence: <example resource/phandle/interrupt mismatch>
Reasoning: <why example fails validation or documents invalid ABI>
Impact: <misleading docs or dt_binding_check failure>
Suggestion: <fix resources, names, phandles, or cells>
```

## Severity

`[BUG]` when examples make `dt_binding_check` fail; `[MINOR]` for incomplete
examples after schema remains valid.
