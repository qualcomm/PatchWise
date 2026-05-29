## Step 3d — Device Tree & DT-Binding Review Checklist

Apply this checklist when a patch touches a Device Tree contract file:
- `Documentation/devicetree/bindings/**/*.yaml` binding schemas.
- `arch/*/boot/dts/**/*.dts` / `*.dtsi` device-tree source.
- `include/dt-bindings/**/*.h` binding header constants.

Driver C changes that only touch `of_match_table`, `of_device_id`, or `of_*`
APIs, with no DT file change, use `refs/dt-driver.md` Step 3d.3 instead.
When a patch changes both DT contract files and driver `of_*` code, apply both refs.
Use upstream `writing-schema.rst`, `writing-bindings.rst`, and
`submitting-patches.rst` as the external baseline.

The detailed schema and DTS rule blocks are split into trigger-conditional
fragments so a binding-only patch does not pull DTS rules and a DTS-only
patch does not pull the YAML schema rules:

- `refs/dt-binding-yaml.md` — Step 3d.1 YAML schema rules. Loaded when the
  patch touches `Documentation/devicetree/bindings/**/*.yaml` or any
  `include/dt-bindings/...h` header.
- `refs/dt-binding-dts.md` — Step 3d.2 DTS / DTSI source rules. Loaded when
  the patch touches `arch/*/boot/dts/**/*.dts` or `*.dtsi`.

If neither fragment loads but this base file is included, the patch touched a
DT-adjacent surface (for example a vendor-prefix file) without changing a
schema or DTS source; apply 3d.4 below and report `Not applicable: …` for the
schema/DTS sub-checklists.

### 3d.3 Driver `of_match` & `of_*` API Consistency

Driver-side `of_*` API rules live in `refs/dt-driver.md` so driver-only patches
can load them without the DT base/schema/DTS checklist. Include both refs when
a patch changes both DT contract files and driver `of_*` code.

### 3d.4 MAINTAINERS & Documentation

- For new binding files, read current `MAINTAINERS` before filing a finding;
  check whether an existing `F:` glob already covers the new path (for example
  `qcom,*-iris.yaml`). File a MAINTAINERS issue only when the new binding, or a
  sibling new file such as a dt-binding header, is genuinely uncovered.
- New vendor prefixes must be added to
  `Documentation/devicetree/bindings/vendor-prefixes.yaml` in the same or a
  preceding patch.
- Binding patches and consuming driver patches should be in the same series when
  they go through one maintainer tree, with the binding first. If they go
  through different trees, send the binding first and add a cover-letter
  `Depends-on:` note or reference the merged binding commit from the driver
  patch.
- Subject prefixes: binding patches use
  `dt-bindings: <subsystem>: <description>`; DTS patches use
  `arm64: dts: <soc>: <description>` or the matching architecture prefix.
