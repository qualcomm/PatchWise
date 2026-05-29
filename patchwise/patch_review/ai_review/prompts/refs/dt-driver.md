## Step 3d.3 — Driver `of_match` & `of_*` API Consistency

Apply this checklist when driver C code changes `of_match_table`,
`of_device_id`, `device_get_match_data()`, `of_device_get_match_data()`, or
other `of_*` call sites, even when no `.yaml`, `.dts`, or `.dtsi` file changes.
These are driver-source rules; load the DT base/schema/DTS checklist in
`refs/dt-binding.md` only when DT contract files also change.

Upstream references: `Documentation/devicetree/bindings/writing-bindings.rst`
and `Documentation/process/submitting-patches.rst`.

| Trigger | Check / required proof | Finding |
|---|---|---|
| New or changed `compatible` in `of_device_id[]` | Confirm a matching binding schema exists under `Documentation/devicetree/bindings/`. | Flag missing schema as DT/binding issue. |
| `of_device_id[]` table | Require final `{}` sentinel. | Flag malformed unterminated tables. |
| Loadable module with OF table | Require `MODULE_DEVICE_TABLE(of, ...)`. | Flag missing module alias support. |
| Driver can build where `CONFIG_OF` may be disabled | Require `of_match_ptr()` around the table in `platform_driver`, `i2c_driver`, etc. | Flag `[MINOR]` if absent. Do not flag on OF-always architectures such as arm/arm64 or when the driver cannot build without OF. |
| `of_property_read_*` | Check return values; optional properties need documented defaults. | Flag unchecked required properties or undocumented optional defaults. |
| Deprecated GPIO/clock OF helpers | Prefer the `devm_*` variant of any reference getter when device lifetime matches: e.g. `devm_gpiod_get*()` over `of_get_named_gpio()`, `devm_clk_get*()` over `of_clk_get()`/`of_clk_get_by_name()`, `devm_reset_control_get*()` over `of_reset_control_get*()`, `devm_regulator_get*()` over `regulator_get*()`. If a non-devm getter remains, treat the returned handle as an owned reference and pair it with the matching `*_put()`/release on every probe-error, remove/unbind, suspend-disable, and retry path; or document the explicit lifetime transfer to a named owner. | Flag deprecated helper use when the modern API applies; flag a missing release for any non-devm reference handle as a leak. |
| `of_find_*` / `of_get_*` node refs | Require `of_node_put()` when the node is no longer needed, or use scope helpers. | Flag leaked node references. |
| `devm_clk_bulk_get_all()` or resource-get-all APIs for compatible-required resources | If match data says clocks/resources are required, handle both negative errors and zero returned resources. Schema validation is not a substitute for a clear runtime error on invalid DT. Trigger specifically on `devm_clk_bulk_get_all()` followed by only `< 0` handling before registration, MMIO, or `clk_bulk_prepare_enable()`. | Flag silent success with zero required resources as at least `[CONCERN]` (not `[MINOR]`), escalating when later MMIO/PHY/register access deterministically needs the resource. |
| `devm_clk_bulk_get_optional()` / optional resource getters | Missing optional resources are success; do not write fallback logic that expects `-ENOENT` for absent optional clocks. | Flag dead fallback branches or use required getters when the compatible truly requires the resource. |

**Match-data / descriptor contract:**
- Guard `device_get_match_data()` / `of_device_get_match_data()` before
  dereference when the driver can bind without match data: ACPI, manual platform device/sysfs
  bind, `driver_override`, legacy platform data, or future table entries without
  `.data`. Dismiss an unconditional dereference only after the review explicitly
  names `driver_override`, `sysfs bind`, and ACPI/`has_acpi_companion`, and proves
  each is rejected before the dereference; otherwise file `[CONCERN]`.
- Check every compatible string and fallback array maps to the intended
  descriptor. A generic fallback is safe only when hardware behavior and required
  resources are truly identical.
- A fallback compatible is unsafe when the new hardware needs extra clocks,
  resets, bus-enable sequencing, power domains, register-access gates, or quirks
  absent from the fallback descriptor/driver. Treat the binding, DTS, and driver
  match table as one ABI contract and require source proof before clearing.
- Keep binding/DTS compatible shapes and driver match tables in sync; a binding
  fallback accepted by schema but mapped differently by the driver is a bug.
- For compatible-selected ops/resource descriptors, prove every callback covers
  all transfer and lifecycle paths that can reach it. If descriptors replace old
  helpers with callbacks, search for remaining direct helper calls and prove they
  are unreachable or descriptor-compatible.
- For shared probe/helper refactors or changed compatible-selected mode bits,
  preserve runtime PM enablement, hardware-control defaults, provider-array
  coverage, legacy fallback, resource optionality, and registration side effects.
  Required proof records: `codebase audit: entrypoints ...`, `codebase audit:
  callees ...`, and `codebase audit: siblings ...`. Clear only when each behavior
  is re-established or proven unreachable for the new platform.
- If probe mutates a global/static descriptor, ops table, parent map, or frequency
  table based on `compatible`, prove single-instance exclusivity; without proof,
  file at least `[CONCERN]` for shared-state corruption risk.
