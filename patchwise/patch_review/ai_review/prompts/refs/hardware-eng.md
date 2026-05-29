## Step 3f — Hardware Engineering Perspective

Apply this checklist whenever a patch touches hardware driver code.  It
applies to **any subsystem** — not just CoreSight — and catches classes of
bug that pure software analysis misses because they depend on hardware state
invariants invisible in the diff alone.

**Trigger conditions** — apply Step 3f when the diff touches any of:
- Hardware register access (`readl`, `readl_relaxed`, `readb`, `readb_relaxed`,
  `readw`, `readw_relaxed`, `readq`, `readq_relaxed`, `writel`, `writel_relaxed`,
  `writeb`, `writeb_relaxed`, `writew`, `writew_relaxed`, `writeq`,
  `writeq_relaxed`, `ioread*`, `iowrite*`, or CPU system-register access via
  assembly / `mrs` / `msr`)
- `regmap` register access (`regmap_read`, `regmap_write`, `regmap_update_bits`,
  `regmap_bulk_read`, `regmap_bulk_write`, `regmap_raw_read`, `regmap_raw_write`,
  `regmap_noinc_read`, `regmap_noinc_write`, and related `regmap_*` calls —
  these are MMIO/I2C/SPI register accesses and trigger the same hardware-state
  analysis as direct `readl`/`writel`)
- Device probe, remove, or shutdown callbacks
- Power management callbacks (`.suspend`, `.resume`, `.runtime_suspend`,
  `.runtime_resume`, PM notifiers, `pm_runtime_get*` / `pm_runtime_put*`)
- IRQ registration or handlers (`request_irq`, `devm_request_irq`, threaded IRQs)
- DMA setup or tear-down (`dma_alloc_*`, `dma_map_*`, `dma_request_chan`)
- Per-CPU hardware devices or `smp_call_function_single()`,
  `smp_call_function_many()`, or `on_each_cpu()` to access hardware or write
  per-CPU software state
- CPU hotplug notifiers (`cpuhp_setup_state*`, `.startup` / `.teardown` callbacks)
- Clock, regulator, reset-controller, or power-domain management

**Sub-section N/A rule**: for each sub-section 3f.1–3f.6, first check whether
its specific trigger patterns appear in the diff.  If none do, write the
corresponding Hardware Engineering Notes bullet as `"N/A — <reason>"` (e.g.
`"Per-CPU hotplug: N/A — no smp_call or cpuhp code touched"`) and skip that
sub-section's detailed analysis.  Do not fabricate findings for sub-sections
whose triggers are absent.

### 3f.1 Device Power State Before Register Access

Any MMIO or system-register access must only occur when the device's power
domain and clocks are on.

- **pm_runtime bracket**: register-access paths reachable outside of the
  device's enable/disable sequence (e.g. sysfs, debugfs, interrupt handlers)
  must acquire a PM runtime reference before the access and release it after,
  or document why the power domain is guaranteed on at that point.
  **Preferred pattern** (v5.1+): `pm_runtime_resume_and_get(dev)` — atomically
  resumes the device and increments the usage count; returns a negative errno
  on failure.  Check the return value and return the error immediately without
  accessing any register.  Release with `pm_runtime_put(dev)` on the success
  path.
  **Older pattern**: `pm_runtime_get_sync(dev)` increments the usage count
  *before* calling the resume callback; if the resume callback fails it
  returns a negative errno while the count is already incremented.  The caller
  must call `pm_runtime_put_noidle(dev)` (not `pm_runtime_put()`) to balance
  the count on the error path.  Unchecked calls to either function are `[BUG]`
  — a failed resume leaves the device unpowered while registers are accessed,
  causing a bus fault or data corruption.  Additionally, confirm the caller
  treats only **negative** return values as errors: `pm_runtime_get_sync()`
  returns `1` (not `0`) on a successful wake from suspend.  A guard of the
  form `if (ret)` incorrectly treats a successful resume as an error — flag
  as `[BUG]`.
  When the diff or any context file contains `pm_runtime_get_sync(`, the
  review must explicitly state whether the return is checked, whether the
  caller balances with `put_noidle` on error, or whether a migration to
  `pm_runtime_resume_and_get` is preferred — silence on this point is a
  validator violation.
- **Probe-time capability reads**: hardware ID/capability registers must be
  read after the device is powered and clocked, before any configuration is
  applied.  Cache these in a struct — but that struct must hold only **static**
  capability information, never runtime state.  Storing runtime state (e.g.
  current status-register values, single-shot flags) in a capabilities struct
  is `[CONCERN]` because sysfs or debugfs readers will see stale values.
  **Dynamic capabilities** (e.g. negotiated link speed, firmware-reported
  feature flags that change on re-probe) must not be cached across
  probe/remove cycles; re-read them at each probe.
