# Review Memory — Subsystem Specific (active)

### MEM-0047: `this_cpu_write/read()` wrong when target CPU may differ from current CPU

Status: active
Scope: general
Triggers:
- A function clears or modifies a per-CPU variable that tracks state for a
  specific device or CPU-bound source (e.g., `percpu_pm_failed` keyed on a
  device's `.cpu` field)
- The function may be invoked on any CPU (e.g., unregister, driver `.remove`,
  hotplug notifier, or any path not pinned to the target CPU)
- `this_cpu_write()`, `this_cpu_read()`, or `this_cpu_ptr()` is used where
  `per_cpu(var, target_cpu)` is required

Maintainer evidence:
- Leo Yan (ARM/Coresight, patch author) self-confirmed on patch 23/28 of
  20260515-arm_coresight_path_power_management_improvement-v13 (coresight:
  Control path during CPU idle, 2026-05-15):
  "This is not right when I looked again, we cannot assume this happens on
  local CPU. I will update and send a new one."
  The bug: `coresight_clear_percpu_source()` used
  `this_cpu_write(percpu_pm_failed, false)` but executes on whichever CPU
  calls `coresight_unregister()`, leaving the flag permanently set on the
  source's actual CPU (CPU X) when unregister runs on CPU Y.
  Our automated review identified this as [BUG] independently; author
  confirmation makes this a direct match (confirmed).

Review action:
- Flag [BUG] when `this_cpu_write()`, `this_cpu_read()`, or `this_cpu_ptr()`
  is used in a function that (a) modifies per-CPU state belonging to a
  specific device or CPU-bound source AND (b) may execute on a CPU other than
  the target CPU (unregister, remove, PM notifier, etc.).
- The correct form is `per_cpu(var, target_cpu) = value` where `target_cpu`
  is the CPU the device or source is bound to (e.g., `csdev->cpu`).
- Verify whether the call site guarantees CPU affinity before downgrading.

False-positive guards:
- Do not flag if the call site is always pinned to the target CPU (e.g.,
  a CPU hotplug enter/exit callback fired by the scheduler for that exact
  CPU, or bracketed by `get_cpu()`/`put_cpu()` that selects the target).
- Do not flag per-CPU counters or sharded statistics where accumulation on
  the current CPU is intentional (not tracking state for a bound device).
- Do not flag if the per-CPU variable is used for the *current* CPU's own
  purpose and there is no notion of a "bound" target CPU.

Confidence: high
Last updated: 2026-05-26

### MEM-0136: ARM/Coresight --- _coresight_build_path() multi-path contamination is out-of-spec; do not flag

Status: active
Scope: subsystem:coresight file-pattern:drivers/hwtracing/coresight/coresight-core.c
Triggers:
- A patch modifies _coresight_build_path() or the recursive path-building
  loop in coresight-core.c
- A reviewer or tool raises a concern that when one recursive branch partially
  fails while another succeeds, the already-added nodes from the failed branch
  remain on path->path_list, leaving garbage entries on a successful return

Maintainer evidence:
- Mike Leach (ARM/Coresight maintainer) on coresight: fix resource leaks on
  path build failure (coresight@lists.linaro.org, 2026-05-20): Multiple paths
  between a source and sink are not permitted under the CoreSight spec. If such
  a system was to be built - then a fix would need to be in the declaration of
  connections - e.g. miss one path out in the device tree for example. Not up
  to the Coresight drivers to handle out of specification hardware.
- James Clark (ARM/Coresight reviewer) confirmed in the same thread:
  That is ok then we can ignore this for this patch. But it would be good to
  enforce that in _coresight_build_path() with some kind of assert. Or at least
  add a comment to appease the AI reviewers.
  Message-ID: 20260513-fix-memory-leak-issue-v1-1-49822d7bc7d4@oss.qualcomm.com

Review action:
- Do not raise a [CONCERN] or [BUG] about multi-path contamination in
  _coresight_build_path().
- The CoreSight spec prohibits multiple source-to-sink routes; a second valid
  path is an out-of-spec DT configuration that must be fixed in the DT, not
  the driver.
- It is acceptable to flag [NIT] suggesting an assertion or in-code comment to
  document the single-path invariant (James Clark explicitly suggested this).

False-positive guards:
- Do not apply if a future patch explicitly adds multi-path support with a
  clear maintainer statement accepting that topology.
- Do not apply to other recursive graph traversals outside
  _coresight_build_path() without confirming the same single-path invariant.

Confidence: high
Last updated: 2026-05-26

### MEM-0151: ath12k AHB — new qcom_scm_pas*() callers conflict with pending OP-TEE PAS migration

Status: active
Scope: subsystem:ath12k file-pattern:drivers/net/wireless/ath/ath12k/ahb.c
Triggers:
- A new ath12k AHB patch adds calls to qcom_scm_pas_auth_and_reset() or
  qcom_scm_pas_shutdown()
- The series is submitted for public review (not an internal-only change)

Maintainer evidence:
- Jeff Johnson (ath12k maintainer) on [PATCH ath-next v5 6/7] wifi: ath12k: add support to
  load shared firmware (2026-05-20): "This patch conflicts with the following series which is
  removing all the qcom_scm_pas*() wrappers, replacing them with qcom_pas*() function calls:
  [PATCH v6 00/16] firmware: qcom: Add OP-TEE PAS service support.
  Since that series is already in public for a long time and the review seems complete, we
  need to wait for it before we can post your series in public." Author (Aaradhana Sahu) agreed to hold patch
  6/7 until the migration is merged. Our automated review missed this conflict (missed-by-us).
  Direct maintainer feedback; promoted from draft to active.

Review action:
- When a patch adds new calls to qcom_scm_pas_auth_and_reset() or qcom_scm_pas_shutdown(),
  check whether the OP-TEE PAS migration (qcom_scm_pas*() -> qcom_pas*()) has landed in
  ath.git.
- Flag [CONCERN] if the migration is still pending: new callers will need rework after merge
  and the patch should be held until after the next merge window.
- Flag [MINOR] if the migration is already merged and the patch still uses the old
  qcom_scm_pas*() API.

False-positive guards:
- Do not flag patches that already use the new qcom_pas*() API.
- This entry becomes stale once the OP-TEE PAS migration is universally merged in ath.git;
  verify tree state before applying.
- Do not flag non-AHB (PCIe) ath12k patches that do not call qcom_scm_pas*().

Confidence: medium
Last updated: 2026-05-27

### MEM-0174: MHI client series — question framework-level PM centralisation before accepting per-client data-path guards

Status: active
Scope: subsystem:mhi file-pattern:drivers/bus/mhi/* drivers/net/mhi_net.c drivers/net/wwan/*
Triggers:
- A series adds identical pm_runtime_get/put guards to two or more MHI client
  drivers covering their TX, RX, or buffer-management data paths
- The MHI core does not currently enforce runtime PM on behalf of its clients

Maintainer evidence:
- Loic Poulain (MHI/WWAN maintainer) on patch 3/6 of 20260522-mhi_runtimepm-v2
  (20260522-mhi_runtimepm-v2-0-fbebf41a82bb@oss.qualcomm.com, 2026-05-22):
  questioned why PM responsibility is pushed to each client rather than handled
  centrally in the MHI framework; suggested it could be done generically there
  (missed-by-us; our automated review did not raise this architectural concern).
- Paolo Abeni (netdev maintainer) on same patch 3/6 (2026-05-26): explicitly
  agreed — adding PM tracking to a NIC driver network data-path "looks quite bad";
  the MHI core should centralize all PM state needed to track this correctly.
  Two independent maintainer NAK-level objections (MHI + netdev).

Review action:
- When 2+ patches in a series each add the same pm_runtime_get/put pattern to
  different MHI client drivers, raise [CONCERN] asking whether the MHI core
  should centralize runtime PM so clients need not bracket every data-path call.
- Suggest the author discuss a framework-level solution with the MHI maintainer
  before posting a new version.

False-positive guards:
- Do not flag if the cover letter explains why framework-level PM is insufficient
  (e.g. per-client suspend budgets, different PM domains).
- Do not flag when only one client driver in the series adds PM guards.
- Do not flag probe-time pm_runtime_no_callbacks() or enable calls alone; the
  concern is repeated get/put wrapping of every TX/RX data-path operation.

Confidence: medium
Last updated: 2026-05-30

### MEM-0185: `__free()` cleanup-helper variable declared after a statement — do not flag "declaration after statement"

Status: active
Scope: general
Triggers:
- A patch declares a local variable with a kernel cleanup specifier (e.g.
  `const struct firmware *fw __free(firmware) = NULL;`) on a line that follows
  a statement (e.g. an `snprintf()` call or other non-declaration)
- A reviewer or automated check flags the pattern as "declaration after statement"
  citing the historical C89/C90 rule against mixing declarations and code

Maintainer evidence:
- Aaradhana Sahu (ath12k patch author) on [PATCH ath-next v5 6/7] wifi: ath12k: add
  support to load shared firmware (2026-05-19): "mixed declarations and code are allowed
  when using cleanup helpers. Therefore, these comments are not applicable in this case."
  Our automated review incorrectly flagged `const struct firmware *fw __free(firmware) = NULL`
  following `snprintf()` as "Declaration after statement"; the author correctly rebutted it.
  checkpatch reported 0 errors, 0 warnings, 0 checks for that patch (no "declaration after
  statement" violation), confirming the kernel tooling does not treat this as an error.

Review action:
- Do NOT flag "declaration after statement" when the variable declaration uses a kernel
  cleanup helper attribute (e.g. `__free()`, `__cleanup()`).
- Kernel source uses C99/gnu11 (not C89), so mixed declarations and code are always
  permitted; the restriction is obsolete in current kernel builds.
- Before raising this finding, verify checkpatch --strict does not report it; if checkpatch
  is silent, so should the review.

False-positive guards:
- This false-positive guard applies only to the "declaration after statement" finding.
  It does not suppress findings about incorrect variable scope, resource leak, or incorrect
  use of the cleanup helper itself.
- If checkpatch --strict does flag a "declaration after statement" issue in the same
  location, the finding may be legitimate for a different reason; do not suppress it.

Confidence: medium
Last updated: 2026-05-27

### MEM-0221: `clk_ops.is_enabled` returning negative errno is treated as "enabled" — intentional conservative behavior; require comment

Status: active
Scope: subsystem:clk file-pattern:drivers/clk/
Triggers:
- A `clk_ops.is_enabled` implementation returns the negative errno from a failed
  register read (e.g. `if (ret) return ret;` after `regmap_read()`)
- A reviewer flags that the CCF evaluates the return value as boolean so a negative
  errno is treated as "enabled" (non-zero)

Maintainer evidence:
- Dmitry Baryshkov (Qualcomm CLK maintainer) on [PATCH v4 2/7] clk: qcom: Add generic
  clkref_en support (linux-arm-msm, 2026-05-28): "to be 'false', the error number must
  be 0." — clarifying that returning negative errno is a deliberate conservative choice
  (unknown hardware state → report "enabled" to avoid disabling something that may be on).
- Qiang Yu (author, same thread): "A regmap_read failure doesn't mean the clock is
  disabled." — confirming the conservative return is intentional; agreed to add a comment.
- Our automated review flagged this as [MINOR] (correct that it is noteworthy) but
  suggested returning 0 (wrong fix); the correct fix is a comment, not a code change.

Review action:
- Flag [MINOR] when `clk_ops.is_enabled` propagates a negative errno from a failing
  register read without an in-code comment explaining the conservative behavior.
- Do NOT suggest changing the return to 0 (disabled) — that is the wrong policy.
- The correct fix is adding a comment: `/* assume enabled on read error (conservative) */`
- Alternatively suggest: `if (ret) return 1; /* assume enabled on read error */`

False-positive guards:
- Do not flag if the function already carries a comment explaining the conservative
  error-return policy.
- Do not flag `is_enabled` implementations that return 0 on `regmap_read` failure;
  that is a different (also valid) policy.

Confidence: medium
Last updated: 2026-05-29

### MEM-0235: Qcom iris series must base on `media-committers/next`, not linux-next

Status: active
Scope: subsystem:media file-pattern:drivers/media/platform/qcom/iris/
Triggers:
- A patch series for the Qualcomm Iris video codec driver (drivers/media/platform/qcom/iris/)
  fails to apply against the current linux-next tag due to a conflict with a commit from
  the iris maintainer tree
- The series cover letter or base-commit points to a linux-next tag rather than
  the `media-committers/next` branch

Maintainer evidence:
- Bryan O'Donoghue (QUALCOMM MEDIA PLATFORM maintainer) on
  [PATCH v8 0/5] media: iris: add support for purwa platform (linux-media,
  2026-05-29): When Jie Gan requested rebasing on the latest linux-next tag to
  fix a conflict with upstream commit 95a337f92f0a ("media: iris: switch to
  hardware mode after firmware boot"), O'Donoghue corrected: "That's a -stable
  commit. Base patches off of media-committers/next."
  git@ssh.gitlab.freedesktop.org:linux-media/media-committers.git
  Our automated review correctly identified the apply failure and root cause, but
  did not know the authoritative base tree for this subsystem (missed-by-us).

Review action:
- When an iris series fails to apply against linux-next and the conflict is in
  iris maintainer tree code, note that the correct base branch is
  `media-committers/next` (git@ssh.gitlab.freedesktop.org:linux-media/media-committers.git),
  not a linux-next tag.
- In the review report CANNOT APPLY section, explicitly name `media-committers/next`
  as the required rebase target when the conflicting upstream commit originates from
  the iris maintainer tree.
- Flag [CONCERN] if the series cover letter base-commit references a linux-next tag
  rather than media-committers/next.

False-positive guards:
- Do not apply to non-iris media drivers (venus, vidc, etc.); use only for
  drivers/media/platform/qcom/iris/ series without separate confirming evidence
  for other drivers.
- Do not flag if the series already bases on media-committers/next.

Confidence: high
Last updated: 2026-05-29

### MEM-0245: API-removal series replaces convenience API with verbose inline at 20+ sites — reviewer will request a replacement wrapper

Status: active
Scope: general
Triggers:
- A series removes a convenience API (e.g. `cpumap_print_to_pagebuf()`) that wraps
  a common multi-argument pattern and is used at 20+ call sites
- Every use is replaced with an equivalent verbose inline (e.g.
  `sysfs_emit(buf, "%*pbl\n", cpumask_pr_args(mask))`)
- No replacement helper macro or static inline is introduced to encapsulate the
  new pattern

Maintainer evidence:
- Robin Murphy (ARM/CCI reviewer) on [PATCH 13/16] perf: Use sysfs_emit() for
  cpumask show callbacks (20260528183625.870813-1-ynorov@nvidia.com, 2026-05-29):
  requested `#define sysfs_emit_cpumask(buf, mask) sysfs_emit((buf), "%*pbl\n", cpumask_pr_args(mask))`
  to avoid boilerplate at 20+ sites, and questioned removing an API solely due to
  occasional misuse. Our automated review missed this (missed-by-us).
- David Laight on the same thread (2026-05-29): agreed, noting a wrapper allows
  re-implementation without hunting all callers. Second direct reviewer confirmation.

Review action:
- Flag [CONCERN] when a series removes a convenience API at 20+ call sites and
  replaces each with a verbose multi-argument inline pattern, with no replacement
  wrapper (macro or static inline) provided.
- Suggest a one-liner macro in the relevant header to encapsulate the new idiom.
- Note that reviewers may question removing an API solely on grounds of occasional
  misuse; the series should justify the removal rationale explicitly.

False-positive guards:
- Do not flag if the replacement pattern is already as concise as the removed API
  (similar character count per call site).
- Do not flag if fewer than ~10 call sites are changed.
- Do not flag if the cover letter explicitly states inline expansion is intentional.
- Do not flag if the removed API had well-known misuse problems the inline expansion
  is specifically intended to discourage.

Confidence: medium
Last updated: 2026-05-29

### MEM-0257: Qcom CAMSS — identical SoC resource struct should use DTS fallback, not duplicate struct + new enum value

Status: active
Scope: subsystem:camss file-pattern:drivers/media/platform/qcom/camss/camss.c
Triggers:
- A patch adds a new `camss_resources` struct for a new SoC where every field
  (csiphy_res, csid_res, vfe_res, icc_res, *_num) points to existing `_2290`
  (or equivalent) arrays — effectively a copy with only a different `.version`
- A corresponding new `CAMSS_xxxx` enum value is also introduced in `camss.h`
  solely to distinguish this otherwise-identical SoC
- OR: a patch adds `case CAMSS_XXXX:` to one or more switch statements in
  `camss-vfe.c` (e.g. `vfe_src_pad_code()`, `vfe_bpl_align_rdi()`) purely as
  a fallthrough to an adjacent case, providing no unique behaviour

Maintainer evidence:
- Loic Poulain on patch 3/8 "media: qcom: camss: add support for QCM2390 camss"
  (linux-media, 2026-05-28): "isn't it exactly the same as 2290? wouldn't it be
  easier to have the shikra simply fallback to qcm2290 (via compatible string)?"
- Bryan O'Donoghue on same patch (2026-05-28): NAK — "what is the point of this
  identifier? It literally just adds a new define and a new string."
- Vikram Sharma (author) ACKed the fallback approach. Two independent maintainer
  objections with explicit NAK and author agreement. Our automated review gave
  READY TO APPLY without flagging the duplicate (missed-by-us).
- Bryan O'Donoghue on patch 5/6 "media: qcom: camss: enable vfe for Glymur"
  (linux-media, 2026-05-29) — NAK: "This is a pointless enum add." — the patch
  added `case CAMSS_GLYMUR:` immediately before `case CAMSS_X1E80100:` in both
  `vfe_src_pad_code()` and `vfe_bpl_align_rdi()` with no unique behaviour.
  Same core objection in a second series; our automated review did not flag it
  (missed-by-us). Third independent NAK confirming the pattern.

Review action:
- Flag [CONCERN] when a new `camss_resources` struct copies all resource arrays
  from an existing struct verbatim and the only diff is the `.version` enum value.
- Suggest using a DTS fallback compatible (e.g. `"qcom,qcm2290-camss"` as
  fallback for `"qcom,shikra-camss"`) to reuse the existing struct without a
  driver change.
- Also check `camss.h`: if the new `CAMSS_xxxx` enum value is referenced only in
  the duplicate struct and/or trivial case-fallthrough adds in `camss-vfe.c`,
  it is a sign that the enum should not exist at all (maintainers will NAK).
- Flag [CONCERN] when a patch adds `case CAMSS_XXXX:` to switch statements in
  `camss-vfe.c` purely as a fallthrough with no unique behaviour; the correct fix
  is to use a DTS fallback compatible so the new SoC picks up the existing case.

False-positive guards:
- Do not flag when the new struct differs in at least one resource array (e.g.
  different csiphy_res or icc_res arrays).
- Do not flag when the new version identifier drives meaningful code branches
  beyond simple case-fall-through aliasing elsewhere in the driver.
- Do not flag case additions that include non-trivial logic unique to the new SoC.

Confidence: high
Last updated: 2026-05-29

### MEM-0286: Qcom CAMSS DT binding — CSIPHY must be a distinct sub-node; monolithic CAMSS binding embedding CSIPHY will be rejected

Status: active
Scope: subsystem:camss file-pattern:Documentation/devicetree/bindings/media/qcom,*camss*.yaml
Triggers:
- A new `qcom,*-camss.yaml` binding describes CSIPHY power supplies (e.g.
  `vdd-csiphy-0p8-supply`, `vdd-csiphy-1p2-supply`) and CSIPHY clock/reset
  resources as top-level properties of the CAMSS node, rather than as
  properties of distinct CSIPHY child sub-nodes
- OR: the binding lists CSIPHY register ranges as named entries in the parent
  CAMSS node's `reg`/`reg-names` list (e.g. `csiphy0`, `csiphy1`, `csiphy4`
  as entries in a monolithic node) with no companion binding for a dedicated
  `qcom,<soc>-csiphy` child node
