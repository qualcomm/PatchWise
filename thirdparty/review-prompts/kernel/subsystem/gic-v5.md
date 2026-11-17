# GICv5 Subsystem Details

This guide covers invariants and bug patterns for GICv5: the host irqchip
driver (`drivers/irqchip/irq-gic-v5*.c`), the shared register and table
definitions (`include/linux/irqchip/arm-gic-v5.h`), and the KVM GICv5 virtual
interrupt controller (`arch/arm64/kvm/vgic/vgic-v5.c`,
`arch/arm64/kvm/hyp/vgic-v5-sr.c`). It is derived from the merged upstream
implementation, its fix history, and the Arm Generic Interrupt Controller
Architecture Specification, GICv5 (ARM IHI 111701).

GICv5 is a redesign, not GICv3 with additions. The single most productive
source of both missed bugs and false reports in this area is a reviewer
applying GICv3 reasoning to GICv5 code, so the first section is devoted to the
assumptions that do not carry over. For GICv3/v4 (including a GICv3 guest
running in compatibility mode on GICv5 hardware) see `gic-v3.md`; for the
generic KVM/arm64 rules that the VGIC shares with the rest of KVM, including
the existing VGIC CPU interface, LPI/vLPI and `ICH_HCR_EL2` trap-ordering
sections, see `kvm-arm64.md`.

The GICv5 code is young and still growing. Where this guide says an interface
"does not exist yet", verify against the target tree's own code rather than
assuming: the rule is about the shape the code must have, not about a snapshot
of which files are present.

## GICv3 Assumptions That Do Not Hold

Reasoning about GICv5 by analogy with GICv3 produces two failure modes that are
equally expensive: a real defect is waved through because the v3 mental model
says the code looks right, and a correct construct is reported as a bug because
it does not look like its v3 counterpart.

> Applying the v3 model to v5 code causes **missed completion and ordering
> bugs** (the barrier idioms are different), **spurious reports against correct
> code** (the structures are owned differently), and **wrong fixes accepted into
> the tree** (a v3-shaped remedy applied to a v5 mechanism).

*   **There is no Distributor and no Redistributor.** A GICv5 system is one or
    more Interrupt Routing Services (IRS), zero or more Interrupt Translation
    Services (ITS), and zero or more Interrupt Wire Bridges (IWB). SPI
    configuration is per-IRS and is reached through a select-then-program
    register discipline, not through a single global `GICD_*` window. Each SPI
    is owned by exactly one IRS; `gicv5_irs_lookup_by_spi_id()` in
    `drivers/irqchip/irq-gic-v5-irs.c` is the lookup, and it returns `NULL` for
    an SPI no IRS claims.
*   **PPI state and configuration live in the CPU interface, as system
    registers.** The `ICC_PPI_*_EL1` family (enable, pending, active, handling
    mode, priority) replaces the per-PE `GICR_*` MMIO region, with `ICV_PPI_*`
    as the guest view and `ICH_PPI_*_EL2` as the EL2 view. Consequently EL2
    mediation of PPIs is sysreg trapping, and world switch is a sysreg walk
    (`__vgic_v5_save_ppi_state()` / `__vgic_v5_restore_ppi_state()` in
    `arch/arm64/kvm/hyp/vgic-v5-sr.c`), not an MMIO copy.
*   **There are no list registers on the native path.** Native GICv5
    virtualization uses memory-backed VM and VPE structures walked by the IRS,
    direct virtual injection (DVI) for PPIs, and doorbells for a non-resident
    VPE. `ICH_LR<n>_EL2` exists only under the GICv3 legacy extension (see
    "GICv3 Legacy Compatibility" below).
*   **The ITS has no command queue.** Configuration is a plain memory write to
    an in-memory table entry followed by a register-driven cache invalidation.
    There is no `MAPD`/`MAPTI`/`INV`/`SYNC` command ring, and no `DISCARD`: an
    unmap is a `VALID = 0` write plus an invalidate. Do not look for command
    construction, queue-wrap handling, or `GITS_CWRITER` analogues, and do not
    report their absence.
*   **`DSB` is not the completion primitive for a GIC system instruction; the
    GIC synchronization barrier is.** GICv5 configuration is no longer a memory
    store, so the GICv3 reflex of "write, then `DSB`, then read back" does not
    transfer. Only the GSB is defined to complete Interrupt Effects:
    `gsb_sys()` completes the Interrupt Effects of all prior GIC instructions,
    `gsb_ack()` completes only those of prior acknowledge (`GICR`)
    instructions. Both are defined in `arch/arm64/include/asm/barrier.h`. State
    this as "a `DSB` alone is not sufficient" rather than "a `DSB` does
    nothing": the architecture does order Interrupt Effects against a `DSB`,
    and a message-passing sequence generally needs the `DSB` on the writing
    side *and* the GSB on the reading side.
*   **There is no IRS cache-invalidate register.** The IRS is the sole writer of
    Interrupt State Table (IST) contents, so its primitive is a sync that drains
    accepted events (`gicv5_irs_syncr()`), never an invalidate. Only the ITS,
    which caches software-written translation tables, has invalidate registers.
    Reporting "the IRS equivalent of `GICR_INVLPIR` is missing" is a false
    positive.
*   **Priority is five bits at the CPU interface, and there is no binary
    point.** `ICC_IDR0_EL1.PRI_BITS` only ever reports 4 or 5 bits, the
    preemption/subpriority split of `ICC_BPR*_EL1` is gone, and the running
    priority is derived from a 32-bit active-priority bitmap (`ICC_APR_EL1`,
    `ICH_APR_EL2`) rather than a set of `APnR` registers. An IRS may implement
    fewer priority bits than the CPU interface (`IRS_IDR1.PRIORITY_BITS`,
    minimum 1), which is why `gicv5_init_common()` computes the usable width as
    `min_not_zero(cpuif_pri_bits, irs_pri_bits)`.

**REPORT as bugs:**
*   Code that reasons about GICv5 ordering from a `DSB` or from a
    read-back-after-write of an IRS/ITS register, where a GSB or a `*_STATUSR`
    poll is required.
*   A GICv5 change that adds a GICv3-shaped construct with no GICv5 basis (a
    command queue, an LPI configuration/pending table pair, a `GICD_CTLR.RWP`
    analogue), or a commit message that justifies GICv5 behaviour by citing
    GICv3 behaviour.

## Typed INTIDs and Type Dispatch

A GICv5 INTID is self-describing: bits [31:29] are the type and bits [23:0] are
an ID within that type's own namespace. The three namespaces are independent
and each is up to 24 bits wide, so the same numeric ID is a valid PPI, LPI and
SPI simultaneously.

> Confusing a full INTID with a bare hardware ID indexes the wrong element of a
> per-interrupt array, dispatches to the wrong irqdomain, or silently addresses
> a different interrupt. Type-checking without bounding the ID reads or writes
> past the end of a fixed-size array.

The encoding and its accessors are in `include/linux/irqchip/arm-gic-v5.h`:
`GICV5_HWIRQ_TYPE` is `GENMASK(31, 29)`, `GICV5_HWIRQ_ID` is `GENMASK(23, 0)`,
and the type values are `GICV5_HWIRQ_TYPE_PPI` (`0x1`), `_LPI` (`0x2`) and
`_SPI` (`0x3`). Note that the type occupies bits [31:29], not the top nibble.
KVM's constructors and accessors are in `include/kvm/arm_vgic.h`
(`vgic_v5_make_ppi()`, `vgic_v5_get_hwirq_id()` and friends).

*   **Dispatch on the type, index on the ID.** `handle_irq_per_domain()` in
    `drivers/irqchip/irq-gic-v5.c` is the canonical shape: extract the type to
    pick the irqdomain, extract the ID to pass as the hwirq. A function that
    receives a full INTID and uses it directly as an array index or a bit
    position is wrong even when the array is large enough, because the type
    bits make every ID enormous.
