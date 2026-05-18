# Plan: bug-recall evaluation harness for patchwise

## Context

We want to measure how often patchwise's `AiCodeReview` reports a bug that was actually fixed in a later kernel commit. The Linux kernel records fix→bug relationships via `Fixes: <buggy_sha>` tags, which gives us a ground-truth signal we can mine automatically.

A reference runner already exists at `../pw-tests/scripts/run_bug_commit_reviews.py`: it shells out to the `patchwise` CLI for each of 10 hardcoded buggy SHAs and dumps `aicodereview.txt`. A hand-curated `report.md` at `../pw-tests/ai_reviews/report.md` then maps individual patchwise findings to later fix commits. That manual step is what we are automating.

The new harness lives in this repo at `tests/eval/`, runs patchwise on demand, matches findings with embedding cosine similarity (no LLM judge), and emits both a markdown report and a `metrics.json`. It is gated behind `PATCHWISE_RUN_EVAL=1` because it shells Docker, calls a paid LLM, and needs a kernel tree with the buggy SHAs in history.

## Layout

```
tests/eval/
  __init__.py
  bug_commits.py        # const list of 10 buggy SHAs
  run_aicodereview.py   # subprocess wrapper around `patchwise` CLI; caches output
  fixes.py              # git-log scanning for Fixes: <bug_sha> commits + scope filter
  parse.py              # split aicodereview.txt into Issue(quoted_diff, prose) records
  embed.py              # litellm.embedding wrapper + on-disk cache keyed by (model, sha256(text))
  match.py              # cosine top-K matching of issues to fix commits
  report.py             # render report.md and metrics.json
  test_eval.py          # pytest entry point, skipif PATCHWISE_RUN_EVAL != "1"
output (generated, gitignored):
  tests/eval/output/
    ai_reviews/<bug_sha>/aicodereview.txt
    embeddings/<sha256>.npy
    report.md
    metrics.json
```

## Approach

### Invocation: subprocess, not direct API

`PatchReview.__init__` (patchwise/patch_review/patch_review.py:55-67) unconditionally builds a Docker image, initializes the shared build volume, and starts a container — `AiCodeReview` inherits this and its agent tools route through `self.docker_manager.run_command(...)`. We cannot bypass Docker, and there is no benefit to instantiating `AiCodeReview` directly over invoking the CLI.

`run_aicodereview.py` mirrors `../pw-tests/scripts/run_bug_commit_reviews.py`:
- finds the `patchwise` executable next to `sys.executable`
- runs `patchwise --reviews AiCodeReview --commits <bug_sha> --repo-path <kernel_path> --output-dir <output_dir>` per buggy commit
- caches the result; re-runs only when `force=True` or the file is missing
- streams stdout/stderr to `<output_dir>/<sha>/patchwise_run.log`

Signature: `run_aicodereview(bug_sha: str, *, kernel_path: Path, output_dir: Path, force: bool = False) -> Path`.

### Issue parsing

The aicodereview.txt format interleaves `> +`/`> -` quoted diff blocks with prose paragraphs (see `../pw-tests/ai_reviews/265280b99822.../aicodereview.txt` for the canonical pattern). Splitting on blank lines breaks issues apart.

`parse.py` groups each `> ` block with the prose that follows it until the next `> ` block. `Issue = (quoted_diff: str, prose: str)`. The single-line "No issues found." sentinel returns `[]`. Trailing pure-quote blocks with no prose are dropped.

### Fix commit discovery

`fixes.py:find_fix_commits(bug_sha, kernel_path, scope_ref)`:
- runs `git -C <kernel_path> log --all -i --grep "^Fixes: <12-char-prefix>" --format=%H`
- if `scope_ref` is set (default `patchwise-linux-next-stable`), filters via `git merge-base --is-ancestor <fix> <scope_ref>`; if the ref doesn't exist in the local tree, log a warning and skip filtering
- collapses cherry-pick duplicates by (subject, author, diff sha) — keeps first
- returns `list[FixCommit]` where `FixCommit` carries `sha, subject, body, diff_text` (unified diff truncated to 8 KB, since embeddings have token caps and the bug we care about is usually visible in the first hunks)

### Embeddings

`embed.py:embed_texts(texts, *, model)`:
- one `litellm.embedding(model=..., input=[batch])` call per ~50-text batch
- on-disk cache at `tests/eval/output/embeddings/<sha256(model+text)>.npy`; reuse if present
- default model `text-embedding-3-small`, override via `PATCHWISE_EVAL_EMBEDDING_MODEL`
- returns `np.ndarray` of shape `(n, d)`, L2-normalized so cosine = dot product

### Matching

`match.py:match_issues_to_fixes(issues, fixes, *, top_k=3)`:
- text per issue: `quoted_diff + "\n\n" + prose`
- text per fix: `subject + "\n\n" + body + "\n\n" + diff_text`
- emits `list[Match]` with `(issue_idx, fix_sha, similarity)`, top-K per issue regardless of threshold
- caller can apply `PATCHWISE_EVAL_MATCH_THRESHOLD` (default 0.70) for the binary "matched?" column in the report; the raw scores are always emitted in `metrics.json` so the threshold is calibrate-able post hoc

