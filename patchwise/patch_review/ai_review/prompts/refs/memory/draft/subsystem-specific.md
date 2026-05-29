# Review Memory — Subsystem Specific (draft)

### MEM-0003: qcom EDP PHY — NULL guard removal accepted when all platforms audited

Status: draft
Scope: subsystem:phy/qualcomm file-pattern:drivers/phy/qualcomm/phy-qcom-edp.c
Triggers:
- A patch removes a NULL pointer guard (e.g. `if (!cfg)` or
  `if (!cfg->swing_pre_emph_cfg)`) from a PHY helper with the stated or
  implied rationale that all in-tree platforms now have non-NULL cfgs.

Maintainer evidence:
- Konrad Dybcio <konrad.dybcio@oss.qualcomm.com> gave Reviewed-by on patch
  3/5 of series 20260427-edp_phy-v5 (phy: qcom: edp: Add SC7280/SC8180X
  swing/pre-emphasis tables) without raising the NULL guard removal as a
  concern. One data point only.

Review action:
- Do not raise as CONCERN. Raise as MINOR only if the commit message omits
  the list of audited in-tree platforms; request a brief audit note in the
  commit body or a WARN_ON_ONCE guard.

False-positive guards:
- Still raise as CONCERN if the removed guard protects a path reachable from
  new or external callers added in the same series.
- Still raise as CONCERN if the function is exported or visible beyond the
  driver (e.g. ops struct function pointer called from a common layer where
  not all users have been verified).
- Do not apply this entry to ops-struct function-pointer call sites (e.g.
  `ops->ldo_config()`): a NULL ops field is a separate pattern and should
  still be checked independently.

Confidence: low
Last updated: 2026-05-26

### MEM-0006: Stray blank line within Qcom QMP PHY init-cfg tables

Status: draft
Scope: subsystem:phy/qualcomm file-pattern:drivers/phy/qualcomm/phy-qcom-qmp*.c
Triggers:
- A QMP_PHY_INIT_CFG (or similar PHY init macro) table contains an unexpected
  blank line that does not logically separate distinct register groups

Maintainer evidence:
- Konrad Dybcio nit on patch 4/4 of Hawi QMP USB3-DP PHY series (2026-04-27,
  linux-arm-msm): "nit: stray \n above" flagging a blank line before
  QMP_PHY_INIT_CFG(QSERDES_V10_RX_SIGDET_ENABLES, 0x0c) inside an RX init table.

Review action:
- Flag [NIT] when a blank line appears inside a PHY init-cfg table where no
  logical register-group boundary (e.g. different IP block or register bank)
  justifies it.

False-positive guards:
- Do not flag blank lines that visually separate distinct register groups
  (e.g. TX vs RX, PCS vs SERDES, or USB3 vs DP sections).
- Do not flag the spacing between separately named table arrays.

Confidence: low
Last updated: 2026-05-26

### MEM-0009: Qcom AudioReach GPR/Q6APM/Q6PRM DTSI node hierarchy — accepted placement pattern

Status: draft
Scope: subsystem:arm/qcom file-pattern:arch/arm64/boot/dts/qcom/*.dtsi
Triggers:
- A patch adds gpr, q6apm, or q6prm nodes to a Qcom SoC DTSI for AudioReach stack support

Maintainer evidence:
- Bjorn Andersson applied QCS615 Talos EVK audio series without corrections
  (Message-ID: 20260409030156.155455-1-le.qi@oss.qualcomm.com, applied 2026-05-12),
  confirming: gpr node placed as a sibling of fastrpc inside glink_edge within
  remoteproc_adsp; q6apm and q6prm as service@ children of gpr; bedais/dais/
  clock-controller as sub-nodes. Pattern consistent with sm8450, sm8550,
  sm8650, sc8280xp DTSIs.

Review action:
- Validate gpr node placement: must be sibling of fastrpc inside glink_edge
  within remoteproc_adsp, not a top-level or standalone node.
- Validate q6apm (service@1) and q6prm (service@2) as direct children of gpr,
  with q6apmbedai, q6apmdai, and q6prmcc as their respective sub-nodes.
- Cross-check the pattern against sm8450, sm8550, sm8650, or sc8280xp DTSIs
  when reviewing a new Qcom SoC DTSI adding AudioReach support.

False-positive guards:
- Do not flag if the SoC uses a legacy APR-based audio stack rather than the
  AudioReach GPR transport.
- Do not flag if the SoC glink_edge topology differs due to a fundamentally
  different firmware communication architecture.

Confidence: low
Last updated: 2026-05-26

### MEM-0012: Prefer direct `return` over intermediate `ret` variable in early-return int functions

Status: draft
Scope: general
Triggers:
- A function is changed from `void` to `int` (or any new int-returning function)
  is written with a pattern like `ret = -EINVAL; ... if (success) { ret = 0; }
  return ret;` where the variable is assigned only once in the success branch

Maintainer evidence:
- James Clark (Coresight reviewer) on patch
  20260509-fix-trace-id-error-v2-1-c900bcbab3e9@oss.qualcomm.com: "just
  'return 0' here is a bit simpler" and "And then 'return -EINVAL' for these
  ones" - preferring `return 0` / `return -EINVAL` directly over maintaining
  a `ret` variable set once before being returned.

Review action:
- Flag [NIT] when an int-returning function uses an intermediate `ret` variable
  that is initialised to an error code and then conditionally set to 0 (or vice
  versa) with a single assignment before the return, where a direct `return 0` /
  `return -EINVAL` at each exit point would be simpler.
- Suggest replacing `ret = 0; return ret;` with `return 0;` and the default
  `return ret;` at function end with `return -EINVAL;`.

False-positive guards:
- Do not flag if the `ret` variable is assigned in more than one place, used
  in multiple expressions, or passed to other helpers before being returned.
- Do not flag if a cleanup label (e.g. `err:`) needs `ret` as the value to
  propagate - the goto pattern requires the variable.
- Do not flag if the variable is reused across multiple error paths that each
  set it to different values.

Confidence: low
Last updated: 2026-05-26

### MEM-0015: Void helpers performing fallible ops should return int, not rely on caller field-checks

Status: draft
Scope: general
Triggers:
- A `void` function performs an allocation, ID assignment, or any fallible
  operation, and stores the result in a caller-visible struct field
- The caller must inspect that struct field (e.g. `path->trace_id`) after
  the call to detect failure rather than checking a return code

Maintainer evidence:
- Leo Yan (ARM/Coresight reviewer) on v1 of patch
  20260508-fix-trace-id-error-v1-1-5f11a5456fdf@oss.qualcomm.com: suggested
  moving IS_VALID_CS_TRACE_ID() into coresight_path_assign_trace_id() and
  converting it from void to int (0 = success, <0 = errno) so callers only
  check the return value instead of inspecting path->trace_id afterward.
- Suzuki K Poulose (ARM/Coresight maintainer) agreed: "Yes please ^"
- Jie Gan acknowledged and agreed to send a follow-up refactor patch.
- Leo Yan on v3 (2026-05-11): also asked "Wouldn't it need to update perf mode
  as well?" when the perf caller still discarded the new int return value.
  Jie Gan agreed to update the perf caller for consistent usage, even though
  the existing perf code was functionally correct without changes.

Review action:
- Flag [NIT] when a void function performs an allocation or fallible assignment
  and the caller must check a side-effect struct field to detect failure.
- Suggest converting the helper to return int (0 on success, negative errno on
  failure) and removing the post-call field check from callers.
- When reviewing the conversion patch itself: also check whether any callers
  discard the new return value. If so, flag [NIT] and suggest updating those
  callers to either check the return value or add a comment documenting the
  intentional discard — even if functionally correct — for consistency.
- Do not suggest adding `__must_check` to the declaration when an existing
  caller intentionally discards the return value; that annotation would generate
  compiler warnings with no benefit unless all callers are updated simultaneously.
- This is a follow-up/improvement note, not a blocker; use [NIT], not [CONCERN].

False-positive guards:
- Do not flag if the function is part of an established callback API (e.g., an
  ops-struct function pointer) where changing the signature requires widespread
  cross-driver refactoring.
- Do not flag if the field check is a secondary validation orthogonal to the
  function's operation (e.g. checking a field that the function intentionally
  leaves for the caller to interpret).
- Do not flag if the current patch is a minimal bug-fix that correctly sets the
  error code — the refactor suggestion belongs in a separate follow-up note.
- Do not suggest `__must_check` unless ALL callers of the function check the
  return value in the same patch.

Confidence: low
Last updated: 2026-05-26

### MEM-0019: fastrpc probe — verify carveout type before using res.start as DMA address

Status: draft
Scope: subsystem:fastrpc file-pattern:drivers/misc/fastrpc.c
Triggers:
- A fastrpc probe patch stores res.start from of_reserved_mem_region_to_resource()
  directly into a dma_addr_t field without verifying the DT node is a static carveout

Maintainer evidence:
- Ekansh Gupta (reviewer) on patch 4/5 of "misc: fastrpc: Add missing bug fixes"
  (2026-05-07): "what would be res.start in case of dynamic DT node instead of
  carveout? It might create problem, can you check this part also?"
  Our automated review caught the uninitialized-res bug (err != 0 path) but
  missed this concern about the err == 0 case with dynamic reserved-memory nodes.

Review action:
- Flag [CONCERN] when fastrpc probe code assigns res.start (from
  of_reserved_mem_region_to_resource()) directly to a dma_addr field without a
  comment or guard confirming only static carveout nodes are expected.
- Ask whether the DT reserved-memory node can be a dynamic (non-carveout) region
  on any supported ADSP platform, as res.start may not be a valid DMA address there.

False-positive guards:
- Do not flag if the code uses of_reserved_mem_device_init() or
  dma_declare_coherent_memory() — those handle dynamic regions via the DMA layer.
- Do not flag if the commit body or DT binding documentation confirms the node is
  always a fixed carveout on all supported platforms.

Confidence: low
Last updated: 2026-05-26

### MEM-0020: PCI shared WAKE# GPIO -- -EBUSY is expected; add in-code comment not error propagation

Status: draft
Scope: subsystem:pci file-pattern:drivers/pci/
Triggers:
- A PCI function acquires a GPIO for WAKE# signaling via fwnode_gpiod_get() (or similar)
- Errors other than -ENOENT are silently discarded, including -EBUSY when the same GPIO descriptor is shared across multiple device nodes

Maintainer evidence:
- Manivannan Sadhasivam on patch 2/2 "PCI: Add support for PCIe WAKE# interrupt" (linux-pci, 2026-04-29): requested a code comment at the fwnode_gpiod_get() error path explaining that -EBUSY for a shared WAKE# line is expected and that the host controller driver still enables power to the topology when WAKE# fires. He did not request error propagation.

Review action:
- When PCI WAKE# GPIO acquire code silently discards -EBUSY, flag [MINOR] and suggest adding an in-code comment documenting the shared-GPIO fallback behavior rather than requesting error propagation.
- Reserve [CONCERN] for -EPROBE_DEFER silently discarded through a void call chain with no log and no deferred-probe retry, since this permanently leaves the device without WAKE# support.

False-positive guards:
- Do not downgrade to [MINOR] if -EPROBE_DEFER is discarded with no log and no retry path -- that remains [CONCERN].
- Do not apply outside PCI WAKE# GPIO setup paths where shared-GPIO semantics are not documented.

Confidence: low
Last updated: 2026-05-26

### MEM-0023: clk KUnit tests must be DAMP — do not modify existing test functions to add new-feature assertions

Status: draft
Scope: subsystem:clk file-pattern:drivers/clk/clk_test.c
Triggers:
- A patch adds assertions for a new clk feature (e.g., assigned-clock-sscs) inside
  an existing test function designed for a different feature (e.g.,
  clk_assigned_rates_assigns_one, clk_assigned_rates_assigns_multiple)
- A patch appends a new KUNIT_CASE_PARAM entry to an existing kunit_suite without
  providing a fully self-contained new test function and matching param array for
  the new feature

Maintainer evidence:
- Stephen Boyd <sboyd@kernel.org> on [PATCH v9 4/6] clk: Add KUnit tests for
  assigned-clock-sscs (2026-04-28): "clk_assigned_rates_assigns_multiple() is
  saying that a clock-assigned-rates property with multiple rates assigns multiple
  rates. It's not supposed to be testing ssc. Don't modify it." And: "Instead of
  adding on another case just copy the entire thing, kunit_case, test_params, etc.
  and implement the tests you want. Test code is the opposite of DRY (DAMP?) so
  don't be afraid to just copy a bunch of stuff. The reason why that is encouraged
  is because existing tests are unchanged, and we don't have to worry that this
  patch breaks the existing tests."

Review action:
- Flag [MINOR] when a patch modifies an existing clk KUnit test function to add
  assertions for a feature the test was not designed to cover.
- Suggest creating a wholly new self-contained test suite (new kunit_case entries,
  new test_params array, new DTSO overlays) that covers the new feature end-to-end.
  The existing test functions and their test_params must remain unmodified.

False-positive guards:
- Do not flag if the modification genuinely fixes a wrong expectation in the
  existing test (e.g., correcting a stale rate constant).
- Do not flag refactoring patches that reorganize helpers while preserving test
  semantics.
- Do not apply to non-clk KUnit suites without separate confirming evidence from
  that subsystem's maintainer.

Confidence: low
Last updated: 2026-05-26

### MEM-0024: KUnit test param arrays — check ALL block comments AND desc strings for copy-paste errors

Status: draft
Scope: file-pattern:drivers/clk/clk_test.c
Triggers:
- A patch introduces a new KUnit test param array by copying an existing one and
  adapting it for a different feature (e.g., copying
  clk_assigned_rates_skips_test_params to create clk_assigned_sscs_skips_test_params)
- Each entry in the new array has both a /* ... */ block comment and a .desc string

Maintainer evidence:
- Stephen Boyd <sboyd@kernel.org> on [PATCH v9 4/6] clk: Add KUnit tests for
  assigned-clock-sscs (2026-04-28): noted "It is?" on an inaccurate block comment,
  "Typo?" on a comment still saying "assigned-clock-rates property" inside the sscs
  array, and "None of these comments are correct." on the full
  clk_assigned_sscs_skips_test_params[] array. Our automated review caught only the
  last .desc string ("provider" vs "consumer") but missed the block-comment
  copy-paste errors in every other entry (wrong property name, wrong placement label).

Review action:
- When a new test param array is introduced by copying an existing one, check EVERY
  entry's block comment AND .desc string — not just the last entry — for copy-paste
  errors: wrong property name (e.g., "rates" vs "sscs"), wrong placement label
  (e.g., "provider" when .consumer_test = true), and stale references to the source
  array's test subject.
- Flag each distinct error as [MINOR]; group entries that share the same root cause
  but list all affected entries by approximate line number.

False-positive guards:
- Do not flag comments that accurately reuse the same description because the
  underlying test logic genuinely is the same for both features.
- Do not flag the .desc string if it already accurately names the feature under test.

Confidence: low
Last updated: 2026-05-26

### MEM-0025: Qcom pinctrl series — DTS patches route through Bjorn's qcom SoC tree, not pinctrl tree

Status: draft
Scope: subsystem:pinctrl/qcom
Triggers:
- A series modifies both pinctrl files (dt-bindings and/or driver) AND
  arch/arm64/boot/dts/qcom/ device-tree files (DTS/DTSI)
- The DTS patch adds or modifies Qualcomm PMIC or SoC device-tree nodes

Maintainer evidence:
- Linus Walleij on the pm8010 GPIO series
  (20260507-pm8010_gpio-v1-0-3bce9da8d2ba@oss.qualcomm.com, 2026-05-23):
  applied patches 1/3 (dt-bindings) and 2/3 (driver) to the pinctrl tree, then
  wrote "Take patch 3 through the SoC qcom tree (Bjorn) please."

Review action:
- In a mixed series (pinctrl binding + driver + Qcom arch/arm64 DTS patch), note
  that the DTS patch(es) should be routed through Bjorn Andersson's qcom SoC
  tree separately from the pinctrl patches.
- Flag in the review summary if the series bundles DTS changes with pinctrl
  binding/driver changes, so the author knows to coordinate two tree merges.

False-positive guards:
- Do not apply to series that only touch arch/arm64/boot/dts/qcom/ — those go
  through the qcom SoC tree entirely without this split.
- Do not apply to arm32 Qcom DTS (arch/arm/boot/dts/qcom/) without separate
  confirming evidence for that tree's routing.
- Do not flag if the series cover letter already acknowledges the split-tree routing.

Confidence: low
Last updated: 2026-05-26

### MEM-0026: PCI/ASPM -- masking L1 from aspm_support must also mask L1SS

Status: draft
Scope: subsystem:pci file-pattern:drivers/pci/pcie/aspm.c
Triggers:
- A patch masks PCIE_LINK_STATE_L1 from link->aspm_support (or equivalent
  per-link ASPM bitmask) based on a DT property or platform policy
- The same patch does not also clear PCIE_LINK_STATE_L1SS from aspm_support

Maintainer evidence:
- Patchwise AI reviewer on "PCI/ASPM: Mask ASPM states based on Devicetree
  properties" (kernel@oss.qualcomm.com, 2026-05-06): masking L1 from
  aspm_support without also masking L1SS leaves L1 PM substates appearing
  capable even when L1 is disabled -- because aspm_capable is initialized from
  aspm_support (and reset to it in pcie_update_aspm_capable()). Missed-by-us:
  our automated review noted the aspm_default stale-bit edge case but did not
  flag this L1SS dependency.

Review action:
- Flag [CONCERN] when a patch clears PCIE_LINK_STATE_L1 from aspm_support
  without also clearing PCIE_LINK_STATE_L1SS. L1 PM substates (L1.1, L1.2,
  L1.1-PCIPM, L1.2-PCIPM) all require L1 as the base power state; without L1
  they can never activate, yet a stale L1SS capability bit may confuse policy.
- Suggest adding link->aspm_support &= ~PCIE_LINK_STATE_L1SS; immediately
  after the L1 masking line.

False-positive guards:
- Do not flag if PCIE_LINK_STATE_L1SS is also cleared in the same conditional
  block (regardless of order).
- Do not flag if an outer guard already ensures L1SS is disabled whenever L1
  is disabled (e.g. a higher-level check that gates the whole L1SS path).
- Do not apply to read-only checks of ASPM state; only applies to write/mask
  paths that modify aspm_support, aspm_capable, or equivalent bitmasks.

Confidence: low
Last updated: 2026-05-26

### MEM-0028: Qcom QMP PHY header — new generic PHY-index constants duplicate existing USB43DP constants

Status: draft
Scope: file-pattern:include/dt-bindings/phy/phy-qcom-qmp.h
Triggers:
- A patch adds new "generic" logical PHY index constants to phy-qcom-qmp.h with
  values 0 and 1 for use with `#phy-cells = <1>` providers (e.g. QMP_PHY_SELECTOR_0,
  QMP_PHY_SELECTOR_1)

