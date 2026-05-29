<!-- Conditional fragment of code-logic.md — the diff shows on-wire/protocol struct patterns in the diff (__le32/__be32/dma_addr_t/
skb_/__packed/firmware load/IPC/RPMSG/SPI/I2C). Apply on top of
refs/code-logic.md §3c.2 Data-Flow Picture base prose. -->

#### Wire protocol struct checklist

Apply when code sends a C struct to firmware, hardware, another processor, USB,
I2C, SPI, GLINK, RPMSG, or any packed/on-wire protocol.
- Stack protocol structs with reserved members, padding, or fields not assigned
  on every path must be zero-initialized (`= {}`, `= {0}`, or `memset()`) before
  field assignment.
- Enumerate every transmitted member from the struct definition, not only diff
  fields; omitted members must be intentionally zero/reserved or assigned by a
  helper before send.
- New opcode/property/packet/switch cases require full wire-contract proof: body
  payload written or explicitly zero-payload, selector type matches encoder/
  firmware/transport expectations, header size/property count/trailing length
  accounting updated, and sibling implementations do not prove a different
  contract. Accepting a new constant with no payload or size update is a defect.
  For `packet_builder_payload_accounting`, name the emitted payload fields, the
  size/count variables updated, and any sibling encoder that proves the expected
  body shape; missing payload or accounting for a newly accepted case is `[BUG]`
  unless the protocol source explicitly defines a zero-payload trigger.
- Private state allocation contract: when retained driver/private state is
  initialized then written through later (`priv`, `ctx`, `drvdata`, flexible
  tail storage, per-instance opaque data), prove the allocation size matches the
  concrete struct written through it (`sizeof(*ptr)`, `struct_size()`, or a named
  private-size field) and that the pointer is non-NULL before first write. File
  `[BUG]` for writes through undersized, unallocated, or wrong-type private
  storage; dismiss only with allocation-site and first-write proof.
- Partial-init read after `_kmalloc()` / moved initialization: when state comes
  from a non-zeroing allocator (`kmalloc`, `devm_kmalloc`, `kmalloc_array`) or a
  `switch`/`if` that assigns fields only on some arms, prove every member read
  later is written on all reachable arms. A `default:`/fall-through arm that skips
  a field, then a later `if (!ptr->field)` or field dereference, reads
  uninitialized heap. This is the common failure mode when initialization is moved
  out of an `_kzalloc()` site or from an init function into a per-version/runtime
  setter. File `[BUG]` for the first reachable uninitialized read; the fix is
  `devm_kzalloc()`/`= {}` or an explicit default arm. Dismiss only by proving every
  arm initializes the read members or the read is unreachable for the unset arm.
- Kernel-API structs, not only on-wire: any stack struct passed by pointer to a
  kernel API that may read unset fields (e.g. `struct dev_pm_domain_attach_data`,
  `struct of_phandle_args`, config/attach descriptors to `_get()`/`_attach()`/
  `_register()` helpers) must be zero-initialized before partial assignment.
  File `[CONCERN]`, or `[BUG]` when a garbage field is known to change behavior.
  The validator check `stack_struct_zero_init_source_aware` enforces this class.
