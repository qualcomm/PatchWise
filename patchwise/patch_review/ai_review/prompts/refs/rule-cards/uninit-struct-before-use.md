# Rule: uninit-struct-before-use

## Trigger

C code declares an on-stack struct passed to a wire/protocol/framework consumer,
uses `__packed`/`struct_size`/`sizeof(*ptr)` allocation, or builds a buffer with
endian helpers (`cpu_to_le*`, `skb_put`) before a send/submit/attach.

## Must Check

- Is an on-stack protocol/command struct fully zero-initialized (`= {}` / `memset`) before individual fields are assigned and the struct is sent?
- After a non-zeroing allocator (`kmalloc`, `kmalloc_array`), are all members initialized on every arm before they are read or sent?
- Does the allocation size match the destination type (`sizeof(*ptr)` / `struct_size`), not a wrong or undersized type?
- When a new opcode/case/payload is added, are the corresponding size/count/length fields updated to account for it?
- Is a kernel-API struct passed to a getter/attach zero-initialized before partial assignment so unset fields are not garbage?

## Evidence Needed

- The struct/buffer declaration and its initialization before first use.
- The allocation size expression vs the destination type.

## Safe Dismissal

Dismiss when source shows full zero-init/`memset` before use, correct allocation
size, and payload accounting updated for new cases.

## Finding Template

```text
[BUG] Uninitialized or undersized struct/buffer before use
File: <path>:<line>
Rule: uninit-struct-before-use
Evidence: <declaration/alloc + first send/read without full init>
Reasoning: <which member is uninitialized or which size is wrong>
Impact: <stack/heap infoleak to device or userspace, OOB write, wrong payload>
Suggestion: <zero-initialize before assignment, fix alloc size, update length fields>
```

## Severity

`[BUG]` for a proven uninitialized send / undersized allocation; `[CONCERN]`
when the unset-field path is plausible but not fully proven.
