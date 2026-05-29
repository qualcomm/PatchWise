# Review Memory — Patch Scope (draft)

### MEM-0060: Large PHY-mode-framework patches must be split into logical incremental steps

Status: draft
Scope: subsystem:phy/qualcomm
Triggers:
- A single driver patch adds all of: new framework structs for per-mode
  configuration, a new probe path, new per-instance clock/reset helpers, and a
  new xlate callback, all to support a complex multi-topology PHY provider
- The patch is 400+ lines and the commit body describes the changes in broad
  terms without listing what each code block does

Maintainer evidence:
- Manivannan Sadhasivam on RFC 3/4 of the qmp-pcie Glymur Gen5x8 link-mode
  series (linux-arm-msm, 2026-05-04): "This patch does too many things at once.
  You should split the changes logically to help human reviewers." The v2 series
  split the equivalent patch across four separate patches (struct/constant
  additions, pipe-clock helper refactoring, multi-PHY probe path, platform
  config tables).

Review action:
- Flag [CONCERN] when a single PHY driver patch introduces new framework structs
  AND a new probe path AND new per-instance resource helpers all in one commit.
- Suggest splitting along logical boundaries: (1) new structs/constants,
  (2) shared helper refactoring, (3) new probe/xlate path, (4) per-platform
  config tables, (5) DTS wiring.

False-positive guards:
- Do not flag small patches (< ~150 lines) that add a new platform config
  without changing probe logic.
- Do not flag simple compatible-string or config-table additions that reuse
  all existing structs and probe paths without modification.
- Do not apply outside PHY/clk-style framework drivers without additional
  maintainer evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0068: Standalone export-only patches without a consumer in the same series are NAKed

Status: draft
Scope: general
Triggers:
- A patch adds only EXPORT_SYMBOL_GPL() or EXPORT_SYMBOL() to an existing
  function, with no other code change
- The patch is submitted as a standalone single-patch series (or as patch 1/1)
  without any in-tree user of the newly exported symbol also in the series

Maintainer evidence:
- Konrad Dybcio on [PATCH v3] genirq: Export irq_can_set_affinity()
  (kernel@oss.qualcomm.com, 2026-05-11): "patches that only export symbols
  are generally going to be NAKed - you should send the user of that symbol
  together in a series."
- Jeff Johnson on the same thread: "Sounds reasonable. Please send a v4 series
  that adds the ath12k patch." -- second independent confirmation.
  Author acknowledged and committed to including the consumer patch in v4.
  Our automated review gave READY TO APPLY and missed the series-organisation
  issue entirely (missed-by-us).

Review action:
- Flag [CONCERN] when a patch adds only an EXPORT_SYMBOL_GPL() or EXPORT_SYMBOL()
  macro to an existing function and no patch in the same series introduces a
  consumer of that newly exported symbol.
- Suggest restructuring as a two-patch series: (1) export patch, (2) the first
  in-tree consumer (e.g. the driver that calls the function). The consumer patch
  provides reviewers with evidence that the export is safe, necessary, and used
  correctly.

False-positive guards:
- Do not flag if a later patch in the same series introduces a consumer of the
  export (the consumer need not be patch 2; it just must be present in the series).
- Do not flag if the commit body explicitly states the export is requested by a
  downstream/out-of-tree driver and the maintainer has already acknowledged the
  out-of-tree use case; this pattern is rare and maintainer-specific.
- Do not flag export patches that are part of a larger refactoring series where
  the function is being moved between compilation units and the export is a
  side-effect of that relocation rather than a new API surface.

Confidence: low
Last updated: 2026-05-26

### MEM-0097: "While at it" in commit body signals separable generic-infrastructure change — recommend patch split

Status: draft
Scope: general
Triggers:
- A commit body contains the phrase "While at it" (or "while at it") to introduce an
  additional change beyond the primary device-specific addition
- The additional change is a generic infrastructure modification (e.g. making a resource
  optional, adding a new optional property) that affects all users of the driver, not only
  the platform being added

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-18) on patch 2/2 "drivers:
  remoteproc: qcom_q6v5_pas: Add support for IPQ9650 CDSP": "the phrase While at it is
  informal and not appropriate for kernel commit messages ... bundling multiple independent
  changes makes bisection and review harder". The commit mixed an IPQ9650-specific device
  struct with generic changes (optional XO clock, mx-supply support). Our automated review
  independently detected the same [MINOR] issue (confirmed pattern from two sources).

