# Rule: resource-acquire-release-symmetry

## Trigger

Driver code acquires a hardware resource — `request_irq`/`request_threaded_irq`,
`dma_request_chan`, `clk_prepare_enable`/`clk_get`, `regulator_enable`/`get`,
`reset_control_get`, `ioremap`, `regmap_init` — outside the devm-managed
lifetime, or changes the matching release path.

## Must Check

- Does every non-devm acquire have a matching release on all error, remove/unbind, and suspend paths (`free_irq`, `dma_release_channel`, `clk_disable_unprepare`/`clk_put`, `regulator_disable`/`put`, `iounmap`, `regmap_exit`)?
- Is a `devm_*`-acquired resource being manually freed/disabled as well, causing double cleanup or use-after-free?
- For ASoC/codecs and other framework components: if a regmap comes from
  `devm_regmap_init*()`, do not pair `snd_soc_component_init_regmap()` with
  `snd_soc_component_exit_regmap()` or `regmap_exit()` unless the code also
  cancels the devres action or proves the regmap was non-managed. The component
  exit helper calls `regmap_exit()`; devres will call it again at device release.
- Is an enable callback that can run repeatedly (open/close, reload, resume) balanced by exactly one disable, with idempotency where needed?
- Is a resource acquired before publication released if a later setup step fails before the object becomes visible?
- Is `regmap_exit`/transport teardown ordered after all consumers (work, IRQ) are drained?
- In teardown helpers, are user-facing surfaces (sysfs attributes, ioctls, char-dev/misc-dev, thermal cooling-device, hwmon, input-device, drm-connector) unregistered BEFORE the underlying transport (`qmi_handle_release`, `regmap_exit`, `free_irq`, `iounmap`, socket shutdown, `pm_runtime_disable`) is released? Releasing the transport while a userspace writer or framework callback (e.g. thermal `set_cur_state`) is in flight is a use-after-free: the surface remains exposed and routes calls into freed transport state. The correct order is unregister-surface → drain-work/cancel_work_sync → release-transport.

## Evidence Needed

- The acquire call and every release counterpart across error/remove/suspend paths.
- Whether the resource is devm-managed or manually owned.
- For `snd_soc_component_exit_regmap()`: the actual regmap allocation API and
  whether any IRQ/work/control callback can still reach the private regmap after
  component removal and before devres release.

## Mandatory Attestation Record

For every non-devm resource acquire in the diff, include in Code Logic Maps:

```
resource_symmetry_audit:
  acquire: <function(resource) at file:line>
  ownership: <devm | manual>
  release_paths:
    - error_label_X: <has matching release | MISSING>
    - remove/unbind: <has matching release | MISSING>
    - suspend: <has matching release | N/A>
  double_free_risk: <NO | YES — devm + manual both release>
```

Omitting this record when non-devm resource acquisition is in the diff is a
review gap.

## Safe Dismissal

Dismiss when source shows balanced acquire/release on every exit, or devm fully
owns the lifetime with no manual release added.

## Finding Template

```text
[BUG] Hardware resource acquire/release asymmetry
File: <path>:<line>
Rule: resource-acquire-release-symmetry
Evidence: <acquire site + missing/duplicate release path>
Reasoning: <which exit path leaks or double-frees the resource>
Impact: <IRQ/clock/regulator/DMA leak, double-free, use-after-free on teardown>
Suggestion: <add the matching release on the leaking path, or drop the manual free for devm>
```

## Severity

`[BUG]` for a proven leak or double cleanup on a reachable path; `[CONCERN]`
when the error/remove path is plausible but not fully traced.