Maintainer evidence:
- Patchwise AI review on patch 2/7 of 20260507-link_mode_support-v2 (2026-05-07):
  "QMP_USB43DP_USB3_PHY and QMP_USB43DP_DP_PHY already define values 0 and 1 for
  the same purpose (logical PHY index for #phy-cells = <1> providers). These generic
  aliases are redundant duplicates with no users in the tree." Our automated review
  gave this patch "Clean minimal addition" (POSITIVE) and missed the duplication entirely.

Review action:
- Flag [CONCERN] when a patch adds constants with values 0 and 1 as generic PHY
  selectors for `#phy-cells = <1>` providers in phy-qcom-qmp.h.
- Point to `QMP_USB43DP_USB3_PHY = 0` and `QMP_USB43DP_DP_PHY = 1` as the
  existing equivalent; suggest reusing those or defining a device-specific
  pair (e.g. QMP_PCIE_GLYMUR_PHY_A) to avoid namespace confusion.

False-positive guards:
- Do not flag constants that serve a truly distinct semantic purpose even if their
  numeric values happen to be 0 and 1 (e.g. mode-select values that index into a
  different table from PHY instance selection).
- Do not apply outside phy-qcom-qmp.h without separate confirming evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0030: `device_get_match_data()` result must be checked for NULL before use

Status: draft
Scope: general
Triggers:
- A probe or init function calls `device_get_match_data()` (or
  `of_device_get_match_data()`) and stores the result in a local pointer
- The pointer is immediately dereferenced (e.g., `data->descs`, `data->num_descs`)
  without a preceding NULL check

Maintainer evidence:
- Patchwise code review on patch 4/7 of Qcom clkref series (kernel@oss.qualcomm.com,
  2026-05-16): "`device_get_match_data()` can return NULL, and `data` is dereferenced
  without a NULL check" in `tcsr_cc_glymur_probe()`. The automated build (W=1) and
  checkpatch did not flag this; only code-logic review caught it.

Review action:
- Flag [BUG] when `device_get_match_data()` or `of_device_get_match_data()` result is
  used without a preceding NULL check.
- Suggest: `if (!data) return -EINVAL;` (or `-ENODEV`) immediately after the call.

False-positive guards:
- Do not flag if the pointer is guarded by a NULL check earlier in the same function
  that covers the dereference site.
- Do not flag if the `of_match_table` entries all carry non-NULL `.data` and the call
  site cannot be reached with an unregistered device (e.g. static-only drivers).
- Do not downgrade to [MINOR]: a NULL dereference is a kernel oops regardless of
  how unlikely the missing-data path is.

Confidence: low
Last updated: 2026-05-26

### MEM-0033: EXPORT_SYMBOL must match the export class used by existing related exports in the same file

Status: draft
Scope: general
Triggers:
- A patch adds EXPORT_SYMBOL() for a new or previously unexported function
- The same file already exports all related functions exclusively using EXPORT_SYMBOL_GPL

Maintainer evidence:
- Trilok Soni on [PATCH] genirq: Export irq_can_set_affinity()
  (kernel@oss.qualcomm.com, 2026-05-07): "irq_set_affinity is GPL, so we should
  keep this as GPL symbol as well?" -- independently raised the same concern as the
  automated review; author updated to EXPORT_SYMBOL_GPL in v2 without objection.

Review action:
- Flag [CONCERN] when a new EXPORT_SYMBOL() is added to a file where all related
  existing exports use EXPORT_SYMBOL_GPL.
- Check the file for other exports of closely related functions; if they are all
  EXPORT_SYMBOL_GPL, the new export should also be EXPORT_SYMBOL_GPL.
- Note that plain EXPORT_SYMBOL allows non-GPL modules to call the function while
  the rest of the API remains GPL-only -- this policy asymmetry requires explicit
  justification.

False-positive guards:
- Do not flag if the commit body explicitly justifies allowing non-GPL module
  access (and that rationale has been acknowledged by the maintainer).
- Do not flag if the file's existing exports are a mix of EXPORT_SYMBOL and
  EXPORT_SYMBOL_GPL with no consistent convention to enforce.
- Do not flag if the new function is unrelated in semantics to the GPL-exported
  group (e.g., a pure utility with no dependency on GPL-only data structures).

Confidence: low
Last updated: 2026-05-26

### MEM-0036: Prefer early-continue guard clause inside loops to reduce nesting depth

Status: draft
Scope: general
Triggers:
- A loop body handles a trivial "skip this iteration" case with an outer
  if-block that wraps the main logic (e.g. `if (x != 0) { if (valid(x)) {...} }`)
- The loop could instead use an early `continue` for the trivial case and
  leave the main logic flat and un-indented

Maintainer evidence:
- Leo Yan (ARM/Coresight reviewer) on patch v3 of
  20260509-fix-trace-id-error-v3-1 (coresight: fix missing error code, 2026-05-11):
  suggested replacing nested `if (trace_id != 0) { if (IS_VALID...) ... }` with
  `if (trace_id == 0) continue; /* 0 means no assignment, keep searching */`
  followed by flat logic, commenting "Early exit can reduce indentation depth,
  and it handles simple cases first and then the complex logic."

Review action:
- Flag [NIT] when a loop body uses an outer if-block to skip a trivial case and
  wraps the meaningful logic at an extra nesting level.
- Suggest inverting the condition with `continue` and a short comment explaining
  the skip: `if (<trivial_case>) continue; /* reason */`
- The main logic then becomes flat and un-indented, improving readability.

False-positive guards:
- Do not flag if the trivial-case branch does more than skip (e.g. accumulates
  state, logs, or requires cleanup before continuing).
- Do not apply outside loop bodies — early return for non-loop guard clauses is
  covered by MEM-0012.
- Do not flag if the existing nesting is already only one level deep and
  inverting the condition would not meaningfully reduce indentation.

Confidence: low
Last updated: 2026-05-26

### MEM-0037: Qcom PCIe shared bus clocks — do not vote for clocks managed by interconnect or bootloader HW_CTL

Status: draft
Scope: subsystem:pci file-pattern:Documentation/devicetree/bindings/pci/qcom,pcie*.yaml
Triggers:
- A new Qcom PCIe RC DT binding or DT node includes GCC_QMIP_PCIE_AHB_CLK,
  GCC_CNOC_PCIE_SF_AXI_CLK, GCC_CFG_NOC_PCIE_ANOC_AHB_CLK, or other shared
  PCIe bus/interconnect clocks not tied to a specific PCIe RC instance
- The stated rationale is data-path bandwidth between PCIe and DDR (i.e. clocks
  that other platforms cover via interconnect votes or HW_CTL mode)

Maintainer evidence:
- Mike Tipton on PCI: qcom: Add support for Eliza series (linux-arm-msm,
  2026-05-02): QMIP AHB clocks "should never be required to explicitly vote for"
  in SW; they are only for bootloader config and normally placed in HW_CTL mode.
  GCC_CNOC_PCIE_SF_AXI_CLK and GCC_CFG_NOC_PCIE_ANOC_AHB_CLK also "shouldn't
  normally be required" since they are typically enabled by default or put under
  HW control in bootloaders on Eliza.
- Krishna Chundru confirmed removing both clocks caused no regression on Eliza HW
  (2026-05-19). Konrad Dybcio agreed: "if you can confirm that removing these
  clocks doesn't break anything, I'd follow that advice" (2026-05-11).
- Our automated review did not raise this concern (missed-by-us).

Review action:
- Flag [MINOR] when a new Qcom PCIe RC DT node or binding adds shared bus clocks
  (QMIP AHB, CNOC_PCIE_SF_AXI, CFG_NOC_PCIE_ANOC_AHB or equivalent) that are not
  instance-specific.
- Ask whether these clocks are already managed via the interconnect bandwidth vote
  path or set to HW_CTL mode in bootloaders; if so, suggest omitting them.

False-positive guards:
- Do not flag instance-specific clocks (e.g., GCC_PCIE_0_PIPE_CLK,
  GCC_PCIE_0_AUX_CLK, GCC_PCIE_0_MSTR_AXI_CLK) — those are required for RC
  operation.
- Do not flag if the commit body or a Qualcomm IP expert explicitly states the
  clock is absent from the interconnect path and must be voted by the RC driver on
  this SoC.
- Do not apply to non-Qcom PCIe DT nodes without separate confirming evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0039: fastrpc_buf->cctx — get()/put() must be symmetric on all alloc/free paths

Status: draft
Scope: subsystem:fastrpc file-pattern:drivers/misc/fastrpc.c
Triggers:
- A patch stores `fl->cctx` (a `struct fastrpc_channel_ctx *`) inside a `fastrpc_buf`
  or any struct with DMA-buf lifetime, without calling `fastrpc_channel_ctx_get()`
- The stored pointer is later used in DMA-buf callbacks (fastrpc_buf_free,
  fastrpc_dma_buf_attach, fastrpc_mmap) that may run after `fastrpc_device_release()`
  has dropped the channel_ctx reference
- A patch calls `fastrpc_channel_ctx_get(buf->cctx)` before a fallible operation (e.g.
  `dma_alloc_coherent()`) but an early-exit error path calls `kfree(buf)` without a
  matching `fastrpc_channel_ctx_put()` — causing a kref leak on the failure path

Maintainer evidence:
- Patchwise AI reviewer (kernel@oss.qualcomm.com, 2026-05-12) on "misc: fastrpc: fix
  use-after-free of cctx in fastrpc_buf_free": independently identified that
  `buf->cctx = fl->cctx` is a raw pointer copy without a kref bump, and that
  `fastrpc_device_release()` calling `fastrpc_channel_ctx_put()` can free cctx before
  DMA-buf callbacks complete — identical to the [BUG] raised by our automated review.
- Patchwise AI reviewer (kernel@oss.qualcomm.com, 2026-05-12) on the same patch: in a
  separate code-review pass, independently flagged that the patch's own
  `__fastrpc_buf_alloc()` error path called `kfree(buf)` after
  `fastrpc_channel_ctx_get()` without a matching `fastrpc_channel_ctx_put()`. Confirmed
  the error-path kref-leak was a regression introduced by the fix itself — matching
  the [BUG] in the automated review.

Review action:
- Flag [BUG] when a struct with DMA-buf or other post-fl lifetime stores `fl->cctx`
  without a matching `fastrpc_channel_ctx_get()` call at alloc time.
- Flag [BUG] when `fastrpc_channel_ctx_get()` is called in an allocation function but
  any error exit path (e.g. after `dma_alloc_coherent()` failure) calls `kfree(buf)`
  without first calling `fastrpc_channel_ctx_put(buf->cctx)`. The get()/put() pair must
  be symmetric across ALL exit paths, including error returns.
- Require a corresponding `fastrpc_channel_ctx_put(buf->cctx)` in the normal free path
  before `kfree(buf)`, mirroring the pattern in `fastrpc_context_alloc()` /
  `fastrpc_context_free()`.

False-positive guards:
- Do not flag if `fastrpc_channel_ctx_get()` is already called immediately after the
  pointer assignment in the same block.
- Do not flag error paths that already call `fastrpc_channel_ctx_put()` before `kfree`.
- Do not apply outside drivers/misc/fastrpc.c without separate confirming evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0041: Qcom TLMM pinctrl — modern SoCs must omit `intr_target_reg` from PINGROUP macro

Status: draft
Scope: subsystem:pinctrl/qcom file-pattern:drivers/pinctrl/qcom/pinctrl-*.c
Triggers:
- A new Qcom TLMM pinctrl driver defines a PINGROUP macro that includes an
  `.intr_target_reg` field
- The SoC is modern (introduced in or after the linux-next cycle that contains
  commit 0720208b37ae)

Maintainer evidence:
- Konrad Dybcio on "pinctrl: qcom: Add the tlmm driver for Maili platform"
  (20260421-maili-pinctrl-v1, linux-arm-msm 2026-04-22): pointed to commit
  0720208b37ae ("pinctrl: qcom: Drop redundant intr_target_reg on modern SoCs")
  and requested the PINGROUP macro and its code generator both be updated to
  omit this field. Author acknowledged and agreed to fix. Our automated review
  did not flag this (missed-by-us).
- Konrad Dybcio on "pinctrl: qcom: Add Shikra pinctrl driver"
  (20260421-shikra-pinctrl-v2, linux-arm-msm 2026-04-22): same comment, same
  commit reference. Author acknowledged: "Thanks, I will remove this entry."
  Second independent instance confirming the pattern on a different SoC.

Review action:
- Flag [MINOR] when a new Qcom TLMM pinctrl driver PINGROUP macro includes
  `.intr_target_reg`. Cite commit 0720208b37ae and suggest removing the field.
- If the driver was auto-generated, also ask the author to update the generator
  so future outputs omit `.intr_target_reg`.

False-positive guards:
- Do not flag legacy SoC drivers (pre-dating commit 0720208b37ae) that are
  being minimally patched and not fully rewritten.
- Do not flag if the driver commit message explicitly justifies retaining the
  field for a non-standard register layout on that SoC.

Confidence: medium
Last updated: 2026-05-26

### MEM-0042: ARM/Coresight --- bus_find_device() reference must be held by the caller, not dropped inside the lookup helper

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/
Triggers:
- A patch modifies coresight_get_sink_by_id() or a similar coresight bus-lookup
  helper to call put_device() inside the helper and return a raw
  struct coresight_device * pointer
- The stated rationale is that callers do not need the reference because they
  acquire one later via coresight_get_ref() / coresight_enable_path()

Maintainer evidence:
- Suzuki K Poulose (ARM/Coresight maintainer) on coresight: drop lookup reference
  in coresight_get_sink_by_id() (20260519084317.1472444-1-make24@iscas.ac.cn,
  2026-05-19): I would rather drop the reference in the etm_setup_aux, to make
  sure we are still dealing with a valid device, that has not been removed under
  our feet. Our automated review analyzed the gap between lookup and
  coresight_get_ref() and concluded it was safe; the maintainer rejected this
  reasoning and NACd the patch. Missed-by-us: verdict was READY TO APPLY but
  the patch was refused at the design level.

Review action:
- Flag [CONCERN] when a coresight bus-lookup helper drops its bus_find_device()
  reference before returning a raw struct coresight_device *.
- Even if the caller appears to acquire a stable reference shortly afterward (e.g.
  via coresight_get_ref() inside coresight_enable_path()), the gap between
  the lookup return and that acquisition is enough for the device to be unregistered.
- Suggest that the caller retain the bus_find_device() reference across the
  lookup-to-use boundary and drop it only after the stable reference is acquired.

False-positive guards:
- Do not flag if the caller acquires a stable get_device() / coresight_get_ref()
  reference atomically in the very next statement with no preemption point between.
- Do not apply outside ARM/Coresight drivers without independent confirming
  maintainer evidence from that subsystem.

Confidence: low
Last updated: 2026-05-26

### MEM-0043: fastrpc — commit body must explain DSP-side semantics of changed protocol parameters

Status: draft
Scope: subsystem:fastrpc file-pattern:drivers/misc/fastrpc.c
Triggers:
- A fastrpc patch fixes a firmware-facing protocol parameter (e.g. pageslen,
  client_id, init.memlen in FASTRPC_IOCTL_INIT_CREATE_STATIC) without
  explaining what that parameter controls on the remote processor (Audio PD, ADSP)
- The commit body describes the kernel-side change but omits the DSP-side effect
  of the old vs. new value

Maintainer evidence:
- Chenna Kesava Raju on patch 1/5 of "misc: fastrpc: Add missing bug fixes"
  (linux-arm-msm, 2026-05-08): "Please explain why the memory is not added when
  pageslen is 0. Some background on this memory pool usage on audio pd running on
  DSP would help reviewers relate it to the issue." The commit body fixed pageslen
  from 0 to 1 but did not explain that pageslen=0 means no buffer pages are
  registered with Audio PD, leaving the memory pool empty. Missed-by-us.

Review action:
- Flag [MINOR] when a fastrpc commit fixes a DSP-facing IOCTL parameter but the
  commit body contains no sentence explaining the parameter's role on the remote side.
- Suggest adding one sentence such as: "pageslen=0 means no buffer pages are sent to
  Audio PD, so the pool starts empty and PD falls back to remote heap allocation."

False-positive guards:
- Do not flag if the commit body already explains the remote-processor semantics,
  even briefly.
- Do not flag parameter changes that are purely kernel-side with no direct DSP-side
  protocol effect (e.g. local struct field reordering, logging-only changes).

Confidence: low
Last updated: 2026-05-26

### MEM-0044: fastrpc probe — question whether dma_alloc_coherent is appropriate for Audio PD reserved-memory

Status: draft
Scope: subsystem:fastrpc file-pattern:drivers/misc/fastrpc.c
Triggers:
- A fastrpc probe patch calls dma_alloc_coherent() on the reserved-memory region
  obtained via of_reserved_mem_region_to_resource() for the Audio PD path
- The commit body does not explain why coherent DMA allocation is used rather than
  direct use of the physical address (e.g. ioremap or of_reserved_mem_device_init())

Maintainer evidence:
- Ekansh Gupta (reviewer) on patch 4/5 of "misc: fastrpc: Add missing bug fixes"
  (linux-arm-msm, 2026-05-08): "just ensure that this dma_alloc_coherent is really
  needed and I think tests should also be tried with this change as it's a logic
  change." Our review caught error-path resource leaks around the DMA allocation but
  did not question whether dma_alloc_coherent was the appropriate API. Missed-by-us.

Review action:
- Flag [CONCERN] when fastrpc probe uses dma_alloc_coherent() on reserved memory from
  of_reserved_mem_region_to_resource(); ask whether the allocation is needed vs. using
  the physical address directly or initialising via of_reserved_mem_device_init().
- Note that fastrpc Audio PD memory lifecycle changes require runtime testing on ADSP
  hardware; if neither commit message nor cover letter mentions testing, add a review
  note requesting it.

False-positive guards:
- Do not flag if the commit body or cover letter explains why coherent DMA allocation
  is required for this platform's memory type.
- Do not apply outside the fastrpc Audio PD reserved-memory probe path.
- MEM-0019 covers using res.start directly as a dma_addr; apply both when the probe
  uses res.start AND dma_alloc_coherent.

Confidence: low
Last updated: 2026-05-26

### MEM-0046: Qcom SCM tracepoints -- TP_fast_assign SMC args must use unsigned long throughout for cross-arch correctness

Status: draft
Scope: subsystem:qcom file-pattern:drivers/firmware/qcom/qcom_scm_trace.h
Triggers:
- A TP_fast_assign block copies SMC call arguments (e.g. arm_smccc_args.args[])
  into a tracepoint dynamic array or field using u64 type anywhere in the chain:
  __dynamic_array(u64, args, ...), u64 *dst = __get_dynamic_array(args), or
  (u64)src[i] upcast per element
- arm_smccc_args.args[] is unsigned long (32-bit on arm32, 64-bit on arm64);
  using u64 throughout causes type mismatches and build warnings/errors on arm32

Maintainer evidence:
- Konrad Dybcio <konrad.dybcio@oss.qualcomm.com> on patch 1/2 of
  "firmware: qcom: scm: add tracepoints for the SMC call interface"
  (linux-arm-msm, 2026-04-27): "args[i] is a u64 and dst[i] is an
  unsigned long, so this typecast makes no sense - maybe you intended
  it to be the other way around, to truncate the higher bits for 32-bit
  architectures?" and "(also please make sure you at least compile-test
  this for arm32)". Also flagged "This should be an unsigned long ptr
  instead, since it's not the same on arm32 and you'll get build
  warnings/errors" for the `u64 *dst` pointer type.
  Our automated review caught the redundant (u8) cast in min_t but missed
  both the wrong-direction cast and the wrong pointer type. Missed-by-us.

Review action:
- Flag [MINOR] when a TP_fast_assign block that copies SMC args uses u64
  anywhere in the chain: __dynamic_array element type, the dst pointer
  type, or the per-element cast. The correct pattern throughout is
  `unsigned long`: declare `__dynamic_array(unsigned long, args, ...)`,
  use `unsigned long *dst = __get_dynamic_array(args)`, and cast each
  element as `(unsigned long)src[i]`.
- Note if the header has not been compile-tested for arm32 (series cover
  letter or commit message mentions only arm64 testing).

False-positive guards:
- Do not flag if the source array type is also u64 (not unsigned long)
  and the code already uses u64 consistently with no arm32 users.
- Do not flag a (unsigned long) cast that already correctly narrows a u64.
- Do not apply to TP_fast_assign blocks copying scalar (non-array) u64
  fields -- those generate compiler warnings more visibly.

Confidence: low
Last updated: 2026-05-26

### MEM-0048: ARM/Coresight — author-acknowledged PREEMPT_RT TODO accepted as deferred work

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/
Triggers:
- A patch calls a potentially sleeping function (e.g. `put_device()`, `kfree_rcu()`)
  while holding a raw spinlock, creating a scheduling-while-atomic risk on PREEMPT_RT
- The submitted patch itself contains a TODO comment explicitly acknowledging the
  PREEMPT_RT limitation and implying a future fix is needed

Maintainer evidence:
- Suzuki K Poulose applied patch 10/28 of
  20260515-arm_coresight_path_power_management_improvement-v14
  (coresight: Take per-CPU source reference during AUX setup, 2026-05-18) with
  "Applied, thanks!" without requesting the RT concern be fixed first.
  The patch called put_device() under coresight_dev_lock (raw_spinlock) and shipped a
  TODO comment acknowledging the scheduling-while-atomic risk on PREEMPT_RT.
  One data point only.

Review action:
- Still flag [CONCERN] when a sleeping function is called under a raw spinlock.
- In the review text, note whether the submitted patch already contains a TODO
  acknowledging the RT limitation; if so, add: "The TODO comment signals the author
  is aware; this may be accepted as deferred work."
- Do not uprate to [BUG] solely because of PREEMPT_RT scheduling-while-atomic when
  a TODO is already present in the patch itself.

False-positive guards:
- Do not lower severity to [MINOR] when no TODO is present — absence of an
  acknowledgement means the author may not be aware of the RT implication.
- Do not generalise beyond ARM/Coresight without additional evidence from other
  subsystems (one data point only).

Confidence: low
Last updated: 2026-05-26

### MEM-0049: Do not replicate non-exported kernel function logic — propose an export patch instead

Status: draft
Scope: general
Triggers:
- A driver introduces a private helper whose body closely mirrors an existing
  non-exported kernel function (e.g. `irq_can_set_affinity()` duplicated in a
  wireless driver as `ath12k_pci_irq_can_set_affinity()`)
- The stated rationale for not calling the kernel function directly is that
  it is not an exported symbol

Maintainer evidence:
- Jeff Johnson <jeff.johnson@oss.qualcomm.com> on ath12k patch
  "[PATCH ath-next v2] wifi: ath12k: enable threaded NAPI when IRQ affinity
  is unavailable" (2026-05-06): "Don't replicate code. If we have a use case
  to use the function then propose a patch to export the function, giving a
  very clear argument for needing it." The driver duplicated
  `irq_can_set_affinity()` logic; Jeff rejected the copy. Our automated
  review praised the helper as correctly scoped and did not flag the
  duplication (missed-by-us).

Review action:
- Flag [CONCERN] when a driver introduces a private helper that duplicates
  the logic of a named, non-exported kernel function.
- Name the kernel function being duplicated and suggest proposing a separate
  patch to export it with a clear justification, rather than maintaining an
  in-driver copy.
- If the export class must also match existing GPL-only exports in that
  file, combine this finding with MEM-0033.

False-positive guards:
- Do not flag if the driver's helper has genuinely distinct semantics or
  intentionally omits conditions from the kernel function for a documented
  reason.
- Do not flag if the kernel function cannot be safely exported due to
  internal locking or data-structure dependencies (and the commit body
  explains this).
- One data point only (Jeff Johnson / ath12k); treat as draft until a
  second maintainer confirms the same expectation.

Confidence: low
Last updated: 2026-05-26

### MEM-0050: Kernel tracepoint header in drivers/ subdirectory -- Makefile include path and TRACE_INCLUDE_FILE both required

Status: draft
Scope: general file-pattern:drivers/*/
Triggers:
- A new trace header (e.g. foo_trace.h) is placed under drivers/ rather than
  include/trace/events/
- The corresponding Makefile does NOT add ccflags-y += -I$(src) to expose
  the directory to the compiler include search path
- The header does NOT define TRACE_INCLUDE_FILE (or does not undef it before
  redefining) to name the file explicitly

Maintainer evidence:
- Konrad Dybcio <konrad.dybcio@oss.qualcomm.com> on patch 0/2 of
  "firmware: qcom: scm: add tracepoints for the SMC call interface"
  (linux-arm-msm, 2026-04-27): series failed to compile without both
  ccflags-y += -I$(src) in drivers/firmware/qcom/Makefile AND
  #undef TRACE_INCLUDE_FILE + #define TRACE_INCLUDE_FILE qcom_scm_trace
  in the header. Reproduced with make ARCH=arm64 LLVM=1 -j24 /
  clang 22.1.3. Our automated build (ARCH=arm64 gcc) reported PASS and
  completely missed the compilation failure. Missed-by-us (critical).

Review action:
- Flag [BUG] when a new trace header is added under drivers/ without BOTH:
  1. ccflags-y += -I$(src) in the same directory Makefile, AND
  2. #undef TRACE_INCLUDE_FILE followed by #define TRACE_INCLUDE_FILE <basename>
     at the bottom of the header (after the endif guard).
- Note that include/trace/events/ headers do not need this treatment (the
  standard include path already covers that directory).
- Add a note to check compilation with clang (LLVM=1) for arm64 if only
  gcc testing is mentioned in the cover letter.

False-positive guards:
- Do not flag if ccflags-y += -I$(src) is already present in the Makefile
  (e.g., added by an earlier patch in the same series).
- Do not flag trace headers placed under include/trace/events/ -- the include
  path is handled by the build system automatically there.
- Do not downgrade to [MINOR]: missing include path causes a hard compile error.

Confidence: low
Last updated: 2026-05-26

### MEM-0051: Prefer int over small unsigned integer types for loop indices

Status: draft
Scope: general
Triggers:
- A loop (for, while) uses a small unsigned type (u8, u16, uint8_t, uint16_t)
  as the loop index or counter variable
- The bounded range happens to fit, but the choice of a narrow type creates
  fragility if the bound expression changes in the future
- The small type provides no meaningful memory saving (auto-variable on stack)

Maintainer evidence:
- Konrad Dybcio <konrad.dybcio@oss.qualcomm.com> on patch 1/2 of
  "firmware: qcom: scm: add tracepoints for the SMC call interface"
  (linux-arm-msm, 2026-04-27): "for (u8 i = 0; i < n; i++) -- It's not
  currently possible for u8 to overflow (min x & 0xF, 6), but this
  introduces a point of fragility while giving us no memory savings.
  Please just use int for i."

Review action:
- Flag [NIT] when a loop uses u8 or another small unsigned type as the
  loop counter or index variable.
- Suggest replacing with int (or unsigned int if signedness matters):
  the range is always within int, the compiler generates equivalent code,
  and future changes to the bound expression are safer.

False-positive guards:
- Do not flag if the loop index doubles as a protocol field or bit-width
  constrained value that must be stored or passed at that exact width.
- Do not flag range-for or iterator patterns where the type comes from a
  container API (e.g., list_for_each_entry).
- Use [NIT], not [MINOR]: this is a fragility concern, not a bug.

Confidence: low
Last updated: 2026-05-26

### MEM-0052: ARM/Coresight — sysfs visibility flag should suppress all non-label attrs, not specific named attrs

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/coresight-sysfs.c
Triggers:
- A patch introduces a device flag (e.g. `no_sysfs_mode`) to hide sysfs attributes
  in a coresight `is_visible()` callback
- The implementation checks specific attribute pointers by name (e.g.
  `attr == &dev_attr_enable_sink.attr || attr == &dev_attr_enable_source.attr`)
  rather than using a catch-all branch to hide all unhandled attributes

Maintainer evidence:
- Leo Yan (ARM/Coresight reviewer) on
  20260507-james-cs-hide-trbe-enable-v1-1-b4e40439f44c@linaro.org (2026-05-13):
  "I'd prefer no_sysfs_mode to work as a general flag rather than being limited to
  sink/source devices only." When asked which other files would be hidden, Leo
  clarified: "The label is already handled separately. So we can hide the rest
  attributes when no_sysfs_mode is set?" — preferring a catch-all final branch
  over per-attribute pointer comparisons. Our review noted the extra coverage path
  as "harmless dead code" and missed the generality concern (missed-by-us).

Review action:
- Flag [MINOR] when a coresight `is_visible()` callback hides attributes by
  hardcoding per-attribute `attr == &dev_attr_X.attr` pointer comparisons under a
  device-mode flag, where a catch-all final branch would be simpler and more
  future-proof.
- Suggest restructuring so that after any named attribute branches (e.g. label),
  the flag check covers all remaining attributes generically:
  `if (csdev->no_sysfs_mode) return 0; return attr->mode;`

False-positive guards:
- Do not flag if different attributes genuinely need different visibility policy
  under the same flag (e.g. some should remain visible while others are hidden),
  requiring per-attribute logic.
- Do not apply outside coresight-sysfs.c without additional confirming evidence.
- One reviewer data point only; treat as draft.

Confidence: low
Last updated: 2026-05-26

### MEM-0053: Static platform-quirk table not preferred when a runtime kernel API can detect the condition

Status: draft
Scope: general
Triggers:
- A driver introduces a static {hw_rev, DT compatible} or similar hardcoded
  platform-quirk table to enable or disable a feature (e.g. threaded NAPI)
- The underlying condition driving the quirk (e.g. lack of IRQ affinity support)
  is detectable at runtime via an existing kernel API (e.g. irq_can_set_affinity())

Maintainer evidence:
- Manivannan Sadhasivam (NACK) on [PATCH ath-next] wifi: ath12k: enable threaded
  NAPI on QCS6490 RB3gen2 (linux-wireless, 2026-04-29): "This is not a scalable
  solution. You should enable threaded NAPI when the underlying IRQ(s) does not
  support affinity management (irq_can_set_affinity() returns false), irrespective
  of the platform used."
- Krishna Chaitanya Chundru on the same patch: "why can't we dynamically check if
  affinity is supported ... this is not limited [to] this platform alone"
- Our automated review called the static table "clean and forward-looking" and
  "the right conservative approach" — missed-by-us: patch received a NACK.

Review action:
- Flag [CONCERN] when a driver enables a feature via a static {hw_rev, DT
  compatible} platform-quirk table and a kernel runtime API exists to detect
  the same condition dynamically.
- Ask whether the available API (e.g. irq_can_set_affinity()) can be called at
  setup time to detect the condition, making the static table unnecessary and
  the feature automatically correct for any future platform with the same limitation.

False-positive guards:
- Do not flag if no kernel API exists to detect the condition at runtime and the
  quirk captures genuinely platform-specific behaviour with no observable runtime
  signal.
- Do not flag if the static table is intentionally a policy override layered on
  top of a dynamic check (i.e. the dynamic check still runs first).
- Do not flag if the maintainer has explicitly accepted the static-table approach
  for that subsystem.

Confidence: low
Last updated: 2026-05-26

### MEM-0056: Multi-variant DRM panel driver -- per-variant supply code is dispatch-table gated; -ENODEV false-positive guard

Status: draft
Scope: subsystem:drm/panel file-pattern:drivers/gpu/drm/panel/
Triggers:
- A multi-panel driver (e.g. panel-ilitek-ili9881c.c) adds
  devm_regulator_get_optional() for a specific new panel variant
- A review flags that missing -ENODEV handling will break all existing panel
  DT nodes that omit the new supply
- The new regulator acquisition code lives inside a per-variant init or
  enable callback that is only invoked when the DT compatible matches the
  new panel variant

Maintainer evidence:
- Linus Walleij gave Reviewed-by on patch 2/4 of Waveshare DSI TOUCH series
  (drm/panel: ilitek-ili9881c: support Waveshare 7.0" DSI panel,
  20260418-waveshare-dsi-touch-v4-2-b249f3e702bd@oss.qualcomm.com, 2026-04-24)
  without flagging -ENODEV handling; patch was applied to drm-misc-next. Our
  automated review raised [BUG] for unhandled -ENODEV; accepted without that
  fix. One data point -- likely false-positive due to variant-dispatch protection.

Review action:
- Before raising [BUG] for unhandled devm_regulator_get_optional() -ENODEV
  in a multi-variant panel driver, verify the code path: if the supply
  acquisition is inside a per-variant callback (e.g. panel_desc->init_sequence,
  panel_desc->prepare) only called after matching the new compatible, existing
  panels that omit the supply never reach that code.
- Only raise as [BUG] when the devm_regulator_get_optional() call is on a
  shared code path (e.g. common probe() body) reachable by all variant DT nodes
  regardless of compatible.

False-positive guards:
- Do not suppress [BUG] when the call is on the common probe() path executed
  before any per-variant dispatch.
- Do not apply to single-panel drivers with no variant dispatch table.
- One data point only; treat as draft.

Confidence: low
Last updated: 2026-05-26

### MEM-0057: Timed busy-wait under spin_lock_irqsave() — verify timeout < minimum hardware watchdog deadline

Status: draft
Scope: general
Triggers:
- A patch adds a deadline or timeout to a busy-wait loop that runs under
  spin_lock_irqsave() (IRQs disabled) to fix a hardware watchdog bite
- The proposed timeout duration is not compared against the minimum watchdog
  timeout on all supported platforms

Maintainer evidence:
- Patchwise AI reviewer on "virtio_console: bound __send_to_port() spin loop
  to prevent watchdog bite" (20260506-add_timeout_to___send_to_port-v4-1@
  oss.qualcomm.com, 2026-05-07): "Spinning for 200ms with IRQs disabled is
  still long enough to trigger watchdog bites on platforms with sub-200ms
  watchdog timeouts, which is the exact problem this patch claims to fix."
  Our automated review verified ownership and NMI-safety of the loop but
  gave READY TO APPLY without checking whether 200ms fits within all
  platform WD timeouts. Missed-by-us.

Review action:
- Flag [CONCERN] when a patch introduces a timed spin loop under
  spin_lock_irqsave() to prevent a watchdog bite and the commit body or
  code comments do not justify that the timeout is shorter than the minimum
  hardware watchdog timeout on all supported platforms.
- Ask: what is the minimum watchdog timeout on supported platforms, and is
  the chosen duration guaranteed to be shorter?
- If no justification exists, suggest adding a comment or reducing the
  timeout to a value clearly shorter than the minimum known WD deadline.

False-positive guards:
- Do not flag if the commit body explicitly derives the timeout from the
  minimum watchdog timeout on all supported platforms.
- Do not flag if the loop can schedule out (i.e., not under IRQs-disabled
  context).
- Do not flag timeouts of a few microseconds that cannot plausibly exceed
  any hardware watchdog deadline.

Confidence: low
Last updated: 2026-05-26

### MEM-0058: Write/send callback returning 0 instead of negative errno on submit failure silently drops data

Status: draft
Scope: general
Triggers:
- A write-like function or send callback (e.g., hvc put_chars, char-device
  write op) is modified to handle a new error path (e.g.,
  virtqueue_add_outbuf() or similar queue-submission failure)
- On that new or modified error path the function returns 0 (e.g., because
  an in_count/byte-count variable is zero-initialised and returned via goto)
  rather than a negative errno
- The caller interprets a 0 return as "wrote 0 bytes" and may silently
  discard the data or enter a busy-retry loop

Maintainer evidence:
- Patchwise AI reviewer on "virtio_console: bound __send_to_port() spin loop
  to prevent watchdog bite" (20260506-add_timeout_to___send_to_port-v4-1@
  oss.qualcomm.com, 2026-05-07): "When virtqueue_add_outbuf() fails, in_count
  is set to 0 and the function returns 0 via goto done ... put_chars() returns
  0 to its caller instead of a negative error code like -ENOSPC, silently
  dropping the data without indicating an error." Our automated review
  analysed ownership semantics across all three buffer-lifetime paths and
  gave READY TO APPLY without checking the return-value contract. Missed-by-us.

Review action:
- Flag [MINOR] when a write/send callback returns 0 on a failure path where
  a negative errno (e.g., -ENOSPC, -ENOMEM) would let the caller propagate
  or log the error.
- Verify the caller contract: if the caller retries on 0, returning 0 on
  error may cause a busy loop; if it treats 0 as success, data is silently
  dropped.
- Suggest returning the appropriate negative errno when the underlying
  submit failed rather than 0.

False-positive guards:
- Do not flag if the callback API contract explicitly defines 0 as the only
  "no data written" signal and negative return is not part of that contract.
- Do not flag pre-existing behavior unchanged by the patch; only flag new
  or modified error paths introduced by the patch under review.
- Use [MINOR], not [BUG], unless silent drop causes visible data corruption
  or an unrecoverable error state.

Confidence: low
Last updated: 2026-05-26

### MEM-0059: Qcom TLMM pinctrl — `.ngpios` must count GPIO-only pins; IPCAT SDC confusion

Status: draft
Scope: subsystem:pinctrl/qcom file-pattern:drivers/pinctrl/qcom/pinctrl-*.c
Triggers:
- A new Qcom TLMM pinctrl driver sets `.ngpios` in `msm_pinctrl_soc_data` to a
  value that may or may not include SDC special pins
- IPCAT documentation lists SDC functions under GPIO numbers even when the SDC
  control registers live in a separate address block (e.g. 0x5ac000 vs the TLMM
  GPIO range 0x500000–0x5a1000)
- The commit body does not clearly separate GPIO-capable pins from SDC special pins

Maintainer evidence:
- Konrad Dybcio questioned `.ngpios = 166` on "pinctrl: qcom: Add Shikra pinctrl
  driver" (20260421-shikra-pinctrl-v2, linux-arm-msm 2026-04-22). After discussion,
  author confirmed: GPIO0–165 = 166 GPIO-capable pins (ngpios=166 is correct); SDC1
  pins at indices 166–169 and SDC2 pins at 170–172 are separate pin groups beyond
  the GPIO range. Cross-checked with Agatti (same model). Konrad accepted: "Right, OK."
  Missed-by-us: our automated review never analyzed the ngpios value.

Review action:
- Verify `.ngpios` equals the count of GPIO-capable pins (gpio0..gpio<N-1>) only.
  SDC special pins (sdc1_*, sdc2_*) must appear as named pin groups at indices
  ≥ ngpios; they must NOT be counted in ngpios even if IPCAT lists SDC functions
  alongside GPIO numbers.
- Cross-check: if the TLMM HPG uses wording like "Non-GPIOs like SDC2", that is a
  signal that SDC pins belong outside the GPIO range.
- When SDC registers live at a separate base address from the TLMM GPIO block, treat
  those pins as non-GPIO regardless of how IPCAT numbers them.
- Reference a same-family SoC driver (e.g. Agatti, Glymur) to confirm the expected
  GPIO count and SDC pin indices.

False-positive guards:
- Do not flag if the SoC's SDC pins genuinely share the TLMM GPIO register space
  and function as GPIOs in the mux (no separate SDC register block).
- Do not flag ngpios when the driver already correctly excludes SDC pins from the
  GPIO count and lists them as separate pin groups at indices ≥ ngpios.

Confidence: low
Last updated: 2026-05-26

### MEM-0062: pinctrl-spmi-gpio — cast spacing in of_device_id table follows pre-existing style; [NIT] not [MINOR]

Status: draft
Scope: file-pattern:drivers/pinctrl/qcom/pinctrl-spmi-gpio.c
Triggers:
- A patch adds a new of_device_id entry to pinctrl-spmi-gpio.c using
  `.data = (void *) <n>` (space between cast and operand)
- checkpatch flags CHECK:SPACING for the space after the cast
- All pre-existing entries in the same pmic_gpio_of_match[] table already use
  the same spaced form

Maintainer evidence:
- Konrad Dybcio gave Reviewed-by on "pinctrl: qcom: spmi-gpio: Add PMG1110 GPIO
  support" (linux-arm-msm, 2026-05-21) without requesting the cast-spacing fix.
  checkpatch CHECK:SPACING flagged `.data = (void *) 4`; all pre-existing entries
  in pmic_gpio_of_match[] already used the same spaced form. One data point.

Review action:
- Flag [NIT] (not [MINOR]) when a new of_device_id entry in pinctrl-spmi-gpio.c
  uses `.data = (void *) <n>` where the spaced form is consistent with all
  pre-existing sibling entries in the same table.
- Note the pre-existing inconsistency in the review text; do not block the patch
  on this style point.

False-positive guards:
- Do not downgrade to [NIT] if the file's table has a mix of spaced and non-spaced
  forms — in that case the new entry is genuinely introducing inconsistency.
- Do not generalise to other files or drivers without additional confirming evidence
  from their respective maintainers.
- One data point only; treat as draft.

Confidence: low
Last updated: 2026-05-26

### MEM-0063: Driver probe must not overwrite a global module_param to encode per-device state

Status: draft
Scope: general
Triggers:
- A probe (or per-device init) function writes a new value to a global
  `module_param` variable based on the type or access method of the device
  being probed (e.g. resolving PARAM_PM_SAVE_FIRMWARE to PARAM_PM_SAVE_SELF_HOSTED)
- The write encodes per-device state in a global singleton, so a subsequent
  probe of a different device type observes the mutated value and skips its
  own detection logic (e.g. a second ETM4 device skips DT firmware check after
  an ETE already set pm_save_enable = PARAM_PM_SAVE_SELF_HOSTED)
- A user-supplied module parameter value is silently overridden as a side-effect

Maintainer evidence:
- Suzuki K Poulose (ARM/Coresight maintainer) on patch 1/2 of
  20260428-james-cs-ete-pm_save_enable-v1-0-c7a90ca6f43b@linaro.org
  (coresight: ete: Always save state on power down, 2026-04-28): questioned
  the ETE-specific write to pm_save_enable; suggested keying the decision on
  sysreg access mode instead of device type, implying the unconditional global
  write was the wrong approach.
- Leo Yan (ARM/Coresight reviewer) on the same series: requested removing the
  global write-back: do not change pm_save_enable inside probe; instead, read
  it as a global parameter at probe time and store the per-device PM mode in
  drvdata. Both maintainers confirmed the problem independently; our automated
  review raised [CONCERN] and the maintainers validated it (confirmed).

Review action:
- Flag [CONCERN] when a probe or per-device init function writes to a
  `module_param` variable to record the outcome of a per-device decision.
- The module parameter should be treated as read-only after module load.
  Per-device state should be computed from the parameter at probe time and
  stored in the device drvdata (e.g. `drvdata->pm_save`, `drvdata->save_state`).
- On mixed-device systems, the write in the first probe permanently changes the
  value seen by all subsequent probes, silently overriding user settings and
  breaking per-device DT/ACPI detection logic.

False-positive guards:
- Do not flag one-time `module_init()` writes that set the parameter before any
  device probes and are never written again at probe time.
- Do not flag if the driver guarantees only one device of that type ever probes
  (e.g. a single-instance SoC component with no mixed-device scenario possible).
- Do not flag read-only uses of module_param values inside probe -- reading and
  storing into drvdata is the correct pattern; only writing back is the concern.

Confidence: low
Last updated: 2026-05-26

### MEM-0064: Qcom clock driver `qcom_cc_desc` — verify whether `.use_rpm` is needed

Status: draft
Scope: subsystem:clk/qcom file-pattern:drivers/clk/qcom/*.c
Triggers:
- A new Qcom clock driver (GCC, videocc, camcc, gpucc, or other MM clock controller)
  defines `struct qcom_cc_desc` without setting `.use_rpm = true`
- The commit body does not explain why RPM involvement is not required for the driver's
  dependent voltage rails (e.g. CX, MXA, MMCX, MXC)

Maintainer evidence:
- Konrad Dybcio on patch 4/5 of the Shikra RPMCC+GCC series (linux-arm-msm, 2026-04-27):
  "do we want .use_rpm = true here?" Author confirmed .use_rpm is not needed because
  Shikra CX and MXA rails are always ON when APPS is active. Our automated review never
  checked this field (missed-by-us).
- Eliza MM clock series (20260525-eliza_mm_cc_v2-v5-0-a1d125619a5a@oss.qualcomm.com,
  2026-05-25): Sashiko-bot flagged [High] that videocc-eliza.c and camcc-eliza.c omit
  `.use_rpm = true`. Dmitry Baryshkov gave Reviewed-by on both drivers without raising
  `.use_rpm`. Cover letter explicitly states: "Eliza camcc and videocc are on CX and MX
  rails and doesn't have MMCX and MXC rails dependency. Since CX and MX rails are
  already ON when APPS is active, explicit power-domain voting is not required similar
  to Milos." Bot concern was a false positive when rails are always-on. Second data point
  confirming the CX/MX always-on guard.

Review action:
- Flag [MINOR] when a new Qcom clock driver qcom_cc_desc omits .use_rpm and the commit body
  or cover letter does not justify its absence.
- Ask: are the driver's dependent voltage rails managed by RPM firmware or always ON when
  APPS is active? If RPM-managed (e.g. MMCX, MXC on flagship SoCs), .use_rpm = true is
  likely needed. If always ON (e.g. CX, MX on Milos/Eliza-class SoCs), omission is correct
  and should be stated in the commit body or cover letter.

False-positive guards:
- Do not flag if the commit body or cover letter explicitly states the relevant rails are
  always active when APPS is running (e.g. "CX and MX rails are already ON when APPS is
  active, explicit power-domain voting is not required").
- Do not flag when reviewing older established drivers with no qcom_cc_desc changes.
- Do not flag videocc/camcc/gpucc on SoCs confirmed to use CX/MX-only rails without MMCX;
  Sashiko-bot raises this as [High] but Dmitry Baryshkov does not flag it for such SoCs.

Confidence: low
Last updated: 2026-05-30

### MEM-0065: Qcom SMD-RPM --- SNOC bus clocks may serve audio NPA nodes despite no icc consumers

Status: draft
Scope: subsystem:clk/qcom file-pattern:drivers/clk/qcom/clk-smd-rpm.c
Triggers:
- A new Qcom RPMCC clock table registers RPM_SMD_SNOC_PERIPH_CLK / RPM_SMD_SNOC_PERIPH_A_CLK
  or RPM_SMD_SNOC_LPASS_CLK / RPM_SMD_SNOC_LPASS_A_CLK pairs (or equivalent SNOC bus clock
  pairs) and none of these appear in the driver icc_clks[] array or as explicit consumers
- The commit body does not explain who votes for these clocks at runtime

Maintainer evidence:
- Konrad Dybcio on patch 3/5 of the Shikra SMD-RPM series (linux-arm-msm, 2026-04-27):
  "these two pairs represent bus clocks, but are not used by anything (not even the icc
  infra)" ... Author replied: "These clocks are part of the NPA nodes ... required for
  audio functionality and will be voted based on the respective use-case requirements."
  Our automated review gave PASS without flagging the unused-looking clock pairs (missed-by-us).

Review action:
- Do not automatically flag SNOC_PERIPH or SNOC_LPASS clock pairs as dead code when they
  lack explicit icc consumers.
- Add an [INFO] note (not [MINOR]) asking the author to confirm whether these clocks serve
  audio NPA nodes, and if so to add a brief comment in the source or commit body explaining
  the NPA voting usage. If the commit body already explains the NPA usage, no note is needed.

False-positive guards:
- Do not raise above [INFO]; these clocks are NPA-voted from the audio subsystem and are
  functionally necessary even when not referenced by icc.
- Do not flag established SMD-RPM tables (agatti, qcm2290, etc.) that carry the same SNOC
  pairs without icc entries; the pattern is consistent across the SoC family.
- One data point; treat as draft.

Confidence: low
Last updated: 2026-05-26

### MEM-0066: Qcom GCC reset tables --- check for missing secondary USB PHY BCR

Status: draft
Scope: subsystem:clk/qcom file-pattern:include/dt-bindings/clock/qcom,*-gcc.h
Triggers:
- A new Qcom GCC reset-ID header defines GCC_QUSB2PHY_PRIM_BCR (primary HS USB PHY block
  reset) but omits GCC_QUSB2PHY_SEC_BCR (secondary HS USB PHY BCR)
- The SoC potentially supports dual USB PHY instances

Maintainer evidence:
- Krishna Kurapati PSSNV on patch 2/5 of the Shikra GCC dt-bindings series
  (linux-arm-msm, 2026-04-25): "I see BCR for the primary high speed phy but not the
  second one. Can you check and confirm the same." Author replied that secondary BCR was
  not confirmed by the USB team for upstream and was intentionally omitted. Our automated
  review never checked for paired primary/secondary BCR presence (missed-by-us).

Review action:
- Flag [NIT] when a new Qcom GCC reset header defines a primary USB PHY BCR without a
  corresponding secondary BCR, if the SoC targets a platform with potential dual USB PHY.
- Ask whether GCC_QUSB2PHY_SEC_BCR is intentionally absent, and request a brief comment in
  the header or commit body confirming the intentional omission.

False-positive guards:
- Do not flag if the commit body already explains why the secondary BCR is absent
  (e.g. "secondary USB PHY not present on this SoC").
- Do not flag if the SoC datasheet confirms a single USB2 PHY only.
- Use [NIT], not [CONCERN]; the maintainer question was informational and the omission was
  intentional pending USB hardware team confirmation on this series.
- One data point; treat as draft.

Confidence: low
Last updated: 2026-05-26

### MEM-0067: Qcom rpmhpd — identical *_rpmhpds[] array must be deduplicated; reuse existing descriptor or use DT fallback compatible

Status: draft
Scope: file-pattern:drivers/pmdomain/qcom/rpmhpd.c
Triggers:
- A patch adds a new `*_rpmhpds[]` static pointer array and matching
  `rpmhpd_desc` to `rpmhpd.c` for a new SoC
- The new array is a verbatim copy of an existing one (same set of
  RPMHPD_* constants pointing to the same global rpmhpd objects)
- The review or diff comment notes the arrays are "the same as <SoC>"
  without flagging the duplication as a concern

Maintainer evidence:
- Konrad Dybcio on patch 2/2 of the Maili RPMh power-domain series
  (linux-arm-msm, 2026-05-18): "This is the same as hawi, please reuse."
  Author proposed making `qcom,maili-rpmhpd` a DT fallback compatible for
  `qcom,hawi-rpmhpd`; Konrad agreed. The driver patch was dropped entirely.
  Our automated review noticed the arrays were identical but accepted the
  duplication without flagging it — missed-by-us.

Review action:
- Flag [MINOR] when a new `*_rpmhpds[]` array in `rpmhpd.c` is a
  verbatim copy of an existing one (same RPMHPD_* indices, same rpmhpd
  object pointers, same length).
- Suggest one of two resolutions:
  1. Reuse: point the new `rpmhpd_desc.rpmhpds` at the existing array
     and use `ARRAY_SIZE()` of that array.
  2. DT fallback: make the new SoC compatible a fallback for the reference
     SoC in both the YAML binding enum and the `of_device_id` table,
     eliminating the driver patch entirely.

False-positive guards:
- Do not flag if even one RPMHPD_* entry differs (different object, extra
  domain, or absent domain).
- Do not flag if the commit body justifies a separate array for future
  extensibility and a maintainer has acknowledged the rationale.

Confidence: low
Last updated: 2026-05-26

### MEM-0069: Negative int return from count-get function assigned to unsigned int without error check

Status: draft
Scope: general
Triggers:
- A probe or init function calls a count-get helper returning int (negative on
  error, non-negative count on success)
- The return value is assigned directly to an unsigned int or u32 field without
  first checking for a negative error code (e.g. `drv->nr = get_count(dev)`)

Maintainer evidence:
- Patchwise AI reviewer (kernel@oss.qualcomm.com, 2026-05-13) on both patches of
  "pinctrl: pinctrl-scmi: Cache pin groups, functions and their counts": flagged
  that `pmx->nr_groups = pinctrl_scmi_get_groups_count(...)` and `pmx->nr_functions
  = pinctrl_scmi_get_functions_count(...)` in scmi_pinctrl_probe() assign int returns
  directly to unsigned int fields. A negative errno wraps to a huge unsigned value;
  devm_kcalloc() then fails or allocates a giant buffer, hiding the real firmware
  error. Our automated review raised this as [MINOR] for the groups patch; the
  Patchwise reviewer confirmed the same pattern on both patches independently.

Review action:
- Flag [MINOR] when a probe assigns the return of an int-returning count function
  directly to an unsigned int or u32 field without a negative-return check.
- Suggest: assign to a local int, check for negative, then assign the validated
  non-negative value to the unsigned field on success:
  `ret = get_count(dev); if (ret < 0) return ret; drv->nr = ret;`

False-positive guards:
- Do not flag if the called function is documented to never return a negative value
  (e.g. it always returns a non-negative count with errors indicated separately).
- Do not flag if a preceding check in the same function already guarantees the
  return is non-negative before the assignment.

Confidence: low
Last updated: 2026-05-26

### MEM-0072: Unsigned int count field used as a zero-ambiguous cache-populated sentinel

Status: draft
Scope: general
Triggers:
- A driver lazy-caches a firmware or hardware count in an unsigned int field
- The "already cached" check uses `if (field)` (truthy = populated), making 0
  indistinguishable from "not yet queried"
- The firmware or hardware can legitimately return 0 as a valid empty count

Maintainer evidence:
- Patchwise AI reviewer (kernel@oss.qualcomm.com, 2026-05-13) on both patches of
  "pinctrl: pinctrl-scmi: Cache pin groups, functions and their counts": flagged
  `if (pmx->nr_groups)` and `if (pmx->nr_functions)` as zero-ambiguous sentinels.
  When firmware returns 0, the check treats the field as "not cached" and re-queries
  firmware on every call, permanently defeating the cache. Our automated review
  did not flag this pattern (missed-by-us).

Review action:
- Flag [MINOR] when an unsigned int count field is the sole cache-populated indicator
  via `if (field != 0)` and the underlying source can legitimately return 0.
- Suggest a separate boolean flag (e.g. `bool nr_groups_valid`) or a sentinel value
  the firmware/hardware cannot return (e.g. UINT_MAX) to distinguish "cached as zero"
  from "not yet populated".

False-positive guards:
- Do not flag when the subsystem or firmware protocol documents the count is always
  >= 1 (e.g. the spec guarantees at least one group must exist).
- Do not flag if a separate mechanism (pointer non-NULL, explicit bool) already
  unambiguously distinguishes "populated with 0" from "not yet populated".
- Use [MINOR], not [CONCERN]: the practical impact is repeated firmware queries,
  not corrupted data.

Confidence: low
Last updated: 2026-05-26

### MEM-0076: Qcom QMP PHY init tables — duplicate register write without explanatory comment is likely copy-paste redundancy

Status: draft
Scope: file-pattern:drivers/phy/qualcomm/phy-qcom-qmp*.c
Triggers:
- A QMP PHY init table (e.g., _serdes_tbl[], _rx_tbl[]) contains the same register
  macro written twice with different values within the same contiguous array
- No comment before the first write explains that an intermediate value is needed for
  hardware initialization sequencing

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-16) on patch 2/2
  "phy: qcom-qmp-pcie: Add support for ipq5210 PCIe phys": QSERDES_PLL_SYSCLK_EN_SEL
  appeared twice in ipq5210_gen3x1_pcie_ep_serdes_tbl (value 0x00 early, value 0x10
  last). The Patchwise reviewer stated "the first write is redundant and the second one
  will overwrite it" and recommended removing the first entry. Our automated review
  flagged the same pattern as [NIT] with "likely intentional" — too cautious; the
  Patchwise reviewer treated it as probable copy-paste redundancy requiring removal or
  an explanatory comment.

Review action:
- Flag [MINOR] (not [NIT]) when the same register macro appears twice in a QMP PHY
  init table with different values and no comment explains why an intermediate value
  is needed.
- Suggest removing the first occurrence if it appears to be a copy-paste artifact;
  or add a comment before the first write explaining the hardware sequencing requirement
  (e.g., "must be written 0 before the PLL lock sequence, then set to final value").

False-positive guards:
- Do not flag if a comment above the first write clearly explains the intermediate
  value is required for hardware initialization (e.g., "set to 0 during cal, 0x10 after").
- Do not flag separate named tables (e.g., rc_tbl vs ep_tbl) that write the same
  register — only flag within a single contiguous table array.
- One AI-reviewer data point only; treat as draft until a human maintainer confirms.

Confidence: low
Last updated: 2026-05-26

### MEM-0077: regmap_config.max_register must cover all register addresses used in the series

Status: draft
Scope: general
Triggers:
- A patch introduces a new regmap_config with a max_register value
- A later patch in the same series (or another function in the same driver) calls
  regmap_read/write/update_bits/raw_read/raw_write with a register address that
  exceeds max_register

Maintainer evidence:
- Konrad Dybcio on patch 2/5 of 20260316-pmic-glink-gio-clients-v1 (linux-arm-msm,
  2026-04-13): noted that gio_regmap_config set max_register = 0xffff, while patch
  3/5 defines GIO_USBC_UCSI_VERSION_REG = 0x20100 -- an address that exceeds the
  declared maximum. regmap rejects accesses beyond max_register at runtime with
  -EIO; our automated review did not cross-check the config limit against actual
  register addresses used elsewhere in the series (missed-by-us).

Review action:
- When a patch introduces a regmap_config with max_register, scan the entire series
  for the highest register address actually read or written in that regmap instance.
- Flag [BUG] when any used register address exceeds max_register.
- Suggest raising max_register to at least the highest used register address, or to
  the documented hardware address space limit if available.

False-positive guards:
- Do not flag if all register addresses in the series are below the stated
  max_register (no address exceeds it).
- Do not flag if max_register is explicitly set to 0 or UINT_MAX and the
  backend is documented to treat those as "unconstrained".

Confidence: low
Last updated: 2026-05-26

### MEM-0081: ath12k QMI optional TLV capability fields — no stale-value concern when phy_cap_send reruns on SERVER_ARRIVE

Status: draft
Scope: subsystem:ath12k file-pattern:drivers/net/wireless/ath/ath12k/qmi.c
Triggers:
- A patch adds an optional QMI TLV field to `ab->qmi` and populates it only when
  the firmware advertises the TLV (e.g. `if (resp.foo_valid) ab->qmi.foo = resp.foo`)
- A review concern is raised that on SERVER_EXIT -> SERVER_ARRIVE firmware recovery,
  the field retains a stale value if the new firmware omits the TLV

Maintainer evidence:
- Aaradhana Sahu <aaradhana.sahu@oss.qualcomm.com> on [PATCH ath-next v7] wifi: ath12k:
  add QMI capability negotiation for dynamic memory mode (2026-05-22): if new firmware
  does not advertise resp.dynamic_ddr_support_valid, then ab->qmi.dynamic_ddr_support will
  remain zero only and not keep old value; there is no chance of stale value during firmware
  restart -- confirming that ab->qmi capability state is reset to zero before phy_cap_send
  re-queries firmware on SERVER_ARRIVE.
- The qgenie automated review independently reached the same conclusion in its Code Logic
  Maps: phy_cap_send() is re-called before host_cap_send runs on every SERVER_ARRIVE.
  (confirmed: our analysis matched the author explanation.)
- qgenie automated review of v5 (2026-05-13) still raised [MINOR] for stale
  dynamic_ddr_support despite this entry existing in memory; the verification step
  (checking call ordering in ath12k_qmi_event_server_arrive) was skipped, producing the
  same false positive a second time. Second confirming instance of the missed-verification
  pattern.
- Patchwise AI reviewer on [PATCH ath-next v6] (2026-05-21): independently raised the
  same concern, additionally citing the case where the PHY capability request itself
  fails. The false-positive guard below covers this: ab->qmi fields are reset to zero
  before phy_cap_send on SERVER_ARRIVE, so a failed call also leaves the field at zero
  (safe default). Third confirming instance; the false-positive suppression continues
  to apply.

Review action:
- Do NOT raise a stale-value concern for an optional QMI TLV field in `ab->qmi` when
  `ath12k_qmi_phy_cap_send()` is called on every SERVER_ARRIVE before any consumer
  of that field (e.g. `ath12k_qmi_host_cap_send()`).
- Mandatory: verify call ordering in `ath12k_qmi_event_server_arrive()` before raising
  this concern. If phy_cap_send always precedes host_cap_send, the field is freshly
  populated (or reset to zero) before consumption -- no stale-value concern applies.

False-positive guards:
- Still raise stale-value concern if the field is populated by a function NOT called on
  SERVER_ARRIVE, meaning it cannot be refreshed before its consumer runs.
- Still raise stale-value concern if code inspection shows ab->qmi fields are NOT reset
  to zero before phy_cap_send on SERVER_ARRIVE (e.g. a patch removes the cleanup code).

Confidence: low
Last updated: 2026-05-26

### MEM-0082: `pci_irq_vector()` return value — use `>= 0` as error check, not `> 0`

Status: draft
Scope: general
Triggers:
- A function calls `pci_irq_vector()` (or a wrapper such as `ath12k_pci_get_msi_irq()`)
  and checks the return value with `if (irq > 0)` rather than `if (irq >= 0)`

Maintainer evidence:
- Patchwise AI reviewer on [PATCH v4 2/2] wifi: ath12k: enable threaded NAPI when DP IRQ
  affinity is unavailable (kernel@oss.qualcomm.com, 2026-05-12): flagged `if (irq > 0)`.
  Author acknowledged: MSI/MSI-X `pci_irq_vector()` never returns IRQ 0 (msi_get_virq
  maps 0 to -EINVAL), so `> 0` is technically correct here, but agreed to update to
  `>= 0` in the next version "for general error handling." One AI-reviewer plus author-
  acknowledgment data point.

Review action:
- Flag [NIT] when `pci_irq_vector()` (or a wrapper returning the same int) is checked
  with `> 0` instead of `>= 0`.
- Note that for MSI/MSI-X the practical difference is nil (IRQ 0 is never returned for
  MSI), but `>= 0` is the conventional form expected for Linux IRQ number return values
  and avoids reviewer questions.

False-positive guards:
- Do not flag if the function is documented to never return 0 on success and the commit
  body explicitly justifies `> 0` for that API contract.
- Use [NIT], not [MINOR]: the practical risk is zero for MSI; this is a convention concern.
- Do not apply to non-PCI IRQ number sources without independent confirming evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0083: ath12k series — missing KITE branch tree tag blocks all automated CI testing

Status: draft
Scope: subsystem:ath12k
Triggers:
- An ath12k patch series is submitted through the Qualcomm KITE CI pipeline (replies from
  ath_bot_tesseract or kernel@oss.qualcomm.com automated systems)
- The series cover letter or series subject header does not include a branch tree tag
  identifying the target tree (e.g., `ath-next`)

Maintainer evidence:
- ath_bot_tesseract (Qualcomm KITE CI, kernel@oss.qualcomm.com, 2026-05-12) on
  [PATCH v4 0/2] genirq/ath12k: fallback to threaded NAPI when IRQ affinity is
  unavailable: reported BRANCH_TREE_TAG_ERROR and stopped all further automated tests;
  requested "Add apt tag and re-spin a new version please."
  Our automated review did not flag the missing branch tag (missed-by-us).
- ath_bot_tesseract (Qualcomm KITE CI, kernel@oss.qualcomm.com, 2026-05-14) on
  [PATCH v5 0/2] same series: BRANCH_TREE_TAG_ERROR again — the branch tag was not
  added in the v5 re-spin either. Second consecutive version of the same series
  blocked. Two independent bot reports on the same series pair.

Review action:
- When the review context indicates submission through Qualcomm KITE (ath_bot replies,
  kernel@oss.qualcomm.com thread), check whether the series cover letter includes a
  branch tree tag (e.g., `ath-next`).
- Flag [MINOR] if absent; the missing tag blocks all KITE automated testing and forces
  a re-spin.

False-positive guards:
- Do not flag if the submitter has confirmed the series bypasses KITE and goes directly
  upstream.
- Do not apply to non-ath12k wireless series without confirming the same KITE branch-tag
  requirement applies to that subsystem.
- Two data points from the same series (v4, v5); treat as draft until seen in a separate
  series.

Confidence: low
Last updated: 2026-05-26

### MEM-0084: Tracepoint placed after a multi-exit function — check whether early-return paths bypass it

Status: draft
Scope: general
Triggers:
- A patch adds a trace_*_done() or similar completion tracepoint immediately after a
  call to a function that has early-return paths (e.g. via a labeled error path, a
  goto, or a conditional early return inside a loop)
- The early-return paths bypass the tracepoint entirely so it is never called on error
  or non-standard exit paths

Maintainer evidence:
- Patchwise AI reviewer (quic_kernel@qualcomm.com, 2026-05-06) on patch 2/2
  "firmware: qcom: scm: instrument SMC call path with tracepoints": noted that
  __scm_smc_do() returns non-zero only via an early return inside its loop (from
  __scm_smc_do_quirk_handle_waitq), which bypasses trace_scm_smc_done(); as a result
  ret at the trace site is always 0 and error outcomes are never traced. Our
  automated review gave READY TO APPLY and missed this (missed-by-us).

Review action:
- When a patch adds a completion tracepoint (trace_*_done, trace_*_exit, etc.) after
  a function call, inspect that function for early returns or gotos that skip the
  trace site; if present, the tracepoint silently misses error events.
- Flag [MINOR] when error or non-standard exits are never traced and the commit body
  does not document the intentional scope limitation.
- Suggest moving the tracepoint inside the callee to cover all exits, placing trace
  calls on each return path, or adding a comment explaining the intentional scope.

False-positive guards:
- Do not flag if the commit body or a code comment explicitly states the tracepoint
  intentionally covers only the clean-exit path.
- Do not flag if the early-return path is an initialization failure already covered
  by a separate tracepoint earlier in the call graph.
- One AI-reviewer data point only; treat as draft.

Confidence: low
Last updated: 2026-05-26

### MEM-0086: DRM_BRIDGE_OP_HDMI_AUDIO requires hdmi_write_audio_infoframe and hdmi_clear_audio_infoframe callbacks

Status: draft
Scope: subsystem:drm/bridge file-pattern:drivers/gpu/drm/bridge/
Triggers:
- A DRM bridge driver sets `DRM_BRIDGE_OP_HDMI_AUDIO` in `bridge->ops`
- The driver's `drm_bridge_funcs` does not implement both `hdmi_write_audio_infoframe`
  and `hdmi_clear_audio_infoframe` callbacks

Maintainer evidence:
- Patchwise AI review (2026-05-13) on "drm: bridge: add support for lontium LT9611UXD
  bridge": `DRM_BRIDGE_OP_HDMI_AUDIO` set in bridge->ops but neither
  `hdmi_clear_audio_infoframe` nor `hdmi_write_audio_infoframe` was present in
  `drm_bridge_funcs`. Our automated review missed this (missed-by-us).

Review action:
- Flag [BUG] when `DRM_BRIDGE_OP_HDMI_AUDIO` is declared in `bridge->ops` without
  matching `hdmi_write_audio_infoframe` and `hdmi_clear_audio_infoframe` implementations
  in `drm_bridge_funcs`.
- Whenever a bridge sets any `DRM_BRIDGE_OP_*` bit, cross-check that the corresponding
  callback field in `drm_bridge_funcs` is non-NULL.

False-positive guards:
- Do not flag if both audio infoframe callbacks are present in `drm_bridge_funcs`.
- Do not apply to drivers using `DRM_BRIDGE_OP_HDMI` (without the `_AUDIO` suffix)
  where audio infoframe callbacks are not required.

Confidence: low
Last updated: 2026-05-26

### MEM-0087: Holding a driver mutex across request_firmware() or a long msleep() blocks all protected operations

Status: draft
Scope: general file-pattern:drivers/
Triggers:
- A driver acquires a mutex that also guards real-time operations (IRQ thread
  handlers, connect detect, EDID reads) and, while still holding that mutex,
  calls `request_firmware()` or `msleep()` with a delay >= 500 ms
- Example pattern: `mutex_lock(&drv->ocm_lock); ... msleep(3000);
  request_firmware(&fw, ...);`

Maintainer evidence:
- Patchwise AI review (2026-05-13) on "drm: bridge: add support for lontium
  LT9611UXD bridge": `lt9611uxd_lock()` (acquires `ocm_lock`) was held across
  `lt9611uxd_prepare_firmware_data()`, which calls `msleep(3000)` then
  `request_firmware()`. The same mutex protects the HPD IRQ thread and EDID
  reads, so all concurrent bridge operations were blocked for several seconds
  during firmware upgrade. Our automated review missed this (missed-by-us).

Review action:
- Flag [CONCERN] when a mutex protecting time-sensitive paths (IRQ handlers,
  detect, EDID reads) is held while calling `request_firmware()` or
  `msleep()`/`usleep_range()` with total delay >= 500 ms.
- Suggest releasing the lock before the slow operation, performing it unlocked,
  then re-acquiring only for the register writes that follow.

False-positive guards:
- Do not flag if the mutex is not also held by any IRQ-driven or
  latency-sensitive path -- a dedicated firmware-load lock held only during
  probe and sysfs writes is acceptable.
- Do not flag short settling sleeps (< 500 ms) that cannot be avoided between
  register writes within a hardware initialization sequence.
- Do not flag if a separate dedicated lock (distinct from the IRQ/register-access
  lock) gates the firmware-load path.

Confidence: low
Last updated: 2026-05-26

### MEM-0088: i2c_device_id table must not use DT-style "vendor,device" vendor prefix

Status: draft
Scope: general file-pattern:drivers/
Triggers:
- A new driver's `i2c_device_id[]` table entry uses a name in the form
  `"vendor,device"` (e.g. `"lontium,lt9611uxd"`) -- a DT-style compatible string
  with a vendor prefix and comma separator
- The `i2c_device_id` table is intended for non-DT I2C board-info matching, not
  for OF/DT matching

Maintainer evidence:
- Patchwise AI review (2026-05-13) on "drm: bridge: add support for lontium
  LT9611UXD bridge": `i2c_device_id` entry named `"lontium,lt9611uxd"` instead
  of `"lt9611uxd"`. Vendor prefixes belong in `of_match_table` / `compatible`
  strings only; `i2c_device_id.name` matching does not use or expect them. Our
  automated review missed this (missed-by-us).

Review action:
- Flag [MINOR] when an `i2c_device_id[]` entry name contains a comma-separated
  vendor prefix (e.g. `"vendor,device"`).
- Suggest trimming to just the chip name (e.g. `"lt9611uxd"`), and confirm the
  `of_match_table` entry retains the correct `"vendor,device"` form.

False-positive guards:
- Do not flag `of_match_table` / `MODULE_DEVICE_TABLE(of, ...)` entries -- those
  correctly use `"vendor,device"` format.
- Do not flag if a human subsystem maintainer has explicitly accepted the
  vendor-prefix form in `i2c_device_id` for this driver.

Confidence: low
Last updated: 2026-05-26

### MEM-0090: ARM/Coresight — per-CPU sticky failure flags must be cleared on device unregister and module removal

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/
Triggers:
- A patch introduces a per-CPU boolean flag (e.g., `DEFINE_PER_CPU(bool, ...)`)
  that is set permanently (never cleared) when a runtime error occurs during
  device operation (e.g., PM restore failure)
- The driver or module has a teardown path (device unregister, module removal)
  that does not clear the flag

Maintainer evidence:
- Suzuki K Poulose on patch 23/28 of
  20260511-arm_coresight_path_power_management_improvement-v12 (coresight-next,
  2026-05-15): "We have to reset this when the ETM4x module is taken off or the
  etmN device is unregistered?" — flagging that `percpu_pm_failed` is set
  permanently on PM restore failure but has no reset in the ETM unregister or
  module-removal path, leaving stale state after module reload. Our automated
  review flagged NOTIFY_BAD semantics and discarded return values on this patch
  but did not flag the missing teardown reset (missed-by-us).

Review action:
- Flag [CONCERN] when a patch introduces a per-CPU "permanently failed" flag
  (a flag that is set to `true` and never cleared within the hot path) and the
  driver teardown path does not contain a matching clear/reset for that flag.
- Suggest adding the clear in the device unregister function and (if applicable)
  the module exit / driver remove callback so that a module reload or device
  re-registration starts with a clean state.

False-positive guards:
- Do not flag per-CPU flags that are cleared at natural operation boundaries
  (e.g., cleared on every CPU_PM_ENTER attempt).
- Do not flag if the teardown path already contains a matching
  `this_cpu_write(flag, false)` or `per_cpu(flag, cpu) = false`.
- Do not apply outside per-CPU or per-device "latch on failure" patterns;
  a normal error return variable does not trigger this entry.

Confidence: low
Last updated: 2026-05-26

### MEM-0091: ARM/Coresight — question new `coresight_device` struct fields applicable only to a device subtype

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/
Triggers:
- A patch adds a new field to `struct coresight_device` (the common device
  descriptor shared by all CoreSight device types)
- The field is only meaningful for a subset of device types (e.g., only for
  non-percpu sources), and the patch guards its use with a type-check such as
  `if (!coresight_is_percpu_source(csdev))` inside generic core helpers
- No per-type substructure or driver-private storage is used

Maintainer evidence:
- Suzuki K Poulose on patch 19/28 of
  20260511-arm_coresight_path_power_management_improvement-v12 (coresight-next,
  2026-05-15): "Do we need to special case this for non-percpu sources? We could
  always let the driver save/clear the path leaving the core out of it. We can
  fix it separately from this series in a follow up patch." — questioning the
  addition of `csdev->path` (used only for non-percpu sources) to the common
  `coresight_device` struct and the associated `coresight_is_percpu_source()`
  guard in core enable/disable functions. Our automated review had no finding on
  this design concern (missed-by-us).

Review action:
- Flag [CONCERN] when a new `coresight_device` field is guarded by a device-type
  predicate inside generic core helpers, rather than being managed by the
  type-specific driver or ops callbacks.
- Ask whether the field and its management should instead live in the driver
  layer (e.g., in source_ops callbacks or a driver-private struct) so the common
  core path requires no type check.
- Note: if the field is genuinely needed for PM notifier atomicity across types,
  document why the driver layer cannot manage it — a clear justification satisfies
  this concern.

False-positive guards:
- Do not flag fields that are genuinely common to all device types (e.g., `mode`,
  `refcnt`, `cpu`).
- Do not flag type-check guards that are already present in the pre-existing code
  for unrelated reasons; flag only new guards introduced by the current patch.
- Treat as [CONCERN] only if the type check is inside a generic core function;
  do not flag per-type driver files that naturally reference their own type.

Confidence: low
Last updated: 2026-05-26

### MEM-0099: Regulator driver --- `n_voltages` must equal `max_sel + 1`, not voltage-range / step-size + 1

Status: draft
Scope: subsystem:regulator
Triggers:
- A regulator driver defines `n_voltages` by computing
  (max_voltage - min_voltage) / step_size + 1
- The driver also has a non-zero `min_sel` (lowest hardware selector is not 0)
  — meaning the framework maps selectors 0..n_voltages-1 but the hardware only
  accepts selectors min_sel..max_sel
- Custom `get_voltage_sel` / `set_voltage_sel` ops are present alongside the
  `n_voltages` descriptor field

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-18) on patch 2/2
  "regulator: mp8899: Add MPS MP8899 PMIC Regulator driver": n_voltages=3296 was
  derived from the voltage range (2.0475V-0.4V)/0.5mV + 1, but max_sel=4095 means
  n_voltages must be 4096 (max_sel + 1) so the framework can reach selectors
  3296..4095. Selectors in that range were silently unreachable, cutting off the
  upper portion of the voltage range. Our automated review flagged the comment
  formula as [MINOR] but did not catch that the value itself was a correctness bug
  (missed-by-us, severity wrong).
- Similarly for the 1mV step range: n_voltages=3201 was used instead of 3601
  (max_sel=3600, so correct n_voltages = max_sel + 1 = 3601).

Review action:
- Flag [BUG] when regulator_desc.n_voltages is computed from
  (max_V - min_V) / step + 1 (voltage arithmetic) rather than max_sel + 1
  (selector arithmetic), and the driver has a non-zero min_sel.
- The correct formula is always: n_voltages = max_sel + 1.
  The framework iterates selectors 0..n_voltages-1 and any selector above
  n_voltages-1 is unreachable regardless of what the hardware supports.
- If a comment near n_voltages shows the formula, verify it matches
  max_sel - min_sel + 1 (selector count within the valid range) rather than
  the voltage difference; then also check n_voltages = max_sel + 1 separately.

False-positive guards:
- Do not flag when min_sel = 0 (selector range starts at 0); in that case
  voltage arithmetic and selector arithmetic give the same result.
- Do not flag if the driver uses the linear_ranges / linear_range_table helpers
  which compute n_voltages from selector count automatically.
- Do not apply to drivers that use the regmap-based .vsel_reg path exclusively
  (no custom get/set_voltage_sel ops), since the framework handles the mapping.

Confidence: low
Last updated: 2026-05-26

### MEM-0100: Regulator driver --- `active_discharge_on` must be set when `active_discharge_reg` and `active_discharge_mask` are used

Status: draft
Scope: subsystem:regulator
Triggers:
- A regulator_desc macro or struct initializer sets `active_discharge_reg` and
  `active_discharge_mask` to non-zero values
- `active_discharge_on` is absent from the initializer (defaults to 0)

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-18) on patch 2/2
  "regulator: mp8899: Add MPS MP8899 PMIC Regulator driver": pointed out that
  `regulator_set_active_discharge_regmap()` writes `desc->active_discharge_on`
  as the bitmask for the "enabled" state. With `active_discharge_on = 0`
  (the default), enabling and disabling active discharge both write 0 to the
  register, making the two operations indistinguishable. Our automated review
  did not flag the missing field (missed-by-us).

Review action:
- Flag [BUG] when `active_discharge_reg` and `active_discharge_mask` are both
  set in a regulator_desc but `active_discharge_on` is absent or zero.
- Suggest adding the correct bitmask: the bit(s) in `active_discharge_mask`
  that correspond to the "enabled" state of the active discharge circuit.

False-positive guards:
- Do not flag if `active_discharge_on` is explicitly set to a non-zero value.
- Do not flag if the driver uses custom `ops->set_active_discharge` rather than
  the regmap helper; in that case the descriptor fields are unused.
- Do not flag when `active_discharge_reg` is 0/absent (feature not supported by
  this regulator).

Confidence: low
Last updated: 2026-05-26

### MEM-0104: Firmware protocol response -- negative `int` errno assigned to `u32` status field silently corrupts the error code

Status: draft
Scope: general
Triggers:
- A driver writes an error code from a kernel API (e.g. `regulator_set_voltage()`,
  `mbox_send_message()`) back to a shared-memory firmware protocol response field
- The response field type is `u32` (or other unsigned integer type)
- The assignment is `response->status = ret;` where `ret` is a negative `int` errno

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-18) on "soc: qcom: Add CDSP power
  management driver": `smem->response.status = ret;` where `ret` is a negative errno and
  `status` is `u32`. Assigning -EINVAL (0xFFFFFFFB as u32) produces a large positive
  integer the NSP Q6 firmware will not recognise as an error. Our automated review missed
  this type mismatch entirely (missed-by-us).

Review action:
- Flag [BUG] when a negative `int` errno is directly assigned to a `u32` (or `__u32`,
  `uint32_t`) firmware response or status field without an explicit cast or encode step.
- The firmware will receive a large positive value (e.g. 0xFFFFFFFB for -EINVAL) rather
  than a negative error code, silently masking the failure from the remote processor.
- Suggest either: (a) changing the field type to `s32`/`int` if the firmware protocol
  supports negative values, or (b) mapping kernel errnos to a firmware-defined positive
  error code before writing.

False-positive guards:
- Do not flag if the field type is signed (`s32`, `int`, `int32_t`, `__s32`).
- Do not flag if the assignment is guarded by a check preventing negative values from
  reaching it (e.g. `if (ret < 0) ret = FIRMWARE_ERR_GENERIC;`).
- Do not flag if the firmware protocol explicitly reinterprets the u32 as a two's-complement
  signed value and is documented to do so.

Confidence: low
Last updated: 2026-05-26

### MEM-0105: Virtual regulator `.disable` op must call `regulator_disable()` unconditionally

Status: draft
Scope: subsystem:regulator
Triggers:
- A virtual or pass-through regulator driver implements the `.disable` regulator_ops
  callback
- The `.disable` implementation guards the underlying `regulator_disable()` call with an
  `is_enabled()` check (e.g. `if (cdsp_virt_reg_is_enabled(rdev)) return regulator_disable(reg);`)

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-18) on "soc: qcom: Add CDSP power
  management driver": `cdsp_virt_reg_disable()` called `regulator_disable()` only when
  `is_enabled()` returned true. The regulator framework already manages the enable refcount
  and only calls `.disable` when the consumer refcount reaches zero; the extra guard breaks
  the enable/disable balance on the underlying consumer handle and can leave it permanently
  enabled. Our automated review missed this framework contract violation (missed-by-us).

Review action:
- Flag [BUG] when a regulator `.disable` callback guards `regulator_disable()` with any
  `is_enabled()` or self-managed refcount check.
- The framework guarantees `.disable` is called only when the consumer's own enable
  refcount reaches zero; adding a redundant guard breaks the underlying consumer balance.
- The correct unconditional form is simply: `return regulator_disable(reg);`

False-positive guards:
- Do not flag if the `is_enabled()` check tests only whether the optional `reg` pointer is
  non-NULL (null-regulator guard), which is a different correctness pattern.
- Do not flag if the underlying regulator uses hardware-level enable tracking and the
  refcount model does not apply (explicitly documented custom enable tracking).
- One AI-reviewer data point; apply as [BUG] due to clear regulator framework contract
  violation.

Confidence: low
Last updated: 2026-05-26

### MEM-0107: qcom interconnect driver -- BCM nodes[] must include all masters routing through that BCM

Status: draft
Scope: file-pattern:drivers/interconnect/qcom/*.c
Triggers:
- A new qcom interconnect driver defines a struct qcom_icc_bcm with a nodes[] list
- One or more master nodes (struct qcom_icc_node) are present in the NoC nodes[]
  array and route bandwidth to the same slave endpoints covered by that BCM, but
  are absent from the BCM nodes[] list

Maintainer evidence:
- Patchwise AI review on patch 2/2 of Maili interconnect series (2026-05-08):
  noted that qnm_video_eva and qnm_mdss_dcp (linking to qns_mem_noc_sf) and
  qnm_mdp (linking to qns_mem_noc_hf) were present in mmss_noc_nodes[] but absent
  from bcm_mm1.nodes[] even though all other nodes feeding the same slaves were
  listed. Our automated review did not flag the BCM coverage gap.

Review action:
- For each BCM defined in a new qcom interconnect driver, cross-check its nodes[]
  list against the corresponding NoC nodes[] array: every master node that routes
  traffic through a slave endpoint governed by that BCM should appear in the BCM
  nodes[] list.
- Flag [CONCERN] when a master node routes to a BCM-governed slave but is absent
  from the BCM nodes[] list; omitting nodes silently excludes their bandwidth from
  aggregation, potentially starving the interconnect path.
- Reference the corresponding sm8650 or similar upstream driver as a cross-check
  baseline when reviewing a new SoC interconnect driver.

False-positive guards:
- Do not flag master nodes whose slave endpoints are governed by a different BCM
  that already lists them correctly.
- Do not flag if the commit body or BCM definition explicitly notes the node is
  excluded because its traffic is accounted for through a different bandwidth
  aggregation path.
- Single AI-reviewer data point; treat as draft with low confidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0108: Qcom GCC + icc-clk -- bundle icc-clk support with the initial GCC driver introduction commit

Status: draft
Scope: subsystem:clk/qcom file-pattern:drivers/clk/qcom/gcc-*.c
Triggers:
- A series adds icc-clk NoC clock support to an existing Qualcomm GCC clock
  driver as a standalone follow-on patch (the GCC driver was introduced in a
  prior, already-accepted series)
- The icc-clk patch is the sole new functional change (adds icc_hws[] +
  icc_sync_state to an otherwise unchanged GCC driver)

Maintainer evidence:
- Konrad Dybcio on patch 2/3 "clk: qcom: ipq9650: Use icc-clk for enabling
  NoC related clocks" (linux-arm-msm, 2026-05-18): gave Reviewed-by but noted
  "Please for the next SoC, try to add this in the 'introduce gcc' commit."
  Author acknowledged with "Ack."

Review action:
- Flag [MINOR] when a series adds icc-clk support to a Qualcomm GCC driver as
  a standalone patch and the GCC driver introduction was a separate prior series.
- Suggest the author bundle icc-clk support (icc_hws[], icc_sync_state,
  #interconnect-cells DTS property) with the initial GCC driver introduction
  commit for new SoC bring-up series.
- Note this is a forward-looking preference for the next SoC, not a hard NAK
  on the current standalone series.

False-positive guards:
- Do not flag when the GCC driver predates the icc-clk framework (commit
  88dfc9fe6c62, "clk: qcom: clk-rpmh: Add icc-clk support"); standalone
  follow-on series are the only viable path in that case.
- Do not flag when icc-clk support is being added across multiple existing GCC
  drivers in a single consolidation series.
- Do not flag if the series author explicitly states icc-clk was not available
  at the time of the original GCC introduction.

Confidence: low
Last updated: 2026-05-26

### MEM-0113: drm/msm — prefer `guard()` scoped lock over raw `mutex_lock()`/`mutex_unlock()`

Status: draft
Scope: subsystem:drm/msm file-pattern:drivers/gpu/drm/msm/
Triggers:
- A drm/msm patch adds or retains a raw `mutex_lock()`/`mutex_unlock()` pair
  where the lock scope is entirely within a single function
- The `guard(mutex)` macro from `<linux/cleanup.h>` could replace the pair
  without changing logic

Maintainer evidence:
- Konrad Dybcio requested the substitution in v5→v6 of "drm/msm/dp: Drop the
  HPD state machine" (Message-ID 20260524-hpd-refactor-v6, 2026-05-24); the
  v6 changelog states: "Switched to guard() instead of raw mutex_lock() (Konrad)".

Review action:
- Flag [NIT] when drm/msm code uses a raw `mutex_lock()`/`mutex_unlock()` pair
  with no goto jumps past the unlock and no mid-function conditional release.
- Suggest replacing with `guard(mutex)(&lock)` from `<linux/cleanup.h>`.
- Verify `#include <linux/cleanup.h>` is present or added in the file.

False-positive guards:
- Do not flag when a goto label jumps past the intended unlock point; the scoped
  guard cannot model that pattern.
- Do not flag conditional re-lock or trylock loops where the mutex is released
  and re-acquired mid-function.
- One data point from one reviewer; apply as [NIT] only.
- Do not apply outside drm/msm without additional confirming evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0114: ath12k QMI — new optional capability field in phy_cap_resp must appear in the existing ath12k_dbg() log call

Status: draft
Scope: subsystem:ath12k file-pattern:drivers/net/wireless/ath/ath12k/qmi.c
Triggers:
- A patch adds a new optional QMI TLV field to qmi_wlanfw_phy_cap_resp_msg_v01
  (or a similar phy capability response struct) and populates ab->qmi from it
- The existing ath12k_dbg(ab, ATH12K_DBG_QMI, ...) call at the end of
  ath12k_qmi_phy_cap_send() is not updated to log the new field
- The debug call IS extended but the format string embeds a \n mid-string (not at
  the end) or a new field's label abbreviates the struct field name

Maintainer evidence:
- Raj Kumar Bhagat on [PATCH ath-next v4 7/7] wifi: ath12k: add QMI capability
  negotiation for dynamic memory mode (2026-05-08): "As mentioned in v2, add
  dynamic_ddr_support capability in the above QMI debug log." The new
  dynamic_ddr_support field was read from the response but not added to the
  ath12k_dbg format string already logging num_phy, single_chip_mlo_support,
  and board_id. Author agreed to fix in the next version. The automated review
  missed this (missed-by-us).
- Patchwise AI reviewer on [PATCH ath-next v6] (2026-05-21): when the debug call was
  extended, flagged an embedded \n after "board_id %d" (splitting output mid-message)
  and label "dynamic_ddr_valid" instead of the full struct field name
  "dynamic_ddr_support_valid". checkpatch passed clean because ath12k_dbg() is not a
  standard printk variant and these checks are not applied to it. Our review caught
  the label abbreviation as [NIT] but missed the embedded \n (missed-by-us).

Review action:
- Flag [MINOR] when a patch adds a new optional TLV field to phy_cap_resp and
  populates it, but does not extend the ath12k_dbg(ATH12K_DBG_QMI, ...) call at
  the end of ath12k_qmi_phy_cap_send() to log the new field.
- Suggest appending the new field name and its value/valid pair to the existing
  format string.
- When the debug call IS extended, flag [NIT] if: (a) the format string embeds \n
  mid-string rather than terminating with \n, or (b) a new field's label in the
  format string abbreviates the struct field name (e.g. "dynamic_ddr_valid" vs
  "dynamic_ddr_support_valid"). Use the full struct field name to aid log grepping.

False-positive guards:
- Do not flag if the new field is already logged via a separate ath12k_dbg statement
  or ath12k_info call in the same function.
- Do not flag if the debug log update is deferred to a follow-on patch named in the
  series.
- Do not flag an abbreviated label when other pre-existing fields in the same format
  string already use the same abbreviation consistently.

Confidence: low
Last updated: 2026-05-26

### MEM-0115: Counter incremented under mutex in power_up but decremented without lock in power_down — flag [BUG]

Status: draft
Scope: general
Triggers:
- A reference counter (e.g. num_userpd_active) is incremented inside a function that
  holds a mutex (e.g. ag->mutex)
- The corresponding decrement appears in a paired shutdown function that does NOT
  acquire the same mutex before decrementing
- Both functions are callable concurrently from multiple contexts

Maintainer evidence:
- Raj Kumar Bhagat on [PATCH ath-next v4 6/7] wifi: ath12k: add support to load
  shared firmware (2026-05-08): "In ath12k_ahb_power_up(), incrementing
  ag->num_userpd_active is protected with ag->mutex, but in ath12k_ahb_power_down(),
  ag->mutex lock is not acquired while decrementing ag->num_userpd_active. Consider
  using atomic variable for ag->num_userpd_active?" Author agreed to address in the
  next version. Our automated review missed this race condition (missed-by-us).

Review action:
- Flag [BUG] when a counter is incremented under a named mutex in one function and
  decremented in a paired function without the same mutex being held.
- Suggest either: (a) acquiring the mutex around the decrement in the teardown path,
  or (b) converting the counter to atomic_t and using atomic_inc()/atomic_dec().
- Verify both power_up/power_down paths for shared resource lifecycle counters in
  AHB/remoteproc-style drivers.

False-positive guards:
- Do not flag if the teardown function is always called with the mutex already held
  by the caller at the call site.
- Do not flag if the counter is already atomic_t.
- Do not flag if the counter is only ever touched from a single-threaded context
  serialised by another documented mechanism.

Confidence: low
Last updated: 2026-05-26

### MEM-0116: __free(firmware) is a valid kernel scope cleanup specifier — do not flag as invalid

Status: draft
Scope: general file-pattern:drivers/
Triggers:
- A patch declares a firmware pointer with __free(firmware) scope cleanup:
  const struct firmware *fw __free(firmware) = NULL;
- A review concern is raised that DEFINE_FREE(firmware, ...) does not exist and
  the declaration will fail to compile

Maintainer evidence:
- Aaradhana Sahu on [PATCH ath-next v4 6/7] wifi: ath12k: add support to load
  shared firmware (2026-05-07): "__free(firmware) is already supported through
  DEFINE_FREE(firmware, ...) in include/linux/firmware.h, so this usage compiles
  correctly and automatically calls release_firmware() on scope exit." Also
  confirmed that mixed declarations with cleanup helpers are allowed in modern
  kernel code. The automated review incorrectly flagged this (false positive by us).

Review action:
- Do NOT flag __free(firmware) as an invalid cleanup specifier; it is defined via
  DEFINE_FREE in include/linux/firmware.h and calls release_firmware() on scope exit.
- Do NOT flag a __free()-annotated declaration after executable statements as a C89
  violation; the kernel permits mixed declarations when using cleanup.h.

False-positive guards:
- Still flag if the firmware pointer scope ends too early, causing premature
  release_firmware() calls before the caller is done.
- Still flag if DEFINE_FREE(firmware, ...) is genuinely absent in the kernel version
  under review.

Confidence: low
Last updated: 2026-05-26

### MEM-0118: Qcom DTS series — ARM32 patches must be submitted separately from arm64 patches

Status: draft
Scope: subsystem:arm/qcom file-pattern:arch/arm/boot/dts/qcom/
Triggers:
- A patch series contains at least one patch that modifies files under
  arch/arm/boot/dts/ (ARM32 DTS) alongside patches modifying
  arch/arm64/boot/dts/ (ARM64 DTS)
- The cover letter or series subject implies it targets only arm64

Maintainer evidence:
- Manivannan Sadhasivam on patch 1/18 "ARM: dts: qcom: sdx55: Fix PCIe wake GPIO
  polarity" (linux-arm-msm, 2026-05-14): "You should send ARM32 patches separately."
  The patch modified arch/arm/boot/dts/qcom/qcom-sdx55-t55.dts but was submitted in
  the same series as 17 arm64 patches. Our automated review did not flag this
  series-organization violation (missed-by-us).

Review action:
- Flag [MINOR] when a series mixes patches touching arch/arm/boot/dts/ with patches
  touching arch/arm64/boot/dts/.
- Suggest extracting the ARM32 patch(es) into a separate submission with subject
  prefix "ARM: dts: qcom:" rather than "arm64: dts: qcom:".
- Check the series cover letter subject line: if it says "arm64: dts: qcom" but one
  or more patches modify arch/arm/boot/dts/, flag the mismatch.

False-positive guards:
- Do not flag if the series maintainer (e.g. Bjorn Andersson) has already acknowledged
  mixing is acceptable in this specific context.
- Do not flag if every patch in the series touches only arch/arm/boot/dts/ — a pure
  ARM32 series needs no split.
- Do not flag series that touch neither arch/arm/ nor arch/arm64/ (e.g. driver-only).

Confidence: low
Last updated: 2026-05-26

### MEM-0119: ARM/Coresight CTI — do not annotate hardware-variant flag check with `unlikely()`

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/coresight-cti*
Triggers:
- A patch adds `if (unlikely(drvdata->is_qcom_cti))` or a similar
  `unlikely()`-wrapped boolean that was set once at probe from a hardware
  DEVARCH/DEVID register read (i.e., a stable per-device hardware-variant flag)
- The flag is used inside a hot-path MMIO address computation helper that is
  called on every register read/write

Maintainer evidence:
- Jie Gan on patch 3/4 of series
  20260426-extended-cti-v8-0-23b900a4902f@oss.qualcomm.com: "I prefer to drop
  the unlikely here, let the cpu do the branch predictor." on the `is_qcom_cti`
  check in `cti_reg_addr()`. Author agreed.

Review action:
- Flag [NIT] when `unlikely()` is placed on a per-device boolean flag that is
  set once at probe time from a hardware register (DEVARCH, DEVID, etc.) and
  reflects a stable hardware configuration, not a runtime error path.
- Suggest removing the `unlikely()` annotation and letting the branch predictor
  handle the stable flag naturally.

False-positive guards:
- Do not flag `unlikely()` on genuine low-probability error paths (e.g.,
  `unlikely(ret < 0)` after an MMIO write) — those are appropriate uses.
- Do not flag `unlikely()` on booleans that change dynamically at runtime.

Confidence: low
Last updated: 2026-05-26

### MEM-0120: ARM/Coresight CTI — prefer (offset, index) parameter pair over single bit-packed register encoding

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/coresight-cti*
Triggers:
- A CTI patch introduces a single-integer bit-packed encoding (e.g.
  `CTI_REG_NR_MASK`, `CTI_REG_SET_NR`, `CTI_REG_GET_NR`, `CTI_REG_CLR_NR`)
  to carry both a base MMIO register offset and a bank/trigger index in one
  `u32` passed to a register access helper
- The helper must then unpack the offset and index before computing the final
  MMIO address

Maintainer evidence:
- Leo Yan on patch 2/4 of series
  20260426-extended-cti-v8-0-23b900a4902f@oss.qualcomm.com: suggested replacing
  the bit-pack macros with:
    `static void __iomem *__reg_addr(struct cti_drvdata *drvdata, int off, int index)`
    plus `#define reg_addr(drvdata, off)` and `#define reg_index_addr(drvdata, off, i)`.
  Author agreed to adopt this approach.

Review action:
- Flag [MINOR] when a new CTI MMIO helper encodes the register index into the
  offset integer (bit-packing) rather than accepting explicit (offset, index)
  parameters.
- Suggest the simpler `__reg_addr(drvdata, off, index)` approach with thin
  `reg_addr()` and `reg_index_addr()` wrapper macros so call sites read
  `reg_index_addr(drvdata, CTIINEN, i)` instead of
  `cti_reg_addr(drvdata, CTI_REG_SET_NR(CTIINEN, i))`.
- Note that bit-packing also risks overlap between the index field and the full
  CoreSight component address space (up to 26 bits per IHI0029) unless the
  index bits are placed well above the realistic offset range.

False-positive guards:
- Do not flag if the helper already uses separate (offset, index) parameters.
- Do not flag existing pre-patch code that uses the CTIINEN(n)/CTIOUTEN(n)
  parameterized macros — they are the upstream pattern being replaced.

Confidence: low
Last updated: 2026-05-26

### MEM-0121: ARM/Coresight CTI — store bank index in `cs_off_attribute`; use `container_of()` in sysfs visibility callback

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/coresight-cti-sysfs.c
Triggers:
- A patch adds indexed/banked sysfs register attributes (e.g. `triginstatus1`,
  `triginstatus2`) as static entries with the bank number encoded only in the
  attribute name
- The `coresight_cti_regs_is_visible()` callback determines the bank index by
  parsing the trailing digit from `attr->name` with `kstrtoint()` / string
  comparison rather than reading a struct field

Maintainer evidence:
- Leo Yan on patch 4/4 of series
  20260426-extended-cti-v8-0-23b900a4902f@oss.qualcomm.com: suggested adding
  `u32 index` to `struct cs_off_attribute`, introducing a
  `coresight_cti_reg_index(name, offset, index)` registration macro, and using
  `container_of(attr, struct cs_off_attribute, attr)` to read the index directly
  in the visibility callback. Author agreed.

Review action:
- Flag [MINOR] when the CTI sysfs visibility callback uses string-parsing
  (e.g. `kstrtoint(attr->name + len, 10, &nr)`) to recover the bank index
  instead of storing it as a typed field in the attribute struct.
- Suggest the `container_of()` pattern: extend `cs_off_attribute` with an
  `index` field set by the registration macro, then read it directly in the
  callback.
- This avoids brittle string matching and keeps the visibility logic
  independent of naming conventions.

False-positive guards:
- Do not flag the visibility callback for the existing non-indexed attributes
  (e.g. `asicctl`) — those use a direct pointer comparison, which is fine.
- Do not flag if the patch already stores the index in the attribute struct.

Confidence: low
Last updated: 2026-05-26

### MEM-0122: ath12k platform-variant series -- each patch must explain backward compatibility

Status: draft
Scope: subsystem:ath12k
Triggers:
- A series of ath12k patches has a cover letter stating the changes "maintain
  backward compatibility" across IPQ5332 or other platform variants
- One or more individual patches in the series omit any sentence explaining how
  the specific change is backward compatible with existing DT bindings or
  deployed platforms

Maintainer evidence:
- Jeff Johnson on [PATCH ath-next v3 1/7] wifi: ath12k: switch to name-based
  reserved memory lookup (ath12k, 2026-04-30): "Since your cover letter says
  'These changes [...] maintain backward compatibility across different IPQ5332
  platform variants' I'd like each patch to explain how backward compatibility
  is maintained." He suggested citing that the names are defined in
  qcom,ipq5332-wifi.yaml, or noting that no upstream IPQ5332 DTS exists yet.
  Author agreed to update all patches. Our review suggested mentioning the
  specific lookup names but missed the backward-compat explanation requirement
  (partially missed-by-us).

Review action:
- Flag [MINOR] when an ath12k series cover letter claims backward compatibility
  across platform variants but individual patch bodies contain no sentence
  explaining how the specific change maintains that compatibility.
- Suggest: (a) citing the DT binding file where the used names are already
  defined, (b) noting that no upstream DTS for the target platform exists yet,
  or (c) describing the fallback behavior for platforms that lack the resource.

False-positive guards:
- Do not flag when the patch body already contains a backward-compat sentence,
  even briefly.
- Do not flag patches whose backward compat is self-evident (pure refactor,
  no DT or ABI impact).
- Do not apply to series that do not mention backward compatibility in the
  cover letter.

Confidence: low
Last updated: 2026-05-26

### MEM-0123: Intentionally discarded return value in teardown path -- add comment or log

Status: draft
Scope: general
Triggers:
- A fallible function's return value is discarded (no assignment, no cast to
  void) inside a teardown, deconfigure, or cleanup function
- The discard is intentional: cleanup must continue regardless of the error
- No code comment explains the intentional ignore and no log records the failure

Maintainer evidence:
- Baochen Qiang on [PATCH ath-next v3 6/7] wifi: ath12k: add support to load
  shared firmware (ath12k, 2026-04-29): "is the return value intentionally
  ignored?" for a bare rproc_shutdown() call, followed by "better to log it
  when fail? and better to have a comment noting that the return value is
  intentionally ignored for the purpose of ..." Author agreed to add a comment
  in the next version. Our automated review did not flag this (missed-by-us).

Review action:
- Flag [NIT] when a fallible function's return value is silently discarded in
  a teardown or cleanup path with no log and no explanatory comment.
- Suggest: (a) logging the failure before continuing (e.g. dev_warn() or
  ath12k_warn()), or (b) adding a brief comment such as "/* intentionally
  ignored - cleanup must proceed even if shutdown fails */".
- Use [NIT], not [MINOR] or [CONCERN], unless the missed error can cause a
  resource leak or data corruption.

False-positive guards:
- Do not flag if a comment already explains the intentional discard.
- Do not flag functions that are explicitly documented as best-effort or
  fire-and-forget (e.g. cancel_work_sync(), devm_* cleanup helpers).
- Do not flag if the calling function is itself void and propagating an error
  return is structurally impossible.
- Do not flag if a dev_warn() or similar call already logs the failure in
  the same block.

Confidence: low
Last updated: 2026-05-26

### MEM-0124: Qcom Geni I2C clock-mode table -- hardcoded array index into geni_i2c_clk_map_* is fragile; use mode-based lookup

Status: draft
Scope: subsystem:i2c/qcom file-pattern:drivers/i2c/busses/i2c-qcom-geni.c
Triggers:
- A patch selects a clock-frequency table entry with a hardcoded numeric index
  (e.g. gi2c->clk_fld = &itr[2]) instead of searching for the matching entry
  by frequency or by a named mode constant
- The comment or surrounding code names the target frequency but does not
  make the index derivation self-evident

Maintainer evidence:
- Konrad Dybcio on [PATCH v1 2/2] "i2c: qcom-geni: Add support for I2C
  High-Speed mode" (linux-arm-msm, 2026-05-08): "This is not at all - I
  suggest rewriting the code that parses geni_i2c_clk_fld to use index-based
  lookups, with modes being the indices" in response to gi2c->clk_fld =
  &itr[2] selecting the 1 MHz Fast Mode Plus entry needed for the HS master
  code phase.  Author agreed to introduce mode-indexed constants.

Review action:
- Flag [MINOR] when a patch selects a geni_i2c_clk_map_* entry by bare
  numeric index.
- Suggest introducing a named mode constant (e.g. GENI_I2C_MODE_FMP = 2)
  and using &itr[GENI_I2C_MODE_FMP], or refactoring to search the table
  for the desired frequency the same way the non-HS path does.

False-positive guards:
- Do not flag if the index is derived from a named constant that makes the
  selection self-evident.
- Do not flag iteration indices in table-scanning loops.

Confidence: low
Last updated: 2026-05-26

### MEM-0125: Struct field widening (e.g. u8 to u16) requires a comment explaining bit-width rationale and max values per mode

Status: draft
Scope: general
Triggers:
- A patch widens integer fields in a kernel struct (e.g. u8 to u16)
  without adding a comment that explains: (a) why the wider type is now
  required (e.g. new hardware mode uses 10-bit fields), and (b) what the
  maximum value is in each operational mode (normal vs extended)
- The widening is visible in the diff but the commit body and code comments
  are silent about the constraint change

Maintainer evidence:
- Konrad Dybcio on [PATCH v1 2/2] "i2c: qcom-geni: Add support for I2C
  High-Speed mode" (linux-arm-msm, 2026-05-08): asked "Have these fields
  always been larger, or is that new with the HS-capable hosts?" when
  geni_i2c_clk_fld.t_high_cnt/t_low_cnt/t_cycle_cnt were widened from
  u8 to u16.  In follow-up (2026-05-11): "Please add a comment reflecting
  their maximum values in normal and HS modes."  Author agreed to add the
  comment in v2.  Our automated review did not flag the missing annotation
  (missed-by-us).

Review action:
- Flag [MINOR] when a struct field is widened and neither the diff nor the
  commit body explains the new bit-width requirement or the per-mode maximum
  value.
- Suggest adding a code comment directly above or alongside the widened
  fields, e.g. "8-bit in normal mode; 10-bit in HS mode (per QUPv3 HPG)".

False-positive guards:
- Do not flag if the diff already adds an explanatory comment alongside the
  widened declaration.
- Do not flag trivial type promotions driven solely by arithmetic safety
  (e.g. avoiding signed overflow) where the maximum value is unchanged and
  self-evident from context.

Confidence: low
Last updated: 2026-05-26

### MEM-0126: Qcom QUPv3 -- new hardware-mode feature must include a runtime version capability check

Status: draft
Scope: subsystem:i2c/qcom file-pattern:drivers/i2c/busses/i2c-qcom-geni.c
Triggers:
- A patch enables a new hardware operating mode (e.g. I2C High-Speed at
  3.4 MHz) on the Qualcomm GENI QUPv3 I2C controller
- The mode requires a minimum QUPv3 core version (e.g. 4.3 per the HPG)
- No runtime check for the required minimum version is added or referenced

Maintainer evidence:
- Konrad Dybcio on [PATCH v1 2/2] "i2c: qcom-geni: Add support for I2C
  High-Speed mode" (linux-arm-msm, 2026-05-11): "Can/should we check that?"
  after the author stated HS support requires QUPv3 core version >= 4.3 per
  the HPG.  Author agreed to add a version check in v2.  Our automated
  review did not flag the missing capability guard (missed-by-us).

Review action:
- Flag [MINOR] when a new QUPv3 hardware feature is added with a stated
  minimum version requirement but no runtime check verifies that requirement.
- Suggest reading the QUP hardware version register (or using an existing
  helper that already exposes the core revision) and failing gracefully at
  probe or feature-enable time if the required version is not met.

False-positive guards:
- Do not flag if the required version is guaranteed by DT compatible string
  matching (i.e., the compatible is only used on SoCs that always meet the
  minimum version requirement, and this is noted in the commit or binding).
- Do not flag if a version check is already present elsewhere in the probe
  path for the same hardware block.

Confidence: low
Last updated: 2026-05-26

### MEM-0127: Qcom Geni I2C -- prefer ternary over if/else for single-argument conditional function calls

Status: draft
Scope: subsystem:i2c/qcom file-pattern:drivers/i2c/busses/i2c-qcom-geni.c
Triggers:
- A patch adds an if/else block whose only difference is one argument to
  an otherwise identical function call (e.g. if/else selecting HS_OP vs
  STD_OP for geni_se_setup_m_cmd())
- The expanded form adds four lines where a single ternary expression would
  suffice (e.g. fn(A, is_hs_mode ? HS_OP : STD_OP, rest))

Maintainer evidence:
- Konrad Dybcio on [PATCH v1 2/2] "i2c: qcom-geni: Add support for I2C
  High-Speed mode" (linux-arm-msm, 2026-05-08): flagged two identical
  if/else patterns in geni_i2c_rx_one_msg() and geni_i2c_tx_one_msg()
  with "ditto", suggesting:
    geni_se_setup_m_cmd(se, gi2c->is_hs_mode ? I2C_HS_READ : I2C_READ, m_param);
  in both cases.  Author agreed to update.  Our automated review did not
  flag these patterns (missed-by-us).

Review action:
- Flag [NIT] when an if/else block calls the same function with one
  conditionally selected argument; suggest collapsing to a ternary.
- Apply as [NIT] only; do not escalate.

False-positive guards:
- Do not flag if the two branches perform materially different side effects
  beyond a single argument difference.
- Do not apply to if/else blocks with non-trivial bodies or where ternary
  would reduce readability (e.g., long argument lists requiring line breaks).
- Single-driver evidence only; apply as [NIT] and treat as draft until
  confirmed in another subsystem.

Confidence: low
Last updated: 2026-05-26

### MEM-0128: Probe error-label EPROBE_DEFER guard -- `return 0` leaks resources and returns false success

Status: draft
Scope: general
Triggers:
- A probe error label introduces if (ret == -EPROBE_DEFER) return 0; before
  remaining cleanup calls (PHY power-off, deinit, resource release)
- The guard bypasses all subsequent cleanup AND returns 0 (false success) instead
  of the real error code to the caller

Maintainer evidence:
- Krishna Chaitanya Chundru (patch author) on PCI: qcom: Add link retention support
  (linux-arm-msm, 2026-05-08): confirmed our logic is not correct as we are
  returning here unconditionally, I will update the logic. The patch had
  if (ret == -EPROBE_DEFER) return 0; at err_pwrctrl_destroy:, bypassing
  qcom_pcie_phy_power_off() and deinit() and returning 0 to the caller.
  Three simultaneous problems: (1) false success returned, (2) PHY left powered,
  (3) clocks/regulators not released. Our automated review correctly flagged [BUG].

Review action:
- Flag [BUG] when an error label uses if (ret == -EPROBE_DEFER) return 0; in
  a path that still has cleanup calls below it.
- Check three failure modes together: (1) false success (0 not ret returned to
  caller), (2) bypassed PHY/power teardown, (3) bypassed clock/regulator deinit.
- The correct pattern: selectively skip one preserved cleanup call with
  if (ret != -EPROBE_DEFER) call();, fall through to all other cleanup, then
  return ret.

False-positive guards:
- Do not flag if (ret != -EPROBE_DEFER) call(); guards that fall through to
  remaining cleanup -- that is the correct selective-skip pattern.
- Do not flag if (ret == -EPROBE_DEFER) return ret; (returns the real error code).
- Do not flag EPROBE_DEFER handling in paths where no further cleanup remains.

Confidence: low
Last updated: 2026-05-26

### MEM-0129: Qcom PCIe -- per-boot operational message should use dev_dbg, not dev_info

Status: draft
Scope: subsystem:pci/qcom file-pattern:drivers/pci/controller/dwc/pcie-qcom.c
Triggers:
- A patch adds dev_info() for a routine operational state message that fires on
  every boot cycle for affected platforms (e.g., Retaining PCIe link)
- The message indicates successful operation rather than an error or warning condition

Maintainer evidence:
- Konrad Dybcio (Qualcomm PCIe reviewer) on PCI: qcom: Add link retention support
  (linux-arm-msm, 2026-05-08): generally this seems like a dev_dbg candidate
  for dev_info(dev, "Retaining PCIe link\n"). He noted it could remain dev_info
  if the feature is expected to cause debugging issues; the patch author pushed back
  citing debugging value, and Konrad left the final choice to the author. Our
  automated review independently flagged the same [MINOR] (confirmed).

Review action:
- Flag [MINOR] when a per-boot operational message in pcie-qcom.c uses dev_info()
  where dev_dbg() would suffice for a routine (non-error) state report.
- Note that the maintainer preference is dev_dbg but the maintainer left the choice
  to the author when a strong observability justification exists.

False-positive guards:
- Do not flag dev_info for error conditions, warnings, or messages expected to be
  rare (e.g., resource allocation failure, unexpected state transition).
- Do not apply outside pcie-qcom.c or Qcom PCIe driver files without confirming the
  same preference from a PCIe subsystem maintainer.
- Do not escalate above [MINOR]; this is a logging-level preference, not a bug.

Confidence: medium
Last updated: 2026-05-26
Note: MEM-0178 captures the broader kernel-wide principle behind this entry.
  Use MEM-0178 when the dev_info() is a probe-time entity-count message in any
  driver; use MEM-0129 only for per-boot operational messages in pcie-qcom.c.

### MEM-0130: ARM/Coresight ETM4x --- seq_ctrl[] is sized for transitions (3), not states (4); rename macro accordingly

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/coresight-etm4x*
Triggers:
- A patch touches ETM_MAX_SEQ_STATES, seq_ctrl[], or TRCSEQEVRn(i) in ETM4x
  sequencer logic
- The existing macro ETM_MAX_SEQ_STATES (value 4) is used to size the seq_ctrl[]
  array or bound the TRCSEQEVRn loop, but the hardware only implements 3 sequence
  transitions (TRCSEQEVRn, n=0..2) when TRCIDR5.NUMSEQSTATE is 0b100

Maintainer evidence:
- Leo Yan (ARM/Coresight reviewer) on patch 2/13 of
  20260422132203.977549-1-yeoreum.yun@arm.com (coresight: etm4x: fix underflow
  for nrseqstate, linux-arm-kernel, 2026-05-05): "we also need to rename
  ETM_MAX_SEQ_STATES to ETM_MAX_SEQ_TRANSITIONS and define it as 3 ... we don't
  allocate 4 items but use only 3 of them."
- Yeoreum Yun (patch author) agreed on the same thread (2026-05-15): proposed
  #define ETM_MAX_SEQ_TRANSITIONS (ETM_MAX_SEQ_STATE - 1), and Leo accepted.
  Our automated review flagged -ENOTSUPP on this patch but missed the array
  sizing / macro rename issue (missed-by-us).

Review action:
- Flag [MINOR] when ETM_MAX_SEQ_STATES (or its value 4) is used to size
  seq_ctrl[] or to bound a TRCSEQEVRn(i) write loop; suggest renaming to
  ETM_MAX_SEQ_TRANSITIONS defined as (ETM_MAX_SEQ_STATE - 1) (= 3).
- Verify: TRCSEQEVRn is defined for n = 0, 1, 2 only; a size-4 array wastes one
  element and the loop bound is off by one if nrseqstate is derived from
  TRCIDR5.NUMSEQSTATE correctly.

False-positive guards:
- Do not flag if the array or loop is already bounded by a runtime capability
  field (e.g. drvdata->nrseqstate) rather than the compile-time constant.
- Do not flag ETM3x code; the ETM3x sequencer register map differs.
- Do not apply outside ARM Coresight ETM4x driver files without confirming the
  same TRCIDR5 register semantics.

Confidence: low
Last updated: 2026-05-26

### MEM-0131: Qcom IMEM/SRAM stats and debugfs reader drivers belong in drivers/soc/qcom/, not drivers/firmware/qcom/

Status: draft
Scope: subsystem:arm/qcom file-pattern:drivers/firmware/qcom/
Triggers:
- A new Qualcomm driver reads a fixed IMEM or SRAM region (boot stats, memory
  dump, sleep counters, etc.) and exposes it through debugfs
- The driver is placed in `drivers/firmware/qcom/` rather than `drivers/soc/qcom/`

Maintainer evidence:
- Konrad Dybcio on patch 2/3 of 20260522102731.1054546-1-yogesh.lal@oss.qualcomm.com
  (firmware: qcom: Add IMEM boot stats reader, linux-arm-msm 2026-05-22):
  "We have similar drivers in drivers/soc/qcom/, I think that's a better place
  for it." Our automated review placed the driver in firmware/qcom/ without
  questioning the subsystem placement (missed-by-us).

Review action:
- Flag [CONCERN] when a new Qcom IMEM/SRAM stats reader or debugfs exporter
  is placed in `drivers/firmware/qcom/`. Suggest `drivers/soc/qcom/` instead,
  citing existing precedents (e.g. `drivers/soc/qcom/rpm_master_stats.c`).

False-positive guards:
- Do not flag drivers that interact with firmware protocols (SCM, SMEM, SMD)
  rather than directly reading a memory-mapped SRAM region; those belong in
  firmware/qcom/.
- Do not flag if a Qualcomm maintainer in the same thread has already accepted
  the firmware/qcom/ placement.

Confidence: low
Last updated: 2026-05-26

### MEM-0132: Qualcomm Innovation Center copyright must use the year-less format

Status: draft
Scope: subsystem:arm/qcom
Triggers:
- A new source file or binding YAML carries a Qualcomm copyright line of the
  form `Copyright (c) <YEAR>, Qualcomm Innovation Center, Inc.`
- The year is included in the copyright notice

Maintainer evidence:
- Konrad Dybcio on patch 2/3 of 20260522102731.1054546-1-yogesh.lal@oss.qualcomm.com
  (firmware: qcom: Add IMEM boot stats reader, linux-arm-msm 2026-05-22):
  "Please switch to the new year-less copyright format" on a file with
  `Copyright (c) 2026, Qualcomm Innovation Center, Inc. All rights reserved.`

Review action:
- Flag [MINOR] when a new file in a Qualcomm patch uses a Qualcomm copyright
  line that includes a year.
- Suggest: `Copyright (c) Qualcomm Innovation Center, Inc. All rights reserved.`
  (no year).

False-positive guards:
- Do not flag non-Qualcomm copyright holders; the year-less convention is
  specific to Qualcomm Innovation Center files.
- Do not flag copyright lines that already omit the year.
- One data point; apply as [MINOR] until a second instance confirms it.

Confidence: low
Last updated: 2026-05-26

### MEM-0133: Qcom SRAM/IMEM stats driver --- define memory layout as struct and use memcpy_fromio() instead of per-field readl_relaxed()

Status: draft
Scope: subsystem:arm/qcom file-pattern:drivers/soc/qcom/
Triggers:
- A new Qcom SRAM or IMEM stats driver reads a contiguous fixed-layout memory
  region using multiple individual `readl_relaxed(base + OFFSET)` calls
- The fields are consecutive and form a well-known firmware-defined struct

Maintainer evidence:
- Konrad Dybcio on patch 2/3 of 20260522102731.1054546-1-yogesh.lal@oss.qualcomm.com
  (firmware: qcom: Add IMEM boot stats reader, linux-arm-msm 2026-05-22):
  "Please define the structure found in memory and simply memcpy_fromio() it.
  See drivers/soc/qcom/rpm_master_stats.c" -- in response to six sequential
  readl_relaxed() calls for a 0x20-byte boot-stats region.

Review action:
- Flag [MINOR] when a Qcom SRAM/IMEM stats driver reads a contiguous fixed
  firmware layout with multiple individual readl_relaxed() calls.
- Suggest defining a packed struct mirroring the memory layout and using
  `memcpy_fromio(&local, base, sizeof(local))` for a single atomic bulk read.
- Cross-reference `drivers/soc/qcom/rpm_master_stats.c` as the established
  in-tree pattern.

False-positive guards:
- Do not flag drivers that read non-contiguous registers or registers from
  different IP blocks where a single struct does not apply.
- Do not flag if the read calls are intentionally ordered or gated by status
  fields that require sequential conditional logic.

Confidence: low
Last updated: 2026-05-26

### MEM-0134: Qcom debugfs stats driver --- add files under existing /sys/kernel/debug/qcom_stats/, not a new directory

Status: draft
Scope: subsystem:arm/qcom file-pattern:drivers/soc/qcom/
Triggers:
- A new Qcom SRAM/IMEM stats driver creates its own debugfs subdirectory
  (e.g. `debugfs_create_dir("qcom_boot_stats", NULL)`) for a single
  or small number of files
- An existing `/sys/kernel/debug/qcom_stats/` directory is already used for
  Qualcomm platform statistics (e.g. RPM/RPMH sleep stats)

Maintainer evidence:
- Konrad Dybcio on patch 2/3 of 20260522102731.1054546-1-yogesh.lal@oss.qualcomm.com
  (firmware: qcom: Add IMEM boot stats reader, linux-arm-msm 2026-05-22):
  "A separate directory for a single file seems a little overkill. We already
  have /sys/kernel/debug/qcom_stats/ (for RPM/H sleep statistics) - can we
  push it there?" Our automated review did not suggest using the shared
  directory (missed-by-us).

Review action:
- Flag [MINOR] when a new Qcom stats driver creates its own top-level debugfs
  directory for one or a few files.
- Suggest adding the file(s) to the existing `qcom_stats` debugfs directory
  instead, citing the RPM/H sleep stats precedent.

False-positive guards:
- Do not flag if the new driver's files are logically unrelated to platform
  power/boot statistics (e.g. a debug interface for a completely separate
  hardware block).
- Do not flag if the `qcom_stats/` directory does not yet exist in the tree
  the patch targets.

Confidence: low
Last updated: 2026-05-26

### MEM-0135: Qcom driver --- do not list multiple of_device_id compatible strings when the driver does not differentiate behaviour between them

Status: draft
Scope: subsystem:arm/qcom
Triggers:
- A new Qcom driver's `of_device_id` table lists both a SoC-specific compatible
  (e.g. `qcom,sdx75-imem-boot-stats`) and a generic fallback compatible
  (e.g. `qcom,imem-boot-stats`) as separate entries
- The driver assigns no `.data` pointer or probe-time branching to distinguish
  them; both entries resolve to identical driver behaviour

Maintainer evidence:
- Konrad Dybcio on patch 2/3 of 20260522102731.1054546-1-yogesh.lal@oss.qualcomm.com
  (firmware: qcom: Add IMEM boot stats reader, linux-arm-msm 2026-05-22):
  "There is no reason to define two compatibles here, as the driver does not
  behave any differently for either of them." Our automated review did not flag
  the redundant entry (missed-by-us).

Review action:
- Flag [MINOR] when a Qcom driver's `of_device_id` table has two or more
  entries with no associated `.data` or driver-side branching that would use
  them differently.
- Suggest keeping only the most generic compatible (or the most specific if
  backward compatibility is not needed) and removing redundant entries.

False-positive guards:
- Do not flag when entries carry distinct `.data` pointers used to select
  per-SoC configuration tables or init functions.
- Do not flag the standard Linux DT pattern of generic-fallback in the DTS
  (the DTS node may list both, but the driver table need only list the ones
  the driver actually handles distinctly).
- Apply as [MINOR], not [CONCERN] or [BUG].

Confidence: low
Last updated: 2026-05-26

### MEM-0137: ARM/Coresight device_unregister inside coresight_mutex causes circular lock dependency

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/coresight-core.c
Triggers:
- A CoreSight patch calls device_unregister() or device_del() while holding coresight_mutex
- Sysfs write callbacks such as enable_source_store() also hold coresight_mutex after
  kernfs_get_active_of() acquires kn->active, creating the inverted ordering

Maintainer evidence:
- James Clark (Linaro/CoreSight reviewer) on patch 7/27 of v11 power-management series
  (20260501-arm_coresight_path_power_management_improvement, 2026-05-07): concurrent
  sysfs enable/disable loop + rmmod on Juno triggered lockdep warning for chain
  kn->active -> cpu_hotplug_lock -> coresight_mutex, with coresight_unregister()
  holding coresight_mutex and calling device_unregister() -> kernfs_drain() -> kn->active.
- Leo Yan (2026-05-08): confirmed deadlock sequence; proposed moving device_unregister()
  after mutex_unlock() and noted device_register() should be moved out symmetrically.
- Our automated review missed this entirely (missed-by-us).

Review action:
- Flag [CONCERN] when device_unregister() or device_del() is called inside a
  coresight_mutex-held critical section.
- Fix: call mutex_unlock(&coresight_mutex) before device_unregister() so that
  sysfs callbacks can finish and release kn->active before the unregister path
  acquires it via kernfs_drain(). Move device_register() outside the mutex
  symmetrically.

False-positive guards:
- Do not flag coresight_device_release() (kobject release callback); it runs
  outside the mutex after device_unregister() returns.
- Do not apply to helpers that only touch connection tables or IDR without
  calling device_unregister().

Confidence: low
Last updated: 2026-05-26

### MEM-0138: ARM/Coresight subtype union must not be accessed without checking csdev->type first

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/
Triggers:
- Code reads csdev->subtype.source_subtype (or sink_subtype / link_subtype) without
  first confirming csdev->type equals the corresponding CORESIGHT_DEV_TYPE_* value
- The subtype field is a C union; the source_subtype member interpretation is undefined
  for non-source devices

Maintainer evidence:
- Suzuki K Poulose (ARM/Coresight maintainer) on patch 25/27 of v11 series
  (20260501-arm_coresight_path_power_management_improvement, 2026-05-06):
  "Minor nit: You must check the csdev->type == DEV_TYPE_SOURCE before check the
  subtype." Helper coresight_source_get_refcnt() compared source_subtype with
  CORESIGHT_DEV_SUBTYPE_SOURCE_SOFTWARE without a type guard. Leo Yan agreed and
  proposed a coresight_is_software_source() helper that checks both fields.
- Our automated review did not flag the missing discriminant check (missed-by-us).

Review action:
- Flag [MINOR] when csdev->subtype.source_subtype (or any union variant) is accessed
  without a preceding csdev->type check.
- Suggest a small helper that combines both checks, e.g. coresight_is_software_source().

False-positive guards:
- Do not flag inside a switch/case branch that already selects on csdev->type.
- Do not flag the appropriate union variant when the matching type guard is already
  present for that variant (sink_subtype with DEV_TYPE_SINK, etc.).

Confidence: low
Last updated: 2026-05-26

### MEM-0140: Notifier-handle pointer must not be used in a 3-state (NULL / valid / ERR_PTR) pattern — flag [BUG]

Status: draft
Scope: general
Triggers:
- A function registers a notifier (e.g. via `qcom_register_ssr_notifier()` or
  `qcom_register_ssr_atomic_notifier()`) and stores the returned handle in a pointer field
- On registration failure the handle is assigned the ERR_PTR() return value and not reset to NULL
- All subsequent checks for the registered/unregistered state test only `!ptr` (NULL check),
  silently treating an ERR_PTR() stored value as a valid handle and skipping the
  unregister call or proceeding to dereference

Maintainer evidence:
- Jeff Johnson (ath12k maintainer) on [PATCH ath-next 1/6] and [PATCH ath-next 3/6] of
  <20260519061217.702484-1-aaradhana.sahu@oss.qualcomm.com> (2026-05-19): "note that this
  misbehaves when g_rproc_info->root_pd_notifier is an ERR_PTR()" and "Upstream does not
  like having a 3-state pointer, so we should consistently use either NULL or an ERR_PTR()
  to represent an invalid notifier." Two independent instances in the same series
  (root_pd_notifier in patch 1/6, root_pd_fatal_notifier in patch 3/6). Our automated
  review could not flag this because the series failed to apply (missed-by-us pattern).

Review action:
- Flag [BUG] when a pointer field can hold three distinct states (NULL = not-yet-registered,
  valid ptr = registered, ERR_PTR() = registration failed) but all guards only check for NULL.
- Suggest one of: (a) reset the field to NULL on registration failure so it is always either
  NULL or valid, or (b) use IS_ERR_OR_NULL() consistently in every guard and unregister check.
- Verify both the register path (what is stored on failure) and every check site (NULL-only
  vs IS_ERR_OR_NULL() vs IS_ERR()).

False-positive guards:
- Do not flag if the pointer is always reset to NULL after a failed registration (only
  two valid states remain: NULL and valid).
- Do not flag if all check sites already use IS_ERR_OR_NULL() or IS_ERR() consistently.
- Do not flag for pointer fields that can never be returned as ERR_PTR() (e.g. returning
  only NULL on failure by API contract).

Confidence: low
Last updated: 2026-05-26

### MEM-0141: ath12k multi-device shared-state constructor must not embed hardware-specific IDs — flag [MINOR]

Status: draft
Scope: subsystem:ath12k file-pattern:drivers/net/wireless/ath/ath12k/ahb.c
Triggers:
- A new "generic" shared-state allocation function (e.g. an rproc_info allocator) for
  multi-device management is introduced in ath12k ahb.c
- The function initialises fields with hardware-specific constants such as
  `ATH12K_IPQ5332_USERPD_ID` or adds a comment naming a specific SoC (e.g. "IPQ5332
  Multi-UserPD Management: ...") to a global variable that is claimed to support any
  multi-UserPD system
- The corresponding hardware-variant probe switch-case (e.g. in wifi7/ahb.c) removes
  the per-SoC userpd_id assignment that was previously segregated there

Maintainer evidence:
- Jeff Johnson (ath12k maintainer) on [PATCH ath-next 1/6]
  <20260519061217.702484-1-aaradhana.sahu@oss.qualcomm.com> (2026-05-19): "if these are
  specific to ipq5332 then they should have ipq5332 in the names but if they are applicable
  to any multi UserPD systems we may have now or in the future then the specific references
  to IPQ5332 should be removed. generic code should be generic." Also flagged that the
  switch-case change in wifi7/ahb.c incorrectly removed IPQ5332-specific assignment from
  the hardware-variant block where it was intentionally segregated. Our automated review
  could not flag this because the series failed to apply (missed-by-us pattern).

Review action:
- Flag [MINOR] when a new shared-state allocator or global variable in ath12k ahb.c
  contains SoC-specific constant references (e.g. `ATH12K_IPQ5332_USERPD_ID`) inside
  code described as generic.
- If the struct or function is truly generic, suggest replacing hardware-specific
  constants with parameters passed in from the hardware-variant probe path.
- If the struct is IPQ5332-specific, suggest renaming accordingly (add "ipq5332" to
  the global/function name) and leaving the SoC-specific initialisation in the
  hardware-variant switch block in wifi7/ahb.c.

False-positive guards:
- Do not flag hardware-specific constants that appear only inside hardware-variant
  switch-case blocks (e.g. `case ATH12K_HW_IPQ5332_HW10:`) — per-SoC initialisation
  there is expected and correct.
- Do not flag if the function name already contains the SoC name (making it clearly
  non-generic).

Confidence: low
Last updated: 2026-05-26

### MEM-0142: reinit_completion() must precede the action that triggers the completion — race window if placed after the triggering call

Status: draft
Scope: general
Triggers:
- A patch calls `reinit_completion()` for a completion variable after initiating the
  asynchronous operation that is expected to complete it (e.g. after triggering spawn
  or issuing a command), rather than immediately before initiating that operation
- A subsequent `wait_for_completion_timeout()` waits on the same completion
- There is a window between the triggering call returning and the reinit_completion()
  call during which the completion event could fire and be lost

Maintainer evidence:
- Patchwise AI reviewer (kernel@oss.qualcomm.com, 2026-05-19) on [PATCH ath-next 6/6]
  <20260519061217.702484-1-aaradhana.sahu@oss.qualcomm.com>: "`reinit_completion` for
  `userpd_ready` must be called before triggering the spawn sequence, not after waiting
  for spawn. If the ready IRQ fires between the spawn wait returning and this
  `reinit_completion` call, the completion is cleared and the subsequent
  `wait_for_completion_timeout` will time out spuriously." One AI-reviewer data point
  only; no human maintainer confirmation yet. Our automated review did not flag this
  because the series failed to apply (missed-by-us pattern).

Review action:
- Flag [BUG] when `reinit_completion()` is called after an asynchronous operation that
  could trigger the same completion has already been initiated, rather than immediately
  before initiating it.
- The safe order is: (1) reinit_completion(), (2) initiate the async operation,
  (3) wait_for_completion_timeout(). Any deviation from this order creates a lost-wakeup
  race.
- Check multi-step recovery sequences (e.g. spawn \u2192 ready) to ensure each completion
  is reset before the step that fires it, not after the preceding step completes.

False-positive guards:
- Do not flag if the completion is only ever used in a single-threaded context where the
  event source cannot fire concurrently.
- Do not flag reinit_completion() called at driver initialisation time before any async
  operation has been started.
- AI-reviewer evidence only; apply as draft and upgrade to active only after a human
  maintainer confirms the same pattern.

Confidence: low
Last updated: 2026-05-26

### MEM-0143: ICC bandwidth vote acquired in probe must be released on all subsequent error paths

Status: draft
Scope: general
Triggers:
- A driver acquires an ICC (interconnect) bandwidth path during probe via
  devm_of_icc_get() + icc_set_bw() before a hardware step that can fail
  (e.g., reading ID registers, clk_bulk_enable)
- One or more error-return paths after the icc_set_bw() call return without
  first invoking the matching ICC disable function

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-11) on patch 1/3
  "iommu/arm-smmu: Add interconnect bandwidth voting support": flagged that
  arm_smmu_device_cfg_probe() failure after arm_smmu_icc_enable() leaves the
  active ICC vote unreleased; arm_smmu_icc_disable() is never called on that
  path. Our automated review caught the runtime_resume ICC concern but missed
  the probe error path -- a missed-by-us finding.

Review action:
- Flag [CONCERN] when icc_set_bw() is called during probe and any subsequent
  error-return path does not invoke the matching ICC disable before returning.
- Cross-check all return-error paths after the icc_set_bw() call to the end of
  the probe function; each must call the disable or the vote is leaked.
- Apply the same audit to any sequenced resource (clock, ICC, regulator): if
  step N+1 fails, steps 1..N must be rolled back.

False-positive guards:
- Do not flag if icc_set_bw(path, 0, 0) is called on the error path, which
  releases the vote.
- Do not flag if a devm cleanup action registered immediately after the enable
  call correctly releases the vote on error unwind.

Confidence: low
Last updated: 2026-05-26

### MEM-0146: ndo_start_xmit runs in atomic/softirq context — use pm_runtime_get() not pm_runtime_resume_and_get()

Status: draft
Scope: subsystem:net
Triggers:
- A review recommends replacing pm_runtime_get() with pm_runtime_resume_and_get() inside
  a netdev ndo_start_xmit (ndo_xmit) callback
- The function signature is netdev_tx_t foo_ndo_xmit(struct sk_buff *, struct net_device *)

Maintainer evidence:
- Konrad Dybcio (2026-05-08) on patch 3/6 of the MHI runtime PM series suggested
  pm_runtime_resume_and_get() for the TX path. Krishna Chaitanya (author) responded:
  "mhi_ndo_xmit() can be called from atomic context, due to this reason I was calling only
  pm_runtime_get()." Confirms async pm_runtime_get() is intentional in ndo_xmit.

Review action:
- Do NOT flag pm_runtime_get() in an ndo_start_xmit callback as wrong; ndo_xmit may be
  called from softirq/atomic context where sleeping (which pm_runtime_resume_and_get() may
  do) is forbidden. The async form is intentional.
- Still flag [BUG] if pm_runtime_get() fails and the error path does not call
  pm_runtime_put_noidle() to balance the already-incremented usage count.

False-positive guards:
- Applies only to ndo_start_xmit callbacks; workqueues, probe, and open/stop paths are not
  atomic and should still prefer pm_runtime_resume_and_get().

Confidence: low
Last updated: 2026-05-26

### MEM-0147: netdev_tx_t must return NETDEV_TX_OK or NETDEV_TX_BUSY, never a negative errno

Status: draft
Scope: subsystem:net
Triggers:
- A function with return type netdev_tx_t returns a negative errno value (e.g. from
  pm_runtime_get(), mhi_queue_skb(), or another helper)
- The function is registered as ndo_start_xmit in a net_device_ops struct

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-06) on patch 5/6 of the MHI runtime
  PM series: "mhi_mbim_ndo_xmit() is declared netdev_tx_t. Returning a raw negative errno is
  wrong; netdev_tx_t values are NETDEV_TX_OK, NETDEV_TX_BUSY, etc." Our automated review
  independently flagged the same issue as [BUG], confirming from two sources.

