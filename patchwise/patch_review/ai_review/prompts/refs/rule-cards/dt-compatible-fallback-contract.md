# Rule: dt-compatible-fallback-contract

## Trigger

Binding, DTS, or driver changes compatible strings, fallback arrays,
`of_device_id`, `of_match_table`, or compatible-selected match data. This is
especially high-signal when a new primary compatible is added to an existing
fallback tuple and the same series adds resources, clocks, power sequencing,
register offsets, or compatible-selected ops for that primary.

## Must Check

- Do binding schema, wrapper/parent schema, DTS/examples, and driver table accept the same tuple shape and order?
- Does every new compatible have a schema and driver/data path?
- Is every new compatible a concrete hardware identifier, not a wildcard/family
  placeholder such as `x`, `xx`, `*`, or a transport suffix that merely repeats
  the parent bus? If the hardware family needs shared handling, use a specific
  primary compatible plus a proven fallback, or split variants when quirks can
  differ.
- Is fallback hardware truly compatible: same resources, quirks, power/register sequencing, and match data?
- Do schema conditions use `contains:` when arrays with fallbacks are valid?
- Build the two-axis compatibility matrix for every fallback tuple:
  - **new kernel + old DTB**: old deployed DTBs still bind and keep the same
    resource requirements and register behavior.
  - **old kernel + new DTB**: if the primary compatible is unknown, the fallback
    compatible selects an older driver/descriptor that must be safe for the new
    hardware.
- For the **old kernel + new DTB** case, prove the fallback driver can operate
  safely without any newly-required resources, clocks, power domains, bus votes,
  reset sequencing, status registers, or quirks. A new primary match entry in
  the same patch does not prove fallback safety for older kernels.
- If the primary hardware needs a different register offset, status-vs-control
  semantic, clock gate, or enable/disable sequence than the fallback descriptor,
  treat the fallback as unsafe unless the patch explicitly prevents old kernels
  from binding through that fallback.

## Evidence Needed

- Changed compatible schema/DTS/driver lines.
- Datasheet/driver evidence for the exact part number or variant represented by
  each new compatible; if the string contains `x`, explain whether it is an
  official part name or an unsafe wildcard.
- Parent/wrapper schema or proof none exists.
- Driver descriptor/match-data selected by each compatible.
- Resource or quirk differences between specific and fallback hardware.
- Old-kernel fallback path: which existing driver descriptor an older kernel
  would select from the fallback string, including its required resources,
  enable/disable callbacks, status callback, and register offsets.

## Safe Dismissal

Dismiss only when every constrained surface accepts the same tuple and the
fallback path is source-proven compatible with the new hardware in both matrix
directions. Do not dismiss wildcard/family compatibles merely because binding
and driver strings match each other; the ABI name must still be specific enough
for future variant quirks. Do not dismiss an old-kernel fallback risk by citing
the new kernel's primary-compatible match data; old kernels will not have that
entry.

## Finding Template

```text
[BUG] DT compatible fallback contract is inconsistent
File: <binding/dts/driver-path>:<compatible>
Rule: dt-compatible-fallback-contract
Evidence: <schema tuple, DTS/example, and driver data mismatch>
Reasoning: <why valid DT is rejected or wrong fallback data is selected>
Impact: <probe failure, wrong resources/quirks, or ABI mismatch>
Suggestion: <align schema/DTS/driver or remove unsafe fallback>
```

## Severity

`[BUG]` for schema/DTS/driver mismatch or unsafe fallback that can select the
wrong descriptor, access unpowered MMIO, program the wrong register, or miss a
mandatory resource. Use `[CONCERN]` when fallback safety lacks resource/quirk
proof but the runtime failure mode is not yet deterministic.
