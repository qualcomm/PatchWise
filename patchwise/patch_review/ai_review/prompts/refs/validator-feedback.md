# Validator Feedback Tracker

Track maintainer-feedback patterns where `scripts/validate_review_packet.py` is too
strict, too broad, or repeatedly forces unnecessary repair. This file is for
validator design calibration only and must not be loaded into routine Mode
A/B/C review prompts.

## Purpose

Validator false positives are validator design bugs. Record patterns when:
- Maintainer/reviewer feedback shows a validator-forced finding or repair was
  unnecessary.
- A check repeatedly fires on source-backed, review-quality reports.
- A repair loop occurs because the validator cannot distinguish safe from unsafe.
- A rule depends on prose/regex inference that should become structured evidence.

## Triage Workflow

1. Map feedback to the validator check name from the violation output.
2. Decide whether the report was invalid, the validator was too strict, or the
   underlying finding was a normal review false positive.
3. Reproduce the false positive with the smallest fixture; if missing, keep the
   entry `open` and note the needed fixture.
4. Choose one action: add a guard, move facts into `generate_evidence_manifest.py`,
   narrow remediation/coverage metadata, downgrade to a process/evidence check,
   keep unchanged, or deprecate.
5. When a rule changes, update `scripts/validate_review_packet.py`, `REMEDIATION`,
   `VALIDATOR_COVERAGE`, validator tests, and `refs/validator-coverage.md`
   together.
6. Run `scripts/self_check.py --quick`; run `--full` when server prompt/report
   validation may be affected.

## Entry Format

Use this exact shape:

```markdown
### VF-0001: Short validator false-positive title

Status: open | guarded | fixed | downgraded | deprecated
Validator check: check_name
Trigger pattern:
- What patch/report/evidence shape made the check fire.
Maintainer evidence:
- Paraphrased feedback with lore link, message ID, date, or local context.
Why it was false positive:
- Which safe case the validator failed to distinguish.
Decision:
- add-guard | structured-evidence | narrow-remediation | downgrade | no-change | deprecate
Required validation change:
- Concrete validator, evidence-manifest, remediation, coverage, or test update.
Fixture:
- Path to reproducer fixture/test, or `needed: <reason>`.
False-positive guard:
- Condition that should prevent this check from firing in the safe case.
Last updated: YYYY-MM-DD
```

Keep entries concise; use one reusable pattern per entry and split unrelated
checks.

## Decision Rules

- Add a guard when the unsafe condition is valid but a safe case can be
  distinguished from existing artifacts.
- Add structured evidence when the rule relies on prose, broad regexes, or
  incomplete patch context.
- Narrow remediation when the failure is real but repair text causes unnecessary
  rewrites or severity changes.
- Downgrade when the claim is useful but not deterministic enough for a hard
  repair gate.
- Deprecate when the rule cannot be made objective or its source of truth is
  stale.
- Use `no-change` only when feedback does not contradict the validator contract;
  document why.

## Active Entries

No tracked validator false-positive entries yet.
