# Rule: managed-device-link-manual-remove

## Trigger

Driver code changes `device_link_add()` flags or calls `device_link_remove()` /
`device_link_del()` near `DL_FLAG_AUTOREMOVE_CONSUMER` or
`DL_FLAG_AUTOREMOVE_SUPPLIER` links.

## Must Check

- Was the link created with `DL_FLAG_AUTOREMOVE_CONSUMER` or `DL_FLAG_AUTOREMOVE_SUPPLIER`?
- Does driver code also manually remove/delete the managed link?
- Can remove/error paths double-remove or race with driver-core auto removal?
- If manual removal is required, was the link created without auto-remove flags?

## Evidence Needed

- `device_link_add()` call and flags.
- Manual `device_link_remove()` or `device_link_del()` site.
- Error/remove path ordering relative to driver-core cleanup.

## Safe Dismissal

Dismiss only when the link is unmanaged, the manual removal is for a different
link, or source proves the auto-remove flag cannot be present on that path.

## Finding Template

```text
[BUG] Managed device link is manually removed
File: <driver-path>:<device-link-line>
Rule: managed-device-link-manual-remove
Evidence: <auto-remove device_link_add flags and manual remove/delete site>
Reasoning: <why driver core already owns link removal>
Impact: <double removal, ordering bug, or stale supplier/consumer relation>
Suggestion: <drop manual remove or create an unmanaged link if manual lifetime is needed>
```

## Severity

Use `[BUG]` for auto-remove link plus manual remove/delete; `[CONCERN]` when the
flag path is indirect and needs more context.
