# Rule: runtime-pm-bracket-safety

## Trigger

Driver code changes `pm_runtime_get_sync()`, `pm_runtime_resume_and_get()`,
`pm_runtime_put*()`, or register/MMIO access reachable from runtime paths.

## Must Check

- Is every register/MMIO access protected by powered clocks/domains or a proven always-on state?
- For `pm_runtime_get_sync()`, are negative returns checked and balanced with `pm_runtime_put_noidle()`?
- Is positive return `1` treated as success, not failure?
- After a successful get, do all new returns/gotos reach the matching put/cleanup?
- Does suspend/resume restore non-retained registers, ICC/OPP/genpd votes, and cached software state?

## Evidence Needed

- PM get/put call sites and all modified exits after the get.
- Register access entry point: sysfs/debugfs/ioctl/IRQ/probe/runtime callback.
- Error labels and restore/resume helper bodies.

## Mandatory Attestation Record

For every function that calls `pm_runtime_get_sync`/`resume_and_get` or
accesses registers, include in Code Logic Maps:

```
pm_bracket_audit:
  get_site: <function:line — which pm_runtime_get* call>
  return_check: <CHECKED ret<0 + put_noidle | UNCHECKED | uses resume_and_get>
  exit_paths: [<label1: has put>, <label2: has put>, <early_return: MISSING put>]
  register_access_protected: <YES — pm_runtime active | NO — explain>
```

Omitting this record when PM calls or register access appear is a review gap.

## Safe Dismissal

Dismiss only by quoting checked `< 0` handling plus `put_noidle`, migration to
`pm_runtime_resume_and_get()`, or a source-proven always-on/unreachable path.

## Finding Template

```text
[BUG] Runtime PM bracket can leak or access unpowered registers
File: <driver-path>:<pm-or-register-line>
Rule: runtime-pm-bracket-safety
Evidence: <PM call, exit path, and register access/restore path>
Reasoning: <why failure/success/early-exit leaves bad PM state or unpowered access>
Impact: <usage-count leak, failed resume, stale state, or bus/register fault>
Suggestion: <check ret < 0, use put_noidle, route exits through cleanup, or migrate API>
```

## Severity

Use `[BUG]` for reachable leaks or unpowered accesses; `[CONCERN]` when restore
or reachability depends on hardware retention not shown in source.
