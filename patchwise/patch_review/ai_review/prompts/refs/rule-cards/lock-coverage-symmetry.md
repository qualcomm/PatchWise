# Rule: lock-coverage-symmetry

## Trigger

Code changes access to a shared field/object under `mutex_*`, `spin_lock*`,
`down`/`up`, or RCU, or adds a builder/submit path for a shared command/packet
buffer.

## Must Check

- Is a field written under a lock on one path also read/reset under the same lock on every other path, with no unlocked writer?
- Is lock coverage symmetric — not "set under lock here, cleared without lock there"?
- For a shared command/packet builder, is construction serialized with submission so a concurrent builder cannot race a partially built buffer?
- When a replacement helper is claimed to preserve/restore state, is that proven by quoting the callee body, not by the name alone?
- Are nested locks acquired in a consistent order across all paths?

## Evidence Needed

- The shared field and every path that reads/writes it, with the lock held on each.
- For builders, the construction and submission sites and their serialization.

## Safe Dismissal

Dismiss when source shows every access to the shared state holds the same lock,
or the data is provably single-threaded on the reached paths.

## Finding Template

```text
[CONCERN] Asymmetric or missing lock coverage on shared state
File: <path>:<line>
Rule: lock-coverage-symmetry
Evidence: <locked access vs unlocked access to the same field>
Reasoning: <which path accesses shared state without the lock held by others>
Impact: <data race, torn read/write, lost update, builder/submit race>
Suggestion: <hold the same lock on all access paths or document why single-threaded>
```

## Severity

`[BUG]` when an unlocked access provably races a concurrent writer with harmful
effect; otherwise `[CONCERN]` pending proof of concurrency.
