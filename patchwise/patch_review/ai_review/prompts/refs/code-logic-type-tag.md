<!-- Conditional fragment of code-logic.md — the diff shows API type-tag / allocation-API mismatches (DMA type tags, buffer-class
flags paired with allocation API). Apply on top of refs/code-logic.md §3c.2
Data-Flow Picture base prose. -->

#### API type-tag consistency checklist

Apply when a patch declares a resource type constant, buffer type flag, or
memory-class tag and separately calls an allocation/mapping/registration API
whose contract implies a specific type.

**Bad-pattern shape:**

    /* Declaration says one type... */
    snd_pcm_set_managed_buffer_all(pcm, SNDRV_DMA_TYPE_CONTINUOUS, ...);

    /* ...but allocation uses a different API contract */
    buf->area = dma_alloc_coherent(dev, size, &buf->addr, GFP_KERNEL);
    /* SNDRV_DMA_TYPE_CONTINUOUS means virt_to_phys pages; dma_alloc_coherent
       returns DMA-coherent memory needing SNDRV_DMA_TYPE_DEV */

The mismatch causes: wrong `mmap` path (userspace maps physical pages that
aren't the DMA buffer), silent data corruption, or kernel page-table confusion.

**Decisive evidence (all three required):**
(1) the type-tag declaration site (quote the constant and the API it's passed to);
(2) the allocation/mapping site (quote the function and its return semantics);
(3) the framework's documented contract for each type constant (name the source
— e.g. `Documentation/sound/kernel-api/writing-an-alsa-driver.rst`,
`include/sound/pcm.h`, `include/linux/dma-mapping.h`).

**Valid dismissal proofs:**
- the type tag matches the allocation API's semantics (e.g.
  `SNDRV_DMA_TYPE_DEV` with `dma_alloc_coherent`, or `SNDRV_DMA_TYPE_VMALLOC`
  with `vmalloc`) — quote both and the framework header that defines the mapping;
- the buffer is pre-allocated by the framework itself (e.g. `snd_pcm_set_managed_buffer`
  handles allocation internally, so the driver never calls `dma_alloc_*` directly)
  — quote the framework call that proves driver-side allocation is absent;
- a platform-specific DMA ops override makes the type tag irrelevant (quote the
  override registration).

**Disqualified dismissals:**
- "it works on our hardware" — correctness depends on the kernel mmap path
  selected by the type tag, which may differ across architectures and configs;
- "the buffer is coherent either way" — coherency and type-tag mmap routing are
  orthogonal; a coherent buffer with the wrong type tag still gets the wrong
  mmap implementation;
- "same as existing driver" without quoting the existing driver's matching
  type+allocation pair;
- "the framework ignores the type for managed buffers" without quoting the
  framework source that proves this.

Severity: `[BUG]` when the mismatch causes user-visible mmap of wrong physical
pages (security/data-corruption); `[CONCERN]` when the mismatch is between
logically-compatible types but violates the documented contract.