- **Power-state restore symmetry**: suspend/runtime_suspend or deactivate
  paths that power-collapse hardware must have a matching resume/activate
  path that restores every state not retained by hardware: programmed
  registers, clocks, resets, interconnect bandwidth, regulators, OPP/genpd
  performance votes, DMA state, and cached software mirrors.  Ask:
  1. After the resume/activate helper returns, is the hardware in the same
     usable state the old code guaranteed?
  2. Did suspend/deactivate drop clocks, OPP/performance votes, or power-domain
     votes to zero?
  3. Before the next transfer, what path restores each dropped vote or
     reprograms each lost hardware state?
  4. Can a cached fast path such as `if (rate == cached_rate) return 0` skip
     that restore/revote/reprogram step?
  Positive conclusions require source evidence: name the exact resume/helper
  call that restores each dropped vote.  If a helper's comment or body says it
  does not alter performance states, the review must not claim that it restores
  OPP/genpd votes.  File `[BUG]` when the missing restore is reachable and
  deterministic.  Use `[CONCERN]` only when hardware retention or platform
  reachability remains uncertain after reading the resume helper and relevant
  transfer path.
  When the review acknowledges that an OPP/perf/clock-rate vote is not
  restored on resume (e.g. "rate is re-set on next transfer"), it must
  also quote any cached fast-path skip in the next-transfer path
  (`if (clk_hz == cur_speed_hz) return 0;` or equivalent) and prove which
  call defeats it; otherwise file `[BUG]`/`[CONCERN]`.  Silence on the
  cached fast-path is a validator violation.

### 3f.2 Hardware Resource Lifecycle Symmetry

Every hardware resource acquired must be released on all exit paths.

- **IRQ lines**:
  - `request_irq()` → requires a matching `free_irq()` on all error and
    remove paths.
  - `devm_request_irq()` → automatic cleanup on device removal; do **not**
    add a manual `free_irq()` in `.remove()` — doing so is a double-free
    that triggers on driver unbind.  Flag any `.remove()` that calls
    `free_irq()` on an IRQ registered with `devm_request_irq()` as `[BUG]`.
- **DMA channels**: `dma_request_chan()` must have a matching
  `dma_release_channel()` on all error and remove paths.
- **Clocks and regulators**: every `clk_prepare_enable()` must have a matching
  `clk_disable_unprepare()` on all paths; every `regulator_enable()` must have
  a matching `regulator_disable()`.
  `devm_clk_get_enabled()` (v6.2+) combines get + prepare + enable and
  auto-disables on device removal — do **not** add a manual
  `clk_disable_unprepare()` when this helper is used; doing so is a
  double-disable bug.
- **Memory-mapped regions**: `ioremap()` must have a matching `iounmap()` on
  all error and remove paths.
- **Transport-backed regmap bounds**: custom `regmap_raw_read` / `reg_read`
  callbacks backed by async transports must reject caller sizes larger than the
  protocol response buffer before queuing the request.  Copying only the fixed
  response capacity and returning success leaves stale bytes in the caller's
  buffer.
- **Per-instance hardware resources** (e.g. trace IDs, DMA descriptors,
  hardware slot allocations): allocations must be released on device disable,
  driver unbind, CPU/hardware-offline events, and error paths inside enable
  functions.  Missing release on any path is `[BUG]` — leaking these corrupts
  shared hardware state (e.g. duplicate trace IDs corrupt a trace stream;
  unreleased DMA channels block other users).
- **Active session teardown before device unregistration**: if a driver manages
  a software session (trace session, DMA transfer, ring buffer) that holds
  per-CPU pointers or other references to device objects, the driver's
  `.remove()` / unbind callback **must** tear down any active session and
  release all per-CPU software state **before** calling `device_unregister()` or
  equivalent.  Failing to do so leaves per-CPU pointers pointing into freed
  `cdev`/`csdev`/struct objects after the device is released; any later access
  (from a PM notifier, an idle callback, or a CPU hotplug callback) causes a
  use-after-free.  Flag as `[BUG]` when a remove path calls `device_unregister()`
  without first ensuring that all per-CPU references to device-owned data are
  cleared.  The check applies even when `devm_*` helpers are used for hardware
  resources — software session state is not managed by `devm_`.
