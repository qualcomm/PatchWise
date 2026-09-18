# GICv3/v4 Subsystem Details

This guide covers invariants and bug patterns for GICv3 and GICv4/v4.1: the
host irqchip driver (`drivers/irqchip/irq-gic-v3.c`,
`drivers/irqchip/irq-gic-v3-its.c`, `drivers/irqchip/irq-gic-v4.c`), the shared
register definitions (`include/linux/irqchip/arm-gic-v3.h`,
`include/linux/irqchip/arm-gic-v4.h`), and KVM's virtual GIC
(`arch/arm64/kvm/vgic/`, `include/kvm/arm_vgic.h`). It is derived from the
merged upstream implementation, its fix history, and the Arm Generic Interrupt
Controller Architecture Specification, GICv3 and GICv4 (ARM IHI 0069).

GICv2 is out of scope. GICv5 is a redesign rather than an extension and has its
own guide, `gic-v5.md`; the only place the two meet is a GICv3 guest running in
compatibility mode on GICv5 hardware, covered in "GICv5 Hardware Running a
GICv3 Guest" below.

Three sibling guides own rules that are deliberately **not** repeated here, and
a reviewer should load them alongside this one rather than expect this file to
be self-contained:

- `kvm-arm64.md` owns the VGIC CPU interface access rules (`ICV_AP<n>R_EL1`
  write ordering, `ICV_IAR*` self-synchronization, `ICC_SRE_EL1_NS.SRE` gating
  of the memory-mapped `GICV_*` frame), the `ICH_HCR_EL2` trap-ordering rules,
  the vGIC lock-ordering rules over `irq_lock` and the LPI xarray, and the
  first-run resource ordering.
- `arm64.md` owns the sysreg synchronization rules, including which register
  writes each RWP bit tracks and the `ICC_PMR_EL1` self-synchronization and
  `pmr_sync()` rules.
- `technical-patterns.md` owns generic kernel patterns (double-fetch,
  read-modify-write without write-back, allocation-context rules) that turn up
  in this code but are not specific to it.

Where this guide touches an area a sibling covers, it goes deeper into the GIC
mechanism rather than restating the sibling's rule, and says so.

## The ITS Command Queue Is a Ring Plus a Doorbell

The ITS is programmed by writing command entries into a ring in Normal memory
and then writing a doorbell register. Every one of the four steps — build,
publish, ring, wait — can be got wrong on its own, and three of the four fail
silently.

> A command the ITS never observes is simply not executed: the device mapping
> is absent, so every MSI from that device is dropped, with no error anywhere.
> A command whose completion is not waited for lets the next operation proceed
> against state the ITS has not yet reached. A queue that is rung with a
> malformed entry can stall, and a stalled queue stops processing everything
> behind it.

The canonical sequence is the `BUILD_SINGLE_CMD_FUNC` macro in
`drivers/irqchip/irq-gic-v3-its.c`, which expands into `its_send_single_command()`
and `its_send_single_vcommand()`. Read it as the reference shape:
`its_allocate_entry()`, the command builder, `its_flush_cmd()`, optionally a
second entry for the SYNC, then `its_post_commands()` and
`its_wait_for_range_completion()`.

*   **The publish step is conditional on coherency; the barrier is not.**
    `its_flush_cmd()` selects `gic_flush_dcache_to_poc()` when the ITS is
    flagged `ITS_FLAGS_CMDQ_NEEDS_FLUSHING` and `dsb(ishst)` otherwise, under
    the comment "Make sure the commands written to memory are observable by the
    ITS". A new path that writes command entries must go through the same
    helper rather than hardcoding either arm, and neither arm may be omitted:
    the store into the queue is a Normal-memory store and the doorbell is a
    Device store, so nothing orders them by default.

*   **That ordering requirement comes from the base architecture, not from the
    GIC specification.** IHI 0069 contains no sentence requiring a barrier or
    cache maintenance on the queue before `GITS_CWRITER` is written; the GIC
    specification defers explicitly, saying "For more information on
    endianness, memory ordering, and barrier instructions, see Arm®
    Architecture Reference Manual for A-profile architecture". Do not ask a
    patch to cite a GIC-specification rule for this, and do not treat the
    absence of such a citation as evidence the barrier is unnecessary.

*   **The analogous requirement that *is* in the GIC specification concerns the
    ITS tables, not the queue.** For a two-level table, "A write to a level 1
    table entry that changes the valid bit from 0 to 1 must be globally visible
    before software adds a command to the ITS command queue that relies on that
    entry. Otherwise it is UNKNOWN if the command will succeed or if it will be
    ignored." A patch that publishes a new level 2 table and immediately queues
    a command referencing it needs that visibility, and this one you can cite.

*   **`GITS_CREADR` is sampled before the doorbell, under the queue lock.** The
    completion wait needs the read pointer as it was *before* the new commands
    were made visible, because it computes progress as a delta. Sampling it
    after ringing conflates "the ITS has already consumed these" with "no
    progress yet". The completion wait itself runs after the lock is dropped.

    ```c
    /* CORRECT: sample, ring, unlock, then wait on the sampled origin */
    rd_idx = readl_relaxed(its->base + GITS_CREADR);
    next_cmd = its_post_commands(its);
    raw_spin_unlock_irqrestore(&its->lock, flags);
    its_wait_for_range_completion(its, rd_idx, next_cmd);

    /* WRONG: the origin is read after the ITS may already have advanced */
    next_cmd = its_post_commands(its);
    rd_idx = readl_relaxed(its->base + GITS_CREADR);
    ```

*   **Ring-index arithmetic must linearize the wrap before comparing.**
    `its_wait_for_range_completion()` adds `ITS_CMD_QUEUE_SZ` to the target
    offset when it is below the origin, and again to the per-iteration delta
    when the read pointer has wrapped. A comparison of raw offsets is wrong for
    exactly the commands that straddle the wrap, which is why this class of bug
    survives light testing.

*   **Every command builder must end in `its_fixup_cmd()`.** That helper
    converts the whole four-doubleword command to little-endian
    (`raw_cmd_le[n] = cpu_to_le64(raw_cmd[n])`). A builder that returns without
    calling it leaves host-endian data in the queue, which is correct on a
    little-endian build and silently wrong on a big-endian one. Check every
    return path, including early `goto`s: `its_build_vmapp_cmd()` reaches its
    `its_fixup_cmd()` through a shared `out:` label precisely so that its two
    early exits cannot skip it.

*   **A command error has three architecturally permitted outcomes and software
    may assume none of them.** The specification states that "If the ITS
    detects an error in the data provided to a command, the resulting behavior
    is a CONSTRAINED UNPREDICTABLE choice of: • Ignoring the command ... •
    Stalling the ITS command queue ... • Treating the data as valid data". Code
    or a commit message that reasons "the ITS will just ignore the bad command"
    is relying on one arm of a CONSTRAINED UNPREDICTABLE choice.

*   **A stalled queue has an architected restart path, and anything that can
    stall must preserve it.** When the ITS stalls, `GITS_CREADR` stops
    advancing and `GITS_CREADR.Stalled` reads 1; "When GITS_CREADR.Stalled == 1
    no subsequent commands are processed". Software restarts it by writing 1 to
    `GITS_CWRITER.Retry`, which "Restarts the processing of commands by the ITS
    if it stalled because of a command error". An emulation of the ITS that can
    enter the stalled state without implementing `Retry` has turned a
    recoverable command error into an unrecoverable wedge of every subsequent
    command.

*   **A `GITS_CWRITER` value outside the range implied by `GITS_CBASER` is a
    separate failure mode.** Behavior is a CONSTRAINED UNPREDICTABLE choice
    between treating the command queue as invalid until a valid value is
    written, and treating the value as valid and UNKNOWN. Validate the offset
    before forwarding a value that did not come from the driver's own ring
    arithmetic.

