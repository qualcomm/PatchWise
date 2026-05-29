### 3f.6 Hardware Topology and Bus Consistency

- **Parent/child power ordering:** do not access child devices before the parent
  bus or power domain is enabled; implicit bring-up ordering is fragile.
- **Deferred probe:** dependencies such as clock providers, PHYs, power domains,
  or IOMMUs must return `-EPROBE_DEFER` when unavailable. Prefer
  `dev_err_probe(dev, ret, "...")` over bare deferral so reasons are logged when
  appropriate.
- **Kconfig dependency guard:** new or expanded hardware use must have matching
  `depends on`/`select` coverage for required infrastructure such as `OF`,
  `HAS_IOMEM`, `PM`, `PM_RUNTIME`, `COMMON_CLK`, reset, GPIO, DMAengine, IOMMU,
  interconnect, or OPP. Flag compile-risk gaps as `[CONCERN]` unless an existing
  dependency chain proves the symbol is always available.
- **Bus address and size correctness:** new register offsets, DMA ranges, or IRQ
  specifiers must match the hardware map and existing drivers for the same SoC/IP.
- **Unique hardware IDs:** DMA channels, IRQs, trace IDs, slots, and similar IDs
  must be unique in scope and allocated through subsystem allocators, not
  hard-coded.
- **`EXPORT_SYMBOL` vs `EXPORT_SYMBOL_GPL`:** new driver-internal kernel APIs
  should use `EXPORT_SYMBOL_GPL` unless intentionally available to out-of-tree or
  proprietary modules. New `EXPORT_SYMBOL` for internal APIs is `[CONCERN]`.
- **Debugfs test knobs with hardware side effects:** a debugfs boolean that masks
  hardware IRQs, disables error handling, or changes recovery behavior must have
  documented one-shot semantics or a restore path when the user clears it. Do not
  silently clear user-controlled test flags in recovery unless the interface says
  they are one-shot.
- **Firmware packet dimensions:** for firmware command builders, every accepted
  command/property case must update payload, size/count, and selector fields
  consistently. A new case that only `break`s is malformed unless the protocol
  explicitly defines zero payload.
- **PHY/link arithmetic:** for link-frequency or bus-rate formulas, check units
  and encode/decode ratios against the hardware spec and helper API convention.
  C-PHY/DPHY-style symbol-rate conversions are high risk because inverted ratios
  can overclock or misprogram hardware.
- **DT resource consumed only via a framework the bound driver bypasses:** a DT
  property is effective only if the driver bound to that node executes the code
  path that reads it. When CPU or device nodes gain `operating-points-v2` tables,
  `interconnects`, `opp-peak-kBps`/bandwidth votes, or similar
  framework-mediated resources, name the bound driver and the exact call that
  consumes the data. The recurring trap is firmware-managed DVFS: drivers that
  drive frequency through firmware (SCMI cpufreq via `perf_ops->freq_set()`,
  cpufreq-hw/EPSS, and similar firmware-DCVS paths) fetch operating points from
  firmware and call neither `dev_pm_opp_of_add_table()` nor
  `dev_pm_opp_set_rate()`, so the OPP core never fires the interconnect/bandwidth
  scaling the DT implies. If the commit message claims DDR/LLCC/bus or
  performance scaling but the active driver bypasses the consuming framework, the
  DT properties are inert dead data; file `[CONCERN]`, or `[BUG]` when the commit
  explicitly promises behavior the bound driver cannot perform.
