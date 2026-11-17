# BTF Special Fields in BPF Maps

## Overview

BPF map values can contain special BTF-typed fields (spin locks, timers,
kptrs, list heads, etc.). These fields require special handling during map
copy and update operations because they hold kernel resources that cannot
be naively memcpy'd.

The related helpers perform different lifecycle actions:

- `check_and_init_map_value()` reinitializes the skipped fields.
- `bpf_obj_cancel_fields()` cancels timer, workqueue, and task-work state but
  leaves other fields untouched.
- `bpf_obj_free_fields()` performs full destruction; verify that every field
  destructor is safe in the caller's execution context.

## Which Map Types Support Special Fields

The table is a navigation aid. Verify the current allowlists in
`map_check_btf()` (`kernel/bpf/syscall.c`) for the exact `BPF_MAP_TYPE_*`;
related and per-CPU map types can differ.

| Field Type | Allowed Map Types |
|-----------|-------------------|
| `BPF_SPIN_LOCK`, `BPF_RES_SPIN_LOCK` | HASH, RHASH, ARRAY, CGROUP_STORAGE, SK_STORAGE, INODE_STORAGE, TASK_STORAGE, CGRP_STORAGE |
| `BPF_TIMER`, `BPF_WORKQUEUE`, `BPF_TASK_WORK` | HASH, RHASH, LRU_HASH, ARRAY |
| `BPF_KPTR_UNREF`, `BPF_KPTR_REF`, `BPF_KPTR_PERCPU`, `BPF_REFCOUNT` | HASH, RHASH, PERCPU_HASH, LRU_HASH, LRU_PERCPU_HASH, ARRAY, PERCPU_ARRAY, SK_STORAGE, INODE_STORAGE, TASK_STORAGE, CGRP_STORAGE |
| `BPF_UPTR` | TASK_STORAGE |
| `BPF_LIST_HEAD`, `BPF_RB_ROOT` | HASH, LRU_HASH, ARRAY |

## Required Handling in Map Operations

### Lookup (kernel to userspace copy)

When a map value is copied into a buffer returned to userspace, verify that
special fields are zeroed in the destination before it is exposed. This is
normally done by calling `check_and_init_map_value()` after the copy.

### Update (userspace to kernel copy)

Trace the value from allocation through update or deletion, possible reuse,
and final release. Determine the destination's prior state, ownership of
special fields, possible execution contexts, and when allocator destructors
actually run. If deferred cleanup retains a copied record or other metadata,
verify what references it owns and how long they remain valid.

## BPF-001: BTF Field Handling in Map Copy/Update

**REPORT as bugs**: Map operations on field-capable map types that copy a
value to userspace without zeroing special fields, or whose update, deletion,
recycling, or final release path leaks a special-field resource, leaves a
dangling reference, causes a use-after-free, or invokes an NMI-unsafe
destructor in NMI context.

Before reporting, identify the exact permitted field type, concrete call path
and context, ownership before and after the operation, and final release path.
Explain the concrete failure. For leak claims, also show why eventual cleanup
does not balance ownership. A helper's presence or absence alone is not
evidence.
