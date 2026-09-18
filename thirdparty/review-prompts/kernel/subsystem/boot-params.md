# Boot Parameter Subsystem Guide

## Documentation Requirement

Every boot parameter added or changed (via `__setup()`, `early_param()`,
`module_param()`, or any command-line option parsed at boot) must be
documented in `Documentation/admin-guide/kernel-parameters.txt`.

**REPORT as regressions**: Any patch that adds or changes a kernel
command-line parameter without a corresponding update to
`Documentation/admin-guide/kernel-parameters.txt`.

### Triggers

The following signals indicate a boot parameter is being modified:

- `__setup("` — kernel command-line parameter handler
- `early_param("` — early boot parameter handler
- `module_param(` — module parameter (module parameters accessible at boot
  via `<module>.<param>=` also go in kernel-parameters.txt)
- `module_param_named(` — same
- `core_param(` — core kernel parameter
- Boot parameter strings in commit messages: `kernel command-line`,
  `boot parameter`, `cmdline`, `command-line option`

### Exceptions

- Debug-only parameters gated by `#ifdef CONFIG_DEBUG_KERNEL` may be
  documented in the parameter file or in a comment near the definition.
  Flag but do not require a kernel-parameters.txt entry for these.
- Parameters defined and consumed entirely within a single driver's
  `CONFIG_EXPERIMENTAL`-gated code path that has no user-facing
  documentation expectation. Still flag for reviewer awareness.

### Checklist

When a patch matches any trigger:

1. Check if `Documentation/admin-guide/kernel-parameters.txt` is also
   modified in the diff.
2. If not modified, the parameter is missing documentation — report as
   a regression unless an exception applies.
3. If modified, verify the documentation entry includes: parameter name,
   format (`tlbi=off` or `tlbi=[off]`), what it controls, and the
   architectures it applies to.
