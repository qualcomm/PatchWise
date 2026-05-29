### 3f.3 Hardware Programming Sequence

Most hardware blocks require a strict order; do not invent a finding when the
necessary hardware sequence is unavailable in context.

- **Enable sequence:** verify power-on → clock enable → reset deassertion →
  register initialization → block enable against TRM/context/sibling drivers.
  Actual order varies by IP. If not confirmable, write
  `programming sequence not verified — TRM not available in context` in Hardware
  Engineering Notes and do not file a finding.
- **Disable sequence:** disable in reverse order; e.g. stop DMA before disabling
  IRQs and keep clocks available until hardware is quiesced.
- **Recovery-before-publication:** recovery paths must quiesce/reset hardware
  before publishing completed fences, retiring hung work, freeing BOs, or waking
  userspace that may unmap buffers still visible to the device. A software fence
  update before hardware recovery is not safe merely because retire happens later.
- **Moving hardware progress:** if hardware can update shared fence/progress memory
  while crash capture or recovery analysis runs, snapshot under a quiesced state
  or avoid synthetic increments based on the moving value. Double-incrementing a
  live fence can retire unexecuted work.
- **Reset handling:** assert reset long enough, wait for completion, and access
  registers only after the device is in a known state.
- **Serialization barriers:** use `wmb()`/`rmb()`/`mb()` or `dma_wmb()`/`dma_rmb()`
  where hardware needs ordered descriptor/status writes/reads. Missing barriers
  on sequences arming DMA or interrupts are `[CONCERN]`.
- **Architecture barrier semantics:** `writel` may not be a full `wmb()` on every
  architecture. For DRAM descriptor writes followed by doorbell MMIO, the
  portable pattern is `dma_wmb()` then `writel_relaxed()`. Do not suggest
  replacing `writel_relaxed()` with `writel()` alone without proving the target
  architecture's barrier guarantee.
