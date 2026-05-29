# Rule: unchecked-setup-result

## Trigger

A setup/init/configure/start/prepare helper's return value flows toward a
publish/register/add/enable/attach path, a bulk property/setter loop applies
multiple values, or an existing helper is newly wired into a control/selector/
resume path.

## Must Check

- Is the setup/init return checked and handled before the object is published (registered, added, attached, enabled, exposed)? Later cleanup does not undo a half-initialized object already visible to other code.
- Is the real failure carried or deliberately translated, not overwritten with success?
- In a bulk loop applying properties/settings, is a single setter failure detected, so hardware state cannot diverge from the contract while the call reports success?
- When a pre-existing helper is wired onto a newly reachable path (new selector, init loop, resume/restore, platform path), are its `-EINVAL`/no-op/dropped returns re-audited for the new context?

## Evidence Needed

- The helper return, the check (or absence), and the publication point.
- For bulk loops, how per-iteration failure is propagated.

## Safe Dismissal

Dismiss when source shows the return is checked before publication and failures
abort or are correctly translated.

## Finding Template

```text
[BUG] Setup result unchecked before publication
File: <path>:<line>
Rule: unchecked-setup-result
Evidence: <helper return + publication/register site without check>
Reasoning: <how a half-initialized object becomes visible, or failure is masked>
Impact: <use of partially-initialized object, masked error, hardware/state mismatch>
Suggestion: <check the return before publish; abort or translate the failure>
```

## Severity

`[BUG]` when a reachable path publishes on unchecked failure; `[CONCERN]` when
the failure mode of the reused helper is not fully proven.
