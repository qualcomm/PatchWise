# Rule: dt-dts-resource-shape

## Trigger

Use this card when a `.dts`/`.dtsi` patch changes `compatible`, `reg`,
`interrupts`, `clocks`, `resets`, `gpios`, `pinctrl-*`, `*-supply`, provider
phandles, or `status`.

## Must Check

- Do compatible strings exist in bindings and follow most-specific-to-fallback
  order?
- Does `reg` match unit-address, parent address/size cells, and the consumer
  mapping path's expected size?
- Do interrupts, GPIOs, clocks, resets, and provider phandle arguments match
  their provider cell counts and binding names?
- Are shared DTSI peripherals left disabled unless every board has the device?
- Are physical supplies and pinctrl states wired for enabled board functions?

## Evidence Needed

- DTS node hunk and nearest parent bus/provider context.
- Relevant binding property definitions.
- Driver consumer path for mapped `reg` or named resources when available.
- Provider binding for phandle cell counts.

## Safe Dismissal

Dismiss only when DTS resource shape matches binding/provider/driver contracts
and enabled devices have required supplies/pinctrl/resources.

## Finding Template

```text
[BUG] DTS resource shape does not match binding or consumer
File: <dts-path>:<node-or-property>
Rule: dt-dts-resource-shape
Evidence: <changed DTS resource and binding/provider/driver expectation>
Reasoning: <why the node encodes the wrong address, cells, resource, or status>
Impact: <probe failure, wrong MMIO/IRQ/provider argument, or unpowered device>
Suggestion: <fix DTS property, provider cells, status, supply, or pinctrl wiring>
```

## Severity

Use `[BUG]` for wrong address/IRQ/provider cells, enabled unusable hardware, or
missing physical supply. Use `[MINOR]` for ordering/formatting-only resource
shape issues.
