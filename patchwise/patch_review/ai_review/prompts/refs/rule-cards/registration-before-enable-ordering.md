# Rule: registration-before-enable-ordering

## Trigger

Driver code changes registration/init/enable ordering for framework objects such
as pinctrl, GPIO, IRQ domains, clocks, PHYs, regulators, components, or child
subsystems.

## Must Check

- Can consumers or framework core call into the object during registration, first enable, status probing, boot-on/always-on reconciliation, disable-unused, or sysfs/debugfs state reads?
- Are all lookup tables, callbacks, functions, groups, resources, private data, clocks, PM domains, resets, and bus votes initialized before registration exposes callbacks that can use them?
- Does the new order preserve error unwinding for partially registered objects?
- Are devm-managed init/register helpers used with the required final enable step?

## Evidence Needed

- Old and new registration/init/enable/status sequence.
- Consumer or framework entry point reachable during registration/enable/status probing.
- Error labels or devm cleanup behavior after partial setup.

## Safe Dismissal

Dismiss only when source proves consumers/framework core cannot observe partial state, or the
new order initializes and powers all exposed callback state before the framework can call back.
For status callbacks, do not dismiss by saying normal consumers call enable later; many frameworks call status callbacks to decide whether enable is needed.

## Finding Template

```text
[BUG] Framework object is enabled before required state is initialized
File: <driver-path>:<registration-or-enable-line>
Rule: registration-before-enable-ordering
Evidence: <register/init/enable order and consumer callback path>
Reasoning: <why consumer can observe missing functions/resources/private data>
Impact: <probe failure, invalid lookup, NULL/stale callback, or unusable device>
Suggestion: <initialize/register data before enable or use register_and_init + explicit enable>
```

## Severity

Use `[BUG]` for reachable partial-state exposure, pre-enable register access, or a registration path that exposes callbacks before mandatory resources are active. Use `[CONCERN]` when callback reachability depends on framework timing not fully proven.