Review action:
- Flag [BUG] when an ndo_start_xmit callback returns a negative errno.
- On an error path: free the SKB with dev_kfree_skb_any(), update a drop counter, and
  return NETDEV_TX_OK. Verify the SKB is consumed on every error path.

False-positive guards:
- Do not flag NETDEV_TX_OK (0) or NETDEV_TX_BUSY (1) -- these are correct.
- Do not apply to internal helpers that are not ndo_start_xmit themselves.

Confidence: low
Last updated: 2026-05-26

### MEM-0152: Atomic lifecycle counter — decrement must not execute on paths where increment was never reached — flag [BUG]

Status: draft
Scope: general file-pattern:drivers/
Triggers:
- A driver uses an atomic_t counter to track active instances (e.g. num_userpd_active)
- atomic_inc is placed at the successful end of a power-up/start function
- atomic_dec is placed unconditionally at the end of the corresponding power-down/stop
  function
- Either: (a) power-down is callable on an error path that runs before power-up's
  atomic_inc is reached, OR (b) power-down has an early-return that bypasses the
  atomic_dec after atomic_inc already ran

Maintainer evidence:
- Rameshkumar Sundaram on [PATCH ath-next v5 6/7] wifi: ath12k: add support to load shared
  firmware (2026-05-21): "ath12k_ahb_remove() calls ath12k_ahb_power_down() on the QMI-fail
  path. If failure happens before the increment but power_down() reaches the decrement, the
  counter can go negative. A negative atomic still reads as nonzero, so
  ath12k_core_check_active_userpd() will think a UserPD is active and can skip shared
  firmware/root PD shutdown." Our automated review missed this (missed-by-us).
