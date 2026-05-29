# Rule: probe-defer-export-topology

## Trigger

Driver code changes deferred-probe handling (`dev_err_probe`, `-EPROBE_DEFER`),
`EXPORT_SYMBOL*`, framework provider registration (PHY/genpd/interconnect/OPP),
`MODULE_FIRMWARE`, debugfs hardware knobs, or Kconfig `depends on`/`select`.

## Must Check

- Is an unavailable dependency handled with `-EPROBE_DEFER` (via `dev_err_probe`) rather than a hard failure that races bring-up order?
- Is a newly exported internal API `EXPORT_SYMBOL_GPL` rather than plain `EXPORT_SYMBOL`, unless the symbol is deliberately non-GPL?
- Does Kconfig declare the dependencies the code now uses (OF, IOMEM, PM, CLK, DMA, IOMMU, framework) to avoid build/link breakage?
- Does every `select X` clause inherit the hard `depends on` chain from `X`'s own Kconfig entry? `select Y` where `Y depends on Z` and the selecting symbol does NOT also `depends on Z` produces a Kbuild "unmet direct dependencies" warning, may force-enable `Y` despite `Z=n`, and breaks at link time when `Y`'s code calls APIs that `Z` provides. Trace each new `select` in the diff to its target's `depends on` line and confirm the depends are inherited (or named in the selecting entry's own `depends on`).
- Does a debugfs knob with a hardware side effect have a restore path, so a test flag is not silently left set?
- If the driver routes a resource through firmware instead of the kernel framework, are the corresponding DT/OPP/interconnect properties either consumed or not claimed?

## Evidence Needed

- The probe-error path, export macro, Kconfig stanza, or debugfs knob changed.
- The dependency the change relies on.

## Safe Dismissal

Dismiss when source shows EPROBE_DEFER on missing deps, GPL export (or
intentional non-GPL), matching Kconfig deps, and restore paths for HW knobs.

## Finding Template

```text
[CONCERN] Probe-defer / export / topology dependency issue
File: <path>:<line>
Rule: probe-defer-export-topology
Evidence: <probe path, export macro, Kconfig, or debugfs knob>
Reasoning: <missing EPROBE_DEFER, non-GPL export, Kconfig gap, or unrestored knob>
Impact: <probe-order failure, ABI exposure to proprietary modules, build break, stuck HW state>
Suggestion: <use dev_err_probe/EPROBE_DEFER, EXPORT_SYMBOL_GPL, add Kconfig dep, add restore>
```

## Severity

`[BUG]` for a build/link break or hardware left in a bad state; otherwise
`[CONCERN]` or `[MINOR]` per impact.
