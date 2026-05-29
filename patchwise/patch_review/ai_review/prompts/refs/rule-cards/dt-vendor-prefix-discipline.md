# Rule: dt-vendor-prefix-discipline

## Trigger

A YAML binding diff adds a new top-level property whose name is hyphenated
device/firmware/feature-specific (e.g. `tmd-names`, `cdsp-config`,
`fastrpc-domain`) — i.e. not part of the kernel-standard hyphenated property
set (`clock-names`, `reset-names`, `dma-names`, `interrupt-names`,
`reg-names`, `interconnect-names`, `*-supply`, `*-gpios`, `#cooling-cells`,
`pinctrl-N`, `pinctrl-names`, etc.).

## Must Check

- Is the new property a kernel-standard binding property (the names listed
  above, or anything documented in
  `Documentation/devicetree/bindings/property-units.txt` /
  `common-properties.txt` / `thermal-cooling-devices.yaml` /
  similarly-canonical core schemas)?  If yes, dismiss.
- Is the new property device/firmware/feature-specific and NOT under the
  vendor-namespaced form (`<vendor>,property-name`)?  Vendor-specific
  properties must carry the vendor prefix to avoid namespace collisions
  with future standard properties or other vendors.
- Is the chosen vendor prefix listed in
  `Documentation/devicetree/bindings/vendor-prefixes.yaml`?
- For shared (cross-vendor) features that legitimately deserve a non-prefixed
  name, is the property already submitted/documented in a core schema rather
  than a vendor-specific one?

## Evidence Needed

- The exact added property line in the YAML diff and its containing schema
  (vendor-rooted vs subsystem-rooted).
- The vendor prefix used elsewhere in the same schema or driver.
- A grep of `vendor-prefixes.yaml` for the chosen prefix.

## Safe Dismissal

Dismiss when the property is a kernel-standard core binding (clock/dma/
interrupt/reset/reg/interconnect-names, supply/gpio family, cooling-cells,
pinctrl-N), or when the unprefixed name is intentionally being elevated to a
core/cross-vendor binding via a parallel core-schema submission.

## Finding Template

```text
[MINOR] Vendor-specific DT property lacks `<vendor>,` prefix
File: <binding-path>:<property>
Rule: dt-vendor-prefix-discipline
Evidence: <added bare property name + the schema's vendor context>
Reasoning: <why the unprefixed name risks namespace collision>
Impact: <future standard property or another vendor's binding cannot reuse the name>
Suggestion: <rename to `<vendor>,<property>` (e.g. `qcom,tmd-names`)>
```

## Severity

`[MINOR]` for a typical vendor-specific property missing the prefix; `[CONCERN]`
when the unprefixed name shadows or is likely to shadow a known core/standard
property; never `[BUG]` (this is a naming/ABI hygiene rule, not a runtime bug).
