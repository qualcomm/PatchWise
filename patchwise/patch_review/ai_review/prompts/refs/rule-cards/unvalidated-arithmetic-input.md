# Rule: unvalidated-arithmetic-input

## Trigger

C code changes arithmetic, masks, shifts, divisions, array indexes, or field
macros using counts/widths/rates parsed from DT, firmware, match data, variant
data, registers, or user-controlled inputs.

## Must Check

- Can the input be zero, negative, too large, or otherwise outside macro/operator bounds?
- Is validation done before `GENMASK(count - 1, 0)`, `BIT(n)`, shift, division, modulo, or array index use?
- Does the binding/descriptor/register spec actually constrain the value, and is that constraint enforced in code?
- Do all alternate probe/variant paths initialize the value before arithmetic consumers run?

## Evidence Needed

- Source of the arithmetic input and its possible range.
- Validation/default path before the arithmetic site.
- Binding/descriptor/register constraint if used as dismissal proof.

## Safe Dismissal

Dismiss only with source-cited validation (`> 0`, upper bound, enum range, array
size check) or a binding/descriptor guarantee that the code actually enforces.

## Finding Template

```text
[BUG] Arithmetic uses an unvalidated zero-capable input
File: <driver-path>:<arithmetic-line>
Rule: unvalidated-arithmetic-input
Evidence: <input source, arithmetic use, and missing/late bounds check>
Reasoning: <why zero/out-of-range reaches mask/shift/division/index>
Impact: <undefined behavior, wrong register mask, divide-by-zero, or OOB access>
Suggestion: <validate range before use and reject/default invalid values>
```

## Severity

Use `[BUG]` for reachable undefined behavior or hardware misprogramming;
`[CONCERN]` when range depends on undocumented firmware/hardware data.
