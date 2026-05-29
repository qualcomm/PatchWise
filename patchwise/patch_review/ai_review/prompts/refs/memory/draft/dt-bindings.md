# Review Memory — Dt Bindings (draft)

### MEM-0001: Qcom DTS pin-conflict fix — base board DTS vs overlay DTSO placement

Status: draft
Scope: subsystem:arm/qcom
Triggers:
- Base board DTS changed to resolve a GPIO/pinmux conflict whose root cause is
  a specific mezzanine board or overlay (DTSO), not a defect present on all
  hardware instances

Maintainer evidence:
- Konrad Dybcio questioned a lemans-evk.dts CTS/RTS removal: "Shouldn't the
  change be moved to the IFP mezz DTSO then?" followed by "does the bare EVK
  debug UART connector have 2 or 4 lines connected to it?" (linux-arm-msm,
  2026-04-30).
- Thread follow-up (2026-05-07 to 2026-05-11): a third party confirmed that
  disabling uart0 in the IFP mezzanine DTSO equally resolves the conflict; the
  author acknowledged both approaches work and deferred to maintainer preference.
  The bare-connector hardware routing question was never definitively answered.
  lemans-evk-ifp-mezzanine.dtso is present in the tree, making the overlay fix a
  viable upstream alternative. Neither author nor thread established a hardware
  reason that the base DTS change was uniquely correct.

Review action:
- Flag [MINOR] when a base board DTS change is explained as fixing a conflict
  that only exists "on systems using overlay X" or "when mezzanine Y is
  attached". Note the ambiguity: is the conflict present on all board hardware
  (justifying the base DTS change), or only with the overlay (in which case the
  fix may belong in the overlay DTSO)?
- When the overlay DTSO is present in the tree, note explicitly that an
  overlay-only fix (e.g. disabling the conflicting peripheral in the DTSO) is a
  viable alternative that avoids changing the default configuration for all
  board users.

False-positive guards:
- Do not flag if the commit body clearly states the conflict exists on all
  hardware regardless of whether any overlay is applied.
- Do not flag if the overlay DTSO is absent from the upstream tree and the base
  DTS is the only viable upstream fix location.
- Do not flag DTS changes that fix issues documented in the base board schematics.

Confidence: low
Last updated: 2026-05-26

### MEM-0008: DT binding commit — "Add compatible string" not "Document X" for single-entry additions (subject and body)

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A patch adds exactly one compatible string enum entry to an existing YAML
  binding schema (single-line diff in the enum list)
- The commit subject line uses "Document the <device>" or "Document <IP block>"
  language that implies a broader documentation effort (e.g. "Document the IPQ9650 PCIe")
- OR the commit body opens with "Document the <device>" or "Document <IP block>"
  language that implies a broader documentation effort

Maintainer evidence:
- Patchwise AI review (2026-05-11) on "dt-bindings: mailbox: qcom: Add IPCC
  support for Maili Platform": "The body originally says 'Document the
  Inter-Processor Communication Controller,' which implies a larger
  documentation effort. Since the patch only adds a single compatible string,
  using 'Add the compatible string for' is more accurate and avoids
  overstating the scope."
- Patchwise AI review (2026-05-26) on "dt-bindings: PCI: qcom,pcie-ipq9574:
  Document the IPQ9650 PCIe": suggested subject rewrite to
  "dt-bindings: PCI: qcom,pcie-ipq9574: Add IPQ9650 compatible" — "Document"
  in the subject overstates the scope when only one enum entry is added.
  Our automated review gave READY TO APPLY without flagging the subject verb
  (missed-by-us). Second independent instance of the same pattern.

Review action:
- Flag [NIT] when a DT binding commit subject or body uses "Document X" but
  the patch diff shows only one compatible string added to an existing enum list.
- For the subject: suggest rephrasing to "Add <SoC> compatible" or
  "Add <SoC> PCIe compatible to <binding>" (drop "Document").
- For the body: suggest rephrasing to "Add the compatible string for X" or
  "Add X compatible string to the existing Y binding."

False-positive guards:
- Do not flag if the patch adds or substantially revises a YAML schema file
  rather than only appending to an existing enum.
- Do not flag if "Document" accurately describes a new binding section,
  required/optional property block, or example node being added.
- Do not apply when the patch touches multiple binding files or makes
  structural changes beyond enum addition.

Confidence: low
Last updated: 2026-05-27

### MEM-0010: Qcom APCS compatible string naming -- use -apss-shared not -apcs-hmss-global

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/mailbox/qcom,apcs-kpss-global.yaml
Triggers:
- A patch adds a new Qualcomm SoC entry to the standalone-compatible enum in
  qcom,apcs-kpss-global.yaml for an HMSS-family APCS block
- The proposed compatible string contains -apcs-hmss-global or the -hmss-
  abbreviation (short for hard macro sub-system)

Maintainer evidence:
- Konrad Dybcio on patch 2/3 of Shikra dt-bindings series (linux-arm-msm,
  2026-04-29): 'hm stands for hard macro, i.e. the hardware block,
  please remove that bit and keep it apss-shared (like in ipcat)' --
  requesting qcom,shikra-apcs-hmss-global be renamed to
  qcom,shikra-apss-shared.

Review action:
- Flag [MINOR] when a new APCS entry for an HMSS-family block uses the
  -apcs-hmss-global suffix. Suggest using -apss-shared instead (e.g.
  qcom,shikra-apss-shared rather than qcom,shikra-apcs-hmss-global).
- Note that the existing qcom,msm8996-apcs-hmss-global and
  qcom,qcm2290-apcs-hmss-global entries are legacy and should not be
  treated as naming models for new SoC additions.

False-positive guards:
- Do not flag entries that already use -apss-shared or a non--hmss-global
  suffix that has not been objected to by a maintainer.
- Do not flag if a maintainer explicitly approves the -hmss-global suffix
  for the specific SoC being added.
- Do not apply outside qcom,apcs-kpss-global.yaml without further evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0011: DT binding commit body — include device type and definite article for compatible-string additions

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A patch adds a compatible string for a named hardware device (e.g., a PMIC, clock
  controller, PHY, or transceiver)
- The commit body refers to the device only by part number (e.g., "PMG1110") with no
  device-type qualifier (e.g., "PMIC") and/or omits the definite article "the" before
  the device name or target platform name

Maintainer evidence:
- Patchwise AI review (2026-05-18) on "dt-bindings: mfd: qcom,spmi-pmic: Document
  PMG1110": body "Add compatible string for PMG1110 which is used on Maili platform"
  revised to "Add compatible string for the PMG1110 PMIC, used on the Maili platform"
  — adding "the" before device and platform, and appending device type "PMIC" after
  the part number.
- Patchwise AI review (2026-05-18) on "dt-bindings: pinctrl: qcom,pmic-gpio: Document
  PMG1110 GPIO support": body "which is used on Maili platform" → suggested rewrite
  "used on the Maili platform"; our automated review independently flagged the same
  [NIT]. Second independent instance of missing "the" before a named Qualcomm platform
  in a DT binding commit body.

Review action:
- Flag [NIT] when a DT binding compatible-string commit body identifies a device only
  by part number with no device-type qualifier (PMIC, clock controller, PHY, etc.).
- Flag [NIT] when "the" is absent before a named device or platform in the commit body
  (e.g., "Maili platform" should be "the Maili platform").
- Suggest: "Add compatible string for the <PartNumber> <DeviceType>, used on the
  <Platform>."

False-positive guards:
- Do not flag if the commit body already uses a device-type qualifier.
- Do not flag if the definite article is already present before the device and platform names.
- Do not apply to patches that add or substantially revise a YAML schema file rather
  than appending a single enum entry.
- Do not flag if the commit subject or cover letter already unambiguously identifies
  the device type in context that flows into the body reading.

Confidence: low
Last updated: 2026-05-26

### MEM-0013: Qcom DTS hardware replacement — check for board revision or variant change