*   **The queue is considered full one entry short of wrapping onto the read
    pointer.** `its_queue_full()` tests `((widx + 1) % ITS_CMD_QUEUE_NR_ENTRIES)
    == ridx`, and `its_allocate_entry()` spins with a bounded count before
    returning `NULL` rather than overwriting an unconsumed entry. A new
    allocation path that returns an entry without that check can overwrite a
    command the ITS has not read.

**REPORT as bugs:**
*   A write of command entries into the ITS queue with no barrier or cache
    maintenance before the `GITS_CWRITER` write, or one that hardcodes
    `dsb(ishst)` or the CMO instead of branching on the ITS's coherency flag.
*   A command builder with a return path that does not pass through the
    endianness fixup.
*   A completion wait whose origin index was sampled after the doorbell write,
    or ring arithmetic that compares offsets without handling wrap.
*   Code or a rationale that depends on one particular ITS behaviour after a
    command error.
*   An ITS emulation that can stall the queue but does not implement
    `GITS_CWRITER.Retry` and `GITS_CREADR.Stalled`.
*   A new level 2 ITS table published and referenced by a queued command
    without being made globally visible first.

## Completion: SYNC Is Physical, VSYNC Is Virtual

The ITS has two synchronization commands and they are not interchangeable. This
is the single easiest completion mistake to make in this driver, because the
wrong one compiles, runs, and appears to work under light load.

> Synchronizing a virtual operation with SYNC synchronizes nothing relevant, so
> the caller proceeds against state the ITS has not reached: a vLPI
> configuration change that has not taken effect, or a translation reused while
> an event for its previous owner is still in flight. In the opposite
> direction, issuing a VSYNC after a command that has already destroyed its
> target is a command error for which an SError is architecturally permitted.

*   **SYNC covers physical interrupts; VSYNC covers a vPEID.** SYNC "ensures
    all outstanding ITS operations associated with physical interrupts for the
    Redistributor specified by RDbase are globally observed before any further
    ITS commands are executed". VSYNC "ensures all outstanding ITS operations
    for the vPEID specified are globally observed before any further ITS
    commands are executed". The two are wired into different send paths in the
    driver: `its_send_single_command()` appends a SYNC built by
    `its_build_sync_cmd()`, and `its_send_single_vcommand()` appends a VSYNC
    built by `its_build_vsync_cmd()`. A virtual command routed through the
    physical send path gets the wrong synchronizer *and* addresses the SYNC at
    a collection whose redistributor need not be the one the vPE is on.

*   **Without one of the two, no ordering exists at all.** "In the absence of a
    SYNC or VSYNC command the ordering of ITS commands and translation requests
    is not defined by the architecture." There is no weaker in-between
    guarantee to rely on.

*   **The builder's return value is control flow, not a diagnostic.** In the
    send macro, the builder returns the object to synchronize against, and a
    `NULL` return elides the trailing SYNC or VSYNC entirely. `valid_col()` and
    `valid_vpe()` return `NULL` when the target is not usable, which
    incidentally drops the synchronization too. When reviewing a new builder,
    decide deliberately what it returns on every path; returning `NULL` to mean
    "nothing to do" silently changes the completion behaviour of the command.

*   **On GICv4.1, unmapping a vPE is self-synchronizing and must not be
    followed by a VSYNC.** The specification states that "A VMAPP with {V,
    Alloc}=={0, x} is self-synchronizing. This means the ITS command queue does
    not show the command as consumed until all of its effects are completed."
    A VSYNC after it would name a vPE that no longer exists, which is a command
    error; the architected error code is `VSYNC_VCPU_INVALID`, and where
    `GITS_TYPER.SEIS` is 1 the implementation may report it as a System error.
    `its_build_vmapp_cmd()` implements this by setting its returned vPE to
    `NULL` on the unmap path, with the comment "Unmapping a VPE is
    self-synchronizing on GICv4.1, no need to issue a VSYNC".

*   **That elision is GICv4.1-only, and the version guard is load-bearing.**
    The self-synchronization sentence appears in the GICv4.1 VMAPP description;
    the GICv4.0 VMAPP description contains no such statement. In the driver the
    `NULL` assignment sits inside an `is_v4_1(its)` test for exactly this
    reason. A patch that hoists the elision out of the version check removes a
    required VSYNC on GICv4.0 hardware; a patch that removes the elision
    reintroduces a VSYNC against an unmapped vPE on GICv4.1.

*   **INVALL is completed by a SYNC.** INVALL "specifies that the ITS must
    ensure any caching associated with the interrupt collection defined by ICID
    is consistent with the LPI Configuration tables held in memory for all
    Redistributors", and the specification is explicit that "A SYNC command
    completes the INV and INVALL commands". An INVALL issued without its SYNC
    leaves a window in which the configuration in memory and the configuration
    the ITS is using disagree.

**Do NOT flag:**
*   A GICv4.1 VMAPP unmap with no following VSYNC. That is the architected
    behaviour, not a missing synchronization.
*   INVDB or VSGI with no explicit VSYNC at the call site. The specification
    states "INVDB is synchronized by a VSYNC command" and "VSGI is synchronized
    by VSYNC", and the driver reaches both through the virtual send path, which
    appends it.

**REPORT as bugs:**
*   A virtual ITS command (anything naming a vPEID) followed by SYNC rather
    than VSYNC, or routed through the physical send path.
*   A VSYNC that can reference a vPE the preceding command unmapped.
*   A VMAPP unmap on GICv4.0 whose VSYNC has been elided, or a v4.1 elision
    applied without a version check.
*   INV or INVALL with no completing SYNC before the caller relies on the new
    configuration.

## LPI Configuration Is Shared State

LPI configuration is not per-redistributor. A group of redistributors is
required to use one copy of the LPI Configuration table, and the architecture
makes divergence within that group UNPREDICTABLE rather than merely
inconsistent.

> Programming different tables into redistributors that must share one leads to
> UNPREDICTABLE behaviour, and the partial constraint the architecture layers on
> top does not rescue it: the GIC picks a copy, and the copy it picks may not be
> the one whose contents software believes are live. The observable failure is
> not a crash but silent divergence — interrupts configured on one CPU behaving
> as if configured differently on another.

*   **`GICR_TYPER.CommonLPIAff` defines the group, by leading affinity
    fields.** The encoding is: `0b00`, all redistributors are in one group;
    `0b01`, all with the same Aff3; `0b10`, all with the same Aff3.Aff2;
    `0b11`, all with the same Aff3.Aff2.Aff1. The requirement attached to it is
    that "Redistributors in the same CommonLPIAff group must use the same copy
    of the LPI Configuration table, and if GICv4.1 is implemented the same copy
    of the vPE Configuration table."

*   **The LPI Pending table is not shared.** The specification says of it:
    "This table is specific to a particular Redistributor." Extending a sharing
    argument from the configuration table to the pending table is a category
    error, and a patch that pins or shares the pending table across a group is
    doing something the architecture does not ask for.

*   **A CommonLPIAff grouping key clears the low bits and keeps the high
    ones.** This inverts the usual intuition that "group by a prefix" means
    "mask down to the low bits", because the packed affinity value places Aff3
    at the top. `compute_common_aff()` is the worked example: it is
    `aff & ~(GENMASK(31, 0) >> (clpiaff * 8))`, so `CommonLPIAff == 0b01`
    retains bits [31:24] (Aff3), `0b10` retains [31:16], `0b11` retains [31:8],
    and `0b00` retains nothing, putting every redistributor in one group. Any
    affinity-derived key deserves the same check: write out which Aff field
    lands in which bits before choosing the mask.

    ```c
    /* CORRECT: keep the leading affinity fields, discard the trailing ones */
    return aff & ~(GENMASK(31, 0) >> (clpiaff * 8));

    /* WRONG: keeps the trailing fields, so redistributors required to share a
     * table are not grouped together, and unrelated ones are */
    return aff & (GENMASK(31, 0) >> (clpiaff * 8));
    ```

    Getting this backwards is doubly bad: the redistributors that were supposed
    to be checked against each other are not, and unrelated ones are grouped
    spuriously.

