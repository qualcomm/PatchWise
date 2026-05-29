# Rule: cross-instance-pointer-unbind

## Trigger

Driver stores or dereferences a raw pointer to another device/component/instance
that can bind or unbind independently.

## Must Check

- Can the pointed-to instance be removed by sysfs unbind, component teardown, hotplug, or bridge/encoder detach?
- Is lifetime protected by `device_link`, refcount/kref, `get_device()`, `suppress_bind_attrs`, or coordinated teardown?
- Are error/remove paths ordered so no surviving instance keeps a stale sibling pointer?
- Does the reader hold the same lifetime lock/ref used by the writer/remover?

## Evidence Needed

- Pointer assignment and all dereference sites.
- Provider/sibling remove or unbind path.
- Lifetime mechanism or explicit bind-attribute suppression.

## Safe Dismissal

Dismiss only with source-cited lifetime proof: managed link/refcount/device ref,
no independent unbind path, or teardown that clears all sibling pointers before free.

## Finding Template

```text
[CONCERN] Cross-instance raw pointer can outlive its provider
File: <driver-path>:<assignment-or-deref>
Rule: cross-instance-pointer-unbind
Evidence: <stored pointer, independent unbind/free path, missing lifetime guard>
Reasoning: <how one instance can dereference another after teardown>
Impact: <use-after-free, stale hardware routing, or crash on unbind/rebind>
Suggestion: <add device_link/refcount/get_device, suppress unbind, or clear pointers in teardown>
```

## Severity

Use `[BUG]` for reachable UAF; `[CONCERN]` when independent unbind exists but a
complete runtime path needs more context.
