# Rule: shared-scratch-serialization

## Trigger

Patch touches code that constructs commands, packets, descriptors, messages, or
configuration buffers in shared/retained mutable storage and submits them to
hardware, firmware, or a queue — especially when construction and submission can
be reached from different contexts (ioctl + streaming, control + qbuf, IRQ +
process, multiple clients on one channel).

## Must Check

- Is the full construction-to-submission sequence serialized, not just the
  final queue-write/doorbell/send? A lock only around the submit call is
  insufficient if another path can interleave writes into the same buffer
  during construction.
- Do all paths that build into the shared buffer hold the same lock (or
  equivalent serialization) from first field write through handoff?
- If a dynamic control/setter path and a streaming/transfer path both write
  into the same retained packet/descriptor storage, do they share the same
  serialization? A control-handler lock alone is insufficient if the
  streaming path uses a different lock.
- For multi-client dispatch (multiple userspace fds, multiple codec/DAI links,
  multiple channels), can two clients race construction on the same shared
  object? If so, is per-client or per-object locking used?

## Evidence Needed

- The shared mutable buffer/descriptor/packet struct and where it lives
  (per-device, per-context, global).
- All write sites that construct into it (list the functions).
- The submission/handoff site (doorbell, queue push, firmware send).
- The lock(s) held during construction vs during submission.
- Whether multiple paths can reach construction concurrently.

## Mandatory Attestation Record

When the diff touches command/packet/descriptor construction that flows to a
submit path, include in Code Logic Maps:

```
scratch_serialization_audit:
  shared_object: <struct name or buffer — where it lives (per-dev/per-ctx/global)>
  construction_paths: [<func1 — lock held: X>, <func2 — lock held: Y>]
  submission_site: <function:line — lock held: Z>
  serialization_consistent: <YES all paths hold same lock | NO — path X holds different lock>
  concurrent_reach: <YES — describe two contexts | NO — single-threaded>
```

Omitting this when shared command/packet construction is in the diff is a
review gap.

## Safe Dismissal

Dismiss only when:
- All construction and submission paths hold the same lock (quote each
  acquire site).
- The buffer is per-context/per-fd with no cross-context sharing (quote the
  allocation proving private ownership).
- Construction is always single-threaded (e.g. probe-only, no concurrent
  callers — quote the serialization guarantee).
- The buffer is constructed on-stack and never retained (quote the local
  declaration and immediate submit without pointer escape).

## Finding Template

```text
[BUG] Shared command buffer construction not serialized with submission
File: <path>:<construction-site>
Rule: shared-scratch-serialization
Evidence: <path A builds packet under lock X; path B builds into same buffer
  under lock Y (or no lock); submit at <site> only locks Z>
Reasoning: Interleaved writes corrupt the packet/descriptor before submission
Impact: Wrong command sent to hardware/firmware, data corruption, protocol error
Suggestion: Extend lock X to cover both construction and submission on all paths,
  or use per-path private staging buffers with a single serialized copy-to-shared

[CONCERN] Dynamic control and streaming path share retained packet storage
File: <path>:<control-setter>
Rule: shared-scratch-serialization
Evidence: <control handler holds ctrl_lock; streaming path holds stream_lock;
  both write to dev->cmd_packet>
Reasoning: Concurrent control set during active stream can corrupt in-flight packet
Impact: Garbled firmware command during streaming
Suggestion: Serialize control application with stream packet construction under
  a single lock, or stage control values and apply atomically at packet build time
```

## Severity

`[BUG]` when two concurrent paths can demonstrably interleave writes into the
same shared buffer before submission — the resulting packet/command is
corrupted. `[CONCERN]` when the concurrency is plausible but not fully proven
(e.g. control path reachability during active streaming not confirmed).