*   **Divergent `GICR_PROPBASER` values within a group are UNPREDICTABLE.**
    "Setting different values in different copies of GICR_PROPBASER on
    Redistributors that are required to use a common LPI Configuration table
    when GICR_CTLR.EnableLPIs == 1 leads to UNPREDICTABLE behavior." A
    secondary sentence constrains it only partially: "If GICR_PROPBASER is
    programmed to different values on different Redistributors, it is
    IMPLEMENTATION DEFINED which copy or copies of GICR_PROPBASER are used when
    the GIC reads the LPI Configuration tables. However, the copy or copies
    that are used will correspond to a Redistributor on which
    GICR_CTLR.EnableLPIs == 1." Read that as a floor on how bad it can get, not
    as a licence: the only guarantee is that the chosen copy belongs to an
    enabled redistributor.

*   **Table contents have their own publication rule, with three named trigger
    points.** "To avoid unpredictable behavior, software must ensure that all
    copies of the LPI Configuration tables are identical, and all changes are
    globally observable, whenever: • GICR_CTLR.EnableLPIs is written from 0 to
    1 on any Redistributor. • GICR_INVLPIR and GICR_INVALLR are written on any
    Redistributor with GICR_CTLR.EnableLPIs == 1, if direct LPIs are supported.
    • The INV and INVALL command is executed by an ITS, in an implementation
    that includes at least one ITS." A configuration write followed by neither
    an invalidate nor an enable transition has not been published at all.

*   **There is no "it will be noticed eventually".** The specification states
    both that "A cached LPI Configuration table entry is not guaranteed to
    remain in the cache" and that "A cached LPI Configuration table entry is not
    guaranteed to remain incoherent with memory". Neither direction can be
    relied on, which is exactly why the explicit invalidation is the only way to
    publish a change.

*   **The driver's LPI ID width is a policy cap, not the architectural one.**
    `lpi_id_bits` is `min_t(u32, GICD_TYPER_ID_BITS(...), ITS_MAX_LPI_NRBITS)`
    with `ITS_MAX_LPI_NRBITS` set to 16, because the property table is sized as
    `2^lpi_id_bits` and an implementation advertising 24 bits would demand a
    16MB contiguous allocation. Where firmware pre-allocated the tables the
    driver instead reads the width back out of `GICR_PROPBASER.IDBITS` rather
    than imposing its own. A new consumer of the hardware-advertised width that
    does not apply the same cap reintroduces the allocation, and a new consumer
    that assumes the cap on the pre-allocated path contradicts firmware.

**REPORT as bugs:**
*   An affinity-derived grouping key that masks to the trailing affinity fields
    instead of the leading ones.
*   Code that allows, or a change that introduces, different LPI Configuration
    table bases across a CommonLPIAff group while LPIs are enabled.
*   An LPI configuration change with no following invalidation, or one that
    relies on the GIC re-reading memory of its own accord.
*   A sharing or pinning argument applied to the LPI Pending table.
*   Consumption of the hardware-advertised LPI ID width on a path where the
    driver has already narrowed it by policy.

## Redistributor and Distributor Write Completion

Different GIC register writes complete in different ways, and the mechanism is
not discoverable from the write itself. `arm64.md` carries the list of which
writes each RWP bit tracks; this section is about the driver-side discipline
around that list, and about what to do for the writes it does not cover.

> Polling the wrong bit reads as "no write pending" forever, so the poll
> returns immediately and the caller proceeds against a write that has not
> landed. For the registers RWP does not track, proceeding without any
> completion step at all means the write may still be sitting in an
> interconnect or buffered inside the GIC when the code that depends on it
> runs.

*   **The two RWP bits live at the same register offset and different bit
    positions.** `GICR_CTLR` is defined as `GICD_CTLR` — both are at offset
    0x0000 in their respective frames — but `GICD_CTLR_RWP` is bit 31 while
    `GICR_CTLR_RWP` is bit 3. Testing the distributor's bit number against a
    redistributor base therefore compiles, runs, reads a bit that is something
    else entirely, and reports "no write pending" essentially always. This was
    a real defect that survived eight years. The driver's defence is
    structural: `gic_do_wait_for_rwp()` takes the base and the bit as a pair,
    and the only two callers are `gic_dist_wait_for_rwp()` and
    `gic_redist_wait_for_rwp()`, each supplying the matched pair.

    ```c
    /* CORRECT: base and bit chosen together */
    gic_do_wait_for_rwp(gic_data_rdist_rd_base(), GICR_CTLR_RWP);

    /* WRONG: distributor bit number, redistributor frame — always reads 0 */
    gic_do_wait_for_rwp(gic_data_rdist_rd_base(), GICD_CTLR_RWP);
    ```

*   **For the writes RWP does not track, the completion primitive is a
    read-back.** The set/clear-active and set/clear-pending registers appear in
    neither RWP list, and there is no other completion bit for them. Two
    separate mechanisms can delay such a write: the mapping is an early
    write-acknowledge Device type, so the store may be considered done while it
    is still in an interconnect, and the GIC itself may buffer the write as
    long as it takes it into account in finite time. Reading the register back
    forces the interconnect to propagate the write and the GIC to process it
    before answering. `gic_irq_set_irqchip_state()` does exactly this, ending
    with a read-back when it wrote the set-active register, under the comment
    "Force read-back to guarantee that the active state has taken effect, and
    won't race with a guest-driven deactivation".

*   **The specification's negative is stronger for the Distributor than for the
    Redistributor, and a review should not over-claim.** `GICD_CTLR.RWP`'s
    description ends with an explicit exclusion clause: "Updates to other
    register fields are not tracked by this field." `GICR_CTLR.RWP`'s
    description has no equivalent sentence — it gives only the enumeration of
    what it does track. So on the redistributor side the correct argument is
    that the enumeration is exhaustive and does not include the active or
    pending registers, not that the specification states an exclusion. If a
    patch or a review comment claims a quoted exclusion clause for
    `GICR_CTLR.RWP`, it is quoting something that is not there.

*   **The Redistributor RWP list has a GICv4.1-only member.** Alongside
    `GICR_ICENABLER0`, the `GICR_CTLR` DPG fields and the `EnableLPIs` 1-to-0
    transition, it covers "In FEAT_GICv4p1, GICR_VPROPBASER, which clears Valid
    from 1 to 0". A GICv4.1 path that clears `GICR_VPROPBASER.Valid` and
    proceeds without the RWP poll is missing a completion the architecture
    provides.

*   **RWP tracking on the enable side is clear-only and directional.** The
    lists name `GICR_ICENABLER0` and `GICD_ICENABLER<n>` — the *clear*-enable
    registers — and never `GICR_ISENABLER0` or `GICD_ISENABLER<n>`, and the
    distributor's group enables are tracked "for transitions from 1 to 0 only".
    Disabling needs the poll; enabling does not.

**Do NOT flag:**
*   A missing RWP poll after an interrupt *enable*, a group *enable*, or a
    priority or routing write. None of those is tracked, so there is nothing to
    poll for.
*   A read-back after a set-active write, on the grounds that it is a
    pointless read. It is the completion mechanism.

**REPORT as bugs:**
*   An RWP poll whose bit constant does not match the frame of the base it is
    polling.
*   A set-active or set-pending write whose effect the caller immediately
    depends on, with no read-back.
*   A GICv4.1 `GICR_VPROPBASER.Valid` clear with no following RWP poll.