- **Queued work before resource teardown**: if probe/init schedules work or an
  async completion can queue work that dereferences device resources, `.remove()`
  and error unwind must call `cancel_work_sync()` / `cancel_delayed_work_sync()`
  before tearing down those resources (`regmap_exit()`, buffer free, IRQ free,
  transport unregister).  `devm_*` cleanup does not cancel ordinary work items.
- **regmap_init / regmap_exit pairing**: prefer `devm_regmap_init*()` so the
  regmap is destroyed in devres unwind order alongside its sibling resources.
  When bare `regmap_init()` is used, `.remove()` MUST do all of the following
  **before** calling `regmap_exit()`:
    1. `cancel_work_sync()` every work item that may dereference the regmap
       (e.g. PDR-up notifier work, alert-driven init work).
    2. Unregister every callback / client whose `.cb()` may invoke the
       regmap from another context (RPMSG callback, IRQ handler,
       transport-layer notifier).
    3. Drop any in-flight wait_for_completion paths bound to the regmap by
       signaling them and rejecting late responses.
  The same ordering applies to probe error paths.  Flag as `[BUG]` any
  bare-`regmap_init()` flow whose teardown calls `regmap_exit()` while a
  callback or work item that touches the regmap remains live — the late
  callback dereferences a freed regmap.
- **Idempotency governs severity assessment, not code design**: when
  assessing the severity of an asymmetric error-path release, idempotency
  of the allocator is a legitimate factor in the reviewer's Gate 2 harm
  analysis — if the allocator is idempotent the functional outcome is the
  same regardless of whether the release fires on a given path.  However,
  code authors must not skip a release call at design time because the
  allocator is idempotent: idempotency is an internal allocator invariant,
  not a caller contract.  These two uses of idempotency are distinct.
