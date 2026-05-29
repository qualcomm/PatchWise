# Rule: branch-precedence-regression

## Trigger

Patch widens or reorders an `if`/`else if` chain, especially by adding a new
`||` condition, around side-effectful setup, power, PHY, clock, lock, or state
initialization.

## Must Check

- Which input/value now matches an earlier branch than before?
- What side effect from the bypassed later branch is lost?
- Is the side effect performed elsewhere for the new branch?
- Are operator precedence and parentheses preserving the intended guard?

## Evidence Needed

- Old and new branch chain with the widened condition.
- The side-effectful later arm that can now be skipped.
- Proof the skipped side effect is redundant or re-established.

## Safe Dismissal

Dismiss only after tracing a concrete input through old and new branch order and
proving no required side effect is bypassed.

## Finding Template

```text
[BUG] Widened branch captures input before required setup
File: <driver-path>:<condition-line>
Rule: branch-precedence-regression
Evidence: <new condition, skipped branch, and lost side effect>
Reasoning: <which input changes arms and why setup no longer runs>
Impact: <missing power/PHY/clock/state init or wrong mode handling>
Suggestion: <reorder branches, split condition, or duplicate required setup>
```

## Severity

Use `[BUG]` when setup/state side effects are bypassed; `[CONCERN]` when the
bypassed effect may be redundant but proof is missing.
