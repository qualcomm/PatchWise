<!-- Conditional fragment of code-logic.md — the diff shows framework allocator/release-contract metadata patterns. Apply on top of
refs/code-logic.md §3c.2 Data-Flow Picture base prose. -->

#### Explicit release-contract checklist

Apply when a framework/helper allocates metadata, contexts, mappings, or other
side resources outside local stack/heap ownership. Read kdoc/implementation,
search sibling users when the contract is non-obvious, and verify release exactly
once on every path that transfers or keeps ownership. File `[BUG]` for omitted
release, double release, or success paths that rely on cleanup that never runs.