- The binding author is a Qualcomm engineer working against an internal deadline
  and the CSIPHY-as-subnode refactor has been requested in prior series versions
  but not implemented

Maintainer evidence:
- Bryan O'Donoghue (CAMSS maintainer) on Patch 1/6 "dt-bindings: media: Add
  bindings for qcom,glymur-camss" (linux-media, 2026-05-29): "This binding should
  be predicated on separate CSIPHY nodes. I've published three perhaps four versions
  of that patch to radio silence on your side." Explicitly NAKed the monolithic
  approach. Message-ID: 20260529-glymur_camss-v1-0-bee535396d22@oss.qualcomm.com
- Krzysztof Kozlowski (DT bindings maintainer) on the same patch (linux-arm-msm,
  2026-05-30): dropped the patch and other CAMSS patches from Patchwork without
  further review. Two independent maintainer-level rejections; our automated review
  only flagged the missing camcc.h header and did not raise the architectural
  issue (missed-by-us).

Review action:
- Flag [CONCERN] when a new `qcom,*-camss.yaml` binding embeds CSIPHY supply
  or clock/reset properties as top-level CAMSS node properties.
- Suggest that the patch should be predicated on CSIPHY being modeled as a
  distinct sub-node binding (Bryan O'Donoghue has published patch versions for
  this and Qualcomm engineers should engage on that work first).
