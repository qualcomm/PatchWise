# Validator Rule Design Guide

This guide is for maintainers changing `scripts/validate_review_packet.py`. Validator
rules are repair gates: they can force block/report rewrites, so every rule must
be objective, source-backed when semantic, narrow, and testable. Do not encode
subjective review taste as a hard validator failure.

## Role Of The Validator

Use the validator to catch structurally invalid or insufficiently audited
reports, not to replace kernel review judgment.

Good hard-check targets:
- Missing required HTML structure, classes, anchors, verdicts, footer text, or
  completion records.
- Missing evidence artifacts: tests/build logs, rules-brief reads, prompt
  records, or source-audit records.
- Finding cards missing required gate traces or using unsupported labels.
- Report content contradicting structured facts, such as claiming DT/hardware is
  not applicable when the patch triggers that section.
- Repeat failures that are objective from the patch, source tree, evidence
  manifest, prompt, rules brief, tests, or build output.

Keep nuanced tradeoffs, maintainer taste, and subsystem preference in refs or
memory as reviewer guidance.

## Admission Criteria

Add a hard rule only when all are true:
- Repeatable: the failure happened before or is a stable blind spot.
- Objective: a deterministic script can detect it without guessing intent.
- Relevant: it prevents misleading reports, missed mandatory audit, invalid HTML,
  invalid severity gates, or false confidence.
- Bounded: false-positive guards are clear and the violation can explain why it
  fired.
- Repairable: the remediation tells a model/maintainer exactly what to change.
- Covered: positive and negative fixtures exist.
- Maintainable: future ref/report wording changes can preserve the contract.

If any item is missing, keep the idea as prompt guidance, memory,
or a warning-only diagnostic until it can be made rule-backed and fixture-backed.

## Artifact Boundaries

Validate only stable artifacts:
- Final HTML report and per-patch block HTML.
- Sidecars: progress records, evidence manifests, patch manifests, build/test
  logs, generated prompts/rules briefs.
- Patch/diff text and bounded source-root reads explicitly passed to the
  validator.
- Shared constants in `refs/review-constants.json`.

Do not require internet access, unrecorded model thoughts, unstored shell output,
or environment state that is unavailable to normal report validation.

## Conservative Check Design

A good validator check is narrow, guarded, and explanatory:
- Match the smallest reliable pattern and prefer structured evidence over prose.
- Include positive and negative conditions; exempt safe variants explicitly.
- Emit a violation with check name, artifact location, and actionable detail.
- Avoid broad regexes over generated natural language when structured facts
  exist or can be added.
- Treat missing evidence separately from proven source bugs.

If the validator cannot distinguish unsafe from safe cases, first add evidence
or keep the rule soft.

## Violation Contract

The check name is a public contract. If introduced, keep it stable unless all
call sites, tests, remediation entries, and coverage docs migrate together.

For each new check:
- Emit `Violation("check_name", location, detail)`.
- Add `REMEDIATION["check_name"]` with a concise `fix` and resolvable `ref`.
- Add `VALIDATOR_COVERAGE["check_name"]` with category, artifacts, rule ref, and
  purpose.
- Add/update tests so one invalid fixture fails and one valid fixture passes.
- Update `refs/validator-coverage.md` by hand to reflect the new check.

Remediation must say what to change; it must not tell the agent to suppress a
finding, weaken severity, or remove evidence unless that is the source-backed
repair.

## Coverage Metadata

`VALIDATOR_COVERAGE` is the audit map. Each entry must state the enforced rule,
artifact dependencies, category, repair action, and whether the check is
structural, evidence-based, source-aware, or prompt/rules-integrity related.

If a check starts using a new artifact, update `refs/validator-coverage.md` by
hand in the same change.

## Severity And Finding Rules

Hard checks may enforce gate-trace format and label consistency. Be conservative
when judging severity content.

Valid checks include:
- Non-NIT findings missing Gate 1/2/3 traces, or NIT findings missing the
  style-track trace.
- Unsupported severity or verdict labels.
- Banner counts/verdicts inconsistent with finding cards.
- Source-backed claims lacking required source/evidence records.

Risky checks need stronger guards:
- Auto-promoting `[CONCERN]` to `[BUG]`.
- Rejecting findings for noncanonical maintainer wording.
- Inferring runtime impact from a short regex without source context.
- Treating absence of a finding as failure without an objective mandatory-finding
  rule.

## Source-Aware Rules

Evidence order:
1. Structured evidence manifest facts.
2. Patch/diff facts.
3. Bounded source-root reads for touched files or required companions.
4. Regex fallback for older artifacts only when conservative.

A source-aware violation should name the triggering file, function, helper, API,
or source fact where practical. If it cannot name the trigger, the rule is too
broad. Prefer extending `generate_evidence_manifest.py` over reparsing prose or
C/YAML snippets.

## False-Positive Handling

Treat validator false positives as validator design bugs. When feedback shows a
rule is too strict:
- Reproduce it with a fixture.
- Add a guard or structured-evidence check for the safe case.
- Downgrade to a process/evidence check if the semantic claim is not
  deterministic.
- Update remediation and coverage when purpose changes.
- Record repeated/unresolved patterns in `refs/validator-feedback.md`; use
  normal memory only when review judgment also needs calibration.

Do not weaken unrelated checks or add broad allowlists that hide real failures.

## When Not To Add A Hard Rule

Do not add hard rules for subjective prose style, maintainer taste, one-off
misses, safe future-looking concerns, checks needing network or current
external state, arbitrary driver-semantics inference without structured
evidence, or repair actions equivalent to "think harder".

Use refs, docs, or manual review instead.

## Implementation Checklist

1. Identify the source of truth: ref section, shared constant, generated artifact,
   or memory entry.
2. Classify the check: structural, evidence-based, source-aware, or prompt/rules
   integrity.
3. Add/extend structured evidence if semantic source facts are needed.
4. Implement the narrowest guarded validator check.
5. Add `REMEDIATION` and `VALIDATOR_COVERAGE`.
6. Add positive and negative tests.
7. Update `refs/validator-feedback.md` for tracked false-positive changes.
8. Regenerate `refs/validator-coverage.md`.
9. Run `scripts/self_check.py --quick`; run `--full` before deployment when
   server integration may be affected.

## Review Before Merge

Verify: the rule explains why it fired; a valid report passes without fixture
special-casing; remediation is actionable; coverage lists artifact dependencies;
series behavior remains correct; structured facts are preferred over generated
prose; and a maintainer would agree it is a hard report-quality failure.

If not, keep it as guidance until narrower and better evidenced.
