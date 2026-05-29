# Rule: platform-child-device-resource-lifecycle

## Trigger

Driver code creates a child `platform_device`, IRQ mapping, resource, or fwnode
bridge using APIs such as `platform_device_register_full()`,
`irq_create_fwspec_mapping()`, `DEFINE_RES_*`, `of_node_reused`, or child device
unregister/dispose helpers. Also trigger when a parent driver uses devm-managed
parent allocations to back child platform-device data, devfreq instances, work,
or callbacks.

## Must Check

- Are child device registration and IRQ/resource mapping unwound in exact reverse order on every error path?
- Is `irq_dispose_mapping()` paired with every successful `irq_create_*_mapping()`?
- Is `platform_device_unregister()` paired with every successful child registration?
- Does the child receive valid parent, fwnode/of_node, resources, and lifetime ownership?
- Are stored child pointers/IRQ numbers cleared after failed registration or removal?
- If child callbacks/devres/devfreq/work reference memory allocated with
  `devm_*(&parent->dev, ...)`, can the child outlive the parent devres cleanup?
  Beware circular teardown: a child framework object takes a reference on the
  child device, child devres cannot run until release, but the parent devres can
  free callback data first.
- Are dummy child platform-device names globally unique? Generic names such as
  `"ddr"`, `"llcc"`, or `"qos"` with `PLATFORM_DEVID_NONE` can collide on the
  global platform bus; use a driver-specific prefix and/or `PLATFORM_DEVID_AUTO`.

## Evidence Needed

- Mapping/resource creation and child registration sites.
- Error labels and remove path.
- Stored child pointer/IRQ fields and clearing behavior.
- Parent-vs-child devres ownership for data used by child callbacks/work.
- Child platform-device `name` and `id` source, including collision resistance.

## Mandatory Attestation Record

When a diff registers child platform devices, include in Code Logic Maps:

```yaml
child_platform_lifecycle_audit:
  registration: <platform_device_register* at file:line>
  parent: <device expression>
  child_name_id: <name/id expressions>
  name_collision_safe: <YES reason | NO — flag>
  child_callback_data_owner: <child devres | parent devres | manual>
  child_can_outlive_parent_data: <NO | YES — flag>
  unregister_paths: [<error/remove path summary>]
```

Omitting this record when child platform devices are registered is a review gap.

## Safe Dismissal

Dismiss only when every successful create/register step has a reverse-order
cleanup on error and remove, with stale fields cleared or unreachable, child
callbacks cannot outlive their data, and platform-device names/IDs are collision
safe.

## Finding Template

```text
[BUG] Child platform-device resource lifecycle is incomplete
File: <driver-path>:<create-register-or-cleanup-line>
Rule: platform-child-device-resource-lifecycle
Evidence: <create/register path, error labels, and missing unregister/dispose/clear>
Reasoning: <which partial-success/lifetime/name path leaks, races, or leaves stale child state>
Impact: <IRQ mapping leak, stale child device, devres UAF, name collision, double unregister, or failed reprobe>
Suggestion: <unwind in reverse order, move callback data under child-owned lifetime, use unique names/IDs, and clear stored child pointers/IRQ numbers>
```

## Severity

Use `[BUG]` for leaked mappings/devices or stale pointers on reprobe; `[CONCERN]`
when ownership is indirect and needs framework confirmation.
