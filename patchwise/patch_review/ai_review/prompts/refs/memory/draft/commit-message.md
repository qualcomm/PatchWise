# Review Memory — Commit Message (draft)

### MEM-0005: Commit message must explain removal of named kernel element

Status: draft
Scope: general
Triggers:
- A patch removes a named capability, enum value, struct field, or platform
  configuration entry
- The commit subject/body describes only what is being added or changed,
  without explaining why the removed element is no longer needed or what
  supersedes it

Maintainer evidence:
- Dikshita Agarwal on patch 1/2 of 20260420-dynamic_encode-v1 (iris encoder):
  "Its not clear what is being done in this change, you are removing one cap,
  without explaining why." The patch removed the INTRA_PERIOD cap from
  iris_platform_gen1.c while the subject said only "Add gop size support";
  no body sentence justified the removal.

Review action:
- Flag [MINOR] when a patch removes a named element and the commit body
  contains no sentence explaining the rationale (e.g. "consolidated into",
  "superseded by", "no longer needed because", "replaced by").
- Suggest adding a one-sentence explanation in the commit body.
- This check applies even when the patch cannot be applied cleanly: the
  commit message text is still reviewable from the mbox or patch file.

False-positive guards:
- Do not flag if the commit body or cover letter clearly explains the
  removal rationale, even briefly.
- Do not flag for trivially dead code (e.g. a symbol introduced and removed
  in the same series, or a TODO/fixme-remove marker).
- Do not flag if the series cover letter provides sufficient context about
  why the element is removed as part of a larger refactor.

Confidence: low
Last updated: 2026-05-26

### MEM-0007: Lowercase "platform" as common noun in commit subjects

Status: draft
Scope: general
Triggers:
- A commit subject contains "Platform" with a capital P used as a common noun
  (e.g., "Add IPCC support for Maili Platform")
- The capitalised word is not part of an official product/SoC name that is
  always written with a capital P

Maintainer evidence:
- Patchwise AI review (2026-05-11) on "dt-bindings: mailbox: qcom: Add IPCC
  support for Maili Platform": "The word 'Platform' in the subject line should
  be lowercase ('platform'), as platform names in Linux Kernel commit subjects
  are not typically title-cased beyond the proper noun itself."

Review action:
- Flag [NIT] when a commit subject contains "Platform" (capital P) where
  "platform" is used as a common noun describing the SoC environment, not as
  an intrinsic part of the SoC's official name.
- Suggest replacing with lowercase "platform".

False-positive guards:
- Do not flag if "Platform" is part of the SoC vendor's official capitalization
  (e.g., a product whose registered name contains "Platform").
- Do not flag proper nouns that happen to end with "Platform" as a distinct
  brand element.

Confidence: low
Last updated: 2026-05-26

### MEM-0021: Use "shall" not "should" when quoting PCIe spec normative requirements in commit messages

Status: draft
Scope: subsystem:pci
Triggers:
- A commit body quotes or paraphrases behavior mandated by the PCIe specification
- The text uses "should" where the spec uses "shall" (normative requirement)

Maintainer evidence:
- Manivannan Sadhasivam on patch 2/2 "PCI: Add support for PCIe WAKE# interrupt" (linux-pci, 2026-04-29): requested s/should/shall for a sentence describing PCIe spec-mandated WAKE# endpoint configuration, where "shall" is the spec's normative word for required behavior.

Review action:
- Flag [NIT] when a commit body uses "should" to describe PCIe spec-mandated (normative) behavior.
- Suggest replacing "should" with "shall" when the sentence describes a SHALL-level requirement from the PCIe specification.

False-positive guards:
- Do not flag "should" used in informal sentences not quoting a spec requirement (e.g., "this patch should fix the issue").
- Do not flag when "should" correctly describes a SHOULD-level recommendation from the spec rather than a SHALL requirement.
- Do not apply to non-PCI subsystem patches without additional maintainer evidence.

Confidence: low
Last updated: 2026-05-26

### MEM-0032: Generic kernel export commits -- hardware-specific benchmarks belong in the cover letter; problem description must survive

Status: draft
Scope: general
Triggers:
- A patch exports a function from a core kernel subsystem (not a device driver)
- The commit body includes platform names, throughput numbers, or benchmark
  comparisons (e.g., 'On Qualcomm RB3 Gen2 ... 802 Mbps to 2.58 Gbps') as
  justification for the export
- Driver-specific use-case details (e.g., 'WLAN driver enables threaded NAPI')
  dominate the motivation over the generic API need
- OR: the commit body correctly omits hardware specifics but describes only
  what the export enables rather than what problem the unexported state causes

Maintainer evidence:
- Multiple reviewers on [PATCH v1] genirq: Export irq_can_set_affinity()
  (kernel@oss.qualcomm.com, 2026-05-07): "hardware-specific performance numbers
  (RB3 Gen2, 802 Mbps to 2.58 Gbps) are better suited for a cover letter or
  mailing list discussion than a commit message for a generic kernel export."
  Author updated commit in v2 removing platform benchmarks and driver specifics.
  Our automated review praised the original commit body as "well-written" and
  missed this -- a missed-by-us finding.