*   **A GICv5 type predicate is not a bounds check.** In `include/kvm/arm_vgic.h`
    the GICv5 arm of `__irq_is_ppi()` is `is_v5_type(GICV5_HWIRQ_TYPE_PPI, i)`,
    which tests the type field and nothing else. The GICv3 arm, by contrast,
    tests a numeric range and therefore does bound the value. Any caller that
    uses a PPI predicate to decide it may index a `VGIC_V5_NR_PRIVATE_IRQS`-sized
    array must check the hardware ID against that bound itself. Clamping with
    `array_index_nospec()` is not a substitute: it converts an out-of-range ID
    into a valid index for a different interrupt rather than rejecting it.
*   **GICv5 has no SGIs.** `__irq_is_sgi()` returns `false` unconditionally for
    the GICv5 model; inter-processor interrupts are LPIs allocated out of the
    LPI domain (`gicv5_irq_ipi_domain_alloc()`, `GICV5_IPIS_PER_CPU`). Code that
    omits an SGI case in a GICv5 path is correct, and a report that GICv5 "does
    not handle SGIs" is a false positive.
*   **KVM supports 64 PPIs, deliberately.** `VGIC_V5_NR_PRIVATE_IRQS` is 64,
    covering the architected PPIs only, and
    `BUILD_BUG_ON(VGIC_V5_NR_PRIVATE_IRQS != 64)` in
    `__vgic_v5_save_ppi_state()` pins the assumption. The upper bank
    (`ICH_PPI_*1_EL2`, `ICH_PPI_PRIORITYR8..15_EL2`) is written to zero on
    restore rather than being carried. Support for the 64 IMPLEMENTATION
    DEFINED PPIs above that was removed on purpose because it could not be
    tested; do not report the zero writes as lost state, and treat a patch that
    reintroduces 128-PPI handling as needing an explicit justification.

**REPORT as bugs:**
*   Passing a full typed INTID where a hardware ID is expected, or vice versa,
    across a function boundary. The tell is a value produced by
    `vgic_v5_make_*()` or read from an acknowledge reaching an array index, a
    bitmap position, or a `*_SELR` register field without a
    `vgic_v5_get_hwirq_id()` / `FIELD_GET(GICV5_HWIRQ_ID, ...)` in between.
*   A new consumer of `__irq_is_ppi()` / `irq_is_ppi()` on the GICv5 model that
    indexes private-interrupt state without independently bounding the hardware
    ID.

## System Instructions, GSB, and Context Synchronization

GICv5 configuration and state changes are issued as `GIC`/`GICR` system
instructions rather than MMIO writes, and they complete asynchronously with
respect to the instruction stream. Two different barriers are needed for two
different questions, and neither substitutes for the other.

> Missing completion means a disable does not take effect before the code that
> depends on it runs, which breaks the lazy-disable contract and delivers
> interrupts the driver believes it has masked. Missing context synchronization
> means a subsequent instruction reads a stale system register, so a
> configuration query returns the previous query's answer.

*   **GSB completes GIC-instruction effects; ISB synchronizes the instruction
    stream.** `gsb_sys()` and `gsb_ack()` guarantee that the Interrupt Effects
    of prior GIC instructions have completed and prevent later loads, stores
    and GIC instructions from starting early. They are not context
    synchronization events. A result deposited in a system register by an
    instruction, or a direct write to a `ICC_PPI_*` register, still needs an
    `isb()` before the following instruction can rely on it.
*   **The GICv5 self-synchronizing register list is short, and it is not the
    GICv3 one.** GICv5 system registers otherwise follow the generic
    architectural rule that a direct write needs a context synchronization
    event before software can rely on its effect on later instructions. The
    architecture carves out exactly three registers as self-synchronizing:
    `ICC_PCR_EL3`, `ICC_PCR_EL1` and `ICV_PCR_EL1`. Nothing else is on that
    list — in particular `ICH_VMCR_EL2` and `ICH_APR_EL2` are not, so a
    hypervisor writing either and then relying on the new value in subsequent
    instructions needs an `isb()`. Do not carry the GICv3 exceptions across:
    that list (`ICC_PMR_EL1`, the `ICC_IAR*` reads) is a different list for a
    different architecture. Note also that `ICH_VMCR_EL2.VPMR` being an alias
    of `ICV_PCR_EL1.Priority` does not transfer the property — the carve-out is
    granted to a direct write to `ICV_PCR_EL1`, and a write to `ICH_VMCR_EL2`
    is not one.

    What the architecture does *not* settle is the narrower question of whether
    the virtual CPU interface itself observes such a write before the
    synchronization event. Do not assert either answer in review.
*   **Disabling needs completion; enabling does not.** The architecture
    guarantees that the effects of a GIC system instruction complete in finite
    time, which is all that is required when unmasking. Masking is different,
    because the lazy-disable mechanism assumes the interrupt really is masked
    when `irq_mask()` returns. In `drivers/irqchip/irq-gic-v5.c`,
    `gicv5_iri_irq_mask()` issues `GIC CDDIS` followed by `gsb_sys()` while
    `gicv5_iri_irq_unmask()` issues `GIC CDEN` with no barrier, and both carry
    a comment naming the rule they rest on.
*   **The finite-time guarantee covers GIC instructions, not direct writes to
    PPI system registers, so the PPI paths are symmetric where the IRI paths
    are not.** This is the trap: the asymmetry above rests on a guarantee that
    does not extend to a `ICC_PPI_*` write, whose effects are explicitly *not*
    guaranteed to complete in finite time without explicit synchronization.
    That is why `gicv5_ppi_irq_mask()` and `gicv5_ppi_irq_unmask()` both end in
    `isb()` — not because the enable also completes in finite time, but because
    neither direction does on its own. Reasoning "an enable is fine without a
    barrier" from the IRI path to the PPI path is therefore wrong, and a PPI
    unmask that drops its `isb()` is a real finding (a core can go to idle with
    the write still in flight).

    ```c
    /* CORRECT: an IRI disable is completed, an IRI enable need not be */
    gic_insn(cddis, CDDIS);
    gsb_sys();
    ...
    gic_insn(cden, CDEN);

    /* WRONG: DSB does not complete a GIC instruction's effects */
    gic_insn(cddis, CDDIS);
    dsb(sy);
    ```
*   **A configuration query needs an ISB before its result is read.** The
    `GIC CDRCFG` instruction deposits its answer in `ICC_ICSR_EL1`, so the
    sequence is instruction, `isb()`, then read.
    `gicv5_iri_irq_get_irqchip_state()` does exactly this, and then checks
    `ICC_ICSR_EL1.F` before trusting the Pending and Active fields.
*   **Configuration of an unreachable INTID fails silently.** An INTID that is
    not implemented, not in the current domain, or not provisioned produces no
    effect and raises no fault. `GIC CDRCFG` reporting `ICC_ICSR_EL1.F` is the
    only way to discover it. A code path that programs an interrupt whose
    reachability is not otherwise established, and does not read back, will
    lose the configuration with no diagnostic. Conversely, do not report a
    missing error check on `CDEN`/`CDDIS`/`CDPRI`/`CDAFF`: those instructions
    have no status output to check.

**REPORT as bugs:**
*   A GIC system instruction whose effect a subsequent access depends on, with
    no `gsb_sys()`/`gsb_ack()` between them, or with a `DSB` used in place of
    one.
*   A read of `ICC_ICSR_EL1` (or any system register written as the result of a
    GIC instruction) without an intervening `isb()`.
*   An `irq_mask()` implementation that returns without completing the disable.

## Acknowledge, Priority Drop, and Deactivate Are Three Separate Steps