Status: draft
Scope: subsystem:arm/qcom file-pattern:arch/arm64/boot/dts/qcom/*.dts
Triggers:
- A DTS patch removes a hardware node for a component (USB SBU mux, retimer,
  power sequencer, etc.) that was described as working in the board-introducing
  commit, and replaces it with a different chip providing the same function on
  the same port or bus

Maintainer evidence:
- Konrad Dybcio on hamoa-iot-evk v2 series (linux-arm-msm, 2026-04-28 and
  2026-05-22): the board-introducing commit c11645afb0e2 described DP as
  working (implying the fsusb42 SBU mux was present), yet a follow-on series
  removed fsusb42 and added a PS8830 retimer. Konrad asked whether these are
  different board revisions coexisting in parallel, or whether the Parade
  retimer version supersedes the original — received no author response by
  2026-05-22.

Review action:
- Flag [CONCERN] when a DTS patch replaces a named hardware component that the
  board-introducing commit described as present and functional, if the commit
  body does not explain whether this is (a) a correction of an error in the
  original DTS, (b) a board hardware revision requiring a new DTS variant, or
  (c) a replacement that applies to all shipped units.
- Suggest the author clarify in the cover letter or commit body whether the two
  hardware configurations coexist, and whether a separate DTS/DTSI variant is needed.

False-positive guards:
- Do not flag if the commit body explicitly states the replaced component was
  never present on any shipped board (i.e., the original DTS was wrong).
- Do not flag if the patch carries a Fixes: tag pointing to the
  board-introducing commit, indicating this is a correction.
- Do not flag if the replaced component was marked status = "disabled" or
  commented as absent in the board-introducing commit.
- Do not flag if the series cover letter or a prior patch in the same series
  already explains the board revision situation.

Confidence: low
Last updated: 2026-05-26

### MEM-0014: DT binding commit body — name the fallback compatible for versioned enum group additions

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A patch adds exactly one compatible string to an existing versioned enum group
  in a YAML binding schema (e.g., the qcom,sdhci-msm-v5 group in sdhci-msm.yaml,
  or an equivalent v4/v6 group in another driver binding)
- The commit body describes the addition but does not identify which fallback
  compatible string the new entry inherits

Maintainer evidence:
- Patchwise AI review (2026-05-18) on "dt-bindings: mmc: sdhci-msm: Add Hawi
  compatible for sdhci": original body "Document the compatible string for the
  SDHCI controller on the Hawi platform" revised to "Add the compatible string
  'qcom,hawi-sdhci' for the SDHCI controller on the Qualcomm Hawi SoC, which
  reuses the existing qcom,sdhci-msm-v5 binding" — explicitly naming the fallback
  so reviewers can confirm correct group placement without consulting the diff.
- Jingyi Wang (2026-05-12) on "dt-bindings: interconnect: qcom-bwmon: Add Maili
  cpu-bwmon compatible": "This commit msg should be more detailed." The body read
  only "Add the Qualcomm Maili SoC compatible string for the CPU bandwidth monitor"
  without stating that Maili reuses the qcom,sdm845-bwmon (BWMON v4) fallback.
  Patchwise AI independently requested that the body explicitly name the hardware
  variant the Maili SoC is derived from. Our automated review did not flag the thin
  body — a missed-by-us finding. First human-reviewer confirmation of this pattern.

Review action:
- Flag [NIT] when a patch adds a compatible string to a versioned enum group and
  the commit body omits the fallback compatible name.
- Suggest appending a phrase such as: "which reuses the existing
  <fallback-compatible> binding" or "placed in the <fallback-compatible> group."

False-positive guards:
- Do not flag if the commit body or cover letter already names the fallback compatible.
- Do not flag for new YAML schema additions that introduce a binding from scratch
  (no pre-existing versioned group to reference).
- Do not apply to single-enum bindings where there is no versioned fallback hierarchy.

Confidence: low
Last updated: 2026-05-26

### MEM-0016: qcom,msa-fixed-perm in new Qcom SNoC WiFi nodes — verify per-SoC by cross-referencing family DTS

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dtsi
Triggers:
- A new Qcom SoC DTSI adds a qcom,wcn3990-wifi (or SNoC-based WiFi) node
  that includes the qcom,msa-fixed-perm flag

Maintainer evidence:
- Konrad Dybcio asked "Is this flag applicable for Shikra?" on patch 1/2 of
  the Shikra WiFi DTS series (20260420070949.3598121-1-miaoqing.pan@oss.qualcomm.com,
  linux-arm-msm 2026-04-22). Author confirmed Shikra uses a fixed MSA region;
  Konrad gave Reviewed-by with no further changes requested.

Review action:
- When qcom,msa-fixed-perm appears in a new SoC WiFi node, cross-reference the
  same IP block in a known-good DTS of the same SoC family (e.g., agatti.dtsi
  for WCN3990/SNoC family) to confirm fixed-MSA usage is expected.
- If no same-family reference is available, note in the review that fixed vs.
  dynamic MSA ownership should be confirmed for the new SoC.

False-positive guards:
- Do not flag if the SoC uses SCM-based dynamic MSA ownership transfer — in that
  case the flag should be absent and absence is correct.
- Do not apply to WiFi nodes using different IP blocks (e.g., WCN7850, WCN6855)
  where MSA ownership semantics may differ, without separate confirming evidence.
- Do not raise as CONCERN when a same-family reference DTS clearly shows the
  same value; a brief [INFO] note or silent confirmation is sufficient.

Confidence: low
Last updated: 2026-05-26

### MEM-0017: qcom,coresight-itnoc DTS node name must match `^itnoc(@[0-9a-f]+)?$`

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dtsi
Triggers:
- A DTS/DTSI node uses `compatible = "qcom,coresight-itnoc"` with a node
  name other than `itnoc` or `itnoc@<addr>` (e.g., `tn@<addr>`,
  `tracenoc@<addr>`)

Maintainer evidence:
- Sashiko-bot on v5 glymur coresight patch (2026-05-19): "[Medium] The
  `tn@11200000` node violates the `qcom,coresight-itnoc` device tree binding
  schema." Confirmed independently by `dtbs_check` on both glymur-crd.dtb
  and mahua-crd.dtb. Binding schema
  `Documentation/devicetree/bindings/arm/qcom,coresight-itnoc.yaml` requires
  `$nodename: pattern: "^itnoc(@[0-9a-f]+)?$"`.

Review action:
- Flag [CONCERN] when a `qcom,coresight-itnoc` node is not named `itnoc` or
  `itnoc@<hex-addr>`. Suggest renaming (e.g., `tn@11200000` → `itnoc@11200000`).
- Note that label names inside the node (endpoint labels, phandle labels) may
  use any abbreviation and do not need to change.

False-positive guards:
- Do not flag nodes already named `itnoc` or `itnoc@<addr>`.
- Do not apply to other CoreSight-compatible strings; this binding constraint
  is specific to `qcom,coresight-itnoc`.

Confidence: low
Last updated: 2026-05-26

### MEM-0018: CoreSight `clock-names = "apb_pclk"` vs binding `const: apb` schema divergence

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dtsi
Triggers:
- A DTS node for a `qcom,coresight-itnoc` device uses
  `clock-names = "apb_pclk"` while the binding schema specifies
  `clock-names: items: - const: apb`
- More broadly: any CoreSight DTS node where `clock-names` value diverges
  from the strict `const:` in its binding schema

Maintainer evidence:
- Sashiko-bot on v5 glymur coresight patch (2026-05-19): asked whether
  `apb_pclk` violates the binding's `const: apb`. Review notes that
  `coresight_get_enable_clocks()` explicitly prefers `"apb_pclk"` first,
  then falls back to `"apb"`, and the driver comment states CoreSight drivers
  should use `apb_pclk`. The binding's `const: apb` therefore appears
  inconsistent with the driver and with all other CoreSight nodes in the tree.

Review action:
- Flag [MINOR] when `clock-names = "apb_pclk"` appears in a node whose
  binding schema strictly requires `const: apb`. Note it is a
  binding-documentation inconsistency, not a runtime defect.
- Recommend either: (a) updating the binding schema to accept `apb_pclk`
  in a companion patch (preferred — aligns with the driver comment and all
  other CoreSight nodes), or (b) using `clock-names = "apb"` to match the
  current binding.

False-positive guards:
- Do not flag if the binding schema already lists `apb_pclk` as a valid item.
- Do not raise above [MINOR]; the driver handles both names gracefully and
  there is no runtime failure.
- Do not flag non-CoreSight nodes — this driver-vs-binding divergence is
  specific to the CoreSight clock naming history.

Confidence: low
Last updated: 2026-05-26

### MEM-0022: DT binding commit body — explicitly name the new compatible string for single-entry additions

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A patch adds exactly one compatible string to an existing YAML binding schema
- The commit body describes the addition abstractly (e.g. "Add devicetree binding
  for X" or "Add support for Y") without quoting or naming the specific compatible
  string being inserted

Maintainer evidence:
- Patchwise AI review (2026-05-11) on "dt-bindings: watchdog: Document Qualcomm
  Maili watchdog": body "Add devicetree binding for watchdog present on Qualcomm
  Maili SoC" revised to "Add the compatible string 'qcom,apss-wdt-maili' to the
  Qualcomm watchdog binding to support the watchdog present on the Qualcomm Maili
  SoC" — explicitly quoting the new compatible string so the body is self-contained.

Review action:
- Flag [NIT] when a DT binding commit body adds a single compatible string but does
  not quote or name that string explicitly.
- Suggest rephrasing to: "Add the compatible string '<vendor,device>' to the
  existing <subsystem> binding to support <device/platform>."

False-positive guards:
- Do not flag if the compatible string is named in the commit subject line and the
  body already provides sufficient additional context beyond the subject.
- Do not flag if the patch adds or substantially revises a YAML schema file rather
  than appending a single enum entry.
- Do not apply when the compatible string already appears verbatim in the commit
  body, regardless of sentence structure.

Confidence: low
Last updated: 2026-05-26

### MEM-0027: DT binding YAML — `maxItems` is redundant when an `items:` list is present

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A YAML binding schema property specifies both `items: [...]` and `maxItems:` set to the
  same count as the items list length
- Similarly, `minItems:` equal to the items list length is also redundant

Maintainer evidence:
- dt_binding_check on patch 1/7 of 20260507-link_mode_support-v2 (2026-05-07):
  reported "maxItems is not needed with an items list" (dtschema meta-schema hint from
  http://devicetree.org/meta-schemas/items.yaml) for clock-output-names and reg
  properties that carried both an `items: [...]` list and a redundant `maxItems:`.
  Our automated review missed this while dt_binding_check flagged it explicitly.

Review action:
- Flag [NIT] when a YAML binding property has both `items: [...]` and `maxItems:`
  set to exactly the items list length (redundant).
- Similarly flag [NIT] when `minItems:` equals the items list length (also redundant).
- Suggest removing the redundant `maxItems` (or `minItems`) key.

False-positive guards:
- Do not flag `minItems:` that is strictly less than the items list length — that
  legitimately marks optional trailing items.
- Do not flag properties that use only `minItems`/`maxItems` without an `items:` list.

Confidence: low
Last updated: 2026-05-26

### MEM-0029: DT binding — splitting if/then/else into separate if/then blocks silently drops else constraints

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A YAML binding patch refactors an existing if/then/else block into two or more
  separate if/then blocks (e.g. to add rules for a new compatible string)
- The original else branch enforced tighter property constraints for non-matching
  compatibles (e.g. `reg: maxItems: 1`, `power-domains: maxItems: 1`)

Maintainer evidence:
- Patchwise AI review on patch 1/7 of 20260507-link_mode_support-v2 (2026-05-07):
  the original single if/then/else block for qcom,sc8280xp-qmp-pcie-phy was split into
  two separate if/then blocks. The else branch that enforced `reg: maxItems: 1` for all
  non-gen5x8 compatibles was dropped, silently relaxing validation for every existing PHY.
  Our automated review caught the power-domains maxItems relaxation but missed the reg
  constraint loss; the AI code reviewer caught both by inspecting the dropped else.

Review action:
- Flag [CONCERN] when a DT binding patch splits an if/then/else block and removes the
  else branch, if that branch enforced a tighter constraint than the top-level
  property definition.
- Check every property in the dropped else: if any had `maxItems`, `minItems`, or
  `required:` entries absent from the top-level schema, those constraints are now lost
  for all non-matching compatibles.
- Suggest either restoring the else branch or adding a comment explaining the
  intentional relaxation.

False-positive guards:
- Do not flag if the dropped else branch added no constraints tighter than the top-level
  property definitions (logically empty or only mirrored top-level defaults).
- Do not flag if the original else was made redundant by other allOf rules added in
  the same patch that re-express the lost constraints.

Confidence: low
Last updated: 2026-05-26

### MEM-0031: binding adds `required:` for existing compatible — verify DTS coverage and require commit-body ABI justification

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A binding patch adds `required:` constraints for a compatible string that already
  has in-tree DTS/DTSI files (the compatible was present before this series)
- The series does not include DTS patches that add the newly required properties to
  those in-tree files, OR the DTS patches arrive too late in the series to be confirmed
- OR: the commit body does not explain whether existing in-tree DTS files already satisfy
  the new requirement

Maintainer evidence:
- Patchwise static analysis on patch 1/7 of Qcom clkref series (kernel@oss.qualcomm.com,
  2026-05-16): dtbs_check at patch 1s tree state showed 34 required-property failures
  for glymur-crd.dtb and mahua-crd.dtb after the binding added required supply
  properties for qcom,glymur-tcsr and qcom,mahua-tcsr. The failures were expected
  intermediate state resolved by patches 5/6 in the same series; our per-patch
  dtbs_check (run only for .dts/.dtsi-touching patches) correctly reported PASS at
  those later tree states.
- Krzysztof Kozlowski on patch 1/7 of eliza MM clock series
  (20260525-eliza_mm_cc_v2-v5-0-a1d125619a5a@oss.qualcomm.com, linux-arm-msm,
  2026-05-26): "That's ABI change, so you need to explain impact on existing devices
  - Milos." The patch added `#power-domain-cells` to `required:` in milos-videocc.yaml
  without explicitly confirming existing Milos DTS nodes already carry the property.
  Author confirmed no breakage (all in-tree Milos nodes already have the property),
  but the commit body lacked that statement. Our automated review called it
  "backward-compatible" without flagging the missing justification (missed-by-us).

Review action:
- When a binding patch adds `required:` for an existing compatible, cross-check the
  series: do later DTS patches add the newly required properties to all in-tree DTS
  files using that compatible?
- If the series contains no DTS patches (or only partial coverage), flag [CONCERN]:
  the binding change will leave existing in-tree DTS files failing dtbs_check.
- Also flag [MINOR] when the commit body does not explicitly state whether existing
  in-tree DTS files already satisfy the new required property. Suggest adding a sentence
  such as: "All in-tree DTS files using <compatible> already carry <property>, so no
  existing device tree is broken by this change."
- Do not flag dtbs_check failures at a binding-only patches tree state as bugs when
  the same series contains DTS patches that satisfy the new constraints.

False-positive guards:
- Do not flag if the newly required properties were already present in all in-tree DTS
  files using that compatible before this binding patch was applied AND the commit body
  already states this.
- Do not flag if the compatible string is newly introduced in this same series and
  has no pre-existing DTS users — only existing DTS files can be broken by new required:.
- Do not raise above [CONCERN] when DTS patches are present in the series; intermediate
  dtbs_check failures at the binding patch tree state are expected and not actionable.

Confidence: low
Last updated: 2026-05-30

### MEM-0035: DT binding commit body — state omission explicitly when a named resource is absent for a new SoC entry

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A patch adds a new SoC compatible string to an existing binding
- A named resource (memory-region, interrupt, clock, etc.) present in sibling
  entries of the same binding is intentionally absent for the new SoC
- The commit body notes the resource is "not managed by the kernel" but does not
  explicitly state it is therefore absent (unlisted) in the binding

Maintainer evidence:
- Jingyi Wang on "dt-bindings: remoteproc: qcom,sm8550-pas: Add Maili ADSP and CDSP"
  (2026-05-12): suggested the commit body say "global_sync_mem is not managed by the
  kernel so it remains unlisted" rather than just "global_sync_mem is not managed by
  the kernel". The explicit "so it remains unlisted" ties the driver-level fact to the
  binding omission, making the intentional absence unambiguous. Author agreed to update.
  Our automated review praised the body as "correctly explains the key behavioural
  differences" without noticing the incomplete explanation — a missed-by-us finding.

Review action:
- Flag [NIT] when a DT binding commit body mentions a resource is unmanaged or
  unavailable but omits an explicit statement that it is therefore absent from the
  binding (e.g. "so it remains unlisted", "so it is not described in this binding").
- Suggest appending a clause such as: "global_sync_mem is not managed by the kernel,
  so it remains unlisted in this binding."

False-positive guards:
- Do not flag if the commit body already explicitly states the resource is absent
  from the binding (e.g. "not listed", "not described", "omitted from the schema").
- Do not flag if no sibling SoC in the same binding uses the resource in question
  (the omission is then unremarkable and needs no explanation).
- Do not raise above [NIT]; this is a commit-body clarity note, not a correctness issue.

Confidence: low
Last updated: 2026-05-26

### MEM-0045: DT binding commit body — named reference SoC must have an entry in the same binding section

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A DT binding commit body states the new SoC "is the same as X", "follows the
  same pattern as X", or "is compatible with X" (where X is a named SoC)
- The named SoC X does not actually have a corresponding compatible string in
  the same binding section (enum, oneOf items list) that the patch modifies

Maintainer evidence:
- Patchwise AI review (2026-05-18) on "dt-bindings: spmi: glymur-spmi-pmic-arb:
  Add compatible for Qualcomm Maili SoC": commit body stated Maili "is the same
  with Hawi", but qcom,hawi-spmi-pmic-arb is absent from the two-string enum in
  qcom,glymur-spmi-pmic-arb.yaml. Our automated review did not cross-check the
  referenced SoC against the actual binding content (missed-by-us).

Review action:
- When a DT binding commit body says "same as <SoC>" or names another SoC as the
  template (e.g. "same as Hawi"), verify that SoC's compatible string actually
  appears in the same binding section being modified.
- If the referenced SoC has no entry, flag [NIT]: the commit body reference may be
  misleading, or the referenced SoC's compatible entry may be missing.

False-positive guards:
- Do not flag if the body merely notes equivalent hardware in passing without
  implying the referenced SoC has an entry in this specific binding section.
- Do not flag if the referenced SoC's compatible belongs to a separate binding file.
- Use [NIT], not [CONCERN] or [BUG]; the issue is commit body accuracy only.

Confidence: low
Last updated: 2026-05-26

### MEM-0054: New SoC DT-binding commit body — identify SoC family context and companion driver

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A patch adds a new SoC compatible string to an existing shared binding schema
  (one YAML file covering multiple SoCs, e.g. qcom,sm8450-videocc.yaml)
- The commit body describes only what was added (compatible string + header) without
  explaining what the new SoC is or its relationship to the SoCs already in the schema

Maintainer evidence:
- Patchwise AI review (2026-05-19) on patch 1/2 of Hawi VideoCC series: body
  "Add device tree bindings for the video clock controller on Qualcomm Hawi SoC"
  revised to include "Hawi is a Qualcomm SoC in the sm8450 family" and a note
  that patch 2/2 introduces the kernel driver consuming these bindings.
  Our automated review independently flagged the same [NIT] (confirmed).

Review action:
- Flag [NIT] when a new SoC binding commit body omits: (a) the SoC family or
  relationship to existing SoCs in the same schema, and/or (b) a cross-reference
  to the companion driver patch in the same series.
- Suggest adding one or two sentences such as: "<SoC> is a Qualcomm SoC in the
  <family> family. Patch <N>/<T> introduces the kernel driver that uses these
  clock, power-domain, and reset identifiers."

False-positive guards:
- Do not flag if the body already identifies the SoC family or relationship.
- Do not flag if there is no companion driver patch in the same series (standalone
  binding-only addition).
- Do not flag if the commit subject unambiguously identifies the SoC family and
  the body provides other meaningful context beyond the subject.

Confidence: low
Last updated: 2026-05-26

### MEM-0055: DT binding example using a cross-tree compatible fails Rob's dt_binding_check at rc1 base

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A new DT binding YAML file includes an example DTS referencing a compatible
  string (e.g. a display panel compatible inside a GPIO or MFD binding example)
  whose binding schema lives in a different subsystem
- That compatible's binding was accepted into a different subsystem staging tree
  (e.g. drm-misc-next, sound-soc-next) but has not yet merged into mainline or
  the rc1 base that Rob Herring's automated checker uses

Maintainer evidence:
- Rob Herring (dt-bindings CI bot) on patch 3/4 of Waveshare DSI TOUCH series
  (20260418-waveshare-dsi-touch-v4-3-b249f3e702bd@oss.qualcomm.com, 2026-04-17):
  reported "'waveshare,8.0-dsi-touch-a' failed to match any schema" because the
  panel binding (jadard,jd9365da-h3.yaml) was in drm-misc-next but not rc1.
  Rob noted: "The base for the series is generally the latest rc1. A different
  dependency should be noted in *this* patch." Dmitry confirmed the missing
  dependency. Our local dt_binding_check passed because the review branch had
  the dependency applied; Rob's bot exposed the cross-tree gap. Missed-by-us.

Review action:
- When a DT binding example DTS references a compatible from another subsystem,
  verify that compatible's binding schema is present in mainline/rc1 -- not just
  in a subsystem staging tree.
- If the binding is only in a subsystem staging tree, flag [CONCERN] and suggest
  adding a per-patch note such as "Depends-on: <commit/tree>" so Rob's bot and
  reviewers can account for the missing base.
- Note that local dt_binding_check will silently pass if the review branch
  already has the dependency applied; Rob's bot at rc1 base will expose this.

False-positive guards:
- Do not flag if the referenced compatible's binding is confirmed present in
  mainline (grep Documentation/devicetree/bindings/ at the rc1 tag).
- Do not flag generic node types (gpio-controller, regulators, etc.) that
  have no subsystem-specific schema to fail against.

Confidence: low
Last updated: 2026-05-26

### MEM-0061: PHY binding — new provider-side topology property may be questioned as redundant with consumer phys cells

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/phy/
Triggers:
- A PHY binding adds a new vendor-specific property for provider-side hardware
  topology or mode selection (e.g., link-mode, phy-mode-select)
- The same topology information is, at least theoretically, available through
  the argument cells in consumer nodes phys = <&phy cell> references
- The commit body does not explain why consumer phys args are insufficient

Maintainer evidence:
- Manivannan Sadhasivam on RFC 1/4 of the qmp-pcie Glymur Gen5x8 link-mode
  series (linux-arm-msm, 2026-05-05): "Why can't the PHY driver extract the
  lane count through the argument passed through the 'phys' property by the
  consumer node? I don't see a need to pass the 'link mode' value through this
  new property."
- Author response clarified the new property is necessary because it programs a
  provider-side TCSR register that must be set before any consumer uses the PHY,
  and that topology discovery from consumer phys cells would require a full DT
  walk at probe time.
- Konrad Dybcio agreed: "the only way to [determine mode at runtime] would be
  to walk the entire devicetree in search of references to the PHY node itself."
  Our automated review flagged the property name as too generic but did not flag
  the "is this property needed at all" question (missed-by-us).

Review action:
- Flag [CONCERN] when a new PHY provider-side topology property is added without
  the commit body explaining: (a) why topology cannot be determined from consumer
  phys phandle args at probe time, and (b) why provider-side hardware programming
  requires a DT property.
- Suggest the cover letter or commit body proactively address: "The phys cell
  approach was considered but is insufficient because <reason>."

False-positive guards:
- Do not flag if the commit body already explains why consumer phys args cannot
  determine the provider topology (e.g., TCSR register programming requirement,
  mode must be set before any consumer probes).
- Do not flag properties that are clearly provider-side with no overlap with
  consumer selection (e.g., hardware calibration values, PHY supply voltages).
- Do not apply outside PHY bindings without additional confirming evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0070: Qcom DT compatible strings — deprecated internal IP block names must not appear in upstream naming

Status: draft
Scope: subsystem:cpufreq/qcom file-pattern:Documentation/devicetree/bindings/cpufreq/
Triggers:
- A patch introduces a new DT compatible string (or generic fallback compatible) whose
  suffix or noun is an internal Qualcomm hardware block name that the vendor itself
  deprecated (e.g., RIMPS which was later renamed OSM, then EPSS)
- The automated review accepts or praises the naming without checking Qualcomm hardware
  naming history

Maintainer evidence:
- Sibi Sankar on patch 1/2 of Shikra cpufreq series (linux-arm-msm, 2026-04-30):
  objected to qcom,cpufreq-rimps because RIMPS was an internal name Qualcomm deprecated;
  it was later called OSM and then EPSS. Author agreed to rename to EPSS-lite. Our
  automated review called the RIMPS naming correct and praised it as missed-by-us.

Review action:
- Flag [CONCERN] when a new Qualcomm DT compatible string uses a hardware block acronym
  known to be a deprecated internal Qualcomm name superseded by a different public name.
- Cross-reference sibling Qualcomm compatibles (qcom,cpufreq-epss, qcom,cpufreq-hw) to
  verify the expected naming family before accepting a new generic fallback.
- Ask whether the proposed name is the publicly stable upstream name or an internal
  acronym replaced by a different name in public hardware documentation.

False-positive guards:
- Do not flag if a Qualcomm maintainer already acknowledged the name in this or a prior
  series version.
- Do not flag SoC-specific compatibles (e.g., qcom,shikra-cpufreq-X); only flag the
  generic fallback that becomes a permanent stable API.
- Do not apply outside Qualcomm DT bindings without separate confirming evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0071: New DT fallback compatible must have a corresponding driver of_device_id entry

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A DT binding patch introduces a new generic fallback compatible string for an existing
  in-tree driver
- The driver of_device_id / of_match_table does not include an entry for the new fallback
- The automated review marks the patch READY TO APPLY without verifying driver-side match

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-04-29) on patch 1/2 of Shikra
  cpufreq series: noted qcom,cpufreq-rimps was not listed in the of_device_id table in
  drivers/cpufreq/qcom-cpufreq-hw.c so no driver would bind to this compatible; suggested
  the fallback should be qcom,cpufreq-epss or the driver needed a corresponding entry.
  Our automated review gave READY TO APPLY without cross-checking the driver of_match_table.

Review action:
- When a DT binding adds a new generic fallback compatible for an existing driver,
  cross-check that driver of_device_id / of_match_table for a matching entry.
- If the fallback is absent from the driver, flag [CONCERN]: no driver will bind to
  devices using only the new fallback, defeating its purpose.
- Suggest either adding the of_match_table entry in a companion driver patch in the
  same series, or reusing an existing fallback instead of introducing a new one.

False-positive guards:
- Do not flag if a driver patch in the same series adds the of_match_table entry for
  the new fallback compatible.
- Do not flag SoC-specific compatibles (e.g., qcom,shikra-cpufreq-X); only flag the
  generic fallback intended to match future SoCs.
- Do not flag when the driver is entirely new (new binding plus new driver pair with no
  pre-existing of_match_table to check).

Confidence: low
Last updated: 2026-05-26

### MEM-0075: DT binding — multiple new compatible strings in one patch must be placed symmetrically

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A DT binding patch adds two or more new compatible strings to the same YAML schema
- The strings are placed in different structural positions: some in a standalone enum
  list (no fallback required) and others in an items+fallback block
- The commit body states a fallback intent that applies to all new strings, or sibling
  SoC entries for the same IP variant already use the items+fallback pattern

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-16) on patch 1/2
  "dt-bindings: phy: qcom,ipq8074-qmp-pcie: Document the ipq5210 QMP PCIe PHY":
  qcom,ipq5210-qmp-gen3x1-pcie-phy was placed in the standalone enum while
  qcom,ipq5210-qmp-gen3x2-pcie-phy was placed in the items+fallback block. The commit
  body stated "using the ipq9574 bindings as a fallback" for both. The existing
  qcom,ipq5424-qmp-gen3x1-pcie-phy was already in the items+fallback block. Both the
  Patchwise reviewer and our automated review independently flagged the asymmetry as
  [CONCERN].

Review action:
- When a patch adds multiple new compatible strings to the same YAML binding, verify
  all new strings are placed in the same structural position (both standalone enum OR
  both in items+fallback blocks with the same fallback compatible).
- If the commit body says all new strings reuse a named fallback, verify each new string
  is in an items+fallback block — standalone enum placement contradicts the stated intent.
- Cross-check existing sibling SoC entries for the same IP variant (gen3x1, gen3x2,
  etc.) to confirm the expected placement pattern before accepting asymmetry.

False-positive guards:
- Do not flag when the two new strings genuinely have different fallback requirements
  (e.g., gen3x1 has a dedicated driver cfg with no fallback needed while gen3x2 requires
  fallback) and the commit body accurately reflects that difference.
- Do not flag when only one new string is added in the patch.
- Do not flag when both new strings are in the standalone enum and no fallback is
  claimed or expected by any sibling entry pattern.

Confidence: low
Last updated: 2026-05-26

### MEM-0078: Platform-specific sub-feature binding — check existing SoC compatible before adding a new one

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/soc/qcom/
Triggers:
- A DT binding patch introduces a new compatible string (e.g. qcom,pmic-glink-gio)
  to represent a feature variant that is only available starting from one named
  SoC platform
- The same binding already has a platform-specific compatible for that SoC (e.g.
  qcom,sm8750-pmic-glink), making a new sub-feature compatible redundant for
  platform discrimination

Maintainer evidence:
- Konrad Dybcio on patch 1/5 of 20260316-pmic-glink-gio-clients-v1 (linux-arm-msm,
  2026-03-16): "It then makes sense to check for the existing glymur compatible,
  instead of inventing another one" -- rejecting qcom,pmic-glink-gio and suggesting
  the driver detect GIO support by checking the existing platform-specific compatible
  string already in the binding. Our automated review did not flag this (missed-by-us).

Review action:
- Flag [CONCERN] when a new sub-feature compatible is introduced for a feature
  available only on one named SoC platform, and the existing platform SoC compatible
  in the same binding enum is already sufficient to identify that platform at runtime.
- Suggest using of_device_is_compatible() or of_match_device() against the existing
  platform compatible rather than adding a new compatible and requiring DT changes.

False-positive guards:
- Do not flag if the feature can genuinely appear on multiple future SoC families
  with no single existing compatible to discriminate them all.
- Do not flag if the new compatible is needed because the feature is also enabled
  via a firmware update on older platforms not covered by a single SoC compatible.
- Do not apply outside Qualcomm pmic-glink or similar platform-gated drivers without
  additional confirming maintainer evidence from that subsystem.

Confidence: low
Last updated: 2026-05-26

### MEM-0092: DT binding — new compatible added to deprecated: true schema without updating the non-deprecated successor

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A patch adds a new SoC-specific compatible string to a YAML binding schema
  that carries deprecated: true
- A non-deprecated successor schema already exists in the same subsystem
  directory (e.g., qcom,snps-dwc3.yaml succeeds qcom,dwc3.yaml) and
  already lists sibling SoC compatibles with per-SoC allOf constraints
- The successor schema is not updated in the same patch or series

Maintainer evidence:
- AI review (qgenie, 2026-05-15) on patch 3/5 dt-bindings: usb: qcom,dwc3:
  Add ipq5210 to USB DWC3 bindings: flagged [CONCERN] that qcom,ipq5210-dwc3
  was added to deprecated qcom,dwc3.yaml while qcom,snps-dwc3.yaml
  (non-deprecated) already listed qcom,ipq5018-dwc3 and qcom,ipq5424-dwc3
  with per-SoC allOf clock-names and interrupt-names constraints; ipq5210
  was absent from the successor schema entirely.
- Patchwise AI review (2026-05-16) independently confirmed qcom,ipq5210-dwc3
  had no if/then allOf blocks, naming expected clock-names (core, iface,
  sleep, mock_utmi) and interrupt-names (pwr_event, dp_hs_phy_irq,
  dm_hs_phy_irq) that the successor schema per-SoC pattern would enforce.

Review action:
- When a patch adds a compatible string to a schema carrying deprecated: true,
  check whether a non-deprecated successor schema exists in the same directory.
- If a successor exists and already contains sibling SoC compatibles, flag
  [CONCERN]: the new compatible should go into the successor schema instead,
  together with appropriate allOf clock-names and interrupt-names conditional
  blocks matching the sibling SoC topology.
- If the deprecated schema is intentional, require the commit body to justify it.

False-positive guards:
- Do not flag if the commit body explains why the deprecated schema is correct
  (e.g., the SoC predates the successor schema and the binding is for a legacy
  DTS only).
- Do not flag if no non-deprecated successor schema exists for the hardware
  class in the same directory.
- Do not flag if the patch also updates the non-deprecated successor schema
  in the same series.

Confidence: low
Last updated: 2026-05-26

### MEM-0094: Qcom PAS DT binding YAML — use GPL-2.0 OR BSD-2-Clause not GPL-2.0-only OR BSD-2-Clause

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/remoteproc/qcom*
Triggers:
- A new Qualcomm PAS or remoteproc DT binding YAML opens with SPDX GPL-2.0-only OR BSD-2-Clause
- Sibling Qualcomm PAS binding files in the same directory use GPL-2.0 OR BSD-2-Clause

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-18) on "dt-bindings: remoteproc:
  Document IPQ9650 CDSP": all other Qualcomm PAS bindings in this directory use
  GPL-2.0 OR BSD-2-Clause, not GPL-2.0-only OR BSD-2-Clause. Our automated review did not
  cross-check the SPDX form against sibling files (missed-by-us).

Review action:
- Flag [NIT] when a new Qualcomm remoteproc/PAS YAML binding uses GPL-2.0-only OR BSD-2-Clause.
- Cross-check sibling PAS binding files (e.g. qcom,sm8550-pas.yaml) to confirm the expected
  form; suggest using GPL-2.0 OR BSD-2-Clause.

False-positive guards:
- Do not flag if sibling files in the same directory also use GPL-2.0-only OR BSD-2-Clause.
- Do not apply outside Qualcomm remoteproc PAS bindings without confirming sibling files use
  the non-only form.
- One AI-reviewer data point only; apply as [NIT].

Confidence: low
Last updated: 2026-05-26

### MEM-0095: DT binding allOf if/then with single-compatible enum is always-true — move constraints to top-level properties

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A new DT binding YAML uses an allOf if/then block where the if condition tests
  compatible: enum: containing only the single compatible string defined at the schema top-level
- Because no other compatible can appear, the condition is always true, making the block unconditional

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-18) on "dt-bindings: remoteproc:
  Document IPQ9650 CDSP": the if condition matches the only possible compatible value, so the
  allOf with if/then is unconditional. The interrupts and interrupt-names constraints should be
  placed directly in the top-level properties section instead. Our automated review praised
  the pattern as forward-extensible without flagging the redundancy (missed-by-us).

Review action:
- Flag [NIT] when an allOf if/then condition tests a compatible enum that contains only the
  single compatible defined in the schema own top-level compatible property.
- Suggest moving the constrained properties directly into the top-level properties section.

False-positive guards:
- Do not flag if the if condition tests against a subset of multiple compatibles listed at the
  top level (different constraints per compatible is the intended use).
- Do not flag bindings explicitly designed as extension templates where additional compatibles
  are documented as forthcoming in the same series.
- One AI-reviewer data point only; apply as [NIT].

Confidence: low
Last updated: 2026-05-26

### MEM-0096: DT binding example — arm-gic interrupt specifier takes exactly 3 cells; trailing extra cell is a bug

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A DT binding YAML example uses interrupts or interrupts-extended with an arm,gic-* parent
- One or more interrupt specifiers contain 4 or more cells (e.g. GIC_SPI N IRQ_TYPE_EDGE_RISING 0)

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-18) on "dt-bindings: remoteproc:
  Document IPQ9650 CDSP": the trailing 0 is a spurious extra cell; arm-gic interrupts take
  3 cells (type, number, flags), not 4. Our automated review missed the extra cell in the
  binding example (missed-by-us).
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-18) on "dt-bindings: soc: qcom:
  Document CDSP Power Management driver": `interrupts-extended = <&intc GIC_SPI 65
  IRQ_TYPE_EDGE_RISING 0>` -- same spurious trailing `0` cell in a different binding
  file. Second independent instance; our automated review again missed it.

Review action:
- Flag [BUG] when an arm-gic interrupt specifier in a DT binding example contains 4 or more
  cells. The GIC format is exactly 3 cells (type, number, flags); a trailing cell is invalid
  and will cause dtbs_check failures.
- Suggest removing the trailing cell(s).

False-positive guards:
- Do not apply to non-GIC interrupt controllers; other controllers may use different cell counts.
- Do not count the parent phandle (e.g. &intc) as a cell — only the specifier cells after it.
- Verify the interrupt parent binding #interrupt-cells value before flagging.

Confidence: medium
Last updated: 2026-05-26

### MEM-0098: DT binding YAML --- `$nodename` pattern must be anchored with `^` and `$`

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A new DT binding YAML defines a `$nodename:` pattern constraint
- The regex is unanchored --- missing the leading `^` and/or trailing `$` delimiter
  (e.g. `"pmic@[0-9a-f]{1,2}"` instead of `"^pmic@[0-9a-f]{1,2}$"`)

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-18) on patch 1/2
  "dt-bindings: regulator: mps,mp8899: Document MPS MP8899 Regulator": pointed
  out `$nodename: pattern: "pmic@[0-9a-f]{1,2}"` is missing `^` and `$`
  anchors, citing `mps,mp5416.yaml` which uses `"^pmic@[0-9a-f]{1,2}$"` as the
  correct form. Our automated review did not flag the missing anchors (missed-by-us).

Review action:
- Flag [MINOR] when a `$nodename:` pattern string is missing `^` at the start
  or `$` at the end.
- Suggest the corrected form: `pattern: "^\<regex\>$"`.

False-positive guards:
- Do not flag if the pattern already has both anchors.
- Do not flag properties other than `$nodename:` unless they also use `pattern:`
  where full-string matching is required; other schema `pattern:` uses follow
  YAML Schema rules and may intentionally omit anchors.
- One AI-reviewer data point only; apply as [MINOR].

Confidence: low
Last updated: 2026-05-26

### MEM-0101: DT binding YAML `title:` must describe the hardware block, not the software driver

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A new DT binding YAML schema sets `title:` to a string ending with "Driver"
  (e.g. "Qualcomm CDSP Power Management Driver")
- The binding describes a hardware block, not a software component

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-18) on "dt-bindings: soc: qcom:
  Document CDSP Power Management driver": `title: Qualcomm CDSP Power Management Driver`
  should be `title: Qualcomm CDSP Power Management` -- the `title:` field describes the
  hardware, not the kernel driver. Our automated review did not flag the word "Driver" in
  the title (missed-by-us).

Review action:
- Flag [NIT] when a DT binding YAML `title:` ends with "Driver" or uses driver-centric
  language (e.g. "... Management Driver", "... Controller Driver").
- Suggest removing "Driver" and rephrasing to describe the hardware block.

False-positive guards:
- Do not flag if "Driver" is part of the hardware's official product name or acronym.
- One AI-reviewer data point only; apply as [NIT].

Confidence: low
Last updated: 2026-05-26

### MEM-0102: DT binding schema must declare `interrupts-extended` if the example uses it

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A DT binding YAML schema declares only `interrupts:` in its properties section
- The inline binding example uses `interrupts-extended =` (needed when interrupts
  come from different interrupt controllers)
- The schema has no `interrupts-extended:` property definition

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-18) on "dt-bindings: soc: qcom:
  Document CDSP Power Management driver": schema defined `interrupts:` only but example
  used `interrupts-extended`; the schema must also define `interrupts-extended` or the
  example uses an undeclared property. Our automated review reported dt_binding_check as
  "PASS" but did not catch this schema/example inconsistency (missed-by-us).

Review action:
- Flag [CONCERN] when a binding schema declares `interrupts:` but the example node uses
  `interrupts-extended =` with no `interrupts-extended:` property in the schema.
- Suggest adding an `interrupts-extended:` definition to the schema, or changing the
  example to use `interrupts:` if a single interrupt controller is sufficient.

False-positive guards:
- Do not flag if the schema already defines `interrupts-extended:` as an alternative.
- Do not flag if both are defined and the example correctly uses one of them.
- Note: some dtschema versions silently accept `interrupts-extended` as a framework-level
  property even without a schema declaration; flag the inconsistency for manual review.
- One AI-reviewer data point; treat as draft.

Confidence: low
Last updated: 2026-05-26

### MEM-0103: New DT binding for a single named SoC must use a SoC-specific compatible as primary entry

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A new DT binding YAML introduces a compatible string for a driver
- The binding description explicitly names one specific SoC as the target
  (e.g. "for the IPQ9650 SoC")
- The `compatible:` block uses only a generic `const:` with no SoC qualifier
  (e.g. `const: qcom,cdsp-power` instead of `const: qcom,ipq9650-cdsp-power`)

Maintainer evidence:
- Our automated review [CONCERN] and Patchwise AI review (kernel@oss.qualcomm.com,
  2026-05-18) on "dt-bindings: soc: qcom: Document CDSP Power Management driver":
  `compatible: const: qcom,cdsp-power` lacks a SoC qualifier despite the binding
  description targeting IPQ9650 only. Upstream DT maintainers require a SoC-specific
  compatible (e.g. `qcom,ipq9650-cdsp-power`) as the primary entry; a generic-only
  compatible cannot be extended without breaking DT ABI. Two independent review sources.

Review action:
- Flag [CONCERN] when a new DT binding description explicitly names one SoC but the
  compatible block has only a generic `const:` with no SoC qualifier.
- Suggest using `qcom,<soc>-<function>` as the primary compatible; a generic fallback
  is acceptable only if the binding is confirmed SoC-agnostic.
- A generic-only compatible cannot later be specialised without DT ABI breakage.

False-positive guards:
- Do not flag class-level bindings covering many SoCs (e.g. `qcom,smem`, `qcom,smp2p`)
  where no per-SoC specialisation is needed.
- Do not flag if a human DT maintainer has already approved the generic-only form.
- Do not flag when the binding description is intentionally SoC-agnostic.

Confidence: low
Last updated: 2026-05-26

### MEM-0106: qcom interconnect binding example -- qcom,bcm-voters must not carry a # prefix

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/interconnect/qcom*
Triggers:
- A DT binding YAML example for a qcom interconnect provider node writes
  #qcom,bcm-voters instead of qcom,bcm-voters (spurious leading #)
- Copy-paste from nearby #interconnect-cells silently adds the # prefix

Maintainer evidence:
- dt_binding_check on patch 1/2 of Maili interconnect series (2026-05-08): reported
  "qcom,bcm-voters is a required property" and unevaluated property #qcom,bcm-voters
  on the gem_noc example node. The aggre_noc sibling node in the same file correctly
  used qcom,bcm-voters, confirming a localised copy-paste error. Our automated review
  caught it via dt_binding_check output. Patchwise AI (same thread) independently
  confirmed the same copy-paste error.

Review action:
- Visually inspect each interconnect provider example node and flag [BUG] if
  qcom,bcm-voters is written as #qcom,bcm-voters.
- The # prefix is valid only for cell-count properties (e.g. #interrupt-cells,
  #interconnect-cells); phandle-list properties like qcom,bcm-voters must not carry it.
- When one sibling example node has the correct spelling and another does not, check
  the entire example block for the same copy-paste error.

False-positive guards:
- Do not flag #interconnect-cells or other legitimate #-prefixed cell-count properties.
- Do not apply outside qcom interconnect binding examples without confirming the
  property is a phandle list rather than a cell count.

Confidence: low
Last updated: 2026-05-26

### MEM-0109: icc-clk binding header -- each node ID group must have a backing clock in the GCC clock header

Status: draft
Scope: file-pattern:include/dt-bindings/interconnect/qcom,*.h
Triggers:
- A patch adds a new icc-clk binding header defining MASTER_*/SLAVE_* node IDs
  grouped by PCIe interface or bus type (e.g. MASTER_ANOC_PCIE0..PCIeN,
  MASTER_CNOC_PCIE0..PCIeN)
