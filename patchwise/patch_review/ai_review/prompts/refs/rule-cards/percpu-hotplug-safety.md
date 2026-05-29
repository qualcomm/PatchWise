# Rule: percpu-hotplug-safety

## Trigger

Code changes per-CPU access (`this_cpu_*`, `per_cpu`, `for_each_*_cpu`), SMP
cross-calls (`smp_call_function*`, `on_each_cpu*`), CPU-hotplug registration
(`cpuhp_*`), or `cpu_online`/`cpus_read_lock` guards.

## Must Check

- Is per-CPU hardware state accessed only on its owning CPU, or correctly via `smp_call_function_single` when accessed from another CPU (e.g. sysfs/ioctl path)?
- Is the return of `smp_call_function_single` checked when the called function writes state the caller later reads?
- Is a `cpu_online()` check protected by `cpus_read_lock()` so the CPU cannot be unplugged between the check and the dispatch?
- Are per-CPU pointers cleared before free, with hotplug/PM-notifier callbacks unwound symmetrically?
- Is a failed cross-call unwound rather than leaving partial per-CPU state?

## Evidence Needed

- The per-CPU access site and which CPU executes it.
- Any hotplug lock/guard around online checks and cross-calls.

## Safe Dismissal

Dismiss when source proves owner-CPU execution, checked cross-calls, and
hotplug-locked online checks.

## Finding Template

```text
[BUG] Unsafe per-CPU or CPU-hotplug access
File: <path>:<line>
Rule: percpu-hotplug-safety
Evidence: <per-CPU/cross-call/online-check site>
Reasoning: <wrong-CPU access, unchecked cross-call, or hotplug race>
Impact: <stale/wrong per-CPU data, race with unplug, dangling per-CPU pointer>
Suggestion: <use smp_call_function_single, check its return, hold cpus_read_lock>
```

## Severity

`[BUG]` for a proven wrong-CPU access or hotplug race; `[CONCERN]` when the
calling CPU or hotplug window is not fully proven.