- Note that Krzysztof Kozlowski will drop these patches from Patchwork until
  the CSIPHY subnode restructuring is done.

False-positive guards:
- Do not flag CAMSS bindings that already model CSIPHY as distinct child nodes
  with their own compatible and sub-node structure.
- Do not apply to non-CAMSS media bindings.
- Do not apply if the upstream CSIPHY-subnode series from Bryan O'Donoghue has
  already been merged and the new binding correctly builds on it.
- Do not flag patches that only add a new compatible enum entry to an existing
  binding YAML with no structural changes (a pure enum extension is not
  introducing a monolithic CSIPHY topology).

Confidence: high
Last updated: 2026-05-30

### MEM-0290: Qcom GENI SPI/SE driver — `geni_se_resources_init()` leaves `se->clk` as ERR_PTR on ACPI; subsequent `clk_round_rate()` will dereference ERR_PTR

Status: active
Scope: subsystem:spi file-pattern:drivers/spi/spi-geni-qcom.c
Triggers:
- A patch replaces an explicit `devm_clk_get(dev, "se")` + `IS_ERR` guard with a
  call to `geni_se_resources_init()` in a driver that later calls
  `geni_se_clk_freq_match()` or `clk_round_rate()` unconditionally on `se->clk`
- `geni_se_resources_init()` tolerates a missing clock on ACPI platforms (ACPI
  companion present) and leaves `se->clk` as an ERR_PTR in that case