- The consuming GCC driver patch is present in the same series for cross-checking

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-16) on patch 1/3
  "dt-bindings: interconnect: Add Qualcomm IPQ9650 support": flagged
  MASTER_CNOC_PCIE0-4 / SLAVE_CNOC_PCIE0-4 (IDs 2,3,6,7,...,18,19) as having
  no corresponding GCC_CNOC_PCIE* clocks in qcom,ipq9650-gcc.h. Our automated
  review caught only the PCIE5 IDs (20-23) and missed the CNOC_PCIE0-4 group.
  Two independent AI reviews agree on the cross-check methodology.

Review action:
- For each node ID group defined in a new icc-clk interconnect header, verify:
  (1) the corresponding GCC clock header defines clocks for that interface
      (e.g. GCC_ANOC_PCIEx_*, GCC_CNOC_PCIEx_* for each PCIe index); and
  (2) the driver icc_hws[] array in the consuming driver patch includes an
      entry for that node ID.
- Flag [CONCERN] for any ID group with no clock header backing, as those IDs
  become permanent ABI that can never be removed after merge.
- Check both ANOC and CNOC sub-groups independently; a SoC may have ANOC but
  no CNOC PCIe clocks.

False-positive guards:
- Do not flag IDs for USB or SNOC nodes whose corresponding clocks are confirmed
  present in the GCC header under a different naming convention.
