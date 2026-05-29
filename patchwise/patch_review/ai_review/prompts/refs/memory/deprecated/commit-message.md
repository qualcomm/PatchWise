# Review Memory — Commit Message (deprecated)

### MEM-0004: Missing `Cc: stable@vger.kernel.org` on a stable-eligible `Fixes:` patch — flag as [MINOR]

Status: deprecated
Scope: general
Triggers:
- A patch carries a `Fixes:` tag but omits `Cc: stable@vger.kernel.org`
- The commit that is being fixed predates the current stable kernel series (i.e., it is present in at least one stable-maintained kernel)

Maintainer evidence:
- Suzuki K Poulose (ARM/Coresight maintainer) applied patch
  20260505-james-cs-ete-pm_save_enable-v3-1-485d21dd79b8@linaro.org with
  "Applied, thanks!" without requesting the missing stable tag be added first,
  confirming that absence does not block acceptance.
- Mark Brown (regulator maintainer) applied
  20260506-fix_pmh0101_ldo16_index-v1-1-cdc8708b01f4@oss.qualcomm.com to
  broonie/regulator for-7.1 without requesting the missing Cc: stable tag,
  despite a clear Fixes: tag pointing to an accepted upstream commit.
  Second independent confirmation that absence does not block acceptance.
- Suzuki K Poulose applied
  20260512-fix-trace-id-error-v4-1-eb3de789767a@oss.qualcomm.com
  (coresight: fix missing error code when trace ID is invalid) with "Applied,
  thanks!" without requesting the missing Cc: stable@vger.kernel.org despite a
  Fixes: tag present. Third independent confirmation that absence does not
  block acceptance.
- Srinivas Kandagatla (fastrpc/misc maintainer) on
  20260526101343.44838-1-kipreyyy@gmail.com (linux-arm-msm, 2026-05-30):
  explicitly requested "This needs cc: Stable" while calling the patch "sane",
  without blocking acceptance pending the tag. First direct maintainer
  request to add the stable tag, confirming the finding warrants [MINOR]
  attention even though absence alone does not block merge.

Review action:
- Flag [MINOR] (not [CONCERN] or [BUG]) when a `Fixes:` patch is missing `Cc: stable@vger.kernel.org` AND the fixed commit is actually present in a stable-maintained kernel or the commit body explicitly requests stable backporting.
- Suggest adding `Cc: stable@vger.kernel.org` immediately after the `Fixes:` line only after that stable eligibility check passes.
- If stable eligibility is unclear, do not file a finding; at most leave an optional verification note.

False-positive guards:
- Do not flag if `Cc: stable@vger.kernel.org` is already present in the trailer block.
- Do not flag if the fixed commit is too recent to be in any stable-maintained kernel (e.g., introduced in the current merge window).
- Do not flag if the patch itself carries an explicit note explaining why it should not be backported.

Confidence: high
Last updated: 2026-05-31
