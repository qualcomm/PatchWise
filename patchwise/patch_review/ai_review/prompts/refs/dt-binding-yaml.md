### 3d.1 DT-Binding Schema (`.yaml`) Rules

**File and top-level contract**
- Path/name: place the schema under
  `Documentation/devicetree/bindings/<subsystem>/`; name it after the primary
  compatible, `<vendor>,<device>.yaml`; keep one unrelated device family per
  file and share common logic through `allOf: [$ref: ...]`.
- Required fields: `$id` must be
  `http://devicetree.org/schemas/<subsystem>/<vendor>,<device>.yaml#` and match
  the file path; `$schema` must be
  `http://devicetree.org/meta-schemas/core.yaml#`; include one-line `title`,
  valid `maintainers` entries in `Name <email>` form, `description` of the
  hardware/binding scope, `properties`, and minimum mandatory `required` list.
- Property closure: use `additionalProperties: false`, or
  `unevaluatedProperties: false` when `allOf`/`$ref` is used so referenced
  properties are evaluated instead of rejected or silently accepted.

**`compatible` contract**
- Use `"<vendor>,<device>"` with a prefix from
  `Documentation/devicetree/bindings/vendor-prefixes.yaml`.
- New hardware uses the most-specific compatible first and the generic fallback
  last; never use a generic-only string when a vendor-specific string exists.
- Binding, parent/wrapper schemas, in-tree DTS/DTSI, examples, and driver match
  tables must agree on the full compatible shape. A bare `const:` is wrong when
  valid users need `[specific, fallback]`.
- Cross-schema tuple consistency is mandatory: if both a common child schema and
  a parent/wrapper `patternProperties` schema constrain the same child node,
  verify that the same compatible tuple length and fallback order can satisfy
  every schema. A new child compatible accepted as `[soc, fallback]` in one file
  but `[variant, soc, fallback]` in another is reportable even if each YAML file
  is locally valid.
- Fallback compatibles must mean real backward compatibility. Do not add a
  fallback to older/generic hardware if the new compatible needs additional
  clocks, resets, register-access enablement, power domains, quirks, or driver
  data that the fallback driver does not provide; prefer a standalone compatible
  until the fallback path is proven safe on old kernels.
- Mandatory fallback proof for every added/changed `compatible:`: open the
  parent/wrapper schema and sibling device bindings/DTS; state in `DT /
  DT-Binding Notes` whether they use `oneOf`/`items` fallback arrays or a single
  `const:`. If no parent wrapper exists, state that explicitly.
- A child schema using only a fallback `const:` while a parent/wrapper accepts
  `items: [variant, base]` rejects valid DTS; file `[BUG]` unless the same
  series narrows/removes the parent contract. Dismissing fallback need requires
  the concrete parent/wrapper YAML path, not just the patch's own binding file;
  silence on that path is a validator violation.
- Existing-device revisions must keep old compatibles accepted and handled
  unless the same series removes every in-tree user.
- Conditions for array-valued compatibles must match membership, not array
  equality: use `contains: { const: ... }` or `contains: { enum: [...] }` inside
  `if:` when fallback-compatible arrays are possible.

**Old-DTB compatibility audit (required when a binding makes resources newly required).**

Fires whenever a binding diff adds a property to `required:`, adds a new
`required:` clock/reset/regulator name, narrows a property's enum/const
to a stricter set, removes an `oneOf` branch, or adds a per-compatible
`if/then` block that promotes an optional resource to required. The
audit asks: **does an in-tree DTB written before this kernel still
parse/probe successfully under the new kernel, or has the patch broken
existing users?**

**Decisive evidence (all three required for any finding or dismissal):**
(1) the diff line(s) that introduce the new requirement (quote the
`required:`/`enum:`/`const:`/`if/then` block being added or tightened);
(2) the set of in-tree DTS users of the affected compatible — name
each `.dts`/`.dtsi` file or state "no in-tree users" with proof
(`grep -rn '"<compatible>"' arch/*/boot/dts/`); (3) for each in-tree
user, whether it already provides the newly-required resource or
whether the patch has updated it in the same series.

