## Step 3f — Hardware Engineering Perspective

Apply this checklist whenever a patch touches hardware-facing code or hardware
resource contracts in any subsystem, including DT/DTS resource contracts for
clocks, resets, power domains, interrupts, DMA, interconnects, OPPs, address
ranges, or bus/topology relationships. It catches hardware-state invariants that
pure software diff review can miss.

**Trigger conditions:** apply Step 3f when the diff touches any of:
- MMIO/system-register access: `readl*`, `readb*`, `readw*`, `readq*`,
  `writel*`, `writeb*`, `writew*`, `writeq*`, `ioread*`, `iowrite*`, assembly,
  `mrs`, or `msr`.
- `regmap_*` register access, including `regmap_read/write/update_bits`, bulk,
  raw, and noinc variants; these are hardware register accesses too.
- Probe/remove/shutdown; system/runtime suspend/resume; PM notifiers;
  `pm_runtime*`, `pm_clk_*`, `dev_pm_*`, `devm_*`; IRQ registration/handlers;
  DMA/DMAengine setup or teardown; GPIO/pinctrl helpers; SMP calls touching
  hardware or per-CPU software state; CPU hotplug; clocks, regulators, resets,
  power domains, interconnects/ICC, OPP/performance states, `set_rate`,
  transfer setup helpers such as `setup_*xfer`, or topology.

**Sub-section N/A rule:** for each sub-section 3f.1–3f.6, first check whether
its trigger appears. If not, write the Hardware Engineering Notes bullet as
`N/A — <reason>` and skip that subsection. Do not fabricate findings for absent
triggers.

**Conditional fragments.** The 3f.1–3f.6 rule tables are loaded as separate
fragment refs only when the diff fires the matching trigger. The assembler
appends them after this base in this order:

- `refs/hardware-eng-pm-register-access.md` — 3f.1 Device Power State Before
  Register Access (PM runtime, MMIO, regmap, suspend/resume restore).
- `refs/hardware-eng-resource-lifecycle.md` — 3f.2 Hardware Resource Lifecycle
  Symmetry (IRQ/DMA/clock/regulator/reset acquire/release, devm vs non-devm,
  cross-instance pointer lifetime).
- `refs/hardware-eng-programming-sequence.md` — 3f.3 Hardware Programming
  Sequence (enable/disable order, barriers, recovery before publication).
- `refs/hardware-eng-percpu-hotplug.md` — 3f.4 Per-CPU and Hot-Pluggable
  Hardware (per-CPU access, SMP calls, hotplug callbacks).
- `refs/hardware-eng-irq-dma-context.md` — 3f.5 Interrupt and DMA Context
  Constraints (atomic context, threaded IRQ boundary, DMA mapping, level-IRQ
  re-enable, partial status clear).
- `refs/hardware-eng-topology-bus.md` — 3f.6 Hardware Topology and Bus
  Consistency (deferred probe, Kconfig deps, EXPORT_SYMBOL, OPP/genpd
  consumption, firmware-managed DVFS).

Fragments that are not loaded simply do not apply to this patch. If the diff
touches hardware state in a way none of the listed triggers match (a novel
shape), still surface the hazard from this base preamble's trigger list and
record the audit in Hardware Engineering Notes; use the fragment naming above
to point reviewers at the matching rule family.
