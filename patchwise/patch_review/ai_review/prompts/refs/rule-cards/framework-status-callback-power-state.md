# Rule: framework-status-callback-power-state

## Trigger

Driver code adds or changes a framework-visible status callback that can read
registers or MMIO before the driver's normal enable path runs. Examples include
regulator `.is_enabled` / `.get_status`, clock `.is_enabled`, reset/status
helpers, PHY/provider status callbacks, and generic helpers such as
`regulator_is_enabled_regmap` that perform `regmap_read()`.

This rule is high-signal when the same compatible, descriptor, or match data
also adds mandatory clocks, power domains, resets, bus votes, runtime-PM, or a
new register/status offset.

## Must Check

- Identify every framework path that can invoke the status callback before or
  without the driver's `.enable()` / runtime-resume path: registration, first
  consumer `get`/`enable`, boot-on/always-on handling, disable-unused, sysfs or
  debugfs state reads, suspend/resume, and error unwind.
- For each status callback register/MMIO read, prove the required clocks, power
  domains, resets, bus votes, and runtime-PM state are active on that path.
- If the callback uses a generic regmap/MMIO helper, expand the helper body and
  cite the actual register read site; do not treat the helper name as proof of
  power safety.
- If hardware can be left enabled by firmware/bootloader, prove the software
  resource reference counts are synchronized before any later disable/unprepare
  path runs. A hardware "already enabled" status does not imply Linux has called
  `clk_prepare_enable()` or acquired PM usage counts.
- Check whether the status register is accessible while clocks are gated. If the
  block requires an interface/bus clock for register reads, status polling must
  either temporarily enable that resource or avoid register access until powered.

## Evidence Needed

- Descriptor or ops assignment for the status callback.
- Framework call path that invokes the status callback before/without normal
  enable, with function names and approximate lines.
- Register/MMIO read site, including helper expansion for regmap helpers.
- Resource acquisition and enable sites for clocks, PM domains, resets, bus votes,
  and runtime-PM; state whether they run before the status callback.
- Bootloader/firmware-already-on handling, including any probe-time sync of Linux
  clock/PM counts or an explicit proof that firmware cannot leave the block on.

## Safe Dismissal

Dismiss only when source proves one of the following:

- The status callback does not touch registers/MMIO and returns cached software
  state that is initialized before registration.
- The required clocks/domains/bus votes are enabled before every possible status
  callback entry and are balanced on every error/remove path.
- The status read is documented and source-proven accessible without those
  resources.
- The driver performs probe-time bootloader-state synchronization, so a later
  disable/unprepare cannot run without matching Linux-side enable/prepare counts.

Do not dismiss by saying the callback runs only after consumers enable the
object; regulator/core and similar frameworks often call status callbacks to
*decide* whether enable is needed.

## Finding Template

```text
[BUG] Framework status callback reads unpowered registers
File: <driver-path>:<ops assignment or callback>
Rule: framework-status-callback-power-state
Evidence: <status callback assignment + framework pre-enable call path + MMIO/regmap read + missing resource enable>
Reasoning: <why callback can run before/without the enable path and access a gated block or desync resource counts>
Impact: <SError/bus fault, wrong initial state, skipped enable, unbalanced disable/unprepare, or failed boot>
Suggestion: <power/clock the register read, avoid register status before enable, synchronize bootloader state, or split/remove unsafe fallback/status callback>
```

## Severity

Use `[BUG]` when a status callback can access unpowered MMIO/registers, skip a
mandatory enable because hardware appears already on, or later execute an
unmatched disable/unprepare. Use `[CONCERN]` when callback reachability or
clock-gated register behavior is plausible but not fully proven.