**Valid dismissal proofs (cite source for each):**
- the same series updates every in-tree user to provide the resource
  (quote each updated `.dts`/`.dtsi` line and confirm the series order
  applies binding *after* DTS — otherwise reverse-bisect breaks);
- the affected compatible has zero in-tree users (run and quote the
  `grep` showing no matches under `arch/*/boot/dts/` and
  `Documentation/devicetree/bindings/*/examples`);
- the new requirement is gated by a per-compatible `if/then` that
  excludes the older compatibles (quote the `if/then` block and
  enumerate which compatibles it applies to);
- the resource is also marked `optional` via `oneOf`/`anyOf` so old
  DTBs without it still validate (quote the schema branch).

**Disqualified dismissals — file the finding instead if any of these
is the only argument:**
- "the driver handles it as optional at runtime" — DT-binding validity
  is independent of driver behaviour; an old DTB that fails
  `dt_binding_check` against the new schema is broken regardless of
  driver tolerance. Quote the schema's `oneOf`/`anyOf` branch or file
  the finding;
- "no in-tree users" without quoting the `grep` that proves it — the
  reviewer must show the search; bare claim is insufficient;
- "this is a new compatible" without naming the patch hunk that adds
  the compatible — verify the diff actually adds a new `enum:`/`const:`
  entry rather than tightening an existing one;
- "old DTBs are out of scope" — the kernel's stable DT ABI applies
  unless the binding is explicitly experimental or the same series
  removes the compatible entirely;
- "matches sibling binding" without naming the sibling and quoting
  its handling of the same backward-compat question;
- "documented in commit message" — commit-message claims do not
  satisfy the audit; the schema/DTS evidence does.

**Required record format.** A discharge or finding must include, under
`DT / DT-Binding Notes`:
- the diff line(s) that introduced the new requirement;
- the in-tree-user search result (`grep` output or "none found");
- for each in-tree user, a one-line note on whether it still validates
  or has been updated in the same series.

A binding change that makes a resource required without one of these
artefacts is `[BUG]` (DT ABI break) when in-tree users exist and lack
the resource; `[CONCERN]` when in-tree users are absent but
out-of-tree-DTB risk is real (e.g. shipping platforms, Android trees);
`[NIT]` only for purely cosmetic tightening (e.g. `description:` text)
that cannot affect parse/probe.

**Properties and common schemas**
- Every property needs a `description` with meaning and units.
- Use standard schema types (`uint32`, `uint64`, `string`, `phandle`,
  `phandle-array`, `bool`, etc.). Numeric bounded values need
  `minimum`/`maximum` or `enum`; arrays need `minItems`/`maxItems`.
- Reference common schemas for `reg`, `interrupts`, `clocks`, `resets`,
  `power-domains`, `iommus`, `dmas`, `pinctrl-*`, `#address-cells`,
  `#size-cells`, and similar standard properties; do not redefine or duplicate
  accepted common properties.
- Mark deprecated properties with `deprecated: true`.
- Do not add DT properties used only as internal firmware/instance IDs; prefer
  `compatible`, `reg`, topology, or accepted common properties.
- Pair `pinctrl-0` with `pinctrl-names` when pin muxing is demonstrated or
  required.
- Provider cell-count properties such as `#interconnect-cells`, `#clock-cells`,
  `#reset-cells`, `#power-domain-cells`, and `#phy-cells` must be explicitly
  defined with `const:` for the compatible when the provider contract is fixed.
  Do not rely on a permissive common schema that allows multiple cell counts.

**Degenerate-default validation for optional numeric properties.**

When a binding defines an optional numeric property that the driver uses as a
divisor, multiplier, bit-count, lane-count, rate-numerator, or any arithmetic
operand, verify that **absence of the property produces a value the driver
validates before use** — not a degenerate value (0, `UINT_MAX`, -1) that
silently breaks hardware programming.

