## Step 3d — Device Tree & DT-Binding Review Checklist

Apply this checklist whenever the patch touches a Device Tree **file**:
- `Documentation/devicetree/bindings/**/*.yaml` (binding schema)
- `arch/*/boot/dts/**/*.dts` / `*.dtsi` (device tree source)

Driver C code that only uses `of_match_table`, `of_device_id`, or `of_*` API
call sites (with no DT file change) is reviewed under
`refs/dt-driver.md` (Step 3d.3) instead — do not require this full schema/DTS
checklist for those patches.

Rules are derived from the authoritative upstream references:
`Documentation/devicetree/bindings/writing-schema.rst`,
`Documentation/devicetree/bindings/writing-bindings.rst`, and
`Documentation/process/submitting-patches.rst`.

### 3d.1 DT-Binding Schema (`.yaml`) Rules

**File placement & naming**
- Schema file lives under `Documentation/devicetree/bindings/<subsystem>/`.
- Filename matches the `compatible` string vendor prefix and device name:
  `<vendor>,<device>.yaml`.
- One schema file per binding; do not describe multiple unrelated devices in
  one file.  Use `allOf: [$ref: ...]` to share common properties.

**Required top-level fields**
- `$id`: must be
  `http://devicetree.org/schemas/<subsystem>/<vendor>,<device>.yaml#`
  and match the file path exactly.
- `$schema`: must be
  `http://devicetree.org/meta-schemas/core.yaml#`.
- `title`: one-line human-readable description.
- `maintainers`: at least one valid `Name <email>` entry.
- `description`: explains what the hardware is and what the binding covers.
- `properties`: declares every property the binding uses.
- `required`: lists the minimum set of mandatory properties.
- `additionalProperties: false` (or `unevaluatedProperties: false` when using
  `allOf`) — prevents undeclared properties from silently passing validation.
  **Note**: when `allOf: [$ref: ...]` is used, `additionalProperties: false`
  does not see properties declared inside the referenced schema, causing
  validation failures.  Use `unevaluatedProperties: false` in that case, as it
  evaluates properties across the entire schema including `$ref` targets.

**`compatible` property**
- Must use the form `"<vendor>,<device>"` with a vendor prefix from
  `Documentation/devicetree/bindings/vendor-prefixes.yaml`.
- New hardware must use the most-specific compatible first and any generic
  fallback last; never use a generic-only string when a vendor-specific
  string exists.
