# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Unit tests for the review-cleanup render/collapse logic (no LLM/docker/git).

`_render_inline_review`, `_is_diff_marker`, `_diff_start_line`, and `_number_lines`
are pure functions of `self.commit_message` / `self.diff` (plus their arguments),
so we drive them against an instance built with `__new__` — no Agent, no docker,
no git — and assert on the rendered text one frame at a time."""

import types

from patchwise.patch_review.ai_review.ai_code_review import AiCodeReview


def _review(commit_message: str, diff: str) -> AiCodeReview:
    """An AiCodeReview shell with just the two attributes the renderer reads.

    `__new__` skips __init__/setup (which need a repo + docker), which is all the
    render path touches — it reads only self.commit_message and self.diff. A stub
    docker_manager is attached so PatchReview.__del__ (which checks
    docker_manager.container_name) is a harmless no-op at teardown."""
    obj = AiCodeReview.__new__(AiCodeReview)
    obj.commit_message = commit_message
    obj.diff = diff
    obj.docker_manager = types.SimpleNamespace(container_name="__test_shell__")
    return obj


SAMPLE_DIFF = "\n".join(
    [
        "diff --git a/d.c b/d.c",
        "index 111..222 100644",
        "--- a/d.c",
        "+++ b/d.c",
        "@@ -10,6 +10,9 @@ static int foo(void)",
        " 	int ret;",
        " 	buf = kmalloc(sz, GFP_KERNEL);",
        " 	if (!buf)",
        "+		return -ENOMEM;",
        "+	ret = bar(buf);",
        "+	if (ret)",
        "+		return ret;",
        " 	return 0;",
        "@@ -50,3 +53,4 @@ static void baz(void)",
        " 	unrelated();",
        " 	more_unrelated();",
        " 	stuff();",
    ]
)


# ---- _valid_cleanup_findings ----------------------------------------------

def test_valid_cleanup_findings_accepts_well_formed_list():
    assert AiCodeReview._valid_cleanup_findings(
        [{"finding": "leak", "start_line": 1, "end_line": 2}]
    )
    assert AiCodeReview._valid_cleanup_findings(
        [
            {"finding": "a", "start_line": 3, "end_line": 3},
            {"finding": "b", "start_line": 1, "end_line": 9},
        ]
    )


def test_valid_cleanup_findings_rejects_bad_shapes():
    assert not AiCodeReview._valid_cleanup_findings(None)      # not parseable
    assert not AiCodeReview._valid_cleanup_findings({"finding": "x"})  # dict, not list
    assert not AiCodeReview._valid_cleanup_findings([])        # empty -> re-prompt
    assert not AiCodeReview._valid_cleanup_findings(["not a dict"])
    # blank finding
    assert not AiCodeReview._valid_cleanup_findings(
        [{"finding": "  ", "start_line": 1, "end_line": 1}]
    )
    # missing line numbers -> re-prompt (renderer no longer defaults them)
    assert not AiCodeReview._valid_cleanup_findings([{"finding": "x"}])
    # non-integer line numbers
    assert not AiCodeReview._valid_cleanup_findings(
        [{"finding": "x", "start_line": "1", "end_line": 2}]
    )
    assert not AiCodeReview._valid_cleanup_findings(
        [{"finding": "x", "start_line": 1, "end_line": None}]
    )
    # bool is an int subclass but never a line number
    assert not AiCodeReview._valid_cleanup_findings(
        [{"finding": "x", "start_line": True, "end_line": 2}]
    )
    # one bad element fails the whole batch
    assert not AiCodeReview._valid_cleanup_findings(
        [
            {"finding": "ok", "start_line": 1, "end_line": 1},
            {"note": "no finding key"},
        ]
    )


# ---- _number_lines --------------------------------------------------------

def test_number_lines_is_one_based_and_maps_to_split_index():
    text = "alpha\nbeta\ngamma"
    numbered = AiCodeReview._number_lines(text)
    assert numbered.splitlines()[0] == "1: alpha"
    assert numbered.splitlines()[2] == "3: gamma"
    # Line N of the numbered patch == text.split("\n")[N-1] — the contract the
    # renderer relies on to reconstruct raw lines from commit_message + diff.
    assert text.split("\n")[2] == "gamma"


# ---- _diff_start_line -----------------------------------------------------

def test_diff_start_line_points_at_first_diff_line():
    cm = "subject line\n\nbody one\nbody two"  # 4 lines
    raw = f"{cm}\n\n{SAMPLE_DIFF}".split("\n")
    ds = AiCodeReview._diff_start_line(cm)
    # 1-based: everything before ds is commit message + the blank separator.
    assert raw[ds - 1] == "diff --git a/d.c b/d.c"
    assert raw[ds - 2] == ""  # the blank separator line


def test_diff_start_line_single_line_commit_message():
    cm = "one line only"
    raw = f"{cm}\n\n{SAMPLE_DIFF}".split("\n")
    ds = AiCodeReview._diff_start_line(cm)
    assert raw[ds - 1] == "diff --git a/d.c b/d.c"


# ---- _is_diff_marker ------------------------------------------------------

def test_is_diff_marker_only_file_and_hunk_headers():
    # Only the two lines that locate a finding are markers.
    assert AiCodeReview._is_diff_marker("diff --git a/f.c b/f.c")
    assert AiCodeReview._is_diff_marker("@@ -1,2 +1,3 @@")
    assert AiCodeReview._is_diff_marker("@@ -1 +1 @@ static int foo(void)")


def test_is_diff_marker_other_headers_are_not_markers():
    # Every other header line is noise for an inline review and collapses away.
    for line in [
        "index 111..222 100644",
        "--- a/f.c",
        "+++ b/f.c",
        "new file mode 100644",
        "deleted file mode 100644",
        "rename from a",
        "rename to b",
        "similarity index 95%",
        "Binary files a and b differ",
        r"\ No newline at end of file",
    ]:
        assert not AiCodeReview._is_diff_marker(line), line


def test_is_diff_marker_plain_code_is_not_a_marker():
    assert not AiCodeReview._is_diff_marker(" 	int ret;")
    assert not AiCodeReview._is_diff_marker("+	ret = bar(buf);")
    assert not AiCodeReview._is_diff_marker("-	old_line();")


def test_is_diff_marker_body_line_that_reads_like_a_header():
    # A hunk-body line whose text happens to start with `diff --git`/`@@` still
    # carries its diff prefix (`+`/`-`/space), so column-0 matching must not
    # mistake it for a real header.
    for line in [
        "+@@ not a hunk header",
        "-diff --git in a comment",
        " diff --git example in context",
        "+@@ -1 +1 @@ style string",
    ]:
        assert not AiCodeReview._is_diff_marker(line), line
    # The real headers, at column 0, are still markers.
    assert AiCodeReview._is_diff_marker("diff --git a/x b/x")
    assert AiCodeReview._is_diff_marker("@@ -1,1 +1,1 @@")


# ---- _render_inline_review ------------------------------------------------

def _numbered_lookup(review: AiCodeReview):
    """Map raw source line -> 1-based number, to pick anchor line numbers the way
    the model would (off the numbered patch)."""
    numbered = AiCodeReview._number_lines(
        f"{review.commit_message}\n\n{review.diff}"
    )
    return {
        line.split(": ", 1)[1]: int(line.split(": ", 1)[0])
        for line in numbered.split("\n")
        if ": " in line
    }


def test_render_keeps_commit_message_and_markers_collapses_rest():
    cm = "mtd: fix leak\n\nFree the buffer on the error path."
    review = _review(cm, SAMPLE_DIFF)
    lookup = _numbered_lookup(review)
    anchor = lookup["+		return ret;"]
    out = review._render_inline_review(
        [{"finding": "buf leaks: add kfree(buf) before return ret.",
          "start_line": anchor - 2, "end_line": anchor}]
    )

    # Commit message is present in full (never collapsed).
    assert "> mtd: fix leak" in out
    assert "> Free the buffer on the error path." in out
    # The file header and the hunk that CONTAINS the finding are kept.
    assert "> diff --git a/d.c b/d.c" in out
    assert "> @@ -10,6 +10,9 @@ static int foo(void)" in out
    # The finding is rendered after its end_line anchor.
    assert "> +		return ret;" in out
    assert "buf leaks: add kfree(buf) before return ret." in out
    # Short unrelated runs (<= _MAX_COLLAPSE_GAP lines) are cheap to show, so
    # they render verbatim rather than collapsing to a placeholder. In this
    # small diff no gap is long enough to be hidden.
    assert "[ ... ]" not in out
    assert ">  	int ret;" in out
    # The second hunk has no finding, so its header collapses too (not just its
    # body): markers without findings do not survive.
    assert "> @@ -50,3 +53,4 @@ static void baz(void)" not in out
    assert "> 	unrelated();" not in out


def test_render_finding_lands_after_its_end_line():
    cm = "subj\n\nbody"
    review = _review(cm, SAMPLE_DIFF)
    lookup = _numbered_lookup(review)
    anchor = lookup["+	ret = bar(buf);"]
    out = review._render_inline_review(
        [{"finding": "MYFINDING", "start_line": anchor, "end_line": anchor}]
    ).split("\n")
    quoted = "> +	ret = bar(buf);"
    qi = out.index(quoted)
    # Finding sits immediately after the anchor line (blank line then text).
    assert out[qi + 1] == ""
    assert out[qi + 2].strip() == "MYFINDING"


def test_render_empty_findings_collapses_entire_diff():
    cm = "subj\n\nbody line"
    review = _review(cm, SAMPLE_DIFF)
    out = review._render_inline_review([])
    # Commit message survives; with no findings, no diff marker is kept.
    assert "> subj" in out
    assert "> diff --git a/d.c b/d.c" not in out
    assert "> @@ -10,6 +10,9 @@ static int foo(void)" not in out
    # The whole diff body is a single collapse run reaching the end, so it emits
    # no placeholder at all — nothing survives past the commit message.
    assert "[ ... ]" not in out
    # No code body lines remain either.
    assert "return -ENOMEM" not in out


def test_render_keeps_only_the_file_block_with_a_finding():
    cm = "s\n\nb"
    two_files = SAMPLE_DIFF + "\n" + "\n".join(
        [
            "diff --git a/other.c b/other.c",
            "index aaa..bbb 100644",
            "--- a/other.c",
            "+++ b/other.c",
            "@@ -1,2 +1,3 @@ void other(void)",
            " 	keep_calm();",
            "+	carry_on();",
            " 	done();",
        ]
    )
    review = _review(cm, two_files)
    lookup = _numbered_lookup(review)
    anchor = lookup["+	ret = bar(buf);"]  # a finding in the FIRST file only
    out = review._render_inline_review(
        [{"finding": "ONLY_FIRST", "start_line": anchor, "end_line": anchor}]
    )
    # First file's header is kept (it has a finding); second file's is not.
    assert "> diff --git a/d.c b/d.c" in out
    assert "> diff --git a/other.c b/other.c" not in out
    assert "> +	carry_on();" not in out


def test_render_merges_adjacent_ranges_into_one_span():
    cm = "s\n\nb"
    review = _review(cm, SAMPLE_DIFF)
    lookup = _numbered_lookup(review)
    a = lookup["+		return -ENOMEM;"]
    b = lookup["+	ret = bar(buf);"]  # the very next line -> ranges are adjacent
    assert b == a + 1
    # Two single-line findings on consecutive lines: adjacency (lo <= hi + 1)
    # merges them into one span with no placeholder splitting the two lines.
    out = review._render_inline_review(
        [
            {"finding": "F1", "start_line": a, "end_line": a},
            {"finding": "F2", "start_line": b, "end_line": b},
        ]
    )
    lines = out.split("\n")
    ia = lines.index("> +		return -ENOMEM;")
    ib = lines.index("> +	ret = bar(buf);")
    # No "[ ... ]" placeholder appears between the two adjacent kept lines.
    assert not any(x.strip() == "[ ... ]" for x in lines[ia:ib])


def test_render_multiline_range_keeps_whole_span():
    cm = "s\n\nb"
    review = _review(cm, SAMPLE_DIFF)
    lookup = _numbered_lookup(review)
    lo = lookup["+		return -ENOMEM;"]
    hi = lookup["+		return ret;"]
    # A single finding spanning the whole added block keeps every line in it.
    out = review._render_inline_review(
        [{"finding": "SPAN", "start_line": lo, "end_line": hi}]
    )
    for src in ["+		return -ENOMEM;", "+	ret = bar(buf);",
                "+	if (ret)", "+		return ret;"]:
        assert f"> {src}" in out


def test_render_clamps_and_swaps_bad_ranges():
    cm = "s\n\nb"
    review = _review(cm, SAMPLE_DIFF)
    # Range hygiene is the renderer's job (the validator guarantees the entries
    # are dicts with a non-empty finding and integer line numbers, but not that
    # those integers are in range or ordered): out-of-range and reversed spans
    # must clamp/swap, not raise.
    out = review._render_inline_review(
        [
            {"finding": "OOR", "start_line": 9999, "end_line": 10000},
            {"finding": "REV", "start_line": 12, "end_line": 8},
        ]
    )
    assert "OOR" in out
    assert "REV" in out


def test_render_no_trailing_placeholder_after_last_finding():
    # A finding in the FIRST hunk leaves the whole second hunk collapsed at the
    # tail. That trailing collapse run must emit no "[ ... ]" — it just ends.
    cm = "subj\n\nbody"
    review = _review(cm, SAMPLE_DIFF)
    lookup = _numbered_lookup(review)
    anchor = lookup["+	ret = bar(buf);"]
    out = review._render_inline_review(
        [{"finding": "LAST", "start_line": anchor, "end_line": anchor}]
    )
    # The finding is the last meaningful content; nothing collapses after it.
    assert out.rstrip().endswith("LAST")
    assert "[ ... ]" not in out.split("LAST", 1)[1]


def test_render_shared_end_line_lists_findings_in_order():
    cm = "s\n\nb"
    review = _review(cm, SAMPLE_DIFF)
    lookup = _numbered_lookup(review)
    anchor = lookup["+		return ret;"]
    out = review._render_inline_review(
        [
            {"finding": "FIRST", "start_line": anchor, "end_line": anchor},
            {"finding": "SECOND", "start_line": anchor, "end_line": anchor},
        ]
    )
    assert out.index("FIRST") < out.index("SECOND")


def _diff_with_gap(n_gap: int) -> str:
    """A single-hunk diff with a finding anchor, then `n_gap` unrelated context
    lines, then a final kept marker-free line. The gap sits between two kept
    regions so it is an interior run (eligible for collapse), not a discarded
    tail."""
    body = [f" 	filler_{k}();" for k in range(n_gap)]
    return "\n".join(
        [
            "diff --git a/g.c b/g.c",
            "index 111..222 100644",
            "--- a/g.c",
            "+++ b/g.c",
            f"@@ -1,{n_gap + 2} +1,{n_gap + 3} @@ void g(void)",
            "+	target();",
            *body,
            "+	tail_target();",
        ]
    )


def test_render_collapses_gap_longer_than_threshold():
    # An interior run of 11 lines (> _MAX_COLLAPSE_GAP) sits between two findings
    # and must collapse to a single placeholder.
    cm = "s\n\nb"
    diff = _diff_with_gap(11)
    review = _review(cm, diff)
    lookup = _numbered_lookup(review)
    lo = lookup["+	target();"]
    hi = lookup["+	tail_target();"]
    out = review._render_inline_review(
        [
            {"finding": "TOP", "start_line": lo, "end_line": lo},
            {"finding": "BOT", "start_line": hi, "end_line": hi},
        ]
    )
    assert "[ ... ]" in out
    # None of the collapsed filler lines survive.
    assert ">  	filler_0();" not in out
    assert ">  	filler_10();" not in out


def test_render_keeps_gap_at_threshold_verbatim():
    # An interior run of exactly _MAX_COLLAPSE_GAP (10) lines is short enough to
    # render verbatim — no placeholder, every filler line kept.
    cm = "s\n\nb"
    diff = _diff_with_gap(10)
    review = _review(cm, diff)
    lookup = _numbered_lookup(review)
    lo = lookup["+	target();"]
    hi = lookup["+	tail_target();"]
    out = review._render_inline_review(
        [
            {"finding": "TOP", "start_line": lo, "end_line": lo},
            {"finding": "BOT", "start_line": hi, "end_line": hi},
        ]
    )
    assert "[ ... ]" not in out
    assert ">  	filler_0();" in out
    assert ">  	filler_9();" in out
