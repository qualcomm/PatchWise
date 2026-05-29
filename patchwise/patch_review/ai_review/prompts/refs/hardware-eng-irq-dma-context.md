### 3f.5 Interrupt and DMA Context Constraints

IRQ handlers and DMA completions run in hardirq/softirq or similarly constrained
contexts.

- **Callback lock inheritance:** for IRQ, regmap, transport, notifier, and
  firmware callbacks, read the invocation site and record locks held by the
  caller. A callback must not re-acquire the same spinlock/mutex through a helper
  or sibling-client dispatch path; non-recursive lock recursion deadlocks.
- **No sleeping APIs in atomic context:** `mutex_lock()`, `msleep()`, `schedule()`,
  `kzalloc(GFP_KERNEL)`, or any sleeper must not run in hardirq, softirq,
  `spin_lock*()`, `spin_lock_bh()`, `spin_lock_irqsave()`, `local_irq_save()`, or
  `local_irq_disable()` context. Use `spin_lock_irqsave()` for data shared with
  process context. Flag `[BUG]` unconditionally — the two-part gate does not
  apply.
- **Clock enable/disable callbacks cannot sleep:** `clk_ops.enable` and
  `clk_ops.disable` run under the CCF enable lock; use `udelay()` for required
  non-sleeping polls/delays. Flag `usleep_range()`/`msleep()` there as `[BUG]`;
  sleeping delays belong in `prepare`/`unprepare`. Do not replace correct
  `udelay()` with a sleeping delay.
- **Threaded IRQ vs. hardirq boundary:** work requiring sleep, such as regulators, I2C, or
  mutex-protected state, belongs in a threaded handler with `IRQF_ONESHOT`, not
  the hardirq handler. Disable/free IRQs before freeing buffers, register blocks,
  or state reachable from the handler; prove no threaded handler remains in flight.
- **DMA mapping contract:** for streaming DMA, require a valid DMA/coherent mask
  where needed, check `dma_mapping_error()` after every `dma_map_*`, unmap with
  the same device, direction, address, and length, and do not free/reuse buffers
  until the device no longer owns them. Missing mapping-error checks or ownership
  violations are `[BUG]` when reachable.
- **DMA coherency:** use `dma_alloc_coherent()` for coherent buffers or paired
  `dma_map_*`/`dma_unmap_*` for streaming DMA; `dma_sync_*_for_device()` /
  `dma_sync_*_for_cpu()` is acceptable but lower-level. Confirm direction/length
  pairing and that CPU does not access buffers while DMA owns them.
- **Transfer-mode parity:** when a patch introduces a resource, clock-rate,
  performance-vote, or ops-table abstraction for transfer setup, search every
  transfer/execution mode, not just the touched mode. A reachable mode still
  using an old helper while the new platform requires the new abstraction is
  `[BUG]`, not `N/A`.
- **IRQ handler state machine:** normal and error paths must leave shared buffer
  pointers, enable flags, and counters consistent; partial updates are `[BUG]`.
- **Partial IRQ-status-clear:** when an IRQ handler reads a multi-bit status
  register and writes back an acknowledgement/clear value, prove the handler
  clears ALL asserted bits that can source the interrupt line, not only the
  subset it explicitly handles.

  **Bad-pattern shape:**

      status = readl(dev->base + IRQ_STATUS);
      /* handler processes only bits it recognises */
      handled = status & (BIT_A | BIT_B | BIT_C);
      writel(handled, dev->base + IRQ_CLEAR);
      /* bits D, E remain asserted → level-triggered IRQ re-fires immediately */

  Level-triggered interrupt lines remain asserted as long as ANY source bit is
  set. If the clear write omits bits the hardware can assert, the IRQ re-fires
  the instant the handler returns — infinite storm, soft lockup, watchdog.

  **Decisive evidence (all three required):**
  (1) the status-read site (quote the register name and which bits it can
  assert — check the register definition or mask constant);
  (2) the clear/acknowledge-write site (quote the value written);
  (3) comparison: are there assertable bits NOT covered by the clear mask?

  **Valid dismissal proofs:**
  - the clear write uses the full status value read (`writel(status, CLEAR)`) —
    all asserted bits are cleared regardless of which the handler processed;
  - unhandled bits are masked at the hardware level before reaching the status
    register (quote the mask-enable register and its programming site);
  - the interrupt is edge-triggered, not level (quote the trigger type in the
    IRQ request or DT binding — `IRQ_TYPE_EDGE_*` / `IRQF_TRIGGER_*`);
  - a separate "catch-all" clear after the switch/if chain writes the full
    status (quote it).

  **Disqualified dismissals:**
  - "only known bits are handled" — level-triggered lines don't care which bits
    the software knows about; uncleared asserted bits re-fire;
  - "the other bits can't assert in practice" without quoting the hardware
    mask-enable register that prevents them;
  - "a tasklet/workqueue handles the rest" without quoting the deferred
    clear/mask that silences the line before the handler returns;
  - "same as existing driver" without quoting the existing driver's full-clear
    site.

  Severity: `[BUG]` when the clear mask provably omits bits the hardware can
  assert (deterministic infinite storm); `[CONCERN]` when the assertable-bit
  set is unclear from context but the handler clears only a strict subset.
- **Runtime PM status lifetime:** keep runtime-PM references and the relevant lock
  held until every status bit used for watchdog, IRQ re-enable, or hardware error
  decisions has been read and acted on. Dropping the PM reference before consuming
  the status can race autosuspend/resume paths that clear or reprogram it.
- **Level-triggered IRQ re-enable:** if an IRQ thread exits early because runtime
  PM, device state, or readiness checks fail, it must clear the asserted hardware
  source or leave the interrupt masked before `enable_irq()`. Re-enabling a level
  IRQ with the source still asserted can create an interrupt storm.
- **Interrupt mask preservation:** when masking error IRQs for test or recovery,
  preserve non-error forward-progress interrupts such as software/preemption/
  completion IRQs. Do not copy a restrictive mask between hardware generations
  without confirming all required control interrupts remain enabled.