GICv5 is structurally split-EOI: no instruction performs both priority drop and
deactivation, and no ordering between them is mandated. `GICR CDIA` acknowledges
(returning a packed valid/type/ID, setting Active and, for edge interrupts,
clearing Pending). `GIC CDEOI` performs the priority drop and takes no INTID at
all: it drops the domain's highest active priority. `GIC CDDI` deactivates a
specific INTID, and for a routed interrupt — an SPI or an LPI — it is legal from
any PE. That cross-PE property does not extend to PPIs: a `CDDI` naming a PPI
that is outside the Current Interrupt Domain has no effect, so a PPI is in
practice deactivated on the PE that owns it.

> Deferring the priority drop until deactivation blocks every interrupt of equal
> or lower priority for the whole duration of the handler. Because Linux
> programs all interrupts at the same priority, that is a denial of service for
> all other interrupts, not a latency nit.

Everything in this section describes the native GICv5 instruction set. Under
GICv3 legacy operation the GICv3 EOI model applies instead, including its
combined drop-and-deactivate mode; see "GICv3 Legacy Compatibility" below.

*   **The priority drop belongs immediately after the acknowledge, not in
    `irq_eoi()`.** This was fixed upstream after the driver initially did the
    drop as part of the EOI callback: with a long-running handler, or a
    directly-entered guest holding an interrupt active, nothing else could be
    signalled. `gicv5_handle_irq()` now issues `GICR CDIA`, `gsb_ack()`,
    `isb()`, then `gic_insn(0, CDEOI)`, and only afterwards dispatches to the
    handler. `gicv5_hwirq_eoi()` issues `GIC CDDI` alone.
*   **Deactivation is what prevents re-signalling.** Since the drop happens
    early, the interrupt cannot be signalled a second time only because it is
    still Active until software deactivates it. A path that skips the
    deactivate must have a reason for the interrupt to be deactivated elsewhere.
*   **An interrupt forwarded to a guest is deactivated by the guest.**
    `gicv5_ppi_irq_eoi()` returns early when `irqd_is_forwarded_to_vcpu(d)`,
    leaving deactivation to the guest's own handling of the injected interrupt.
    This is correct and mirrors GICv3; do not report the missing `CDDI`.
*   **LPIs have an active state.** Unlike a GICv3 LPI, a GICv5 LPI cannot
    retrigger while it is being handled, so `IRQD_RESEND_WHEN_IN_PROGRESS` is
    meaningless on a GICv5 LPI and was removed from the ITS domain. Do not
    report its absence, and question a patch that adds it back.

**REPORT as bugs:**
*   A GICv5 handler or irqchip that performs `GIC CDEOI` in the `irq_eoi()`
    callback, or that couples the priority drop to deactivation in any way.
*   A `GIC CDEOI` issued with a non-zero INTID operand, which suggests the
    author believes it deactivates a specific interrupt.
*   An acknowledge path that dispatches to a handler without `gsb_ack()` and
    `isb()` after `GICR CDIA`.

## IRS Register Programming: Select, Program, Poll

Several IRS register groups are select-then-program: a selector register names
the object, then configuration registers act on whatever is currently selected.
The selection is per-IRS state, not per-CPU state, and each step completes
asynchronously.

> Two CPUs interleaving a select-then-program sequence on the same IRS
> configure the wrong interrupt or the wrong PE. Failing to wait for completion
> lets the next write land while the previous one is still in flight, which the
> architecture does not define. Ignoring the validity result configures an
> object that does not exist and reports success.

*   **Serialize the whole sequence, not the individual writes.** The lock must
    span selector plus configuration. `gicv5_spi_irq_set_type()` takes
    `irs_data->spi_config_lock` (a `raw_spinlock_t`, initialized per IRS at
    probe) and holds it across `IRS_SPI_SELR`, the completion wait,
    `IRS_SPI_CFGR`, and the second wait. A patch that adds a new SPI
    configuration register write must extend the same critical section, not
    take its own.
*   **Poll the matching `*_STATUSR` after each step.** The pairs are fixed:
    `IRS_SPI_SELR` and the SPI config registers complete via
    `IRS_SPI_STATUSR`, `IRS_PE_SELR` and `IRS_PE_CR0` via `IRS_PE_STATUSR`,
    `IRS_IST_BASER` and `IRS_MAP_L2_ISTR` via `IRS_IST_STATUSR`, `IRS_SYNCR`
    via `IRS_SYNC_STATUSR`, `IRS_CR0` via its own `IDLE` bit.
    `gicv5_wait_for_op()` and `gicv5_wait_for_op_atomic()` in
    `include/linux/irqchip/arm-gic-v5.h` wrap the poll and carry a 10ms timeout.
*   **`IDLE` and `V` answer different questions.** `IDLE` means the register
    write has completed; `V` means the selected object is valid. Both matter,
    but not everywhere. `gicv5_irs_wait_for_spi_op()` checks `IDLE` then
    requires `V`, because selecting an SPI this IRS does not own must fail.
    `gicv5_irs_wait_for_irs_pe()` takes a `selr` flag and checks `V` only after
    a selector write, because after an `IRS_PE_CR0` write there is no new
    object to validate. That asymmetry is deliberate; a report that the `CR0`
    path "forgets" the validity check is a false positive.
*   **A poll timeout is an error, not a warning.** `gicv5_wait_for_op_s()`
    returns `-ETIMEDOUT` after a rate-limited message. Callers must propagate
    it and undo whatever they were setting up: `gicv5_irs_init_ist_linear()`
    frees the table it had just published, `gicv5_irs_iste_alloc()` clears the
    L1 entry it wrote and frees the L2 table.
*   **The completion poll also provides the ordering against table memory.**
    The MMIO accessors inside the poll supply the barriers that order CPU
    accesses to a table against the IRS's accesses to it. This is why
    `gicv5_irs_ist_synchronise()` is documented as the synchronization point
    and why the post-sync cache maintenance in `gicv5_irs_iste_alloc()` is safe
    where it sits.

**REPORT as bugs:**
*   A select-then-program sequence on an IRS register group with no lock, with
    a lock that covers only part of the sequence, or with a lock that is not
    the one the rest of that IRS's sequences use.
*   A write to an IRS register with a defined `*_STATUSR` pairing that is not
    followed by a completion poll before the next dependent access.
*   A `gicv5_wait_for_op*()` return value that is discarded, or a failure path
    that leaves a published table address or a half-written table entry behind.

## Table Sizing: `n` Is an Alignment Exponent

The GICv5 sizing expressions for the IST look like size computations and are
not. `IRS_IST_BASER.ADDR` is `GENMASK_ULL(55, 6)`, and the architecture states
the constraint as "bits [n:0] of the base address are zero", that is, an
alignment requirement of 2^(n+1) bytes. The `Max(5, ...)` that appears in the
expression is therefore a 64-byte alignment-granule floor and nothing more:
there is no architectural minimum IST size, and no requirement that the
allocation be 2^(n+1) bytes.

> Getting this wrong in the shrinking direction gives the IRS a table smaller
> than the ID space it was told to cover, so the IRS reads and writes memory the
> driver did not allocate. Getting it wrong in the widening direction wastes
> memory but is harmless, which is why over-provisioning is not a defect.

*   **Allocating 2^(n+1) bytes is one correct way to satisfy the constraint,
    not the constraint itself.** `gicv5_irs_init_ist_linear()` computes
    `n = max(5, lpi_id_bits + 1 + istsz)` and allocates `BIT(n + 1)` bytes,
    which is both large enough for `2^(LPI_ID_BITS + ISTSZ + 2)` bytes of
    entries and, from a power-of-two allocator, suitably aligned. A table that
    is larger than the ID space strictly requires is not a bug, and neither are
    two sites that clamp the same expression differently, provided each site's
    result is at least as large as what it is used to cover.