- Do not flag if a companion driver patch in the series explicitly registers all
  defined IDs via icc_clk_register(), confirming driver-side coverage.
- Single AI-reviewer data point; treat as draft with low confidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0110: checkpatch TYPO_SPELLING false positive for "SoM" (System-on-Module)

Status: draft
Scope: general
Triggers:
- A patch commit message or DT binding description uses "SoM" as an abbreviation
  for System-on-Module
- checkpatch reports WARNING:TYPO_SPELLING: 'SoM' may be misspelled - perhaps 'Some'?

Maintainer evidence:
- Patchwise checkpatch bot (kernel@oss.qualcomm.com, 2026-05-11) flagged "SoM" as a
  TYPO_SPELLING warning across patches 1/4, 3/4, and 4/4 of the Shikra DTS series
  (seven instances total). "SoM" is the accepted industry abbreviation for System-on-Module
  and is not a misspelling; checkpatch's spell-checker does not know this term.

Review action:
- Do not report checkpatch TYPO_SPELLING warnings for "SoM" as a review finding.
- When summarising checkpatch output, note this as a known false positive and exclude
  it from the warning count when assessing patch quality.

False-positive guards:
- Do not suppress genuine TYPO_SPELLING warnings for other terms that happen to appear
  alongside "SoM" in the same checkpatch output.
- If the word "SoM" is used in a context that clearly means "some", flag it; this guard
  applies only to the hardware abbreviation.

Confidence: low
Last updated: 2026-05-26

### MEM-0111: DT binding YAML — single-entry `enum:` list should be `const:`

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A DT binding YAML schema uses `enum:` with exactly one entry (e.g.
  `- enum: [qcom,shikra-iqs-evk]` or a block-form `enum:` with a single item)
- The single-value enum should instead be expressed as `const: value`

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-11) on patch 1/4 of the Shikra
  DTS series (dt-bindings: arm: qcom: Document Shikra and its EVK boards): a
  single-entry `enum: [qcom,shikra-iqs-evk]` was flagged — per dtschema conventions a
  single-value enum must use `const:` instead. Our automated review did not flag this
  (missed-by-us).

Review action:
- Flag [NIT] when a DT binding YAML `enum:` list contains exactly one entry.
- Suggest replacing `enum: [value]` or a block `enum:` with a single item with
  `const: value`.

False-positive guards:
- Do not flag `enum:` lists with two or more entries.
- Do not apply to `oneOf:` blocks that happen to resolve to a single const — the pattern
  applies specifically to a bare `enum:` property with a single-element list.

Confidence: low
Last updated: 2026-05-26

### MEM-0112: Qcom DTS — `status = "okay"` is redundant when the node is not disabled in the base DTSI

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dts
Triggers:
- A board DTS or EVK DTS overrides a node label and includes `status = "okay"`
- The referenced node has no `status = "disabled"` (or `status = "reserved"`) in the
  base DTSI chain; the DT default is "okay", so the override is a no-op

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-11) on patch 4/4 of the Shikra
  DTS series: `&qupv3_0 { firmware-name = ...; status = "okay"; }` — qupv3_0 was not
  disabled in shikra.dtsi so the `status = "okay"` is redundant. Our automated review
  did not flag this (missed-by-us).

Review action:
- Flag [NIT] when a Qcom board DTS override sets `status = "okay"` on a node that is
  not explicitly disabled in any base DTSI in the include chain for that board.
- Suggest removing the redundant line; if the intent is defensive (guard against future
  disablement in the base), a comment is preferable.

False-positive guards:
- Do not flag if the base DTSI or any included DTSI in the chain carries
  `status = "disabled"` or `status = "reserved"` for the same node label.
- Do not flag `status = "okay"` when the SoC base DTSI explicitly documents the node
  as "disabled by default, enabled per-board" (some Qcom base DTSIs follow this
  convention to make board-level intent explicit).
- Do not apply outside Qcom DTS files without additional confirming evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0117: DTS GPIO/property polarity correction — check binding YAML examples for matching stale value