## vPE Residency, Affinity, and Doorbells

GICv4 gives a vPE a residency state in a redistributor and a doorbell for when
it is not resident. Both the transitions and the locking around them are
recurring sources of bugs, because the hardware is scanning tables
asynchronously across the transitions and because changing one vPE's state
affects interrupts that do not belong to it.

> Writing `GICR_VPENDBASER` while the redistributor is still scanning is
> UNPREDICTABLE. Losing a doorbell request means a blocked vCPU is never woken
> for an interrupt that is already pending, which presents as a guest that
> hangs rather than as a latency problem. Getting the lock order wrong between
> the per-VM and per-vPE locks deadlocks.

*   **Wait for `GICR_VPENDBASER.Dirty` to clear before descheduling.** The
    redistributor sets Dirty while it is parsing the virtual pending table
    after a schedule, and the code path between making a vPE resident and
    entering the guest is preemptible, so a deschedule can arrive mid-scan. On
    GICv4.1 the architecture is explicit in both directions: with `Valid == 0`,
    "Writing 1 to GICR_VPENDBASER.Valid is UNPREDICTABLE while
    GICR_VPENDBASER.Dirty == 1"; with `Valid == 1`, "Writing 0 to
    GICR_VPENDBASER.Valid is UNPREDICTABLE while GICR_VPENDBASER.Dirty == 1".
    Do not quote that pairing at a GICv4.0 implementation: `GICR_VPENDBASER`
    has two full field-description variants, and in the GICv4.0 one the
    `Valid == 1` sub-case reads "Writing **1**", additionally gated on
    `GICR_TYPER.Dirty == 1`. The rule in the next bullet is the
    variant-independent one and is the safer thing to cite.
    `its_clear_vpend_valid()` opens by
    waiting for Dirty to clear, under the comment "Make sure we wait until the
    RD is done with the initial scan", which makes it a full residency barrier
    rather than just a Valid-clearing helper.

*   **The whole-register rule is stricter than the Dirty rule alone.** "Writing
    a new value to any bit of GICR_VPENDBASER, other than
    GICR_VPENDBASER.Valid, when GICR_VPENDBASER.Valid==1 is UNPREDICTABLE." A
    patch that adjusts any other field of a live `GICR_VPENDBASER` — even one
    that looks advisory — is outside the architecture.

*   **Resolve an ambiguous pending answer conservatively.** After the
    deschedule, if Dirty is still set, `its_clear_vpend_valid()` forces
    `PendingLast` on rather than reporting "nothing pending". Erring toward a
    spurious wakeup is correct; erring the other way is a hung vCPU.

*   **`pending_last` is a hint, not a statement about the table.** The
    schedule path sets `PendingLast` unconditionally and explains why: there is
    no race-free way to discover that the pending table is empty, because the
    doorbell can arrive at any moment. Treat `pending_last` as "the vCPU may
    have something pending". A patch that tightens it into an exact answer is
    claiming a guarantee the hardware does not offer.

*   **The lock order for any ITSList sequence is documented and three deep.**
    `include/linux/irqchip/arm-gic-v4.h` states it: `vmapp_lock -> vpe_lock ->
    vmovp_lock`. The way this gets violated is not by taking locks in the wrong
    order at one site, but by a function that takes the vPE lock and then calls
    a helper that takes the per-VM lock. The fix shape is to hoist the outer
    lock into the caller, not to reorder locally.

*   **VMOVP under ITSList is a serialization point.** When the ITSList feature
    is in use, every ITS must observe VMOVP commands in the same order, so
    `its_send_vmovp()` takes a global lock and stamps a sequence number around
    the loop that emits one VMOVP per ITS. A change that narrows that lock to
    the individual sends, or that emits VMOVPs from a second site, breaks the
    ordering the feature requires.

*   **Changing a vPE's affinity affects interrupts that are not the vPE.** The
    driver spells this out: "changing the affinity of a vPE affects *other
    interrupts* such as all the vLPIs that are routed to this vPE. This means
    that the irq_desc lock is not enough to protect us". Any path that reads
    `vpe->col_idx` must take the vPE lock, not merely the descriptor lock of
    the interrupt it happens to be handling.

*   **A VMOVP must not be issued for a vPE that is no longer mapped, and
    `vmapp_count` is the guard.** Userspace can request an affinity change
    against a doorbell interrupt that is still visible in `/proc/irq` after the
    vPE has been unmapped. `its_vpe_set_affinity()` checks `vmapp_count`, which
    `its_build_vmapp_cmd()` maintains on both the map and unmap paths and which
    is common to GICv4.0 and GICv4.1.

*   **Not-yet-mapped is a legitimate state under lazy mapping, and the guard
    must say so.** With lazily-mapped vPEs a guest that has not yet issued a
    MAPTI has no mapping, and an affinity change then is not an error: the
    driver updates the effective affinity and returns without touching
    hardware. Only the eager-mapping case fails. This distinction was itself a
    regression introduced by the previous rule's fix, which is the reason to
    check it: a new guard on a hardware-state predicate must enumerate the
    states that are legitimately in that condition, not assume they are all
    errors.

*   **The doorbell request is one-shot and races the non-residency write.** The
    doorbell can fire at any point after the write that makes the vPE
    non-resident, including between that write and the update of the software
    flag recording whether anything was pending — so the two must be
    serialized, or a doorbell that arrives in the window is overwritten by the
    stale value and the vCPU sleeps until something unrelated wakes it. GICv4.0
    is not exposed to this because the doorbell is actively masked on guest
    entry; GICv4.1 manages doorbell delivery in hardware, so the window is real
    there.

*   **Residency is driven by `vcpu_load()`/`vcpu_put()`, so it cannot be used
    to infer intent to block.** A preemption between the put and the actual
    schedule makes the vPE resident again on the way back in, at which point
    the blocking path no longer requests a doorbell and the vCPU sleeps
    unwakeable. The WFI emulation therefore records that it is entering WFI in
    an explicit vCPU flag, sets the flag and performs the vGIC put together
    under `preempt_disable()`, and keys the doorbell request on the flag rather
    than on the residency state. Note that the same put serves two purposes at
    once — syncing the priority mask back for the pending check, and requesting
    doorbells — which is why a change to either concern has to be checked
    against the other.

*   **The ITS has no idempotent map.** Mapping a vLPI that is already mapped,
    and unmapping one that is not, are both errors the caller must exclude
    before issuing the command.

**REPORT as bugs:**
*   A `GICR_VPENDBASER` write that is not preceded by a wait for Dirty to
    clear, or a write to any field other than `Valid` while `Valid == 1`.
*   A vPE deschedule path that reports "nothing pending" when the Dirty state
    left the answer unknown.
*   A function that takes the per-vPE lock and then calls into something that
    takes the per-VM `vmapp_lock`.
*   A path that reads or acts on `vpe->col_idx` under only the interrupt
    descriptor lock.
*   A VMOVP emitted outside the serialized send path when ITSList is in use.
*   A vLPI map issued without establishing that the vLPI is not already mapped.

## LPI Lifetime and Reference Counting

Every `struct vgic_irq` for an LPI is refcounted and lives in a per-VM xarray.
The protocol around that refcount is where this subsystem's use-after-free bugs
live, and it has enough structure that a reviewer can check a new call site
mechanically. `kvm-arm64.md` covers the lock-ordering rules layered on top of
this protocol; the rules below are about the protocol itself.

> The failure mode throughout is use-after-free reached from a guest-triggerable
> race: a guest issues a DISCARD for an LPI that is still queued on a vCPU and
> immediately remaps the same INTID, or two vCPUs drain a translation cache
> concurrently. The resulting frees are of objects another CPU is still walking.