- Baochen Qiang on the same patch: when wait_for_completion_timeout returns 0 in power_down,
  the function returns early, skipping atomic_dec; num_userpd_active is permanently
  incremented, blocking all future shared firmware/root PD shutdown. Second missed
  error-path asymmetry.

Review action:
- When a patch introduces an atomic_t lifecycle counter with paired inc/dec in power-up
  and power-down functions, trace all power-down call sites and all early-return paths
  within power-down:
  1. Verify the decrement is not reached unless the increment was previously executed for
     that instance (guard against underflow / negative counter from error-path calls).
  2. Verify every early-return in power-down either skips the decrement (if increment was
     not reached) or calls it before returning (guard against counter-stuck-high leak).
- Flag [BUG] for each asymmetric case found.

False-positive guards:
- Do not flag if power-down is only callable after the increment is guaranteed by a state
  machine or serialization that prevents premature power-down calls.
- Do not flag symmetrically balanced error paths where both increment and decrement are
  consistently skipped on failure (the counter is never touched on the error path at all).

Confidence: medium
Last updated: 2026-05-27

### MEM-0155: QMP PHY register offset headers - no leading zeros for sub-0x100 hex values

Status: draft
Scope: file-pattern:drivers/phy/qualcomm/phy-qcom-qmp-qserdes-*.h
Triggers:
- A new QMP PHY register offset header defines macro values with unnecessary leading zeros
  for hex numbers below 0x100 (e.g. 0x03c instead of 0x3c, 0x084 instead of 0x84)