*   **Validate the type as well as the value.** `BIT(n + 1)` is `1UL << (n+1)`;
    assigning it to a `u32` truncates to zero at 32 and beyond, and
    `kzalloc(0)` returns `ZERO_SIZE_PTR`, which is non-`NULL` and passes the
    usual `if (!ptr)` check. The merged driver avoids this by using `size_t`
    and by capping against `KMALLOC_MAX_SIZE` with an explicit warning that
    reduces the advertised ID bits to match. A shift count that can reach or
    exceed the width of the shifted type is undefined behaviour in the kernel;
    `-fno-strict-overflow` does not cover it, and `CONFIG_UBSAN_SHIFT` exists
    to detect it.
*   **Unsigned sizing arithmetic can wrap past its own clamp.** In an
    expression of the form `max(5, a - b + c)` with unsigned operands, a
    negative inner result wraps to a very large value and `max()` selects the
    wrapped value rather than the floor. When you see this shape, the question
    to answer is whether the caller structurally guarantees `a > b`; if the
    guard is in a different function from the arithmetic, say so, because that
    separation is what makes the construct fragile even when it is currently
    safe.
*   **The size that is validated and the size that bounds the loop must come
    from the same variable.** This is the highest-value structural check in
    this area. Table geometry is recorded in more than one place at once: in the
    configuration register the software wrote, and in the in-memory descriptor
    the hardware walks. When a length check reads one and the copy or walk that
    follows reads the other, anything that can make the two disagree turns the
    check into a no-op. Trace both to their source and confirm they are the same
    value, not merely two values that happen to be equal in the common case.

    ```c
    /* WRONG: validated against the register, copied according to the descriptor */
    if (user_size != BIT(cfg_reg.id_bits) * sizeof(u32))
            return -EINVAL;
    for (i = 0; i < BIT(descriptor.id_bits); i++)
            put_user(entry[i], &buf[i]);

    /* CORRECT: one variable decides both */
    n = BIT(descriptor.id_bits);
    if (user_size != n * sizeof(u32))
            return -EINVAL;
    for (i = 0; i < n; i++)
            put_user(entry[i], &buf[i]);
    ```

**Do NOT flag:**
*   **`kmalloc()`/`kzalloc()` not guaranteeing alignment for a GIC table.** The
    kernel's allocator contract, stated in
    `Documentation/core-api/memory-allocation.rst`, is that "for sizes which are
    a power of two, the alignment is also guaranteed to be at least the
    respective size", and that for other sizes the alignment is at least the
    largest power-of-two divisor. The IST and ITS table allocations are
    power-of-two sized, so a 4KB allocation is 4KB-aligned and the low address
    bits masked by `GICV5_ISTL1E_L2_ADDR_MASK` and friends are already zero.
    An allocation whose size is *not* a power of two is a different matter and
    is worth checking.
*   **A table larger than the minimum, or two clamps that differ.** See above:
    over-provisioning to an alignment granule is the intended behaviour.

**REPORT as bugs:**
*   `BIT(n)` or `BIT(n + 1)` assigned to a type narrower than the shift can
    reach, or a table size that is not checked against an allocator limit.
*   A length validation and the loop or copy it is meant to bound that read
    their extent from different variables.

## Who Owns the Valid Bit

GICv5 in-memory structures are shared with hardware, and the architecture is
specific about which side writes the valid bit. It is not the same answer
everywhere, and getting it backwards in a review is the single most common
false positive in this subsystem: automated reviewers repeatedly report "the
code fails to set the VALID bit" against code that is correct precisely because
it does not.

> Software setting a valid bit that the IRS owns makes the behaviour of the IRS
> Domain UNPREDICTABLE, and the only recovery is to invalidate an enclosing
> structure — at best the affected VM, at worst the whole VM table or IST.
> Software failing to set a valid bit it does own leaves the entry invisible to
> hardware, and every interrupt covered by it is dropped.

**For IRS-walked structures, the rule is path-dependent:**

