# Rule: platform-id-table-module-alias-contract

## Trigger

Driver code changes `struct platform_device_id`, `.id_table`,
`MODULE_DEVICE_TABLE(platform, ...)`, or platform device names used by
`platform_device_register*()` / MFD child creation.

## Must Check

- Does every new platform device name have a matching `platform_device_id` entry or explicit driver-name match?
- Does a loadable module export `MODULE_DEVICE_TABLE(platform, table)` for autoloading?
- Does `.id_table` point at the same table that carries the module aliases?
- Do parent-created child names exactly match the child driver's table strings?
- Is OF match data still available when binding via platform ID instead of OF compatible?

## Evidence Needed

- Platform device name creation site and child driver table.
- `.id_table` assignment and `MODULE_DEVICE_TABLE(platform, ...)`.
- Probe path behavior when `of_device_id` data is absent.

## Safe Dismissal

Dismiss only when platform names, `.id_table`, module aliases, and non-OF probe
behavior all match the new binding path.

## Finding Template

```text
[CONCERN] Platform ID/module alias contract is incomplete
File: <driver-path>:<id-table-or-device-name>
Rule: platform-id-table-module-alias-contract
Evidence: <platform name, id_table, module table, or missing non-OF data path>
Reasoning: <why platform-created device may not bind/autoload/probe correctly>
Impact: <module autoload failure, unbound child device, or NULL match data>
Suggestion: <add matching id_table entry, MODULE_DEVICE_TABLE, or non-OF probe data>
```

## Severity

Use `[BUG]` for definite bind/probe failure; `[CONCERN]` for missing module alias
or ambiguous non-OF data path.