- All other versioned txrx and COM headers in the same directory omit the leading zero

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-02) on patch 05/12
  "phy: qcom-qmp: qserdes-txrx: Add v10 register offsets": multiple sub-0x100 offsets
  used unnecessary leading zeros (e.g. 0x03c, 0x084, 0x08c, 0x090, 0x094, 0x0e4).
  Every other txrx header in this directory, as well as the v10 COM header, omits the
  leading zero. Our automated review did not flag this style inconsistency (missed-by-us).

Review action:
- Flag [NIT] when a new QMP PHY register offset header uses leading zeros for hex values
  less than 0x100 (e.g. 0x03c should be 0x3c).
- Cross-check at least two sibling versioned headers in the same directory to confirm
  the no-leading-zero convention before flagging.

False-positive guards:
- Do not flag hex values >= 0x100; those cannot have a shorter non-leading-zero form.
- Do not flag if sibling headers in the same directory use leading zeros (convention may
  have changed); always confirm from current siblings first.

Confidence: low
Last updated: 2026-05-26

### MEM-0157: Qcom automotive SoC new series — cover letter must clarify if SoC is new silicon or a VM partition of existing hardware

Status: draft
Scope: subsystem:arm/qcom file-pattern:arch/arm64/boot/dts/qcom/sa*.dtsi
Triggers:
- A new DT series introduces a Qcom SA-family automotive SoC (e.g. SA7255P, SA7775P)
  whose hardware codename or product family closely matches an existing DT-supported SoC
  (e.g. SA8255P / MonacoAU)
- The cover letter or commit body does not clarify whether this is (a) new silicon, (b) the
  same chip running a different hypervisor VM partition (e.g. GearVM vs. Android VM), or
  (c) a different firmware/OS stack on the same hardware

Maintainer evidence:
- Konrad Dybcio on SA7255P SoC support series (linux-arm-msm, 2026-05-22): immediately asked
  "Is this platform just MonacoAU, running GEARVM?" The author confirmed SA7255P is MonacoAU
  (SA8255P-family hardware) running GearVM. Neither the cover letter nor any patch body
  explained this relationship. The automated review did not flag the missing clarification
  (missed-by-us). Single data point.

Review action:
- When a new Qcom SA-family automotive SoC DT series arrives, check whether the cover letter
  explains: (a) the hardware generation/codename (e.g. MonacoAU, MonacoLE), (b) whether it
  is the same silicon as an existing DT-supported SoC, and (c) if a VM/hypervisor
  configuration (e.g. GearVM, ADAS-VM) differentiates this product name from an existing one.
- Flag [CONCERN] when the new SoC appears to share a hardware codename with an existing
  DT-supported SoC and no clarification is provided in the cover letter or commit body.

False-positive guards:
- Do not flag if the cover letter or patch body already states the hardware identity,
  platform codename, and VM/OS configuration context.
- Do not apply to non-automotive Qcom SoC series (SM/SC families) where VM partition
  naming is not a standard product differentiation mechanism.
- Single maintainer data point; apply as draft with low confidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0158: Macro wrapper for implicit THIS_MODULE — use descriptive suffix, not `__` prefix, for the exported implementation

Status: draft
Scope: general
Triggers:
- A public function is renamed with a leading `__` prefix and exposed via a
  `#define name(args) __name(args, THIS_MODULE)` macro wrapper
- The renamed implementation is still EXPORT_SYMBOL_GPL'd under the `__` name
- The `__` prefix conventionally signals internal/private in Linux kernel code

Maintainer evidence:
- Leo Yan (ARM/Coresight maintainer) on patch 3/4 of
  20260518-acpi_mod_name-v5 (coresight: pass THIS_MODULE implicitly through
  a macro): requested renaming `__coresight_init_driver` to
  `coresight_init_driver_with_owner` because the `__` prefix is for
  internal functions, not for exported symbols. Also requested the function
  prototype appear in the header before the macro definition.

Review action:
- Flag [MINOR] when an EXPORT_SYMBOL_GPL'd function is given a `__` prefix
  as the hidden implementation of a THIS_MODULE macro wrapper.
- Suggest a descriptive suffix instead (e.g. `_with_owner`, `_full`, or
  `_impl`) rather than a `__` prefix.
- Also flag if the macro definition appears in the header before the function
  prototype; the prototype must come first.

False-positive guards:
- Do not flag `__` prefix on truly internal (non-exported) helpers that are
  not part of any public macro API.
- Do not flag if the maintainer has already accepted the `__` naming
  convention for this specific function in the same thread.

Confidence: low
Last updated: 2026-05-26

### MEM-0160: `pure_initcall` for early infrastructure — confirm no other `pure_initcall` user accesses the resource before raising link-order concern

Status: draft
Scope: general
Triggers:
- A patch moves infrastructure initialisation (e.g. kset_create_and_add())
  from a higher-level initcall (e.g. subsys_initcall) to pure_initcall so
  built-in drivers can use the resource from core_initcall or later
- A review concern flags link-order fragility: multiple pure_initcall
  registrations execute at level 0 in link order, so any existing
  pure_initcall driver that accesses the resource could NULL-deref

Maintainer evidence:
- Gary Guo and Petr Pavlu on 20260518-acpi_mod_name-v5 patch 2/4: both
  accepted pure_initcall for param_sysfs_init(). Petr confirmed sysfs and
  slab are available at that point. The sole in-tree pure_initcall driver
  registration (tegra CBB) was demoted to core_initcall by patch 1/4 of the
  same series, eliminating the ordering hazard. Our review raised [CONCERN]
  about link-order fragility; this was a partial false positive because
  patch 1/4 had already resolved the only known ordering conflict.

Review action:
- Before raising [CONCERN] about link-order fragility in a pure_initcall
  infrastructure patch, search the tree for other pure_initcall() users
  that dereference the resource being initialized.
- If the series demotes all such users (or none exist in-tree), reduce
  severity to [NIT] or omit the link-order finding entirely.
- Always suggest a code comment update when the initcall level changes
  (see MEM-0159).

False-positive guards:
- Still raise [CONCERN] if a known pure_initcall user that accesses the
  resource is NOT demoted by the current series.
- Do not suppress the comment-update request; it remains valid regardless.

Confidence: low
Last updated: 2026-05-26

### MEM-0163: reboot-mode DTS nodes must include a compatible property for driver to bind

Status: draft
Scope: general
Triggers:
- A DTS/DTSI patch adds a "reboot-mode" child node (for syscon-reboot-mode, nvmem-reboot-mode,
  psci-reboot-mode, or any reboot-mode variant) without a compatible property
- The commit body or binding description does not explain which driver will bind to the node

Maintainer evidence:
- Multiple AI reviews (Patchwise/Claude, kernel@oss.qualcomm.com, 2026-04-23) on the Qualcomm
  PSCI reboot-mode DTS series (patches 10-13/13): all reviewed DTS patches added "reboot-mode"
  child nodes without a compatible property. Without compatible, no driver will bind to the node;
  the node is silently inert. All existing reboot-mode nodes in the tree (syscon-reboot-mode,
  nvmem-reboot-mode) require a compatible property.

Review action:
- Flag [CONCERN] when a DTS "reboot-mode" node lacks a compatible property.
- Note that the reboot-mode subsystem dispatches based on compatible (e.g.,
  "syscon-reboot-mode", "nvmem-reboot-mode"); without it, no driver binds.

False-positive guards:
- Do not flag if the binding under which the reboot-mode node lives explicitly documents that
  no compatible is required (some future firmware-node-based registration paths may differ).
- Do not flag if a compatible is present but just differs from well-known values.

Confidence: low
Last updated: 2026-05-26

### MEM-0164: MFD cell fwnode assignment must come after mfd_acpi_add_device() not before

Status: draft
Scope: file-pattern:drivers/mfd/mfd-core.c
Triggers:
- A patch extends mfd-core.c to set cell->fwnode on a new platform device before calling
  mfd_acpi_add_device()
- The code contains a comment such as "ACPI fwnode should be primary so keep this block before
  mfd_acpi_add_device()" and a guard like "if (!pdev->dev.fwnode && cell->fwnode)"

Maintainer evidence:
- AI review (Patchwise/Claude, kernel@oss.qualcomm.com, 2026-04-23) on patch 8/13
  "mfd: core: Add firmware-node support to MFD cells": identified that mfd_acpi_add_device()
  calls set_primary_fwnode() unconditionally when a parent ACPI device exists, overwriting any
  fwnode set in a preceding block. The !pdev->dev.fwnode guard does not protect against this
  because the ACPI call happens afterwards. The block must be placed AFTER mfd_acpi_add_device()
  so the guard correctly skips assignment when ACPI has already populated the fwnode.

Review action:
- Flag [BUG] when a block that conditionally sets device_set_node() on an MFD child device runs
  BEFORE mfd_acpi_add_device(); mfd_acpi_add_device() will silently overwrite it.
- The correct ordering is: call mfd_acpi_add_device() first, then conditionally set fwnode only
  if !pdev->dev.fwnode (i.e. ACPI did not provide one).

False-positive guards:
- Do not flag if the block intentionally runs after mfd_acpi_add_device().
- Do not flag on non-ACPI-capable systems where mfd_acpi_add_device() is a no-op.

Confidence: low
Last updated: 2026-05-26

### MEM-0165: reboot-mode mode-* DT properties must be single u32; of_property_read_u32() ignores subsequent cells

Status: draft
Scope: file-pattern:drivers/power/reset/reboot-mode.c
Triggers:
- A DTS patch defines reboot-mode mode-* properties with two or more u32 cells
  (e.g., "mode-bootloader = <0x80010001 0x2>;" or "mode-edl = <0x80000000 0x1>;")
- The consuming driver uses of_property_read_u32() or device_property_read_u32_array()
  with count=1 to read the property

Maintainer evidence:
- Multiple AI reviews (Patchwise/Claude, kernel@oss.qualcomm.com, 2026-04-23) on the Qualcomm
  PSCI reboot-mode DTS series (patches 10-13/13): reboot_mode_register() calls
  of_property_read_u32() which reads only the first cell; the second cell is silently ignored.
  If the intent is to pass two arguments to SYSTEM_RESET2 (reset_type and cookie), the driver
  must be updated to handle the two-cell format and the binding must document it.

Review action:
- Flag [CONCERN] when a reboot-mode node uses two-cell mode-* property values and the driver
  reads them with of_property_read_u32() (single-cell read). The second cell is silently dropped.
- Either: (a) use single u32 values in DTS, or (b) update the driver and binding to handle
  multi-cell mode-* properties.

False-positive guards:
- Do not flag single-cell mode-* values (e.g., "mode-normal = <0>;") - these are correct.
- Do not flag if the driver has been updated in the same series to read multi-cell values.

Confidence: low
Last updated: 2026-05-26

### MEM-0173: New pci/pwrctrl driver for named endpoint chip -- check for parallel series by other authors

