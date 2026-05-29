# HTML Output Template (Orchestrator Reference)

This file contains the full HTML/CSS skeleton for the review output file.
The orchestrator uses this template when creating the HTML file in Step 6.1.
The subagent does NOT need this file — it writes only commit-block fragments
(defined in `core.md` Step 5b).

## HTML skeleton

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Review: <series subject></title>
  <style>
    /* ── Reset & base ── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                   "Helvetica Neue", Arial, sans-serif;
      font-size: 14px; line-height: 1.6;
      background: #f5f5f5; color: #222;
    }
    a { color: #0366d6; text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* ── Layout ── */
    .page-wrap { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }

    /* ── Header card ── */
    .review-header {
      background: #fff; border: 1px solid #d0d7de;
      border-radius: 8px; padding: 20px 24px; margin-bottom: 24px;
    }
    .review-header h1 { font-size: 1.4em; margin-bottom: 12px; }
    .review-header table { border-collapse: collapse; width: 100%; }
    .review-header td { padding: 3px 8px; vertical-align: top; }
    .review-header td:first-child { font-weight: 600; white-space: nowrap;
                                    color: #555; width: 180px; }

    /* ── Verdict banner ── */
    .verdict-banner {
      border-radius: 8px; padding: 20px 24px; margin-bottom: 24px;
      border: 2px solid;
    }
    .verdict-banner.needs-fixes  { background: #fff8f0; border-color: #e36209; }
    .verdict-banner.needs-discussion { background: #fffbdd; border-color: #b08800; }
    .verdict-banner.ready        { background: #f0fff4; border-color: #2da44e; }
    .verdict-banner.cannot-apply { background: #fff3cd; border-color: #e6b800; }
    .verdict-banner h2 { font-size: 1.2em; margin-bottom: 12px; }
    .verdict-pill {
      display: inline-block; padding: 4px 14px; border-radius: 20px;
      font-weight: 700; font-size: 1em; margin-bottom: 16px;
    }
    .verdict-pill.needs-fixes  { background: #e36209; color: #fff; }
    .verdict-pill.needs-discussion { background: #b08800; color: #fff; }
    .verdict-pill.ready        { background: #2da44e; color: #fff; }
    .verdict-pill.cannot-apply { background: #e6b800; color: #000; }
    .stats-row { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
    .stat-chip {
      padding: 4px 12px; border-radius: 6px; font-size: 0.9em; font-weight: 600;
    }
    .stat-chip.bugs     { background: #ffd7d7; color: #9e1c1c; }
    .stat-chip.concerns { background: #fff0b3; color: #7d5a00; }
    .stat-chip.minors   { background: #ddf4ff; color: #0550ae; }
    .stat-chip.commits  { background: #e8f5e9; color: #1b5e20; }

    /* ── Key findings ── */
    .findings-section { margin-top: 16px; }
    .findings-category {
      font-size: 0.75em; font-weight: 700; letter-spacing: 0.08em;
      text-transform: uppercase; color: #555;
      border-bottom: 2px solid #d0d7de; padding-bottom: 4px;
      margin: 20px 0 10px;
    }
    .finding-card {
      border-left: 4px solid; border-radius: 0 6px 6px 0;
      padding: 12px 16px; margin-bottom: 12px; background: #fff;
    }
    .finding-card.bug     { border-color: #cf222e; }
    .finding-card.concern { border-color: #e36209; }
    .finding-card.minor   { border-color: #0550ae; }
    .finding-card.nit     { border-color: #6e7781; }
    .finding-card .badge {
      display: inline-block; padding: 1px 8px; border-radius: 4px;
      font-size: 0.78em; font-weight: 700; margin-right: 6px;
    }
    .badge.bug     { background: #cf222e; color: #fff; }
    .badge.concern { background: #e36209; color: #fff; }
    .badge.minor   { background: #0550ae; color: #fff; }
    .badge.nit     { background: #6e7781; color: #fff; }
    .finding-card .patch-subject {
      font-size: 0.8em; color: #555; font-style: italic; margin-bottom: 4px;
    }
    .finding-card .title { font-weight: 600; }
    .finding-card .body  { margin-top: 8px; color: #333; }
    .finding-card .file-ref {
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 0.85em; color: #555; margin-top: 6px;
    }
    .finding-card .suggestion {
      margin-top: 8px; padding: 8px 12px;
      background: #f6f8fa; border-radius: 4px;
      font-size: 0.9em; color: #333;
    }
    .finding-card .suggestion::before {
      content: "Suggestion: "; font-weight: 600;
    }

    /* ── Section cards ── */
    .section-card {
      background: #fff; border: 1px solid #d0d7de;
      border-radius: 8px; padding: 20px 24px; margin-bottom: 24px;
    }
    .section-card h2 {
      font-size: 1.1em; margin-bottom: 16px;
      padding-bottom: 8px; border-bottom: 1px solid #d0d7de;
    }
    .section-card h3 { font-size: 1em; margin: 16px 0 8px; color: #333; }
    .section-card h4 { font-size: 0.95em; margin: 12px 0 6px; color: #444; }

    /* ── Test results table ── */
    .test-table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
    .test-table th, .test-table td {
      padding: 8px 12px; text-align: left;
      border: 1px solid #d0d7de;
    }
    .test-table th { background: #f6f8fa; font-weight: 600; }
    .test-table tr:nth-child(even) { background: #fafafa; }
    .result-pass { color: #2da44e; font-weight: 700; }
    .result-fail { color: #cf222e; font-weight: 700; }
    .result-warn { color: #e36209; font-weight: 700; }
    .result-skip { color: #6e7781; font-weight: 700; }
    .result-info { color: #0550ae; font-weight: 700; }

    /* ── Commit blocks ── */
    .commit-block {
      background: #fff; border: 1px solid #d0d7de;
      border-radius: 8px; margin-bottom: 24px; overflow: hidden;
    }
    .commit-header {
      background: #f6f8fa; padding: 12px 20px;
      border-bottom: 1px solid #d0d7de;
      display: flex; align-items: baseline; gap: 10px;
    }
    .commit-hash {
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 0.85em; color: #0550ae; font-weight: 600;
    }
    .commit-subject { font-weight: 600; font-size: 1em; }
    .commit-body { padding: 16px 20px; }
    .commit-body h3 {
      font-size: 1.05em; margin: 20px 0 10px; padding: 6px 0;
      border-bottom: 2px solid #d0d7de; color: #24292f;
    }
    .commit-summary { color: #555; margin-bottom: 16px; font-style: italic; }

    /* ── Code / pre ── */
    pre, code {
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 0.85em;
    }
    pre {
      background: #f6f8fa; border: 1px solid #d0d7de;
      border-radius: 6px; padding: 12px 16px;
      overflow-x: auto; white-space: pre-wrap; word-break: break-word;
      margin: 8px 0;
    }
    code { background: #f0f0f0; padding: 1px 5px; border-radius: 3px; }

    /* ── Lists ── */
    ul, ol { padding-left: 20px; margin: 8px 0; }
    li { margin-bottom: 4px; }

    /* ── Positive notes ── */
    .positive-note {
      background: #f0fff4; border-left: 4px solid #2da44e;
      border-radius: 0 6px 6px 0; padding: 10px 14px; margin-bottom: 8px;
      font-size: 0.9em;
    }
    .preexisting-note {
      background: #fff8f0; border-left: 4px solid #d29922;
      border-radius: 0 6px 6px 0; padding: 10px 14px; margin-bottom: 8px;
      font-size: 0.9em; color: #333;
    }
    .preexisting-flag {
      display: inline-block; padding: 1px 8px; border-radius: 999px;
      font-size: 0.78em; font-weight: 700; margin-right: 8px;
      background: #d29922; color: #fff;
    }

    /* ── Footer ── */
    .page-footer {
      text-align: center; color: #888; font-size: 0.8em;
      margin-top: 32px; padding-top: 16px;
      border-top: 1px solid #d0d7de;
    }
  </style>
</head>
<body>
<div class="page-wrap">

  <!-- ═══ HEADER CARD ═══ -->
  <div class="review-header">
    <h1>Review: <series subject or "Last N commits in &lt;repo&gt;" or "File &lt;path&gt; in &lt;repo&gt;"></h1>
    <table>
      <tr><td>Date</td><td>YYYY-MM-DD</td></tr>
      <tr><td>Message-ID</td><td><code>&lt;message-id&gt;</code></td></tr>
      <tr><td>lore.kernel.org</td>
          <td><a href="https://lore.kernel.org/r/<message-id>">https://lore.kernel.org/r/&lt;message-id&gt;</a></td></tr>
      <tr><td>Dependencies</td><td>
        <!-- If none stated: -->
        None stated
        <!-- If present and satisfied: -->
        <!-- <code>&lt;identifier&gt;</code> — present in base commit -->
        <!-- If missing: -->
        <!-- <strong style="color:#cf222e">MISSING: &lt;identifier&gt;</strong>
             — findings may be affected; see verdict banner -->
      </td></tr>
    </table>
  </div>

  <!-- ═══ VERDICT BANNER ═══ -->
  <!-- Use class "needs-fixes", "needs-discussion", "ready", or
       "cannot-apply" on both .verdict-banner and .verdict-pill to match
       the recommendation. -->
  <div class="verdict-banner needs-fixes">
    <h2>Overall Summary — Verdict at a Glance</h2>
    <div class="verdict-pill needs-fixes">NEEDS FIXES</div>
    <div class="stats-row">
      <span class="stat-chip commits">N commits reviewed</span>
      <!-- Mode C: use "1 file reviewed" instead of "N commits reviewed" -->
      <span class="stat-chip bugs">N bugs</span>
      <span class="stat-chip concerns">N concerns</span>
      <span class="stat-chip minors">N minor issues</span>
    </div>

    <!-- Key findings grouped by category -->
    <div class="findings-section">

      <div class="findings-category">PATCH SCOPE VIOLATIONS</div>

      <div class="finding-card bug" data-attribution="introduced">
        <span class="badge bug">[BUG]</span>
        <span class="title">&lt;patch subject&gt; — &lt;short title&gt;</span>
        <div class="patch-subject">Patch: &lt;NN/TT&gt; &lt;full commit subject line&gt;</div>
        <div class="body">One-sentence summary; <a href="#patch-N-finding-K">see Patch N</a>.</div>
        <div class="file-ref">See linked per-commit finding</div>
        <div class="suggestion">See linked per-commit finding.</div>
      </div>

      <div class="findings-category">CORRECTNESS ISSUES</div>

      <div class="finding-card bug" data-attribution="introduced">
        <span class="badge bug">[BUG]</span>
        <span class="title">&lt;patch subject&gt; — &lt;short title&gt;</span>
        <div class="patch-subject">Patch: &lt;NN/TT&gt; &lt;full commit subject line&gt;</div>
        <div class="body">One-sentence summary; <a href="#patch-N-finding-K">see Patch N</a>.</div>
        <div class="file-ref">See linked per-commit finding</div>
        <div class="suggestion">See linked per-commit finding.</div>
      </div>

      <div class="findings-category">STYLE / MINOR</div>

      <div class="finding-card minor" data-attribution="introduced">
        <span class="badge minor">[MINOR]</span>
        <span class="title">&lt;patch subject&gt; — &lt;short title&gt;</span>
        <div class="patch-subject">Patch: &lt;NN/TT&gt; &lt;full commit subject line&gt;</div>
        <div class="body">One-sentence summary; <a href="#patch-N-finding-K">see Patch N</a>.</div>
        <div class="file-ref">See linked per-commit finding</div>
        <div class="suggestion">See linked per-commit finding.</div>
      </div>

    </div><!-- /findings-section -->
  </div><!-- /verdict-banner -->

  <!-- Apply-failure variant (AUTHORITATIVE): this is the single source of
       truth for CANNOT APPLY reports. Other refs (e.g. startup-workflow.md
       Mode B git-am failure) must point here rather than re-describe the
       structure. Replace the normal verdict-banner contents with a diagnostic
       summary, keep the same outer page structure, and omit per-commit
       blocks. -->
  <!--
  <div class="verdict-banner cannot-apply">
    <h2>Overall Summary — Verdict at a Glance</h2>
    <div class="verdict-pill cannot-apply">CANNOT APPLY</div>
    <div class="findings-section">
      <div class="findings-category">APPLY FAILURE</div>
      <div class="finding-card bug" data-attribution="introduced">
        <span class="badge bug">[BUG]</span>
        <span class="title">Patch series could not be applied for review</span>
        <div class="body">Summarize the exact git-am failure, the conflicting file/hunk, and whether a missing dependency or unrelated upstream drift appears to be responsible.</div>
        <div class="file-ref">File: &lt;path&gt;, line ~&lt;line&gt; (or failing hunk reference)</div>
        <div class="suggestion">Rebase the series on top of the current tree before resubmitting for review.</div>
      </div>
    </div>
  </div>
  -->

  <!-- ═══ TEST RESULTS ═══ -->
  <div class="section-card">
    <h2>Test Results</h2>
    <table class="test-table">
      <thead>
        <tr><th>Test</th><th>Result</th><th>Notes</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>checkpatch</td>
          <td><span class="result-pass">PASS</span></td>
          <td>0 errors, 2 warnings (see below)</td>
        </tr>
        <tr>
          <td>Build (W=1)</td>
          <td><span class="result-pass">PASS</span></td>
          <td>No new errors or warnings</td>
        </tr>
        <tr>
          <td>dt_binding_check</td>
          <td><span class="result-skip">SKIP</span></td>
          <td>No .yaml files changed</td>
        </tr>
        <tr>
          <td>sparse</td>
          <td><span class="result-skip">SKIP</span></td>
          <td>sparse not available</td>
        </tr>
        <tr>
          <td>get_maintainer</td>
          <td><span class="result-info">INFO</span></td>
          <td>To/Cc list (see below)</td>
        </tr>
      </tbody>
    </table>
    <h3>checkpatch findings</h3>
    <pre>...verbatim output...</pre>
  </div>

  <!-- ═══ TEST RESULTS — FAIL Notes-cell contract (mandatory) ═══
       When a row is FAIL, the Notes cell MUST carry concrete evidence so the
       saved report is self-contained.  Two shapes are accepted:

       (a) Quote a compiler/checker diagnostic directly in the cell:
             <td>error: implicit declaration of 'foo' at drivers/foo/bar.c:42</td>
             <td>WARNING: line over 100 characters at amdgpu_dm_color.c:1632</td>

       (b) Reference the per-block details section that explains it:
             <td>Build break in patch 3 — see <a href="#patch-3-finding-1">Patch 3</a></td>
             <td>Per-patch FAIL — see <code>Build / Test Notes</code> in Patch 1</td>

       Bare counts like "Per-patch W=1 build artifact failure(s): patch 1" are
       NOT acceptable.  The validator's `test_results_fail_evidence` check
       rejects reports whose FAIL Notes carry neither (a) nor (b).

       If a per-block Build/Test Notes section explains the FAIL as a benign
       Kconfig syncconfig restart (i.e. the build actually succeeded), change
       the row from FAIL to PASS and put the syncconfig explanation in the
       Notes cell — `test_results_build_notes_consistency` rejects the
       contradiction. -->

  <!-- ═══ PER-COMMIT REVIEWS ═══ -->
  <!-- Repeat one .commit-block per patch/commit -->
  <!-- Each commit block is assembled from tmp/patch_<N>_block.html files -->

  <!-- ═══ FOOTER ═══ -->
  <div class="page-footer">
    Generated by AI agent (qgenie) &mdash; <em>YYYY-MM-DD</em>
  </div>

</div><!-- /page-wrap -->
</body>
</html>
```

## HTML Conformance Rules

- Use the document order shown in the skeleton: head/CSS, header card, verdict
  banner, test results, per-commit blocks, footer.
- Apply-failure reports still use the same skeleton, but the verdict class/text
  are `cannot-apply` / `CANNOT APPLY`, the verdict banner contains the
  diagnostic finding(s), and the per-commit block section is omitted.
- Verdict-banner finding cards are concise anchor summaries.  Full analysis,
  file references, suggestions, code snippets, and Gate traces live only in the
  canonical per-commit `.finding-card` with id `patch-<N>-finding-<K>`.
- Finding cards should carry `data-attribution="introduced"` for defects
  created by the current patch or `data-attribution="newly_exposed"` for
  pre-existing harmful paths made newly reachable, required, user-visible, or
  materially worse by the patch.  Never render a pre-existing-only issue as a
  finding card; use `.preexisting-note` instead.
- Do not render self-negating, process-only, or informational notes as
  `.finding-card`.  If the note says the code is correct/safe/acceptable/not a
  defect, or only "for completeness" / "worth verifying", keep it as plain
  prose in `Positive Notes` or another non-counted patch-local note instead.
- If you need to mention a real issue in unchanged surrounding code that is
  explicitly not introduced by the patch, put it only in the relevant
  commit-block under an optional `Pre-existing Issues (non-blocking)` heading
  using `.preexisting-note`.  These notes are context/follow-up only: they do
  not belong in the verdict banner, stat-chip counts, or `.finding-card`
  totals.
- Use only the CSS classes defined in this template; do not add custom CSS or
  alternate class names.
- In any `.finding-card`, keep `.body`, `.file-ref`, and `.suggestion` to
  prose/inline HTML only.  Never nest `<pre>`, lists, tables, headings, `<p>`,
  or another `<div>` inside those slots; put code snippets in sibling `<pre>`
  blocks immediately after `.suggestion` or after the relevant prose slot.
- Keep the header table limited to `Date`, `Message-ID`, `lore.kernel.org`,
  and `Dependencies`. Do not add non-template rows such as `Reviewer`, `Mode`,
  `Commits / Patches`, `Branch`, `Author`, `Dates`, `Reviewed by`,
  `Maintainers`, `Mailing lists`, or `Base`.
- The footer text is fixed: `Generated by AI agent (qgenie) &mdash;
  <em>YYYY-MM-DD</em>`. Do not wrap it in an extra `<p>` element or substitute
  another generator string.


### Finding-card render-safe pattern

```html
<div class="finding-card concern" id="patch-N-finding-K" data-attribution="introduced">
  <span class="badge concern">[CONCERN]</span>
  <span class="title">Category: short summary.</span>
  <div class="patch-subject">Patch: N/T full commit subject line</div>
  <div class="body">Detailed analysis. (Gate 1: [sub-rule: none] reachable path; Gate 2: concrete harm; Gate 3: severity justification.)</div>
  <div class="file-ref">File: drivers/foo/bar.c, line ~123</div>
  <div class="suggestion">Short prose fix description only.</div>
  <pre>optional code snippet as a sibling, never nested in .body/.suggestion</pre>
</div>
```

### Optional pre-existing note pattern

```html
<h3>Pre-existing Issues (non-blocking)</h3>
<div class="preexisting-note">
  <span class="preexisting-flag">Pre-existing</span>
  Runtime PM imbalance in unchanged teardown path at
  <code>drivers/example.c</code>, line ~81. Not introduced by this patch;
  mention only as follow-up context.
</div>
```

## CSS Class Mapping Reference

### Severity-to-CSS-class mapping

| Severity tag | CSS class on `.finding-card` and `.badge` |
|---|---|
| `[BUG]`     | `bug`     |
| `[CONCERN]` | `concern` |
| `[MINOR]`   | `minor`   |
| `[NIT]`     | `nit`     |

### Verdict-to-CSS-class mapping

| Recommendation      | CSS class on `.verdict-banner` and `.verdict-pill` |
|---|---|
| READY TO APPLY      | `ready`            |
| NEEDS FIXES         | `needs-fixes`      |
| NEEDS DISCUSSION    | `needs-discussion` |
| CANNOT APPLY        | `cannot-apply`     |

### Result-to-CSS-class mapping (test table)

| Result | CSS class on `<span>` |
|---|---|
| PASS   | `result-pass` |
| FAIL   | `result-fail` |
| WARN   | `result-warn` |
| SKIP   | `result-skip` |
| INFO   | `result-info` |