Status: draft
Scope: subsystem:pci/qcom file-pattern:arch/arm64/boot/dts/qcom/*.dts
Triggers:
- A DTS/DTSI patch corrects a GPIO flag (e.g. GPIO_ACTIVE_HIGH → GPIO_ACTIVE_LOW)
  or other property value that was incorrect per the hardware spec
- The corresponding DT binding YAML for that driver/property still hardcodes the
  old incorrect value in its inline example DTS node

Maintainer evidence:
- Patchwise AI reviewers raised this independently on five patches in the 18-patch Qcom
  PCIe wake GPIO polarity series (linux-arm-msm, 2026-05-14):
  - Patch 1/18 (sdx55): qcom,pcie-sdx55.yaml example still used GPIO_ACTIVE_HIGH
  - Patch 3/18 (sdm845): qcom,pcie-sdm845.yaml example still used GPIO_ACTIVE_HIGH
  - Patch 6/18 (sm8250): qcom,pcie-sm8250.yaml example still used GPIO_ACTIVE_HIGH
  - Patch 7/18 (sm8350): qcom,pcie-sm8350.yaml example (line 168) still used GPIO_ACTIVE_HIGH
  - Patch 9/18 (sm8550): qcom,pcie-sm8550.yaml example still used GPIO_ACTIVE_HIGH
  - Patch 14/18 (qcs8300): qcom,pcie-sa8775p.yaml example still used GPIO_ACTIVE_HIGH
  Our automated review missed all of these — a missed-by-us finding repeated six times.

Review action:
- When a DTS/DTSI patch corrects a property value (polarity flag, enum constant, etc.),
  grep the corresponding DT binding YAML file inline example for the old incorrect value.
- If the example still carries the stale value, flag [MINOR]: the binding documentation
  contradicts the DTS fix and will mislead future board porters.
- For qcom PCIe wake-gpios, look in Documentation/devicetree/bindings/pci/
  qcom,pcie-<soc>.yaml or qcom,pcie-common.yaml.
- Suggest updating the binding example in the same patch or a companion patch.

False-positive guards:
- Do not flag if the binding YAML example already uses the corrected value.
- Do not flag if the binding YAML for the property is marked deprecated: true at the
  property level (stale examples in deprecated properties are lower priority).
- Do not flag if a later patch in the same series corrects the binding example
  (check all patches in the series before flagging).
- Apply to DTS corrections of any spec-mandated property value, not only GPIO flags.

Confidence: low
Last updated: 2026-05-26

### MEM-0144: devm_of_icc_get(NULL) -- interconnect-names DT property is not consumed by the driver

Status: draft
Scope: general
Triggers:
- A DTS or DT binding patch adds an interconnect-names property to a node
- The corresponding driver acquires the ICC path by calling devm_of_icc_get(dev, NULL)
  with NULL as the name argument rather than by a named string matching interconnect-names

Maintainer evidence:
- Konrad Dybcio on patch 3/3 "dt-bindings: iommu: arm,smmu: Document optional
  interconnects property" (linux-arm-msm, 2026-05-12): "I don't think
  interconnect-names is useful here, unless you intend to only turn on a subset
  of the paths." The arm-smmu driver calls devm_of_icc_get(smmu->dev, NULL);
  with NULL name the ICC core does not parse interconnect-names. Author agreed
  to remove interconnect-names from both the DTS and binding. Our automated
  review flagged the schema error but missed the deeper issue (missed-by-us).
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-11) on patch 2/3 DTS:
  independently confirmed the property is unused when NULL is passed.

Review action:
- When a DTS patch adds interconnect-names, cross-check the driver ICC acquisition
  call: if devm_of_icc_get() (or of_icc_get()) is called with NULL as the name
  argument, interconnect-names is ignored by the ICC core.
- Flag [MINOR] when interconnect-names is added but the driver uses NULL as the
  name argument to of_icc_get; the property is unused and should be omitted.

False-positive guards:
- Do not flag when the driver calls devm_of_icc_get() with a non-NULL string name
  that matches the proposed interconnect-names value.
- Do not flag when interconnect-names is used to select a specific path from
  multiple interconnects entries (only the named path is voted for).
- Do not flag when interconnect-names is used as a forward-reserved property with
  an explicit comment noting the driver will consume it in a later patch.

Confidence: low
Last updated: 2026-05-26

### MEM-0153: Qcom PCIe DT binding example - use GIC_SPI not GIC_ESPI for standard PCIe interrupts

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/pci/qcom*.yaml
Triggers:
- A new Qcom PCIe DT binding YAML example uses GIC_ESPI (value 2) in interrupts or
  interrupt-map specifiers
- All other Qcom PCIe binding YAML files in the same directory use GIC_SPI (value 1)

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-02) on patch 01/12
  "dt-bindings: PCI: qcom: Document the Hawi PCIe Controller": both the interrupts
  block and interrupt-map used GIC_ESPI while every other Qcom PCIe binding in the
  tree uses GIC_SPI. GIC_ESPI (type 2) requires GICv3 Extended SPI support and a
  separate interrupt-number space. Our automated review did not flag this (missed-by-us).

Review action:
- Flag [MINOR] when a Qcom PCIe DT binding example uses GIC_ESPI instead of GIC_SPI
  in interrupts or interrupt-map entries.
- Cross-check at least one other Qcom PCIe binding YAML in the same directory to confirm
  the expected interrupt type before flagging.

False-positive guards:
- Do not flag if the SoC genuinely uses Extended SPI interrupt ranges (numbers >= 1020)
  for its PCIe interrupt lines and GIC_ESPI is confirmed correct.
- Do not apply outside Qcom PCIe DT binding YAML files without additional evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0154: Qcom PCIe DT binding example - reset-gpios undeclared; perst-gpios is the correct name

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/pci/qcom*.yaml
Triggers:
- A new Qcom PCIe DT binding YAML example includes reset-gpios in its DTS node
- The binding uses allOf [$ref qcom,pcie-common.yaml] with unevaluatedProperties false
- reset-gpios is not declared in qcom,pcie-common.yaml; the host-bridge GPIO reset
  property is perst-gpios

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-02) on patch 01/12
  "dt-bindings: PCI: qcom: Document the Hawi PCIe Controller": example used reset-gpios
  but qcom,pcie-common.yaml declares perst-gpios for the PCIe PERST# line.
  With unevaluatedProperties false, the undeclared property causes a schema validation
  failure. Our automated review did not catch this (missed-by-us).

Review action:
- Flag [MINOR] when a Qcom PCIe binding example uses reset-gpios without declaring it
  in the binding own properties section while the binding inherits
  qcom,pcie-common.yaml with unevaluatedProperties false.
- Suggest using the declared name perst-gpios, or declaring reset-gpios explicitly
  in the binding own properties if it differs from perst-gpios.

False-positive guards:
- Do not flag if reset-gpios is explicitly declared in the new binding properties
  section alongside the qcom,pcie-common.yaml allOf reference.
- Do not flag if qcom,pcie-common.yaml has been updated to declare reset-gpios in
  the same series.

Confidence: low
Last updated: 2026-05-26

### MEM-0156: checkpatch TYPO_SPELLING false positive for Synopsys (semiconductor company name)

Status: draft
Scope: general
Triggers:
- A patch commit message or DT binding YAML uses Synopsys to refer to the semiconductor
  IP company (e.g. Synopsys DesignWare PCIe IP)
- checkpatch reports WARNING:TYPO_SPELLING: Synopsys may be misspelled - perhaps Synopsis?

Maintainer evidence:
- Patchwise checkpatch bot (kernel@oss.qualcomm.com, 2026-05-02) on patch 01/12
  "dt-bindings: PCI: qcom: Document the Hawi PCIe Controller": flagged Synopsys as
  TYPO_SPELLING in "the Synopsys DesignWare PCIe IP." Synopsys is the correct
  registered company name; the checkpatch spell-checker does not recognise it as
  a proper noun. Pattern is identical to MEM-0110 (SoM acronym).

Review action:
- Do not report checkpatch TYPO_SPELLING warnings for Synopsys as a review finding.
- When summarising checkpatch output, note this as a known false positive and exclude it
  from the warning count when assessing patch quality.

False-positive guards:
- Do not suppress if the word is genuinely misspelled (e.g. Synopys).
- Do not suppress other TYPO_SPELLING warnings in the same checkpatch output.

Confidence: low
Last updated: 2026-05-26

### MEM-0161: `reboot-mode` child node of `arm,psci` node — psci.yaml `additionalProperties: false` requires binding update first

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/arm/psci.yaml
Triggers:
- A DTS/DTSI patch adds a `reboot-mode` child node (or any non-`power-domain-*` child) to a `psci` node
- The patch does not include a companion change to `psci.yaml` allowing the new child

Maintainer evidence:
- dtbs_check on Qualcomm PSCI reboot-mode series (kernel@oss.qualcomm.com, 2026-04-23): reported
  "psci (arm,psci-1.0): reboot-mode does not match any of the regexes: ^pinctrl-[0-9]+, ^power-domain-"
  from arm/psci.yaml for every board DTS adding a reboot-mode sub-node. AI review (Patchwise,
  2026-04-23) confirmed psci.yaml has additionalProperties: false and only permits power-domain-*
  children via patternProperties.

Review action:
- Flag [CONCERN] when a DTS patch adds any child node to a psci node without a companion psci.yaml
  binding patch explicitly permitting the new child type.

False-positive guards:
- Do not flag power-domain-* named children; they are already permitted.
- Do not flag when the same series also updates psci.yaml to allow the new child type.

Confidence: low
Last updated: 2026-05-26

### MEM-0162: PSCI binding guard for reboot-mode uses arm,psci-1.0 but SYSTEM_RESET2 is PSCI 1.1

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/arm/psci.yaml
Triggers:
- A psci.yaml binding change gates a reboot-mode node or SYSTEM_RESET2-based property on
  "compatible: contains: const: arm,psci-1.0"
- The feature relies on SYSTEM_RESET2, which is defined in PSCI specification version 1.1

Maintainer evidence:
- AI review (Patchwise/Claude, kernel@oss.qualcomm.com, 2026-04-23) on patch 6/13 of PSCI
  reboot-mode series: identified the binding gates reboot-mode on arm,psci-1.0 but SYSTEM_RESET2
  is PSCI_1_1_FN_SYSTEM_RESET2 (PSCI 1.1). No arm,psci-1.1 compatible exists in the schema so
  the guard is at the wrong version level. Our automated review did not catch this (missed-by-us).

Review action:
- Flag [MINOR] when a PSCI DT binding gates a SYSTEM_RESET2-based feature on arm,psci-1.0; note
  SYSTEM_RESET2 is only available from PSCI 1.1. Suggest either adding arm,psci-1.1 as a compatible
  or documenting the version limitation.

False-positive guards:
- Do not flag for features genuinely available since PSCI 1.0.
- Do not flag if the commit body explains that arm,psci-1.0 is used as the closest available gate.
- One AI-review data point only; apply as [MINOR].

Confidence: low
Last updated: 2026-05-26

### MEM-0166: Unnecessary UEFI/kernel load-address comments in Qcom reserved-memory

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dtsi
Triggers:
- A Qcom SoC DTSI reserved-memory section includes inline comments
  documenting UEFI reclaim addresses or Linux kernel load addresses
  (e.g., `/* UEFI region at 0x9F400000 is reclaimed by Linux */` or
  `/* Linux kernel image is loaded at 0xB5000000 */`)

Maintainer evidence:
- Pankaj Patil on patch 2/4 of the Shikra DTS series (linux-arm-msm,
  2026-05-03): requested removal of both the UEFI reclaim comment and
  the Linux kernel load-address comment from reserved-memory; these have
  no DT functional value. Author acknowledged. Our automated review did
  not flag these (missed-by-us).

Review action:
- Flag [NIT] when a Qcom SoC reserved-memory section contains inline
  comments documenting UEFI reclaim or Linux kernel load addresses.
- Suggest removing them; firmware/bootloader placement is not
  DT-relevant information.

False-positive guards:
- Do not flag comments that describe the purpose or owner of a reserved
  region (e.g., `/* SMEM region */`, `/* TZ stats */`).
- Do not apply outside Qcom SoC DTSI reserved-memory sections without
  further confirming evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0167: Qcom SoC base DTSI psci node must carry a psci: label

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dtsi
Triggers:
- A new Qcom SoC DTSI introduces a `psci { compatible = "arm,psci-1.0"; ... }`
  node without a `psci:` label

Maintainer evidence:
- Pankaj Patil on patch 2/4 of the Shikra DTS series (linux-arm-msm,
  2026-05-03): "Add a label psci: ? Reboot mode node in board file will
  use it." Author acknowledged. The label enables board DTS files to
  reference `&psci { reboot-mode { ... }; };`. Our automated review did
  not flag the missing label (missed-by-us).

Review action:
- Flag [NIT] when a Qcom SoC base DTSI introduces a psci node without
  a `psci:` label.
- Suggest adding `psci:` so board DTS files can attach reboot-mode or
  other child nodes via `&psci`.

False-positive guards:
- Do not flag if the `psci:` label is already present.
- Do not apply outside Qcom SoC base DTSIs without additional evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0168: cache-size property missing in Qcom DTS L2/L3 cache nodes

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dtsi
Triggers:
- A new Qcom SoC DTSI adds L2 or L3 cache nodes (compatible = "cache") to
  the CPU topology section
- The cache nodes omit the `cache-size` property

Maintainer evidence:
- Konrad Dybcio on patch 2/4 of the Shikra DTS series (linux-arm-msm,
  2026-05-04): requested `cache-size = <(256 * 1024)>` in the L2 cache
  node and `cache-size = <(512 * 1024)>` in the L3 cache node. Author
  acknowledged. Our automated review did not flag the missing cache-size
  properties (missed-by-us).

Review action:
- Flag [NIT] when a Qcom SoC DTSI adds cache nodes (compatible = "cache")
  that omit `cache-size`.
- Suggest adding `cache-size = <(size_in_bytes)>` from the SoC hardware
  specification.

False-positive guards:
- Do not flag if `cache-size` is already present in the node.
- Do not apply outside CPU cache topology nodes (compatible = "cache").

Confidence: low
Last updated: 2026-05-26

### MEM-0169: Qcom MPM qcom,mpm-pin-count must match RPM firmware virtual count

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dtsi
Triggers:
- A new Qcom SoC DTSI adds a `qcom,mpm` interrupt controller node
- The `qcom,mpm-pin-count` value matches ipcat physical-entry count rather
  than the virtual count exposed by the RPM firmware

Maintainer evidence:
- Konrad Dybcio on patch 2/4 of the Shikra DTS series (linux-arm-msm,
  2026-05-05): asked whether qcom,mpm-pin-count = <95> matched the virtual
  MPM count from RPM firmware (historically 96). Sneh Mankad (2026-05-11)
  confirmed RPM firmware exposes 96 interrupts; the DTS value of 95 was
  wrong. Our automated review did not flag this (missed-by-us).

Review action:
- Note that `qcom,mpm-pin-count` must match the virtual interrupt count
  exposed by the RPM firmware, not the ipcat physical pin count.
- Flag [MINOR] if the count appears inconsistent with sibling Qcom
  RPM-based SoC DTSIs (e.g., agatti.dtsi, sm6115.dtsi).

False-positive guards:
- Do not flag if the count is confirmed correct by the firmware team or
  matches sibling SoC DTSIs in the same family.
- Do not apply outside RPM-based Qcom platforms using `qcom,mpm`.

Confidence: low
Last updated: 2026-05-26

### MEM-0170: DTS reg address entries must use consistent hex zero-padding width

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dtsi
Triggers:
- A DTS/DTSI node `reg` property contains multiple address entries
- One or more entries use fewer leading zeros than adjacent entries in the
  same `reg` list (e.g., `<0x0 0x0f00000 ...>` next to `<0x0 0x00e00000 ...>`)

Maintainer evidence:
- Konrad Dybcio on patch 2/4 of the Shikra DTS series (linux-arm-msm,
  2026-05-04): noted `0x0f00000` in the LLCC `reg` array is missing a
  leading zero compared to adjacent `0x00e00000` and `0x01000000` entries.
  Requested consistent 8-digit hex formatting. Our automated review did
  not flag this (missed-by-us).

Review action:
- Flag [NIT] when a DTS `reg` array mixes hex address widths within the
  same property (e.g., some entries are 7-digit, others 8-digit).
- Suggest padding all address values in a `reg` list to the same width
  (typically 8 hex digits for 32-bit fields in a 64-bit address space).

False-positive guards:
- Do not flag single-entry `reg` properties.
- Do not flag if all entries in the `reg` list are consistently formatted
  even if not at the maximum width.

Confidence: low
Last updated: 2026-05-26

### MEM-0172: DT binding fallback-group addition — commit body must confirm hardware property compatibility with fallback SoC

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A patch adds a new SoC-specific compatible string to an items+const fallback group
  in a YAML binding schema (the new SoC reuses an existing SoC's driver and hardware
  model via a generic fallback compatible)
- The commit body confirms driver compatibility (e.g. "uses the same kaanapali fallback")
  but does not state whether the new SoC's hardware properties (DMA bus width, clock
  topology, register layout) match those of the fallback SoC

Maintainer evidence:
- Dmitry Baryshkov on "dt-bindings: misc: qcom,fastrpc: Add Maili FastRPC compatible"
  (linux-arm-msm, 2026-05-25): asked "Can I assume that it has the same bus width as
  Kaanapali?" before accepting. Yijie Yang (author) confirmed DMA width for CDSP and ADSP
  is the same; Baryshkov replied "Thanks for the confirmation." The reviewer's initial
  question shows the hardware compatibility is not assumed from driver fallback alone.
  Our automated review verified driver of_match coverage but did not ask whether Maili's
  hardware properties match the kaanapali fallback (missed-by-us).

Review action:
- When a patch adds a new SoC compatible to an items+const fallback group, check whether
  the commit body confirms that the new SoC's relevant hardware properties (bus width,
  DMA configuration, register layout) match the fallback SoC.
- Flag [NIT] when the body establishes driver compatibility but omits any statement
  that the hardware characteristics match (e.g. "Maili has the same DMA bus width and
  register layout as Kaanapali").
- Suggest adding a one-sentence hardware compatibility statement to the commit body.

False-positive guards:
- Do not flag if the commit body already states that the hardware properties match the
  fallback SoC explicitly.
- Do not flag for standalone-enum compatibles with no items+const fallback pairing; the
  hardware compatibility question arises specifically because a shared fallback implies
  shared hardware behaviour.
- Apply as [NIT] only; omitting the statement does not block the patch if a maintainer
  confirms compatibility directly in the review thread.

Confidence: low
Last updated: 2026-05-30

### MEM-0176: DT binding YAML example — hardware-specific property values must match the target SoC

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A DT binding YAML adds or updates an inline example DTS node
- The example contains a hardware-specific numerical value (IOMMU stream ID,
  register address, interrupt number, stream-function constant) that was
  copied from a different SoC and does not match the hardware named by the
  binding's compatible string or YAML filename

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-21) on patch 1/5
  "dt-bindings: media: qcom: venus: add iommu-map support": the example in
  qcom,sc7180-venus.yaml used iommu-map = <VENUS_FIRMWARE &apps_smmu 0xe42 0x1>
  where 0xe42 is the QCS615 Venus firmware SMMU stream ID; the SC7180 firmware
  stream is 0x0c42. Our automated review did not cross-check the stream ID
  against the SoC the binding targets (missed-by-us).

Review action:
- When a binding example includes a hardware-specific numerical value (stream
  ID, SID, register address, cell value), cross-check it against the SoC named
  in the binding compatible string or YAML filename.
- Flag [MINOR] when a numerical value in the example appears inconsistent with
  the target SoC (e.g., value taken from a different SoC's DTS without updating).
- For IOMMU stream IDs, cross-reference the board DTS for the named SoC to
  verify the expected stream ID.

False-positive guards:
- Do not flag illustrative placeholder values explicitly marked as examples
  (e.g., a comment saying "replace with your SoC's stream ID").
- Do not flag values that are SoC-agnostic (e.g., a mask cell of 0x1 in
  an iommu-map entry, or a logical function-ID constant defined for all SoCs).
- One AI-reviewer data point only; treat as draft and apply as [MINOR].

Confidence: low
Last updated: 2026-05-26

### MEM-0201: DT binding YAML example — embedded DTS node contents must use tab indentation, not spaces

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A new or modified DT binding YAML file contains an `examples:` section with
  embedded DTS node blocks
- The property lines inside those node blocks use space characters for indentation
  rather than tab characters

Maintainer evidence:
- Patchwise AI review (2026-05-26) on patch 1/3 of Shikra EPSS L3 series:
  "The example is not indented as DTS. Use tabs for the node contents."
  The epss_l3 example node used spaces for its properties (compatible, reg,
  clocks, etc.) rather than tabs. The automated review did not flag this
  (missed-by-us). AI-reviewer data point only; no human maintainer confirmation.

Review action:
- Flag [NIT] when properties inside a node block in a YAML `examples:` section
  are indented with spaces rather than tabs.
- The standard Linux DT binding convention for embedded DTS examples is to use
  tab characters for node-content indentation (matching how DTS files are written
  elsewhere in the kernel tree).

False-positive guards:
- Do not flag the YAML-level indentation (the leading spaces that make the DTS
  block a valid YAML scalar) -- only the indentation within node content (properties
  between the opening and closing braces) must use tabs.
- Do not flag if the binding example uses consistent tabs throughout the node body.
- Single AI-reviewer data point only; treat as draft until confirmed by human
  reviewer or `dt_binding_check` output.

Confidence: low
Last updated: 2026-05-27

### MEM-0209: DT binding YAML — `properties: X: true` in an `allOf if/then` does not restrict X to that compatible

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A YAML binding schema declares a new property (e.g. `qcom,rpmh`, `qcom,pmic-id`) in the
  top-level `properties:` block (making it globally valid for all compatibles)
- The same schema uses an `allOf if/then` block to gate the new property to a specific
  compatible (e.g. `qcom,pmh0101-gpio`) by listing `X: true` in the `then: properties:` section
- The intent is to restrict the property to that compatible only

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 2/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com:
  "Because these properties are defined in the top-level properties block, they are globally
  permitted for all PMIC compatibles. Setting them to true in this then block is a no-op in
  JSON schema, as affirming a property is allowed does not forbid it from appearing in
  unmatched conditionals. Should the schema explicitly forbid these properties for unsupported
  variants?" Our automated review did not flag this (missed-by-us).
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-28) on the same patch: "Setting
  them to true in this then block is a no-op in JSON schema. If these are required [for
  pmh0101], add them to a required: list in this schema branch." Second independent
  AI-reviewer data point on the same patch confirming the no-op pattern.

Review action:
- Flag [MINOR] when a YAML binding declares a new property at the top level AND uses
  `X: true` in an `allOf if/then then: properties:` block with the stated intent of
  restricting X to a subset of compatibles. The `true` is a no-op: the property is already
  permitted by the top-level declaration for all compatibles.
- To actually restrict the property to a specific compatible, either omit the top-level
  declaration and declare it only inside the `then:` block, or add an explicit
  `else: properties: X: false` to prohibit it for non-matching compatibles.
- If the property should be *required* (not merely allowed) for the matching compatible,
  add it to a `required:` list in the `then:` block; `X: true` alone does not enforce
  the presence of X.

False-positive guards:
- Do not flag `X: true` when the intent is simply to document that X is expected for a
  particular compatible and no exclusion of other compatibles is intended.
- Do not flag when the property is constrained by `unevaluatedProperties: false` or
  `additionalProperties: false` at the top level — that changes the semantics and the
  top-level declaration may be intentionally absent.
- Two AI-reviewer data points; keep as draft until human maintainer confirms.

Confidence: low
Last updated: 2026-05-30

### MEM-0227: DT binding YAML `allOf if/then` — `compatible: enum` doesn't match array-typed property; use `contains: const` or `contains: enum`

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- An `allOf if/then` block uses `compatible: enum: [<value>]` (or `compatible: const: <value>`)
  as the if condition to select per-SoC property constraints
- The binding is for a device that may use two-element compatible strings (SoC-specific +
  generic fallback), e.g. `["qcom,x1p42100-iris", "qcom,sm8550-iris"]`

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 1/5 of iris purwa series
  (20260529-enable_iris_on_purwa-v8-0-b1b9670459ab@oss.qualcomm.com): flagged [Medium]
  "Broken schema conditional matching for qcom,x1p42100-iris causes valid device tree nodes
  to fail validation" — compatible is an array of strings; `compatible: enum: [foo]` tests
  that the array equals exactly `[foo]`, which never matches a node with a two-element
  compatible array. The if condition is always false; the then constraints silently do not
  apply. The correct form is `compatible: contains: {const: foo}` or
  `compatible: contains: {enum: [foo, bar]}`.

Review action:
- Flag [CONCERN] when an `allOf if/then` block uses `compatible: enum:` or `compatible: const:`
  to match a SoC-specific compatible that may appear alongside a generic fallback in an array.
- Suggest replacing with `compatible: contains: {const: <value>}` (for a single compatible)
  or `compatible: contains: {enum: [<values>]}` (for multiple alternatives).

False-positive guards:
- Do not flag when the binding schema explicitly requires a single-element compatible array
  (e.g., `compatible: minItems: 1 maxItems: 1`) — in that case array equality is correct.
- Do not flag top-level `compatible:` schema definitions (not inside an `if:` block); this
  issue is specific to conditional `if:` matching.
- One AI-reviewer (sashiko-bot) data point; treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0228: DT binding YAML `allOf if/then` — `minItems` in `then:` without `required:` does not prevent absent mandatory properties

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- An `allOf if/then` block adds per-compatible constraints using `minItems` for a clock,
  interrupt, or other list property (e.g. `clocks: minItems: 4`)
- The `then:` block does not list those properties in a `required:` entry
- The stated or implied intent is that the property is mandatory for that compatible

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 1/5 of iris purwa series
  (20260529-enable_iris_on_purwa-v8-0-b1b9670459ab@oss.qualcomm.com): flagged [Medium]
  "Missing required properties in the conditional block for qcom,x1p42100-iris allows
  incomplete device tree nodes to pass validation" — `minItems` constrains the minimum
  count only when the property is present; a node that omits `clocks` entirely still passes
  schema validation. Without `required: [clocks, clock-names]` inside the `then:` block,
  the mandatory fourth clock can be silently absent.
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-28) on [PATCH v2 2/5] dt-bindings: clock:
  qcom: Add Qualcomm Shikra Display clock controller (linux-arm-msm): flagged [Medium]
  "The conditional schema for 'qcom,shikra-dispcc' fails to enforce the presence of its 3
  newly required input clocks because `minItems` is not overridden in the `then` block" —
  the top-level `minItems: 6` means a node with only 6 clocks can still pass even though
  9 are required for Shikra. The `then:` block should add `minItems: 9` alongside the
  `items:` list to enforce the count. Second independent AI-reviewer instance of this
  pattern in a different driver binding.

Review action:
- Flag [MINOR] when an `allOf if/then then:` block uses `minItems` or an `items:` list to
  enforce a minimum count for a property that is mandatory for the matched compatible, but
  the `then:` block does not include that property in a `required:` list or does not also
  override `minItems` to enforce the per-compatible minimum count.
- Suggest adding the property to `required:` inside `then:`, and if the top-level
  `minItems` is lower than required, add an explicit `minItems: N` inside `then:`.
- Similarly, adding `maxItems: N` to the `else:` block for the non-matching compatible
  prevents that branch from silently accepting the extra items.

False-positive guards:
- Do not flag when the property is already listed in the top-level `required:` (enforced
  unconditionally for all compatibles, so the per-compatible `then:` enforcement is redundant
  but not wrong).
- Do not flag when the property is genuinely optional for that compatible and `minItems`
  only constrains the list length when the property appears.
- Two AI-reviewer (sashiko-bot) data points; no human maintainer confirmation yet — treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0230: Qcom USB DWC3 board DTS — `dr_mode = "otg"` is the default and should be dropped

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dts
Triggers:
- A Qcom board DTS override block for a DWC3 USB node (e.g. `&usb_1`) includes
  `dr_mode = "otg"` without an explicit reason to set the value

Maintainer evidence:
- Dmitry Baryshkov (Qcom DTS/USB maintainer) on [PATCH v7 2/2] arm64: dts: qcom:
  Add Xiaomi 12 Lite 5G (taoyao) DTS (linux-arm-msm, 2026-05-29):
  "This is default, it can be dropped." when the board DTS `&usb_1` override
  contained `dr_mode = "otg"`. Our automated review did not reach this patch
  (apply failure) — missed-by-us.

Review action:
- Flag [NIT] when a Qcom board DTS sets `dr_mode = "otg"` in a DWC3 USB node
  override without accompanying context requiring a non-default value.
- `dr_mode = "otg"` is the default DWC3 operating mode; the property is redundant
  unless overriding a SoC DTSI that explicitly sets a different mode.
- Suggest removing the property or adding a comment if the intent is to override a
  SoC-level `dr_mode` setting.

False-positive guards:
- Do not flag if the SoC base DTSI for that USB controller explicitly sets
  `dr_mode` to a different value (e.g., `"host"` or `"peripheral"`) and the
  board DTS is intentionally overriding it to `"otg"`.
- Do not apply outside Qcom board DTS files without additional evidence.
- One maintainer data point; treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0231: Qcom USB DWC3 — `usb-role-switch` belongs in SoC DTSI, not board DTS

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dts
Triggers:
- A Qcom board DTS adds `usb-role-switch` to a DWC3 USB node override block
  (e.g. `&usb_1`) when the SoC DTSI for that USB controller does not already
  carry the property

Maintainer evidence:
- Dmitry Baryshkov (Qcom DTS/USB maintainer) on [PATCH v7 2/2] arm64: dts: qcom:
  Add Xiaomi 12 Lite 5G (taoyao) DTS (linux-arm-msm, 2026-05-29):
  "This should go to the SoC DT." when `usb-role-switch` appeared in the board
  DTS `&usb_1` override. The property describes a capability of the SoC USB
  controller, not a board-specific configuration. Our automated review did not
  reach this patch (apply failure) — missed-by-us.

Review action:
- Flag [MINOR] when a Qcom board DTS adds `usb-role-switch` to a DWC3 USB node
  override and the SoC DTSI for that USB controller does not already contain it.
- The property reflects a hardware capability of the SoC USB controller and should
  live in the SoC-level DTSI rather than the board DTS.
- Suggest moving it to the SoC DTSI (e.g., sm7325.dtsi for SM7325 `usb_1`) and
  keeping the board DTS override minimal.

False-positive guards:
- Do not flag if `usb-role-switch` is already present in the SoC DTSI for that
  USB controller node; the board DTS override would then be redundant, not wrong.
- Do not flag if the board DTS is the only DTS file introducing this SoC (i.e.,
  no shared SoC DTSI exists yet for this IP block) and a SoC DTSI patch is not
  part of the same series.
- One maintainer data point; treat as draft.

Confidence: low
Last updated: 2026-05-29

### MEM-0232: `usb-c-connector` in pmic-glink node — SBU endpoint must use `port@2`, not `port@1`

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dts
Triggers:
- A board DTS adds a `usb-c-connector` node inside a `pmic-glink` block
- The SBU (Sideband Use) endpoint (e.g., `pmic_glink_sbu` connecting to an SBU mux)
  is placed in `port@1` instead of `port@2`

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org) on [PATCH v7 2/2] arm64: dts: qcom:
  Add Xiaomi 12 Lite 5G (taoyao) DTS (2026-05-28): "[Low] The Type-C SBU endpoint
  in the `pmic-glink` connector node is incorrectly assigned to `port@1` instead
  of `port@2`." Per the `usb-connector.yaml` binding, `port@0` = HS data lines,
  `port@1` = SS (SuperSpeed) data lines, `port@2` = SBU lines. Assigning SBU to
  `port@1` violates the DT schema even when SuperSpeed lines are absent. Our
  automated review did not reach this patch (apply failure) — missed-by-us.

Review action:
- Flag [MINOR] when a `usb-c-connector` node places the SBU endpoint in `port@1`.
  Per `usb-connector.yaml`: `port@0` = HS, `port@1` = SS, `port@2` = SBU.
- This applies even when SuperSpeed is not implemented; the USB Type-C connector
  schema fixes port indices regardless of whether SS ports are physically present.
  `port@1` must be omitted or reserved, not reused for SBU.
- Suggest renaming the SBU port/endpoint to `port@2` / `reg = <2>`.

False-positive guards:
- Do not flag if the SBU endpoint is already at `port@2`.
- Do not flag if the DTS uses a custom (non-standard) binding that documents
  a different port assignment with explicit maintainer acceptance.
- One AI-reviewer (sashiko-bot) data point; treat as draft with low confidence.
  Verify against the current usb-connector.yaml schema before flagging.

Confidence: low
Last updated: 2026-05-29

### MEM-0234: DTS uses clock constant from prerequisite series not yet in tree — causes DT build failure

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dtsi
Triggers:
- A board DTS or SoC DTSI references a clock constant (e.g. `VIDEO_CC_MVS0_BSE_CLK`)
  from a clock-controller binding header (e.g. `dt-bindings/clock/qcom,videocc-*.h`)
- That header, and thus the constant, is part of a prerequisite series (clock controller
  driver/binding) not yet merged into the review tree
- The series declares the prerequisite via `prerequisite-change-id` or `prerequisite-patch-id`
  cover-letter tags

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 4/5 of iris purwa series
  (20260529-enable_iris_on_purwa-v8-0-b1b9670459ab@oss.qualcomm.com part=4): flagged [Low]
  that `VIDEO_CC_MVS0_BSE_CLK` was undefined — the macro was expected to come from the
  prerequisite purwa videocc/camcc series not yet present in the tree. The CPP would leave
  it unexpanded, causing a dtc syntax error and a DT build failure. Our automated review
  was skipped (CANNOT APPLY) and could not catch this; the pattern is reusable for series
  that declare missing clock-controller prerequisites.

Review action:
- When a series declares one or more `prerequisite-patch-id` or `prerequisite-change-id`
  tags for a missing clock controller series, scan the new DTS patches for clock constants
  (e.g. `<&videocc VIDEO_CC_*>`, `<&gcc GCC_*>`) and cross-check against the in-tree
  clock-controller header for that SoC.
- If a constant is absent from the in-tree header and the missing prerequisite is the
  expected source, flag [CONCERN]: the DTS build will fail with an undeclared identifier.
- Correlate with the DEPENDENCY MISSING header finding — missing prerequisites make
  undefined constants predictable.

False-positive guards:
- Do not flag constants that are already present in the in-tree clock header for that
  SoC (confirm by grepping `include/dt-bindings/clock/`).
- Do not flag when the clock constant is defined in the same series (new binding header
  added before the DTS patch).
- Apply cautiously when the series did apply cleanly; the concern is most relevant
  when a prerequisite series is flagged as missing.

Confidence: low
Last updated: 2026-05-29

### MEM-0237: Qcom DISPCC/GPUCC binding — new SoC extends existing SoC binding with more inputs; check existing SoC hardware too

Status: draft
Scope: subsystem:clk/qcom file-pattern:Documentation/devicetree/bindings/clock/qcom,*dispcc*.yaml Documentation/devicetree/bindings/clock/qcom,*gpucc*.yaml
Triggers:
- A DT binding patch extends an existing Qcom DISPCC or GPUCC YAML binding to add a
  new SoC (e.g. `qcom,shikra-dispcc`) as a fallback compatible for an existing one
  (e.g. `qcom,qcm2290-dispcc`), with additional required input clocks for the new SoC
- The existing SoC hardware (per IPCAT / hardware block reference) also supports the
  same additional inputs (e.g. DSI1 PHY clocks) but they were not previously exposed
  in the binding

Maintainer evidence:
- Dmitry Baryshkov on [PATCH v2 2/5] dt-bindings: clock: qcom: Add Qualcomm Shikra Display
  clock controller (linux-arm-msm, 2026-05-28): "According to the IPcat, display clock
  controller also has (unused) inputs for the DSI1. Please extend the ABI for Agatti, then
  extend add Shikra." — when the patch only added DSI1 clock-names for the new
  `qcom,shikra-dispcc` compatible but left the existing `qcom,qcm2290-dispcc` (Agatti)
  binding unchanged. Our automated review raised the DSI1 byte clock miss but did not
  flag the existing-SoC ABI gap (missed-by-us).
- Dmitry Baryshkov follow-up on same thread (2026-05-29): "Also make sure to not change
  the order of the clocks, you can't break the ABI." — rebutting author's proposal to
  remove clock-names and switch to index-based approach in the same series, which would
  have broken existing device trees.

Review action:
- When a patch extends an existing Qcom display/GPU clock binding with new input clocks for
  a new SoC, cross-check whether the existing SoC hardware (IPcat or reference implementation)
  also exposes the same inputs.
- If the existing SoC hardware supports the same inputs, flag [CONCERN]: the new SoC binding
  extension should first extend the existing SoC's ABI before adding the new SoC, so the
  existing and new SoC can share the same clock-names list.
- When new clocks are appended to an existing `clock-names` list, also flag [CONCERN] if
  the patch removes or reorders existing clock-names entries: the kernel DT ABI requires
  that existing entries remain at the same index position.
- The updated driver must degrade gracefully when the old DT (without new clock entries)
  is used; new clocks should be optional or probed by name/index with a NULL check.

False-positive guards:
- Do not flag when the existing SoC hardware genuinely does not have the additional inputs
  (confirmed by hardware reference / schematic).
- Do not flag when the patch author already extends both SoCs' bindings in the same series.
- Do not apply outside Qcom DISPCC/GPUCC bindings without separate maintainer confirmation.
- One series; treat as draft.

Confidence: medium
Last updated: 2026-05-29

### MEM-0254: Qcom DT binding filename missing `qcom,` prefix silently drops linux-arm-msm from get_maintainer

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/*/qcom*
Triggers:
- A Qualcomm DT binding YAML filename does not carry the `qcom,` prefix
  (e.g. `sdhci-msm.yaml` instead of `qcom,sdhci-msm.yaml`)
- As a result the file does not match the MAINTAINERS wildcard
  `F: Documentation/devicetree/bindings/*/qcom*` in the ARM/QUALCOMM MAILING
  LIST entry, so `linux-arm-msm@vger.kernel.org` is absent from
  `get_maintainer.pl` output for that binding

Maintainer evidence:
- Manivannan Sadhasivam submitted dt-bindings: mmc: sdhci-msm: Rename the
  binding to include 'qcom' prefix
  (20260528135342.11678-1-manivannan.sadhasivam@oss.qualcomm.com, 2026-05-28)
  because sdhci-msm.yaml was the sole Qualcomm binding file without the `qcom,`
  prefix; linux-arm-msm@vger.kernel.org was absent from get_maintainer.pl output.
  Ulf Hansson applied it with "Applied for next, thanks!" — no corrections
  requested, confirming the READY TO APPLY verdict (confirmed).

Review action:
- When reviewing a new or renamed Qualcomm DT binding YAML, verify the filename
  starts with `qcom,` (e.g. `qcom,sdhci-msm.yaml`).
- If the prefix is absent, flag [MINOR]: the file will miss the
  `Documentation/devicetree/bindings/*/qcom*` MAINTAINERS wildcard, and
  `linux-arm-msm@vger.kernel.org` will not appear in `get_maintainer.pl` output.
- Also verify the `$id` field matches the new filename path exactly.

False-positive guards:
- Do not flag Qualcomm binding files that already carry the `qcom,` prefix.
- Do not flag non-Qualcomm vendor binding files; the wildcard in question is
  specific to the ARM/QUALCOMM MAILING LIST section of MAINTAINERS.
- Do not flag if the file is already covered by a MAINTAINERS entry that
  explicitly lists linux-arm-msm@vger.kernel.org.

Confidence: low
Last updated: 2026-05-29

### MEM-0260: Qcom DTS overlay shared by multiple boards — filename must reflect the common base, not one specific board

Status: draft
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dtso
Triggers:
- A DTS overlay file and its Makefile entry are named after one specific board
  variant (e.g. `shikra-cqm-evk-imx577-camera.dtso`)
- The commit body states the overlay is shared by multiple board variants
  because their hardware is identical on the overlaid subsystem

Maintainer evidence:
- Bryan O'Donoghue on patch 7/8 "arm64: dts: qcom: shikra-cqm-evk-imx577-camera:
  Add DT overlay" (linux-arm-msm, 2026-05-28): "If the overlay is not specific to
  board then the overlay should have some kind of base name
  shikra-evk-imx577-camera.dtb." Acknowledged as a NIT.
  Our automated review accepted the filename without noting the naming mismatch
  (missed-by-us).
- Nihal Kumar Gupta (author, 2026-05-29) clarified: the CQM overlay is shared with
  CQS because both use PM4125 PMIC with identical camera supply rails; IQS uses
  PM8150 with different supply rails so it requires its own overlay and cannot share.
  Author proposed renaming to `shikra-cqm-cqs-evk-imx577-camera` to make the shared
  scope explicit, noting a generic name would be misleading given IQS incompatibility.
  This confirms: when boards share an overlay due to a specific common attribute (same
  PMIC, same supply rails), naming that attribute in the filename is an acceptable
  alternative to a fully generic base name.
- Bryan O'Donoghue (2026-05-29) explicitly accepted the author's proposed rename:
  "That would sufficiently pick the nit for me." — confirming that listing all sharing
  board identifiers in the filename is the right resolution when a fully generic name
  would be misleading.

Review action:
- Flag [NIT] when a DTS overlay commit body says the overlay applies to multiple
  board variants but the overlay filename identifies only one of those boards by name
  without reflecting the shared hardware scope.
- Suggest either: (a) a name that lists all sharing boards (e.g.
  `shikra-cqm-cqs-evk-imx577-camera.dtso`), or (b) a generic base name (e.g.
  `shikra-evk-imx577-camera.dtso`) when all boards with that feature can use it.
- Do not suggest a single generic name when hardware differences between board
  families (e.g. different PMICs / supply rails) would make that name misleading.

False-positive guards:
- Do not flag overlays that genuinely differ between board variants (different
  supply rails, GPIO assignments, or sensor configurations).
- Do not flag when all sharing boards happen to carry the same identifier in
  their names.
- Do not suggest merging distinct per-PMIC overlays into one generic overlay when
  the author has confirmed hardware incompatibility (different supply rails).

Confidence: medium
Last updated: 2026-05-30

### MEM-0273: Qcom PCIe DT binding — compatible string must follow `qcom,pcie-<soc>` (function-first) convention

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/pci/qcom*.yaml
Triggers:
- A new Qualcomm PCIe DT binding YAML introduces a compatible string in the
  form `qcom,<soc>-pcie` (SoC-first) rather than `qcom,pcie-<soc>`
  (function-first)
- The binding file is also named `qcom,<soc>-pcie.yaml` instead of
  `qcom,pcie-<soc>.yaml`

Maintainer evidence:
- Our automated review [MINOR] on patch 1/2 of
  [PATCH v2 0/2] PCI: qcom: Add PCIe support for upcoming Hawi SoC
  (20260529-hawi-pcie-v2-0-de87c6cc230c@oss.qualcomm.com, 2026-05-29):
  all 18+ sibling Qcom PCIe bindings in the same directory use
  `qcom,pcie-<soc>` (e.g. qcom,pcie-sc7280, qcom,pcie-sm8550,
  qcom,pcie-x1e80100, qcom,pcie-sa8775p). New binding used `qcom,hawi-pcie`
  (SoC-first), breaking the subsystem convention.
- Sashiko AI reviewer on patch 2/2 (2026-05-29): independently flagged the
  compatible string naming as medium-severity, citing both the convention
  violation and the failure to differentiate distinct controller instances.
  Two independent automated reviewers; no human maintainer response yet.

Review action:
- Flag [MINOR] when a new Qualcomm PCIe binding uses `qcom,<soc>-pcie` form.
- Cross-check all sibling bindings in
  Documentation/devicetree/bindings/pci/qcom*.yaml to confirm the expected
  `qcom,pcie-<soc>` pattern before flagging.
- Suggest renaming the file to `qcom,pcie-<soc>.yaml`, updating the `$id:` URL
  accordingly, and changing the compatible string to `const: qcom,pcie-<soc>`.
  Also note the driver of_device_id entry in the companion driver patch must be
  updated to match.

False-positive guards:
- Do not flag bindings where a DT maintainer has explicitly approved the
  SoC-first form for this specific compatible.
- Do not apply outside Qcom PCIe bindings without confirming the sibling naming
  pattern first; other Qcom subsystems may use different conventions.
- Two automated-reviewer data points only; keep as draft until a human DT
  maintainer explicitly requests the rename.

Confidence: low
Last updated: 2026-05-30

### MEM-0275: DT binding `qcom,pmic-id`-style properties — do not use instance IDs; use DT-standard identification

Status: draft
Scope: subsystem:qcom file-pattern:Documentation/devicetree/bindings/
Triggers:
- A DT binding patch introduces a new Qualcomm `qcom,pmic-id` (or similarly named
  instance-ID) property to carry a string identifier such as `"A_E0"` that encodes
  an internal firmware resource name suffix
- The DT binding maintainer has documented that instance IDs are forbidden in DT
  bindings (see Documentation/devicetree/bindings/chosen.yaml or maintainer precedent)

Maintainer evidence:
- Krzysztof Kozlowski (DT bindings maintainer) on patch 2/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com (2026-05-30):
  "You do not get instance IDs (it's explicitly documented in docs)." — objecting to
  the `qcom,pmic-id` property that carried a firmware-instance-ID string
  (pattern `^[A-N]_E[0-3]+$`) used as an RPMh resource name suffix. Our automated
  review did not flag the instance-ID property (missed-by-us).
- Patchwise AI review on the same patch independently flagged the regex pattern
  `^[A-N]_E[0-3]+$` accepting invalid suffixes like `A_E00` (trailing `+` vs `$`),
  but did not identify the instance-ID prohibition.

Review action:
- Flag [CONCERN] when a new DT binding property encodes an internal firmware or
  hardware instance-ID (a string that names a specific instance within a larger class,
  such as `A_E0`, `B_E1`, a numeric PMIC slot index, etc.).
- Instance IDs violate DT philosophy: hardware identity must be expressed through
  compatible strings, reg addresses, or vendor-defined structural properties that
  describe the hardware topology, not internal firmware naming.
- Suggest expressing the PMIC identity through the compatible string or an existing
  DT address/node-name mechanism instead of an opaque string ID.

False-positive guards:
- Do not flag properties that carry physical hardware identifiers embedded in silicon
  (e.g. SMEM chip ID, eFuse slot index when no compatible string covers the variant).
- Do not flag if the DT binding maintainer has explicitly approved an instance-ID
  property in this thread or a prior version of the same series.
- Do not flag non-PMIC drivers without additional maintainer evidence.

Confidence: medium
Last updated: 2026-05-30

### MEM-0276: DT binding custom vendor voltage/enable property — check for standard pinconf generic properties first

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/pinctrl/
Triggers:
- A pinctrl DT binding patch introduces a new custom `qcom,<name>-ls-en` (or similar
  vendor-specific) property to enable/disable a voltage-level-related hardware function
  (e.g. a bidirectional level shifter)
- No standard generic pinconf property (e.g. `output-enable`, `drive-strength`,
  `power-source`) covers the hardware function
- The commit body does not explain why existing generic pinconf properties are insufficient

Maintainer evidence:
- Krzysztof Kozlowski (DT bindings maintainer) on patch 2/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com (2026-05-30):
  "And there are no generic pinconf properties defining the voltage?" — questioning
  whether a standard generic property could replace `qcom,1p2v-1p8v-ls-en`. Our
  automated review did not flag the missing generic-property evaluation (missed-by-us).

Review action:
- Flag [MINOR] when a new vendor-specific pinctrl property controls a voltage-selection
  or enable/disable function without the commit body explaining why standard generic
  pinconf properties (see include/dt-bindings/pinctrl/pinctrl.h and pinctrl generic
  bindings) are insufficient.
- Suggest checking `output-enable`, `drive-strength-microamp`, `power-source`, and the
  full generic-pinconf property list before introducing a vendor property.

False-positive guards:
- Do not flag if the commit body or cover letter already explains why generic properties
  cannot represent the hardware function (e.g. the property controls a separate
  always-on hardware block unrelated to pin drive mode).
- Do not flag vendor properties that describe hardware entirely outside the standard
  pinconf model (e.g. a DMA descriptor hint or a clock mux selector).
- One human maintainer data point; keep as draft.

Confidence: low
Last updated: 2026-05-30

### MEM-0279: New board DTS with custom GPIO-key or button GPIOs must include pinctrl states

Status: draft
Scope: file-pattern:arch/arm/boot/dts/qcom/*.dts file-pattern:arch/arm64/boot/dts/qcom/*.dts
Triggers:
- A new board DTS introduces one or more `gpio-keys` button nodes or other
  board-specific GPIO-driven peripherals (camera focus, power, volume keys, etc.)
- The DTS does not include `pinctrl-0` / `pinctrl-names` configuration for those GPIOs
- The base DTSI for the SoC does not already configure pin multiplexing, drive
  strength, or bias for those specific GPIO numbers

Maintainer evidence:
- Sashiko-bot on patch 2/2 "ARM: dts: qcom: msm8926-sony-xperia-yukon-eagle: add
  initial device tree" (20260527-yukon-eagle-v1-0, 2026-05-27): "[Medium] Board-specific
  GPIOs lack explicit pin control configurations. Relying on the bootloader for pin
  multiplexing, drive strengths, and bias resistors can leave pins in an undefined state
  and might cause issues after resuming from suspend."
  Our automated review did not flag missing pinctrl states for the gpio-keys nodes
  (missed-by-us). AI-reviewer data point only; treat as draft.

Review action:
- Flag [MINOR] when a new board DTS adds GPIO-driven peripherals (gpio-keys, regulator
  enable GPIOs, SIM detect, SD card-detect, etc.) without pinctrl-0 / pinctrl-names
  entries defining the pin configuration for those GPIOs.
- Note that relying on bootloader pin state is fragile across suspend/resume; the kernel
  should own pin state for all board-specific GPIOs.
- Suggest adding a pinctrl sub-node in the new DTS (or in the SoC DTSI if the config
  applies to all boards) that specifies mux, drive-strength, and bias for each GPIO.

False-positive guards:
- Do not flag if `pinctrl-0` / `pinctrl-names = "default"` already appears in the node
  or an ancestor node that covers the GPIO configuration.
- Do not flag GPIOs described in the base SoC DTSI with explicit pinctrl entries.
- Do not flag on the first board DTS for a new SoC if no pinctrl driver exists yet; the
  concern applies when a pinctrl driver is already upstream for that SoC.
- Single AI-reviewer data point; treat as draft.

Confidence: low
Last updated: 2026-05-30

### MEM-0280: `regulator-always-on` on a supply that has a functional consumer — question whether it is needed

Status: draft
Scope: file-pattern:arch/arm/boot/dts/qcom/*.dts file-pattern:arch/arm64/boot/dts/qcom/*.dts
Triggers:
- A board DTS adds `regulator-always-on` to a PM regulator node (e.g. pm8226_l6, pm8150l_l1)
- A consumer node in the same DTS references that regulator as a supply
  (e.g. `vqmmc-supply = <&pm8226_l6>`) and is a subsystem that can manage regulator state
  (MMC, USB, sensor)
- The commit body does not explain an unmodeled hardware constraint requiring always-on

Maintainer evidence:
- Sashiko-bot on patch 2/2 "ARM: dts: qcom: msm8926-sony-xperia-yukon-eagle: add
  initial device tree" (20260527-yukon-eagle-v1-0, 2026-05-27): "[Medium] Does this
  regulator need to be forced always-on? It is provided to sdhc_1 as its vqmmc-supply,
  so the MMC subsystem should be able to dynamically manage its power state. Unless there
  is an unmodeled hardware constraint, the regulator-always-on property prevents the
  consumer from managing the supply efficiently."
  Our automated review did not flag the potentially unnecessary regulator-always-on
  (missed-by-us). AI-reviewer data point only; treat as draft.

Review action:
- Flag [MINOR] when a regulator in a new board DTS carries `regulator-always-on` and that
  same regulator is the supply for a subsystem that manages its own power state (MMC
  vqmmc-supply, USB, camera, sensor).
- Ask in the review: "Is there a hardware constraint (e.g. always-on rail, shared supply
  with a non-kernel consumer) that prevents the MMC subsystem from managing this supply?
  If not, consider removing `regulator-always-on` to allow dynamic power management."
- This is a question, not a definitive bug; the always-on property may be needed for
  hardware-specific reasons not visible in the DTS alone.

False-positive guards:
- Do not flag if the commit body or DTS comment explains why the regulator must remain
  always-on (e.g., shared with a modem or WiFi SoC that expects the supply to be up).
- Do not flag regulators with no consumer node in the same DTS (always-on may be
  intentional for unlisted consumers or fixed-voltage hardware rails).
- Do not flag `regulator-boot-on` (different semantics from `regulator-always-on`).
- Single AI-reviewer data point; treat as draft.

Confidence: low
Last updated: 2026-05-30

### MEM-0281: New board DTS — `/delete-node/` + recreate reserved-memory nodes when only `reg` changes; prefer property override

Status: draft
Scope: file-pattern:arch/arm/boot/dts/qcom/*.dts file-pattern:arch/arm64/boot/dts/qcom/*.dts
Triggers:
- A new board DTS uses `/delete-node/ &<label>` to remove a reserved-memory node
  that exists in the base DTSI, then recreates the entire node with new `reg` values
  but otherwise identical or subset properties
- The base unit address of those regions is unchanged; only the size or sub-range differs

Maintainer evidence:
- Sashiko-bot on patch 2/2 "ARM: dts: qcom: msm8926-sony-xperia-yukon-eagle: add
  initial device tree" (20260527-yukon-eagle-v1-0, 2026-05-27): "[Low] Is it necessary
  to delete and recreate these reserved memory nodes? Since the base unit addresses for
  these regions don't change, we could override the reg property directly instead of
  deleting the nodes. Completely deleting the nodes risks dropping other properties
  defined in the base dtsi."
  Our automated review did not flag this pattern (missed-by-us). AI-reviewer data point only.

Review action:
- Flag [MINOR] when a board DTS uses `/delete-node/` on a reserved-memory region label
  and then re-adds a node in `reserved-memory {}` with the same or similar address, when
  only `reg` values differ from the base DTSI definition.
- A simpler override using `&<label> { reg = <...>; };` would avoid silently dropping any
  other properties (e.g. `no-map`, `reusable`, `alignment`) present in the base DTSI node.
- Note: delete+recreate is the correct approach when the node name (unit address) changes,
  since DT node overrides cannot change the name. Apply this check only when the base address
  is identical to the base DTSI.

False-positive guards:
- Do not flag when the unit address of the recreated node differs from the base DTSI
  (delete+recreate is necessary to change the node name).
- Do not flag when the commit body explains that intentional property removal is the goal
  (e.g., stripping `no-map` from a region to allow kernel mapping).
- Do not flag when the base DTSI node has no label (cannot be overridden without recreating).
- Single AI-reviewer data point; treat as draft.

Confidence: low
Last updated: 2026-05-30

### MEM-0289: Qcom variant binding — `compatible: const:` rejects multi-string fallback array; use `oneOf:` when a parent wrapper defines fallback compatibles

Status: draft
Scope: file-pattern:Documentation/devicetree/bindings/spi/qcom,*.yaml file-pattern:Documentation/devicetree/bindings/i2c/qcom,*.yaml
Triggers:
- A new Qcom SoC-specific binding uses `compatible: const: qcom,<soc>-<ip>` as its
  only compatible constraint
- A parent QUP wrapper binding (e.g. `qcom,sa8255p-geni-se-qup.yaml`) defines child
  nodes matching the same IP via `oneOf:` with both the `const:` entry and an
  `items:` fallback array (e.g. `- const: qcom,sa8797p-geni-spi` +
  `- const: qcom,sa8255p-geni-spi`)
- A downstream variant SoC legitimately supplies the two-entry fallback array as its
  compatible value

Maintainer evidence:
- Sashiko-bot on [PATCH v2 1/4] "spi: dt-bindings: describe SA8255p"
  (20260530-enable-spi-on-sa8255p-v2-0-17574601bd63@oss.qualcomm.com, 2026-05-30):
  "[Medium] The `qcom,sa8255p-geni-spi` binding strictly requires a single compatible
  string, rejecting the valid `sa8797p` fallback array." The parent
  `qcom,sa8255p-geni-se-qup.yaml` wrapper already defined the variant-plus-fallback
  `items:` block, making the child binding `const:` over-restrictive.
  Our automated review missed this incompatibility (missed-by-us).

Review action:
- When a new Qcom SoC binding uses `compatible: const:`, cross-check any parent QUP
  wrapper binding for the same IP to see if it lists a `oneOf:` or `items:` fallback
  array for variant SoCs.
- If the parent wrapper allows a multi-string fallback array, flag [CONCERN]: the
  child binding `const:` will reject valid DT nodes from variant SoCs and cause
  `dtbs_check` failures.
- Suggest replacing `const: qcom,<soc>-<ip>` with a `oneOf:` block containing both
  the standalone `const:` and the parent-declared fallback `items:` array.

False-positive guards:
- Do not flag if no parent wrapper binding exists for this IP.
- Do not flag if the parent wrapper uses only a single-entry `const:` for this IP
  (no multi-entry `items:` block is defined).
- Do not flag bindings that already use `oneOf:` or `items:` to accommodate the fallback.

Confidence: low
Last updated: 2026-05-31
