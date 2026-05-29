# Rule: dt-binding-schema-basics

## Trigger

YAML binding adds or changes top-level schema fields, property closure, or file
path/name: `$id`, `$schema`, `maintainers`, `properties`, `required`,
`additionalProperties`, `unevaluatedProperties`, `allOf`, or `$ref`.

## Must Check

- Does `$id` match `Documentation/devicetree/bindings/<subsystem>/<file>.yaml#`?
- Does `$schema` use the DT core meta-schema?
- Are required top-level fields present and maintainers `Name <email>`?
- Does filename match the primary compatible and avoid unrelated families?
- Is closure correct: `additionalProperties: false` only when the schema is
  self-contained, or `unevaluatedProperties: false` when `$ref`/`allOf` pulls
  in common-schema properties? Treat `$ref`/`allOf` plus
  `additionalProperties: false` as a finding, not as a safe closure.
- When the diff adds an entry to the top-level `required:` list (e.g.
  `- '#power-domain-cells'`, `- '#cooling-cells'`, `- '#clock-cells'`,
  `- 'reg-names'`), AND the binding's `compatible:` is an `enum:` over multiple
  device variants (or the file uses `oneOf`/`if-then` per-compatible carve-outs),
  verify EVERY listed compatible actually exposes the required property.
  A required property that one of the enum'd compatibles does not provide
  (e.g. a BIST clock controller with no power domains being forced to advertise
  `#power-domain-cells`) is an ABI bug — the schema rejects valid DT or forces
  the device to lie about its capabilities.  Either move the requirement
  inside an `if/then` branch keyed on the specific compatibles that need it,
  or split the variant into a separate binding.

## Evidence Needed

- Changed YAML top-level lines, file path, primary compatible, and any `$ref`/`allOf`.
- Closure mode and every referenced common schema that contributes properties
  outside the local `properties:` block.
- For `required:` additions: the full `compatible:` list of the binding, and
  for each compatible, the corresponding dt-bindings header file (or driver
  source) showing whether that compatible exposes the property in question.

## Mandatory Attestation Record

When the diff adds at least one item to the `required:` list, include in
the Code Logic Maps or DT/DT-Binding Notes:

```
required_per_compatible_audit:
  added_required_property: <quoted property name(s) added to required>
  compatibles_in_binding: [<compatible-1>, <compatible-2>, ...]
  per_compatible_capability:
    - compatible: <name>
      header_or_driver: <path to dt-bindings header or driver>
      provides_property: <YES — quote the relevant define/code | NO — flag bug>
  carve_out_present: <YES path=if/then/$ref | NO — flag if any compatible lacks the property>
```

Omitting this record when a `required:` addition is in the diff is a review gap.

## Safe Dismissal

Dismiss only when metadata/path is complete and unknown properties are closed
without rejecting referenced common-schema properties. If a binding references
`dai-common.yaml#`, `graph.yaml#`, `i2c-device.yaml#`, or any other common
schema that can evaluate additional properties, dismissal must name the
`unevaluatedProperties: false` line or explain why the reference contributes no
properties.

## Finding Template

```text
[MINOR] DT binding schema contract is incomplete
File: <binding-path>:<field>
Rule: dt-binding-schema-basics
Evidence: <missing/mismatched schema field or closure rule>
Reasoning: <why schema validation or ABI docs are incomplete>
Impact: <bad metadata or unknown properties accepted/rejected>
Suggestion: <fix id/schema/metadata/path or closure>
```

## Severity

`[CONCERN]` for closure that accepts invalid ABI or rejects valid referenced
properties; `[MINOR]` for metadata/path issues.
