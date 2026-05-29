# Reviewer Base Contract

Use this contract for one-patch review packets. It is intentionally small; the
orchestrator owns workflow setup, checks, dispatch, validation, and report
assembly.

## Scope

- Review exactly the patch named in the packet.
- Use the packet's commit message, diff, context snippets, checker evidence,
  and selected rule cards.
- Do not fetch, apply, reorder, or rewrite patches.
- Do not load startup, orchestrator, HTML-template, or validator-only refs.
- Do not assume a rule is irrelevant merely because it is absent if the diff
  itself shows direct evidence of a serious bug; report the evidence and mark
  the missing rule as an orchestration/selector concern.

## Tool Discipline

- Do not run ad-hoc build, sparse, checkpatch, git, or DT validation commands.
- Specifically do not run `make dt_binding_check`, `make dtbs_check`,
  `dt-doc-validate`, `dt-validate`, broad `make`, or long-running shell probes.
- Use only packet checker evidence and orchestrator-produced artifacts. If a
  needed checker artifact is absent, mark the check inconclusive/manual instead
  of launching tools.

## Evidence Discipline

- File findings only when Gate 1 is supported by concrete changed-code or
  changed-contract evidence from the packet.
- Use surrounding context to prove impact and lifecycle, not to invent facts.
- For code changes, treat `state/lifecycle:` as a source-aware edge matrix: entry outcomes, callee side effects, exit paths, paired cleanup, and async/remove observers must be named before a `SAFE` dismissal.
- Use `context-coverage` as an evidence inventory: `evidence_in_packet` means the packet contains candidate evidence, not that the rule is satisfied.
- If required context is `missing_from_packet` or absent, mark the check inconclusive instead of guessing.
- Prefer one precise finding over several speculative variants.
- Quote symbols, APIs, properties, and paths exactly as shown in the packet.

## Severity Discipline

- `[BUG]`: user-visible breakage, memory corruption, security/ownership breach,
  build failure, data corruption, deadlock, unsafe hardware operation, or ABI/DT
  contract break with real deployment impact.
- `[CONCERN]`: credible risk with incomplete proof, maintainability issue likely
  to become a bug, or behavior requiring maintainer clarification.
- `[MINOR]`: low-risk correctness, robustness, or documentation issue.
- `[NIT]`: style-only issue with no functional impact.

## Required Review Flow

1. Read the commit message and changed files.
2. Read the diff and packet context.
3. For each selected rule card, answer every `Must Check` item or mark it
   inconclusive with the missing evidence.
   For lifecycle-shaped code, enumerate every prepare/open/start/setup
   outcome and the paired cleanup owner before clearing the rule.
4. Apply the severity rules and safe-dismissal clauses before filing findings.
5. Produce output using only `output-format-mini.md`.
