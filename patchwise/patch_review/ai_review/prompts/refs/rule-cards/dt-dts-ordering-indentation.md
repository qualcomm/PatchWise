# Rule: dt-dts-ordering-indentation

## Trigger

Use this card when a `.dts`/`.dtsi` patch adds nodes or properties under an
existing bus/node.

## Must Check

- Are bus child nodes sorted by numeric unit address within the same parent?
- Does each node name use a generic class and `node@unit-address` form when
  `reg` is present?
- Does the unit-address match the first `reg` cell in lowercase hex without
  unnecessary leading zeroes?
- Do added properties use the same tab indentation as same-node siblings?
- Are labels and hex formatting consistent with DTS style?
- **Context-node ordering:** when a hunk inserts new nodes, extract the
  unit-address of the nearest pre-existing sibling ABOVE and BELOW the
  insertion point (from `@@` header, context lines, or on-demand read). Every
  new node's address must be greater than the preceding context node's address
  AND less than the following. A `@3d90000` inserted after a block ending at
  `@ae00000` is out-of-order even if the new nodes sort correctly among
  themselves. If the `@@` header references a child node (e.g.
  `mdss_dp0_out: endpoint`), trace to the parent's unit-address.

## Evidence Needed

- Added node/property hunk and same-parent sibling context.
- `reg` value for new unit-address nodes.
- Same-node sibling properties for indentation comparison.
- Preceding and following context node unit-addresses from the hunk.

## Mandatory Attestation Record

For every DTS patch adding nodes, state in DT/DT-Binding Notes:

```
node-ordering: preceding_context=<node@addr>, new_nodes=[addr1, addr2, ...],
  following_context=<node@addr>; preceding < all new < following: <PASS|FAIL>
```

Omitting this when nodes are added is a review gap.

## Safe Dismissal

Dismiss only when ordering and indentation are compared against same-parent or
same-node siblings, not unrelated context. For context-node ordering, dismiss
only after verifying the parent bus-node address boundaries.

## Finding Template

```text
[MINOR] DTS node ordering or formatting is inconsistent
File: <dts-path>:<node-or-property>
Rule: dt-dts-ordering-indentation
Evidence: <new node/property and sibling context>
Reasoning: <ordering, unit-address, or indentation mismatch>
Impact: <review/style issue that checkpatch/dtc may not catch>
Suggestion: <move node, fix unit-address, or align indentation>
```

## Severity

Use `[MINOR]` for ordering/unit-address issues. Use `[NIT]` for indentation-only
issues with no functional ambiguity.