*   **Adding an entry to a structure that is already valid: software leaves the
    valid bit at 0 and the IRS sets it** in response to the write of the
    corresponding map register, then reports completion. This applies to a
    level 2 IST published through `IRS_MAP_L2_ISTR`, a level 2 VM table
    published through `IRS_VMAP_L2_VMTR`, and a virtual IST published through
    `IRS_VMAP_VISTR`. The merged driver is a worked example:
    `gicv5_irs_iste_alloc()` writes the L2 address into the L1 entry with the
    valid bit clear, writes `IRS_MAP_L2_ISTR`, waits for
    `IRS_IST_STATUSR.IDLE`, and its trailing comment says so explicitly ("Make
    sure we invalidate the cache line pulled before the IRS had a chance to
    update the L1 entry and mark it valid"). The same function *reads*
    `GICV5_ISTL1E_VALID` to decide whether an L2 table already exists, which is
    the correct use of a bit only hardware writes.
*   **Providing an entry before the containing structure becomes valid:
    software does write the valid bit.** A hypervisor populating a level 2 VM
    table entry, including `L2_VMTE.LPI_IST_VALID` / `SPI_IST_VALID`, at the
    moment the VM is made valid is architected, and is how a VM's virtual ISTs
    are provided for migration and for suspend/resume. A tree with no such
    prefill path will have a valid-bit macro that is defined and never used;
    that is consistent with the architecture, not evidence of a bug.
*   **That licenses pre-populating the table *entry*, not the IST's
    *contents*.** The distinction matters because the two look alike in a diff
    and only one of them is architected. Making an IST valid while it holds
    non-zero Pending, HWU or metadata state is UNPREDICTABLE; the only sanctioned
    way to install live interrupt state that way is an IMPLEMENTATION DEFINED
    restore mechanism, which by definition cannot be assumed to exist on the
    target implementation. The architectural migration path is instead: snapshot
    the IST, record which interrupts were Pending, scrub the transient fields
    (the specification's procedure zeroes Pending, HWU and metadata, and also
    the affinity field for a 1-of-N interrupt where the IRS supports 1-of-N),
    install the scrubbed image, make it valid, and only then re-inject each
    recorded interrupt with `GIC VDPEND`. Note what that instruction names: a
    VM identifier and an INTID, not a VPE. Valid VPEs are a *precondition* on
    the destination VM — the re-injection must come after they are valid, or
    the interrupts are not considered for those VPEs' virtual candidate
    highest-priority pending interrupt. So a restore path that hands hardware a table
    image with Pending bits still set is a real finding, while one that scrubs
    and re-injects is correct even though it looks like it is "losing" state.
*   **Writing a valid entry at all is UNPREDICTABLE.** Setting a valid bit into
    a live entry, or updating a level 1 entry that is already valid, has
    UNPREDICTABLE IRS Domain behaviour, and recovery is only ever by
    invalidating some enclosing structure. Which structure depends on the
    entry, and the granularity is worth getting right because a reviewer will
    otherwise assume the cheapest one. A bad write to a level 1 IST entry is
    recovered by invalidating the IST; to a level 1 VM table entry, by
    invalidating the VM table; to a VPE table entry, by invalidating the VM.
    The two level 2 VM table cases are the trap, because they differ from each
    other: a bad write to a *valid* level 2 entry recovers at VM granularity,
    while a write to an *invalid* level 2 entry that sets its valid bit
    escalates to invalidating the whole VM table. The reason the coarser cases
    are coarse is that the architecture provides no way to invalidate an
    individual level 2 IST, an individual level 2 VM table, or an individual
    VPE — a VPE can only be made invalid by making its VM invalid. So the
    suggested "fix" of ORing the valid bit in is not merely unnecessary, it
    introduces a defect, and it also makes the subsequent map-register write a
    no-op because that write only has an effect on an entry that is currently
    invalid.

**For ITS tables, the opposite holds: software owns the valid bit.** The ITS
has no map register; software writes the complete entry, valid bit included,
and then invalidates. `gicv5_its_alloc_l2_devtab()`,
`gicv5_its_device_register()`, `gicv5_its_create_itt_two_level()` and
`gicv5_its_map_event()` in `drivers/irqchip/irq-gic-v5-its.c` all set
`GICV5_DTL1E_VALID` / `GICV5_DTL2E_VALID` / `GICV5_ITTL1E_VALID` /
`GICV5_ITTL2E_VALID` directly. Do not carry the IRS rule across to the ITS.

**REPORT as bugs:**
*   Software setting an IRS-owned valid bit (`L1_VMTE.VALID`,
    `L2_VMTE.{LPI,SPI}_IST_VALID`, an L1 ISTE valid bit) on a structure that is
    already valid, rather than letting the map register drive it.
*   A map-register write with no preceding entry write, or an entry write with
    no map-register write and no completion poll: either half alone leaves the
    entry unpublished.
*   An ITS table entry written without its valid bit, or written and never
    invalidated.
*   A restore path that makes an IST valid while the image it installed still
    carries Pending, HWU or metadata state, without the target implementation
    providing an IMPLEMENTATION DEFINED restore mechanism it can name.

**Do NOT flag:**
*   A defined-but-unreferenced valid-bit macro for an IRS structure, or an IRS
    entry written without its valid bit and followed by a map-register write.
    Both are the architected sequence.
*   A migration path that scrubs Pending, HWU and metadata out of the IST image
    it installs and replays the recorded pending interrupts with `GIC VDPEND`.
    That is the architectural sequence, not lost state.

## ITS: Publish Is Write, Invalidate, Then Sync

Because there is no command queue, the ITS may hold cached copies of both valid
and invalid table entries, and those caches are not affected by PE cache
maintenance. A table write is therefore not visible to the ITS until an
invalidation completes.

> A mapping the ITS never observes silently drops every event for that device or
> event. A stale cached translation delivers an event to an LPI that has been
> freed and reused, which is a cross-device interrupt at best and, once the LPI
> has been handed to a different driver, a corruption of that driver's state.

*   **Every table entry write is followed by an invalidate and a completion
    poll.** `its_write_table_entry()` does the `WRITE_ONCE` plus the cache
    clean; the caller then invalidates by event (`gicv5_its_itt_cache_inv()`,
    which writes `ITS_DIDR`, `ITS_EIDR`, `ITS_INV_EVENTR`) or by device
    (`gicv5_its_device_cache_inv()`, `ITS_DIDR` plus `ITS_INV_DEVICER`), and
    both end in `gicv5_its_cache_sync()` polling `ITS_STATUSR.IDLE`.
*   **There is no unmap operation; unmap is `VALID = 0` plus invalidate.**
    `gicv5_its_unmap_event()` clears `GICV5_ITTL2E_VALID` and invalidates;
    `gicv5_its_device_unregister()` zeroes the whole DTE and invalidates.
    Invalidation works irrespective of the values stored, which is why no
    separate discard step exists.
*   **Reusing a translation needs both syncs, in order.** Invalidation (a cache
    operation) is a different tier from draining accepted events. Before an
    LPI or an ITT entry can be safely reused, the accepted events must be
    drained: `gicv5_its_irq_domain_free()` calls `gicv5_its_syncr()` for the
    device and then `gicv5_irs_syncr()`, each polling its own
    `*_SYNC_STATUSR.IDLE`. A free path that invalidates but does not sync can
    hand a reused LPI an in-flight event from its previous owner.
*   **Table entries are `__le64` and must be converted on read.** A bit test
    against a raw `__le64` is a real bug on a big-endian build and was fixed
    upstream in exactly this shape: `FIELD_GET(GICV5_ITTL2E_VALID, *itte)`
    became `FIELD_GET(GICV5_ITTL2E_VALID, le64_to_cpu(*itte))`. Sparse catches
    this, so the pattern to look for in review is a new accessor that
    dereferences a `__le64` table pointer without `le64_to_cpu()`.

**Do NOT flag:**
*   A second invalidate immediately after a function that already invalidated.
    One was removed upstream as redundant, and adding one back is noise, not
    safety.

**REPORT as bugs:**
*   An ITS device-table or ITT entry modified without a following invalidate,
    or invalidated without polling `ITS_STATUSR.IDLE`.
*   An LPI, EventID or ITT freed or reused without the ITS sync and IRS sync
    pair.
*   A `FIELD_GET()` or bit test applied directly to a `__le64` GIC table entry.

## Non-Coherent IRS and ITS

An IRS or ITS may be non-coherent with the PEs, described by `dma-noncoherent`
in DT or the corresponding MADT flag. The kernel handles this by programming
non-cacheable memory attributes for the component and by doing explicit cache
maintenance on the tables. What changes is the publish operation; the ordering
requirements do not change.

> Omitting the cache maintenance on a non-coherent system means the component
> walks stale table contents: an entry the driver believes it wrote is not there,
> or a stale entry it believes it cleared still is.

*   **The publish step is conditional, the barrier is not.** Both
    `gicv5_its_dcache_clean()` and the open-coded equivalents in
    `irq-gic-v5-irs.c` select `dcache_clean_inval_poc()` when the component is
    flagged non-coherent and `dsb(ishst)` otherwise. A new table write path must
    go through the same helper rather than hardcoding either arm.
*   **Reading back an entry the hardware wrote needs an invalidate, after the
    completion poll.** On a non-coherent system the PE may have pulled a stale
    copy of a line the IRS is about to update. `gicv5_irs_iste_alloc()` issues
    `dcache_inval_poc()` on the L1 entry *after* `gicv5_irs_ist_synchronise()`
    has returned, and comments that the poll's MMIO barriers are what keep the
    invalidate from running early. An invalidate placed before the completion
    poll would be useless.
*   **Access attributes are programmed once, before anything is valid.**
    `gicv5_irs_init_bases()` writes `IRS_CR1` and then enables the IRS via
    `IRS_CR0.IRSEN`; `gicv5_its_init_bases()` writes `ITS_CR1` before allocating
    the device table and enabling the ITS. Attributes take effect from the last
    write made while no structure was valid, so a patch that adjusts `CR1` after
    tables are live has no effect and should be questioned.

**REPORT as bugs:**
*   A new IRS or ITS table write path that uses `dsb(ishst)` unconditionally, or
    that calls the CMO unconditionally, instead of branching on the component's
    coherency flag.
*   Cache maintenance for a hardware-written entry placed before, rather than
    after, the completion poll that guarantees the hardware has written it.

## Discovery Registers Report Width, Not Range

Every GICv5 capability is discovered from an ID register field, and those
fields are consistently wider than the values the architecture permits them to
hold. Treating the field width as the value range produces confident,
arithmetically correct, and wrong reports.

> The false-positive direction wastes reviewer and maintainer time on
> overflow claims that cannot occur. The false-negative direction is worse: code
> that consumes a field without clamping it will misbehave on a
> non-conforming or future implementation, and code that assumes two components
> agree will size a structure for the wrong one.

*   **Check the field's documented maximum before claiming a truncation.**
    Worked examples from the GICv5 specification: `IRS_IDR3.VM_ID_BITS` is a
    5-bit field, bits [9:5], whose minimum valid value is 8 and maximum is 16,
    so a VM ID never needs more than 16 bits and a `u16` cannot lose one.
    `IRS_IDR3.VMD_SZ` and `IRS_IDR4.VPED_SZ` have a maximum valid value of 12,
    giving a maximum descriptor of 4096 bytes, so neither can produce a
    zero-sized allocation by wrapping. `IRS_IDR2.MIN_LPI_ID_BITS` has a maximum
    of 14 and is IMPLEMENTATION DEFINED, with the architecture noting that most
    implementations are expected not to require a minimum at all. "The field is
    N bits wide, therefore 2^N - 1 is reachable" is not a valid step.
*   **Give every ID-register decode a defined fallback.** `gicv5_set_cpuif_pribits()`,
    `gicv5_set_cpuif_idbits()` and `irs_setup_pri_bits()` all end in a `default:`
    that logs and picks a safe value, because the architecture defines only a
    subset of the encodings. A `switch` over an ID register field with no
    `default`, or one that leaves the destination uninitialized, is a real
    finding.
*   **Capabilities are per-component and need not agree.** The number of INTID
    ID bits is reported independently by the IRS (`IRS_IDR2.ID_BITS`) and the
    CPU interface (`ICC_IDR0_EL1.ID_BITS`). The architecture only *recommends*
    that components match, and separately recommends that the IRS support at
    least as many bits as the PEs, so an IRS with more bits than the CPU
    interface is explicitly the sanctioned direction and is not a mismatch to
    report. Software that must work with both takes the minimum:
    `gicv5_irs_init_ist()` caps `lpi_id_bits` by `cpuif_id_bits`, and
    `gicv5_init_common()` takes `min_not_zero()` of the two priority widths.
    Note also that the CPU interface can only report 16 or 24 ID bits while the
    IRS reports a raw count, so they are not comparable encodings.
*   **A policy cap is not an architectural cap, and must be re-applied
    wherever the value can be set again.** When the driver or KVM narrows a
    hardware-reported capability to its own limit, every later path that can
    write that field has to apply the same limit, not merely the architectural
    one. `vgic_v5_reset()` is the pattern: it pins the guest's view to
    `ICC_IDR0_EL1_ID_BITS_16BITS` and 5 priority bits regardless of what the
    host allows.

**Do NOT flag:**
*   A narrow C type holding an ID-register field whose architectural maximum
    fits in it. Cite the maximum from the register description before deciding
    either way.
*   The IRS and the CPU interface reporting different ID-bit or priority-bit
    widths.

**REPORT as bugs:**
*   A `switch` or decode over an ID-register field with no defined behaviour for
    an unexpected encoding.
*   A hardware capability consumed directly where the code has previously
    narrowed it by policy, so the policy cap is bypassed on that path.

## KVM: PPI State Lives in Hardware

The merged GICv5 vGIC is PPI-centric. Private PPIs are the only interrupts it
emulates; a GICv3-aware guest on GICv5 hardware runs on the existing vgic-v3
stack as a compatibility device instead. Because the PPI state lives in the CPU
interface rather than in KVM's own structures, the shadow `struct vgic_irq`
state and the hardware registers must be reconciled on every entry and exit,
and the direction of that reconciliation differs by handling mode.

> Getting the reconciliation wrong loses interrupts outright. An edge that is
> not transferred into the hardware pending register is never delivered; an edge
> that is not cleared after transfer is delivered twice; a stale pending bit
> written over a directly-injected PPI overwrites hardware-maintained state.

*   **Iterate the exposed PPI mask, not the full range.** KVM exposes only a
    handful of PPIs to a guest: the timers, the PMU interrupt and the software
    PPI. `for_each_visible_v5_ppi()` (`arch/arm64/kvm/vgic/vgic.h`) walks
    `gicv5_vm.vgic_ppi_mask`, and every state-folding, state-flushing,
    pending-check and priority-sync loop in `vgic-v5.c` uses it. An earlier
    implementation tried to detect which bits had changed instead, and that
    lost edges the guest had not yet consumed, so the change-detection approach
    was replaced by iterating the (small) exposed set unconditionally.
*   **Edge and level pending are handled asymmetrically, in both directions.**
    On the way in, `vgic_v5_flush_ppi_state()` builds the guest's pending
    bitmap and clears `pending_latch` for edge interrupts, because the latch has
    now been transferred to hardware and nothing else will lower it; a level
    interrupt's pending state is driven by the line, so it is left alone. On the
    way out, `vgic_v5_fold_ppi_state()` ORs the hardware pending bit into
    `pending_latch` for edge interrupts only, and the OR is deliberate so that
    an edge injected in software while the guest was running is not lost. Both
    halves were upstream fixes. A patch that makes either direction symmetric
    across handling modes is almost certainly wrong, and a report that the fold
    "should use LEVEL" has read the condition backwards.
*   **Directly-injected PPIs are excluded from the pending write-back.** DVI
    aliases the physical PPI's pending state into the virtual PPI in hardware,
    so KVM must not also write that PPI's pending bit on restore.
    `__vgic_v5_restore_ppi_state()` computes `bitmap_andnot(pendr, ..., dvir)`
    and writes only the non-DVI'd bits. DVI is disabled (`ICH_PPI_DVIR*_EL2`
    zeroed) on save and re-enabled from the shadow on restore.