Review action:
- Flag [MINOR] when a commit body uses "While at it" to introduce a generic infrastructure
  change mixed with a device-specific addition.
- Suggest splitting into: (1) a preparatory patch for the generic infrastructure change and
  (2) the device-specific patch that relies on it.
- If kept as one patch, require the commit subject to reflect all changes introduced.

False-positive guards:
- Do not flag "While at it" introducing a trivially local change (e.g. a comment fix or
  spelling correction) with no impact on other users.
- Do not flag if the additional change is already mentioned in the patch subject and scope.
- Do not flag if the series cover letter explicitly justifies combining the changes (e.g.
  the infrastructure change has no other user yet and splitting adds noise).

Confidence: low
Last updated: 2026-05-26

### MEM-0139: Preparatory patch must not contain logic deferred to a later patch in the series description

Status: draft
Scope: general
Triggers:
- A patch series has patch N described as preparatory refactoring and patch N+1
  described as implementing a specific new behaviour
- Patch N contains a code block that implements the new behaviour described in patch N+1
  (e.g. an early-exit guard, a list-traversal change, or a new condition that only
  makes sense once the subsequent feature patch is applied)
- The patch N commit message does not mention this additional logic

Maintainer evidence:
- Suzuki K Poulose (ARM/Coresight maintainer) on patch 14/27 of v11 series
  (20260501-arm_coresight_path_power_management_improvement, 2026-05-06): flagged
  the nd == last early-exit hunk in coresight_enable_path() as belonging to patch 15
  (range support), not patch 14 (move helper disabling). Leo Yan agreed and confirmed
  the hunk should move to patch 15, which introduces range traversal making the
  CORESIGHT_DEV_TYPE_SINK assumption invalid.
- Our automated review missed the mixed-responsibility concern (missed-by-us).

Review action:
- Flag [MINOR] when a preparatory patch contains a hunk whose rationale only becomes
  clear in the context of a later patch in the series.
- Suggest moving the hunk into the later patch where it logically belongs, or splitting
  the current patch to make all included logic self-contained and described in the
  commit message.

False-positive guards:
- Do not flag forward-compatible no-op changes (e.g. renaming a variable) that are
  genuinely preparatory and self-contained even if they are only exercised by a later
  patch.
- Do not flag when the preparatory patch commit body explicitly calls out the hunk
  as groundwork for a named later patch.

Confidence: low
Last updated: 2026-05-26

### MEM-0240: Overly broad `prerequisite-patch-id` list must not gate an entire series on unrelated DT infrastructure prerequisites

Status: draft
Scope: subsystem:media file-pattern:drivers/media/platform/qcom/iris/
Triggers:
- A patch series cover letter lists `prerequisite-patch-id` tags for a DT
  infrastructure series (e.g. videocc, camcc) whose commits are only required
  by a subset of patches (typically the DT patches at the end of the series)
- The driver patches (non-DT) are independent of those prerequisites and can
  be reviewed and applied before the prerequisite DT series merges
- The maintainer asks why unrelated patches are gated on the prerequisite

Maintainer evidence:
- Bryan O'Donoghue (QUALCOMM MEDIA PLATFORM maintainer) on
  [PATCH v8 0/5] media: iris: add support for purwa platform (linux-media,
  2026-05-29): asked "why are camcc patches prerequisites for vidc?" and stated
  he would "drop all of that stuff" since the driver patches do not depend on it
  and should not be gated by it.
- Wangao Wang (author, same thread): confirmed only the two DT patches (patches
  4/5 and 5/5) depend on the videocc series; the driver patches (1/5–3/5) are
  ready to apply independently.
  Our automated review listed the missing prerequisites as the root cause of the
  apply failure without questioning whether all series patches actually needed them
  (missed-by-us).

Review action:
- When a series lists `prerequisite-patch-id` or `prerequisite-change-id` tags,
  check whether all patches actually require all listed prerequisites.
- Flag [CONCERN] if only a subset of patches (e.g. DT patches at the end) depend
  on the prerequisite series and the driver patches are independently applicable.
- Suggest limiting the `prerequisite-*` tags to only those patches that directly
  depend on the external series, or splitting the series so driver-only patches
  can be merged without waiting for the DT infrastructure.

