### 3d.2 Device Tree Source (`.dts` / `.dtsi`) Rules

**Node and property basics**
- Node names use generic device classes (`i2c`, `spi`, `gpio`, `ethernet`, ...),
  not vendor chip names; node form is `<name>@<unit-address>`.
- Unit address equals the first `reg` value, in lowercase hex, no `0x` prefix,
  no leading zeros beyond one digit; labels use `lower_case_with_underscores`.
- DTS `compatible` strings must be declared by the binding, most-specific first,
  fallback last, with no extra quoting/whitespace.
- `reg` ranges must match the hardware map and parent `#address-cells` /
  `#size-cells`. If a patch changes a range size, inspect the consumer mapping
  path (`of_address_to_resource`, `platform_get_resource`,
  `devm_platform_ioremap_resource`, `ioremap`, etc.) for minimum-size clamps,
  compatibility workarounds, or boot warnings that make the DT change ineffective.
- Interrupt numbers/flags must match hardware and use symbolic constants from
  the right `<dt-bindings/interrupt-controller/...>` header.
- Phandles (`clocks`, `resets`, `gpios`, `pinctrl-0`, etc.) must resolve in the
  same DTS/DTSI tree; clock/reset indices must match provider cell counts and
  binding `*-names`; GPIO flags use `<dt-bindings/gpio/gpio.h>` constants.
- Shared DTSI peripherals stay `status = "disabled"`; board DTS enables present
  devices with `status = "okay"`. Do not set `okay` in shared DTSI unless every
  board using it has the device.
- Use `<dt-bindings/...>` constants; never include C headers or hard-code raw
  IRQ/GPIO/clock/reset IDs when a DT binding header exists.
- Formatting: one tab per nesting level, brace on node line, one property per
  line, no trailing whitespace, lowercase hex, and aligned multi-value arrays
  such as `reg = <0x1000 0x100>;`.

**CPU topology and cache hierarchy**
- For new SoC `.dtsi` CPU nodes, cross-check `cpu-map` clusters against CPU
  `reg`/MPIDR values, CPU compatibles, PMU PPI partitions, power/thermal
  domains, and `next-level-cache` links.
- If CPUs are split into clusters but share the same LLC phandle, compare sibling
  SoC DTSI files and ask for hardware confirmation; flag `[CONCERN]` when the
  split appears to be only a big/LITTLE type split rather than a physical
  topology boundary.
- Do not overstate this as scheduler breakage unless runtime evidence proves it;
  treat it as topology consistency because cacheinfo can still build LLC sibling
  masks from `next-level-cache`.

**Bus-child ordering**
- For DTS patches, children of bus nodes (`soc`, `i2c@...`, `amba`, etc.) must
  be in strictly ascending unit-address order; upstream Qualcomm reviewers
  enforce this, while `checkpatch`/`dtc` do not.
- Verification: identify the bus node, collect sibling node unit addresses from
  both added and context lines matching `node@<hex> {`, parse each address as
  hex even without `0x`, sort numerically, and flag `[MINOR]` if a new node is
  out of order. Example: `geniqup@4ac0000` must precede `timer@f420000` because
  `0x04ac0000 < 0x0f420000`.
- **Mandatory context-node check:** when a diff hunk inserts new nodes, the `@@`
  header and surrounding context lines name pre-existing sibling nodes. Extract
  the unit-address of the nearest pre-existing sibling ABOVE the insertion point
  (from the hunk context or `@@` function-name hint). Every new node's
  unit-address must be greater than the preceding context node's address AND less
  than the following context node's address. A `@3d90000` inserted after a block
  ending at `@ae00000` is out-of-order even if the new nodes are sorted among
  themselves. When context is insufficient, use an on-demand read of the
  surrounding DTSI to determine the enclosing address range.
- **Required record format** in `DT / DT-Binding Notes`: for every DTS patch
  adding nodes, state: `node-ordering: preceding_context=<node@addr>,
  new_nodes=[<addr1>, <addr2>, ...], following_context=<node@addr>` and confirm
  `preceding < all new < following`. Omitting this record when nodes are added
  is a self-audit gap. If the hunk `@@` header references a child node of a
  sibling (e.g. `mdss_dp0_out: endpoint`), trace upward to the parent's
  unit-address to determine the insertion point's position in the bus.

**Property indentation cross-check**
- For each added DTS/DTSI property, compare leading tab count with sibling
  properties inside the same enclosing node block, not with unrelated parent or
  child context. `checkpatch`/`dtc` do not enforce this.
- Scan upward to the nearest `node@addr {` or `node {`, find sibling property
  context lines in that same block, and flag `[NIT]` if the added property's tab
  count differs. Only same-node siblings are valid references.

**New board DTS files**
- Include the SoC-level DTSI.
- Define `/` with `compatible` (board-specific first, SoC-generic second) and
  `model = "<Vendor> <Board Name>"`.
- Add the DTB to the correct `arch/*/boot/dts/*/Makefile` with
  `dtb-$(CONFIG_<SOC>) += <board>.dtb`.
- Claimed pinctrl states must map to actual users: every label named in a
  node's `pinctrl-*` should correspond to a real child/device function, and
  new standalone pinctrl labels should be referenced by some node unless the
  patch explains a staged follow-up. Treat unreferenced pinctrl as dead board
  data or missing functionality.
- External GPIO/interrupt lines for keys, sensors, NFC, SD/eMMC, wake sources,
  and similar board devices should not rely on bootloader mux/bias defaults.
  Require explicit pinctrl states unless the binding, SoC pin default, or board
  comment proves the state is fixed and safe across suspend/resume.
- If a board enables an audio route, mic-bias path, analog supply, or DAPM
  widget that depends on a physical regulator, the DTS must wire the matching
  `*-supply`; otherwise a dummy regulator can hide an unpowered capture/playback
  path.