Status: draft
Scope: subsystem:pci/pwrctrl file-pattern:drivers/pci/pwrctrl/*.c
Triggers:
- A patch adds a new driver under drivers/pci/pwrctrl/ for a named third-party
  endpoint chip (e.g., TC9563)
- The driver introduces new exported API for endpoint power-enable or reset control

Maintainer evidence:
- Konrad Dybcio on patch 06/10 of the Shikra PCIe series (linux-arm-msm,
  2026-05-25): pointed to a parallel TC9563 endpoint power/reset series by
  elder@riscstar.com posted 2026-05-01
  (Message-ID: 20260501155421.3329862-10-elder@riscstar.com) -- "Please be
  aware of this parallel effort." The Qualcomm series was submitted 2026-05-22,
  three weeks after the parallel series. Our automated review did not flag the
  overlap (missed-by-us).

Review action:
- Flag [NIT] when a new pci/pwrctrl driver for a named chip is submitted:
  ask the author to confirm awareness of any in-flight series adding support
  for the same chip on the PCI mailing list.
- Note that pci/pwrctrl is a recently introduced subsystem where multiple
  vendors may independently submit competing drivers for common endpoint chips.

False-positive guards:
- Do not flag when the cover letter explicitly names a parallel series and
  describes coordination (e.g., "building on top of" or "supersedes").
- Do not flag a series that is itself a version bump (v2+) of an already-posted
  series -- the parallel-work check was the author's responsibility at v1.
- Do not apply outside drivers/pci/pwrctrl/ without additional evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0177: New kernel bus_type .dma_configure must call iommu_device_use_default_domain() and provide .dma_cleanup

Status: draft
Scope: general
Triggers:
- A patch introduces a new struct bus_type with a .dma_configure callback
- The .dma_configure implementation calls of_dma_configure_id() (or
  of_dma_configure()) but does not call iommu_device_use_default_domain()
  for the driver-bound code path
- The bus_type has no .dma_cleanup callback to call
  iommu_device_unuse_default_domain()

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-21) on patch 2/5
  "media: qcom: venus: introduce a bus for Venus VPU sub-devices":
  venus_vpu_bus_dma_configure() called of_dma_configure_id() but omitted
  iommu_device_use_default_domain(), unlike all other DMA-capable bus
  implementations. The reviewer noted: "Devices on this bus can then use
  the DMA API without claiming the IOMMU default domain." Suggested adding
  iommu_device_use_default_domain() for the driver-bound path and a
  .dma_cleanup callback calling iommu_device_unuse_default_domain(). Our
  automated review did not flag this (missed-by-us).

Review action:
- When a new bus_type provides .dma_configure, verify:
  (1) the callback calls iommu_device_use_default_domain() after configuring
      the device (for the driver-bind path); and
  (2) the bus_type also provides a .dma_cleanup callback that calls
      iommu_device_unuse_default_domain().
- Flag [CONCERN] when either is missing; devices on the bus may use the DMA
  API without a properly claimed IOMMU default domain, risking silent
  misconfiguration.
- Cross-check at least one other in-tree bus_type (e.g., platform_bus_type)
  to confirm the expected pattern.

False-positive guards:
- Do not flag if the bus type is explicitly not IOMMU-mapped (e.g., a
  non-DMA-capable bus or a bus where all IOMMU mappings are managed externally).
- Do not flag if the commit body explains why iommu_device_use_default_domain()
  is not needed (e.g., the bus devices are not bound to drivers via the
  driver-core bind path).
- One AI-reviewer data point only; treat as draft.

Confidence: low
Last updated: 2026-05-26

### MEM-0179: `BIT(n)` preferred over `GENMASK(n,n)` for single-bit driver config fields --- flag [NIT]

Status: draft
Scope: general
Triggers:
- A driver config struct, irqchip descriptor, or hardware register definition uses
  GENMASK(n, n) to describe a single-bit field (start bit equals end bit)
- BIT(n) would express the same mask more clearly

Maintainer evidence:
- Stephan Gerhold on patch 5/8 of the qcom-pdc pass-through mode series
  (linux-arm-msm, 2026-05-26): "BIT(5) / BIT(4) would be clearer here in my opinion"
  for pdc_cfg_v3_2.gpio_irq_sts = GENMASK(5,5) and
  pdc_cfg_v3_2.gpio_irq_mask = GENMASK(4,4).

Review action:
- Flag [NIT] when GENMASK(n, n) is used where BIT(n) would be equivalent and clearer.
- Suggest replacing GENMASK(n, n) with BIT(n).

False-positive guards:
- Do not flag GENMASK(high, low) where high != low (multi-bit fields).
- Do not flag existing code not touched by the patch; only flag new or modified
  definitions introduced in the diff.

Confidence: low
Last updated: 2026-05-26

### MEM-0180: qcom-pdc multi-mode series --- cover letter must document test configurations and results

Status: draft
Scope: subsystem:irqchip file-pattern:drivers/irqchip/qcom-pdc.c
Triggers:
- A series modifies drivers/irqchip/qcom-pdc.c in a way that changes the PDC
  operational mode (e.g. pass-through vs secondary controller mode)
- The change affects multiple boards or firmware versions with different mode
  configurations
- The cover letter mentions hardware testing only in general terms without stating
  which configurations were tested or what test tool was used

Maintainer evidence:
- Stephan Gerhold on cover letter of the x1e80100 PDC wake GPIO v2 series
  (linux-arm-msm, 2026-05-26): "Tested how? I recommend testing with the
  tlmm-test module Bjorn added, in all supported configurations, to make sure
  you don't introduce regressions for one of them. It would be also good to
  provide the test results here in the cover letter."

Review action:
- Flag [CONCERN] when a qcom-pdc mode-changing series does not document in the
  cover letter: (a) the specific boards/firmware versions tested, (b) the test
  tool used (e.g. tlmm-test), and (c) a summary of pass/fail results across
  configurations.
- Suggest adding a "Testing" section to the cover letter listing each tested
  configuration and its result.

False-positive guards:
- Do not flag if the cover letter already names specific boards, firmware builds,
  and a test tool with results.
- Do not flag patches that do not change PDC mode selection or irq enable logic.

Confidence: low
Last updated: 2026-05-26

### MEM-0181: irqchip register read-modify-write on a field shared with another irqchip path must hold the chip lock

Status: draft
Scope: subsystem:irqchip file-pattern:drivers/irqchip/qcom-pdc.c
Triggers:
- A new irqchip function does a read-modify-write on a per-interrupt config register
  (e.g. irq_cfg_reg) that also has fields written by another irqchip operation
  (e.g. set_type)
- The new function does not acquire the chip's raw_spin_lock before the RMW sequence
- Two CPUs could race on the same register: one writing the enable or type field,
  the other writing a gpio_status or gpio_mask field, causing a lost write

Maintainer evidence:
- Stephan Gerhold on patch 5/8 (linux-arm-msm, 2026-05-26): "Is this guaranteed to be
  called sequentially, i.e. not in parallel on another CPU? Otherwise, you need to add
  the lock here to make sure the read-modify-write doesn't race with another CPU. Note
  that since the irq_cfg_reg is also used in qcom_pdc_gic_set_type() it would be safest
  to add the lock there as well."
- Stephan Gerhold on patch 3/8 (2026-05-26): "pdc_enable_intr_cfg() is still a
  read-modify-write. If two CPUs read IRQ_i_CFG at the same time and modify different
  bits then write back the modified register one of the modifications will get lost."

Review action:
- Flag [BUG] when a new irqchip function performs a read-modify-write on a register
  whose fields are also updated by another irqchip callback, without holding the
  chip's existing spin lock.
- Check whether IRQCHIP_SET_TYPE_MASKED already serializes set_type with other
  irqchip operations; even so, concurrent multi-CPU access to different fields of the
  same register is still a race.
- Recommend a shared helper (e.g. pdc_update_irq_cfg()) that holds the lock and
  performs the RMW atomically for all callers of the same register.

False-positive guards:
- Do not flag functions that already acquire the chip spin lock before the RMW.
- Do not flag if the register fields modified are strictly disjoint from all other
  callback paths AND each field is only ever accessed by one code path.
- Applies to drivers/irqchip/qcom-pdc.c; for other irqchip drivers, require
  independent confirming evidence before raising as [BUG].

Confidence: low
Last updated: 2026-05-26

### MEM-0182: Function pointer in driver struct assigned the same concrete function on all paths --- justify or remove

Status: draft
Scope: general
Triggers:
- A patch adds one or more function pointer fields to a driver private struct
- Every probe path (or all branches of probe) assigns the same concrete function to
  those pointers --- no variant implementation is conditionally assigned
- The commit message or code contains no comment explaining a future differentiation
  plan

Maintainer evidence:
- Stephan Gerhold on patch 5/8 of the qcom-pdc series (linux-arm-msm, 2026-05-26):
  "What is the purpose of these function pointers if you always assign the same
  function?" for pdc->unmask_gpio = pdc_unmask_gpio_cfg and
  pdc->clear_gpio = pdc_clear_gpio_cfg unconditionally assigned in probe.

Review action:
- Flag [MINOR] when new function pointers are added to a struct and all call sites
  assign the same concrete implementation with no conditional variant.
- Suggest either: (a) removing the indirection and calling the function directly,
  or (b) adding a code comment explaining what future variant is planned for a
  named platform or series.

False-positive guards:
- Do not flag function pointers that are conditionally assigned different functions
  based on hardware version, compatible string, or runtime detection --- even if only
  one variant exists initially.
- Do not flag ops structs that are part of a published kernel API or subsystem
  interface (e.g. irq_chip, platform_driver) --- those slots exist by design.
- Do not flag if a code comment or cover letter describes a second variant planned
  for a named future platform.

Confidence: low
Last updated: 2026-05-26

### MEM-0184: perf cs-etm state machine extension --- new packet type case must call cs_etm__packet_swap() for correct boundary tracking

Status: draft
Scope: subsystem:perf file-pattern:tools/perf/util/cs-etm.c
Triggers:
- A patch adds a new case to `cs_etm__process_traceid_queue()` for a new packet type
- The new case breaks out without calling `cs_etm__packet_swap()`, unlike the
  `CS_ETM_RANGE` case which does
- A downstream boundary check in `cs_etm__sample()` tests `prev_packet->sample_type`
  for the new type

Maintainer evidence:
- Sashiko AI reviewer (sashiko-bot@kernel.org, 2026-05-26) on patch 1/2 of
  20260526-james-cs-context-tracking-fix-v1-0 (perf cs-etm): the `CS_ETM_CONTEXT`
  case never calls `cs_etm__packet_swap()`, so `prev_packet` never becomes a CONTEXT
  packet, making the boundary check in `cs_etm__sample()` dead code and preventing
  context packets from ever acting as branch sample boundaries. Rated [High].
  Our automated review found the dead check as [MINOR] but missed the root cause and
  the correct fix direction (add the swap; fix helper functions).
- Same review: `cs_etm__last_executed_instr()` and `cs_etm__copy_insn()` do not handle
  `CS_ETM_CONTEXT` packets; if context packets were correctly swapped into `prev_packet`
  they would return `CS_ETM_INVAL_ADDR` and risk invalid memory reads. Missed-by-us.
- Arnaldo Carvalho de Melo (perf maintainer, 2026-05-29): forwarded the Sashiko review
  to the author with "some looks legitimate, wdyt?"; James Clark acknowledged "there
  will definitely be a v2." Partial human endorsement that the root-cause analysis is
  correct.

Review action:
- When a patch adds a new case to `cs_etm__process_traceid_queue()`, verify whether
  the new packet type is intended to act as a branch sample boundary.
- If yes, confirm the new case calls `cs_etm__packet_swap()`; flag [MINOR] if it does not.
- Flag any `prev_packet->sample_type == NEW_TYPE` check in `cs_etm__sample()` as dead
  code if the new case never calls `cs_etm__packet_swap()`.
- Also verify that `cs_etm__last_executed_instr()` and `cs_etm__copy_insn()` handle the
  new packet type before it is added to the boundary check.

False-positive guards:
- Do not flag new cases that are explicitly non-boundary events (e.g. ancillary metadata
  packets not intended to delimit samples).
- Do not flag if the intent is confirmed to not generate branch boundaries for the type.

Confidence: low
Last updated: 2026-05-30

### MEM-0186: qcom GCC driver — trivial reset/clock omission from original series draws maintainer question

Status: draft
Scope: subsystem:clk/qcom file-pattern:drivers/clk/qcom/gcc-*.c
Triggers:
- A series adds 1–3 reset or clock entries to a qcom GCC driver introduced by a stated prerequisite series that has not yet merged
- The commit body or cover letter omits any explanation of why the resource was not included in the original driver series

Maintainer evidence:
- Dmitry Baryshkov on patch 2/2 of 20260526-shikra-gcc-usb-resets-v1-0 (clk: qcom: gcc-shikra: Add USB3 DP PHY reset, linux-arm-msm, 2026-05-26): "Why was it not a part of the original submission?" — a single reset entry (GCC_USB3_DP_PHY_PRIM_BCR) was sent as a separate 2-patch series rather than in the still-pending Shikra GCC prerequisite series. He gave Reviewed-by after; advisory, not blocking.

Review action:
- Flag [NIT] when a qcom GCC driver follow-up series adds only 1–3 clock or reset entries to a driver whose prerequisite series has not yet merged, and gives no explanation for the omission.
- Suggest adding a cover-letter note explaining why the resource was not in the original series (e.g., discovered later, firmware dependency, missed during initial development).

False-positive guards:
- Do not flag if the commit body or cover letter already explains why the resource was omitted.
- Do not flag if the prerequisite driver series merged more than one kernel cycle ago; incremental additions to an established driver are normal.
- Do not flag if the follow-up series adds substantial new functionality beyond a trivially small resource entry.
- Single data point; treat as draft and apply [NIT] only.

Confidence: low
Last updated: 2026-05-27

### MEM-0187: qcom-pcie legacy-binding driver workaround — maintainer requests DT migration instead

Status: draft
Scope: subsystem:pci file-pattern:drivers/pci/controller/dwc/pcie-qcom.c
Triggers:
- A patch adds a driver workaround (e.g. skipping a duplicate GPIO or resource
  acquisition) specifically because a named platform still uses the legacy DT
  binding rather than the current non-legacy binding
- The commit body explains the fix is needed "on platforms such as <X>" that
  use the legacy path

Maintainer evidence:
- Bjorn Andersson on "PCI: qcom: avoid duplicate PERST# GPIO acquisition in
  legacy path" (linux-pci, 2026-05-26): "Please send patches to update IPQ5424
  to the non-legacy binding." The patch removed the duplicate GPIO acquisition
  in the legacy path because IPQ5424 still described both PERST# and PHY under
  the RC node. Bjorn rejected the driver workaround and asked for the proper
  fix: migrate the IPQ5424 DT to the non-legacy binding. Our automated review
  gave READY TO APPLY without flagging the approach concern (missed-by-us).

Review action:
- Flag [CONCERN] when a driver patch works around a conflict caused by a
  specific platform still using the legacy DT binding, rather than migrating
  that platform to the current binding.
- Ask: "Would a DT update for <platform> to the non-legacy binding be
  feasible? The preferred fix is to migrate the DT rather than add a driver
  workaround to the legacy path."
- Suggest a companion patch (or separate series) updating the affected
  platform DT to the non-legacy binding.

False-positive guards:
- Do not flag if the commit body or cover letter already explains why DT
  migration is infeasible (e.g. upstream ABI constraint, firmware dependency,
  or the legacy path is preserved for good reason).
- Do not flag if the patch removes the legacy binding path entirely rather
  than adding a workaround to it.
- Do not apply outside pcie-qcom without additional confirming evidence.
- Single data point; treat as draft.

Confidence: low
Last updated: 2026-05-27

### MEM-0188: dev_warn() in recursive DT-traversal function causes log spam — flag [NIT], suggest dev_warn_once()

Status: draft
Scope: subsystem:pci file-pattern:drivers/pci/controller/dwc/pcie-qcom.c
Triggers:
- A dev_warn() (or dev_err/dev_info) is added inside a function that
  recursively calls itself for each child DT node
- The warning condition depends on a struct field set before the recursion
  begins, so the condition evaluates true on every recursive call — once
  per descendant node

Maintainer evidence:
- Manivannan Sadhasivam on "PCI: qcom: avoid duplicate PERST# GPIO acquisition
  in legacy path" (linux-pci, 2026-05-26): "This will cause spat for each child
  node. So switched to dev_warn_once() and squashed this fix to the offending
  commit." dev_warn() was placed in qcom_pcie_parse_perst() which recurses over
  RP child nodes; pcie->reset is globally set so the warning fires per node.
  Our automated review noted this as [NIT] (confirmed; same finding independently
  raised by sashiko-bot).

Review action:
- Flag [NIT] when a dev_warn() is added inside a recursive DT-traversal function
  and the warning condition depends on a struct field set before the recursion,
  causing the message to log once per descendant.
- Suggest using dev_warn_once() to suppress duplicate log lines.

False-positive guards:
- Do not flag if the warning is only reachable on a non-recursive code path
  (e.g. an early-exit branch that returns before the recursive loop).
- Do not flag if each recursive call genuinely has an independent condition
  that can fire separately per node.
- Do not flag dev_dbg() — debug-level messages are filtered by default.

Confidence: low
Last updated: 2026-05-27

### MEM-0189: sdhci-msm ICE fields and probe code must be guarded by #ifdef CONFIG_MMC_CRYPTO

Status: draft
Scope: subsystem:mmc file-pattern:drivers/mmc/host/sdhci-msm.c
Triggers:
- A new struct field related to ICE (Inline Crypto Engine) is added to
  `sdhci_msm_host` without a `#ifdef CONFIG_MMC_CRYPTO` guard
- New ICE clock setup or ICE operational code is added to `sdhci_msm_probe()`
  (or other sdhci-msm functions) without a `#ifdef CONFIG_MMC_CRYPTO` guard

Maintainer evidence:
- Abhinaba Rakshit on "mmc: sdhci-msm: Add support to set ice clk rate"
  (Message-ID: 20260526074401.3363300-1-ram.gupta@oss.qualcomm.com,
  2026-05-26): both the new `struct clk *ice_clk` field in `sdhci_msm_host`
  and the ICE clock setup block in `sdhci_msm_probe()` should be guarded with
  `#ifdef CONFIG_MMC_CRYPTO`, consistent with the existing ICE instance and
  ICE-related code already inside that guard in the same file.

Review action:
- When reviewing sdhci-msm patches, flag [CONCERN] if any new struct field or
  function body code that is specific to ICE / inline-crypto is not enclosed in
  `#ifdef CONFIG_MMC_CRYPTO` / `#endif`, matching the pattern used for the
  existing ICE fields and operations in `sdhci_msm_host` and `sdhci_msm_probe`.
- Point to the existing guarded ICE block in the file as the precedent.

False-positive guards:
- Do not flag code that is genuinely needed regardless of crypto support (e.g.
  a clock needed for non-crypto data path).
- Do not flag if the whole function or struct definition is already inside a
  `#ifdef CONFIG_MMC_CRYPTO` block.

Confidence: low
Last updated: 2026-05-27

### MEM-0190: GPI DMA `gchan->config` must be accessed via protocol-discriminated cast, not raw byte offset

Status: draft
Scope: subsystem:dmaengine file-pattern:drivers/dma/qcom/gpi.c
Triggers:
- A patch reads a field from `gchan->config` by casting to `u8 *` and indexing
  by byte position (e.g. `((u8 *)gchan->config)[1]`) rather than casting to the
  correct protocol-specific struct type
- The GPI channel may carry I2C, SPI, or UART transfers; the same byte offset maps
  to different fields in each protocol's config struct

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-26) on patch 1/2
  "dmaengine: qcom-gpi: Add I2C High-Speed mode configuration support": flagged
  `u8 *config_flags = (u8 *)gchan->config; if (config_flags[1]) nr_tre++` as
  protocol-unsafe. Byte offset 1 of `gpi_i2c_config` is `set_config1`, but byte
  offset 1 of `gpi_spi_config` is `loopback_en` -- so the check incorrectly bumps
  `nr_tre` for SPI channels with loopback enabled. Patchwise: "Restrict this to
  QCOM_GPI_I2C and use struct gpi_i2c_config instead of indexing raw bytes."
  Our automated review independently raised the same [CONCERN] with the same fix
  direction (confirmed from two AI sources).
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-26) on v2 of the same
  patch (follow-up thread): "For SPI, byte 1 is loopback_en, so enabling SPI
  loopback incorrectly increases nr_tre and can make prep fail with 'not enough
  space in ring'." Describes the same bug; failure manifests as ring-space
  exhaustion in gpi_prep_slave_sg() for SPI channels with loopback enabled.
  Third independent AI-reviewer source confirming the concern.

Review action:
- Flag [CONCERN] when `gchan->config` is read via raw byte cast without first
  checking `gchan->protocol` (or equivalent discriminant) to confirm the channel type.
- Suggest: gate the access on `gchan->protocol == QCOM_GPI_I2C` (or the appropriate
  enum) and cast to the correct struct type (e.g. `const struct gpi_i2c_config *`).
- Also flag if `nr_tre` or ring-sizing decisions are made on the raw byte result without
  a protocol guard; for SPI, the overcount causes ring-space exhaustion in the DMA
  prepare call.

False-positive guards:
- Do not flag code that already gates the access behind a `gchan->protocol` check.
- Do not flag uses of `gchan->config` that cast to a specific, explicitly named struct
  type rather than using a raw byte pointer.

Confidence: low
Last updated: 2026-05-27

### MEM-0191: `geni_se_clk_freq_match` must use exact match when HS timing constants are pre-computed for a specific source frequency

Status: draft
Scope: subsystem:i2c file-pattern:drivers/i2c/busses/i2c-qcom-geni.c
Triggers:
- A patch calls `geni_se_clk_freq_match()` with the `exact` argument set to `false`
  (allows selecting a higher-than-requested clock rate)
- The HS mode timing counters (TCYCLE, TLOW, etc.) used elsewhere in the same function
  are hard-coded constants pre-computed for the requested source frequency

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-26) on patch 2/2
  "i2c: qcom-geni: Add support for I2C High-Speed mode": `geni_se_clk_freq_match(...,
  false)` allows a rate higher than 100 MHz to be selected. The HS timing values are
  fixed for a 100 MHz source, so this must require an exact match or derive the timing
  values from `freq_out`. Our automated review did not flag this (missed-by-us).
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-26) on v2 of the same patch
  (follow-up thread): "This must require an exact 100 MHz match. The HS timing values
  programmed above are hardcoded for 100 MHz, but exact=false allows a lower
  parent-table rate to be selected and then used with the wrong timings." Corroborates
  the exact-match requirement from a second AI reviewer source.

Review action:
- Flag [CONCERN] when `geni_se_clk_freq_match()` is called with `exact=false` and the
  caller subsequently uses hard-coded timing counters that were derived for a specific
  source frequency (e.g. TCYCLE=28 and TLOW=38 for 100 MHz I2C HS).
- Suggest either: (a) passing `true` for exact match so the selected frequency matches
  the pre-computed constants, or (b) computing timing values dynamically from the
  returned `freq_out` value.
- Verify that the returned `freq_out` is checked against the requested frequency when
  exact=false is intentional.

False-positive guards:
- Do not flag if the timing counters are computed from `freq_out` rather than being
  hard-coded constants.
- Do not flag non-HS clock selection paths where over-selection has no timing impact
  (e.g. frequency headroom is acceptable for the protocol in use).
- Two AI-reviewer data points; no human maintainer confirmation yet.

Confidence: low
Last updated: 2026-05-27

### MEM-0192: checkpatch TYPO_SPELLING false positive for "TRE" in GPI/GENI DMA code

Status: draft
Scope: subsystem:dmaengine file-pattern:drivers/dma/qcom/gpi.c
Triggers:
- checkpatch reports WARNING:TYPO_SPELLING on "TRE" or "tre" in GPI or GENI DMA drivers
- The flagged token is used as a domain abbreviation for Transfer Ring Element

Maintainer evidence:
- Patchwise static analysis (kernel@oss.qualcomm.com, 2026-05-26) on patch 1/2
  "dmaengine: qcom-gpi: Add I2C High-Speed mode configuration support": reported
  11 WARNING:TYPO_SPELLING hits for "TRE" and "tre" in comments and variable names.
- Patchwise static analysis (kernel@oss.qualcomm.com, 2026-05-26) on patch 2/2
  "i2c: qcom-geni: Add support for I2C High-Speed mode": reported 6 TYPO_SPELLING
  warnings for "TRE" in comments and the commit body.
  "TRE" stands for Transfer Ring Element -- the fundamental descriptor unit in Qualcomm
  GPI DMA hardware. Our automated checkpatch run reported 0 warnings on the same patches
  (checkpatch version sensitivity: the Patchwise tool uses a newer or stricter version).

Review action:
- Do NOT flag TYPO_SPELLING warnings for "TRE" or "tre" in GPI or GENI DMA source files
  or commit bodies. Transfer Ring Element is the standard domain term; it is not a
  misspelling of "TREE".
- If checkpatch reports this warning, suppress it and do not include it in the review.

False-positive guards:
- Do apply genuine TYPO_SPELLING fixes for other tokens in the same files if checkpatch
  flags them; only suppress the TRE/tre false positive specifically.
- If a human maintainer explicitly requests renaming TRE to a different term, defer
  to that preference.

Confidence: low
Last updated: 2026-05-27

### MEM-0193: Defensive NULL parameter guards in static internal driver functions are unwanted

Status: draft
Scope: general
Triggers:
- A static (file-scoped) driver function adds an `if (!param)` or `if (param)`
  guard on a pointer parameter to handle the NULL case defensively
- All call sites of the function are within the same compilation unit or driver
  file, so callers are fully visible and under the author's control
- The NULL path is not a legitimately valid argument value

Maintainer evidence:
- Daniel Lezcano (thermal/PM maintainer) on patch 1/2 of
  20260526-tsens_interrupt_wake_control-v1 (linux-pm, 2026-05-26): "You can
  remove this check, it is a static function called inside the driver which is
  supposed to know what it does (like not passing a NULL pointer parameter)."
  The author had added `else if (irq_num)` guard in static tsens_register_irq().
  Our automated review did not flag the defensive guard (missed-by-us).

Review action:
- Flag [NIT] when a static driver function adds a defensive NULL guard on a
  parameter where all callers are within the same file and the NULL path is
  not a legitimately valid optional-argument value.
- Suggest removing the guard with a note that file-scoped static functions
  are expected to be called with valid arguments by their in-file callers.

False-positive guards:
- Do not flag NULL guards in extern or exported functions; this entry applies
  only to `static` functions whose entire call graph is within one file.
- Do not flag if NULL is a legitimately valid argument value (e.g. an optional
  parameter where the caller may intentionally pass NULL for default behavior).
- Do not flag if the function is assigned to a function pointer and may be
  called from an external context.
- Single data point from one thermal maintainer; treat as draft.

Confidence: low
Last updated: 2026-05-27

### MEM-0194: `device_may_wakeup()` in PM suspend implies IRQ registration — redundant `irq_num > 0` guards rejected

Status: draft
Scope: general
Triggers:
- A PM suspend callback checks `device_may_wakeup(dev)` before calling
  `enable_irq_wake()` for IRQ numbers stored in the device struct at probe time
- The code additionally guards each `enable_irq_wake()` call with
  `if (priv->some_irq > 0)` inside the already-gated `device_may_wakeup()` block
- `device_init_wakeup(dev, true)` is called in probe only after all IRQs are
  successfully registered (probe returns an error immediately on IRQ failure)

Maintainer evidence:
- Daniel Lezcano (thermal/PM maintainer) on patch 1/2 of
  20260526-tsens_interrupt_wake_control-v1 (linux-pm, 2026-05-26): "Using the
  check on combined_irq / uplow_irq / crit_irq is not necessary because if the
  code goes after the device_may_wakeup() block, it is because interrupts are
  set." Also noted that if tsens_register_irq() fails, probe fails so
  suspend/resume cannot be reached with unregistered IRQs.
  Our review praised the `>0` guards as correct defensive programming
  (missed-by-us overpraise).

Review action:
- Flag [NIT] when `if (irq_num > 0)` guards appear inside a
  `device_may_wakeup()` block, if probe success is a prerequisite for
  `device_init_wakeup()` being called (coupling wakeup capability to IRQ
  registration).
- Do not praise such guards as good defensive programming when the design
  already guarantees IRQs are set whenever `device_may_wakeup()` returns true.

False-positive guards:
- Do not flag if `device_init_wakeup()` is called unconditionally in probe
  regardless of IRQ registration outcome (breaking the wakeup/IRQ coupling).
- Do not flag if IRQ numbers may legitimately be zero for some device
  configurations that can still succeed probe and reach suspend (optional IRQs).
- Single data point from one thermal maintainer; treat as draft.

Confidence: low
Last updated: 2026-05-27

### MEM-0195: GPI DMA new TRE type requires updating MAX_TRE and descriptor ring allocation

Status: draft
Scope: subsystem:dmaengine file-pattern:drivers/dma/qcom/gpi.c
Triggers:
- A patch adds a new TRE type (e.g. CONFIG1) to the GPI DMA TRE chain for a
  transfer (e.g. CONFIG0 + CONFIG1 + GO + DMA = 4 TREs for a non-multi I2C write)
- The patch increments nr_tre for the new TRE but does not update MAX_TRE or
  the `desc->tre[]` array size to accommodate the increased maximum TRE count

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-26) on patch 1/2
  "dmaengine: qcom-gpi: Add I2C High-Speed mode configuration support":
  "This can write past desc->tre because MAX_TRE is still 3; set_config +
  set_config1 + GO + DMA needs four TREs for a non-multi write." Our automated
  review did not flag this ring-size issue (missed-by-us).

Review action:
- Flag [CONCERN] when a GPI DMA patch adds a new TRE to the chain and nr_tre
  can reach a value exceeding MAX_TRE in the descriptor struct.
- Verify that the worst-case TRE count (all optional TREs present simultaneously)
  does not exceed the `desc->tre[]` array size.
- Suggest updating MAX_TRE (or the struct array size) to reflect the new maximum,
  and updating all size comments that document the TRE layout.

False-positive guards:
- Do not flag if the new TRE is mutually exclusive with an existing TRE so the
  total count cannot increase (e.g. replaces an existing TRE rather than adding).
- Do not flag if the patch already updates MAX_TRE or the array size accordingly.
- One AI-reviewer data point only; treat as draft.

Confidence: low
Last updated: 2026-05-27

### MEM-0196: i2c-qcom-geni — new I2C opcode must be added to all opcode condition guards, not only TRE construction

Status: draft
Scope: subsystem:i2c file-pattern:drivers/i2c/busses/i2c-qcom-geni.c
Triggers:
- A patch introduces a new I2C opcode (e.g. I2C_HS_WRITE alongside the existing
  I2C_WRITE, or I2C_HS_READ alongside I2C_READ)
- The new opcode is added to the TRE-construction block (e.g. `gpi_create_i2c_tre()`)
  but not to other conditions in the driver that gate behaviour on the existing opcode
  (e.g. the read-address-phase suppression guard in `geni_i2c_gpi()`)

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-26) on patch 2/2
  "i2c: qcom-geni: Add support for I2C High-Speed mode": "`geni_i2c_gpi()` only
  suppresses msg_idx_cnt increment for the read-address phase when op == I2C_WRITE,
  so passing I2C_HS_WRITE for a read message advances to the next message before
  the RX call. Include I2C_HS_WRITE in that condition." Our automated review did
  not flag this opcode-condition gap (missed-by-us).

Review action:
- When a patch adds a new I2C opcode, search the driver for every conditional that
  tests the existing standard opcode (e.g. `op == I2C_WRITE`, `op == I2C_READ`)
  and verify the new HS variant is also included where semantically equivalent.
- Flag [CONCERN] when a new opcode is omitted from a condition that controls
  multi-message sequencing, msg_idx advancement, or transfer phase gating.
- In particular, check `geni_i2c_gpi()` read-address-phase conditions when
  I2C_HS_WRITE is added alongside I2C_WRITE.

False-positive guards:
- Do not flag if the new opcode is intentionally excluded from a condition (e.g.
  a standard-mode-only path that HS mode bypasses entirely via a separate code branch).
- Do not flag unrelated opcode conditions that the new HS opcode genuinely cannot
  reach by design.
- One AI-reviewer data point only; treat as draft.

Confidence: low
Last updated: 2026-05-27

### MEM-0198: devres LIFO ordering — async work cancel action must be registered after DMA channels and mutexes

Status: draft
Scope: general
Triggers:
- A driver registers `devm_add_action_or_reset()` to call `cancel_work_sync()`
  before registering devres actions for DMA channel release or mutex destruction
- The workqueue callback accesses DMA channels, result buffers, or mutexes that
  are owned by those later-registered devres cleanup actions

Maintainer evidence:
- Sashiko AI reviewer flagged [Critical]/[High] on patches 7/14, 9/14, and 12/14
  of the qce BAM locking series v19
  (20260526-qcom-qce-cmd-descr-v19-0-08472fdcbf4a@oss.qualcomm.com, 2026-05-26):
  registering `qce_cancel_work` before `devm_qce_dma_request()` and
  `devm_mutex_init()` causes LIFO teardown to destroy the mutex and free DMA
  channels before `cancel_work_sync()` runs, with UAF if work fires during teardown.

Review action:
- Flag [BUG] when a `devm_add_action_or_reset()` work cancellation action is
  registered BEFORE devres actions for DMA channels, buffers, or mutexes that
  the work callback accesses; devres runs in LIFO order so the cancel runs last.
- The work cancel action must be registered LAST in probe so it executes FIRST
  in teardown, flushing in-flight callbacks before dependent resources are freed.

False-positive guards:
- Do not flag if the workqueue cannot fire after teardown begins (e.g. already
  stopped by a synchronous `dmaengine_terminate_sync()` that runs first).
- Do not flag if the devres actions are semantically independent and cannot race.
- Single data point from an AI reviewer; verify with human maintainer feedback.

Confidence: low
Last updated: 2026-05-27

### MEM-0199: Explicit free of devm-managed resources inside a devres callback causes double-free

Status: draft
Scope: general
Triggers:
- A devres cleanup callback (registered via `devm_add_action_or_reset()`) calls
  `kfree()` on a pointer obtained from `devm_kmalloc()`, or calls
  `dma_release_channel()` on a channel obtained from `devm_dma_request_chan()`
- A preceding patch in the same series converts manual alloc/request calls to
  their `devm_*` counterparts but does not remove the explicit free from the
  existing callback

Maintainer evidence:
- Sashiko AI reviewer flagged [High] on patches 11/14, 12/14, and 13/14 of the
  qce BAM locking series v19
  (20260526-qcom-qce-cmd-descr-v19-0-08472fdcbf4a@oss.qualcomm.com, 2026-05-26):
  `qce_dma_terminate()` retained `kfree(dma->result_buf)` and
  `dma_release_channel()` calls after the series switched to `devm_kmalloc()` and
  `devm_dma_request_chan()`, causing double-free / slab corruption at teardown.

Review action:
- Flag [BUG] when a devres cleanup callback explicitly frees a resource that is
  also registered for automatic devres cleanup in the same probe path.
- When reviewing a "convert to devm_*" patch, verify that the explicit free in the
  old cleanup callback is removed in the same patch; if not, flag [BUG].

False-positive guards:
- Do not flag `dmaengine_terminate_sync()` preceding `dma_release_channel()` —
  that is the correct shutdown sequence, not a double-free.
- Do not flag if the callback frees a sub-object that is not itself the devm
  allocation (e.g. freeing a field within a devm-allocated struct).
- Single data point from an AI reviewer; verify with human maintainer feedback.

Confidence: low
Last updated: 2026-05-27

### MEM-0200: Qcom osm-l3/EPSS driver — new SoC-specific LUT-entry cap must be audited against sibling small-class SoCs

Status: draft
Scope: subsystem:interconnect/qcom file-pattern:drivers/interconnect/qcom/osm-l3.c
Triggers:
- A patch adds a new SoC-specific osm_l3_data descriptor (or equivalent per-SoC
  driver-data struct) to the osm-l3/EPSS interconnect driver that limits the
  number of usable frequency LUT entries below the hardware maximum (e.g.,
  sets lut_row_cnt or max_entries to a value less than OSM_TABLE_SIZE)
- The series does not address whether other small/IoT-class SoCs already in the
  driver (e.g., agatti, sm6115, sm6125) share the same architecture and may
  also need the same cap

Maintainer evidence:
- Konrad Dybcio on patch 2/3 of Shikra EPSS L3 series (linux-arm-msm,
  2026-05-22): after giving Reviewed-by, asked "we have a number of smaller
  SoCs in the tree with a roughly similar architecture (agatti, sm61[12]5, etc.)
  - do any of them also need this limit?" The automated review did not raise
  this question (missed-by-us).

Review action:
- When a patch introduces a SoC-specific osm_l3_data (or similar per-SoC
  descriptor) that caps LUT entries below the driver maximum, flag [MINOR] if
  the commit body or cover letter does not address whether other small-class
  Qcom SoCs in the driver (agatti, sm6115, sm6125, or similar IoT-family SoCs)
  also require the same cap.
- Suggest the author verify whether sibling SoC hardware datasheets document the
  same LUT-size limit, and if so, either include them in the same patch or note
  them as follow-up work.

False-positive guards:
- Do not flag if the commit body explicitly states the LUT limit is unique to
  the new SoC and confirms sibling SoCs are unaffected.
- Do not flag if no other small-class SoCs with similar architecture are present
  in the driver at review time.
- Do not apply to patches that change other driver parameters (e.g., opp-table
  entries, regulator limits) unrelated to the LUT read-count cap.

Confidence: low
Last updated: 2026-05-27

### MEM-0202: Qcom clk/GDSC --- BRANCH_HALT on gated clock branches is a mechanically implied companion to HW_CTRL_TRIGGER; commit body need not enumerate it separately

Status: draft
Scope: subsystem:clk/qcom file-pattern:drivers/clk/qcom/gcc-*.c
Triggers:
- A patch adds HW_CTRL_TRIGGER to one or more GDSCs and also sets halt_check = BRANCH_HALT on the clock branches directly gated by those GDSCs
- The commit subject and body describe only the HW_CTRL_TRIGGER GDSC change, with no mention of the BRANCH_HALT additions
- A reviewer considers flagging [MINOR] because the diff contains undescribed changes

Maintainer evidence:
- Bryan O'Donoghue gave Reviewed-by on patch 2/8 of
  20260526-msm8939-venus-rfc-v9-0-bb1069f3fe02@gmail.com (clk: qcom:
  gcc-msm8939: mark Venus core GDSCs as hardware controlled) without
  requesting any commit body update to mention BRANCH_HALT additions to
  gcc_venus0_core0/core1_vcodec0_clk. Our automated review flagged [MINOR]
  for the undescribed companion change --- a false positive.

Review action:
- Do not flag [MINOR] when halt_check = BRANCH_HALT is added to clock branches that are directly gated by a GDSC also being set to HW_CTRL_TRIGGER in the same patch; the two are mechanically coupled and the subject captures the functional intent.
- Still flag if the BRANCH_HALT additions touch clock branches outside the scope of the modified GDSCs, as that would be a distinct undescribed change.

False-positive guards:
- Do not apply if the BRANCH_HALT changes span clock branches not governed by the modified GDSCs.
- One data point (absence of complaint, not explicit confirmation); treat as draft.

Confidence: low
Last updated: 2026-05-27

### MEM-0203: Venus pm_helpers --- devm_pm_domain_attach_list() stub may leave core->pmdomains NULL when CONFIG_PM_GENERIC_DOMAINS is disabled; guard before pd_devs access

Status: draft
Scope: subsystem:media/qcom file-pattern:drivers/media/platform/qcom/venus/pm_helpers.c
Triggers:
- A patch adds a loop over core->pmdomains->pd_devs[] that is gated only on a static resource field (e.g. res->vcodec_pmdomains being non-NULL) but does not separately check core->pmdomains itself
- The loop entry point assumes that a non-NULL resource field implies a valid pmdomains pointer

Maintainer evidence:
- Sashiko AI review (sashiko-bot@kernel.org, 2026-05-26) on patch 3/8 of
  20260526-msm8939-venus-rfc-v9-0-bb1069f3fe02@gmail.com: when
  CONFIG_PM_GENERIC_DOMAINS is disabled, devm_pm_domain_attach_list() is a
  stub that returns 0 without allocating the list pointer, leaving
  core->pmdomains NULL. A loop gated on res->vcodec_pmdomains_num but not on
  core->pmdomains will NULL-deref. Our automated review reported 0 bugs on this
  patch (missed-by-us).

Review action:
- Flag [BUG] when a Venus power domain loop accesses core->pmdomains->pd_devs[] without first guarding core->pmdomains against NULL.
- Suggest adding an explicit NULL guard: if (!core->pmdomains) return 0; before any access to pmdomains->pd_devs[].

False-positive guards:
- Do not flag if CONFIG_PM_GENERIC_DOMAINS is a hard Kconfig dependency of the driver (i.e., a select or depends ensures it is always enabled).
- Do not flag if a NULL check on the pointer itself is already present earlier in the call chain for the same code path.
- One automated reviewer data point only; treat as draft and apply only within the Venus driver context.

Confidence: low
Last updated: 2026-05-27

### MEM-0204: DRM colorop — repeated `->next` linked-list traversal appearing 3+ times should be extracted into a named iterator macro

Status: draft
Scope: subsystem:drm file-pattern:drivers/gpu/drm/
Triggers:
- A patchset introduces or extends linked-list traversal via a `->next` pointer
  (e.g. `for (colorop = head; colorop; colorop = colorop->next)`) and the same
  loop body appears 3 or more times across the patchset
- No `for_each_*` macro for this traversal exists in the associated header file

Maintainer evidence:
- Alex Hung (AMD DRM reviewer) on patch 1/3 of
  <20260526142940.504911-1-mwen@igalia.com> ("drm/atomic: only add states of
  active or transient active colorops", 2026-05-26): the
  `for (colorop = ...; colorop; colorop = colorop->next)` pattern appeared 5
  times across the patchset; reviewer suggested
  `drm_for_each_colorop_in_pipeline(colorop, pipeline)` in `drm_colorop.h`.
  Our automated review did not raise this (missed-by-us).
- Jani Nikula (Intel DRM) on the same thread (2026-05-29): asked "Is there a
  reason struct drm_colorop reinvents lists and doesn't have struct list_head
  node?" — implicitly corroborates that the custom ->next list design itself
  (which necessitates the manual loop) is questioned by maintainers; see also
  MEM-0248 which captures the struct-design concern separately.

Review action:
- Flag [NIT] when the same `for (x = head; x; x = x->next)` traversal appears
  3 or more times within the patchset and no `for_each_*` macro exists for it.
- Suggest a macro in the appropriate header following the `drm_for_each_*`
  naming convention, e.g.:
  `#define drm_for_each_colorop_in_pipeline(colorop, pipeline) \`
  `    for ((colorop) = (pipeline); (colorop); (colorop) = (colorop)->next)`

False-positive guards:
- Do not flag if a matching `for_each_*` macro already exists and is unused.
- Do not flag if the loop appears fewer than 3 times in the patchset.
- Do not apply outside the DRM subsystem without additional maintainer evidence
  for the specific subsystem's macro conventions.

Confidence: medium
Last updated: 2026-05-29

### MEM-0205: work_struct embedded in heap-allocated struct requires cancel_work_sync() in teardown path

Status: draft
Scope: general
Triggers:
- A patch adds a work_struct (or delayed_work) field to a heap-allocated
  driver struct (e.g. struct rproc, a platform-device private struct)
- The corresponding teardown function (e.g. rproc_del(), driver .remove)
  does not call cancel_work_sync() on the new field before
  device_del() / put_device() / kfree()

Maintainer evidence:
- Stephan Gerhold (remoteproc maintainer) on patch 1/2 of
  20260409-rproc-attach-issue-v1 (linux-remoteproc, 2026-04-10): confirmed
  cancel_work_sync() is required before freeing resources in rproc_del()
  when a new attach_work is scheduled on the global workqueue. Stated:
  "cancel_work_sync() should wait until the worker execution has finished.
  If you call it before freeing the resources (= deleting the remoteproc),
  I would expect it should work as expected." Our automated review raised
  this as [CONCERN]; confirmed by maintainer.

Review action:
- Flag [CONCERN] when a patch embeds a new work_struct / delayed_work in
  a heap-allocated struct and no cancel_work_sync() / cancel_delayed_work_sync()
  is added to the corresponding teardown path.
- Note that state-machine guards (e.g. a RPROC_DELETED check inside the work
  function) are logical checks only -- they do not prevent a use-after-free
  if kfree() / put_device() races with work dispatch from the global workqueue.
- Suggest adding cancel_work_sync(&obj->new_work) in the teardown function
  immediately before device_del() or the matching free call.

False-positive guards:
- Do not flag if cancel_work_sync() is already present for that field.
- Do not flag statically allocated structs (e.g. module-scope or stack objects)
  where kfree() is never called.
- Do not flag if the work function holds a counted reference on the struct
  before any dereference and the teardown path drops the reference only after
  the work can no longer re-queue.

Confidence: low
Last updated: 2026-05-27

### MEM-0206: remoteproc subdev stop/unprepare unbalanced call -- per-callback NULL guard is symptom fix; subdevs_started bool is preferred architectural fix

Status: draft
Scope: subsystem:remoteproc file-pattern:drivers/remoteproc/
Triggers:
- A patch adds a NULL guard to a *_subdev_stop() or *_subdev_unprepare()
  callback (e.g. if (!glink->edge) return) to prevent a crash when the
  subdev start/prepare counterpart was never called
- The unbalanced call occurs because rproc_stop_subdevices() is invoked
  during crash recovery after a failed attach; checking rproc->state !=
  RPROC_DETACHED in rproc_stop() does not prevent the call because the
  crash handler sets rproc->state = RPROC_CRASHED before calling
  rproc_boot_recovery()

Maintainer evidence:
- Stephan Gerhold (remoteproc maintainer) on patch 2/2 of
  20260409-rproc-attach-issue-v1 (linux-remoteproc, 2026-04-10):
  "rproc_stop_subdevices() should not be called without a prior call to
  rproc_start_subdevices(). I think we need a more generic solution" and
  proposed a bool subdevs_started in struct rproc managed separately from
  rproc->state. A state check on RPROC_DETACHED fails because RPROC_CRASHED
  is set before recovery. Author agreed subdevs_started is the better approach.
  Our review accepted the NULL guard as architecturally correct and flagged
  only the sibling SMD function; this is a missed-by-us architectural finding.

Review action:
- Flag [CONCERN] when a patch adds per-callback NULL guards to remoteproc
  subdev stop/unprepare functions to work around an unbalanced stop-without-start
  scenario during crash recovery after a failed attach.
- Explain the root cause: rproc_stop_subdevices() is called without a prior
  rproc_start_subdevices() because rproc->state is RPROC_CRASHED, masking
  the detached-never-started condition.
- Suggest the architectural fix: add bool subdevs_started to struct rproc,
  set it to true in rproc_start_subdevices(), reset it to false in
  rproc_stop_subdevices(), and gate both rproc_stop_subdevices() and
  rproc_unprepare_subdevices() on this flag rather than on rproc->state.

False-positive guards:
- Do not flag NULL guards protecting a genuinely optional subdev field that
  may be NULL for reasons independent of start/stop imbalance (e.g. a subdev
  type conditionally registered by the platform driver at probe time).
- Do not apply outside the remoteproc subsystem without additional maintainer
  evidence for the same start/stop symmetry contract.

Confidence: low
Last updated: 2026-05-27

### MEM-0207: of_find_device_by_node() + dev_get_drvdata() NULL must return -EPROBE_DEFER, not -ENODEV

Status: draft
Scope: general
Triggers:
- A helper resolves a controller device via `of_parse_phandle()` + `of_find_device_by_node()`,
  then calls `dev_get_drvdata()` on the returned platform device to obtain the driver-private
  struct (e.g. `struct rsc_drv *`)
- When `dev_get_drvdata()` returns NULL (device found in DT but not yet fully probed),
  the helper returns `-ENODEV` (or another permanent error) instead of `-EPROBE_DEFER`

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 1/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com:
  "If the RPMH controller device is found by of_find_device_by_node() but hasn't fully
  probed yet, dev_get_drvdata() will return NULL. Does returning -ENODEV here cause a
  premature and permanent probe failure for consumers instead of allowing them to
  gracefully defer by returning -EPROBE_DEFER?" Our automated review analysed the
  resource-lifecycle path and gave READY TO APPLY without flagging the error code choice
  (missed-by-us).

Review action:
- Flag [BUG] when a probe helper resolves a device via `of_find_device_by_node()` (device
  exists in DT) and then returns a permanent error code (e.g. `-ENODEV`, `-EINVAL`) when
  `dev_get_drvdata()` is NULL.
- A NULL drvdata after a successful device lookup means the supplier device was found but
  has not yet completed probe; the correct response is `-EPROBE_DEFER` so the probe
  framework retries after the supplier binds.
- Suggest: `if (!drv) return ERR_PTR(-EPROBE_DEFER);` in the helper, and document that
  `-EINVAL` / `-ENODEV` should be reserved for the case where the device is genuinely absent
  or of the wrong type.

False-positive guards:
- Do not flag if a prior check has already confirmed the drvdata cannot be NULL at that
  point (e.g. the device is known to be fully probed before any consumer is registered,
  enforced by a device-link or bus ordering guarantee).
- Do not flag if the caller already wraps the helper result and converts -ENODEV to
  -EPROBE_DEFER upstream.
- Do not flag the outer `of_find_device_by_node()` returning NULL (device absent from DT
  or not yet enumerated); that path may correctly return -EPROBE_DEFER or -ENODEV
  depending on whether the phandle is expected to always be present.

Confidence: low
Last updated: 2026-05-29

### MEM-0208: Phandle-resolved drvdata cast — validate target is the expected driver type before use

Status: draft
Scope: general
Triggers:
- A helper resolves a controller device via `of_parse_phandle()` + `of_find_device_by_node()`
  and immediately casts `dev_get_drvdata()` to a specific driver-private type (e.g.
  `struct rsc_drv *`) with no driver-type validation
- If the DT phandle accidentally or maliciously points to a non-target device,
  the cast silently reinterprets a different driver's struct, causing type confusion and
  potential memory corruption

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 1/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com:
  "If a device tree maliciously or accidentally points the 'qcom,rpmh' phandle to a
  non-RPMH device, is it possible for drvdata to point to a different driver's structure
  when get_rpmh_ctrlr_from_dev() evaluates it? Would this cause type confusion and memory
  corruption?" Our automated review analysed the lifecycle path and gave READY TO APPLY
  without flagging the missing identity check (missed-by-us).

Review action:
- Flag [CONCERN] when a driver resolves a phandle device and immediately casts drvdata to
  a typed struct without first verifying that the device is bound to the expected driver
  (e.g. by checking the driver name, an ops pointer, or a magic sentinel in the struct).
- Suggest adding a validation step such as checking `ctrl_dev->driver == &expected_driver`
  or verifying a distinguishing field in the returned struct before any dereference.

False-positive guards:
- Do not flag if the device is resolved through a managed kernel-internal registry (not a
  user-controlled DT property) where only the correct driver can populate that drvdata slot.
- Do not flag if a companion patch adds explicit driver-type validation in the same series.
- Downgrade to [NIT] if the subsystem enforces driver identity structurally (e.g. bus
  matching ensures only one driver type can bind to the node class).

Confidence: low
Last updated: 2026-05-29

### MEM-0210: `ERR_PTR()` in a header stub requires `<linux/err.h>` — header must be self-contained

Status: draft
Scope: general
Triggers:
- A patch adds an `#else` stub (or any inline/static function) to a kernel header that calls
  `ERR_PTR()`, `IS_ERR()`, or `PTR_ERR()` to return a fake error pointer
- The header does not include `<linux/err.h>` directly; it relies on an implicit transitive
  include from other headers already pulled in by kernel .c files

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-28) on patch 1/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com:
  "`include/soc/qcom/rpmh.h` now uses `ERR_PTR()` but does not include `<linux/err.h>`.
  Add the missing include so the header remains self-contained." The stub
  `static inline struct device *rpmh_get_ctrlr_dev(struct device *dev) { return ERR_PTR(-ENODEV); }`
  was added without a companion `#include <linux/err.h>`. Our automated review did not flag
  this (missed-by-us).

Review action:
- Flag [MINOR] when a patch adds `ERR_PTR()`, `IS_ERR()`, or `PTR_ERR()` to a header file
  without also adding `#include <linux/err.h>` to that same header.
- The include may be absent because existing `.c` file users happen to pull it in transitively,
  but any .c file that includes only this header will fail to compile.

False-positive guards:
- Do not flag if `#include <linux/err.h>` is already present in the same header file.
- Do not flag if the header includes another header (e.g. `<linux/device.h>`) that is
  documented to re-export err.h symbols transitively and that guarantee is stable — in
  practice this is fragile; prefer the explicit include.
- One AI-reviewer data point; treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0212: Stack-allocated completion passed to async hardware transaction — UAF on `wait_for_completion_timeout()` timeout without cancel

Status: draft
Scope: general
Triggers:
- A synchronous function declares a completion (`DECLARE_COMPLETION_ONSTACK`) and
  message buffer on the stack
- Submits an asynchronous hardware request that stores a pointer to the stack completion
- Calls `wait_for_completion_timeout()` — if the timeout expires the function returns
  and the stack frame is destroyed
- No mechanism cancels the in-flight hardware transaction before the stack frame is freed

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 1/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com (pre-existing
  pattern in `rpmh_write_ctrlr()`): "[Critical] When wait_for_completion_timeout()
  times out, the function returns -ETIMEDOUT and the local stack frame is destroyed.
  However, rpm_msg and compl are allocated on the stack and the hardware transaction
  isn't explicitly canceled. When the hardware eventually completes the request, the
  interrupt handler calls rpmh_tx_done() which accesses the stale rpm_msg->completion
  pointer and calls complete(), writing to unmapped or reused stack memory."
  Our automated review did not flag this (missed-by-us).

Review action:
- Flag [BUG] when a synchronous function uses `DECLARE_COMPLETION_ONSTACK` as the
  completion for an asynchronous hardware transaction, calls
  `wait_for_completion_timeout()`, and has no mechanism to cancel the in-flight
  transaction before returning on timeout.
- Suggest adding a transaction-cancel call before the timeout return, or converting
  to heap-allocated messages with `needs_free = true` so the callback safely frees
  them after the caller has already returned.

False-positive guards:
- Do not flag if a cancel/abort call on the timeout path ensures the interrupt handler
  cannot fire after the function returns.
- Do not flag `wait_for_completion()` (no timeout) — the indefinite wait cannot return
  while the transaction is still in flight.
- Do not flag if the completion is heap-allocated (not on the stack).

Confidence: low
Last updated: 2026-05-29

### MEM-0213: pinctrl — new function enum value must be added to ALL parallel function-name arrays

Status: draft
Scope: subsystem:pinctrl
Triggers:
- A patch adds a new entry to a pinctrl driver's function-index enum (e.g.
  `PMIC_GPIO_FUNC_INDEX_LEVEL_SHIFTER`) without adding a corresponding entry in
  the parallel function-name string array (e.g. `pmic_gpio_functions[]`)
- Debugfs or the pinctrl core dereferences `functions[function_index]` for a pin
  configured with the new function, accessing an out-of-bounds element

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 4/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com:
  "[High] If pmic_gpio_pinconf_pin_dbg_show() formats the status of a level-shifter
  pin, it dereferences pmic_gpio_functions[function]. For a level-shifter pin, this
  would be index 10, while the array only has 10 elements — out-of-bounds."
  Our automated review did not flag this (missed-by-us).

Review action:
- Flag [BUG] when a new enum value is added to a pinctrl function-index enum but the
  corresponding function-name string array is not extended.
- Cross-check: verify `ARRAY_SIZE(functions)` covers the new maximum index.
- Also check other parallel arrays indexed by function index.

False-positive guards:
- Do not flag if the new enum value is a software-only pseudo-function that is never
  registered via `pinctrl_register_map()` and the debugfs show path already guards
  against out-of-bounds (e.g. `if (function >= ARRAY_SIZE(functions)) return;`).

Confidence: low
Last updated: 2026-05-29

### MEM-0214: devres LIFO ordering — framework-registered data must not be allocated after `devm_*_register()`

Status: draft
Scope: general
Triggers:
- A driver probe function calls `devm_*_register()` (pinctrl, gpio, input, etc.) and then
  allocates memory with `devm_kcalloc()` / `devm_kzalloc()` that is subsequently passed
  into the same framework device (e.g. as group names or function data)
- On driver unbind, devres releases in LIFO order: the later-allocated memory is freed
  before the framework device is unregistered, leaving the framework with dangling pointers

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 4/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com:
  "[High] Because devres releases resources in LIFO order, the level shifter memory
  (ls_group_data, ls_group_names allocated via devm_kcalloc/devm_kzalloc after
  devm_pinctrl_register_and_init) will be freed before the pinctrl device is
  unregistered. Does this leave a window where the pinctrl device remains active and
  exposed to userspace (sysfs/debugfs) while its registered groups and functions point
  to freed memory?" Our automated review did not flag this (missed-by-us).

Review action:
- Flag [CONCERN] when probe allocates memory with `devm_*` AFTER calling
  `devm_*_register()` AND that memory is passed to the framework device.
- Suggest allocating all data that the framework device will reference BEFORE the
  framework registration call, so that devres LIFO order unregisters the framework
  device before freeing the data.

False-positive guards:
- Do not flag devm allocations that are entirely private to the driver and never passed
  into the framework device.
- Do not flag if the framework's unregister path copies all registered data at
  registration time and does not retain raw pointers into driver memory.

Confidence: low
Last updated: 2026-05-29

### MEM-0215: spmi-gpio — software pseudo-function index must bypass hardware function register write

Status: draft
Scope: file-pattern:drivers/pinctrl/qcom/pinctrl-spmi-gpio.c
Triggers:
- A patch adds a new software-only pseudo-function entry to `enum pmic_gpio_func_index`
  whose index value exceeds the hardware function-register field width (3 bits for
  non-LV/MV PMIC GPIO: values 0–7)
- The `pmic_gpio_pinconf_pin_set()` path writes `pad->function` shifted into
  `PMIC_GPIO_REG_MODE_CTL` without checking whether `pad->function` is a software-only
  pseudo-function value

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 4/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com:
  "[High] If pad->function is PMIC_GPIO_FUNC_INDEX_LEVEL_SHIFTER (10, 0b1010),
  shifting it by 1 results in 20 (0x14). Since the hardware function field is only
  3 bits, this overflows and overwrites bit 4 (PMIC_GPIO_REG_MODE_DIR_SHIFT)."
  Our automated review did not flag this (missed-by-us).

Review action:
- Flag [BUG] when a software pseudo-function enum index is written into a hardware
  register field narrower than the index value requires.
- Suggest an explicit guard in the MODE_CTL write path: skip the write (or write a
  fixed safe value) when `pad->function == PMIC_GPIO_FUNC_INDEX_LEVEL_SHIFTER` (or
  any index >= the number of real hardware functions).

False-positive guards:
- Do not flag if the pinconf_set path already contains a guard skipping the hardware
  write for the new pseudo-function index.
- Do not flag if the new enum index fits within the hardware register field width.
- One AI-reviewer data point; treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0216: pinctrl — new pinconf parameter in `_set` must have matching `_get` implementation

Status: draft
Scope: subsystem:pinctrl
Triggers:
- A patch adds a new custom pinconf parameter (e.g. `PMIC_GPIO_CONF_LS_ENABLE`) to a
  pinctrl driver's `pin_config_set` or `pin_config_group_set` handler
- The same parameter has no corresponding case in `pin_config_get` or
  `pin_config_group_get`, causing programmatic reads to fail with `-EINVAL`

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 4/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com:
  "[Medium] pmic_gpio_pinconf_pin_get() lacks a case for PMIC_GPIO_CONF_LS_ENABLE.
  This appears to break the symmetry of the pinctrl API, which might cause programmatic
  reads of this configuration to fail with -EINVAL." Our automated review did not flag
  this (missed-by-us).

Review action:
- Flag [MINOR] when a new custom pinconf parameter is handled in `pin_config_set` (or
  `pin_config_group_set`) but has no corresponding case in `pin_config_get` (or
  `pin_config_group_get`).
- The pinctrl API contract expects get/set symmetry. If readback is not supported,
  the commit body should document why (e.g. write-only hardware register).

False-positive guards:
- Do not flag if the hardware register is write-only and the commit body documents this.
- Do not flag if a generic fallback handler covers the parameter in the get path.
- Use [MINOR], not [CONCERN]: the asymmetry breaks API contract but does not cause
  runtime crashes on the normal pin-configuration path.

Confidence: low
Last updated: 2026-05-29

### MEM-0217: GENI SE I2C — conf registers not restored after system sleep when moved to probe-only

Status: draft
Scope: subsystem:i2c file-pattern:drivers/i2c/busses/i2c-qcom-geni.c
Triggers:
- A patch moves qcom_geni_i2c_conf() (or equivalent GENI SE register programming for
  SE_GENI_CLK_SEL, GENI_SER_M_CLK_CFG, SE_I2C_SCL_COUNTERS) from per-transfer to
  probe-only, citing that the GENI SE power domain is never turned off
- Neither geni_i2c_runtime_resume() nor geni_i2c_resume_noirq() is updated to
  reprogram these registers on resume

Maintainer evidence:
- Praveen Talari (Qualcomm I2C reviewer) on [PATCH v2 2/2] i2c: qcom-geni: Configure
  SCL counters once at probe time (linux-i2c, 2026-05-29): "For S2R/S2D, these values
  are not preserved. I suggest retaining them within the I2C SE initialization API."
  The patch comment claimed the GENI SE domain is "never turned off" but this holds only
  for runtime suspend; system sleep (S2R/S2D) can power-collapse the domain on some
  platforms. Our automated review raised this as [CONCERN]; maintainer confirmed it
  (confirmed).
- Patchwise AI review (2026-05-28) on the same patch independently noted genpd can power
  off the SE domain during runtime suspend on DT platforms with power-domains.

Review action:
- Flag [CONCERN] when qcom_geni_i2c_conf() (or equivalent SE register writes) is removed
  from the per-transfer path and not added to geni_i2c_runtime_resume() and/or
  geni_i2c_resume_noirq().
- Suggest adding qcom_geni_i2c_conf() inside geni_i2c_runtime_resume() after
  geni_se_resources_on() succeeds to restore SE_GENI_CLK_SEL, GENI_SER_M_CLK_CFG, and
  SE_I2C_SCL_COUNTERS after any power-domain resume.
- Accept the optimization only if the patch documents that GENI SE hardware state is
  preserved across all sleep states on all supported platforms.

False-positive guards:
- Do not flag if geni_i2c_runtime_resume() (or geni_i2c_resume_noirq()) already calls
  qcom_geni_i2c_conf() or otherwise restores these registers.
- Do not flag if the commit body explicitly documents that the GENI SE power domain is
  never collapsed on any supported platform and references the genpd topology as evidence.

Confidence: medium
Last updated: 2026-05-29

### MEM-0218: geni_se_clk_freq_match() nearest-match may pair wrong SCL counters with returned clock index

Status: draft
Scope: subsystem:i2c file-pattern:drivers/i2c/busses/i2c-qcom-geni.c
Triggers:
- A patch uses geni_se_clk_freq_match() with nearest-match or ceiling semantics to
  select an entry from a fixed-rate clock table (e.g. geni_i2c_clk_map_19p2mhz)
- The SCL counter table is calibrated for exactly that source rate; a nearest-match
  result may return an index for a different rate, mis-pairing the counter table
  with an incorrect clock index

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-28) on patch 1/2
  "i2c: qcom-geni: Fix hardcoded clock index in SE_GENI_CLK_SEL": "This allows
  geni_se_clk_freq_match() to return a clock table entry that is only a multiple
  or closest match to 19.2 MHz, but the selected counter table is calibrated for a
  19.2 MHz source. Reject entries where res_freq != freq here as well."
  Our automated review missed this matching-semantics issue (missed-by-us).

Review action:
- Flag [MINOR] when geni_se_clk_freq_match() is called with nearest-match semantics
  for a source rate paired with a fixed counter table, and the caller does not validate
  that res_freq matches the requested freq before using the returned index.
- Suggest adding an exact-match guard: skip or reject the result when res_freq differs
  from the requested frequency.

False-positive guards:
- Do not flag when the caller already validates res_freq == freq before using the index.
- Do not flag when nearest-match is intentional and the counter table tolerates imprecise
  rates (e.g. best-effort frequency, not a strict SCL-counter calibration).
- One AI-reviewer data point only; treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0219: SE_GENI_CLK_SEL write must mask index with CLK_SEL_MSK to avoid setting reserved bits

Status: draft
Scope: subsystem:i2c file-pattern:drivers/i2c/busses/i2c-qcom-geni.c
Triggers:
- A patch writes a computed clock index variable directly to SE_GENI_CLK_SEL via
  writel_relaxed() without masking against CLK_SEL_MSK
- The index may exceed the field width and set reserved bits in the register

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-28) on patch 1/2
  "i2c: qcom-geni: Fix hardcoded clock index in SE_GENI_CLK_SEL": "SE_GENI_CLK_SEL
  only uses CLK_SEL_MSK; writing the raw index can set reserved bits when the clock
  table index is larger than the field width. Mask the value before writing it."
  Our automated review did not flag the missing mask (missed-by-us).

Review action:
- Flag [MINOR] when a writel_relaxed() to SE_GENI_CLK_SEL writes an unmasked index
  without AND-ing with CLK_SEL_MSK (or equivalent field mask).
- Suggest: writel_relaxed(gi2c->clk_idx & CLK_SEL_MSK, gi2c->se.base + SE_GENI_CLK_SEL)

False-positive guards:
- Do not flag if the value is guaranteed to fit within the field by construction (e.g.
  hardcoded 0, or a table whose maximum index is verified to be within the mask width).
- Do not flag if CLK_SEL_MSK is applied elsewhere before the write site.
- One AI-reviewer data point only; treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0220: pinctrl — level-shifter pseudo-function must enforce mutual exclusivity with hardware GPIO output functions

Status: draft
Scope: subsystem:pinctrl file-pattern:drivers/pinctrl/qcom/pinctrl-spmi-gpio.c
Triggers:
- A patch adds a level-shifter pseudo-function to a pinctrl driver
- The driver's `pin_config_set` (or `pin_config_group_set`) does not verify that the
  pin is not simultaneously configured for a normal GPIO output function
- Both the physical GPIO output buffer and the external level-shifter could drive the pin
  concurrently if no mutual-exclusivity guard is enforced

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 4/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com:
  "[High] If a device tree simultaneously assigns a normal function to a pin and enables
  the level shifter on its associated group, pad->function will be NORMAL. Since the check
  will pass, it will set pad->is_enabled = true, potentially causing both the physical GPIO
  output buffer and the external level shifter to drive the pin concurrently. Could this
  result in electrical overstress?" Our automated review did not flag this (missed-by-us).

Review action:
- Flag [CONCERN] when a level-shifter pseudo-function is added to a pinctrl driver but no
  guard in `pin_config_set` / `pin_config_group_set` verifies that the pin's current
  function is not a normal GPIO output or other hardware-driving function.
- Suggest adding an explicit check: if `pad->function != PMIC_GPIO_FUNC_INDEX_LEVEL_SHIFTER`
  when the level-shifter pinconf is being enabled, return an error or emit a warning, as
  concurrent activation of a GPIO output driver and an external level-shifter risks
  electrical overstress.

False-positive guards:
- Do not flag if the hardware physically prevents concurrent enable of the GPIO output
  buffer and the level-shifter (e.g. the level-shifter enable sequence automatically
  tri-states the pad).
- Do not flag if the existing probe-level or DT-level validation already ensures the
  two configurations are mutually exclusive before pinconf_group_set is reachable.
- One AI-reviewer data point (sashiko-bot); treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0226: Boot-enabled QREF clock — `unprepare` calling `regulator_bulk_disable` without prior kernel `prepare` is unbalanced

Status: draft
Scope: subsystem:clk/qcom file-pattern:drivers/clk/qcom/
Triggers:
- A new clock type's `clk_ops.unprepare` callback calls `regulator_bulk_disable()`
- The driver has no mechanism to sync regulator state during probe for hardware left
  enabled by the bootloader
- The CLK framework will call `unprepare()` via `clk_disable_unused()` for any clock
  the kernel never `prepare`d but which was found enabled in hardware

Maintainer evidence:
- Sashiko AI review (sashiko-bot@kernel.org, 2026-05-28) on [PATCH v4 2/7]
  clk: qcom: Add generic clkref_en support: "[High] If the bootloader leaves this
  clock enabled, the common clock framework will call unprepare() during late init
  to turn off unused clocks. Since prepare() was never called by the kernel, won't
  this regulator_bulk_disable() call trigger an unbalanced disable warning and
  permanently leak power? Does the driver need to sync the hardware state during
  probe by enabling the regulators if the clock is already on?" Our automated review
  did not flag this lifecycle gap (missed-by-us).

Review action:
- Flag [CONCERN] when a new clock type's `unprepare` callback calls
  `regulator_bulk_disable()` and the driver has no probe-time bootloader-state sync.
- Suggest: at probe time, call `clk_ops.is_enabled()` for each registered clock; if
  the clock is already enabled, call `regulator_bulk_enable()` to match the future
  `regulator_bulk_disable()` in `unprepare`.

False-positive guards:
- Do not flag if the driver already performs probe-time bootloader state sync by
  calling `regulator_bulk_enable()` for any clock found enabled at probe.
- Do not flag clock types where `is_enabled()` always returns 0 after reset (hardware
  requires explicit SW enable after reset, bootloader never leaves them on).
- Single AI-reviewer data point (sashiko-bot); treat as draft until a human maintainer
  confirms the concern.

Confidence: low
Last updated: 2026-05-29

### MEM-0229: Qcom iris/media — `iris_vpu_power_off_hw()` disables power domains before disabling hardware clocks

Status: draft
Scope: subsystem:media file-pattern:drivers/media/platform/qcom/iris/iris_vpu_common.c
Triggers:
- A patch modifies `iris_vpu_power_off_hw()` or adds new clock disable calls adjacent
  to the existing power-domain disable call in that function
- The function calls `iris_disable_power_domains()` before calling
  `iris_disable_unprepare_clock()` for the hardware clocks

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 2/5 of iris purwa series
  (20260529-enable_iris_on_purwa-v8-0-b1b9670459ab@oss.qualcomm.com): flagged [High]
  (labeled as pre-existing) that `iris_vpu_power_off_hw()` calls
  `iris_disable_power_domains()` before disabling hardware clocks. The power-on sequence
  is: enable power domain, enable clocks, set hwmode. The error path (LIFO) correctly
  reverses this order. The normal off path reverses only the hwmode step and then tears
  down in the wrong order: domain disable before clock disable. On ARM/Qualcomm, turning
  off a GDSC while associated clocks are still running can prevent domain collapse, cause
  bus hangs, or trigger SErrors when the clock controller subsequently accesses unpowered
  registers. The patch perpetuates the unsafe ordering by inserting a new BSE clock
  disable after the power-domain disable.
  Message-ID: 20260529-enable_iris_on_purwa-v8-0-b1b9670459ab@oss.qualcomm.com part=2
  Note: sashiko-bot labeled this as a pre-existing issue, not introduced by the patch.

Review action:
- Flag [CONCERN] when `iris_vpu_power_off_hw()` disables a power domain before
  disabling the associated hardware clocks.
- The correct teardown order mirrors the LIFO error path of `iris_vpu_power_on_hw()`:
  disable all hardware clocks first, then disable the power domain.
- If a patch adds a new clock to the off path, also check whether it is inserted before
  or after the power-domain disable call; flag [CONCERN] if inserted after.

False-positive guards:
- Do not flag if a separate patch in the same series or a recent upstream commit already
  corrected the teardown ordering in `iris_vpu_power_off_hw()`.
- Do not flag when the GDSC is controlled via hardware mode (`hwmode`) and the hardware
  itself ensures clocks stop before power collapse with no software involvement.
- Single AI-reviewer data point (sashiko-bot, pre-existing tag); treat as draft until
  confirmed by an iris subsystem maintainer.

Confidence: low
Last updated: 2026-05-29

### MEM-0233: `local_t` must not be used for per-device shared state — use `atomic_t`

Status: draft
Scope: general
Triggers:
- A struct field or variable uses `local_t` (with `local_cmpxchg()`, `local_set()`,
  `local_read()`) as an exclusivity gate, reference count, or flag for state that
  is accessed from multiple CPUs (e.g. a miscdev open/release pair, a per-device
  reference counter, or a probe-time flag)
- `local_t` is documented for per-CPU counters only; it provides no cross-CPU
  visibility guarantee

Maintainer evidence:
- James Clark (ARM/Coresight reviewer) gave Reviewed-by on
  coresight: etb10: restore atomic_t for shared reading state
  (20260528165201.319452-1-runyu.xiao@seu.edu.cn, 2026-05-29), which restores
  `atomic_t` for `etb_drvdata->reading` after commit 27b10da8fff2 incorrectly
  changed it to `local_t`. The open/release file-op pair can run on different CPUs;
  `local_cmpxchg()` offers no cross-CPU visibility, so `atomic_cmpxchg()` is required.
  Our automated review correctly identified the bug and matched the Reviewed-by outcome
  (confirmed).
- Suzuki K Poulose (ARM/Coresight maintainer) applied the same patch with "Applied,
  thanks!" (https://git.kernel.org/coresight/c/fa09f08ede3d). Maintainer-applied
  confirmation; merged from MEM-0239.

Review action:
- Flag [BUG] when `local_t` is used as an exclusivity gate or shared flag for
  per-device state (e.g. in open/release, probe, or any path reachable from multiple CPUs).
- The correct type is `atomic_t` with `atomic_cmpxchg()` / `atomic_set()` /
  `atomic_read()` for per-device shared state.
- `local_t` is only correct for per-CPU statistics and counters where each CPU
  independently accumulates its own value.
- Also check whether other `local_t` fields in the same driver are used for shared
  (non-per-CPU) state; the perf ring-buffer `local_t data_size` field is typically
  correct per-CPU usage and should not be changed.

False-positive guards:
- Do not flag `local_t` in per-CPU data structures (e.g. `struct perf_output_handle`,
  `cs_buffers`, perf ring-buffer fields) where each CPU has its own copy and no
  cross-CPU access occurs; the `local_t data_size` ring-buffer field in CoreSight
  ETB/ETF is one such correct per-CPU use.
- Do not flag if the `local_t` field is provably only accessed while preemption and
  migration are disabled (e.g. bracketed by `get_cpu()`/`put_cpu()`) so the accessing
  CPU cannot change.
- MEM-0047 covers the related case of `this_cpu_write()` on per-CPU variables where the
  target CPU may differ from the accessing CPU.

Confidence: medium
Last updated: 2026-05-30

### MEM-0236: Qcom clock driver — prefer `.clk_cbcrs` over bare `qcom_branch_set_clk_en()` calls in probe

Status: draft
Scope: subsystem:clk/qcom file-pattern:drivers/clk/qcom/*.c
Triggers:
- A Qcom GCC, DISPCC, or GPUCC driver patch drops `CLK_IS_CRITICAL` clock branches and
  replaces them with a sequence of bare `qcom_branch_set_clk_en(regmap, addr)` calls
  in the probe function
- The `qcom_cc_desc` for the driver does not have a corresponding `.clk_cbcrs` array

Maintainer evidence:
- Dmitry Baryshkov on [PATCH v2 1/5] clk: qcom: gcc-qcm2290: Drop modelling of critical
  clocks (linux-arm-msm, 2026-05-28): "If you are chancing the driver, why are you not
  using .clk_cbcrs?" when the patch replaced removed CLK_IS_CRITICAL branches with nine
  bare `qcom_branch_set_clk_en()` calls in `gcc_qcm2290_probe()`. Our automated review
  did not flag the `.clk_cbcrs` preference (missed-by-us).
- Author (Imran Shaik) replied 2026-05-29: "Sure, will add these to .clk_cbcrs in next
  series." — confirmed in v3 change plan. Second data point from author agreement.

Review action:
- Flag [MINOR] when a Qcom clock driver probe unconditionally calls `qcom_branch_set_clk_en()`
  for multiple always-on clocks without using the `.clk_cbcrs` mechanism in `qcom_cc_desc`.
- Suggest populating a `.clk_cbcrs` array (with corresponding `num_clk_cbcrs` field) in the
  `qcom_cc_desc` and letting `qcom_cc_probe()` handle the always-on enablement uniformly.

False-positive guards:
- Do not flag `qcom_branch_set_clk_en()` calls for clocks that must be sequenced in a
  specific order relative to PLL configuration or other probe steps that `.clk_cbcrs`
  cannot accommodate.
- Do not flag if the driver's `qcom_cc_desc` already uses `.clk_cbcrs` for these clocks.

Confidence: medium
Last updated: 2026-05-30

### MEM-0238: Qcom DISPCC/GPUCC — static global struct pointer rewritten in probe to select per-compatible freq_tbl

Status: draft
Scope: subsystem:clk/qcom file-pattern:drivers/clk/qcom/gpucc-*.c drivers/clk/qcom/dispcc-*.c
Triggers:
- A Qcom clock driver probe function rewrites a pointer field inside a static global
  `clk_rcg2` or `clk_regmap` struct (e.g. `gpu_cc_gx_gfx3d_clk_src.freq_tbl = ...`)
  to select a different frequency table based on `device_is_compatible()`
- The rewritten struct is the same static object used for all probe instances

Maintainer evidence:
- Sashiko-bot on [PATCH v2 5/5] clk: qcom: Add support for Qualcomm GPU Clock Controller
  on Shikra (linux-arm-msm, 2026-05-28): flagged [Medium] "Global State Mutation / State
  Pollution — because gpu_cc_gx_gfx3d_clk_src is a static global structure, dynamically
  assigning a new frequency table here will permanently pollute the shared table for the
  entire driver module." The pattern writes `gpu_cc_gx_gfx3d_clk_src.freq_tbl =
  ftbl_gpu_cc_gx_gfx3d_clk_src_shikra` inside `gpu_cc_qcm2290_probe()` when the Shikra
  compatible matches, permanently changing the static global on any subsequent unbind/rebind.
  Dmitry Baryshkov explicitly requested splitting the patch; the mutation is an additional
  concern in the unsplit code.

Review action:
- Flag [CONCERN] when a Qcom clock driver probe mutates a pointer field of a static
  `clk_rcg2` / `clk_regmap` global struct based on `device_is_compatible()` or equivalent.
- Static module data is shared across all probe instances; mutation is not idempotent when
  multiple compatible devices exist or on driver unbind/rebind cycles.
- Suggest instead defining a separate per-compatible `clk_rcg2` variant (or using a
  per-device clk_init_data copy) rather than rewriting a shared static field.

False-positive guards:
- Do not flag probe-time configuration of per-device drvdata structs (heap-allocated per
  probe call); only flag mutations of file-scope `static` structs.
- Do not flag if the driver guarantees at most one probe per module lifetime (no unbind
  path, only built-in drivers) and the commit body documents this.
- Treat as draft (one AI reviewer + one maintainer split-request data point).

Confidence: low
Last updated: 2026-05-29

### MEM-0243: sdhci-msm — `MMC_CAP2_CRYPTO` guard in early-probe helper is always false at cold-boot; but the same helper may be re-invoked during PM resume with caps2 already set

Status: draft
Scope: subsystem:mmc file-pattern:drivers/mmc/host/sdhci-msm.c
Triggers:
- A patch adds a `caps2 & MMC_CAP2_CRYPTO` guard inside `sdhci_msm_gcc_reset()`
  (or another function called early in `sdhci_msm_probe()`) before
  `sdhci_msm_cqe_add_host()` / `sdhci_msm_ice_init()` have run
- The automated review concludes the guarded block is unconditionally dead code

Maintainer evidence:
- Jie Gan (linux-mmc reviewer) on
  [PATCH RESEND v4] mmc: Avoid reprogram all keys to Inline Crypto Engine for
  MMC runtime suspend resume (20260529092612.1749752-1-neeraj.soni@oss.qualcomm.com,
  2026-05-29): "Always false at this point. The first set of the host->mmc->caps2
  is later in the sdhci_msm_cqe_add_host." — confirmed the guard is always false
  on the cold-boot (first probe) path; dead at probe time.
- Neeraj Soni (patch author, same thread, 2026-05-29): "Yes for cold boot this is
  true and Crypto reprogram is not needed. This patch addresses the use cases like
  runtime suspend resume, deep sleep/Quick Boot (DS/QB) and suspend to disk
  (hibernation) use cases where the runtime context is preserved either in dynamic
  memory (DS/QB) or in secondary memory (hibernation)." — the guard fires correctly
  on these PM resume paths because `caps2` is already populated (preserved by the
  PM layer); cold-boot dead-ness is intentional.
  Our automated review correctly identified the cold-boot dead-code, but incorrectly
  concluded the block is dead in all contexts; it missed the hibernation/DS/QB PM
  resume invocations (false-positive for "always dead").

Review action:
- Flag [CONCERN] when a new `caps2 & MMC_CAP2_CRYPTO` block is added in a function
  called early in probe (before `sdhci_msm_cqe_add_host()`); the guard is always
  false on the cold-boot probe path.
- Before concluding the guarded block is "dead code overall", check whether the
  same function is registered as a PM resume callback (or called from one) for
  hibernation, Deep Sleep/Quick Boot, or runtime resume. On those paths `caps2`
  is preserved from the prior boot stage and the guard can be true.
- If the function is called only from probe (no PM resume registration), the block
  is genuinely dead; flag [CONCERN] and suggest the intent be implemented in a
  dedicated runtime-resume callback registered after `sdhci_msm_ice_init()`.
- If the function is also called from a PM resume path (cold-boot dead is
  intentional), downgrade to [MINOR] and request a code comment explaining this.

False-positive guards:
- Do not flag code that reads `caps2` for an unrelated flag set earlier in probe.
- Do not conclude "dead in all contexts" based solely on the cold-boot probe call
  graph; verify whether the helper has PM resume call sites.
- Do not flag if a future refactor moves `sdhci_msm_ice_init()` earlier in the
  probe sequence (verify the actual call-ordering in the patch under review).
- Do not apply to non-sdhci-msm MMC drivers without checking their specific
  probe and PM resume call order.

Confidence: low
Last updated: 2026-05-29

### MEM-0244: Qcom DISPCC/GPUCC driver — silently changing `fw_name` or GDSC flags/wait_vals for existing SoC while adding new SoC support

Status: draft
Scope: subsystem:clk/qcom file-pattern:drivers/clk/qcom/dispcc-*.c drivers/clk/qcom/gpucc-*.c
Triggers:
- A Qcom DISPCC or GPUCC driver patch changes the `.fw_name` string in a
  `clk_parent_data` entry (e.g. from `"gcc_disp_gpll0_clk_src"` to
  `"gcc_disp_gpll0_div_clk_src"`) without a corresponding update to the DT binding
  `clock-names` list and existing DTS files that supply that clock by name, embedded
  in a patch that also adds new-SoC support
- OR: the same patch corrects GDSC flags (e.g. `HW_CTRL` → `HW_CTRL_TRIGGER |
  POLL_CFG_GDSCR | RETAIN_FF_ENABLE`) and/or adds `en_rest_wait_val`/`en_few_wait_val`/
  `clk_dis_wait_val` fields for the existing SoC without an explanation in the commit body
  and without being in a separate "fix" commit with a Fixes: tag

Maintainer evidence:
- Dmitry Baryshkov on [PATCH v2 4/5] clk: qcom: dispcc-qcm2290: Add support for
  Qualcomm Shikra DISPCC (linux-arm-msm, 2026-05-28):
  (1) "Do you realize that this is an undocumented ABI change?" — when the patch
      silently renamed `.fw_name` from `"gcc_disp_gpll0_clk_src"` to
      `"gcc_disp_gpll0_div_clk_src"` in `disp_cc_parent_data_3[]`.
  (2) "And this also needs explanation." — when GDSC flags were changed from
      `HW_CTRL` to `HW_CTRL_TRIGGER | POLL_CFG_GDSCR | RETAIN_FF_ENABLE` and
      `*_wait_val` fields were added without justification in the commit body.
  Author agreed to split GDSC fixes into a separate commit in v3. Our automated
  review flagged the bundled changes as [MINOR] but did not identify the fw_name
  ABI breakage or the GDSC flag change as needing separate commits (missed-by-us).

Review action:
- Flag [CONCERN] when a Qcom clock driver patch changes an existing `.fw_name`
  string in `clk_parent_data` without updating the corresponding DT binding YAML
  `clock-names` list and all in-tree DTS files that supply that clock.
- Flag [MINOR] when GDSC flags or `*_wait_val` fields are changed for an existing SoC
  in the same patch that adds new-SoC support, with no explanation in the commit body.
  Suggest a separate commit with a `Fixes:` tag and justification (e.g. "correct
  GDSC wait values per hardware reference manual section X").
- The `.fw_name` string is the DT clock-name as seen by the consumer driver; it is
  part of the kernel DT ABI and must not be changed without a coordinated DT +
  binding + driver update.

False-positive guards:
- Do not flag if the renamed `.fw_name` is only used by the new SoC compatible being
  added in the same patch and the old SoC's clock-names list is untouched.
- Do not flag if all DTS files and the binding YAML are updated in the same patch/series.
- Do not flag `.name` (internal clk-core name) vs. `.fw_name` (DT clock-name); only
  `.fw_name` and `.dev_id`/`.con_id` string changes affect DT ABI.
- Do not flag GDSC wait_val additions if the commit body explains the hardware reason
  for each field (e.g. "set per TRM table 5.3 for Shikra and QCM2290").

Confidence: medium
Last updated: 2026-05-30

<!-- MEM-0245 moved to active/subsystem-specific.md on 2026-05-29 -->

### MEM-0247: DRM/MSM DP — `atomic_enable()` serialization justifies RMW; "same thread" comment is incorrect and will be rejected

Status: draft
Scope: subsystem:drm/msm file-pattern:drivers/gpu/drm/msm/dp/
Triggers:
- A patch splits a write register sequence into separate link-config and stream-config
  helpers, where the stream-config helper uses a read-modify-write (RMW) operation
- An in-code comment or review finding justifies concurrent-safety by noting the two
  helpers "are called on the same thread" or "are called sequentially"
- The patch is targeting MST support, where per-stream operations may run in
  overlapping contexts

Maintainer evidence:
- Dmitry Baryshkov on patch 4/15 "drm/msm/dp: split msm_dp_ctrl_config_ctrl() into
  link parts and stream parts" (linux-arm-msm, 2026-05-28): rejected the comment
  "in SST, config_ctrl_link and config_ctrl_streams are called sequentially on the
  same thread. In MST, caller holds mst_lock." Reason: "There is neither MST nor
  mst_lock. Also being called on the same thread means nothing, there can be another
  thread, executing the same code concurrently." Dmitry's guidance: "Please point out
  that they are called only from the atomic_enable() callback, which is guaranteed to
  be executed once at a time."
  Our automated review raised a [CONCERN] about the RMW ordering but suggested RMW
  conversion as the fix; Dmitry confirmed a comment is the correct fix, and the comment
  content must reference `atomic_enable()` serialization (missed the exact fix).

Review action:
- When a split-register-config helper uses RMW and an in-code comment justifies
  thread safety by "same thread" or "sequential call" reasoning, flag [MINOR] and
  suggest replacing the comment with: "Called only from atomic_enable(), which is
  guaranteed to be executed once at a time."
- Do NOT suggest converting to a full write (non-RMW) as the safety fix; a correct
  serialization comment is sufficient.

False-positive guards:
- Do not apply outside drm/msm/dp without confirming `atomic_enable()` serialization
  applies to the subsystem in question.
- Do not flag if the comment already correctly references `atomic_enable()` or another
  DRM-framework serialization guarantee.
- One data point; treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0248: DRM struct using custom `->next` pointer instead of `struct list_head` will draw maintainer question

Status: draft
Scope: subsystem:drm file-pattern:include/drm/ drivers/gpu/drm/
Triggers:
- A new DRM object type (e.g. `struct drm_colorop`) uses a custom `->next` or `->prev`
  pointer for linked traversal instead of embedding `struct list_head`
- A patch extends traversal over that custom list in new functions

Maintainer evidence:
- Jani Nikula (Intel DRM) on patch 1/3 of
  <20260526142940.504911-1-mwen@igalia.com> ("drm/atomic: only add states of
  active or transient active colorops", 2026-05-26): "Is there a reason struct
  drm_colorop reinvents lists and doesn't have struct list_head node?"
  Our automated review did not question the use of a custom ->next list (missed-by-us).

Review action:
- Flag [NIT] when a DRM struct uses a bare `->next` pointer for list traversal
  where `struct list_head` + `list_for_each_entry()` would be the idiomatic
  kernel choice.
- Note that maintainers (Jani Nikula) have explicitly questioned this design for
  drm_colorop, and a future refactor to list_head may be expected.

False-positive guards:
- Do not flag a custom ->next pointer that is intentionally a singly-linked
  hardware-ordered pipeline (where list_head overhead or double-link is
  undesirable and the design choice is documented).
- Do not flag if the struct is defined in an out-of-tree or vendor driver that
  already has an established convention for ->next.
- One data point; treat as draft until additional evidence arrives.

Confidence: low
Last updated: 2026-05-29

### MEM-0249: New DRM atomic rejection semantics for a new object type may break existing IGT colorop tests

Status: draft
Scope: subsystem:drm file-pattern:drivers/gpu/drm/drm_atomic.c
Triggers:
- A patch adds a new rejection or validation path in `drm_atomic_check_only()` or
  a related DRM atomic check function for a newly introduced object type
  (e.g. colorop) that was previously unchecked
- CI full runs include tests exercising that object type (e.g. `kms_color_pipeline`,
  `kms_properties@colorop-properties-atomic`)
- The series introduces a behavioral change that makes previously-accepted atomic
  commits fail with -EINVAL

Maintainer evidence:
- Xe.CI.FULL failure for <20260526142940.504911-1-mwen@igalia.com> (2026-05-26):
  `kms_color_pipeline@plane-ctm3x4@pipe-a-plane-2` PASS→FAIL (+28 other tests fail)
  and `kms_properties@colorop-properties-atomic@pipe-c-hdmi-a-3` PASS→FAIL (+35 fails)
  after patch 3/3 added drm_atomic_colorop_check() rejecting inactive-pipeline colorop
  updates. Our automated review did not predict that the new check would break IGT
  tests that previously exercised colorop property setting without an active pipeline.

Review action:
- When a patch adds a new -EINVAL rejection to `drm_atomic_check_only()` for
  colorop or similar new DRM object types, flag [CONCERN] that existing IGT tests
  exercising that object type may fail if they set properties without first
  activating a color pipeline.
- Note that CI full runs should be checked for `kms_color_pipeline` and
  `kms_properties@colorop-properties-atomic` regressions.

False-positive guards:
- Do not flag if the series includes companion IGT test updates that accommodate
  the new check.
- Do not flag for rejections that are clearly unreachable by existing tests (e.g.
  error paths that require hardware-specific configurations with no IGT coverage).
- One data point; treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0250: TRACE_EVENT `__dynamic_array` — do not add a redundant `__field` for its length

Status: draft
Scope: general
Triggers:
- A trace event (TRACE_EVENT or DECLARE_EVENT_CLASS) declares both a
  `__dynamic_array(type, name, len)` field AND a separate `__field(unsigned int, len)`
  (or similar) that mirrors the array's length
- `TP_fast_assign` sets `__entry->len = len` in addition to
  `memcpy(__get_dynamic_array(name), buf, len)`
- `TP_printk` uses `__entry->len` to pass the length to `__print_hex()` or similar

Maintainer evidence:
- Steven Rostedt (TRACING maintainer) on
  [PATCH v4 1/2] serial: qcom-geni: trace: Add tracepoint support for Qualcomm GENI serial
  (<20260526-add-tracepoints-for-qcom-geni-serial-v4-0-e94fbaec0232@oss.qualcomm.com>,
  2026-05-29): "No need to save the length of the dynamic array in __entry->len because
  it's already saved in the metadata of the dynamic array that is stored on the buffer."
  Suggested using `__get_dynamic_array_len(data)` in TP_printk instead.
  Net gain: 4 bytes saved per event in the ring buffer plus a few cycles.
  Our automated review did not flag this (missed-by-us).

Review action:
- Flag [MINOR] when a trace event declares a `__dynamic_array` AND a separate
  `__field` storing that same array's length, with `__entry->len` used in TP_printk.
- The correct pattern is:
    TP_STRUCT__entry(__string(name, ...) __dynamic_array(u8, data, len))
    TP_fast_assign(__assign_str(name); memcpy(__get_dynamic_array(data), buf, len);)
    TP_printk("... len=%u data=%s", __get_dynamic_array_len(data),
              __print_hex(__get_dynamic_array(data), __get_dynamic_array_len(data)))
- Suggest removing the redundant `__field` and replacing `__entry->len` with
  `__get_dynamic_array_len(<array_name>)` everywhere in TP_printk.

False-positive guards:
- Do not flag if the `__field(len)` is used for a purpose other than shadowing the
  dynamic array length (e.g., it encodes a logical length distinct from the actual
  stored array size).
- Do not flag if the dynamic array size differs from the logical length stored in
  `__entry->len` (i.e., the array is over-allocated intentionally).
- One data point from a senior subsystem maintainer; treat as draft.

Confidence: medium
Last updated: 2026-05-29

### MEM-0251: ARM/Coresight CTI — vendor-extension header must be folded into `coresight-cti.h`; separate file causes circular dependency

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/coresight-cti*
Triggers:
- A patch introduces a new vendor-specific header (e.g. `qcom-cti.h`) inside
  `drivers/hwtracing/coresight/` that includes `coresight-cti.h`
- `coresight-cti.h` in turn needs register definitions or inline helpers from the
  vendor header, creating a circular include dependency
- The vendor header contains only register-offset `#define` constants and a small
  inline translation function (`cti_qcom_reg_off()` or equivalent)

Maintainer evidence:
- Leo Yan (ARM/Coresight reviewer) on [PATCH v9 2/4] coresight: cti: use __reg_addr()
  helper for register access (coresight@lists.linaro.org, 2026-05-29): identified
  circular dependency between `coresight-cti.h` and `qcom-cti.h`; proposed folding
  all QCOM CTI register defines and the `cti_qcom_reg_off()` inline into
  `coresight-cti.h` and deleting the separate file. Author (Yingchao Deng) agreed
  to apply this approach to patches 02/03 (same thread). Our automated review missed
  the circular dependency and the preferred code-organisation choice (missed-by-us).

Review action:
- Flag [CONCERN] when a new vendor-extension header inside `drivers/hwtracing/coresight/`
  includes `coresight-cti.h` (or other coresight subsystem headers) while the main
  header also needs types/functions from the vendor header; this creates a circular
  include dependency.
- Suggest folding all vendor-specific `#define` constants and small inline helpers
  directly into the existing subsystem header (`coresight-cti.h`) under a clearly
  delimited `/* <VENDOR> CTI extension */` block, and removing the separate file.
- If the separate file is kept, verify there is no include cycle: the vendor header
  must not include the header that also includes it.

False-positive guards:
- Do not flag a separate vendor header that does NOT include any coresight subsystem
  headers and is only included by the `.c` file (no circular risk).
- Do not flag large vendor-extension files (hundreds of lines of driver code) where
  folding into the main header would be impractical.

Confidence: medium
Last updated: 2026-05-29

### MEM-0252: ARM/Coresight CTI — do not write to CLAIMSET/CLAIMCLR for Qcom CTI; bypass claim operations via helpers

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/coresight-cti*
Triggers:
- A Qualcomm CTI patch clears a stale CLAIMSET value during probe by writing 0 (or
  any value) directly to the `CORESIGHT_CLAIMSET` register on Qcom hardware
- The commit comment states the hardware CLAIMSET is incorrectly initialized to a
  non-zero value and clears it to reflect the unclaimed state
- A reviewer questions whether writing to CLAIMSET/CLAIMCLR is the right approach
  for hardware that does not implement CoreSight Claimtag functionality

Maintainer evidence:
- Leo Yan (ARM/Coresight reviewer) on [PATCH v9 3/4] coresight: cti: add Qualcomm
  extended CTI identification and quirks (coresight@lists.linaro.org, 2026-05-28):
  "I don't think the CTI driver should clear the external claim bit as this totally
  break the protocol defined in PSCI." Proposed creating claim-bypass helpers
  (`cti_clear_self_claim_tag()`, `cti_claim_device()`, `cti_unclaim_device_unlocked()`)
  that check `drvdata->is_qcom_cti` and return early (skipping all claim register
  operations) rather than writing to any claim register. Author (Yingchao Deng)
  agreed to use the helper-bypass approach (same thread, 2026-05-29). Our automated
  review correctly identified the write-0-to-CLAIMSET concern but incorrectly
  suggested using CLAIMCLR instead; the preferred fix is to skip claim operations
  entirely (confirmed, but fix suggestion was wrong).

Review action:
- Flag [CONCERN] when a Qcom CTI probe path writes any value to `CORESIGHT_CLAIMSET`
  or `CORESIGHT_CLAIMCLR` as a workaround for non-standard claim register initialization.
- The preferred fix is NOT to write to CLAIMCLR; it is to bypass claim operations
  entirely for Qcom CTI by wrapping each `coresight_claim_device()`,
  `coresight_disclaim_device_unlocked()`, and `coresight_clear_self_claim_tag()` call
  site with a Qcom-aware helper that returns early (no-ops) when `drvdata->is_qcom_cti`.
- Note that writing to CLAIMSET/CLAIMCLR on hardware that may follow PSCI claim
  semantics violates the PSCI protocol; even on non-standard hardware this is risky.

False-positive guards:
- Do not flag writes to claim registers that are part of the standard CoreSight
  claim/disclaim protocol on non-Qcom hardware.
- Do not apply to non-CTI coresight drivers unless a similar non-standard
  CLAIMSET-initialization quirk is confirmed for that hardware variant.

Confidence: medium
Last updated: 2026-05-29

### MEM-0255: Test binary using fork()+pipes — unused pipe ends must be closed after fork()

Status: draft
Scope: file-pattern:tools/perf/tests/shell/coresight/*.c
Triggers:
- A user-space test binary creates two or more pipes and then calls `fork()`
- After `fork()`, neither child nor parent closes the unused ends of the pipes
  (e.g., child keeps `a_to_b[0]` and `a_to_b[1]`; parent keeps `b_to_a[0]`
  and `b_to_a[1]`)
- Both processes eventually call `read()` or `write()` on their respective pipe ends

Maintainer evidence:
- Sashiko AI review on patch 2/2 of 20260526-james-cs-context-tracking-fix-v1-0
  (perf test cs-etm: Test thread attribution, 2026-05-26): "If one process exits
  prematurely via exit(1) upon an unexpected read or write failure, the surviving
  process will block indefinitely in read_block() because it still holds a write
  end of the pipe open itself." Arnaldo Carvalho de Melo (perf maintainer) forwarded
  the Sashiko review with "some looks legitimate", giving partial human endorsement.
  Our automated review missed this deadlock risk entirely (missed-by-us).

Review action:
- Flag [CONCERN] when a test workload forks and then uses pipe I/O but neither
  process closes its inherited unused pipe ends immediately after `fork()`.
- The standard pattern is: child closes write end of A-to-B and read end of B-to-A;
  parent closes read end of A-to-B and write end of B-to-A.
- Failure to close unused ends means EOF is never delivered on premature exit,
  potentially hanging the test harness indefinitely.

False-positive guards:
- Do not flag if the code already closes the unused pipe ends immediately after
  the `if (!child_pid)` / `else` branch in both parent and child.
- Do not apply to pipes used only for one-directional signalling where the write
  end is intentionally held by both processes as a reference count.
- One partial human endorsement (Arnaldo forwarding the finding); treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0256: Test binary functions grep'd by name from shell script must have external linkage

Status: draft
Scope: file-pattern:tools/perf/tests/shell/coresight/*.c
Triggers:
- A user-space test binary declares functions with `static` linkage
- A companion shell script (`perf script` or `grep`/`nm`) checks for those
  exact function names in the symbol table or perf report output
- The functions are decorated with `noinline` but are otherwise `static`

Maintainer evidence:
- Sashiko AI review on patch 2/2 of 20260526-james-cs-context-tracking-fix-v1-0
  (perf test cs-etm: Test thread attribution, 2026-05-26): "Since they are declared
  with internal linkage, the compiler or linker might suffix the symbols (e.g.,
  thread1.lto_priv.0), inline them despite noinline, or omit them from the symbol
  table entirely. If omitted, the greps will fail." Arnaldo forwarded the review
  with "some looks legitimate". Our automated review did not flag the linkage concern
  (missed-by-us).

Review action:
- Flag [MINOR] when a coresight test binary declares `static noinline` functions
  whose names are hard-coded in a companion shell script that searches perf output
  for those exact names.
- Suggest removing the `static` qualifier to give the functions external linkage,
  ensuring their names are preserved in the symbol table under all optimization
  and LTO configurations.
- Alternatively, suggest using `__attribute__((visibility("default")))` if a global
  namespace is undesirable.

False-positive guards:
- Do not flag if the functions already have external linkage (no `static` keyword).
- Do not flag if the companion script uses a pattern match tolerant of symbol
  suffixes (e.g. `grep '^thread[12]'` would be robust to simple suffixes).
- One partial human endorsement (Arnaldo); treat as draft until a second maintainer
  or CI failure confirms the concern.
- Do not apply to functions that are purely internal and not referenced by any
  companion test script.

Confidence: low
Last updated: 2026-05-29

### MEM-0263: ARM/Coresight CTI — `cti_allocate_trig_con()` bitmask sized by `nr_trig_max` needs in/out-sigs bounds check

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/coresight-cti-platform.c
Triggers:
- A patch changes `cti_allocate_trig_con()` to allocate trigger-group bitmasks using
  `drvdata->config.nr_trig_max` (the device-reported maximum) instead of a compile-time
  constant (e.g. `CTIINOUTEN_MAX`)
- The function accepts `in_sigs` / `out_sigs` caller-supplied counts
- No guard ensures `in_sigs` and `out_sigs` are ≤ `nr_trig_max` before the bitmask
  is allocated and later used with those counts as the bit range

Maintainer evidence:
- Leo Yan (ARM/Coresight reviewer) on [PATCH v9 1/4] coresight: cti: Convert trigger
  usage fields to dynamic (coresight@lists.linaro.org, 2026-05-29): "AI review suggests
  that when in_sigs / out_sigs bigger than nr_trig_max, it might access memory
  out-of-boundary (see cti_plat_read_trig_group()). It is good to add a check."
  Proposed explicit guard returning NULL when either count exceeds nr_trig_max, with
  dev_err(). Author (Yingchao Deng) agreed to add the check. Our automated review
  missed this bounds-check gap (missed-by-us).

Review action:
- Flag [BUG] when `cti_allocate_trig_con()` (or a similar dynamic-sized allocator for
  trigger groups) takes caller-supplied signal counts and sizes bitmasks to `nr_trig_max`
  without first checking that the caller counts do not exceed `nr_trig_max`.
- The required guard is:
    if (in_sigs > n_trigs || out_sigs > n_trigs) {
        dev_err(dev, "trigger signal out of range...\n");
        return NULL;
    }
- This guard prevents out-of-bounds bitmap access in `cti_plat_read_trig_group()` and
  callers that iterate up to `in_sigs` / `out_sigs` bit positions.

False-positive guards:
- Do not flag if a compile-time constant cap (e.g. `CTIINOUTEN_MAX`) is still used as
  the bitmask size and `in_sigs`/`out_sigs` are verified ≤ that constant elsewhere.
- Do not flag if the calling context already enforces the upper bound on `in_sigs` and
  `out_sigs` before passing them into the allocator.

Confidence: low
Last updated: 2026-05-29

### MEM-0264: ARM/Coresight CTI — new banked sysfs register attrs require `Documentation/ABI/testing/sysfs-bus-coresight-devices-cti` update

Status: draft
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/coresight-cti-sysfs.c
Triggers:
- A patch adds new sysfs attributes to the coresight CTI driver (e.g. banked
  `triginstatus[1-3]`, `trigoutstatus[1-3]`, `inen[128-255]`, `outen[128-255]`)
- The `Documentation/ABI/testing/sysfs-bus-coresight-devices-cti` file is not updated
  with `What:`, `Date:`, `KernelVersion:`, `Contact:`, and `Description:` entries for
  the new knobs

Maintainer evidence:
- Leo Yan (ARM/Coresight reviewer) on [PATCH v9 4/4] coresight: cti: expose banked
  sysfs registers for Qualcomm extended CTI (coresight@lists.linaro.org, 2026-05-29):
  "AI tool reminds to update Documentation/ABI/testing/sysfs-bus-coresight-devices-cti,
  you might need to add description with a new patch." Provided an example ABI entry
  for `trigoutstatus[1-3]` and asked for documentation of all new knobs. Our automated
  review flagged only the MAINTAINERS warning (checkpatch); the ABI doc omission was
  missed (missed-by-us).

Review action:
- Flag [MINOR] when a patch adds new CTI sysfs attributes and
  `Documentation/ABI/testing/sysfs-bus-coresight-devices-cti` is not updated.
- Each new attribute (or attribute group, e.g. `triginstatus[1-3]`) requires a
  `What:` / `Date:` / `KernelVersion:` / `Contact:` / `Description:` block.
- Recommend adding the ABI documentation as a separate patch or an amendment to the
  patch that introduces the attributes.

False-positive guards:
- Do not flag if the patch is a rename or removal of an existing documented attribute.
- Do not flag if the new attributes are explicitly listed as internal or debugfs-only
  (not exposed via the `sysfs-bus-coresight-devices-cti` ABI file).
- One reviewer data point; treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0265: `tools/` user-space test binary must not include `<linux/compiler.h>` — use `__attribute__((noinline))` directly

Status: draft
Scope: file-pattern:tools/perf/tests/shell/coresight/*.c
Triggers:
- A new user-space test binary under `tools/` includes `<linux/compiler.h>` solely
  to use the `noinline` macro (or similar kernel-only macro)
- No other test binary in the same directory uses kernel headers; the directory
  Makefile does not specify `-I tools/include/`
- The binary can fail to build when compiled outside the perf top-level Makefile tree

Maintainer evidence:
- Sashiko AI review (sashiko-bot@kernel.org, 2026-05-26) on patch 2/2 of
  20260526-james-cs-context-tracking-fix-v1-0 (context_switch_loop.c): "Is it safe to
  include the kernel-specific header <linux/compiler.h> in this user-space test tool
  to use the noinline macro? If the test is compiled standalone outside of the perf
  Makefile tree, the build might fail." Rated [Low].
- Our automated review independently flagged [MINOR] for the same issue, noting the
  Makefile already uses `-O0` making `noinline` unnecessary, and that no peer test
  binary uses kernel headers. Two independent sources confirm the finding.
- Arnaldo Carvalho de Melo (perf maintainer, 2026-05-29): forwarded the Sashiko review
  with "some looks legitimate." Partial human endorsement.

Review action:
- Flag [MINOR] when a new test binary under `tools/` includes `<linux/compiler.h>`
  only for a macro like `noinline`.
- Preferred fix: replace `#include <linux/compiler.h>` with a local definition
  `#define noinline __attribute__((noinline))`, which is portable to any C compiler.