### Report

`report.py:generate_report(...)` writes `report.md` with these sections (mirroring `../pw-tests/ai_reviews/report.md` as much as automation permits):

1. **Bug Commit Summary** — one row per buggy commit: bug sha+subject, all fix shas referencing it, did patchwise find ≥ 1 matched issue, top match similarity.
2. **All `Fixes:` Commits** — one row per (bug, fix) pair: bug sha, fix sha+subject, best-matching patchwise issue (if any), similarity.
3. **Patchwise Issues That Were Later Fixed** — issue-level: bug sha, issue text excerpt, best fix match, similarity.
4. **Patchwise Issues Not Matched** — issues with all top-K below threshold; emit blank "Category" column for human triage (we cannot auto-classify false positives vs. real-but-unfixed).
5. **Totals** — bug commits with ≥1 match, total issues, total matched, total fixes covered.

`metrics.json` schema:
```
{
  "config": {model, threshold, top_k, scope_ref, kernel_head},
  "per_bug_commit": {
    <bug_sha>: {
      n_issues, n_issues_matched, n_fixes, n_fixes_with_match,
      matches: [{issue_idx, fix_sha, similarity}, ...]
    }
  },
  "overall": {bug_commits_with_at_least_one_match, total_issues, total_matched, total_fixes}
}
```

### pytest entry

`test_eval.py` is a single test, skipped unless `PATCHWISE_RUN_EVAL=1`:
- skip with a clear reason if the kernel tree is missing or any of the 10 SHAs aren't reachable
- skip if `docker` isn't on PATH
- orchestrates run_aicodereview → parse → fixes → embed → match → report
- asserts `report.md` and `metrics.json` were written; no quality threshold

## Configuration (env vars)

| Var | Default | Purpose |
|---|---|---|
| `PATCHWISE_RUN_EVAL` | unset | gate: must be `"1"` to run |
| `PATCHWISE_EVAL_KERNEL_PATH` | `<repo_root>/sandbox/kernel` | kernel tree |
| `PATCHWISE_EVAL_OUTPUT_DIR` | `<repo_root>/tests/eval/output` | report + cache root |
| `PATCHWISE_EVAL_SCOPE_REF` | `patchwise-linux-next-stable` | ancestor filter for fix candidates |
| `PATCHWISE_EVAL_EMBEDDING_MODEL` | `text-embedding-3-small` | passed to `litellm.embedding` |
| `PATCHWISE_EVAL_TOP_K` | `3` | top-K matches kept per issue |
| `PATCHWISE_EVAL_MATCH_THRESHOLD` | `0.70` | binary match threshold for the report |
| `PATCHWISE_EVAL_FORCE_RERUN` | unset | re-run patchwise even if `aicodereview.txt` exists |

`patchwise --model` / `--provider` get inherited from the parent shell env when shelling out — match the existing runner's behavior.

## Critical files to read/modify

- New: everything under `tests/eval/`
- Reference (read-only): `/local/mnt/workspace/DEV/pw-tests/scripts/run_bug_commit_reviews.py`, `/local/mnt/workspace/DEV/pw-tests/ai_reviews/report.md`
- Modify: `.gitignore` to exclude `tests/eval/output/`
- Reuse patterns from: `tests/ai_code_review/test_tools.py` (PATCHWISE_SANDBOX_PATH handling, kernel-tree fixture); `patchwise/patch_review/ai_review/ai_review.py` (litellm wiring style)
- No new pyproject deps required — `litellm>=1.74` already covers `litellm.embedding`; numpy is a transitive dep (verify before relying on it; if not, add `numpy` to `[project.dependencies]`).

## Verification

1. `source .venv/bin/activate`
2. Ensure `sandbox/kernel` exists and contains all 10 SHAs:
   ```
   for sha in $(python -c "from tests.eval.bug_commits import BUG_COMMITS; print('\n'.join(BUG_COMMITS))"); do
     git -C sandbox/kernel cat-file -e "$sha" || echo "MISSING $sha"
   done
   ```
3. First run (slow, populates caches):
   ```
   PATCHWISE_RUN_EVAL=1 pytest tests/eval/test_eval.py -v -s
   ```
4. Inspect `tests/eval/output/report.md` and compare row-by-row to `../pw-tests/ai_reviews/report.md` — the "Bug Commit Summary" and "All Fixes Commits" tables should structurally match; expect some divergence on the `Yes/No` column where similarity threshold disagrees with manual judgment.
5. Re-run without `PATCHWISE_EVAL_FORCE_RERUN`: should complete in seconds (everything cached).
6. Sanity-check matches: open `metrics.json`, find the entry for `e130242dc351...` (which the manual report flags as a clear match) — its top match should be `000eca5d044d...` with high similarity. If not, the embedding/parse pipeline has a bug.
7. Tweak `PATCHWISE_EVAL_MATCH_THRESHOLD` post-hoc and re-render the report (no LLM calls needed) to calibrate.

## Out of scope

- LLM-as-judge matching (decided: embeddings only).
- Auto-classifying unmatched issues as false positives vs. real-but-unfixed.
- Pass/fail quality thresholds in pytest.
- CI integration (the test is gated; wiring into CI is a follow-up).
