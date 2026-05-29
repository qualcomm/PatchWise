# Rule: dt-driver-of-match-contract

## Trigger

Use this card when driver code changes `of_device_id`, `of_match_table`,
`MODULE_DEVICE_TABLE(of, ...)`, `of_match_ptr()`, `device_get_match_data()`, or
compatible-selected descriptors/ops.

## Must Check

- Does every new compatible have a matching binding schema?
- Is the `of_device_id[]` table terminated by a final `{}` sentinel?
- Does a loadable module export `MODULE_DEVICE_TABLE(of, table)`?
- Is `of_match_ptr()` needed when the driver can build without `CONFIG_OF`?
- Is match data guarded before dereference for ACPI, sysfs bind, driver_override,
  legacy platform data, or table entries without `.data`?
- Do fallback compatibles map to descriptor data that is truly compatible?

## Evidence Needed

- Changed match table and platform/i2c/spi driver registration.
- Kconfig/module context and binding path.
- `device_get_match_data()` dereference site.
- Descriptor callbacks/resources selected by compatible.

## Safe Dismissal

Dismiss only when schema, module aliasing, table termination, OF-optional build
behavior, and match-data lifetime all match the driver's bind paths.

## Finding Template

```text
[CONCERN] Driver OF match contract is incomplete
File: <driver-path>:<match-table-or-call>
Rule: dt-driver-of-match-contract
Evidence: <match table, module table, get_match_data, or descriptor mismatch>
Reasoning: <which bind path can miss data, aliasing, schema, or fallback safety>
Impact: <module autoload failure, NULL dereference, wrong descriptor, or no schema>
Suggestion: <add schema/sentinel/MODULE_DEVICE_TABLE/of_match_ptr/guard/fix data>
```

## Severity

Use `[BUG]` for NULL dereference, wrong descriptor, or missing schema for a new
compatible. Use `[CONCERN]` for alias/OF-optional/fallback risks.
