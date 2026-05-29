# Rule: qcom-scm-vmid-memory-assignment

## Trigger

Use this card when a patch changes Qualcomm secure memory ownership or VMID
assignment, including `qcom_scm_assign_mem()`, `QCOM_SCM_VMID_*`, `qcom,vmid`,
TrustZone/non-HLOS/SMMU language, GPR/APM/audio DSP memory assignment, or
secure-DMA ownership transfer.

## Must Check

- Is the address passed to SCM in the namespace the API expects, normally a
  physical address rather than an IOVA or unrelated DMA address?
- Does the assigned range cover the whole allocation and every firmware-visible
  subregion, including offsets, alignment, and page rounding?
- Is assignment state scoped to the real lifetime owner: buffer, substream,
  graph, stream, device instance, or shared object?
- Do all supported data paths use symmetric assignment and unassignment, such as
  PCM, compress, mmap/copy, push-pull, or graph-specific modes?
- Do partial setup failures restore ownership before memory can be freed,
  reused, or reassigned?
- If unassign fails, does the code avoid treating the memory as safely returned
  to the original owner?
- Are repeated prepare/free or bind/unbind paths idempotent and race-safe?

## Evidence Needed

- Allocation site and address values stored for the buffer or region.
- Call sites for `qcom_scm_assign_mem()` or wrappers.
- Free/unprepare/error paths for the same memory.
- Per-instance state fields or refcounts controlling assignment.
- Mode-specific paths that can reach the same memory.
- Binding or DT properties that provide VMID/domain values, if present.

## Safe Dismissal

Dismiss only when the packet proves the address namespace is correct, the whole
range is covered, lifetime state is per owner or safely refcounted, all modes
are symmetric, and failure paths prevent unsafe reuse after failed unassign.

## Finding Template

```text
[BUG] Unsafe Qualcomm SCM memory assignment lifetime
File: <path>:<line-or-function>
Rule: qcom-scm-vmid-memory-assignment
Evidence: <changed assignment/unassignment/address/range code>
Reasoning: <which must-check fails and why>
Impact: <secure-world access, stale ownership, memory corruption, or security risk>
Suggestion: <fix ownership, address namespace, range, mode coverage, or rollback>
```

## Severity

Default to `[BUG]` for confirmed wrong address namespace, incomplete range,
unsafe ownership reuse, or failed-unassign reuse. Use `[CONCERN]` when the
packet lacks enough context but shows a credible uncovered ownership path.
