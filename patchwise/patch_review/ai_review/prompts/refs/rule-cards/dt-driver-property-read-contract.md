# Rule: dt-driver-property-read-contract

## Trigger

Use this card when driver code changes `of_property_read_*`,
`device_property_read_*`, `fwnode_property_read_*`, resource-get-all APIs,
optional resource getters, deprecated OF GPIO/clock/reset/regulator helpers, or
`of_find_*`/`of_get_*` node-reference APIs. Treat `*_bulk_get_all()` and other
"get all available resources" helpers as count-returning parsers, not just
errno-returning getters.

## Must Check

- Are required property read errors checked and optional defaults documented?
- Do `*_get_all()` resource APIs treat zero returned resources as invalid when
  the compatible, match data, commit text, or later callbacks require those
  resources? Required-resource absence must be rejected even if schema validation
  should have caught the bad DT.
- Does optional getter logic understand that absent optional resources can be
  success rather than `-ENOENT`?
- Are non-devm resource handles and OF node references released on all error,
  remove/unbind, suspend, and retry paths?
- Can deprecated OF helper use be replaced by a `devm_*` lifetime-managed API?

## Evidence Needed

- Changed property/resource getter call and return-value handling.
- Binding requirement/default for the property or resource.
- Error/remove/unbind paths for owned handles or node references.
- Later consumer of the parsed value/resource.
- For count-returning helpers, the exact zero-count path from the helper
  implementation or API docs, plus the first later operation that assumes at
  least one resource exists.

## Safe Dismissal

Dismiss only when every required read/resource path validates errors and counts,
optional absence has a documented default, and owned refs are released or devm
managed. A binding `required:` entry is not a safe dismissal for driver-side
zero-count handling; invalid DTs, old DTBs, overlays, and manual test DTs still
need a clear runtime failure instead of a silent no-op.

## Finding Template

```text
[BUG] Driver DT property/resource read contract is unsafe
File: <driver-path>:<getter-call>
Rule: dt-driver-property-read-contract
Evidence: <getter, binding requirement, and missing check/release/default>
Reasoning: <why invalid or absent DT reaches unsafe runtime behavior>
Impact: <probe failure, NULL/zero use, leaked reference, or wrong resource>
Suggestion: <check return/count, add default, use devm API, or release refs>
```

## Severity

Use `[BUG]` for unchecked values that can crash, silently skip mandatory power
or clock programming, access unpowered registers, or program hardware wrongly,
and for leaked references on repeatable bind/unbind. Use `[CONCERN]` for
ambiguous optional/default behavior or required zero-count handling whose later
harm is not yet deterministic.

## Focus Pattern — Mandatory Clocks With `devm_clk_bulk_get_all()`

When a patch sets match data such as `has_clocks`, adds binding `clocks` /
`clock-names`, or says clocks are mandatory, and the driver uses
`devm_clk_bulk_get_all()`:

1. Require `num_clks <= 0` handling, not only `< 0`.
2. If `num_clks == 0` continues to registration or hardware access, file a
   finding even when the binding marks clocks required.
3. If a later enable path calls `clk_bulk_prepare_enable(num_clks, clks)`, note
   that zero clocks makes the enable path a successful no-op.
