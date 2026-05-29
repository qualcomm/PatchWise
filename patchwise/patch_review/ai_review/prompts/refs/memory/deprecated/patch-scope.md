# Review Memory — Patch Scope (deprecated)

### MEM-0149: `Fixes:` patch in a feature series must be decoupled for stable backport

Status: deprecated
Scope: general
Triggers:
- A patch series contains a patch with a `Fixes:` tag alongside patches introducing new
  features or unrelated refactors
- The Fixes: patch has dependencies on only some earlier patches in the series (not all)
- A stable maintainer would need to cherry-pick the fix without the feature patches

Maintainer evidence:
- Jeff Johnson (ath12k maintainer) on [PATCH ath-next v5 0/7] wifi: ath12k: improve memory
  management for IPQ5332 platform variant (2026-05-20): "Let's start with Patch 4 since it
  has a Fixes tag. If this doesn't have dependencies upon the first 3 patches then it should
  go separately as a bug fix that can be backported. If it does have dependencies, then it
  should be grouped in a series only with the dependencies so that series can be backported."
  Author confirmed patch 4/7 depends on patches 1/7 and 2/7 only, and agreed to send a
  separate 3-patch series for stable. Our automated review raised this as [MINOR] (confirmed).
- Jeff Johnson on same thread (per-patch comment on patch 4/7, 2026-05-20): "Does this patch
  depend upon any of the previous 3 patches in this series? Since this has a Fixes tag the
  stable team will try to backport it, so it is important to know if it has dependencies."
  Second direct confirmation from the same maintainer; author confirmed dependencies and
  agreed to split. Our [MINOR] finding on patch scope was confirmed.

Review action:
- Flag [MINOR] when a `Fixes:` patch is co-submitted in a series with feature patches that
  are NOT required prerequisites for the fix.
- Ask: "Does the Fixes: patch depend on patches N, N+1, ... in this series?" If only a
  subset of earlier patches are required, request a separate minimal series containing only
  the fix and its strict prerequisites.
- Also verify `Cc: stable@vger.kernel.org` is present on the Fixes: patch (see MEM-0004).

False-positive guards:
- Do not flag if all other patches in the series are prerequisites required for the fix to
  compile or function correctly (the entire series is one inseparable unit).
- Do not flag if the series is explicitly framed as a combined bug-fix + feature series
  where the maintainer has already acknowledged the coupling.

Confidence: high
Last updated: 2026-05-27