- Jeff Johnson <jeff.johnson@oss.qualcomm.com> on [PATCH v2] genirq: Export
  irq_can_set_affinity() (kernel@oss.qualcomm.com, 2026-05-08): "The most
  important thing the commit text needs to do is describe the problem, and the
  v2 commit text doesn't describe the problem nearly well enough, nor does it
  highlight how this helps fix the underlying issue." He explicitly called
  the v1 Patchwise advice (shorten the message) "NOT helpful." The v2 body
  stated only what the export enables ("modules need this check so they can
  adjust their internal policy accordingly") but did not describe what fails
  without the export. Our automated review gave v2 a positive note on commit
  message quality and did not catch the weak problem description -- missed-by-us.

Review action:
- Flag [MINOR] when a commit exporting a core kernel function includes
  hardware-specific performance benchmarks, platform names, or driver-internal
  policy details that only make sense for one consumer.
- Suggest moving platform-specific context to the cover letter or mailing list
  discussion; the commit body should state the generic API motivation (the need
  to call the function from modules, not one driver's throughput gain).
- Driver-specific context (e.g., what a WLAN driver does with the exported
  symbol) belongs in the driver's own commit message, not the infrastructure
  commit.
- After confirming hardware specifics are absent, also check that the commit
  body describes the concrete problem the unexported state causes -- what modules
  currently fail to do -- not just what the export enables. A body that says only
  "modules need this check so they can adjust policy accordingly" is too vague;
  it should name the failure mode (e.g. "without this export, loadable modules
  cannot determine at runtime whether IRQ affinity is supported and must use a
  conservative fallback policy on all platforms").

False-positive guards:
- Do not flag driver commits -- hardware benchmarks and platform context are
  appropriate in driver commit bodies.
- Do not flag if the hardware mention is brief (one clause) and serves as a
  motivating example without dominating the commit body.
- Do not flag when the patch is a driver + infrastructure combined change where
  the hardware context is inseparable from the motivation.
- Do not flag if the body already names a concrete failure mode or module type
  that cannot function correctly without the export.

Confidence: low
Last updated: 2026-05-26

### MEM-0038: `Fixes:` tag should point to the commit that introduced the specific bug, not a later reorganization

Status: draft
Scope: general
Triggers:
- A patch carries a `Fixes:` tag
- The tagged commit subject uses reorganization language ("Move", "Rename", "Refactor",
  "Restructure") rather than describing the original introduction of the code path
- An older commit specifically introduced the function call or code construct being fixed

Maintainer evidence:
- Leo Yan (ARM/Coresight reviewer) on "coresight: fix source not disabled on idr_alloc_u32
  failure" (linux-arm-kernel, 2026-05-11): corrected `Fixes: 1f5149c7751c` ("coresight:
  Move all sysfs code to sysfs file") to `Fixes: 5c0016d7b343` ("coresight: core: Use IDR
  for non-cpu bound sources' paths.") -- the commit that introduced idr_alloc_u32() for
  non-CPU sources and thus introduced the bug. Our review accepted the original tag without
  checking that the tagged commit introduced the buggy construct (missed-by-us).

Review action:
- When a `Fixes:` tag subject contains reorganization language, verify the tagged commit
  actually introduced the buggy code construct, not just relocated it.
- Flag [MINOR] and suggest `git log -S <identifier>` to find the commit that first
  introduced the specific function call or code path being fixed.

False-positive guards:
- Do not flag if the reorganization commit changed the logic and thereby introduced the bug
  (as opposed to merely moving pre-existing code).
- Do not flag if the bug is inherent to the reorganization itself.
- Use [MINOR], not [CONCERN] or [BUG].

Confidence: low
Last updated: 2026-05-26

### MEM-0040: Bug-fix patches missing a `Fixes:` tag — flag [MINOR]

Status: draft
Scope: general
Triggers:
- A patch fixes a memory-safety defect (use-after-free, null-deref, memory leak)
  or other clearly identifiable regression
- The commit message contains no `Fixes:` tag identifying the commit that introduced
  the defect
- OR: code analysis reveals a real defect (e.g. memory leak from unbounded heap growth)
  but the commit body uses design-improvement language ("unsafe design", "allocate
  upfront") rather than defect-description language, with no `Fixes:` or `Cc: stable`

Maintainer evidence:
- Patchwise AI reviewer (kernel@oss.qualcomm.com, 2026-05-01) on "misc: fastrpc: fix
  use-after-free of cctx in fastrpc_buf_free": recommended adding a `Fixes:` tag per
  Documentation/process/submitting-patches.rst; our automated review raised the same
  [MINOR] finding independently, confirming the expectation from two sources.
- Konrad Dybcio and Manivannan Sadhasivam gave Reviewed-by for the 18-patch Qcom PCIe
  wake GPIO polarity series (linux-arm-msm, 2026-05-14) without requesting `Fixes:` tags;
  the author's cover letter stated "No Fixes tag is added as no functional issue has
  been observed." Both maintainers accepted the series as-is. Our automated review raised
  a [CONCERN] for missing Fixes:/stable — a false positive in terms of severity.
- Dmitry Baryshkov on patch 4/5 of 20260515-jianping-li-misc-fastrpc-add-missing-bug-fixes
  (linux-arm-msm, 2026-05-15): "So, is this a bugfix or not? Is it possible to make the
  kernel misbehave without this patch?" and "The tag, cc:stable, clear description as
  the bugfix? How would anybody guess if the patch is to be backported to earlier kernels?"
  The patch fixed a real memory leak (Audio PD heap never shrinks) but used design framing
  with no `Fixes:` or `Cc: stable`. Our automated review found the code defect but missed
  the missing `Fixes:` tag (missed-by-us).

Review action:
- Flag [MINOR] when a bug-fix patch omits a `Fixes:` tag.
- Suggest using `git log -S <identifier>` to locate the introducing commit, then
  adding `Fixes: <sha1> ("<subject>")`.
- Also suggest `Cc: stable@vger.kernel.org` if the bug is present in stable-maintained
  branches (see MEM-0004 for the stable-tag convention).
- When code analysis reveals a defect but the commit body uses design-rationale language,
  also check for missing `Fixes:` and `Cc: stable` and flag [MINOR] if absent.

False-positive guards:
- Do not flag if a `Fixes:` tag is already present.
- Do not flag if the defect is a design flaw with no single identifiable introducing
  commit.
- Do not flag if the fix was introduced in the current merge window and is not present
  in any stable-maintained branch.
- Do not raise above [MINOR]; never use [CONCERN] or [BUG] solely for a missing
  `Fixes:` tag.
- Do not flag (or flag at most [NIT]) when the cover letter or commit body explicitly
  states the fix is a spec-compliance correction with no observed functional failure.
  Qcom DTS maintainers (Konrad Dybcio, Manivannan Sadhasivam) accept polarity/spec
  corrections without Fixes: tags when no functional regression was reported.

Confidence: low
Last updated: 2026-05-26

### MEM-0073: DTS idle state removal — commit body must explain specific cpuidle/governor context, not just vague performance claim

Status: draft
Scope: subsystem:arm/qcom file-pattern:arch/arm64/boot/dts/
Triggers:
- A patch removes a firmware-supported PSCI idle state (domain-idle-states node) from a
  DTS/DTSI file
- The commit body justifies the removal only as "not utilized in favor of performance" or
  similar vague language without citing the specific cpuidle governor behavior, scheduling
  issue, or regression that makes the state impractical

Maintainer evidence:
- Konrad Dybcio on [PATCH 0/2] Remove gold/silver_cpu_sleep idle states for lemans and
  monaco (linux-arm-msm, 2026-05-14): "Is this a sign that the idle scheduler should get
  some attention instead?" — challenging the vague justification and asking whether fixing
  the scheduler root cause is the right approach. The author supplied detailed follow-up
  citing cpuidle menu governor commit 85975daeaa4d, the Intel regression, the revert
  10fad4012234, and the observed performance recovery on LeMans/Monaco SoCs. Our automated
  review gave READY TO APPLY without flagging the vague justification (missed-by-us).

Review action:
- Flag [MINOR] when a DTS idle state removal commit body gives only a vague performance
  justification without citing: (a) the specific cpuidle governor or scheduler condition
  that makes the state impractical in practice, and (b) why fixing the governor/scheduler
  is not the preferred solution.
- Suggest the author briefly explain: "CPU power collapse is avoided because <specific
  reason, e.g., the cpuidle menu governor reverts cause it to be skipped in practice>."

False-positive guards:
- Do not flag if the commit body already cites a specific cpuidle, firmware, or scheduler
  reason (e.g., references a cpuidle commit, a governor regression, or a power/performance
  measurement result).
- Do not flag removal of states documented as unsupported or non-functional in firmware;
  the vagueness concern applies only to states confirmed to be firmware-supported.
- Do not apply outside DTS cpuidle idle state removals without additional confirming
  evidence from a human maintainer.

Confidence: low
Last updated: 2026-05-26

### MEM-0074: Use "aligning with" or "consistent with" instead of "inline with" in commit bodies

Status: draft
Scope: general
Triggers:
- A commit body or subject line uses the phrase "inline with" to describe consistency with
  another SoC, driver, or established pattern (e.g. "inline with SM8350/SM8450/SM8550/SM8650")

Maintainer evidence:
- Patchwise AI reviewer (kernel@oss.qualcomm.com, 2026-05-16) on patch 1/2 "arm64: dts:
  qcom: lemans: Remove the gold_cpu_sleep idle state": "'inline with' is informal; prefer
  'aligning with' or 'consistent with' for a more professional tone." The same substitution
  was applied in the rewritten patch 2/2 commit text. Two instances in one review session.

Review action:
- Flag [NIT] when a commit body uses "inline with" as an informal synonym for "consistent
  with" or "aligning with."
- Suggest replacing "inline with X" with "aligning with X" or "consistent with X."

False-positive guards:
- Do not flag "inline" used in a technical sense (inline function, inline assembly, or
  describing literal placement of code in the same compilation unit).
- Evidence is from an AI reviewer only (no human maintainer confirmation); treat as draft
  and apply only as a [NIT] until a human maintainer echoes the preference.

Confidence: low
Last updated: 2026-05-26

### MEM-0079: Large complexity-adding series must state concrete technical benefits in cover letter

Status: draft
Scope: general
Triggers:
- A series adds 500+ lines to existing in-tree drivers without adding obvious new
  device support
- The cover letter motivates the complexity increase with abstract design language
  only ("scalable mechanism", "clean design", "standardized framework") without
  naming: (a) new hardware/firmware features that require the change and cannot be
  supported by the existing code, (b) the first platform where the change is needed,
  or (c) concrete future benefits (e.g. transport portability)

Maintainer evidence:
- Konrad Dybcio on [PATCH 0/5] Add GIO interface and update clients
  (20260316-pmic-glink-gio-clients-v1, linux-arm-msm, 2026-03-16):
  "This doesn't really address anything, other than making our existing drivers
  more complex ... Because this diffstat is tough to swallow if there's no real
  benefit." After the author (Fenglin Wu) explained that GIO is transport-agnostic,
  is the primary interface on Glymur, and exposes new firmware features not
  accessible via the legacy protocol, Konrad accepted: "That is much better
  reasoning, please summarize some of those points in the commit log."
  Our automated review did not flag the thin motivation in the cover letter
  (missed-by-us).

Review action:
- Flag [CONCERN] at the series or cover-letter level when a large infrastructure
  series (500+ lines added to existing drivers) justifies the complexity increase
  only with abstract design claims.
- Ask: what concrete new capability does this enable that the existing code cannot
  provide? Name specific firmware features, platforms, or transport constraints that
  make the new approach necessary.
- Suggest adding one paragraph: "The existing approach cannot X because Y; the new
  approach is first needed on <platform> because Z."

False-positive guards:
- Do not flag when the cover letter already names concrete new capabilities gated on
  the new code (new firmware features, future transports, specific platform requirement).
- Do not flag series that are primarily bug fixes, test additions, or refactors
  explicitly linked to a stated correctness or performance problem.
- Do not flag series adding new device support (e.g. new SoC DTS) where necessity
  is self-evident from the device name.
- Do not flag if a maintainer in the same thread has already acknowledged the
  motivation is sufficient.

Confidence: low
Last updated: 2026-05-26

### MEM-0080: Unexplained vendor-internal chip abbreviations in commit bodies --- flag [NIT]

Status: draft
Scope: general
Triggers:
- A commit body references a chip, SoC, or hardware module by a short abbreviation
  (e.g. "HMT chip") that is not a publicly documented product name and is not
  spelled out anywhere in the commit message, driver file comments, or Documentation/

Maintainer evidence:
- Dmitry Baryshkov on [PATCH v2] Bluetooth: hci_qca: Use 100 ms SSR delay for
  rampatch and NVM loading (linux-bluetooth, 2026-05-25):
  "What is HMT? Don't use abbreviations which are not known outside of your
  company." The commit body mentioned "HMT chip" without expansion. Our
  automated review praised the message as a model bug-fix commit message and
  used the abbreviation itself in hardware analysis without flagging it
  (missed-by-us).

Review action:
- Flag [NIT] when a commit body uses a chip nickname or abbreviation that cannot
  be resolved from the commit itself, the driver Kconfig help text, or a
  publicly reachable product page.
- Suggest spelling out the full name on first use with the abbreviation in
  parentheses, or replacing with the public SoC name (e.g. the qcom compatible
  string family name).

False-positive guards:
- Do not flag universally understood kernel abbreviations (SoC, UART, SPI,
  PCIe, USB, SSR, NVM, BLE, etc.).
- Do not flag abbreviations already expanded in the driver file's module
  description, Kconfig help, or an earlier commit in the same series.
- Do not flag chip names that appear verbatim in Documentation/ or as part of
  the DT compatible string (e.g. "qcom,sm8650").
- One data point only; treat as draft and apply only as [NIT].

Confidence: low
Last updated: 2026-05-26

### MEM-0085: Tracepoint/instrumentation series commit bodies must state the observability motivation

Status: draft
Scope: general
Triggers:
- A patch adds tracepoints, trace events, or other kernel instrumentation
  (ftrace, perf, eBPF attachment points) to an execution path
- The commit body describes only the mechanical wiring (e.g. "wire the tracepoints
  into the execution path by including the header with CREATE_TRACE_POINTS") without
  explaining what problem the instrumentation solves or what observable benefit it
  provides

Maintainer evidence:
- Patchwise AI reviewer (quic_kernel@qualcomm.com, 2026-05-06) on patch 2/2
  "firmware: qcom: scm: instrument SMC call path with tracepoints" v1: "it lacks
  context about why these tracepoints are useful -- there is no explanation of
  what problem they solve or what observability benefit they provide." The commit
  body stated only the mechanical action; no debugging scenario, latency concern,
  or correctness issue was named. Our automated review gave READY TO APPLY without
  flagging the missing motivation (missed-by-us).
- Patchwise AI reviewer (kernel@oss.qualcomm.com, 2026-05-26) on patch 2/2
  "firmware: qcom: scm: instrument SMC call path with tracepoints" v2
  (20260522-scm-tracepoints-v2-0-e27cdbe0c585@oss.qualcomm.com): same finding
  on resubmitted series — commit body stated only the mechanical wiring action
  with no explanation of the observability benefit. Suggested leading with "SCM
  calls enter secure firmware and can block, retry, or sleep on wait queues,
  making failures and latency difficult to diagnose from the kernel." Our
  automated v2 review gave READY TO APPLY without flagging (missed-by-us again).

Review action:
- Flag [NIT] when a tracepoint-addition commit body describes only what is wired or
  added (the how) with no sentence explaining why (the concrete debugging scenario,
  latency problem, or correctness concern that motivated the instrumentation).
- Suggest adding one sentence such as: "This enables runtime observation of <component>
  via ftrace/perf, aiding diagnosis of <specific issue type, e.g. SMC call latency,
  wait-queue retry storms, or call-path correctness>."

False-positive guards:
- Do not flag if the cover letter or a companion patch in the same series already
  explains the observability motivation.
- Do not flag if the commit body already names a concrete debugging scenario or
  performance problem the tracepoints address.
- Two AI-reviewer data points (same reviewer, two series versions); apply as [NIT]
  and treat as draft until a human maintainer echoes this expectation.

Confidence: low
Last updated: 2026-05-27

### MEM-0089: GENMASK bit-field expansion with no current in-tree consumer — commit message must state preparatory intent and ABI safety

Status: draft
Scope: general
Triggers:
- A patch expands a GENMASK() bit-field macro to enable larger encoded values
- No current in-tree code path exercises the newly expanded range
- The macro feeds into a firmware/ABI-facing context (e.g. constructing a PAS ID,
  an SCM peripheral authentication field, or a protocol command field)
- The preparatory statement is present but uses speculative hedging ("may require",
  "might be needed") when the platform requirement is already known

Maintainer evidence:
- Jeff Johnson (ath12k maintainer, 2026-05-21) on "wifi: ath12k: expand UserPD
  ID mask to support up to 8 PDs" (GENMASK(9,8) to GENMASK(10,8), no current
  in-tree path uses IDs > 3): "perhaps the commit text should be updated to say
  this is in support of multi-UserPD support which will come in the future" and
  asked for an explanation of why the expansion is safe, noting "GENMASK() is
  often used when defining fields in ABIs." Author agreed to update the commit
  message in the next version. Our automated review gave READY TO APPLY with
  0 findings (missed-by-us).
- Patchwise AI reviewer (2026-05-26) on v7 of the same patch ("Some future
  IPQ5332 multi-PD platform variants may require more than three UserPDs"):
  "avoid speculative wording such as 'may require' if the platform requirement is
  already known" — suggested replacing with "need to support" or "will need",
  and rewriting the body to lead with a clear problem statement. Our automated
  review again missed this nuance (missed-by-us).

Review action:
- Flag [MINOR] when a GENMASK() bit-field expansion has no current in-tree
  consumer exercising the new range AND the commit message does not both:
  (1) explicitly state the change is preparatory for future patches/platforms, and
  (2) explain why the expansion is safe in any firmware/ABI-facing context (e.g.
  confirm no bit-overlap with adjacent fields in the same compound identifier).
- Suggest adding: (a) one sentence naming the future feature or platform, and
  (b) a brief bit-overlap proof or code comment confirming ABI safety.
- If a preparatory statement is present but uses "may require" or "might be needed",
  flag [NIT] and suggest factual language: "need" (if the requirement is already
  determined for a specific platform) or "will need" (if future support is planned
  but not yet confirmed). Reserve "may require" only for genuinely uncertain
  requirements.

False-positive guards:
- Do not flag if the commit body already states the expansion is preparatory and
  explains ABI safety, even briefly.
- Do not flag if a later patch in the same series immediately exercises the
  expanded range; the in-tree consumer provides the justification.
- Do not flag if the macro has no firmware/ABI consumers and no ABI overlap
  analysis is needed.
- Do not flag if the maintainer has already accepted the commit message as-is.
- Do not upgrade "may require" to [MINOR] on the speculative-wording point alone;
  use [NIT] for wording precision and reserve [MINOR] for the absent preparatory
  statement or missing ABI-safety explanation.

Confidence: low
Last updated: 2026-05-27

### MEM-0093: Commit subject -- "Enable X support" implies toggling existing feature; use "Add X support" for new hardware

Status: draft
Scope: general
Triggers:
- A commit subject uses the verb "Enable" for a patch that introduces a new
  hardware compatible entry, adds a new SoC to a driver match table, or
  brings up a PHY or bus for the first time
- No prior driver infrastructure for the new hardware existed before this
  patch (i.e., nothing is being toggled on; support is being introduced
  from scratch)

Maintainer evidence:
- Patchwise AI review (2026-05-16) on patch 4/5 "phy: qcom: qmp: Enable
  ipq5210 support": "The subject line verb Enable was changed to Add to
  better reflect that new support is being introduced rather than toggling
  an existing feature on." The rewritten subject was "Add QMP USB3 PHY
  support for ipq5210".

Review action:
- Flag [NIT] when a commit subject uses "Enable <hardware/feature> support"
  for a patch that adds a new compatible string or device entry without any
  pre-existing disabled or conditional code path to enable.
- Suggest replacing "Enable" with "Add": e.g., "Add QMP USB3 PHY support
  for ipq5210" instead of "Enable ipq5210 support".

False-positive guards:
- Do not flag if the patch genuinely enables an existing but disabled code
  path (e.g., re-enables a feature gated by a Kconfig option, or enables
  a previously status-disabled DTS node).
- Do not flag "Enable" used in a technical context that is not about new
  hardware introduction (e.g., "Enable MSI-X", "Enable clock gating").
- Single AI-reviewer data point; apply as [NIT] only.

Confidence: low
Last updated: 2026-05-26

### MEM-0145: Race-condition fix commit message must describe intermittent failure, not overstate as unconditional

Status: draft
Scope: general
Triggers:
- A commit body states "without X, the hardware is unreachable" or
  "without X, probe fails" for a resource that was absent from in-tree code
  since a prior accepted commit
- The hardware was observed working before this patch (evidenced by in-tree
  users since a prior commit date or confirmed by a maintainer)
- The actual failure mode is a race condition or corner case (e.g., a
  sleep/wakeup ordering window), not a constant failure on every access

Maintainer evidence:
- Konrad Dybcio on "arm64: dts: qcom: sc7280: Add gem_noc interconnect to
  adreno_smmu" (linux-arm-msm, 2026-05-12): "This paragraph suggests that
  since commit 96c471970b7b from 2021, the GPU SMMU was not working. I can
  attest to that not being the case." The commit body said "Without voting on
  this path the SMMU is unreachable, leading to probe failures." In reality,
  the failure is a sleep/wakeup race where GEM_NOC vote can be removed before
  adreno_smmu is powered down. Konrad requested the race condition backstory be
  folded into the commit message. Our review had a [MINOR] about patch ordering
  but missed the overstatement -- a missed-by-us finding.

Review action:
- Flag [MINOR] when a commit body uses unconditional failure language ("X is
  unreachable without Y", "probe fails without Y") for a hardware resource
  whose absence caused only intermittent or corner-case failures.
- Cross-reference: if the hardware was added to the tree without the described
  resource and remained working for a significant period, absolute language is
  an overstatement.
- Suggest rephrasing to describe the specific corner case: "Under certain
  conditions (e.g., sleep/wakeup transitions), Y may be accessed without an
  active X vote, causing intermittent failures."

False-positive guards:
- Do not flag if the hardware has genuinely never been working without the
  resource in any known configuration.
- Do not flag if a Fixes: tag points to a commit that explicitly removed the
  resource, confirming it was intentionally present before and then removed.
- Do not flag when the hardware was only recently added to the tree and no
  operational history exists to contradict the unconditional claim.
- Use [MINOR], not [CONCERN] or [BUG].

Confidence: low
Last updated: 2026-05-26

### MEM-0148: Commit body copy-pasted from sibling patch — wrong driver or subsystem name silently present

Status: draft
Scope: general
Triggers:
- A multi-patch series has two or more patches that make similar changes to different drivers
  or subsystems
- The commit body of one patch names the wrong driver (e.g. "The mhi_net driver..." in a patch
  that only modifies net/qrtr/mhi.c)
- The copied body was not updated to reflect the actual file/driver modified

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-06) on patch 4/6 of the MHI runtime
  PM series: "The body says 'The mhi_net driver...' but this patch modifies net/qrtr/mhi.c
  (the QRTR MHI transport driver). Factually incorrect, will confuse reviewers." Our automated
  review caught this as [MINOR], confirming from two sources.

Review action:
- Flag [MINOR] when a commit body names a driver or subsystem that does not match any file
  modified by the patch (check the diff --stat header).
- Suggest updating the commit body to name the actual driver or file being changed, and verify
  the problem description is accurate for that driver.

False-positive guards:
- Do not flag when the commit body names a driver that calls into the modified subsystem and the
  description is logically correct (e.g., "This affects the foo driver which uses the bar API"
  when the patch modifies bar).
- Do not flag if the driver name mismatch is only in the subject line tag (e.g. net: vs net:
  wwan:); body content mismatch is the key concern.

Confidence: low
Last updated: 2026-05-26

### MEM-0159: Changing an initcall level must update the function's timing-rationale comment

Status: draft
Scope: general
Triggers:
- A patch changes the initcall level of a function (e.g. subsys_initcall to
  pure_initcall, or pure_initcall to core_initcall)
- The function has a preceding comment explaining why the original timing was
  chosen, and that comment now refers to the old context or reason

Maintainer evidence:
- Petr Pavlu on patch 2/4 of 20260518-acpi_mod_name-v5 (kernel: param:
  initialize module_kset in a pure_initcall): param_sysfs_init() was moved
  from subsys_initcall to pure_initcall, but the existing comment still said
  "This must be done before the initramfs is unpacked and request_module()
  thus becomes possible." Petr requested updating it to reflect the new
  reason: must be done before any driver registration so the driver core can
  add built-in modules under /sys/module. Author acknowledged and committed
  to updating the comment in the next revision.

Review action:
- Flag [MINOR] when a patch changes an initcall level without updating any
  existing comment that documents the original timing rationale.
- Suggest wording that explains why the new, earlier (or later) level is
  required and what constraint the new level satisfies.

False-positive guards:
- Do not flag if the function has no preceding comment about init timing.
- Do not flag if the patch already updates the comment as part of the diff.

Confidence: low
Last updated: 2026-05-26

### MEM-0175: New SoC driver descriptor limiting a shared config parameter — commit body must explain hardware reason for the limit

Status: draft
Scope: general
Triggers:
- A driver patch introduces a new SoC-specific device descriptor or configuration
  struct that reduces (limits or caps) a shared configuration parameter (e.g. LUT
  entry count, table size, buffer depth) relative to the existing generic descriptor
- The commit body states the numerical limit (e.g. "supports only N entries") but
  does not explain the hardware or architectural reason why the limit exists for
  this SoC

Maintainer evidence:
- Konrad Dybcio on patch 2/3 "interconnect: qcom: Add EPSS L3 scaling support for
  Shikra SoC" (linux-arm-msm, 2026-05-21): "Please emphasize in the commit message
  why that limiting is necessary." The commit body stated "EPSS on Shikra SoC supports
  only twelve frequency lookup entries (LUT)" without explaining the hardware reason
  (e.g. the physical count of programmable LUT slots in the EPSS block on this SoC).
  Our automated review did not flag the incomplete motivation (missed-by-us).

Review action:
- Flag [MINOR] when a driver commit adds a new SoC-specific descriptor that caps a
  shared configuration parameter and the commit body states the limit without explaining
  the hardware reason for it.
- Suggest adding a sentence such as: "The <SoC> <IP block> has only N hardware LUT
  slots, so only N entries can be programmed into the lookup table."

False-positive guards:
- Do not flag if the commit body already explains the hardware-architectural reason for
  the limit (e.g. references the SoC TRM section, notes a hardware register count, or
  compares against the parent IP block specification).
- Do not flag if the limit is purely software-imposed (e.g. a memory or performance cap)
  and the commit body explains that.
- Do not raise above [MINOR]; the functional change is correct, only the explanation is
  incomplete.

Confidence: low
Last updated: 2026-05-26

### MEM-0183: `Co-authored-by:` (GitHub convention) is non-standard --- use `Co-developed-by:` + matching `Signed-off-by:`

Status: draft
Scope: general
Triggers:
- A commit trailer uses `Co-authored-by: Name <email>` (GitHub-style co-authorship tag)
- The tag is not the standard Linux kernel co-authorship trailer

Maintainer evidence:
- checkpatch --strict flags `Co-authored-by:` as "WARNING: Non-standard signature"
  per Documentation/process/submitting-patches.rst; confirmed on patch 1/2 of
  20260526-james-cs-context-tracking-fix-v1-0 (perf cs-etm, 2026-05-26).
- Our automated review independently flagged [MINOR] on the same patch, corroborating
  the checkpatch warning from two sources.
- Arnaldo Carvalho de Melo (perf maintainer) forwarded reviewer comments including
  this issue to the author with "some looks legitimate" (2026-05-29), giving partial
  human endorsement that the trailer fix is expected.

Review action:
- Flag [MINOR] when a commit trailer uses `Co-authored-by:` instead of the
  kernel-standard `Co-developed-by:`.
- Suggest replacing with `Co-developed-by: Name <email>` followed immediately by a
  matching `Signed-off-by: Name <email>` from the same person, placed before the
  submitter's own `Signed-off-by:`.

False-positive guards:
- Do not flag `Co-developed-by:` --- the kernel-standard form.
- Do not flag `Reviewed-by:`, `Tested-by:`, `Acked-by:` --- those are separate
  standard trailer types and are correct.
- Do not flag if the subsystem maintainer has explicitly accepted `Co-authored-by:`
  in the same thread.

Confidence: low
Last updated: 2026-05-29

### MEM-0197: New hardware-mode feature commit body must state which hardware makes the mode necessary and what existing code lacked

Status: draft
Scope: general
Triggers:
- A patch adds support for a new hardware operating mode (e.g. I2C High-Speed,
  PCIe Gen5 link, UART auto-baud) to an existing driver
- The commit body describes the implementation (what was added) but omits: (a) which
  SoC, peripheral, or QUP version requires the mode, and (b) what the existing code
  path lacked that prevents the mode from working without this patch
- Documentation/process/submitting-patches.rst requires the body to explain the reason
  for the change

Maintainer evidence:
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-26) on patch 1/2
  "dmaengine: qcom-gpi: Add I2C High-Speed mode configuration support": "the commit
  message mostly describes what is added. It should more clearly state the problem:
  the existing GPI I2C path only supports non-HS transfers and does not program the
  CONFIG1 TRE and HS GO command fields required by the hardware." Provided a rewritten
  body that leads with the missing capability before describing the change.
- Patchwise AI review (kernel@oss.qualcomm.com, 2026-05-26) on patch 2/2
  "i2c: qcom-geni: Add support for I2C High-Speed mode": "the body focuses heavily on
  what the patch changes and only briefly explains why ... state the problem: the driver
  currently handles standard, fast, and fast-mode plus timings, but does not configure
  the controller for 3.4 MHz transfers." Both independent AI reviewers independently
  requested the same 'why before what' rewrite (confirmed from two sources).
  Our automated review raised this [MINOR] on both patches; both AI reviewers confirmed it.

Review action:
- Flag [MINOR] when a commit body for a new hardware-mode addition describes the
  implementation changes without first stating: (a) which hardware (SoC, peripheral
  family, or IP version) requires the mode and cannot be supported by the existing
  code, and (b) what the existing driver path currently does that is insufficient.
- Suggest restructuring the body as: problem statement (what fails without the patch)
  → solution summary → key implementation points.

False-positive guards:
- Do not flag if the commit body already opens with the hardware motivation and the
  missing capability (even briefly: one sentence is sufficient).
- Do not flag if the cover letter for the series already provides this context and
  the commit body is intentionally terse (single-patch series have no cover letter
  and must be self-contained).
- Do not flag if the commit body explicitly references a hardware specification (e.g.
  HPG section) that identifies the version requirement; the reference itself provides
  sufficient motivation.

Confidence: low
Last updated: 2026-05-27

### MEM-0253: Multi-version series — carry `Reviewed-by`/`Acked-by` tags from prior version into updated patches

Status: draft
Scope: general
Triggers:
- A patch series is re-spun as version N+1 (vN+1)
- Reviewers or maintainers gave `Reviewed-by:` or `Acked-by:` tags on unchanged or
  minimally changed patches in version N
- The vN+1 patches omit those review tags despite the patches being substantively
  unchanged, or the only changes being unrelated to the reviewed code
- A maintainer or reviewer reminds the author to include the prior-version tags

Maintainer evidence:
- Leo Yan (ARM/Coresight reviewer) on [PATCH v9 1/4] coresight: cti: Convert trigger
  usage fields to dynamic (coresight@lists.linaro.org, 2026-05-29): "BTW, I have given
  my review tag on v8, please remember to update patches with review / ack tags."
  Yingchao Deng (author) acknowledged and agreed to update. Our automated review did
  not check for absent prior-version review tags (missed-by-us).

Review action:
- Flag [MINOR] when a re-spun series (v2 or later) changes only a subset of patches
  and the unchanged or lightly edited patches do not carry `Reviewed-by:` or
  `Acked-by:` tags that were given on the corresponding patch in the prior version.
- Check the prior version's lore thread for review/ack tags on the same patch before
  flagging; the tag may be genuinely absent from the prior version too.
- Suggest: "Please add the `Reviewed-by:` tag from vN if the code reviewed has not
  substantively changed."

False-positive guards:
- Do not flag if the patch has substantive code changes relative to the prior version;
  prior tags do not automatically carry forward through functional changes.
- Do not flag if the prior version thread is not accessible or the series is an
  initial submission (no prior version exists).
- Do not flag if the prior reviewer has already submitted a new tag in the vN+1 thread.
- Do not flag `Signed-off-by:` — that tag is not portable across revisions in the
  same way.

Confidence: low
Last updated: 2026-05-29

### MEM-0267: Cover letter changelog must itemize specific changes, not just cite reviewer names or vague summaries

Status: draft
Scope: general
Triggers:
- A re-spun series (v2 or later) cover letter changelog section uses vague language
  such as "Taken care of comments from vN" or "Addressed reviewer feedback" without
  listing the specific changes made
- OR the changelog cites only that it addressed "bot comments" without naming what was
  changed

Maintainer evidence:
- Dmitry Baryshkov on the eliza MM clock series v5 cover letter
  (20260525-eliza_mm_cc_v2-v5-0-a1d125619a5a@oss.qualcomm.com, linux-arm-msm,
  2026-05-25): "Which comments? Please be more specific in changelogics."
  The v5 changelog read "Taken care of comments from v3, v4." Author replied it was
  sashiko-bot comments that were addressed. Our automated review did not check
  changelog specificity (missed-by-us).

Review action:
- Flag [MINOR] when a versioned series cover letter changelog item uses only vague
  attribution (e.g. "Taken care of comments from vN", "Addressed feedback") without
  listing the specific changes made (what was added, removed, or corrected and why).
- Suggest listing each change as a bullet, e.g.:
  "- Removed duplicate clock 'gpu_cc_gpu_smmu_vote_clk' from driver and bindings.
  - Added '#power-domain-cells' for 'camcc' and 'cambistmclkcc' device node."

False-positive guards:
- Do not flag changelogs that list specific items alongside reviewer attribution,
  e.g. "Fixed typo in commit body (Konrad Dybcio)."
- Do not flag if the cover letter has no prior version (v1/initial submission).
- Do not flag trivial single-change series where "Rebased on linux-next" is the
  only change and specificity is self-evident.

Confidence: low
Last updated: 2026-05-30

### MEM-0268: Networking patches targeting the `net` or `net-next` tree must carry a `[PATCH net]` or `[PATCH net-next]` subject prefix

Status: draft
Scope: subsystem:net file-pattern:net/
Triggers:
- A patch fixes a bug or adds a feature in a networking driver or subsystem (net/,
  drivers/net/, net/wireless/, etc.)
- The patch subject uses a plain `[PATCH]` prefix without the tree qualifier
  `net` or `net-next`

Maintainer evidence:
- Alexander Lobakin (networking reviewer) on net: qrtr: fix node refcount leak on
  ctrl packet alloc failure (netdev@vger.kernel.org, 2026-05-28):
  "Please specify the net tree in the subject prefix, i.e. [PATCH net]."
  The submitted patch used `[PATCH]`; the fix targets net (stable-bound via Fixes:).
  Our automated review did not flag the missing tree qualifier (missed-by-us).
- Documented in Documentation/process/maintainer-netdev.rst: bug fixes go to
  `net` (prefix `[PATCH net]`); new features and non-urgent changes go to
  `net-next` (prefix `[PATCH net-next]`).

Review action:
- Flag [MINOR] when a networking patch (files under net/, drivers/net/,
  drivers/net/wireless/, etc.) uses a bare `[PATCH]` subject prefix instead of
  `[PATCH net]` (for fixes/Fixes: patches) or `[PATCH net-next]` (for new features).
- Use `[PATCH net]` for patches carrying a `Fixes:` tag or targeting patchwork's
  netdev net queue; use `[PATCH net-next]` for patches without a `Fixes:` tag that
  add new capabilities.

False-positive guards:
- Do not flag if the prefix already contains the correct tree qualifier
  (`[PATCH net]`, `[PATCH net-next]`, `[PATCH v2 net]`, etc.).
- Do not flag if the patch is for an out-of-tree or vendor-specific networking driver
  that routes to a different tree (e.g., ath12k → ath.git, wireless → wireless-next).
- Do not flag version tags (e.g., `[PATCH v2]`) as missing the tree qualifier if the
  tree was provided in a cover letter explicitly addressing the tree routing.
- Single networking reviewer data point; keep as draft until a second independent
  maintainer or reviewer echoes the same expectation.

Confidence: low
Last updated: 2026-05-30

### MEM-0269: Verbose "Dostoyevsky" cover letter with AI hallmarks — pinctrl maintainer requests Assisted-by tag

Status: draft
Scope: general
Triggers:
- A cover letter (or commit body) is notably long and describes each patch's changes in
  obvious or unnecessary detail ("commenting the obvious")
- The text exhibits AI-generated prose hallmarks: em-dashes (—), overly formal or flowery
  language, excessively detailed explanations of self-evident code changes
- No `Assisted-by:` tag appears in any patch trailer despite clear AI involvement

Maintainer evidence:
- Linus Walleij (pinctrl maintainer) on v2 0/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com (2026-05-29):
  "This cover letter has a very long text mass, something Andy Shevchenko strikingly
  dubbed 'Dostoyevsky commitlogs'. It adds completely obvious descriptions of what every
  patch does breaking the rule of 'don't comment the obvious'. This is usually a sign of
  LLM AI-assisted commit message. It also contains emdashes and other obvious signs of AI.
  In that case, please use the Assisted-by tag, because the LLM can then read this comment
  of mine and learn from it." Cited Documentation/process/coding-assistants.rst.
  Our automated review was classified READY TO APPLY and did not flag the verbose cover
  letter (missed-by-us).

Review action:
- Flag [NIT] when a cover letter (or commit body) is unusually verbose, uses em-dashes,
  and describes every patch's changes in obvious detail that could be inferred from the
  patch subject lines alone.
- Note that Documentation/process/coding-assistants.rst defines a standard `Assisted-by:`
  tag form; if AI assistance is apparent from the text style, suggest adding it.
- Do not rewrite or editorially reduce the cover letter; one [NIT] comment about verbose
  style and the `Assisted-by:` tag is sufficient.

False-positive guards:
- Do not flag well-justified lengthy cover letters that explain *why* the series was
  structured a particular way, dependency chains, or design tradeoffs not obvious from
  the code (that is valuable context).
- Do not flag if the author has already included a proper `Assisted-by:` or similar
  disclosure per coding-assistants.rst.
- Do not flag the presence of em-dashes alone without the "describes the obvious"
  pattern; em-dashes occasionally appear in non-AI text.
- One human maintainer data point; treat as draft.

Confidence: low
Last updated: 2026-05-30

### MEM-0271: Race-fix series without Cc: stable — maintainer may request BROKEN marker patch first

Status: draft
Scope: general
Triggers:
- A series claims to fix a known race condition or safety hazard in a driver that
  has been shipping in stable kernels for multiple releases
- None of the patches in the series carry `Cc: stable@vger.kernel.org`
- The cover letter acknowledges the race or hazard but does not address stable
  backportability or explicitly say the fix is not suitable for stable

Maintainer evidence:
- Eric Biggers (linux-crypto maintainer) on
  [PATCH v19 00/14] crypto/dmaengine: qce: introduce BAM locking and use DMA for register I/O
  (20260526-qcom-qce-cmd-descr-v19-0-08472fdcbf4a@oss.qualcomm.com, 2026-05-29):
  "None of these fixes are Cc'ed to stable, so stable kernels will remain vulnerable
  to these race conditions. Shouldn't this be preceded by a patch, Cc'ed to stable,
  that marks the driver as BROKEN? ... none of the current functionality of this driver
  is actually useful in Linux. It's just been causing problems."
  Our review could not assess this because the series did not apply (CANNOT APPLY).
  Single human maintainer objection; recorded as draft.

Review action:
- Flag [CONCERN] when a series addresses known races or safety bugs in a driver that
  ships in stable kernels but no patches carry `Cc: stable@vger.kernel.org`.
- If the cover letter implies current in-tree behavior is broken or dangerous, ask
  whether a preceding minimal patch marking the driver `BROKEN` (with Cc: stable)
  should come first so stable users are informed.
- Apply only when the series explicitly acknowledges a pre-existing race or hazard;
  do not raise for new-feature series.

False-positive guards:
- Do not flag if the series explicitly explains why the fix is not stable-backportable
  (e.g. requires non-trivial DT or firmware changes to be useful).
- Do not flag if at least one patch in the series already carries `Cc: stable@vger.kernel.org`.
- Do not flag new-feature-only series that add functionality without claiming to fix
  a pre-existing safety or correctness bug.
- Single data point from one maintainer; verify with additional cases before promoting.

Confidence: low
Last updated: 2026-05-30

### MEM-0278: Qcom clock patch subject says "drop critical clocks" but includes non-CLK_IS_CRITICAL clocks — commit body must explain all removed clocks

Status: draft
Scope: subsystem:clk/qcom file-pattern:drivers/clk/qcom/*.c
Triggers:
- A Qcom clock driver patch subject or body uses "critical clocks" or "drop
  modelling of critical clocks" as the description
- The diff also removes one or more clock branches that did NOT carry `CLK_IS_CRITICAL`
  in their `clk_init_data` (i.e., `ops = &clk_branch2_ops` without a `CLK_IS_CRITICAL`
  flag)
- No explanation is given in the commit body for why the non-critical clocks are
  being removed alongside the critical ones

Maintainer evidence:
- Dmitry Baryshkov on [PATCH v2 1/5] clk: qcom: gcc-qcm2290: Drop modelling of critical
  clocks (linux-arm-msm, 2026-05-28): "This clock is not critical. Why is it being
  dropped?" — for `gcc_gpu_iref_clk`. "This clock isn't marked as CRITICAL, why is it
  being dropped?" — for `gcc_video_ahb_clk` and `gcc_video_xo_clk`, which had no
  `CLK_IS_CRITICAL` flag. Author replied the non-critical clocks "also should have been
  marked as CRITICAL" and clarified the intent; agreed to update the commit message.
  Our automated review did not flag the inaccurate subject ("critical clocks") for
  clocks that were never marked critical (missed-by-us).

Review action:
- Flag [MINOR] when a Qcom clock patch title says "drop critical clocks" (or similar)
  but the diff removes clocks that lack `CLK_IS_CRITICAL` in their init data.
- Suggest updating the commit body to explicitly list which removed clocks were not
  previously marked `CLK_IS_CRITICAL` and explain why they are now being treated as
  always-on (e.g., "these clocks should have been marked critical from the start").
- Cross-reference: when any `CLK_IS_CRITICAL`-less clock branch is removed and replaced
  with `qcom_branch_set_clk_en()`, the commit body should justify each such clock.

False-positive guards:
- Do not flag if the commit body already explains why all removed clocks are being
  treated as always-on, regardless of whether they carried `CLK_IS_CRITICAL` before.
- Do not flag if the non-critical clocks are removed for a different reason (e.g.,
  hardware programming via a separate mechanism) and the commit body says so.
- One data point; treat as draft.

Confidence: low
Last updated: 2026-05-30

### MEM-0282: `Reported-by:` must not be used for non-bug improvements — use `Suggested-by:`

Status: draft
Scope: general
Triggers:
- A patch commit trailer uses `Reported-by: Person <email>` for a contribution
  that is an improvement, rename, or cleanup with no actual defect or regression
- The person identified a gap or suggested a change, but no functional bug exists

Maintainer evidence:
- Krzysztof Kozlowski (DT bindings maintainer) on "dt-bindings: mmc: sdhci-msm:
  Rename the binding to include 'qcom' prefix" (linux-arm-msm, 2026-05-30):
  "Suggested-by, please. No bug here." — the patch renamed a binding to fix
  MAINTAINERS wildcard coverage; Mukesh Ojha identified the gap, but no defect
  was present. Our automated review praised `Reported-by:` as correct (false positive).

Review action:
- Flag [NIT] when a commit uses `Reported-by:` for a change that is an improvement,
  rename, or style fix with no actual bug (defect, regression, crash, or functional
  failure) being fixed.
- Suggest replacing `Reported-by:` with `Suggested-by:` per
  Documentation/process/submitting-patches.rst.

False-positive guards:
- Do not flag `Reported-by:` when the patch fixes a genuine defect, regression, or
  functional failure.
- Do not flag when a `Closes:` link points to a bug report or GitHub issue describing
  a failure (a failure report still warrants `Reported-by:`).
- Do not flag when the commit already uses `Suggested-by:` correctly.

Confidence: low
Last updated: 2026-05-30

### MEM-0283: Commit body "the only X" uniqueness claim — verify before accepting

Status: draft
Scope: general
Triggers:
- A commit body makes a uniqueness claim about the element being changed:
  "This is the only X", "the sole exception", or "uniquely missing Y"
- The claim can be verified by a grep or directory listing in the same tree area

Maintainer evidence:
- Krzysztof Kozlowski (DT bindings maintainer) on "dt-bindings: mmc: sdhci-msm:
  Rename the binding to include 'qcom' prefix" (linux-arm-msm, 2026-05-30):
  corrected "This is the only Qcom binding that doesn't have 'qcom' prefix in the
  bindings name" — multiple others also lacked the prefix (dp-controller.yaml,
  dpu-common.yaml, dsi-controller-main.yaml, gmu.yaml, gpu.yaml, hdmi.yaml,
  mdp4.yaml, mdss-common.yaml, ipq806x-dwmac.yaml, leds-qcom-*).
  Our automated review accepted and praised the commit body accuracy (false positive).

Review action:
- Flag [NIT] when a commit body uses "the only X", "sole exception", or similar
  absolute uniqueness language.
- Verify by grepping the relevant directory for counterexamples (e.g.,
  `ls Documentation/devicetree/bindings/mmc/*.yaml | grep -v qcom` for a binding
  that claims to be the only one missing a vendor prefix).
- If counterexamples exist, flag [NIT]: the claim is factually overstated and will
  mislead reviewers about the scope of the problem.

False-positive guards:
- Do not flag uniqueness claims that are structural or logical (e.g. "this is the
  only call site that takes the lock without checking X") rather than empirical.
- Do not flag claims already qualified as "one of the few X" rather than "the only X".
- Do not elevate above [NIT]; the patch itself may be correct even if the uniqueness
  claim is overstated.

Confidence: low
Last updated: 2026-05-30
