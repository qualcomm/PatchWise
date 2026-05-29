# Rule: dt-provider-cells-const

## Trigger

Provider binding adds or changes `#*-cells` (`#clock-cells`, `#reset-cells`,
`#power-domain-cells`, `#interrupt-cells`, `#address-cells`, `#size-cells`, etc.).

## Must Check

- Is a fixed provider ABI constrained with `const:`?
- Does driver/provider xlate code expect exactly that count?
- Do examples and consumers use the same count?
- If variable by compatible, are all counts modeled and supported by code?
- **`$ref` propagation:** when the binding uses `allOf: - $ref: <common>.yaml#`
  (e.g. `qcom,gcc.yaml#`), does the common schema force `#reset-cells` or
  `#power-domain-cells` into `required:` for ALL compatibles? If a compatible
  has no resets/power-domains (driver has no `.gdscs`/`.resets`), the binding
  must gate the requirement with `if/then` or move that compatible to a
  separate file. A DTS node forced to advertise provider cells it cannot serve
  is a false ABI contract.

## Evidence Needed

- `#*-cells` property schema.
- Provider registration/xlate or consumer parsing path.
- Example and consumer nodes; per-compatible count conditionals if any.
- When `allOf: $ref` is present: the referenced schema's `required:` list and
  whether each compatible's driver actually registers the implied provider
  (GDSCs, resets, etc.).

## Safe Dismissal

Dismiss only with the correct `const:` or complete compatible-specific constraints
that match driver-supported counts. For `$ref` propagation, dismiss only if every
compatible genuinely provides the implied capability (quote the driver's
registration of GDSCs/resets for each compatible).

## Finding Template

```text
[BUG] Provider cell count is not fixed by the binding
File: <binding-path>:<#*-cells>
Rule: dt-provider-cells-const
Evidence: <schema count and driver/provider expectation>
Reasoning: <why permissive schema accepts consumers code rejects/misparses>
Impact: <invalid DT accepted, probe failure, or wrong provider arguments>
Suggestion: <add const or compatible-specific constraints matching code>

[CONCERN] $ref forces provider capability on non-provider compatible
File: <binding-path>:required
Rule: dt-provider-cells-const
Evidence: <allOf $ref adds #power-domain-cells/reset-cells to required>;
  <compatible X driver has no GDSCs/resets>
Reasoning: schema advertises provider capability the driver cannot serve
Impact: integrators may reference this as a power-domain/reset provider → fail
Suggestion: gate requirement with if/then excluding non-provider compatibles
```

## Severity

Use `[BUG]` for fixed-count ABI without `const:`; `[CONCERN]` for incomplete
variant-specific count modeling or `$ref` propagation forcing false capabilities.