**Bad-pattern shape:**

    /* DT binding: property is optional, no default documented */
    qcom,foo-bits-per-lane:
      $ref: /schemas/types.yaml#/definitions/uint32
      description: Number of data bits per lane.

    /* Driver: reads with of_property_read_u32(); on absence, val stays 0 */
    of_property_read_u32(np, "qcom,foo-bits-per-lane", &cfg->bits_per_lane);
    /* ... later ... */
    bitclock = data_rate / cfg->bits_per_lane;  /* division by zero */

**Decisive evidence (all three required):**
(1) the binding property definition (quote — is it in `required:` or optional?
what are its `minimum`/`maximum` or `enum` constraints?);
(2) the driver's read site and what happens on absence (does it use
`of_property_read_u32` with no error check? does it have a default assignment?);
(3) the consumer arithmetic/hardware-programming site (quote the line where the
value is used — division, shift, register write, rate calculation).

**Valid dismissal proofs:**
- the property is in `required:` and `dt_binding_check` enforces presence (quote
  the `required:` list — if absent DTS fails schema validation before reaching
  the driver);
- the driver assigns a sane default when the property is absent (quote the
  default-assignment line: `if (ret) cfg->bits_per_lane = 16;`). Note: `= 0`
  is NOT a sane default if the field is used as a divisor, shift count, loop
  bound, or `GENMASK`/`BIT` operand — zero in those contexts produces
  undefined behaviour, infinite loops, or hardware misconfiguration. A
  `dev_warn()` before `= 0` does not make it safe; quote the downstream
  consumer to prove 0 is a valid operational value, or file the finding;
- the driver validates the value before use and returns an error for degenerate
  values (quote the check: `if (!cfg->bits_per_lane) return -EINVAL;`);
- the binding constrains `minimum: 1` so zero is schema-invalid (quote the
  constraint).

**Disqualified dismissals:**
- "the property is optional" — optionality is the problem, not the dismissal;
  the question is what the driver does when it's absent;
- "the hardware requires it, so DTS authors will always provide it" — DTS
  validation is not enforcement; a DTS without the property passes if it's
  optional in the schema;
- "zero is handled elsewhere" without quoting the check site;
- "same as existing driver" without quoting the existing driver's default
  assignment or validation.

Severity: `[BUG]` when absence → 0 → division by zero, infinite loop, or
hardware register programmed with value that locks the bus/PLL; `[CONCERN]`
when absence → 0 → degraded but non-crashing behaviour (rate=0 → hardware
idle, no data transfer).

**Resources, names, and ABI matrix**
- Resource counts for `reg`, `interrupts`, `clocks`, `resets`, `dmas`,
  `power-domains`, `iommus`, interconnects, etc. must match schema
  `minItems`/`maxItems`, hardware, providers, and driver expectations.
- If a resource array has multiple entries or the driver selects by name,
  require/document the matching `*-names` property (`reg-names`,
  `interrupt-names`, `clock-names`, `reset-names`, `dma-names`, etc.).
- If either side of a resource/name pair is unusable alone, enforce the pair
  with `dependencies:` or equivalent `if`/`then`. Ask whether a DTS can legally
  provide only one side and make the driver silently fall back, pick the wrong
  resource, or fail later.
- Named DMA is mandatory source-aware review: if the driver uses
  `dma_request_chan(dev, "tx")`/`"rx"`, a binding or example with `dmas` but no
  `dma-names` is reportable. If the schema defines both `dmas:` and
  `dma-names:` and an `examples:` block has `dmas = <...>`, explicitly state
  whether the example has `dma-names = ...`; missing example names are at least
  `[MINOR]`, and silence is a validator violation.

**Companion-property dependency audit (required when a binding diff defines paired properties).**

