# Rule: dt-companion-property-dependency

## Trigger

Binding changes paired resource/name properties such as `clocks`/`clock-names`,
`dmas`/`dma-names`, `interrupts`/`interrupt-names`, `reg`/`reg-names`,
`resets`/`reset-names`, or `interconnects`/`interconnect-names` — or introduces
a conditional cell-count specifier (`#*-cells: enum [N, M]`) where one cell
count is meaningful only with a companion array property (e.g.
`#cooling-cells: 3` selecting an index named via `tmd-names`).

## Must Check

- Can schema validation pass with only one side of the pair?
- Does `dependencies:`, `dependentRequired:`, `if`/`then`, or `required:` enforce the pair?
- For conditional cell-count specifiers (e.g. `#cooling-cells: enum [2, 3]`):
  is the larger cell count tied to its companion via `if`/`then` or
  `dependentRequired`? A bare `enum: [2, 3]` lets the index-selecting form
  validate without `tmd-names` (or whatever names array indexes into),
  passing schema while the driver later fails or addresses the wrong device.
- Does the driver use name-based lookup or a proven positional fallback?
- Do examples include companions for every demonstrated named resource?

## Evidence Needed

- Exact property pair and enforcement block, or proof none exists.
- Driver lookup site such as `devm_clk_get(dev, "core")` or `dma_request_chan()`.
- Example DTS fragment using the resource.

## Safe Dismissal

Dismiss only when schema enforces the pair, the companion is required elsewhere,
or positional fallback is documented and safe. Example-only coverage is not enough.

## Finding Template

```text
[CONCERN] DT resource/name pair is not schema-enforced
File: <binding-path>:<property>
Rule: dt-companion-property-dependency
Evidence: <pair, schema enforcement, driver lookup>
Reasoning: <how asymmetric DTS can pass and mislead/fail driver>
Impact: <wrong resource, late probe failure, or ambiguous ABI>
Suggestion: <add dependency/dependentRequired/if-then or safe fallback docs>
```

## Severity

`[BUG]` when partial pairs can select the wrong hardware resource; `[CONCERN]`
for validation/probe ambiguity; `[MINOR]` for example-only gaps.