False-positive guards:
- Do not flag if every patch in the series genuinely requires the prerequisite.
- Do not flag when the maintainer has already acknowledged the gating as intentional.
- Do not apply outside Qualcomm subsystem series without confirming the same pattern.

Confidence: low
Last updated: 2026-05-29

### MEM-0246: Functional API change must not be mixed with parameter renames or cleanup in the same patch

Status: draft
Scope: general
Triggers:
- A patch drops or adds a parameter to a function (substantive API change) while
  also renaming existing parameters (e.g. `msm_dp_panel` → `panel`) in the same diff
- The subject describes the substantive change, but the rename is silently included
- Downstream reviewers cannot cleanly isolate the functional delta from cosmetic noise

Maintainer evidence:
- Dmitry Baryshkov on patch 10/15 "drm/msm/dp: allow dp_ctrl stream APIs to use any
  panel passed to it" (linux-arm-msm, 2026-05-28): objected to a rename of
  `msm_dp_panel` → `panel` co-mingled with dropping the cached panel pointer: "Please
  don't mix sensible changes with the renames / cleanups." Our automated review raised
  only a checkpatch alignment [MINOR] and missed the mixed-scope concern (missed-by-us).

Review action:
- Flag [CONCERN] when a patch that changes a function signature also renames
  parameters that are orthogonal to the API change.
- Suggest splitting into: (1) a preparatory patch with only the rename, (2) the patch
  with the functional signature change.

False-positive guards:
- Do not flag a rename that is introduced purely to match the new parameter's meaning
  (e.g. renaming `old_panel` to `panel` as part of removing cached state is
  inseparable from the semantic change).
- Do not flag trivial single-character or local-variable renames that do not appear in
  function signatures or public headers.
- One data point; treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0272: Series listing unmerged cross-tree prerequisites — maintainer skips review as unmergeable and untestable