*   **A lookup must elevate the refcount before releasing whatever serializes
    refcount changes.** Returning a pointer and taking the reference afterwards
    leaves a window in which the object can reach zero and be freed. Both
    lookups in the tree have the same shape — take RCU, load, attempt to take a
    reference, and return `NULL` if the attempt fails:

    ```c
    /* CORRECT: the reference is taken before the lock is dropped */
    rcu_read_lock();
    irq = xa_load(&dist->lpi_xa, intid);
    if (!vgic_try_get_irq_ref(irq))
            irq = NULL;
    rcu_read_unlock();
    return irq;

    /* WRONG: caller takes the reference after the lookup returns */
    rcu_read_lock();
    irq = xa_load(&dist->lpi_xa, intid);
    rcu_read_unlock();
    return irq;
    ```

*   **The refcount drop and the eviction from the container must be one atomic
    step.** If the decrement happens outside the lock that guards the xarray,
    a concurrent registration of the same INTID can insert a *new* object at
    that key in the gap, and the releasing context then erases the new object
    and frees the old one. `vgic_put_irq()` closes this with
    `refcount_dec_and_lock_irqsave()` on the xarray lock, performing the
    eviction only in the branch where the decrement reached zero and the lock
    was taken.

*   **Where the atomic form is unavailable, the API splits and the caller
    inherits an obligation.** Callers already holding a raw spinlock cannot
    take the xarray lock, so they use the no-release variant, which is marked
    `__must_check`, accumulate its results across the loop, and call the
    deferred release once the raw lock has been dropped. Both loops that do
    this — the AP-list pruning path and the pending-LPI flush path — follow the
    same shape. A new caller of the no-release variant that discards the return
    value leaks the object permanently.

    ```c
    /* CORRECT: accumulate, then release outside the raw lock */
    raw_spin_lock_irqsave(&vgic_cpu->ap_list_lock, flags);
    list_for_each_entry_safe(irq, tmp, &vgic_cpu->ap_list_head, ap_list) {
            ...
            deleted |= vgic_put_irq_norelease(vcpu->kvm, irq);
    }
    raw_spin_unlock_irqrestore(&vgic_cpu->ap_list_lock, flags);
    if (deleted)
            vgic_release_deleted_lpis(vcpu->kvm);
    ```

*   **Orphans are identified by refcount, never by a flag on the object.** A
    "release is pending" flag stored in the object is itself a use-after-free
    once a concurrent path is allowed to free that object, which is why the
    deferred-release walk tests the refcount directly and no such flag exists in
    the structure. A patch that reintroduces one is reintroducing the bug.

*   **A reservation taken before the lock is not a reservation that survives
    the gap.** Pre-reserving an xarray slot outside the lock and then storing
    under it with a zero gfp assumes nothing removed the node in between, and
    something can: a concurrent release erases the entry and frees the node, and
    the store then fails with `-ENOMEM`. The store under the lock passes a real
    (non-sleeping) gfp for this reason.

*   **When draining a container that other contexts may drain concurrently, put
    what the erase returned, not what the iterator handed you.** The
    translation-cache invalidation is reachable from three paths that hold three
    different locks and exclude one another not at all. Each erases atomically
    and drops the reference only for the entry it actually removed, under the
    comment "Only the context that erases the entry drops its cache ref."
    Putting the iterated pointer instead drops one cache reference several
    times over.

    ```c
    /* CORRECT: only the context that removed the entry drops its reference */
    xa_for_each(&its->translation_cache, idx, irq) {
            irq = xa_erase(&its->translation_cache, idx);
            if (irq)
                    vgic_put_irq(kvm, irq);
    }

    /* WRONG: every racing context puts the same entry */
    xa_for_each(&its->translation_cache, idx, irq) {
            xa_erase(&its->translation_cache, idx);
            vgic_put_irq(kvm, irq);
    }
    ```

*   **A best-effort cache still has to balance its references.** The cache
    insertion takes a reference, then drops it again if the store returned an
    error, and separately drops the reference on any entry it displaced when
    two CPUs raced to cache the same translation. Deliberately swallowing the
    error — the cache is best effort, so the caller is not told — is correct and
    is commented as such; leaking the reference is not.

*   **`xa_release()` belongs outside the xarray lock.** The registration path
    drops the lock before releasing a reserved-but-unused slot, which is why
    that function is structured without a shared error label.

*   **SPIs are bounded, LPIs are keyed.** The interrupt lookup range-checks SPIs
    against the configured count and applies `array_index_nospec()` before
    indexing the array, while LPIs go through the xarray. A new path that treats
    an LPI INTID as an array index has chosen the wrong half of that function.

*   **A guest-supplied INTID reaching an invalidation or self-injection
    register must be sanitized in every dimension the emulation does not
    implement.** The redistributor's LPI invalidate handler is the worked
    example: it discards writes to the upper half of the register (those are for
    vPEs, which the emulation does not support), returns early unless LPIs are
    enabled, and rejects any INTID below the LPI base. Each of the three is a
    separate check for a separate way the guest can name something the handler
    was not written for. When reviewing a newly forwarded or newly emulated
    register that carries an interrupt identifier, ask what the guest can make
    the GIC do with an arbitrary value in each field; forwarding a raw value is
    a decision to justify, not a default.

**REPORT as bugs:**
*   A lookup that returns an interrupt structure without having taken a
    reference under the same lock or RCU section that made the lookup safe.
*   A refcount decrement and a container eviction that are not a single atomic
    step, or the decrement performed outside the lock the eviction needs.
*   A discarded return value from the no-release put, or a raw-spinlock loop
    that uses it without a following deferred release.
*   Any per-object flag used to mean "this is awaiting release".
*   A container drain that puts the iterated pointer rather than the value the
    erase returned.
*   An emulated register handler that accepts a guest-supplied INTID without
    range-checking it and without rejecting the fields the emulation does not
    implement.

## The AP List and Interrupt Migration

Each vCPU has an active-pending list of interrupts it is responsible for. The
pruning walk migrates interrupts whose target has changed, and to do that it
must drop and retake locks — which is where its bugs come from.

> Every bug in this area is a use-after-free or a corrupted list reached by a
> guest doing something ordinary at an unlucky moment: disabling LPIs on one
> vCPU while another migrates an interrupt, or a maintenance interrupt arriving
> slowly enough that the hardware state has moved on.

*   **After retaking the locks, re-validate ownership as well as affinity.**
    Checking only that the interrupt's target is still this vCPU is not enough,
    because a concurrent path can take the interrupt off the list without
    touching its target: the pending-LPI flush clears the owning vCPU pointer
    but leaves enabled, pending and target state untouched, so the target oracle
    still answers the same and the deletion runs a second time on an entry
    already removed. The check must be "still targeted here **and** still ours".

*   **Take a reference before dropping the locks.** With the locks dropped, the
    interrupt can reach a zero refcount and be freed before the retry
    reacquires them. The walk takes an explicit reference for the duration,
    under the comment "make sure it is kept alive while locks are dropped".

*   **Pending state is not carried across a migration.** There is no
    architectural expectation that pending state survives a change of target,
    so the migration path deliberately does not try to preserve it. A patch that
    adds pending-state transfer to make migration "lossless" is adding
    complexity for a property the architecture does not promise, and the
    attempt to preserve it was itself part of a use-after-free.

*   **Two-vCPU list locking is ordered by vCPU ID, smallest first**, with the
    second acquired as a nested lock. Any new path that needs both lists must
    use the same ordering rather than inventing one.

*   **EOIcount deactivations must start after the last interrupt that made it
    into the list registers.** EOIcount counts deactivations of interrupts that
    are *not* in an LR. If the maintenance interrupt is slow enough that further
    interrupts were activated out of the LRs before the exit, walking the AP
    list from the head deactivates interrupts that are in LRs — the wrong ones —
    and the guest loses interrupts. The walk therefore starts after a recorded
    marker for the last interrupt loaded into an LR.