- Or simply drop the `noinline` attribute if the Makefile already compiles with `-O0`.
- Cross-check all peer test binaries in the same directory; if none use kernel headers,
  flag the inconsistency.

False-positive guards:
- Do not flag if the `tools/include/` path is explicitly added to the Makefile for
  this binary, making `<linux/compiler.h>` resolvable in all build contexts.
- Do not flag if a peer binary in the same directory already includes kernel headers
  under an established convention.
- Do not apply to files under `tools/include/` itself (those are the kernel-header
  mirrors intended for `tools/` consumers).

Confidence: low
Last updated: 2026-05-30

### MEM-0266: drm/msm Adreno GPU series must base on msm-next-robclark, not linux-next

Status: draft
Scope: subsystem:drm/msm file-pattern:drivers/gpu/drm/msm/adreno/
Triggers:
- A drm/msm Adreno GPU or GMU series fails to apply against linux-next
- The cover letter or base-commit trailer declares msm-next-robclark (e.g.
  `base-commit: <hash>` plus "Rebased on msm-next-robclark@<sha>") as the
  staging-tree base
- The apply failure is caused by a binding or driver context that has landed
  in Rob Clark's msm-next tree but not yet in linux-next

Maintainer evidence:
- Alexander Koskovich v7 Adreno 810 series (lore: 20260528-adreno-810-v7-0-7fe7fdd97fc2@pm.me,
  2026-05-28): patch 2/6 "dt-bindings: display/msm/gpu: Document Adreno 810 GPU" failed
  against linux-next next-20260527 because the qcom,adreno-44070001 const introduced by an
  earlier msm-next-robclark commit was absent from gpu.yaml. Cover letter stated
  "Rebased on msm-next-robclark@d0f39fc" with base-commit d32ccd45. Our automated review
  correctly identified the apply failure and root cause; pattern confirmed by maintainer
  Krzysztof Kozlowski issuing Reviewed-by on patch 2/6 in the same thread
  (krzk@kernel.org, 2026-05-29, confirming the DT binding content is correct).

