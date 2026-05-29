# Rule: devfreq-governor-state-contract

## Trigger

Devfreq core, governor, or driver code changes `struct devfreq_governor`,
governor flags/attrs, `devfreq->governor`, `get_target_freq`,
`profile->target`, `get_cur_freq`, transition statistics, PM QoS clamping,
sysfs governor attributes, suspend/resume frequency state, or governor
module add/remove paths.

## Must Check

- Are all reads/writes of `devfreq->governor` protected by the same lifetime
  rule as governor replacement/removal, including sysfs, PM QoS notifiers,
  monitor work, suspend/resume, and module unload?
- Do sysfs governor-attribute read/write paths and `governor_store()` acquire
  locks and kernfs active references in a consistent order, avoiding ABBA
  deadlocks around `sysfs_update_group()`?
- If a governor is `IMMUTABLE`, can module unload or forced governor removal
  bypass that immutability and leave a device bindable to an incompatible
  governor?
- If a governor bypasses `profile->target()` or tracks remote frequency, does
  the code still round/validate to real OPP entries before updating transition
  stats, `time_in_state`, tracepoints, and `previous_freq`?
- Are PM QoS min/max constraints applied only to requested local targets, not
  incorrectly clamping observed remote hardware frequencies?
- Does governor start validate required callbacks such as `get_cur_freq`, so
  polling work cannot repeatedly log failures forever?
- Are `previous_freq`, `new_freq`, `resume_freq`, and `suspend_freq` updated in
  the direction their names imply across suspend/resume and transition paths?

## Evidence Needed

- Changed devfreq/governor fields, flags, callbacks, and sysfs attributes.
- Locking/lifetime path for governor replacement, removal, monitor work, PM QoS,
  and module unload.
- Transition-stat path showing OPP validation/rounding and state updates.
- Start/stop/suspend/resume event handler behavior and required callback checks.

## Mandatory Attestation Record

When a diff changes devfreq governor flags/attrs or bypasses `profile->target`,
include in Code Logic Maps:

```yaml
devfreq_governor_state_audit:
  changed_governor_or_core_path: <file:line>
  governor_lifetime_locking: <same lock/ref pins all readers | gap — flag>
  sysfs_lock_order_checked: <YES | N/A | gap — flag>
  immutable_unload_checked: <YES | N/A | gap — flag>
  target_bypass: <NO | YES callback/path=...>
  opp_rounding_or_validation: <YES line=... | NO — flag>
  stats_trace_previous_freq_consistency: <YES | NO — flag>
  required_callback_validation: <YES | NO/N/A>
```

Omitting this record for devfreq governor/core changes is a review gap.

## Safe Dismissal

Dismiss only when the changed path is a leaf driver using existing devfreq APIs
without changing governor/core semantics, or when all governor readers are
pinned/locked and transition stats are updated only with validated frequencies.

## Finding Template

```text
[BUG] Devfreq governor state/lifetime contract is broken
File: <path>:<line>
Rule: devfreq-governor-state-contract
Evidence: <changed governor/core path and missing lock/validation/state invariant>
Reasoning: <race, deadlock, invalid stat update, immutable bypass, or bad suspend/resume state>
Impact: <UAF/NULL deref, warning flood, incorrect stats/tracepoints, or crash on governor switch>
Suggestion: <pin/lock governor lifetime, validate callbacks, route through OPP/target handling, or preserve immutable/state invariants>
```

## Severity

Use `[BUG]` for reachable UAF/NULL deref/deadlock/crash; `[CONCERN]` for
stats/tracepoint corruption, warning floods, or lifetime paths needing subsystem
confirmation.