*   **The DVI bitmap needs atomic bit operations.** Individual bits are each
    protected by their own `vgic_irq->irq_lock`, but the bitmap as a whole has
    no lock, so concurrent updates to different PPIs race. `vgic_v5_set_ppi_dvi()`
    uses `assign_bit()`, not `__assign_bit()`; the non-atomic version was an
    upstream bug. This generalizes: a per-interrupt lock does not serialize a
    shared bitmap indexed by interrupt.
*   **VM-wide finalization must be locked and idempotent.** `vgic_v5_finalize_ppi_state()`
    runs per-vCPU but computes VM-wide state, so it takes
    `kvm->arch.config_lock` and returns early if it has already run; without
    both, two vCPUs race and one zeroes the mask the other is populating.
*   **Residency is tracked in software and the entry points are re-entrant.**
    `vgic_v5_load()` and `vgic_v5_put()` are each called twice around WFI, so
    both begin with a `cpu_if->gicv5_vpe.resident` check and return early on the
    redundant call, which is what prevents the saved VMCR from being clobbered
    by a second save. A finding that `vgic_v5_load()` unconditionally makes the
    VPE resident has quoted the body without the guard above it.
*   **Priority comparison is a strict inequality.** An interrupt is signalled
    only if its priority is numerically less than the effective mask;
    `vgic_v5_has_pending_ppi()` uses `irq->priority < priority_mask` after an
    upstream fix, because `<=` produced spurious wakeups at the limit. The mask
    itself is `min(highest_active_priority, VPMR + 1)`, and is zero when the
    guest has not enabled interrupt delivery, which short-circuits the whole
    check.

**REPORT as bugs:**
*   A GICv5 PPI state path that iterates `VGIC_V5_NR_PRIVATE_IRQS` directly
    instead of the exposed mask, or that reintroduces change-detection over the
    pending bitmap.
*   An edge-triggered PPI whose `pending_latch` is not cleared after being
    flushed to hardware, or whose hardware pending bit is assigned rather than
    ORed when folded back.
*   A pending write-back that does not exclude DVI'd PPIs.
*   A non-atomic bitmap operation (`__set_bit()`, `__assign_bit()`,
    `__clear_bit()`) on a per-vCPU or per-VM interrupt bitmap whose only
    claimed protection is a per-interrupt lock.
*   VM-wide vGIC state computed from a per-vCPU entry point without
    `config_lock` and without an already-done check.

## Userspace-Facing and Save/Restore Paths

KVM's VGIC register emulation gives each register up to four handlers: a guest
read and write, and optional userspace read and write overrides
(`uaccess_read` / `uaccess_write` in `struct vgic_register_region`,
`arch/arm64/kvm/vgic/vgic-mmio.h`). The override exists because restore
legitimately needs to do things a guest may not: program a table base before
the tables exist, write a field the guest-side handler would refuse while some
other state is live. That is a correct design, and it is also a systematic
source of defects, because each override silently drops whatever the guest-side
handler was doing beyond the bare field write.

