# Review Memory — Dt Bindings (deprecated)

### MEM-0241: DT binding `if:` condition must use `contains:` not `properties:` for array-valued `compatible`

Status: deprecated
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A YAML binding `allOf/if:` block tests the `compatible` property using
  `properties: compatible: enum: [value]` (direct enum match)
- The DT spec allows `compatible` to be an array of strings; a direct `enum`
  match fails when the node has more than one compatible string because
  jsonschema enum matching requires the full value to match, not just one element
- The effect is that the `if:` condition always evaluates to false for real DTS
  nodes that carry two compatible strings, causing the `else:` branch to apply
  unconditionally

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 1/5 of iris purwa
  series (20260529-enable_iris_on_purwa-v8-0-b1b9670459ab@oss.qualcomm.com):
  flagged [Medium] that the `if: properties: compatible: enum: [qcom,x1p42100-iris]`
  condition causes the else branch (maxItems: 3) to apply to qcom,x1p42100-iris
  nodes, preventing validation of the required 4-clock layout.
  Suggested using `contains: enum:` or `contains: const:` instead of a direct enum.
  Series did not apply cleanly so our automated review was skipped (missed-by-us).
  Single AI-reviewer data point; duplicate of MEM-0227, which covers the same
  pattern with an identical data point. Deprecated to avoid confusion.

Review action:
- Use MEM-0227 instead.

False-positive guards:
- See MEM-0227.

Confidence: low
Last updated: 2026-05-31

### MEM-0242: DT binding conditional `then:` with `minItems` without `required:` silently passes absent properties

Status: deprecated
Scope: file-pattern:Documentation/devicetree/bindings/
Triggers:
- A YAML binding `allOf/if/then:` block adds `minItems` (or `maxItems`) constraints
  for a property that is mandatory for the matched compatible
- The `then:` block does not also include a `required:` list for that property
- The property could be entirely absent from a DTS node and still pass validation,
  because `minItems` only applies if the property is present

Maintainer evidence:
- Sashiko-bot (sashiko-bot@kernel.org, 2026-05-29) on patch 1/5 of iris purwa
  series (20260529-enable_iris_on_purwa-v8-0-b1b9670459ab@oss.qualcomm.com):
  flagged [Medium] that `then: properties: clocks: minItems: 4` without a
  `required: [clocks, clock-names]` entry in the same `then:` block allows a DTS
  node for `qcom,x1p42100-iris` to omit the clocks property entirely and still
  pass schema validation, even though the fourth BSE clock is mandatory for the
  platform to operate.
  Duplicate of MEM-0228, which covers the same pattern and adds a second data point
  (Shikra dispcc). Deprecated to avoid confusion.

Review action:
- Use MEM-0228 instead.

False-positive guards:
- See MEM-0228.

Confidence: low
Last updated: 2026-05-31

### MEM-0262: Qcom CAMSS binding — CSIPHY must be described as distinct sub-nodes, not monolithic registers in the CAMSS parent

Status: deprecated
Scope: subsystem:camss file-pattern:Documentation/devicetree/bindings/media/qcom,*camss*.yaml
Triggers:
- A new Qcom CAMSS DT binding YAML describes CSIPHY register ranges as entries
  in the parent CAMSS node's `reg`/`reg-names` list

Maintainer evidence:
- Bryan O'Donoghue (linux-media, 2026-05-29) on patch 1/6 "dt-bindings: media:
  Add bindings for qcom,glymur-camss": NAK; CSIPHY sub-node refactor is a
  prerequisite. Duplicate of MEM-0286 (active), which consolidates all CAMSS
  CSIPHY sub-node evidence including both supply-topology and reg-names variants.

Review action:
- Use MEM-0286 instead.

False-positive guards:
- See MEM-0286.

Confidence: medium
Last updated: 2026-05-31

### MEM-0284: Qcom CAMSS DT binding — CSIPHY must be a distinct sub-node; flat embedded-CSIPHY topology is blocked

Status: deprecated
Scope: subsystem:camss file-pattern:Documentation/devicetree/bindings/media/qcom,*camss*.yaml
Triggers:
- A new Qcom CAMSS DT binding YAML describes CSIPHY hardware inline in the main
  camss node (csiphy* in reg-names/interrupt-names; vdd-csiphy-*-supply as
  camss-level properties) following the pre-existing flat topology

Maintainer evidence:
- Bryan O'Donoghue + Krzysztof Kozlowski (linux-media, 2026-05-29/30) NAK'd the
  glymur-camss series and dropped all CAMSS patches from Patchwork on the same
  architectural grounds. Duplicate of MEM-0286 (active), which consolidates the
  complete evidence including the supply-topology variant.
  Message-ID: 20260529-glymur_camss-v1-0-bee535396d22@oss.qualcomm.com

Review action:
- Use MEM-0286 instead.

False-positive guards:
- See MEM-0286.

Confidence: low
Last updated: 2026-05-31

### MEM-0285: DTS overlay filename must enumerate all covered board variants when shared across multiple boards

Status: deprecated
Scope: file-pattern:arch/arm64/boot/dts/qcom/*.dtso
Triggers:
- A DTS overlay (.dtso) file is shared by two or more board variants and the
  filename identifies only one variant

Maintainer evidence:
- Bryan O'Donoghue (linux-arm-msm, 2026-05-28/29) nit on shikra-cqm-evk-imx577-camera;
  agreed the filename should enumerate all covered boards.
  Duplicate of MEM-0260 (draft), which covers the same thread and same resolution
  in greater detail.

Review action:
- Use MEM-0260 instead.

False-positive guards:
- See MEM-0260.

Confidence: low
Last updated: 2026-05-31