*   **In the nested case the physical interrupt has already been deactivated by
    the list register's hardware bit, and a second deactivate is not harmlessly
    redundant.** The shared deactivation helper therefore performs the physical
    deactivation only when the hardware bit is set *and* the vGIC is not in the
    nested state. The reason it is not merely redundant is that on at least one
    implementation, deactivating an interrupt that is not active but is the
    highest-priority pending interrupt loses the pending state and prevents
    delivery of future interrupts. Treat a duplicated deactivation as a defect
    even where the architecture alone would tolerate it.

**REPORT as bugs:**
*   A revalidation after a lock drop that checks affinity but not continued
    ownership.
*   Any path that drops the interrupt lock and the list lock around a
    manipulation without holding a reference across the gap.
*   A second AP-list acquisition ordered by anything other than vCPU ID.
*   An EOIcount deactivation walk that starts from the head of the list.

## List Registers

The list registers hold the virtual interrupts presented to a guest, and the
architecture places uniqueness constraints on their contents. Two of those
constraints are easy to conflate because they look alike and are in different
sections.

> Violating either uniqueness rule is UNPREDICTABLE, and the observed symptom is
> a guest that locks up rather than anything that identifies the cause.

*   **Two list registers must not hold the same virtual INTID unless both are
    Invalid.** The architecture states that "Behavior is UNPREDICTABLE if two or
    more List Registers specify the same vINTID when: • ICH_LR<n>_EL2.State ==
    0b01. • ICH_LR<n>_EL2.State == 0b10. • ICH_LR<n>_EL2.State == 0b11." Only
    the Invalid state is exempt. This is what makes multi-source software
    interrupts awkward: distinct sources are architecturally distinct interrupt
    events but must not occupy several list registers at once, so the emulation
    injects one per entry and arranges a maintenance interrupt to deliver the
    rest.

*   **The physical INTID rule is a different rule.** In the separate list of
    programming errors that result in UNPREDICTABLE behaviour, the architecture
    names "Having two or more interrupts with the same pINTID in the List
    registers for a single virtual CPU interface." Two list registers may carry
    the same *physical* INTID in some other arrangement no more than they may
    carry the same virtual one, but the two statements are in different
    sections, constrain different fields, and cannot be cited for each other.
    If a patch or review comment cites one section for the other's claim, the
    citation is wrong even if the conclusion happens to hold.

*   **The same programming-error list carries the hardware-bit consistency
    rule.** It is an error to have a list register entry with the hardware bit
    set, associated with a physical interrupt, in the active or pending state,
    when the distributor does not have the corresponding physical interrupt in
    the active or active-and-pending state. A mapped interrupt whose two halves
    have drifted apart is therefore not merely inconsistent bookkeeping.

*   **The list also constrains EOImode-0 operation**: it is an error to have an
    active interrupt in the list registers whose priority is not set in the
    corresponding active priorities register, or to have two active interrupts
    with the same preemption priority.

*   **GICv4 adds two more entries to that list**, both about the same virtual
    interrupt arriving by two routes: a valid list register and an ITS mapping
    for a vPE that use the same virtual INTID, and, under GICv4.1, a valid list
    register whose virtual INTID is a software-generated interrupt that is also
    generated for the vPE through the ITS. Code that can inject the same
    interrupt through both the list registers and direct injection needs to
    exclude the overlap.

*   **Special INTIDs and the LPI range have their own constraints.** A virtual
    INTID in 1020-1023 in a list register whose state is not Inactive is
    UNPREDICTABLE, and specifying a virtual INTID in the LPI range while
    `ICC_SRE_EL1.SRE == 0` is UNPREDICTABLE.

**REPORT as bugs:**
*   Any path that can place the same virtual INTID in two list registers in a
    state other than Invalid.
*   A list register with the hardware bit set whose physical counterpart is not
    correspondingly active in the distributor.
*   Injection of a virtual interrupt through the list registers for a vPE that
    can also receive it through the ITS.

## Mapped Interrupts

A mapped interrupt is one whose state is partly in hardware: the guest's
deactivation of the virtual interrupt also deactivates the physical one. That
split is the source of a recurring family of stale-state bugs.

> The state software holds and the state hardware holds can disagree at any
> point where only one of them was updated, and the resulting symptoms are
> spurious injections, interrupts that are lost across a reset, and — for the
> priority-mask case — a vCPU that blocks forever.

*   **Resample the hardware pending state on deactivation.** When the guest
    deactivates a mapped level interrupt, the physical interrupt is deactivated
    with it, but the software pending state may be stale: it was sampled at
    entry and the guest may since have removed the condition. Without a
    resample the interrupt is injected again spuriously.

*   **The hardware pending state is readable only while the vCPU is loaded**,
    so the userspace-facing accessor cannot be the guest-facing one. A userspace
    read that falls through to the guest accessor reads hardware state from a
    context where it is not available. The emulation keeps a separate
    userspace read accessor for exactly this reason.

*   **Mapped interrupts cannot be reset through the userspace path** because
    their state lives in hardware; the owning subsystem (the architected timer,
    today) resets them explicitly on VM reset instead. A patch that adds a
    userspace reset path for them is working around the wrong end.

*   **The guest's view of the priority mask is in hardware until the vCPU is
    put, and the accessor reads a shadow copy.** `ICH_VMCR_EL2` is left loaded
    across the run loop; `vgic_v3_get_vmcr()` reads `cpu_if->vgic_vmcr`, the
    saved copy, not the live register. So any host-side computation that
    depends on the guest's priority mask is reading whatever the last put
    saved. The computation that matters is the pending check, which compares
    `irq->priority < vmcr.pmr` — a guest that masks interrupts, is preempted
    and rescheduled, then unmasks and executes WFI would otherwise be evaluated
    against its old masked value, report nothing pending, and block with an
    interrupt waiting. The WFI emulation therefore performs a full vGIC put
    before halting rather than relying on the scheduler to do it, and says so:
    "Sync back the state of the GIC CPU interface so that we have the latest
    PMR and group enables." A new path that evaluates guest pending state while
    the vCPU is still loaded reintroduces the stale read.

*   **A virtual software-generated interrupt backed by GICv4.1 hardware needs
    its pending state written through.** When userspace sets the pending state
    of such an interrupt, leaving it in the software latch loses it, because the
    interrupt is delivered from hardware. The write-through matters mainly
    across a VMM-driven reset of a running VM, which is why it is easy to miss.

**REPORT as bugs:**
*   A mapped level interrupt deactivated without the software pending state
    being resampled.
*   A userspace accessor that reads hardware-resident interrupt state through
    the guest-facing path.
*   A host-side evaluation of the guest's priority mask on a path that can run
    before the virtual control register has been synced back.

## ITS Table Save and Restore

KVM's ITS keeps its device and interrupt translation tables in guest memory in
an architected format, so that migration can save and restore them. The restore
side parses attacker-influenced data and is the natural place for validation to
be missing.

> A restore path that accepts what the live path rejects lets migration
> introduce a state the guest could never have produced, and the values involved
> — table sizes, event-ID widths, table offsets — are the ones that go on to
> bound loops and index tables. A save path that writes a stale entry produces
> an image that restores into something that was never live.

*   **A restore path must reject what the live command path rejects.** The
    device-table restore is the worked example: the live device-mapping command
    refuses an EventID width wider than the virtual ITS advertises, and the
    restore path did not, so an out-of-range width was stored and then converted
    into an oversized table-scan range. The fix mirrors the live check, with the
    comment "Mimic the MAPD behaviour and reject invalid EID bits". For any new
    restore handler, put it side by side with the live handler for the same
    object and enumerate what the live one refuses.

