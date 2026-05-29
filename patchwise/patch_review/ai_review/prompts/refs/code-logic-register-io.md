<!-- Conditional fragment of code-logic.md — the diff shows register-IO patterns in the diff (readl/writel/ioread/iowrite/regmap_*).
Apply on top of refs/code-logic.md §3c.2 Data-Flow Picture base prose. -->

#### Register read data-flow checklist

Apply to direct MMIO (`readl*`, `readq`, `writel*`, `ioread32`, `iowrite32`,
etc.) and `regmap_*` access.
- Width/sign: use types wide enough for the register (`u32`/`u64`). Signed
  storage is `[NIT]` unless the value reaches signed arithmetic/comparison or is
  widened with sign-extension; then file `[BUG]`.
- Field extraction: verify `FIELD_GET()` or shift/mask covers the documented bit
  range. `BMVAL()` is Qualcomm-internal and absent upstream; flag upstream use
  as `[CONCERN]`.
- Packed field construction: when building register/protocol/header words, prove
  every constant and dynamic value is shifted or `FIELD_PREP()`ed into the
  declared field offset before OR-ing. A raw enum/constant/value OR-ed into the
  final word, or shifted into a neighboring field, is `[BUG]` when the wrong
  bits reach hardware/firmware; dismiss only with the field definition and final
  encoded word proof. This covers `packed_field_constant_shift` and
  `packed_field_dynamic_shift` calibration classes.
- Read-modify-write: read/write offsets must match and reserved bits must be
  preserved; wrong complement masks or shifts corrupt adjacent fields.
- Endianness/barriers: confirm `readl_relaxed`/`writel_relaxed` match bus
  endianness and ordering needs; use `readl` when ordering is required. Raw or
  bulk regmap reads returning LE protocol words require `__leXX` temporaries and
  `leXX_to_cpu()` before status decoding, bitfields, or API outputs.
- **Macro arithmetic on unvalidated input:** `GENMASK(count - 1, 0)`,
  `BIT(count - 1)`, array indexing `arr[count - 1]`, or any expression where
  a subtraction/shift depends on a count that originates from DT parsing,
  variant data, firmware response, or user input requires proof that the count
  cannot be zero (or the degenerate value that makes the expression undefined).

  `GENMASK(-1, 0)` is undefined (wraps to `GENMASK(UINT_MAX, 0)` on some
  architectures, produces a full-register mask, or triggers UBSAN). Division
  by zero, negative shift, or out-of-bounds index are equally fatal.

  **Decisive evidence (all three required):**
  (1) the macro/expression site that subtracts from the count (quote it);
  (2) the source of the count value — DT property read, variant struct field,
  firmware message, or user ioctl (trace back to the assignment);
  (3) the validation site that rejects zero/degenerate before reaching the
  expression (quote it, or state "none found").

  **Valid dismissal proofs:**
  - the count is validated > 0 before use (quote the check);
  - the variant data is compile-time constant and non-zero in every variant
    struct (quote all variant definitions and confirm no zero);
  - the DT schema constrains `minimum: 1` for the source property (quote it);
  - the macro is guarded by `if (count)` or the expression is inside a loop
    that doesn't execute when count is 0 (quote the loop bounds).

  **Disqualified dismissals:**
  - "the hardware always has at least one" without quoting the DT schema
    constraint or variant struct;
  - "the loop won't execute" when the `GENMASK` / `BIT` is OUTSIDE the loop;
  - "same as existing driver" without quoting the existing driver's validation.

  Severity: `[BUG]` when zero is reachable and produces undefined behaviour
  (`GENMASK(-1, 0)`, division by zero, negative shift); `[CONCERN]` when
  zero is unlikely but not provably excluded.