- **Disable path must be read before filing a resource-leak finding**: for
  any subsystem-specific logical resource (trace IDs, reference counts,
  hardware slots), read the corresponding **disable / teardown path**
  before filing.  Two distinct scenarios must be handled differently:

  *Scenario A — Consistent omission (design intent)*: the disable path
  AND all error paths consistently omit the release — the subsystem
  intentionally keeps the resource allocated for post-session
  observability or similar reasons.  Verify this by reading the code:
  look for a comment, a consistent pattern across the subsystem, or a
  documented design decision.  Do not assume intentionality — an omission
  may also be a pre-existing bug.  When confirmed intentional, Gate 2
  (harm) fails; **dismiss the finding entirely** and document the design
  invariant as a positive note.  Do not file even a `[NIT]`.

  *Scenario B — Refactor-introduced asymmetry*: a refactor moved a
  release call from an outer function into an inner callback or helper,
  so one error path (e.g. the outer function when the callback never ran)
  no longer releases while another (e.g. the callback's own error path)
  still does.  The code previously released on all failure paths; after
  the refactor it no longer does on at least one.  This is a behavioral
  regression to an error path.  Apply the behavioral regression floor
  from the Gate Rules section: severity is **`[MINOR]`**, not `[NIT]`.
  The idempotency of the allocator (when present) makes the regression
  harmless in practice and rules out `[BUG]` or `[CONCERN]`, but does
  not reduce it below `[MINOR]`.

### 3f.3 Hardware Programming Sequence

Most hardware blocks require operations in a strict order documented in the
hardware specification.  Misordering causes undefined hardware behaviour that
is difficult to reproduce and debug.

- **Enable sequence**: confirm the patch follows the hardware's documented
  enable sequence (e.g. power-on → clock enable → reset deassertion →
  register initialisation → block enable — always verify against the
  hardware TRM; the actual sequence varies by IP block).  Verify the programming sequence
  against sibling drivers in the provided context files or against existing
  drivers for the same SoC or IP block visible in the diff.  If the correct
  sequence cannot be confirmed from available context, write `"programming
  sequence not verified — TRM not available in context"` in the Hardware
  Engineering Notes and do not file a finding.
- **Disable sequence**: disable must be the reverse of enable.  Stopping DMA
  before disabling interrupts, disabling the hardware block before ungating
  its clock, etc.
- **Reset handling**: hardware reset (via reset controller, register bit, or
  power cycle) must leave the device in a known state.  Confirm reset is
  asserted long enough per specification, and that the driver waits for reset
  completion before accessing registers.
- **Serialisation barriers**: `wmb()` / `rmb()` / `mb()` or `dma_wmb()` /
  `dma_rmb()` must be used where the hardware requires ordered writes or reads
  (e.g. writing a DMA descriptor before writing the doorbell register, reading
  a status register after writing an arm register).  Flag missing barriers on
  write sequences that arm hardware DMA or interrupts as `[CONCERN]`.
  **Architecture barrier semantics**: `writel` semantics vary by architecture
  — on some architectures it provides only a device write barrier, not a full
  `wmb()`.  For ordering between a descriptor write in DRAM and a hardware
  doorbell write, the correct portable pattern is `dma_wmb()` before the
  doorbell followed by `writel_relaxed()`.  Recommending a switch from
  `writel_relaxed` to `writel` alone is insufficient for this ordering
  requirement; do not suggest it as a fix without verifying the target
  architecture's barrier guarantees.

### 3f.4 Per-CPU and Hot-Pluggable Hardware

Per-CPU hardware devices (PMU counters, trace units, timers, watchdogs) have
lifecycle events tied to CPU hotplug.

- **CPU online check before access**: any function that accesses per-CPU
  hardware must be called on the owning CPU or with that CPU guaranteed online.
  `smp_call_function_single()` failure (CPU offline) must unwind all state
  symmetrically with the success path — including any resource allocations made
  before the call.  Flag as `[BUG]` if any resource is leaked on the failure
  path.
- **`this_cpu_*` means current CPU only**: `this_cpu_read/write/ptr()` is correct
  only when the state belongs to the CPU currently executing the code.  If a
  function takes a target CPU/device, runs from sysfs/ioctl/workqueue context, or
  can execute on a CPU different from the owner, require `per_cpu(var, cpu)`, an
  SMP call to the owner CPU, or another proven owner-CPU guarantee.  Flag `[BUG]`
  when the wrong CPU's per-CPU state can be read or modified.
- **smp_call_function_single() / smp_call_function_many() / on_each_cpu()
  for per-CPU software state — check return value**:
  when any of these SMP call variants is used not only to access hardware
  registers but also to write per-CPU *software* state (e.g. clearing a
  `DEFINE_PER_CPU` pointer inside the called function), the return value
  **must** be checked.  If the call fails (`-ENXIO`, CPU offline), the state
  written inside the called function never executes.  The caller must then
  clear that per-CPU state directly — typically via an explicit
  `per_cpu(var, cpu) = value` write, which is safe when the target CPU is
  offline.  Flag as `[BUG]` when:
  (a) the return value of the smp-call is ignored, **and**
  (b) the called function writes per-CPU software state that is later read by a
  PM notifier, idle callback, hotplug callback, or any path that runs after the
  target CPU returns online.  The classic failure chain: smp-call fails → per-CPU
  pointer not cleared → referenced object freed by subsequent teardown → CPU
  returns online → PM notifier reads stale pointer → use-after-free.
- **PM notifier / CPU idle callback pointer validity**: PM notifiers and CPU idle
  callbacks that dereference per-CPU pointers (e.g. `this_cpu_read(session_ptr)`)
  must be protected against stale pointers that can arise from two sources:
  (a) a prior `smp_call_function_single()` that failed to clear the pointer (see
  above), or (b) device removal without session teardown (§3f.2 above).  Verify
  that there is a clear ownership invariant: the per-CPU pointer must be
  explicitly nulled before the pointed-to object is freed on *every* code path —
  successful disable, failed SMP call, and driver `.remove()`.  An IRQ-disabled
  execution context (typical for PM notifiers) does not protect against a stale
  pointer that was set before IRQs were disabled on a previous execution of the
  owning CPU.  Flag as `[BUG]` if any of these nulling paths is missing.
- **sysfs / ioctl entry point guards**: sysfs store/show callbacks and ioctls
  that dispatch work to a specific CPU must handle the CPU going offline between
  the user-space call and the actual dispatch.  The correct patterns are:
  (a) hold `cpus_read_lock()` across the online check and the dispatch, or
  (b) call `smp_call_function_single()` directly and check its return value
  (`-ENXIO` means the CPU is offline — handle it gracefully).
  A bare `cpu_online()` check without `cpus_read_lock()` is racy — the CPU
  can go offline between the check and the dispatch — and must be flagged as
  `[CONCERN]`.
- **Hotplug callbacks**: new per-CPU functionality must register hotplug
  `.startup` and `.teardown` callbacks so hardware is properly initialised when
  a CPU comes online and quiesced before it goes offline.
- **Resource release on CPU offline**: resources tied to a specific CPU (IRQ
  affinities, hardware contexts, software-visible unique IDs) must be released
  in the `.teardown` callback before the CPU is marked offline.

### 3f.5 Interrupt and DMA Context Constraints

Hardware IRQ handlers and DMA completion callbacks run in hardirq or softirq
context.

- **Callback lock inheritance**: for IRQ, regmap, transport, notifier, and
  firmware callbacks, read the callback invocation site and record any lock held
  by the caller.  A callback must not re-acquire the same spinlock/mutex through
  a helper or sibling-client dispatch path; non-recursive lock recursion is a
  deadlock even when the callback body looks locally protected.
- **No sleeping APIs in atomic context**: `mutex_lock()`, `msleep()`,
  `schedule()`, `kzalloc(GFP_KERNEL)`, and any function that may sleep must
  not appear in any atomic context.  Atomic contexts include:
  hardirq handlers, softirq handlers, sections guarded by `spin_lock()`,
  `spin_lock_bh()`, or `spin_lock_irqsave()`, and sections with IRQs
  explicitly disabled via `local_irq_save()` or `local_irq_disable()`.
  Use `spin_lock_irqsave()` / `spin_unlock_irqrestore()` for data shared
  with process context.  Flag as `[BUG]` unconditionally — the two-part
  gate does not apply.
- **Clock enable/disable callbacks cannot sleep**: `clk_ops.enable` and
  `clk_ops.disable` run under the common clock framework enable lock, so use
  non-sleeping delays such as `udelay()` when a hardware poll/delay is required.
  Flag `usleep_range()` / `msleep()` in these callbacks as `[BUG]`; do not
  suggest replacing a correct `udelay()` there with a sleeping delay.  Sleeping
  delays belong in `prepare` / `unprepare` callbacks.
- **Threaded IRQ vs. hardirq boundary**: work requiring sleeping (regulator
  access, I2C reads, mutex-protected state) must be in the threaded handler
  (`IRQF_ONESHOT`), not the hardirq handler.
- **DMA coherency**: DMA buffers must use `dma_alloc_coherent()` for coherent
  allocations, or `dma_map_*` / `dma_unmap_*` pairs for streaming DMA on
  platforms without hardware cache coherency.  `dma_sync_*_for_device()` /
  `dma_sync_*_for_cpu()` is acceptable but lower-level; prefer the `dma_map_*`
  pairing pattern.  Confirm `dma_map_*` / `dma_unmap_*` calls are correctly
  paired and the CPU does not access the buffer while DMA is active.
- **Transfer-mode parity**: when a patch introduces a new resource, clock-rate,
  performance-vote, or ops-table abstraction for transfer setup, verify every
  transfer/execution mode the driver supports uses it consistently.  Search
  all alternative modes (not just the one the diff touches) for old helper
  calls.  A mode that still uses the old helper while the new platform
  requires the new abstraction is `[BUG]`, not `N/A`, if the platform can
  reach that mode.
- **IRQ handler state machine**: the IRQ handler must leave all shared state
  (buffer pointers, enable flags, error counters) consistent on both normal
  and error paths.  A partial update that leaves the state machine indeterminate
  is `[BUG]`.

### 3f.6 Hardware Topology and Bus Consistency

Drivers that operate within a larger hardware topology (bus hierarchies,
interconnects, pipelines) must maintain consistency with that topology.

- **Parent/child power ordering**: child devices must not be accessed before
  their parent bus or power domain is enabled.  Probe ordering that relies on
  implicit bring-up order rather than `devm_*` or `pm_runtime` is fragile.
- **Probe ordering and deferred probe**: if the driver depends on another
  device (clock provider, PHY, power domain, IOMMU), confirm it returns
  `-EPROBE_DEFER` when that dependency is not yet available, rather than
  failing permanently or assuming the dependency is always present.  Prefer
  `return dev_err_probe(dev, ret, "...")` over a bare `return -EPROBE_DEFER`
  — it logs the deferral reason when `ret == -EPROBE_DEFER` and is a no-op
  otherwise, keeping error paths clean.
- **Bus address and size correctness**: new register offsets, DMA address
  ranges, or interrupt specifiers must be consistent with the hardware address
  map and with existing drivers for the same SoC or IP block.
- **Unique hardware IDs**: hardware identifiers (DMA channel numbers, IRQ
  lines, trace IDs, hardware slot numbers) must be unique within their scope
  and allocated through the subsystem's allocator, not hard-coded.
- **`EXPORT_SYMBOL` vs `EXPORT_SYMBOL_GPL`**: symbols exported from a driver
  for use by other kernel modules should use `EXPORT_SYMBOL_GPL` unless the
  API is intentionally available to out-of-tree or proprietary modules.
  Using `EXPORT_SYMBOL` for a new kernel-internal API is `[CONCERN]`.