Review action:
- When a drm/msm Adreno series fails to apply against linux-next and the cover letter
  declares msm-next-robclark as the base, name msm-next-robclark
  (https://gitlab.freedesktop.org/robclark/kernel) as the required rebase target in the
  CANNOT APPLY section.
- Note in the report that once the prerequisite lands in linux-next the series can be
  re-reviewed end-to-end.
- Flag [CONCERN] if the series lacks a machine-readable Depends-on: or
  Prerequisite-patch-id: trailer pointing to the missing msm-next-robclark commit,
  so reviewers and CI can resolve the dependency automatically.

False-positive guards:
- Do not apply to non-Adreno drm/msm patches; other MSM sub-drivers may use
  different upstream trees.
- Do not flag if the series applies cleanly against linux-next (the base-commit may
  already be merged).
- This entry becomes stale once the referenced prerequisite merges into linux-next
  and a new rolling base is adopted.

Confidence: low
Last updated: 2026-05-30

### MEM-0270: `irq_chip_*_parent()` helpers do not check `parent_data` for NULL — explicit guard required when hierarchy is trimmed

Status: draft
Scope: general file-pattern:drivers/pinctrl/qcom/pinctrl-msm.c
Triggers:
- A patch replaces open-coded parent irqchip delegation (e.g. `d->parent_data->chip->irq_eoi(d->parent_data)`) with an `irq_chip_*_parent()` helper (e.g. `irq_chip_eoi_parent()`, `irq_chip_mask_parent()`)
- The irqchip registers a single callback that handles both wakeup-capable and non-wakeup GPIOs
- Non-wakeup GPIOs have their parent hierarchy trimmed via `irq_domain_disconnect_hierarchy()` + `irq_domain_trim_hierarchy()`, leaving `d->parent_data == NULL`

Maintainer evidence:
- Linus Walleij (pinctrl maintainer) applied patch
  20260529-pinctrl_msm_irq_eoi-v2-1-7edd050a46f6@oss.qualcomm.com with "Patch applied!"
  The patch preserves an explicit `if (d->parent_data)` guard before calling
  `irq_chip_eoi_parent(d)` because the helper dereferences `parent_data` unconditionally.
  Both Dmitry Baryshkov (Reviewed-by) and Linus Walleij (applied) accepted the guard as
  essential. Our automated review correctly identified this guard as necessary.

Review action:
- When a patch introduces `irq_chip_*_parent()` and the irqchip serves interrupts whose
  parent hierarchy may be trimmed (non-wakeup GPIOs, hierarchy disconnect patterns),
  verify an explicit `if (d->parent_data)` (or equivalent) guard is present before the
  helper call.
- If the guard is absent, flag [BUG]: the helper will NULL-dereference for non-wakeup
  interrupts at runtime.
- If the guard is present, confirm this matches the commit message explanation — the
  message should note that `irq_chip_*_parent()` does not perform the NULL check
  internally.

False-positive guards:
- Do not flag if all interrupts registered with the irqchip are guaranteed to have a
  valid parent hierarchy (e.g. the domain never calls `irq_domain_disconnect_hierarchy()`).
- Do not flag other `irq_chip_*_parent()` usages where the irqchip is not shared
  between wakeup and non-wakeup interrupt sources.

Confidence: medium
Last updated: 2026-05-30

### MEM-0274: pinctrl — mutual exclusivity between a software pseudo-function and physical GPIO functions must be enforced at `pinconf_set` time

Status: draft
Scope: subsystem:pinctrl
Triggers:
- A patch adds a software-only pseudo-function (e.g. `PMIC_GPIO_FUNC_INDEX_LEVEL_SHIFTER`)
  to a pinctrl driver where the pin is physically shared between the pseudo-function and
  real GPIO output functions
- The `pin_config_set` (or `pin_config_group_set`) handler sets `pad->is_enabled = true`
  without first verifying that `pad->function` is not the pseudo-function
- No runtime check prevents both the physical GPIO output buffer and the external
  hardware controlled by the pseudo-function from being active simultaneously

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 4/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com:
  "[High] If a device tree simultaneously assigns a normal function to a pin and
  enables the level shifter on its associated group, pad->function will be NORMAL.
  Since the check `if (pad->function != PMIC_GPIO_FUNC_INDEX_LEVEL_SHIFTER)` will
  pass, it will set pad->is_enabled = true, potentially causing both the physical GPIO
  output buffer and the external level shifter to drive the pin concurrently. Could
  this result in electrical overstress?" Our automated review did not flag this
  (missed-by-us).

Review action:
- Flag [CONCERN] when a new software pseudo-function shares physical pins with real
  GPIO functions and the `pin_config_set` path does not enforce that the pseudo-function
  and real GPIO functions are mutually exclusive at the pad level.
- Suggest adding an error return or warning in `pin_config_set` / `pin_config_group_set`
  when the pad is already configured with a conflicting function, and documenting the
  exclusivity constraint.

False-positive guards:
- Do not flag if the hardware architecture physically prevents concurrent activation
  (e.g. the pad is driven to high-Z when the pseudo-function is selected at the hardware
  level, independent of the driver state).
- Do not flag if the DT schema already enforces mutual exclusivity (e.g. the level-shifter
  group property requires `function = "level-shifter"` and rejects all other function values).
- One AI-reviewer data point; treat as draft.

Confidence: low
Last updated: 2026-05-30

### MEM-0288: fastrpc bug-fix patch — verify the defect is not already fixed in linux-next before reviewing

Status: draft
Scope: subsystem:fastrpc file-pattern:drivers/misc/fastrpc.c
Triggers:
- A patch fixes a use-after-free, refcount race, or lifecycle bug in
  drivers/misc/fastrpc.c
- The review is run against a linux-next base that postdates several fastrpc
  bug-fix cycles (e.g., 2026 or later)

Maintainer evidence:
- Srinivas Kandagatla (fastrpc/misc maintainer) on
  <20260526104243.27596-1-kipreyyy@gmail.com> (linux-arm-msm, 2026-05-30):
  "Thanks for the patch, have you tested this on linux-next this should be fixed
  with [b01bf21ae7e7c4c7cd4f1c8419bafc1e04c008e4]?" — asking whether
  the submitted bug fix is superseded by an already-queued linux-next commit.
  Our automated review raised [CONCERN] and [MINOR] without checking whether the
  defect was already addressed upstream (missed-by-us).

Review action:
- Before raising a [CONCERN] or [BUG] on a fastrpc use-after-free or refcount
  lifecycle patch, run `git log --oneline drivers/misc/fastrpc.c | head -20` on
  the review base to check for recently queued fixes addressing the same UAF or
  lifetime issue.
- If a recent linux-next commit (e.g. b01bf21ae7e7) already fixes the same
  defect class, flag [CONCERN]: the patch may be redundant and the author should
  verify against the latest linux-next before resubmitting.
- Reference the upstream commit hash in the finding so the author can check
  whether it covers their scenario.

False-positive guards:
- Do not suppress the review entirely; the patch may address a different code
  path or a residual bug not covered by the upstream fix.
- Do not apply outside drivers/misc/fastrpc.c without separate confirming evidence.
- Do not flag if the patch's cover letter or commit body already acknowledges the
  upstream fix and explains why additional change is needed.

Confidence: low
Last updated: 2026-05-31

### MEM-0291: Qcom GENI SE — `geni_se_resources_activate()` does not restore OPP rate on resume; subsequent transfers may see zero-voltage state

Status: draft
Scope: subsystem:spi subsystem:i2c subsystem:uart file-pattern:drivers/spi/spi-geni-qcom.c file-pattern:drivers/i2c/busses/i2c-qcom-geni.c
Triggers:
- A patch replaces explicit `geni_icc_enable()` + `geni_se_resources_on()` +
  `dev_pm_opp_set_rate(mas->dev, mas->cur_sclk_hz)` in `runtime_resume` with a
  single call to `geni_se_resources_activate()`
- `geni_se_resources_activate()` does not call `dev_pm_opp_set_rate()` to restore
  the OPP/performance state vote

Maintainer evidence:
- Sashiko-bot on [PATCH v2 3/4] "spi: qcom-geni: Use resources helper APIs in
  runtime PM functions"
  (20260530-enable-spi-on-sa8255p-v2-0-17574601bd63@oss.qualcomm.com, 2026-05-30):
  "[High] geni_se_resources_deactivate() still drops OPP to 0 on suspend, but
  geni_se_resources_activate() does not restore it. Subsequent transfers bypass the
  re-vote because the fast-path check `if (clk_hz == mas->cur_speed_hz) return 0`
  skips set_clock if the request matches the cached speed." Our automated review
  missed this correctness issue (missed-by-us).

Review action:
- When a patch removes an explicit `dev_pm_opp_set_rate(dev, cur_rate)` call from
  `runtime_resume` and delegates to a helper, verify the helper restores the OPP rate.
- Flag [BUG] if the new suspend path still votes rate to 0 but the new resume path
  does not restore it, AND the data-transfer path has a speed-equality fast-path that
  silently skips re-voting.
- Suggest either: (a) adding `dev_pm_opp_set_rate(dev, cur_rate)` to
  `geni_se_resources_activate()`, or (b) calling it explicitly in `runtime_resume`
  after the helper.

False-positive guards:
- Do not flag if `geni_se_resources_activate()` already internally calls
  `dev_pm_opp_set_rate()` with a non-zero rate on resume.
- Do not flag if the driver does not use OPP at all (e.g. SCMI-managed platforms
  where the helper fully handles power-domain voting and `se->clk` is absent).

Confidence: low
Last updated: 2026-05-31

### MEM-0292: Qcom GENI SPI — GPI DMA path (`setup_gsi_xfer`) must use the same clock/rate abstraction as the non-DMA path; hard-coded `get_spi_clk_cfg` breaks SCMI platforms

Status: draft
Scope: subsystem:spi file-pattern:drivers/spi/spi-geni-qcom.c
Triggers:
- A patch introduces a `set_rate` function pointer (or similar abstraction) in a
  per-platform descriptor to allow SCMI-based platforms to skip `clk_round_rate()` /
  `geni_se_clk_freq_match()` when setting the SPI clock rate
- The abstraction is wired only in the non-DMA transfer path (e.g. `setup_se_xfer`)
  but `setup_gsi_xfer()` (GPI DMA path) continues to call `get_spi_clk_cfg()` directly
- SCMI platforms leave `se->clk` NULL or ERR_PTR, so `clk_round_rate()` inside
  `get_spi_clk_cfg()` will panic when GPI DMA transfers are attempted

Maintainer evidence:
- Sashiko-bot on [PATCH v2 4/4] "spi: qcom-geni: Enable SPI on SA8255p Qualcomm
  platforms" (20260530-enable-spi-on-sa8255p-v2-0-17574601bd63@oss.qualcomm.com,
  2026-05-30): "[High] setup_gsi_xfer() still hardcodes get_spi_clk_cfg(), bypassing
  the new set_rate abstraction. On SA8255P, se->clk is uninitialized (NULL); this
  breaks all SPI transfers using GPI DMA." Our automated review raised [MINOR] for
  an unrelated NULL-guard inconsistency but did not flag the GPI DMA bypass
  (missed-by-us).

Review action:
- When a patch adds a per-platform rate-setting abstraction (function pointer or
  helper), check ALL transfer entry points — not just the non-DMA path.
- Flag [BUG] when `setup_gsi_xfer()` (or any other transfer path that calls
  `get_spi_clk_cfg()`) is not updated to use the new abstraction while SCMI
  platforms rely on it to avoid touching `se->clk`.
- The fix is to route `setup_gsi_xfer()` through the same `set_rate` abstraction
  (or guard its `get_spi_clk_cfg()` call behind an `if (se->clk)` check that skips
  it on SCMI platforms).

False-positive guards:
- Do not flag if GPI DMA is not supported for the new platform (e.g. the SCMI
  platform descriptor explicitly leaves the DMA ops NULL and probe code refuses
  to use GPI DMA on that platform).
- Do not flag if `setup_gsi_xfer()` already calls through the rate-setting abstraction
  after the patch is applied.

Confidence: medium
Last updated: 2026-05-31
