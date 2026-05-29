## Step 3d.3 — Driver `of_match` & `of_*` API Consistency

Apply this checklist when the patch changes **driver C code** that uses the
Device Tree API — `of_match_table`, `of_device_id`, or `of_*` call sites — even
when the patch touches no `.yaml`, `.dts`, or `.dtsi` file. These are rules
about driver source, not about device-tree files; the schema (3d.1) and DTS
(3d.2) checklists in `refs/dt-binding.md` do not apply unless a DT file is also
changed.

Rules are derived from the authoritative upstream references:
`Documentation/devicetree/bindings/writing-bindings.rst` and
`Documentation/process/submitting-patches.rst`.

- Every `compatible` string in `of_device_id[]` must have a corresponding
  binding schema in `Documentation/devicetree/bindings/`.
- `of_device_id` table must be terminated with `{}` sentinel.
- `MODULE_DEVICE_TABLE(of, ...)` must be present for loadable modules.
- `of_match_ptr()` must wrap the `of_device_id` table in the
  `platform_driver` / `i2c_driver` etc. struct when `CONFIG_OF` may be
  disabled.  On architectures where `CONFIG_OF` is always enabled (e.g.
  arm64, arm — `CONFIG_OF` is unconditionally selected on these architectures),
  `of_match_ptr()` is redundant; modern kernel style omits it.  Do not flag
  its absence as a defect on such architectures.  On multi-arch drivers
  targeting architectures where `CONFIG_OF` may be disabled, `of_match_ptr()`
  is required — flag its absence as `[MINOR]`.
- `of_property_read_*` return values must be checked; missing optional
  properties handled with a documented default.
- `of_get_named_gpio()` is deprecated since kernel 5.x — use
  `devm_gpiod_get*()` instead.
- `of_clk_get_by_name()` is deprecated — use `devm_clk_get()` instead.
- `of_node_put()` must be called on every `of_find_*` / `of_get_*` result
  that is no longer needed (or use `of_node_get/put` scope helpers).
- **Match-data / descriptor contract**: when `compatible` data selects an
  ops table, resource descriptor, or platform quirk, ask:
  1. Can the driver bind without that match data (ACPI, manual platform
     device, `driver_override`, or future table entry without `.data`)?  If
     yes, guard the `device_get_match_data()` / `of_device_get_match_data()`
     result before dereferencing.  Do not dismiss an unconditional dereference
     as merely theoretical until the probe path proves that every non-OF bind
     mode is impossible or rejected before the dereference.
     Required proof tokens when dismissing the deref as unreachable: the
     review must explicitly name `driver_override`, `sysfs bind` (manual
     bind), and ACPI (or `has_acpi_companion`) and state why each is
     rejected for this driver; otherwise file a `[CONCERN]` for the missing
     guard.
  2. Does every compatible string and fallback array resolve to the intended
     descriptor?  A fallback to a generic descriptor is correct only when the
     hardware behaviour and required resources are genuinely identical.
  3. Do binding/DTS compatible shapes and driver match tables evolve together?
     A binding-accepted fallback that the driver maps differently is a bug.
  4. Does every ops callback cover every transfer or lifecycle path that can
     reach the descriptor?  If a new descriptor replaces clock/resource helpers
     with callbacks, search for remaining direct calls to the old helpers and
     prove they are unreachable or compatible for that descriptor.