Maintainer evidence:
- Sashiko-bot on [PATCH v2 2/4] "spi: qcom-geni: Use geni_se_resources_init()"
  (20260530-enable-spi-on-sa8255p-v2-0-17574601bd63@oss.qualcomm.com, 2026-05-30):
  "[High] geni_se_resources_init() leaves se->clk as ERR_PTR on ACPI; downstream
  clk_round_rate() (called via get_spi_clk_cfg → geni_se_clk_freq_match) only
  checks for NULL, not IS_ERR(), and will dereference the error pointer." Prior
  code correctly aborted probe if the clock was missing. Our automated review
  missed this regression (missed-by-us).

Review action:
- When a patch switches from explicit `devm_clk_get()` to `geni_se_resources_init()`,
  check all downstream call sites that dereference `se->clk` (e.g.
  `geni_se_clk_freq_match`, `clk_round_rate`, `clk_set_rate`).
- Flag [BUG] if any such call site checks `!se->clk` but not `IS_ERR(se->clk)`, or
  does not check at all, while `geni_se_resources_init()` may leave `se->clk` as
  ERR_PTR on ACPI platforms.
- The fix is either: add an `IS_ERR(se->clk)` guard before those calls, or add an
  early-out check after `geni_se_resources_init()` for `IS_ERR(se->clk)`.

False-positive guards:
- Do not flag if the driver only runs on DT platforms and has no ACPI companion support
  (ERR_PTR path in `geni_se_resources_init()` is unreachable).
- Do not flag if all `clk_round_rate()` / `geni_se_clk_freq_match()` callers already
  guard with `if (IS_ERR_OR_NULL(se->clk)) return 0` or equivalent.

Confidence: medium
Last updated: 2026-05-31
