### 3f.4 Per-CPU and Hot-Pluggable Hardware

Per-CPU hardware and software state must track CPU hotplug and owner-CPU rules.

| Trigger | Required check / proof | Finding |
|---|---|---|
| CPU online check before access: access to per-CPU hardware | Code must run on the owning CPU or prove that CPU is online. `smp_call_function_single()` failure must unwind all pre-call resources symmetrically. | Leaked resource on failed SMP call is `[BUG]`. |
| `this_cpu_*` | Valid only for state owned by the currently executing CPU. Target-CPU/device paths from sysfs/ioctl/workqueue require `per_cpu(var, cpu)`, SMP call to owner CPU, or another owner guarantee. | Wrong CPU state access is `[BUG]`. |
| `smp_call_function_single()` / `_many()` / `on_each_cpu()` writes per-CPU software state | Check return value. If the call fails (`-ENXIO`), caller must directly clear/update offline CPU state, e.g. `per_cpu(var, cpu) = value`. | Ignored return plus called function writes state later read by PM notifier, idle, hotplug, or online path is `[BUG]` because stale per-CPU pointers can cause UAF. |
| PM notifier / CPU idle callback pointer validity: dereferences per-CPU pointer | Prove pointer is nulled before object free on successful disable, failed SMP call, and `.remove()`. IRQ-disabled context does not protect against a stale pointer set on an earlier CPU execution. | Missing nulling path is `[BUG]`. |
| sysfs / ioctl entry point guards: dispatch to a specific CPU | Either hold `cpus_read_lock()` across online check and dispatch, or call `smp_call_function_single()` directly and handle `-ENXIO`. | Bare `cpu_online()` without `cpus_read_lock()` is racy and `[CONCERN]`. |
| Hotplug callbacks / Resource release on CPU offline: new per-CPU functionality | Register `.startup` and `.teardown` hotplug callbacks. Release CPU-tied IRQ affinities, hardware contexts, and IDs in `.teardown()` before offline. | Missing hotplug lifecycle or offline release is a hardware lifecycle bug. |
