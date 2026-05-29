<!-- Conditional fragment of code-logic.md — the diff shows user-action / trigger entrypoints (ioctl/sysfs/debugfs/configfs/netlink/
event/control with potential firmware command). Apply on top of
refs/code-logic.md §3c.2 Data-Flow Picture base prose. -->

#### Action / trigger contract checklist

Apply when a public control, ioctl, request, button, execute-on-write field, or
event-like API reaches a setter, property-programming path, or firmware command.
Classify persistent state vs one-shot action from API definition, flags, and
in-tree implementations. one-shot actions must not replay from bulk "apply all",
default programming, resume/restore, or setup unless the contract explicitly
requires replay. For `execute_on_write_replay`, prove the execute-on-write path
can run only from the explicit user/action request or cite source showing replay
is required by the ABI; replay from init/restore/session setup is `[BUG]` when it
can trigger firmware/hardware action. If common setter tables mix state and
trigger setters, identify the filter/gate for trigger entries. Cross-check
sibling backends for the same public action; mismatched fire conditions are
semantic bugs.
- Dynamic controls that are allowed during streaming must be serialized with any
  queue/stream/firmware path sharing the same command buffer or packet builder.
  A control-handler lock alone is insufficient if qbuf/stream paths use a
  different lock and both write into the same retained packet storage.

**User-facing ABI guard:** for ioctl, sysfs, configfs, netlink, debugfs promoted
to tooling, or other UAPI-like entrypoints, check that new structs/attributes are
extensible and stable: reserved fields zero-checked, padding initialized, sizes
and versions validated, 32-bit compat handled, user lengths bounded, and
`copy_from_user()`/netlink attribute parsing rejects unknown or short input as
appropriate. Do not file speculative ABI findings for private debug-only knobs;
file `[CONCERN]` or `[BUG]` when a committed userspace ABI can leak padding,
break compat, or accept malformed user-controlled lengths.
