# Review Memory — Commit Message (active)

### MEM-0034: Non-standard AI disclosure trailer tag — flag [NIT] and suggest prose note

Status: active
Scope: general
Triggers:
- A commit trailer uses a non-standard tag such as "Assisted-by: Claude:<model>" with a
  colon-separated model suffix, or "Generated-by:", to disclose AI tool involvement
- The colon-suffix syntax (e.g. "Assisted-by: Claude:claude-opus-4-6") is not parseable
  by b4, patchwork, or kernel patch-tracking tooling

Maintainer evidence:
- Patchwise AI review (2026-05-12) on "dt-bindings: remoteproc: qcom,sm8550-pas: Add
  Maili ADSP and CDSP": "Assisted-by: Claude:claude-opus-4-6" flagged as non-standard;
  not parseable by b4, patchwork, or kernel patch-tracking tooling. Confirmed by two
  independent automated reviews in the same thread.
- Patchwise AI review (2026-05-12) on "misc: fastrpc: fix use-after-free of cctx in
  fastrpc_buf_free": "Assisted-by: Claude:claude-4-6-sonnet" flagged as non-standard;
  recommended removing the tag entirely or, if co-authorship is intended, using the
  standard "Co-developed-by: Name <email>" + matching "Signed-off-by:" pair. Second
  independent instance of the same reviewer rejecting this pattern on a different patch.
- Patchwise AI review (2026-05-12) on "dt-bindings: interconnect: qcom-bwmon: Add Maili
  cpu-bwmon compatible": "Assisted-by: Claude:claude-opus-4-7" flagged as non-standard;
  the colon-separated model suffix does not match any kernel trailer convention; suggested
  removing or replacing with a prose note in the body. Third independent instance of this
  pattern; our automated review raised the same [NIT] independently, confirming it is
  consistently detected by both tools.
- Dmitry Baryshkov on "dt-bindings: misc: qcom,fastrpc: Add Maili FastRPC compatible"
  (linux-arm-msm, 2026-05-25): replied to "Assisted-by: Claude:claude-opus-4-6" with
  "Claude assisting to write a one-liner patch? It's becoming ridiculous." First human
  maintainer objection to this colon-suffix syntax; the tag drew unwanted scrutiny.
- Linus Walleij (pinctrl maintainer) on patch v2 0/4 of
  20260528-pinctrl-level-shifter-v2-0-3a6a025392bf@oss.qualcomm.com (2026-05-29):
  explicitly requested bare "Assisted-by:" when the cover letter displayed obvious AI
  hallmarks (over-verbose descriptions, em-dashes), citing
  Documentation/process/coding-assistants.rst. This confirms that plain "Assisted-by: <tool>"
  per coding-assistants.rst is the correct disclosure form, distinct from the non-standard
  colon-suffix syntax flagged above.
- Krzysztof Kozlowski (DT bindings maintainer) on "dt-bindings: misc: qcom,fastrpc: Add
  Maili FastRPC compatible" (linux-arm-msm, 2026-05-30): after Dmitry Baryshkov already
  complained ("becoming ridiculous"), Kozlowski dropped the patch from patchwork: "If a
  human cannot write and validate this one, I see as putting effort on maintainers." The
  patch was rejected from patchwork solely because of AI disclosure on a trivial one-liner.
  Second maintainer-level rejection in the same thread confirms the colon-suffix tag on
  trivial patches causes outright rejection, not just scrutiny.

Review action:
- Flag [NIT] when a commit trailer uses a colon-separated model suffix in an AI disclosure
  tag (e.g. "Assisted-by: Claude:claude-opus-4-6", "Generated-by: GPT:gpt-4").
- Distinguish: bare "Assisted-by: <tool>" per Documentation/process/coding-assistants.rst
  is the intended standard form and should not be removed — it is properly formed disclosure.
- Suggest replacing the colon-suffix form with the correctly formatted version per
  coding-assistants.rst, or moving to a prose note in the commit body.
- If the intent is to credit a co-author who contributed code, suggest the standard
  "Co-developed-by: Name <email>" + matching "Signed-off-by:" pair instead.
- Note: two Qualcomm-subsystem maintainers (Baryshkov, Kozlowski) have explicitly rejected
  patches where the colon-suffix form appeared on trivial one-liner changes.

False-positive guards:
- Do not flag standard trailer tags (Fixes:, Cc:, Reported-by:, Suggested-by:,
  Co-developed-by:, Tested-by:, Acked-by:, Reviewed-by:, Signed-off-by:, Link:).
- Do not flag bare "Assisted-by: <tool>" that follows the format in
  Documentation/process/coding-assistants.rst (no colon-separated model suffix).
- Do not flag tags explicitly accepted by the subsystem maintainer in the same thread.

Confidence: high
Last updated: 2026-05-30

### MEM-0171: `Co-developed-by:` must not replicate the `From:` author

Status: active
Scope: general
Triggers:
- A patch trailer contains `Co-developed-by: Name <email>` where Name and email
  exactly match the `From:` field of the same patch
- The nominal patch author is thus credited as both author and co-developer

Maintainer evidence:
- Dmitry Baryshkov on patches 1/5, 2/5, and 5/5 of
  20260515-jianping-li-misc-fastrpc-add-missing-bug-fixes (linux-arm-msm, 2026-05-15):
  "If it's From:Ekansh, it can't be CDB: Ekansh. How can Ekansh co-develop the patch
  with himself?" Author acknowledged and removed the redundant tag. checkpatch also warns
  on this pattern. Our automated review flagged it [MINOR] via checkpatch; confirmed.

Review action:
- Flag [MINOR] when `Co-developed-by: X` matches the `From:` author of the same patch.
- Suggest removing the redundant `Co-developed-by:` line.
- If a second contributor (e.g. the Signed-off-by co-signer) also wrote code in the
  patch, use `Co-developed-by: <their name>` with a matching `Signed-off-by:` instead.

False-positive guards:
- Do not flag `Co-developed-by:` that names a different person from the `From:` author.
- Do not flag `Signed-off-by:` lines — multiple Signed-off-by entries are normal.

Confidence: high
Last updated: 2026-05-26
