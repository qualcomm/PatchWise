<!-- Conditional fragment of code-logic.md — the diff shows allocator/loader/registration calls in the diff (devm_*/kmalloc/kzalloc/
request_irq/dma_alloc/qcom_mdt_pas_load and similar). Apply on top of
refs/code-logic.md §3c.2 Data-Flow Picture base prose. -->

#### API alloc/release-pairing contract checklist

Apply when a changed function calls an allocator/loader/helper whose kdoc,
header, or implementation requires a later release, put, free, or cleanup.
Reading that contract is mandatory before clearing the call.
- Qualcomm PAS metadata: `qcom_scm_pas_init_image()` / `qcom_mdt_pas_load()`
  allocate firmware metadata that must be released with
  `qcom_scm_pas_metadata_release()` after authentication. A load path without
  that release leaks on every load; file `[BUG]`. The validator check
  `pas_metadata_release_source_aware` enforces this.
- `devm_*` on repeatable paths: devres lifetime is the device, not an operation.
  If `devm_*` allocation can run repeatedly for one long-lived device
  (open/close, firmware reload, recovery, stream restart), state whether it is
  one-shot; if repeatable, file `[BUG]` for cumulative allocation.
- General ownership: for any `*_alloc`/`*_get`/`*_load`/`*_init_*` with a named
  counterpart, trace every success/error exit and confirm exactly one release per
  acquisition. Cite the kdoc/source line; do not infer "no release needed" from
  call-site shape alone.
- Managed vs manual cleanup: `devm_*`, managed device links, auto-remove links,
  and framework-managed registrations have API-specific teardown rules. Do not
  pair them with manual remove/delete calls unless the API contract says the
  exact object state is manually removable.
