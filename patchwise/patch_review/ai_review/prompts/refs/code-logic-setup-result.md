<!-- Conditional fragment of code-logic.md — the diff shows setup/init/configure/start/prepare paths leading to publish/register/
attach/enable. Apply on top of refs/code-logic.md §3c.2 Data-Flow Picture base
prose. -->

#### Setup-result / publication audit

Apply when setup/init/prepare/start/configure status flows toward publish,
register, attach, enable, or exposure to other code.
- Guard before publication: the return must be checked and handled before first
  publication; later cleanup is not equivalent after a half-initialized object is
  visible.
- Carry or deliberately translate the real failure; do not overwrite it with
  success or continue as if setup succeeded.
- Reused helper on newly activated path: if a patch wires an existing helper or
  setter into a new control, selector, init loop, resume/restore path, or
  platform path, re-audit its return values and side effects. Pre-existing
  `-EINVAL`, no-op, or dropped returns become reviewable when newly reachable,
  required, or user-visible.
- Public contract vs setter preconditions: compare advertised min/max/default or
  enum values against setter rejects (`!value`, `< min`, sentinel/default such as
  `0`/`1`). If a newly advertised valid value can be rejected and replay/apply
  drops the return, file `[CONCERN]` minimum; escalate to `[BUG]` for direct,
  deterministic runtime harm.
- Bulk property/control application must propagate setter failures. If a loop
  over capabilities, controls, firmware properties, or table entries ignores a
  setter return, a single rejected property can make stream-on/probe/resume
  succeed with hardware state different from the advertised userspace or DT
  contract.