*   **An unmap must invalidate the guest-memory entry, not only the in-kernel
    object.** When a device is unmapped or a translation discarded, the
    corresponding table entry in guest memory has to be cleared. Leaving it
    valid means a subsequent save does not write it (the object is gone) while a
    subsequent restore reads it (the memory still says valid), so a
    save-and-restore cycle resurrects an entry that was never live.

*   **Two-level table scans must stop at the end of the current level 2 table.**
    The scan advances by an offset read out of each entry, and the remaining
    length is unsigned: a large forward offset makes the subtraction wrap to a
    huge positive value, and the scan continues from a bad guest address instead
    of returning to the next level 1 entry. The check must come before the
    subtraction:

    ```c
    /* CORRECT: bound first, then advance */
    byte_offset = next_offset * esz;
    if (byte_offset >= len)
            break;
    id  += next_offset;
    gpa += byte_offset;
    len -= byte_offset;

    /* WRONG: unsigned len wraps and the scan walks off the table */
    len -= next_offset * esz;
    if (!len)
            break;
    ```

*   **Guest-memory entry accesses go through helpers that check the declared
    entry size against the type at the call site.** The ABI declares an entry
    size per table; the C code passes a concrete type. A mismatch writes the
    wrong number of bytes into guest memory, so the helpers assert the two agree
    — at build time where there is only one ABI, and at run time where there
    could be more. A new save or restore site that open-codes the guest access
    loses that check.

*   **A table walk that finds no interrupt for an identifier must continue, not
    fail.** An LPI can be legitimately unmapped by a different ITS while a walk
    is in progress, so both the move-all handler and the pending-table sync skip
    such identifiers and carry on. Turning that into an error aborts a migration
    for a state the guest is allowed to be in.

**REPORT as bugs:**
*   A restore handler that omits a validation its live counterpart performs.
*   An unmap that frees the in-kernel object without clearing the corresponding
    guest-memory table entry.
*   Unsigned length arithmetic in a table walk performed before the bound is
    checked.
*   An open-coded guest-memory table access that bypasses the entry-size
    checking helpers.

## vGIC Creation, Readiness, and Teardown

The vGIC is created, configured, made ready, and torn down through several
ioctls and vCPU lifecycle hooks. Ordering and unwind bugs here are not about
interrupt delivery; they are about a vCPU observing a half-built or half-torn
distributor.

> Publishing readiness before the state it advertises lets a vCPU enter the
> guest against an unregistered MMIO region. Asymmetric unwind leaves
> registrations behind for objects that no longer exist, which is a
> use-after-free the next time anything walks them.

*   **Readiness is published last, and the ordering is explicit.** The
    distributor's ready flag must be set after the MMIO registration it
    advertises. Setting it earlier and registering afterwards leaves a window
    in which a vCPU can start running against a distributor whose MMIO is not
    yet visible. The flag is published with a release store and consumed with
    an acquire load, which is the detail to check when reviewing a change here:
    the ordering used to be left implicit, borrowed from the full barrier
    inside the MMIO registration's `synchronize_srcu()`, and was made explicit
    afterwards. Borrowing it again would be a regression, and not only
    stylistically — the GICv5 model registers no distributor MMIO region at
    all, so on that path there is no `synchronize_srcu()` to borrow from.

*   **Guest-visible addresses are fixed at creation, not at finalization.** The
    CPU interface and redistributor addresses must be established when the vGIC
    is created. Re-deriving or resetting them at finalize time changes state the
    guest may already be using.

*   **A failed initialization must not eagerly tear down**, and a failed vCPU
    creation must unregister exactly what it registered. The recurring shape is
    an unwind that is not the inverse of the setup: a redistributor left
    registered for a vCPU that failed to be created, or a vCPU left associated
    with a redistributor region across teardown. When reviewing a change to
    either path, walk the setup and the unwind side by side and check that each
    registration has exactly one matching unregistration on every exit.

*   **The configuration lock's correct scope is not "always held".** It protects
    vGIC state, but it must not be held across MMIO unregistration — one fix
    added it around a CPU-interface teardown and another removed it from around
    redistributor unregistration. The rule to apply is therefore about scope and
    ordering against the KVM device machinery, not about presence: check what a
    new critical section calls into, and specifically whether it can reach the
    MMIO bus registration path.

**REPORT as bugs:**
*   A readiness or "initialized" flag set before the state it advertises is
    published.
*   An error path that leaves a redistributor or CPU interface registered for an
    object that was not successfully created.
*   A new configuration-lock critical section that spans a call into MMIO
    registration or unregistration.

## Priority, Groups, and Pseudo-NMI

The GICv3 priority model carries the kernel's pseudo-NMI support, and it
interacts with the security state in ways that are not visible at the call
site. `arm64.md` owns the `ICC_PMR_EL1` synchronization rules; this section is
about the value in the register and the ordering around acknowledgement.

> Comparing priorities on the wrong scale misclassifies an NMI as a normal
> interrupt or the reverse. Missing the synchronization between acknowledging an
> interrupt and handling it lets the handler run against stale state, which for
> IPIs means reading data the sender wrote before signalling.

*   **There must be a context synchronization event between the acknowledge and
    the handling, and it must not be left implicit.** Where the driver runs with
    EOI mode 1 it writes the end-of-interrupt register right after the
    acknowledge, and that write happens to provide the synchronization — but
    where it does not, nothing else would. The ack-completion helper therefore
    issues the barrier unconditionally, outside the conditional write. Pseudo-NMI
    support originally missed this because it duplicated the acknowledge path
    without the barrier.

    ```c
    /* CORRECT: the barrier is unconditional, the EOI write is not */
    if (static_branch_likely(&supports_deactivate_key))
            write_gicreg(irqnr, ICC_EOIR1_EL1);
    isb();

    /* WRONG: the barrier only happens in EOI mode 1 */
    if (static_branch_likely(&supports_deactivate_key)) {
            write_gicreg(irqnr, ICC_EOIR1_EL1);
            isb();
    }
    ```

*   **The IPI sender needs a barrier before the interrupt and one after.**
    Stores to Normal memory that the receiving CPU will read must be made
    visible before the interrupt is signalled — and it must be a `dsb`, not a
    `dmb`, because a write to a system register is not a memory access and a
    `dmb` does not order the memory stores against it. Afterwards, an `isb`
    forces the system-register writes themselves to be executed. The receiving
    side is not automatically safe either: a CPU can speculatively enter the
    interrupt entry path and prefetch shared data before the acknowledge that
    identifies the interrupt, so the ordering between reading the acknowledge
    register and reading the shared data has to be established too.

*   **Distributor priorities and CPU-interface priorities are two scales, and
    the driver keeps two sets of constants for them.** Whether the two scales
    coincide depends on `GICD_CTLR.DS` and `SCR_EL3.FIQ` together, and only one
    of the three reachable combinations makes them differ: with security
    enabled and Group 0 deliverable to the non-secure world, the interrupt
    priorities are presented in the non-secure view (a written value
    right-shifted by one with the top bit set) while `ICC_PMR_EL1` is not. The
    driver resolves this once at init rather than at each use — `gic_prio_init()`
    pre-converts the distributor-side constants into the non-secure view in
    exactly that case, so that `dist_prio_irq` and `dist_prio_nmi` are always
    the right values to program into `GICD_IPRIORITYR`/`GICR_IPRIORITYR0` while
    the `GICV3_PRIO_*` constants remain the right values to compare against
    `ICC_PMR_EL1` and `ICC_RPR_EL1`. Its explanatory comment carries the full
    three-row table and is worth reading before touching anything here. The
    reviewable rule is that a priority value must be used on the side it was
    prepared for: a new distributor or redistributor priority write that uses a
    raw `GICV3_PRIO_*` constant instead of the `dist_prio_*` variable is wrong
    on precisely the configurations that are hardest to test on.