Fires whenever a binding diff adds a property together with a companion
naming/selector property (e.g. `clocks` + `clock-names`, `dmas` +
`dma-names`, `interrupts` + `interrupt-names`, `regs` + `reg-names`,
`resets` + `reset-names`, `power-domains` + `power-domain-names`,
`interconnects` + `interconnect-names`, or any other pair where one
side selects/names entries on the other) and the binding's `examples:`
block exercises the primary property. The audit asks: **if a DTS
provides one side without the other, will it pass `dt_binding_check`
and reach the driver — and what does the driver do with a mismatched
or partial pair?**

**Decisive evidence (all three required for any finding or dismissal):**
(1) the property pair name (e.g. `clocks`/`clock-names`) and the diff
line(s) that define both; (2) the schema enforcement — quote the
`dependencies:` block, `if/then` clause, or sibling `required:` line
that ties the two together (or state explicitly "no schema
enforcement"); (3) the driver's selector behaviour for partial pairs
— quote the driver lookup site
(`devm_clk_get_optional(dev, "name")`, `dma_request_chan(dev,
"name")`, `platform_get_resource_byname()`, etc.) and what it does
when the name is absent (fallback, NULL return, EPROBE_DEFER, silent
zero).

**Valid dismissal proofs (cite source for each):**
- the schema enforces the pair via `dependencies:` (quote the block);
- the schema enforces the pair via `if: { required: [name] } then: {
  required: [resource] }` (quote the conditional);
- the example exercises only one side AND the schema makes the other
  side `required:` unconditionally (quote the `required:` list);
- the companion is meaningful even when absent because the driver has
  a documented positional fallback (quote both the driver lookup and
  the comment/doc that authorizes positional use — bare positional
  access in a multi-entry context is rarely safe);
- a generic parent schema (e.g. `simple-bus.yaml`) imposes the
  dependency for the whole class (quote the parent path and the
  enforcing line).

**Disqualified dismissals — file the finding instead if any of these
is the only argument:**
- "the example shows both" — having both in the example does not
  enforce the pair for downstream DTS; quote the schema mechanism
  that prevents asymmetric DTS, not the example;
- "the driver requires it at runtime" — runtime requirement does
  not satisfy `dt_binding_check`; an in-tree DTS without the
  companion can still ship, fail to probe, and leave users debugging
  silently;
- "matches existing bindings in this directory" without naming the
  sibling binding and quoting its `dependencies:`/`if-then` block;
- "the names are optional" without quoting where the schema marks
  the companion `dependencies:`-free or where the driver tolerates
  absence with a documented fallback;
- "single-entry case has no ordering" — even single-entry resources
  benefit from named selectors when the binding may grow (any future
  variant adding a second entry breaks every existing DTS that uses
  positional access);
- "documented in commit message" — commit-message claims do not
  satisfy the audit; the schema mechanism does.

**Required record format.** A discharge or finding must include, under
`DT / DT-Binding Notes`:
- the property pair (e.g. `clocks`/`clock-names`);
- the schema enforcement quote (or "none — pair is unenforced");
- the driver lookup site and partial-pair behaviour;
- a one-line verdict on whether asymmetric DTS is reachable.

A binding that defines paired properties without schema enforcement
and without an audited driver fallback is `[CONCERN]` (latent DTS
ambiguity); `[BUG]` when the driver's partial-pair behaviour can
silently mis-select a resource (wrong clock enabled, wrong DMA
channel claimed); `[NIT]` only when the audit confirms enforcement
and the reviewer is documenting the audit trail.

### Completeness checks

- Per-compatible resource differences must be encoded in schema with
  `allOf`/`if`/`then`: when a new compatible changes counts or mandatory
  resources, the `then:` block must set the right `minItems` and `required:`.
- Adding a compatible to a top-level enum is incomplete if existing `allOf`
  conditionals enforce variant-specific clocks, resets, power domains,
  interrupts, `assigned-clocks`, supplies, or names for sibling compatibles.
  Add the new compatible to the matching conditional or explicitly prove the
  generic constraints are sufficient. Check conditionals using `contains`/`enum`
  as well as direct `const:` matches, because fallback-compatible arrays can miss
  a condition that only looks at the first string.
- Binding/provider ABI matrix is mandatory when arrays or IDs grow or reorder:
  compare schema `items`/counts, `include/dt-bindings/...` IDs and order,
  provider arrays (`clks[]`, `resets[]`, `num_*`, etc.), parent maps/local enums
  or mux parent tables, and driver name-based lookups. Name each inspected
  non-local file/table in `DT / DT-Binding Notes`; use existing
  `codebase audit: callees ...` / `codebase audit: siblings ...` proof when a
  compared surface is in C. Any count/order/meaning mismatch is reportable even
  if `dt_binding_check` passes.
- **`$ref` property-propagation audit:** when a binding uses
  `allOf: - $ref: <common-schema>.yaml#` (e.g. `qcom,gcc.yaml#`), the common
  schema's `required:` list and property definitions apply to ALL compatibles in
  the binding. Verify that every compatible in the `enum:` actually provides the
  capabilities implied by the referenced schema (e.g. `#reset-cells` implies a
  reset provider, `#power-domain-cells` implies a power-domain provider). If a
  compatible does not provide the capability (no resets registered, no GDSCs),
  either gate the `$ref` with an `if/then` conditional that excludes that
  compatible, move the non-conforming compatible to a separate binding file, or
  override the property with `const: 0` for that compatible. A binding that
  forces a DTS node to advertise provider capabilities the driver does not
  implement is `[CONCERN]` — it creates a false ABI contract that misleads
  integrators and can cause silent runtime failures when consumers reference the
  non-existent provider.

**Old-DTB / new-kernel compatibility**
- When a binding revision or new compatible makes supplies, clocks, resets,
  GPIOs, interrupts, DMA, interconnects, power domains, or similar resources
  newly required, inspect the driver probe/helper path that acquires them.
- File at least `[CONCERN]` if an old DTB that previously booted would fail to
  probe with the new kernel and the series does not prove a safe compatibility
  path.
- Required proof in `DT / DT-Binding Notes`: name the old-DTB-visible resource,
  the exact acquisition call/helper, and the optional/fallback/legacy path that
  keeps old DTBs bootable; dismiss only when source proves old DTB shapes still
  work or all users are updated with a compatibility path.

**Examples and validation**
- Every schema needs at least one `examples:` block; the example must be minimal,
  complete, and pass `dt_binding_check`.
- Define placeholder phandles used in examples; do not reference non-existent
  phandles.
- Examples must include companion `*-names` and dependencies for every resource
  they demonstrate; compare named resource arrays (`dmas`, `clocks`, `resets`,
  `reg`, etc.) against schema dependencies and driver lookup APIs before
  clearing the example.
- Validate interrupt specifier cell counts against the interrupt-parent binding;
  ARM GIC examples use exactly three cells after the phandle (`type`, number,
  flags), so a fourth trailing cell is a schema/example bug.
- Read `patch_<N>_dtbinding.txt` (`DT-binding file:`) and report all errors and
  warnings. If absent, note `N/A` in `DT / DT-Binding Notes`.
- Tool `SKIP`, `ERROR`, or environment failure is not a pass. Manually apply all
  schema rules above, especially compatible fallback, resource/name dependency,
  ABI matrix, old-DTB compatibility, and example-completeness checks; state that
  the verdict is from manual schema review, not tool output.
- Mandatory example attestation when `examples:` appears in the diff: for every
  resource property the schema defines (`dmas`, `clocks`, `resets`,
  `power-domains`, `interrupts`, etc.), answer whether the example includes it
  and, if yes, whether required `*-names` companions are present. Do not write
  “example is correct/valid” without this resource-by-resource answer.
- Do NOT run `make dt_binding_check` or `make dtbs_check` directly; use the
  orchestrator-produced DT-binding artifact.
