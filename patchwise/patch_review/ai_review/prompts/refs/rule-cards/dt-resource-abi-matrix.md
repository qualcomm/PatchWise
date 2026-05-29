# Rule: dt-resource-abi-matrix

## Trigger

Binding/header/driver changes resource arrays, names, counts, provider IDs,
`include/dt-bindings/*` constants, or compatible-specific resource requirements.

## Must Check

- Do schema `minItems`/`maxItems`/`items`, examples, DTS, and driver lookups agree on count/order/name?
- Are per-compatible resource differences encoded for every affected compatible and fallback tuple?
- Do dt-bindings IDs match provider arrays, local enums, mux parents, and named lookups?
- Can schema pass while the driver selects the wrong resource or array element?
- Are hardware interrupt lines modeled with standard `interrupts` /
  `interrupts-extended` and consumed through IRQ APIs, rather than as a custom
  `*-gpios` property plus `gpiod_to_irq()`? Only dismiss a GPIO-modeled
  interrupt when the line is truly used as GPIO state/control in addition to IRQ
  routing and the binding documents that hardware reason.
- Does any vendor property encode raw register addresses, register/value pairs,
  magic init scripts, or firmware-style programming sequences? DT should
  describe board topology/parameters; fixed register tables belong in the
  driver keyed by compatible. If values are board-specific, the binding must
  expose semantic fields with units/ranges instead of opaque register scripts.

## Evidence Needed

- Binding resource definitions/conditionals.
- Changed dt-bindings constants or provider arrays.
- Driver lookup sites and `num_*`/array tables.
- Example/DTS resource users.
- For IRQ-like resources: binding property name, driver lookup (`platform_get_irq`,
  `fwnode_irq_get`, `gpiod_to_irq`, etc.), and whether the line is also used as
  a GPIO control/data signal.
- For init tables: property description, driver consumer, and proof that each
  exposed cell is a semantic board parameter rather than a raw register address
  or value.

## Safe Dismissal

Dismiss only when schema, header IDs, provider tables, examples, and driver
lookup semantics all agree, including variant-specific cases.

## Finding Template

```text
[BUG] DT resource ABI matrix is inconsistent
File: <binding/header/driver-path>:<resource-or-id>
Rule: dt-resource-abi-matrix
Evidence: <schema count/order/name and driver/provider mismatch>
Reasoning: <why valid DT selects wrong resource or fails runtime>
Impact: <wrong clock/reset/DMA/reg/IRQ/provider arg or probe failure>
Suggestion: <align schema, examples, constants, arrays, and lookups>
```

## Severity

`[BUG]` for count/order/meaning mismatches; `[CONCERN]` for incomplete variant
matrix needing more runtime context. Raw register scripts in DT and GPIO-modeled
hardware interrupts are normally `[CONCERN]` unless direct maintainer or binding
policy makes the ABI rejection decisive.