*   **The software-generated interrupt ID field is four bits.** The
    architecture defines "INTID, bits [27:24] — The INTID of the SGI", and the
    driver's mask is correspondingly `0xf` shifted to bit 24. A wider mask, or a
    signed one, lets an out-of-range value through — which matters most in the
    KVM emulation of the register, where the value is guest-supplied.

*   **A general system interrupt must never translate to a software-generated
    one.** Software-generated interrupts are handled earlier in the domain
    translation, so a later translation producing one indicates a firmware
    description that is wrong. Report it explicitly rather than accepting it.

*   **GICv3 system registers are only usable once the system register interface
    has been enabled**, and every path that reaches code touching them must have
    done so first: primary boot, secondary CPU bring-up, and resume from power
    management. Accesses before that are UNDEFINED, and on a configuration where
    nothing else enabled the interface earlier they crash the boot.

*   **The driver must not assume it owns the non-secure side of a
    two-security-state system.** Interrupt group configuration has to follow the
    security state the hardware actually reports, including the case of a single
    security state; getting it wrong means interrupts are simply never
    delivered.

**Do NOT flag:**
*   A comparison of `ICC_RPR_EL1`'s value directly against a `GICV3_PRIO_*`
    constant with no shift applied. Once the distributor-side constants have
    been pre-converted at init, the CPU-interface scale is the one those
    constants are already on, so the comparison is correct as written.

**REPORT as bugs:**
*   An interrupt acknowledge path where the synchronization before handling
    depends on an EOI mode or another conditional write.
*   An IPI send path that uses a `dmb`-class barrier to order Normal-memory
    stores against the system-register write that signals the interrupt.
*   A distributor or redistributor priority write that uses a CPU-interface
    priority constant instead of the pre-converted distributor-side value.
*   A software-generated-interrupt ID extracted with a mask wider than four
    bits or with a signed type.
*   Code that accesses GICv3 system registers on a path that can run before the
    system register interface is enabled.

## GICv5 Hardware Running a GICv3 Guest

GICv5 hardware may implement a GICv3-compatible **virtual** CPU interface, so a
GICv3-aware guest can run on a machine with no GICv3 anywhere in it. The
boundary matters here because roughly half of this guide stops applying on such
a system while the other half continues to apply unchanged. `gic-v5.md` covers
the GICv5 side; what follows is what a reviewer holding the GICv3 model needs.

> Assuming the compatibility extends past the CPU interface leads to review
> comments asking for GICv3 system-level behaviour that no hardware on the
> machine provides. Assuming it extends nowhere leads to the opposite: treating
> the shared vgic emulation code as dead on such a system when it is exactly
> what a compatibility guest runs on.

*   **The compatibility is a virtual CPU interface and nothing else.** There is
    no distributor, no redistributor, and no GICv3 ITS underneath: the guest's
    entire MMIO view is emulated in software by the same vgic-v3 code a GICv3
    host uses, while the physical routing beneath it remains native GICv5.

*   **Consequently the driver-side rules in this guide do not apply on such a
    system, and the emulation-side rules do.** The GICv3 host driver is not
    probed at all, so the command queue, RWP polling and redistributor
    programming sections describe hardware that is not present. The list
    register rules, the LPI refcounting rules, the AP list rules and the ITS
    table save and restore rules all continue to apply, because that code is
    shared and is what the compatibility guest is running on.

*   **The virtual EOI mode bit still selects between combined and split EOI,
    exactly as on GICv3.** Under legacy operation the virtual control
    register's EOI mode field is the one that decides: with it clear, a write
    to the virtual end-of-interrupt register performs both priority drop and
    deactivation (and accesses to the virtual deactivate register are
    UNPREDICTABLE); with it set, the end-of-interrupt register drops priority
    only and the deactivate register deactivates. So a compatibility guest
    coupling the two is correct only in the first case, and checking the mode
    bit is part of reviewing such a path. `gic-v5.md` covers what changes on
    the native side.

**REPORT as bugs:**
*   Code that infers the existence of a GICv3 distributor, redistributor or ITS
    from the presence of the GICv3 compatibility feature on GICv5 hardware.

## Quick Checks

*   **Locks belong at the top of a set of operations that all need them.** The
    vCPU-affinity entry point takes its lock once at the top rather than having
    each callee take it, because a callee that reads mapping state without the
    lock races the unmap path. When a function's callees all need the same lock,
    hoisting it is the fix, not sprinkling.
*   **Devices sharing a device identifier share one device structure.** Devices
    behind a PCI bridge, or on hardware that aliases identifiers, resolve to the
    same ITS device, so lookup-then-allocate needs a per-ITS mutex or two
    concurrent probes double-allocate. A shared device is deliberately never
    freed, because its lifecycle is not tracked.
*   **Page allocation helpers in this driver take an order, not a count.**
    Passing 1 where 0 was meant allocates two pages and leaks one — check the
    parameter's meaning at every call site rather than reading the argument as a
    quantity.
*   **The LPI free-range list must stay sorted ascending, or range merging
    silently stops working.** The allocator keeps free LPI IDs as a list of
    `{base, span}` ranges and relies on the sort order to coalesce adjacent
    ranges on free. Break the order and nothing crashes and nothing is
    reported: the ranges simply stop merging, so the free list fragments and
    allocation of a large contiguous block starts failing on a system that has
    plenty free. The release path maintains the invariant by walking backwards
    to the insertion point rather than sorting, then attempting a merge against
    **both** neighbours — a change that inserts without preserving the order,
    or that merges against only the following neighbour, reintroduces the
    fragmentation with no symptom at the point of the bug.
*   **Interrupt-identifier exhaustion is an error to propagate.** Continuing
    past a failed allocation with nothing allocated produces a device that
    appears set up and delivers nothing.
*   **Non-coherent designs need the table flushed before the base register is
    written**, not after, and the GICv4 redistributor tables need the same
    shareability and cacheability treatment as the GICv3 ones. The GICv4 half
    was overlooked when non-coherent support was added, so a new table type is
    the thing to check.
*   **CPU hotplug notifier callbacks run in atomic context.** Allocations on the
    per-CPU ITS initialization path must not sleep, which is easy to miss
    because the same allocation is fine on the boot path.
*   **An introspection path must not assume the interrupt it is walking still
    exists.** The vgic debug iterator in `vgic-debug.c` walks INTIDs rather than
    live objects, so a lookup partway through the walk can legitimately return
    `NULL` — an LPI can be unmapped while the file is being read. Its show
    function therefore looks the interrupt up, returns early if the lookup
    fails, and puts a reference only on the path where it took one. Any new
    read-only walker over interrupt state inherits all three obligations.
*   **A userspace-reachable accessor must tolerate state that has not been
    configured yet.** Userspace can read any register at any time, including
    before the ioctls that configure the device have run; a guest cannot,
    because it has to configure the device before using it. So a computed
    read-side field must handle the unconfigured case rather than assume the
    setup order. The redistributor type register's "last" bit is the worked
    example: computing it dereferenced the redistributor region descriptor,
    which userspace could read before any base address had been set. Note
    which fix survived — the field was first dropped from the userspace view
    entirely, and that was reverted a few months later in favour of making the
    computation safe (the helper now returns false when the descriptor pointer
    is null) so that the bit is architecturally correct for userspace too. Do
    not cite the removal as precedent for hiding a field from userspace;
    upstream's settled position is that compliance wins and the read side gets
    hardened.
*   **A userspace write handler must take the field from the value being
    written.** Extracting it from the current register contents instead makes
    the write a no-op that returns success — the identification register's
    revision field had this bug, so userspace could never select a revision for
    migration compatibility, and nothing reported an error.
*   **A translation cache entry must not be created for a directly-injected
    interrupt.** The cache is a software translation shortcut; an interrupt
    delivered by hardware to a vPE does not go through it, and caching it
    creates a reference to state the software path will not maintain.
