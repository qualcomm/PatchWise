## Qualcomm SCM Memory Assignment Checklist

Trigger this checklist when a patch uses `qcom_scm_assign_mem()`, changes
VMID ownership, or describes secure/non-HLOS/TrustZone/SMMU DMA sharing.

Reviewer must verify and state the evidence for each item:

1. **Physical address**: every address passed to `qcom_scm_assign_mem()` is a
   physical address for the backing pages, not an IOVA, DMA API bus address, or
   value with SID bits ORed in. If the device has `iommus`, do not assume
   `dma_buffer.addr` is physical.
2. **Full region coverage**: the SCM-assigned size covers the complete
   allocation and every hardware-visible subregion, including padding,
   workaround pages, position buffers, metadata, and fragment buffers.
3. **Per-buffer state**: assignment state is scoped to the actual allocated
   buffer/substream/graph/compress stream. Component-global state is acceptable
   only when the code proves a single live buffer per state slot.
4. **Mode parity**: all buffer users supported by the driver are covered:
   playback, capture, compress, mmap/copy paths, push-pull mode, and any
   alternate graph or fragment allocation path.
5. **Failed unassign safety**: if SCM revoke/unassign fails, the driver must
   prevent normal free/reuse of the affected memory, or explicitly quarantine or
   leak it. Logging, comments, or best-effort retry alone are not sufficient.
6. **DT value space**: any VMID DT binding limit must match the architectural or
   documented VMID value space, not only the current Linux owner-mask
   implementation. Cross-check `include/dt-bindings/firmware/qcom,scm.h` when
   available.

Severity guide: a physical/IOVA mix-up, incomplete secure grant, or failed
unassign that can lead to freed memory retaining non-HLOS access is a blocker
unless the patch proves the path is unreachable or safely quarantined.
