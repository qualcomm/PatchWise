# Review Memory — Subsystem Specific (deprecated)

### MEM-0178: Probe-time entity-count dev_info() calls rejected — use dev_dbg() or tracing

Status: deprecated
Scope: general
Triggers:
- A patch or series adds dev_info() to driver probe functions solely to log counts
  of firmware-discovered or enumerated entities (e.g. "Initialized N domains",
  "Initialized N sensors", "Initialized N pins, M groups, P functions")
- The message fires once per successful probe and reports a resource count; it is
  not an error, unexpected condition, or user-visible state change

Maintainer evidence:
- Greg Kroah-Hartman (NAK on "scmi: Log client subsystem entity counts",
  <20260513-scmi-client-probe-log-v1-0-00b47b1be009@oss.qualcomm.com>, 2026-05-14):
  "When drivers work properly, they should be quiet. If a developer wants to see
  extra messages, use the dev_dbg() infrastructure, or the tracing infrastructure."
- Guenter Roeck (hwmon maintainer, same thread): "Then please use dev_dbg()."
- Sudeep Holla (SCMI maintainer, same thread): "I completely agree and tend to follow that."
- Andy Shevchenko (same thread): "I believe the trend is to drop such messages and
  not add them [back]."
- Linus Walleij (pinctrl, same thread): initially applied the pinctrl patch, then
  dropped it after Andy pushback -- final outcome matches Greg KH position.
- Our automated review for this series flagged only code-quality issues within
  individual patches; it missed the series-level policy violation entirely (missed-by-us).

Review action:
- Flag [MINOR] when a patch adds dev_info() to a probe path for a purely informational
  resource-count message that is not an error or unexpected condition.
- Note in the finding that Greg KH has explicitly NAKed this pattern across multiple
  subsystems; the preferred replacement is dev_dbg() or the kernel tracing infrastructure.
- Apply at the series level if multiple patches share the same pattern (one finding per
  series is sufficient; do not repeat per patch).

False-positive guards:
- Do not flag dev_info() for error paths, warnings, or messages reporting unexpected
  conditions (missing firmware resources, unsupported configurations, partial success).
- Do not flag dev_info() that is consistent with a pre-existing dev_info() in the same
  driver for the same category of message -- the new message fits an established
  per-driver pattern.
- Do not flag if the subsystem already has documented maintainer acceptance of probe
  dev_info() for entity counts (e.g., the SCMI power and performance domain drivers have
  pre-existing probe dev_info(); patches following that pattern in the same subsystem are
  consistent, even if the broader trend is to remove them).
- Do not escalate above [MINOR]; this is a kernel-wide logging policy, not a bug.
- See MEM-0129 for the closely related case of per-boot operational messages in Qcom PCIe.

Confidence: high
Last updated: 2026-05-26

### MEM-0211: `dev_get_drvdata()` NULL in probe-reachable lookup → return `-EPROBE_DEFER`, not `-ENODEV`

Status: deprecated
Scope: general
Triggers:
- A lookup helper (called from another device's probe context) resolves a cross-tree
  supplier device via `of_find_device_by_node()` or similar and then calls
  `dev_get_drvdata()` on the resolved device
- When `dev_get_drvdata()` returns NULL (supplier found but not yet fully probed),
  the helper returns `-ENODEV`

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 1/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com:
  "[High] Returning -ENODEV instead of -EPROBE_DEFER when the RPMH controller
  hasn't fully probed yet causes premature and permanent probe failures for consumers."
  Duplicate of MEM-0207 which covers the same pattern with more detail and better
  false-positive guards. Deprecated to avoid confusion.

Review action:
- Use MEM-0207 instead.

False-positive guards:
- See MEM-0207.

Confidence: low
Last updated: 2026-05-29

### MEM-0225: CLK `enable`/`disable` callbacks run under spinlock — `udelay` is correct; `usleep_range` is wrong

Status: deprecated
Scope: subsystem:clk file-pattern:drivers/clk/
Triggers:
- A `clk_ops.enable` or `clk_ops.disable` callback uses `udelay()` after writing a
  clock enable/disable register
- A reviewer or automated tool suggests replacing `udelay()` with `usleep_range()`
  for better power consumption

Maintainer evidence:
- Qiang Yu (patch author) on [PATCH v4 2/7] clk: qcom: Add generic clkref_en support
  (linux-arm-msm, 2026-05-28): "The .enable and .disable callbacks are called under
  the clock framework's enable spinlock, so sleeping is not allowed here. udelay is
  intentional." Our automated review incorrectly flagged udelay in enable/disable as
  needing usleep_range, asserting the context was sleepable.
- CLK framework design: prepare_lock (mutex) for prepare/unprepare; enable_lock
  (raw_spinlock) for enable/disable. Sleeping under a raw_spinlock is prohibited.

Review action:
- Do NOT suggest `usleep_range` for delays inside `clk_ops.enable` or `clk_ops.disable`.
- `udelay()` is correct because these callbacks run under enable_lock (a raw_spinlock)
  where sleeping is forbidden.
- `usleep_range` is only appropriate in `clk_ops.prepare` / `clk_ops.unprepare`, which
  run under prepare_lock (a mutex).

False-positive guards:
- Do not apply this guard to `prepare` / `unprepare` callbacks; those hold a mutex
  and `usleep_range` is indeed preferred there.
- Verify the callback type before suggesting a change: enable/disable → spinlock (udelay
  correct); prepare/unprepare → mutex (usleep_range preferred).

Confidence: high
Last updated: 2026-05-29
