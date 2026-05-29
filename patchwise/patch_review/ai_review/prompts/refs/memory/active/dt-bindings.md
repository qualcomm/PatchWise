# Review Memory — Dt Bindings (active)

### MEM-0002: Qcom DTS node override — blank line required before status property

Status: active
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dts
Triggers:
- A DTS node override block adds a new property (e.g., pinctrl-0, clocks,
  iommu-map) immediately before `status = "okay"` with no blank line between them

Maintainer evidence:
- Konrad Dybcio nit on a lemans-evk.dts patch: "please keep a \n above
  'status'" when pinctrl-0 was placed directly before status = "okay" with no
  separating blank line (linux-arm-msm, 2026-04-30).
- Konrad Dybcio on patch 5/5 "arm64: dts: qcom: talos: enable video codec on
  Talos" (linux-arm-msm, 2026-05-21): "Let's keep an \n before 'status'" when
  iommu-map was added immediately before status = "okay" in an &venus DTSO
  override block. Second independent confirmation; applies to both DTS and DTSO.

Review action:
- Flag [NIT] when a property is added immediately before `status = "okay"` in
  a Qcom DTS or DTSO node override block with no blank line separating them.

False-positive guards:
- Do not flag if there is already a blank line before `status`.
- Do not apply outside Qcom DTS/DTSO files without further confirming evidence.

Confidence: medium
Last updated: 2026-05-26

### MEM-0222: Qcom TCSR YAML — SoC-specific compatibles with unique supply topologies must get their own binding file, not extend sm8550-tcsr.yaml

Status: active
Scope: subsystem:clk/qcom file-pattern:Documentation/devicetree/bindings/clock/qcom,*tcsr*.yaml
Triggers:
- A patch adds new Qualcomm SoC-specific TCSR compatible strings (e.g.
  `qcom,glymur-tcsr`, `qcom,mahua-tcsr`) with unique supply/required-property sets
  to the existing `qcom,sm8550-tcsr.yaml` binding via `allOf/if/then` conditionals
- The DT binding maintainer had already requested a dedicated binding file in a prior
  series version and the request was not addressed

Maintainer evidence:
- Krzysztof Kozlowski (DT bindings maintainer) on [PATCH v4 1/7]
  dt-bindings: clock: qcom,sm8550-tcsr (linux-arm-msm, 2026-05-28):
  "I don't think you implemented my last comments. You need own binding file."
  Follow-up confirmed a single combined file for Glymur and Mahua is acceptable:
  "Yes. Single file should be fine." This was a repeat of feedback from an earlier
  series version; the author did not implement it in v4. Our automated review
  accepted the allOf/if/then approach and did not flag the need for a separate file
  (missed-by-us).

Review action:
- Flag [CONCERN] when a patch extends `qcom,sm8550-tcsr.yaml` (or any existing
  Qcom TCSR binding YAML) with new SoC-specific `allOf/if/then` blocks that add
  unique supply properties required only for the new SoC family.
- Suggest creating a dedicated `qcom,glymur-tcsr.yaml` (or similar per-SoC-family
  binding file); two closely related SoCs can share a single new file if the DT
  binding maintainer agrees.
- Escalate to [CONCERN] if the DT binding maintainer had already requested this
  split in a prior series version.

False-positive guards:
- Do not flag adding a new compatible enum entry to an existing binding when no
  new supply properties or structural changes are needed (simple enum extension).
- Do not flag when the DT binding maintainer has explicitly accepted the
  allOf/if/then extension in this or a prior thread.
- Do not flag bindings that already carry complex per-compatible if/then blocks
  for multiple SoC families where split was not requested.

Confidence: high
Last updated: 2026-05-29

### MEM-0258: DT binding — per-compatible `minItems:` difference requires per-compatible item descriptions via if/then blocks

Status: active
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A patch extends an existing binding YAML by adding a new SoC compatible string
  via an `enum:` block
- The same patch also reduces or relaxes item constraints on an existing property
  (e.g. adds `minItems: 1` to a property that previously had only `maxItems: N`)
  without adding per-compatible allOf/if/then blocks that explicitly describe the
  items for each compatible

Maintainer evidence:
- Bryan O'Donoghue on patch 1/8 "dt-bindings: media: qcom: Add Shikra CAMSS
  compatible" (linux-media, 2026-05-28): questioned `minItems: 1` added to the
  `iommus:` property while extending qcom,qcm2290-camss.yaml.
  "If it uses the same binding then why does it need minItems:1? Does Shikra have
  only the one iommus entry - if so why? If not then adding minItems:1 is nothing
  to do with adding another compatible string. Either way this patch isn't right."
  Our automated review did not flag the unexplained minItems change (missed-by-us).
- Krzysztof Kozlowski (DT bindings maintainer) on the same patch (linux-media,
  2026-05-30): "No. Same feedback as before — you need to describe now the items
  if you claim that there is distinction. I already pointed this out to Qualcomm
  at least two or three times." Confirms: merely adding `minItems:` is insufficient;
  the binding must supply per-compatible item descriptions (allOf/if/then blocks
  listing what each item is for each compatible) when compatibles differ in count.
  Second independent maintainer NAK; recurring pattern for Qualcomm submissions.

Review action:
- Flag [CONCERN] when a patch adds a new SoC compatible to an existing binding
  and also changes `minItems`/`maxItems` on a property, without adding
  per-compatible allOf/if/then blocks that explicitly describe the items for
  each compatible.
