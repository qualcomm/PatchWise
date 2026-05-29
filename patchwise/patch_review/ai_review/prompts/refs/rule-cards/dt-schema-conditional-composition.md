# Rule: dt-schema-conditional-composition

## Trigger

DT binding schema changes a wrapper/common schema composition block such as
`anyOf`, `oneOf`, `allOf`, `contains`, or `$ref`, especially when adding a
vendor-specific schema under a common binding.

## Must Check

- Is the new branch conditionally gated by the compatible strings it is meant
  to validate, or can unrelated compatibles satisfy it as a fallback?
- If the added branch has `additionalProperties: true`, omits a compatible
  constraint, or has loose closure, can it annotate/evaluate properties that
  make a stricter sibling vendor schema failure disappear?
- Does the parent schema use `unevaluatedProperties: false`, and if so, which
  branch is responsible for evaluating each vendor-specific property?
- For every sibling schema in the same `anyOf`/`oneOf`, would an invalid node
  for that sibling still fail after the new branch is added?

## Evidence Needed

- The parent/wrapper schema composition block before and after the change.
- The added referenced schema's `compatible` constraints and closure mode.
- At least one sibling branch/schema considered for fallback bypass risk.

## Mandatory Attestation Record

When a DT binding diff adds a `$ref` branch under `anyOf` or `oneOf`, include
in DT/DT-Binding Notes:

```yaml
schema_composition_audit:
  parent_schema: <path>
  added_branch: <$ref/path>
  branch_compatible_gate: <YES line=... | NO — flag if vendor-specific>
  branch_closure: <additionalProperties/unevaluatedProperties setting>
  sibling_schema_checked: <path/name>
  unrelated_fallback_possible: <NO | YES — flag finding>
```

Omitting this record when a composition branch is added is a review gap.

## Safe Dismissal

Dismiss only when the added branch is compatible-gated so unrelated devices
cannot satisfy it, or the branch is intentionally common and has strict enough
closure that it cannot mask sibling-schema failures.

## Finding Template

```text
[CONCERN] DT schema branch can bypass stricter sibling validation
File: <binding-path>:<anyOf/oneOf/$ref line>
Rule: dt-schema-conditional-composition
Evidence: <new branch, missing compatible gate, loose closure, sibling schema>
Reasoning: <how an invalid sibling node can satisfy this branch instead>
Impact: <dt_binding_check accepts invalid ABI or suppresses vendor-specific errors>
Suggestion: <gate the branch with if/then compatible matching, tighten closure, or move it out of the unconditional composition list>
```

## Severity

Use `[CONCERN]` when an unrelated compatible can plausibly satisfy the new
branch; `[MINOR]` only for incomplete evidence in a non-vendor/common schema.