> A userspace path that accepts a register write the guest path would have
> refused, validated, or acted upon leaves the emulated device in a state the
> guest path can never produce. The consequences observed in practice are a
> field restored past the cap the emulation advertises, a table marked valid
> with no table behind it, and a configuration write accepted and discarded so
> the setting is silently lost across migration.

*   **Review overrides pairwise, and enumerate.** For each register with a
    userspace override, put the guest handler and the userspace handler side by
    side and ask what the guest handler does that the override does not:
    refuse under some condition, allocate or free something, clamp a field,
    request a reload, or set derived state. Then check the other direction:
    a userspace *read* override that returns a different value from the guest
    read is only a problem if that value can be fed back on restore, so a
    register that is write-ignored on every path cannot be misled by it. Doing
    this exhaustively over the register table, and saying how many registers
    were compared, is what turns "there are some divergences here" into a claim
    a maintainer can act on.
*   **The fix is usually a post-condition, not the missing guard.** Adding the
    guest-side guard to the userspace path breaks restore, because the
    documented restore sequence depends on the guard being absent. What is
    actually missing is a validation step at the *end* of restore that
    re-establishes the invariants the guest path maintains continuously: that
    the configuration register and the descriptor the hardware walks agree, that
    a "valid" flag matches whether the backing object exists, that every
    restored field is within the cap the emulation advertises. Recommending the
    guard is the fix that gets sent back.
*   **A register that is accepted and discarded is worse than one that is
    rejected.** A `case X: break;` in a userspace write handler, with no
    comment, means userspace's value is silently dropped: the setting does not
    survive migration and userspace has no way to find out. Either the write
    must take effect or it must be rejected.
*   **A read-only attribute must reject writes, and the rejection must be
    tested.** The merged GICv5 KVM device has one attribute of this kind,
    `KVM_DEV_ARM_VGIC_USERSPACE_PPIS`, documented in
    `Documentation/virt/kvm/devices/arm-vgic-v5.rst` as read-only with attempts
    to set it rejected.
*   **Every documented error code must be reachable, and every reachable one
    documented.** When reviewing a new device attribute, walk the documented
    error table against the code. An error branch that cannot fire, because an
    earlier validation already excluded its precondition, is a documentation
    bug and often reveals a parameter that has no effect at all.

**REPORT as bugs:**
*   A userspace write override that omits an allocation, free, clamp, reload
    request or refusal performed by the guest-side handler for the same
    register, with no restore-time step that re-establishes the same invariant.
*   A restore path with no final self-consistency check across the state it
    just wrote.
*   A userspace write case that accepts a value and discards it.
*   A device attribute documented as read-only whose set path does not return an
    error.

## Native Virtualization: Doorbells and VPE Configuration

Merged KVM carries no doorbell handling — `struct gicv5_vpe` in
`include/linux/irqchip/arm-gic-v5.h` holds only `bool resident` — so this
section is architectural rather than code-anchored. Use it to review new code
against the architecture, and verify the specifics against the target tree's
own code rather than against anything stated here about which interfaces
exist.

> A missed doorbell means a vCPU blocked in WFI is never woken for an interrupt
> that is already pending, which is an indefinitely hung guest rather than a
> latency problem.

*   **The doorbell condition is a predicate over current state, not an edge.**
    A VPE doorbell is generated when the VPE is non-resident, its doorbell
    settings are valid, a doorbell is requested, and there exists a qualifying
    interrupt that is Pending, Inactive and Enabled at or above the doorbell
    priority mask. Because it is a standing condition re-evaluated on any
    configuration change, making a VPE non-resident with a doorbell requested
    while an interrupt is already pending generates the doorbell immediately.
    So "the interrupt became pending just before the arming write, therefore the
    wakeup is lost" is not a real race, and reporting it is a false positive.
*   **Requesting a doorbell and configuring one are different steps.**
    `ICH_CONTEXTR_EL2.DB` on the write that makes the VPE non-resident and
    `IRS_VPE_DBR.REQ_DB` are two routes to the same architectural "requested"
    state, not two arms that must both be set, so code that sets only the former
    at deschedule time is correct. What *is* separately required is that the
    VPE's doorbell settings are valid, and they are not valid when a VPE is
    created: they become valid only after the VPE is selected and
    `IRS_VPE_DBR` is written, and a VPE becoming valid resets its configuration
    so that it has no doorbell settings at all. Therefore the `IRS_VPE_DBR`
    write must be redone after **every** VPE creation or revalidation,
    including a vCPU reset, not once at setup.
*   **A permissive doorbell priority mask is the correct default.** The
    condition is "priority greater than or equal to the doorbell priority mask",
    so leaving the mask at zero means every interrupt generates a doorbell. A
    zero mask is not an unconfigured field.
*   **Doorbells are one-shot.** The request self-clears when the doorbell is
    generated, so it must be re-requested on each deschedule. A doorbell arrives
    as an ordinary physical LPI in the VPE's own domain, not on a special
    exception path.
*   **A VPE's descriptor memory must be zero when the VPE becomes valid.** The
    architecture states this as an expectation rather than a prohibition, but
    it attaches two consequences that make it a requirement in practice: the
    VPE's configuration, doorbell settings included, is reset to UNKNOWN
    values, and it becomes CONSTRAINED UNPREDICTABLE *whether* the IRS Domain
    selects a virtual candidate HPPI for that VPE at all. Note the term:
    a *candidate* HPPI is the per-VPE nominee, distinct from the HPPI finally
    selected among candidates, and the CONSTRAINED UNPREDICTABLE is about
    whether one is nominated, not about which one. This is a
    zero-initialization requirement on the allocation, so the thing to check is
    the allocator: a descriptor obtained with a non-zeroing allocator, or
    reused from a previous VPE without being cleared, meets it in neither case.

**REPORT as bugs:**
*   VPE doorbell configuration performed once at setup rather than after every
    VPE validation, including after a vCPU reset.
*   A blocked-vCPU wakeup path whose only signal is the doorbell, with no
    re-request after the doorbell fires.
*   A VPE made valid over descriptor memory that was not zero-initialized.

## GICv3 Legacy Compatibility

GICv5 hardware may implement `FEAT_GCIE_LEGACY`, which provides a
GICv3-compatible **virtual** CPU interface. It is not a general compatibility
mode: `FEAT_GCIE` excludes `FEAT_GICv3`, so there is no legacy physical CPU
interface, and nothing in the IRS, ITS or IWB emulates a GICD/GICR/GICv3-ITS
memory map. A GICv3 guest's MMIO view is therefore emulated entirely in
software, by the existing vgic-v3 code, while the physical routing underneath
remains native GICv5.

> Assuming legacy support extends beyond the virtual CPU interface leads to code
> that expects hardware to provide a GICv3 system view that does not exist.
> Assuming its absence leads to a guest taking undefs on GICv3 registers the
> host could have trapped and emulated.

*   **Discovery is `ICC_IDR0_EL1.GCIE_LEGACY`, read directly.**
    `test_has_gicv5_legacy()` in `arch/arm64/kernel/cpufeature.c` gates on
    `ARM64_HAS_GICV5_CPUIF` and then reads the field, populating
    `ARM64_HAS_GICV5_LEGACY`. Note the cpucap is an early local-CPU feature;
    code that runs before capabilities are finalized must use
    `cpus_have_cap()` rather than `cpus_have_final_cap()`.