Status: draft
Scope: general
Triggers:
- A patch series cover letter (or dependency annotation) lists one or more
  prerequisite series that are not yet merged into any single upstream tree
  (e.g. "depends on: clk series queued on linux-next" + "depends on: icc
  series queued on linux-next")
- The prerequisites span different subsystem trees (e.g. clk.git,
  interconnect.git) that have not landed in a common integration base
- The result is a series that cannot be applied as a standalone unit for review
  or testing

Maintainer evidence:
- Krzysztof Kozlowski (DT bindings maintainer) on
  [PATCH v2 0/2] PCI: qcom: Add PCIe support for upcoming Hawi SoC
  (linux-pci / linux-arm-msm, 2026-05-30): "It cannot depend there it makes it
  unmergeable and untestable. I skip review in such case, please follow standard
  documented practices about decoupling independent works."
  The series depended on two unmerged cross-tree series (clk v3, icc v4).
  Our automated review confirmed the dependency commits were present in the
  applied base but never questioned the cross-tree merge conflict or flagged
  the unmergeable state (missed-by-us).

Review action:
- Flag [CONCERN] at the series level when the cover letter or dependency
  annotations list prerequisites that live in different subsystem trees and
  are not yet merged into a common integration base (e.g. linux-next or
  mainline).
- Note explicitly that this makes the series unmergeable and untestable as a
  unit; maintainers such as Krzysztof Kozlowski will decline to review until
  dependencies are decoupled or resolved.
- Suggest: either decouple the series so it is independently applicable, or
  wait until all prerequisites are merged into a common base before posting.

False-positive guards:
- Do not flag if all listed prerequisites are already merged into the same
  upstream tree or linux-next at a verifiable base commit.
- Do not flag if the dependency is within the same subsystem tree and the
  author notes the expected merge order clearly.
- Do not flag a series that applies cleanly against the current linux-next
  and all dependencies are merged there, even if not yet in mainline.

Confidence: low
Last updated: 2026-05-30

### MEM-0277: Trivially-small follow-up that only modifies prerequisite-series files — squash into prerequisite

Status: draft
Scope: general
Triggers:
- A patch series (2 or fewer patches) depends on an unmerged prerequisite series
- Every file touched by the new series was introduced by that prerequisite (none
  of the files exist in the base tree)
- The total change is trivially small (e.g. one `#define` added to a header,
  one entry added to a static table)

Maintainer evidence:
- Krzysztof Kozlowski on patch 1/2 of
  20260526-shikra-gcc-usb-resets-v1-0-6d9e7fee2998@oss.qualcomm.com
  (dt-bindings: clock: qcom: Add the definition for the USB3 DP PHY reset,
  linux-arm-msm, 2026-05-30): "So just squash into the dependency." — directly
  requesting the one-line DT header change be merged back into the prerequisite
  series (20260429-shikra-gcc-rpmcc-clks-2094edfff3b0:v2) rather than
  maintained as a standalone follow-up series.
- Dmitry Baryshkov on patch 2/2 of the same series (clk: qcom: gcc-shikra: Add
  support for the USB3 DP PHY reset, 2026-05-26): "Why was it not a part of the
  original submission?" — second independent reviewer questioning why a one-line
  driver addition was not included in the original prerequisite series.
  Our automated review offered two options (wait for prerequisite, or combine
  into a single thread) but did not specifically recommend squashing the change
  into the prerequisite series itself (missed-by-us).

Review action:
- When a series cannot apply because its prerequisite series is not yet merged,
  and every touched file is owned by that prerequisite, and the total diff is
  trivially small (≤ ~5 lines across all patches), flag [CONCERN] and suggest:
  "This change is small enough to squash into the prerequisite series
  (<change-id>); send a revised version of that series incorporating this
  addition rather than a separate follow-up."
- Do not merely say "wait for prerequisite" or "combine into a single thread" —
  the maintainer preference is to squash back into the dependency itself.

False-positive guards:
- Do not flag if the new series is non-trivial (adds new files, new hardware
  tables, new bindings beyond extending a single header).
- Do not flag if the prerequisite series has already been accepted (the follow-up
  can be a standalone incremental fix at that point).
- Do not flag if the cover letter explains that the follow-up is intentionally
  held for a separate merge window.
- One data point; treat as draft.

Confidence: low
Last updated: 2026-05-30

### MEM-0287: Non-functional stub commit adding empty driver descriptor — resources deferred to a later patch in the same series

Status: draft
Scope: general
Triggers:
- A patch series has a patch N that introduces a new `enum` value, a `compatible`
  string registration, and a named driver descriptor struct (e.g. `camss_resources`)
  that is intentionally left empty (no resource arrays) because "later changes will
  enumerate" the resources
- A subsequent patch in the same series (patch M > N) fills in those resource arrays,
  making the intermediate commit non-functional: applying patch N alone and a DTS
  results in a driver that will not initialize correctly

Maintainer evidence:
- Krzysztof Kozlowski on Patch 3/6 "media: qcom: camss: Add Glymur compatible"
  (linux-media, 2026-05-30): "Incomplete. Apply this patch + DTS and tell me if
  camss is working." — directly rejecting the hollow stub; the patch introduced
  `CAMSS_GLYMUR` with an empty `glymur_resources` struct and a commit body saying
  resources would be added "in subsequent commits."
- Krzysztof Kozlowski on Patch 6/6 "media: qcom: camss: Enumerate resources for
  Glymur" (linux-media, 2026-05-30): "NAK, this is getting ridiculous. You add
  incomplete 'compatible' claiming that such change as adding a compatible is a
  complete work, complete change (as explained in submitting patches). Stop inflating
  your patchcount." Both NAKs are from the same maintainer on the same series;
  our automated review raised only a commit-body wording [MINOR] (missed-by-us).

Review action:
- Flag [CONCERN] when a patch introduces a driver registration struct
  (e.g. `camss_resources`, platform device data, `of_device_id` entry) that
  explicitly defers its resource arrays or configuration to a later patch in the
  same series, leaving the intermediate commit non-functional.
- Note that Documentation/process/submitting-patches.rst requires each patch to be a
  "complete, stable change" that could be bisected; a hollow stub with empty resource
  arrays violates this. Suggest squashing the stub and its follow-up enumeration
  patch into a single complete patch.

False-positive guards:
- Do not flag forward-compatible preparatory patches that are self-contained and do
  not register any broken-at-intermediate-state entry (e.g. a pure refactoring or
  helper function addition that doesn't change any observable driver state).
- Do not flag when the incomplete patch is clearly marked RFC or has explicit reviewer
  agreement that the intermediate state is acceptable for review purposes.
- One maintainer data point; treat as draft.

Confidence: low
Last updated: 2026-05-30
