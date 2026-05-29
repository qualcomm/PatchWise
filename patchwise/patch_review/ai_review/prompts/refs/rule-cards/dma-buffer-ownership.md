# Rule: dma-buffer-ownership

## Trigger

C code changes DMA mapping/unmapping, coherent/streaming allocation, or pairs a
DMA/buffer type tag (`SNDRV_DMA_TYPE_*`, `DMA_*_DEVICE`, `VB2_MEMORY_*`,
`V4L2_*_TYPE_*`) with an allocation/mapping API.

## Must Check

- Is every `dma_map_*` result checked with `dma_mapping_error()` before use?
- Do unmap calls match the original device, direction, and length of the map?
- Is a coherent allocation (`dma_alloc_coherent`) freed with the coherent counterpart, not a streaming unmap, and vice-versa?
- Does the declared type tag match the allocation API's contract (e.g. `SNDRV_DMA_TYPE_CONTINUOUS` vs `dma_alloc_coherent` page semantics) so userspace mmap maps the right physical pages?
- Is buffer ownership transferred to the device before access and back to the CPU before CPU reads?

## Evidence Needed

- The map/alloc call, its paired unmap/free, and the device/direction/length used.
- The type-tag declaration and the allocation API it is paired with.

## Safe Dismissal

Dismiss when map results are error-checked, unmap parameters match, and the type
tag and allocator agree per source.

## Finding Template

```text
[BUG] DMA mapping/ownership or type-tag mismatch
File: <path>:<line>
Rule: dma-buffer-ownership
Evidence: <map/alloc + unmap/free params or tag vs API>
Reasoning: <unchecked map, mismatched unmap, or tag/API contract break>
Impact: <DMA into wrong/freed memory, IOMMU fault, mmap of wrong pages, corruption>
Suggestion: <add dma_mapping_error check, match unmap params, align tag with allocator>
```

## Severity

`[BUG]` for memory corruption / wrong-page exposure; `[CONCERN]` when the
mismatch is plausible but the consuming path is not fully proven.
