## Special Cases

These cases adjust review content; they do not skip mandatory sections, gate
traces, step records, sidecars, or validator-required output.

### Merge commits
- If reviewing a merge commit, inspect only conflict resolution and integration
  effects, not every already-reviewed parent change.
- Do not flag ordinary merge metadata or subject format as commit-message issues.
- Still report real conflicts: lost hunks, wrong resolution, build breakage, or
  behavioral changes introduced only by the merge.

### Revert patches
- A revert should clearly name the reverted commit and why reverting is needed.
- Do not demand a new root-cause analysis if the revert is a short-term recovery.
- Flag when the revert leaves dependent follow-up code, bindings, Kconfig, or
  documentation inconsistent.

### `include/uapi/` changes — ABI stability
- Treat UAPI as ABI: flag struct layout changes, enum renumbering, ioctl number
  reuse, removed defines, or changed userspace-visible semantics.
- Additions must preserve backward compatibility, padding/reserved fields, and
  32-bit compat where relevant.
- Require documentation or commit-body ABI rationale for new userspace-visible
  interfaces.

### New Kconfig symbols
- Check type, prompt/help text, dependencies, defaults, and build coverage.
- Default should normally be `n`; flag risky default-`y` enablement unless it is
  tightly justified and safe for existing configs.
- Dependencies must cover compile needs such as `OF`, `HAS_IOMEM`, `PM`, clocks,
  resets, or bus subsystems.

### defconfig / config-fragment additions
- Every `CONFIG_<SYM>=y`/`=m` line added to a `defconfig` or config fragment must
  reference a Kconfig symbol that exists in the same base tree or is introduced by
  an earlier patch in the series. Search `Kconfig*` for the bare symbol name.
- An addition for an undefined symbol (driver not yet upstreamed, typo, wrong
  symbol name) is silently dropped by `make savedefconfig`/`olddefconfig` and the
  intended driver is never built. File `[CONCERN]` for a defconfig line with no
  matching Kconfig symbol; dismiss only by naming the defining `Kconfig` file/line
  or the in-series patch that adds it.
- Keep `defconfig` entries in their tooling-sorted position; an out-of-order line
  is `[NIT]` because the next `savedefconfig` will move it.

### Patches touching `kernel-parameters.txt`
- Ensure the parameter exists in code or is added by the same patch/series.
- Check spelling, type, units, defaults, and boot-time/runtime scope.

### `SYSCALL_DEFINE*` patches
- Require UAPI review, compat handling, security/permission checks, copy_to/from
  user validation, extensibility, and documentation/man-page considerations.
- New syscalls need especially strong justification; missing ABI review is at
  least `[CONCERN]`.

### Very large series (> 20 patches)
- Prioritize patch ordering, bisectability, dependency grouping, repeated bug
  patterns, and cross-patch inconsistencies.
- Do not repeat the same low-value style nit on every patch; raise once at
  series level when appropriate.

### RFC patches (`[RFC PATCH]` prefix)
- RFC status lowers expectations for polish but not for correctness/safety.
- Still report bugs, ABI breaks, unsafe hardware behavior, build failures, and
  misleading commit messages.
- Phrase non-blocking design questions as `[CONCERN]` or `[MINOR]` depending on
  impact.

### Whitespace-only / formatting patches
- Verify the patch is truly formatting-only.
- Flag any behavior change, generated-code churn, or unrelated cleanup mixed in.
- Do not demand functional tests beyond build/checkpatch unless the formatting
  touches fragile generated tables or assembly-like code.

### Documentation-only patches
- Check technical accuracy against nearby code or binding when practical.
- Do not require runtime tests for pure docs, but flag docs that describe APIs,
  compatible strings, parameters, or behavior not present in code.

### Stable/backport trailer checks
- `Cc: stable@vger.kernel.org` should be used for fixes suitable for stable; do
  not require it for every `Fixes:` tag.
- If `Cc: stable` appears without `Fixes:`, require a clear body explanation or
  obvious stable-only context.
- For backports, check conflicts caused by missing prerequisites and avoid
  requiring mainline-only context that is irrelevant to the target stable tree.

### Mixed feature + bugfix series
- Prefer a minimal fix series plus a separate feature/refactor series.
- Do not flag when the fix depends on the new infrastructure or the cover letter
  explains an inseparable dependency chain.

### Patch ordering / dependency violations
- Flag when a patch uses symbols, bindings, Kconfig options, headers, or generated
  constants introduced only by a later patch.
- Binding/schema changes should generally precede DTS/driver users.

### Interdependent patch build failures
- If patch N cannot build until patch N+1, flag `[CONCERN]` unless the series is
  explicitly non-bisectable and the target subsystem accepts that.

### Non-upstream-targeted patches
- If a patch is clearly vendor/internal and not intended upstream, say the normal
  upstream bar may not apply, but still report objective correctness, safety,
  ABI, and build issues.