- Binding, parent/wrapper schemas, in-tree DTS/DTSI examples, and driver
  match tables must agree on the full compatible **shape**: a bare `const:`
  is wrong if valid users need a multi-string fallback array.  Cross-check
  wrappers and sibling DTS before accepting `const:` for variant hardware.
  If an existing parent/wrapper schema accepts `items: [specific, fallback]`,
  a child/device schema that accepts only the fallback `const:` rejects valid
  DTS and must be reported unless the patch also removes or narrows that parent
  contract in the same series.  This cross-check is mandatory whenever a patch
  adds or changes a `compatible:`: open the parent/wrapper schema (e.g. the QUP
  `*-geni-se-qup.yaml` node pattern that matches this device) and any sibling
  device binding, and state in the review whether they use `oneOf`/`items`
  (a SoC fallback array) for the same node.  A bare `const:` that contradicts a
  parent `oneOf: [const, items: [variant, base]]` is a `[BUG]`-class schema
  mismatch (`dtbs_check` will reject valid variant DTS), not a stylistic note.
  When dismissing the fallback (e.g. "no oneOf is needed", "no announced
  base variant"), the review must cite the concrete parent/wrapper YAML
  path it inspected (e.g. `qcom,sa8255p-geni-se-qup.yaml`) — the patch's
  own binding file does not count.  If no parent wrapper exists, state
  that explicitly.  Silence on the parent-file path is a validator
  violation.
- If a binding revises an existing device, keep the old compatible accepted
  and handled unless the patch removes all users in the same series.

**Property definitions**
- Every property must have a `description` field explaining its meaning and
  units.
- Use standard schema types: `uint32`, `uint64`, `string`, `phandle`,
  `phandle-array`, `bool`, etc.
- Numeric properties must specify `minimum` / `maximum` or an `enum` where
  the value space is bounded.
- Array properties must specify `minItems` / `maxItems`.
- Reuse existing common properties via `$ref`:
  - `reg`, `interrupts`, `clocks`, `resets`, `power-domains`,
    `iommus`, `dmas`, `pinctrl-*`, `#address-cells`, `#size-cells` etc.
    must reference the standard schema in
    `Documentation/devicetree/bindings/` rather than being redefined.
- Deprecated properties must be marked with `deprecated: true`.
- Do not invent new properties that duplicate existing standard ones.

**Resource arrays, names, and dependencies**
- Resource counts (`reg`, `interrupts`, `clocks`, `resets`, `dmas`,
  `power-domains`, `iommus`, etc.) must match the schema's `minItems` /
  `maxItems` and the hardware/driver expectation.
- If a resource array has multiple entries **or** the driver selects entries
  by name, require and document the matching `*-names` property
  (`reg-names`, `interrupt-names`, `clock-names`, `reset-names`,
  `dma-names`, etc.).
- If the resource property is optional but unusable without its names, enforce
  the pair with `dependencies:` or an equivalent `if`/`then`.  Ask: “Can a
  DTS legally provide only one side of the pair, and would the driver then
  silently fall back, pick the wrong resource, or fail later?”  This is
  especially important for named DMA channels: if the driver uses
  `dma_request_chan(dev, "tx")` / `"rx"`, then a binding or example with
  `dmas` but no `dma-names` is a reportable schema/example defect.
  When the binding diff defines both `dmas:` and `dma-names:` schema
  properties and the `examples:` block contains `dmas = <...>`, the review
  must explicitly state whether the example also contains `dma-names = ...`
  and flag the missing example property; silence on this is a validator
  violation.
- Per-compatible resource-count differences must be expressed in schema, not
  only in commit prose.  When a new compatible changes `minItems`/`maxItems`,
  require `allOf`/`if`/`then` constraints that describe the items for each
  compatible; if a property is mandatory only for that compatible, the `then:`
  block must also enforce presence with `required:` and the correct `minItems`.
- Conditional matching for array-valued `compatible` must match membership, not
  array equality.  Inside `if:`, use `compatible: contains: { const: ... }` or
  `contains: { enum: [...] }` when nodes may carry fallback compatibles; a bare
  `compatible: const:`/`enum:` condition can silently fail to match two-string
  compatible arrays.
- Do not introduce DT properties whose only purpose is to carry an internal
  firmware or instance ID.  Prefer standard hardware identification through
  `compatible`, `reg`, node topology, or an already accepted common property.
- `pinctrl-0` must be paired with `pinctrl-names` when the node demonstrates
  or requires pin multiplexing.

**Examples**
- Every binding schema must contain at least one `examples:` block.
- The example must be a minimal but complete DTS node that passes
  `dt_binding_check` without errors.
- Examples must not reference non-existent phandles; use placeholder labels
  (`&clk0`, `&rst0`) that are defined within the example block.
- Examples must include the companion `*-names` properties and dependencies
  for every resource they demonstrate; examples should not teach a DTS shape
  that is legal in schema but non-functional in the driver.  When an example
  contains a named resource array (`dmas`, `clocks`, `resets`, `reg`, etc.),
  explicitly compare it against both the schema dependencies and the driver's
  lookup API before marking the example clean.
- Validate interrupt specifier cell counts against the interrupt parent binding.
  For ARM GIC parents, the specifier is exactly three cells after the phandle
  (`type`, interrupt number, flags); a trailing fourth cell in an example is a
  schema/example bug.

**Validation**
- Read `patch_<N>_dtbinding.txt` (provided as `DT-binding file:`) and report
  all errors and warnings.  If the file is absent, dt_binding_check was not
  applicable for this patch — note "N/A" in the DT / DT-Binding Notes section.
- A tool **SKIP, ERROR, or environment failure** (e.g. dtschema/Python version
  error) is NOT a pass and does NOT make the binding clean.  When the automated
  schema check could not run, you MUST manually apply the schema rules above —
  in particular the `compatible`-shape/fallback check, the resource-array
  `dependencies:` check (`dmas` ⇒ `dma-names`, `clocks` ⇒ `clock-names`, etc.),
  and the example-completeness check — and state in the DT / DT-Binding Notes
  that the verdict is from manual schema review, not tool output.  Do not write
  "binding and driver are consistent" off a skipped check without showing you
  exercised each of those rules against the actual `compatible`, resource
  arrays, and example in the diff.
- **Mandatory example attestation (when `examples:` exists in diff)**: for
  every resource property the schema defines (`dmas`, `clocks`, `resets`,
  `power-domains`, `interrupts`, etc.), explicitly answer in DT-Binding Notes:
  (a) does the example include this property? (b) if yes, does the example
  also include the matching `*-names` companion when the schema or driver
  requires one?  An example that demonstrates a resource without its required
  companion is a defect even if the schema validates — flag `[MINOR]` minimum.
  Do not write "example is correct/valid" without answering (a)+(b) for each
  resource property present in the example node.
- Do NOT run `make dt_binding_check` or `make dtbs_check` directly — the
  orchestrator ran these during the unified loop; results are in the DT-binding
  file.

### 3d.2 Device Tree Source (`.dts` / `.dtsi`) Rules

**Node naming**
- Node names follow the form `<name>@<unit-address>` where `<name>` is the
  generic device class (e.g. `i2c`, `spi`, `gpio`, `ethernet`) — not the
  vendor chip name.
- Unit address must match the first `reg` value (hex, no leading zeros beyond
  one digit, no `0x` prefix in the node name).
- Label names use `lower_case_with_underscores`; avoid camelCase labels.

**`compatible` in DTS**
- Must exactly match a string declared in the corresponding binding schema.
- Most-specific compatible listed first; generic fallback last.
- No trailing whitespace or extra quotes.

**`reg` values**
- Must match the hardware address map; cross-check against the SoC TRM or
  existing nodes for the same SoC.
- Address and size cells must be consistent with the parent bus node
  (`#address-cells`, `#size-cells`).
- When a patch changes a `reg` range size, inspect the consumer driver path
  that reads/maps the resource (`of_address_to_resource`,
  `platform_get_resource`, `devm_platform_ioremap_resource`, `ioremap`, etc.).
  Check for minimum-size clamps, compatibility workarounds, or warnings that
  would make the DT change ineffective or noisy at boot.

**Interrupt specifiers**
- Interrupt number and flags must match the hardware; cross-check against
  existing nodes or the SoC datasheet.
- Use symbolic IRQ flag constants (`IRQ_TYPE_LEVEL_HIGH`, etc.) via the
  appropriate `#include <dt-bindings/interrupt-controller/...>` header.

**CPU topology and cache hierarchy**
- For new SoC `.dtsi` CPU nodes, cross-check `cpu-map` cluster grouping
  against CPU `reg`/MPIDR values, CPU `compatible` strings, PMU PPI
  partitions, power/thermal domains, and `next-level-cache` links.
- If CPUs are split into different `cpu-map` clusters but share the same LLC
  phandle (for example all ultimately point at the same `l3-cache`), do not
  assume the split is correct just because the core types differ. Compare with
  sibling SoC DTSI files and ask for hardware confirmation; flag a [CONCERN]
  when the split appears to be only a big/LITTLE type split rather than a real
  physical/topology boundary.
- Do not overstate this as proof that the scheduler cannot see the shared LLC;
  cacheinfo can still build LLC sibling masks from `next-level-cache`. Treat it
  as a topology consistency concern unless direct runtime breakage is shown.

**Clock, reset, GPIO, pinctrl references**
- All phandle references (`clocks`, `resets`, `gpios`, `pinctrl-0`) must
  point to nodes that exist in the same DTS/DTSI tree.
- Clock and reset indices must match the provider's `#clock-cells` /
  `#reset-cells` and the binding's `clock-names` / `reset-names`.
- GPIO flags must use constants from
  `<dt-bindings/gpio/gpio.h>` (`GPIO_ACTIVE_HIGH`, `GPIO_ACTIVE_LOW`).

**`status` property**
- Disabled-by-default peripherals use `status = "disabled"` in the DTSI and
  are enabled in board-specific DTS with `status = "okay"`.
- Never set `status = "okay"` in a shared DTSI unless the peripheral is
  always present on every board using that DTSI.

**`#include` / `#define` headers**
- Use `<dt-bindings/...>` headers for constants (IRQ types, GPIO flags, clock
  IDs, reset IDs) — never hard-code raw integers for these.
- Do not include C headers directly in DTS files.

**Formatting**
- Indentation: one tab per nesting level.
- Opening brace on the same line as the node name.
- One property per line; no trailing whitespace.
- Hex values lower-case: `0xdeadbeef` not `0xDEADBEEF`.
- Multi-value arrays aligned with angle brackets on the same line:
  `reg = <0x1000 0x100>;`

**Bus node ascending unit-address order (mandatory for DTS patches)**

Child nodes of a bus node (e.g. `soc { }`, `i2c@...`, `amba`) must appear in
strictly ascending unit-address order.  This ordering rule is consistently
enforced by upstream Qualcomm DT reviewers.

Verification algorithm:
1. Identify the bus node that the new child is being added to.
2. Extract unit addresses from sibling nodes visible in the diff (both `+`
   and ` ` context lines).  A unit address is the hex value after `@` in
   the node name (e.g. `timer@f420000` → `0xf420000`).
3. Convert all unit addresses to integers:
   - If the address has no `0x` prefix, treat it as hexadecimal (DT convention).
   - Strip leading zeros for comparison.
   - Comparison: `int(addr, 16)` for each address.
4. Sort the extracted addresses numerically.  The new node's address must
   fit in the correct sorted position relative to its visible siblings.
5. If the new node violates the sorted order: flag as `[MINOR]`.

Algorithm (pseudocode):
```
siblings = []
for each node line matching /^\s*[\w,-]+@([0-9a-fA-F]+)\s*\{/ in diff context:
    addr = int(match.group(1), 16)
    siblings.append((addr, node_name, is_new_line))

sorted_siblings = sorted(siblings, key=lambda x: x[0])
if siblings != sorted_siblings:
    flag [MINOR] "Bus-child ordering: <new_node> at 0x<addr> is out of
    ascending order relative to siblings"
```

`checkpatch` and `dtc` do **not** check bus-child ordering, so this class of
error always passes automated tools.

Example (incorrect — must be flagged):
```
  timer@f420000      ← 0x0f420000
  geniqup@4ac0000    ← 0x04ac0000 — wrong: 0x04ac0000 < 0x0f420000
```
Suggestion: move `geniqup@4ac0000` before `timer@f420000`.

**Property indentation cross-check (mandatory for DTS patches)**

When a patch adds properties to DTS/DTSI nodes, verify each added line's tab
count against its sibling properties *within the same node block*, not just
against the surrounding diff context lines.  Nodes at different nesting depths
(e.g. root-level vs. inside `soc { }`) require different property indentation;
diff context from a differently-nested node can silently mask this mismatch.

`checkpatch` and `dtc` do not enforce tab-count parity within a node, so this
class of error always passes automated checks.

Verification algorithm:
1. For each added (`+`) property line in the diff, identify the enclosing
   node block by scanning upward for the nearest `node@addr {` or `node {`
   line (whether `+` or ` ` context).
2. Within that same node block, find sibling property lines (` ` context lines
   that are NOT sub-node openings or closings).
3. Count leading tab characters on the sibling lines — this is the expected
   indentation depth for that node.
4. Count leading tab characters on the added line.
5. If the added line's tab count ≠ the sibling tab count: flag `[NIT]`.

Algorithm (pseudocode):
```
for each added_line (starts with '+') that looks like a DT property:
    expected_tabs = count_tabs(nearest_sibling_property_in_same_node)
    actual_tabs = count_tabs(added_line)
    if actual_tabs != expected_tabs:
        flag [NIT] "Property indentation: <property> has <actual> tabs,
        siblings have <expected> tabs"
```

**Important**: Only compare within the SAME node block.  A context line from
a parent or child node at a different depth is NOT a valid reference.

**New board DTS files**
- Must `#include` the SoC-level DTSI.
- Must define `/` root node with `compatible` (board-specific string first,
  SoC-generic string second) and `model` property.
- `model` string format: `"<Vendor> <Board Name>"`.
- Must be added to the correct `arch/*/boot/dts/*/Makefile` with
  `dtb-$(CONFIG_<SOC>) += <board>.dtb`.

### 3d.3 Driver `of_match` & `of_*` API Consistency

Driver-side `of_*` API rules have moved to `refs/dt-driver.md` so they can be
applied to driver-only patches without loading the full schema/DTS checklist.
When a patch changes **both** a DT file and driver `of_*` code, both this file
and `refs/dt-driver.md` are included.

### 3d.4 MAINTAINERS & Documentation

- New binding files must add or update a `MAINTAINERS` entry with an `F:`
  line covering `Documentation/devicetree/bindings/<subsystem>/`.
- If the binding introduces a new vendor prefix, the prefix must be added to
  `Documentation/devicetree/bindings/vendor-prefixes.yaml` in the same or a
  preceding patch.
- Binding patches and the driver patch that consumes them should be in the
  same series when submitted to a single maintainer tree; the binding patch
  must come first.  When binding and driver are sent to different maintainer
  trees (e.g. DT bindings via the DT maintainer, driver via the subsystem
  maintainer), the binding series should be sent first and the driver patch
  should include a `Depends-on:` cover-letter note or reference the binding
  series commit hash once merged.
- Commit subject prefix for binding patches:
  `dt-bindings: <subsystem>: <description>`.
- Commit subject prefix for DTS patches:
  `arm64: dts: <soc>: <description>` (adjust arch as appropriate).