- The correct fix is NOT just documenting the hardware reason in the commit body.
  The binding YAML must include per-compatible item constraints (e.g. one if/then
  block per compatible that enumerates what the N items are for that compatible).
- For `iommus:` in particular: if the new SoC uses 1 entry while an existing SoC
  uses 4, add allOf/if/then blocks for each compatible, each with a concrete
  `items:` list describing what each SID entry is.

False-positive guards:
- Do not flag when the binding already supplies per-compatible allOf/if/then
  blocks describing the items for each compatible that has a different count.
- Do not flag constraint changes where no hardware distinction exists between
  compatibles (the existing constraint already covers all listed compatibles
  correctly and no relaxation is needed).

Confidence: medium
Last updated: 2026-05-30

### MEM-0259: Qcom CAMSS DT node — IOMMU SID list must be complete and justified against sibling SoC

Status: active
Scope: subsystem:camss file-pattern:arch/arm64/boot/dts/qcom/*.dtsi
Triggers:
- A DTS/DTSI patch adds a `camss` node with an `iommus` property that lists
  fewer SIDs than a register-compatible sibling SoC (e.g. Agatti/QCM2290 lists
  multiple SIDs for VFE, CDM, OPE while the new node lists only one)
- The commit body does not explain which SIDs are intentionally excluded and why

Maintainer evidence:
- Bryan O'Donoghue on patch 4/8 "arm64: dts: qcom: shikra: Add CAMSS node"
  (linux-media, 2026-05-28): "I'm suspicious of this IOMMU. We should list the
  full range of IFE SIDs here not a subset. ... Please list in your next
  submission commit log the IOMMU SIDs — comment in the DTS is fine too. Ideally
  list the IOMMUs for Agatti/2290 and then explain why the singleton you have
  enumerated here is the only required one."
- Vikram Sharma confirmed Shikra VFE SID matches Agatti; CDM excluded as unused;
  OPE to be added separately.
- Bryan O'Donoghue follow-up (linux-media, 2026-05-29): after Vikram explained
  that Shikra and Agatti SID spaces differ architecturally ("Only VFE SID is
  same for both"), Bryan replied "five is too many for Agatti's IOMMU set" and
  requested a numbered list of SIDs for both SoCs. The concern therefore extends
  to the sibling SoC reference node itself potentially having incorrect entries.
  Our automated review did not flag the singleton IOMMU entry (missed-by-us).

Review action:
- Flag [CONCERN] when a new Qcom CAMSS DTS node lists fewer `iommus` entries
  than the register-compatible sibling SoC node, and the commit body or DTS
  comments do not enumerate the SID values and explain each exclusion.
- Suggest adding inline DTS comments listing the SID values and justifying
  absent entries (e.g. "CDM SID excluded — not used; OPE SID to be added separately").
- When the author claims the SID spaces differ architecturally between SoCs,
  flag that both nodes need numbered SID documentation — the concern is mutual,
  not resolved by pointing to different SID spaces.
- Cross-reference the Agatti or QCM2290 CAMSS node iommus list for the expected
  full range.

False-positive guards:
- Do not flag if the commit body or DTS comments already enumerate the SID
  assignments and justify the reduced set with numbered SID values.
- Do not treat an author claim of "different SID spaces" as resolving the concern;
  architectural SID differences still require explicit per-node SID documentation.
- Do not flag if the sibling SoC node was itself confirmed incorrect by the same
  reviewer thread — in that case flag both nodes, not just the new one.
- Do not apply outside Qcom CAMSS DTS nodes without additional confirming evidence.

Confidence: medium
Last updated: 2026-05-30

### MEM-0261: Sensor DTS node — absent regulators require inline comment explaining supply source

Status: active
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dtso
Triggers:
- A sensor device node (camera, IMU, etc.) in a DTS/DTSO lists only a subset
  of the supply regulators expected for that sensor (e.g. only `dovdd-supply`
  while `avdd-supply` and `dvdd-supply` are absent)
- The commit body does not explain whether absent supplies are fixed-voltage,
  board-supplied, or provided by a daughter board

Maintainer evidence:
- Bryan O'Donoghue on patches 7/8 and 8/8 of the Shikra CAMSS series
  (linux-arm-msm, 2026-05-28): "I don't have your schematic BUT where are the
  rest of the regulators. If they are absent or powered by the daughter board,
  a comment in the patch would be warranted."
- Nihal Kumar Gupta (author, 2026-05-29) agreed on patch 8/8 and provided the
  example comment text: "/* avdd and dvdd are supplied by on-board regulators on
  the IMX577 module from the connector's 3.3 V rail; they are not SoC-controlled.
  dovdd is the only supply sourced from the SoC PMIC. */"
  Our automated review did not flag absent regulators without a comment
  (missed-by-us).

Review action:
- Flag [MINOR] when a sensor device node lists fewer supply properties than
  similar in-tree sensor nodes of the same type, and neither the commit body
  nor the DTS carries a comment explaining the absent supplies.
- Suggest an inline DTS comment above the sensor node, e.g.:
  `/* avdd and dvdd are supplied by fixed on-board regulators on the sensor
     module; they are not SoC-controlled. Only dovdd is PMIC-sourced. */`
- The author's v2 of patch 8/8 included exactly this style of comment.

False-positive guards:
- Do not flag if the sensor's binding schema marks the absent supply as optional
  and the commit body confirms the supply is not used on this board.
- Do not flag if the commit body or DTS already explains the supply topology
  (e.g. "avdd and dvdd are always-on on the camera module").

Confidence: medium
Last updated: 2026-05-30
