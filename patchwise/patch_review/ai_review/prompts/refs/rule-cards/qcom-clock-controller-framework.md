# Rule: qcom-clock-controller-framework

## Trigger

Use this card when a patch adds or modifies a Qualcomm clock controller driver
under `drivers/clk/qcom/` — any file with `qcom_cc_desc`, `clk_rcg2`,
`clk_alpha_pll_*`, `freq_tbl`, `parent_map`, `.hw_clk_ctrl`, or `.use_rpm`.

## Must Check

### 1. Parent-data / parent-map consistency

For every `parent_map[]` array, verify each distinct `P_*` enum entry maps to
a distinct `.hw` pointer in the corresponding `parent_data[]` array. When a
`P_*_OUT_EVEN`/`OUT_ODD`/`OUT_AUX` entry exists, it must reference a separate
`clk_alpha_pll_postdiv` struct — NOT the main PLL's `.clkr.hw`. Two parent_map
entries pointing to the same `.hw` without a postdiv struct causes CCF to
report the main PLL rate for both, while hardware divides.

### 2. `qcom_cc_desc` sibling-field consistency

Compare the new driver's `qcom_cc_desc` fields against the nearest sibling of
the same CC class (e.g. `camcc-milos.c` for `camcc-eliza.c`). Flag omissions
of fields present in ALL sibling drivers:

- `.use_rpm = true` — CRITICAL: without this, runtime PM is not enabled before
  PLL writes; register access to unpowered block causes sync external abort.
  Every recent camcc/videocc/gpucc sibling has it. Missing = `[BUG]`.
- `.gdscs` / `.num_gdscs` — missing = `[CONCERN]`.
- `.driver_data` — missing = `[CONCERN]`.

### 3. `.hw_clk_ctrl` appropriateness

For every `clk_rcg2` struct with `.hw_clk_ctrl = true`, verify:
- The clock is genuinely hardware-gated (GDSC sequencer, MVS trigger), NOT a
  software-controlled bus clock (AHB, XO distribution).
- The equivalent RCG in the nearest sibling driver also has `.hw_clk_ctrl`.
- If the sibling does NOT set the flag, this is `[BUG]` — `update_config()`
  will timeout waiting for a hardware trigger that never arrives.

### 4. Freq-table / parent-rate cross-check

For `F()` entries using a divided PLL parent (`P_*_OUT_EVEN` etc.), verify the
arithmetic uses the post-divided rate. If `parent_data` points to the main PLL
without a postdiv struct, the `F()` parameters will program wrong dividers.

## Evidence Needed

- All `parent_map[]` and `parent_data[]` arrays in the file.
- The `qcom_cc_desc` struct initialization — list all fields present.
- The sibling driver's `qcom_cc_desc` (use on-demand read).
- Every RCG with `.hw_clk_ctrl = true` — its name, role, and `.ops`.
- The sibling's equivalent RCG for `.hw_clk_ctrl` comparison.

## Mandatory Attestation Record

The review MUST include this record in Code Logic Maps or DT/DT-Binding Notes:

```
qcom_clock_audit:
  parent_data_distinct: <PASS|FAIL — list each P_* and its .hw target>
  desc_sibling_compare: <sibling file> fields=[present] missing=[absent or NONE]
  hw_clk_ctrl_check: <PASS|N/A — for each flagged RCG, state role + sibling>
  use_rpm_check: <PRESENT|ABSENT with sibling comparison>
```

Omitting this record when the patch touches a Qcom CC driver is a review gap.

## Safe Dismissal

- `.use_rpm` absent: only if commit message explicitly states rails are
  always-on with hardware justification. "Consistent with hardware" alone is
  not sufficient.
- `.hw_clk_ctrl = true`: only if the equivalent RCG in the sibling also sets
  it AND the clock is documented as hardware-triggered.
- Duplicate parent_data `.hw`: only if a `clk_alpha_pll_postdiv` struct exists
  for the divided output elsewhere in the file.

## Finding Template

```text
[BUG] Missing .use_rpm in qcom_cc_desc — runtime PM not enabled before PLL writes
File: drivers/clk/qcom/<driver>.c:<qcom_cc_desc definition>
Rule: qcom-clock-controller-framework
Evidence: <new desc fields> vs <sibling desc with .use_rpm = true>
Reasoning: All sibling drivers have .use_rpm; without it register access faults
Suggestion: Add .use_rpm = true to the qcom_cc_desc

[BUG] parent_data maps P_*_OUT_EVEN to main PLL without postdiv struct
File: drivers/clk/qcom/<driver>.c:<parent_data array>
Rule: qcom-clock-controller-framework
Evidence: parent_map[1]=P_OUT_EVEN→mux 3; parent_data[1]=&pll0.clkr.hw (same as OUT_MAIN)
Reasoning: CCF reports main PLL rate; F() table programs wrong dividers
Suggestion: Add clk_alpha_pll_postdiv struct for the divided output

[BUG] .hw_clk_ctrl on software-controlled AHB RCG causes update_config timeout
File: drivers/clk/qcom/<driver>.c:<rcg struct>
Rule: qcom-clock-controller-framework
Evidence: <RCG with hw_clk_ctrl + clk_rcg2_shared_ops> vs sibling without flag
Reasoning: AHB is SW-triggered; HW trigger never arrives → timeout
Suggestion: Remove .hw_clk_ctrl = true from this RCG
```

## Severity

- Parent-data/postdiv mismatch: `[BUG]` — wrong hardware frequency.
- Missing `.use_rpm`: `[BUG]` — sync external abort on unpowered registers.
- `.hw_clk_ctrl` on SW-controlled RCG: `[BUG]` — update_config timeout.
- Missing `.gdscs`/`.driver_data`: `[CONCERN]`.
