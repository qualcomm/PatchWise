# Rule: rcu-refcount-release

## Trigger

C code changes RCU-protected pointer access (`rcu_dereference`,
`rcu_assign_pointer`, `*_rcu` list walks) or reference-count lifecycle
(`kref_put`, `refcount_dec`, `kobject_put`, `put_device`) on an object.

## Must Check

- Is every `rcu_dereference()` inside a held `rcu_read_lock()` (or equivalent) section?
- Is an RCU-published pointer updated with `rcu_assign_pointer()` and freed only after `synchronize_rcu()`/`kfree_rcu()`?
- After the final `kref_put`/`refcount_dec_and_test`, is the object freed only in the release callback, never directly at the put site?
- Is a refcounted object dereferenced after the put that may have dropped the last reference?

## Evidence Needed

- The RCU read/update site and the surrounding lock/grace-period proof.
- The put call, the release callback, and any post-put dereference.

## Safe Dismissal

Dismiss when source shows the RCU read is lock-protected and frees use a grace
period, or the put is not the last reference / object is not touched after.

## Finding Template

```text
[BUG] Unsafe RCU access or post-release reference use
File: <path>:<line>
Rule: rcu-refcount-release
Evidence: <rcu_dereference without lock, or deref after final put>
Reasoning: <missing read-side lock / grace period, or use-after-free after put>
Impact: <torn pointer read, use-after-free, refcount underflow>
Suggestion: <wrap in rcu_read_lock, free via kfree_rcu, move free into release cb>
```

## Severity

`[BUG]` for unlocked RCU deref or post-final-put use; `[CONCERN]` when the
last-reference condition is not fully proven.
