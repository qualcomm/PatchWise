# Rule: dt-dts-board-file-contract

## Trigger

Use this card when a patch adds a new board `.dts`, changes a board root node,
adds a DTB Makefile entry, or adds standalone pinctrl labels/functions.

## Must Check

- Does the board include the correct SoC `.dtsi`?
- Does `/` define `model` and compatible strings with board-specific first and
  SoC-generic fallback second?
- Is the new DTB listed in the correct `arch/*/boot/dts/*/Makefile`?
- Are new pinctrl labels referenced by real devices or explained as staged data?
- Do wake/external GPIO devices define explicit pinctrl and bias states?

## Evidence Needed

- New board file root node and include lines.
- DT Makefile hunk.
- Pinctrl labels and nodes that reference them.
- Binding or board comments for safe default pin state.

## Safe Dismissal

Dismiss only when the board file is build-reachable, identifies the board and
SoC correctly, and all standalone pinctrl data is used or justified.

## Finding Template

```text
[BUG] New board DTS is not build-reachable or not correctly identified
File: <dts-or-makefile-path>:<line-or-node>
Rule: dt-dts-board-file-contract
Evidence: <missing include/model/compatible/Makefile/pinctrl reference>
Reasoning: <why the board cannot build, match, or configure hardware correctly>
Impact: <DTB not produced, wrong board identity, or dead/missing pinctrl data>
Suggestion: <add include/root compatible/model/Makefile entry or wire pinctrl>
```

## Severity

Use `[BUG]` for missing DTB Makefile entry or invalid root identity. Use
`[CONCERN]` for unreferenced pinctrl or wake GPIOs lacking explicit state.