*   **The GIC maintenance interrupt exists if and only if `FEAT_GCIE_LEGACY`
    does.** On a PE implementing `FEAT_GCIE`, PPI 25 (GICMNT) is implemented
    when `FEAT_GCIE_LEGACY` is implemented and is not implemented otherwise;
    `FEAT_GCIE_LEGACY` implies `FEAT_EL2`, but not the converse, so a
    `FEAT_GCIE` + `FEAT_EL2` PE with no legacy support is architecturally valid
    and has no GICMNT. An unimplemented PPI is RAZ/WI through the PPI system
    registers and can never become pending. This is why the driver does not
    treat a missing maintenance interrupt as fatal. It is also why a firmware
    description that omits the maintenance interrupt is not a kernel bug: the
    kernel discovers GICMNT's existence from `ICC_IDR0_EL1.GCIE_LEGACY`, not
    from DT or ACPI.
*   **The two worlds are mutually exclusive at EL1, and the switch is
    `ICH_VCTLR_EL2.V3`.** Under legacy operation the native GICv5 instructions
    and registers are UNDEFINED at EL1 and `ICH_VMCR_EL2` takes the GICv3 field
    layout. Consequently a hypervisor that runs both kinds of guest must
    explicitly leave legacy mode before restoring native state:
    `__vgic_v5_restore_vmcr_apr()` calls `__vgic_v5_compat_mode_disable()`,
    which clears `ICH_VCTLR_EL2.V3` and issues an `isb()` before writing
    `ICH_VMCR_EL2`. Dropping that clear, or the `isb()`, means the subsequent
    `ICH_VMCR_EL2` write is interpreted in the wrong layout.
*   **Registration is additive and independently gated.** `vgic_v5_probe()`
    registers `KVM_DEV_TYPE_ARM_VGIC_V5` and then, separately, registers
    `KVM_DEV_TYPE_ARM_VGIC_V3` in compatibility mode if
    `ARM64_HAS_GICV5_LEGACY` is set, enabling the GICv3 CPU interface traps via
    `vgic_v3_enable_cpuif_traps()` so a compat guest does not take an undef on a
    trapped register. Either registration can be skipped: pKVM currently skips
    the native GICv5 device entirely, and a probe returns `-ENODEV` only if
    neither device registered. When reviewing this function, check that the
    max-vCPU limit and the capability flags are consistent with which devices
    were actually registered on the path taken.
*   **No native virtualization implies no legacy.** The architecture forbids the
    combination, so `gic_of_setup_kvm_info()` returns without publishing
    anything to KVM when `IRS_IDR0.VIRT` says the implementation is not
    virtualization-capable. Note the polarity of that read: an inverted `!` on
    it was an upstream bug (`gicv5_global_data.virt_capable = !FIELD_GET(...)`
    where `!!` was meant), which is worth remembering as the shape to look for
    whenever a boolean capability is derived from `FIELD_GET()`.

**Do NOT flag:**
*   A legacy-mode path that performs priority drop and deactivation in one
    operation **when `ICH_VMCR_EL2.VEOIM` is 0**. In that mode a write to
    `ICV_EOIR0_EL1` / `ICV_EOIR1_EL1` does both, exactly as on GICv3, and
    accesses to `ICV_DIR_EL1` are UNPREDICTABLE — so a hypervisor emulating
    this cannot treat `ICV_DIR_EL1` as merely inert either.

    Check the mode bit before applying this, because the exemption is
    conditional. With `VEOIM == 1` the split is back even in legacy mode:
    `ICV_EOIR<n>_EL1` performs the priority drop only and `ICV_DIR_EL1`
    deactivates, so a legacy path that couples the two at `VEOIM == 1` is a
    real finding. What is native-GICv5-only is that the split is
    **unconditional** — the GICv5 form of `ICH_VMCR_EL2` has no `VEOIM` field
    at all, so there is no mode in which `GIC CDEOI` deactivates. Legacy mode
    makes the split a mode; native GICv5 makes it structural.

**REPORT as bugs:**
*   Code that infers a GICv3 system-level view (a distributor, a GICv3 ITS, a
    GICv3 physical CPU interface) from `FEAT_GCIE_LEGACY`.
*   A native GICv5 guest-state restore that does not clear `ICH_VCTLR_EL2.V3`,
    or that does so without a context synchronization event before writing
    GICv5-layout registers.
*   `cpus_have_final_cap(ARM64_HAS_GICV5_LEGACY)` on a path that can run before
    capabilities are finalized.
*   A boolean capability assigned from `FIELD_GET()` with a single `!` where the
    sense should be `!!`.

## Quick Checks

*   **Tables handed to hardware and never freed need `kmemleak_ignore()`.** The
    IST allocations are reachable only by physical address from the GIC, so
    kmemleak reports them as leaks. `gicv5_irs_init_ist_linear()` and
    `gicv5_irs_iste_alloc()` mark them after the publish has succeeded, which is
    the right point: before the publish, the failure path really does free them.
*   **Do not `WARN()` on a firmware-described value.** A malformed DT phandle
    is a firmware bug and warrants `pr_warn(FW_BUG ...)`, not a backtrace; a CPU
    node with no logical ID is not an error at all when the kernel was booted
    with a restricted CPU count. Upstream removed both `WARN_ON()`s from the
    IRS affinity parsing for exactly these reasons. Reserve `WARN()` for
    conditions that indicate a kernel bug.
*   **Error unwind in a domain allocation loop must cover previous
    iterations.** `gicv5_irq_lpi_domain_alloc()` shows the shape: it allocates
    an LPI and an L2 IST entry per interrupt, and on failure releases the LPI it
    had just taken and then calls `gicv5_irq_lpi_domain_free()` for the `i`
    interrupts already set up. Both halves are needed. The ITS twin,
    `gicv5_its_irq_domain_alloc()`, is where getting only one of them was an
    upstream bug: its unwind freed the in-flight LPI but left the earlier
    iterations' LPIs and parent irqs allocated, and the fix rewrote it to walk
    back over them.
*   **A loop counter used in a reverse cleanup loop must be signed.** A
    `for (i = i - 1; i >= 0; i--)` over an `unsigned int` never terminates; this
    was a real fix in the ITS ITT cleanup path.
*   **`gicv5_irs_lookup_by_spi_id()` can return `NULL`** for an SPI outside
    every IRS's range, and it is stored as the irq chip data. Check new
    dereferences of an SPI's chip data.
*   **The IWB never targets SPIs.** An IWB turns wires into ITS events, which
    the ITS translates into LPIs like any MSI. The whole IWB presents a single
    DeviceID and each wire index *is* the EventID, which is why
    `gicv5_iwb_write_msi_msg()` is an empty stub: the mapping is fixed in
    hardware and the MSI domain template merely requires the callback. Do not
    report the empty stub as unimplemented.
*   **The IWB must already be enabled by firmware.** `gicv5_iwb_init_bases()`
    fails probe if `IWB_CR0.IWBEN` is clear rather than setting it, and
    zero-initializes every `IWB_WENABLER<n>` before waiting on
    `IWB_WENABLE_STATUSR`.
*   **A GICv5 PPI's trigger type is fixed in hardware.** `gicv5_ppi_irq_set_type()`
    exists only so that a hierarchy can be built on top of the PPI domain; it
    validates the requested type against `ICC_PPI_HMR<n>_EL1` and configures
    nothing. A patch that makes it actually program the handling mode is wrong.
*   **`ICC_PPI_*` register selection is by bank, and the banks are 64 bits.**
    The `irq < 64 ? ..._EL1 : ..._EL1` pattern with `BIT_ULL(irq % 64)` appears
    throughout; a bank index computed without the corresponding bit-position
    modulo, or vice versa, addresses the wrong PPI. The same shape appears in
    KVM's priority register handling, where each register holds eight five-bit
    fields at byte granularity (`pri_reg = i / 8`, `pri_bit = (i % 8) * 8`).
*   **`vgic_v5_probe()` is the only gate for GICv5 guests.** pKVM skips native
    GICv5 registration entirely today, so a change that assumes a GICv5 vGIC is
    available under protected mode needs that gate revisited first.
