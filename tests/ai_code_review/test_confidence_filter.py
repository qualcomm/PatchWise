# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Unit tests for the record_finding confidence threshold (no LLM/docker/kernel
needed): the header-tag format Agent._tool_record_finding writes, and the
AiCodeReview classmethods that parse it back out and apply
MIN_FINDING_CONFIDENCE before the false-positive filter phase."""

from patchwise.patch_review.ai_agent.agent import Agent
from patchwise.patch_review.ai_review.ai_code_review import AiCodeReview

# ---------------------------------------------------------------------------
# _confidence_rank
# ---------------------------------------------------------------------------


def test_confidence_rank_orders_low_medium_high():
    assert AiCodeReview._confidence_rank("low") < AiCodeReview._confidence_rank(
        "medium"
    )
    assert AiCodeReview._confidence_rank("medium") < AiCodeReview._confidence_rank(
        "high"
    )


def test_confidence_rank_is_case_insensitive():
    assert AiCodeReview._confidence_rank("HIGH") == AiCodeReview._confidence_rank(
        "high"
    )
    assert AiCodeReview._confidence_rank("Medium") == AiCodeReview._confidence_rank(
        "medium"
    )


def test_confidence_rank_defaults_missing_or_unrecognised_to_high():
    # Ambiguous signal must never be what silently drops a finding — same
    # defensive default as _impact_is_high for a missing `impact`.
    assert AiCodeReview._confidence_rank("") == AiCodeReview._confidence_rank("high")
    assert AiCodeReview._confidence_rank("sort-of") == AiCodeReview._confidence_rank(
        "high"
    )


# ---------------------------------------------------------------------------
# _split_finding_blocks / _block_confidence
# ---------------------------------------------------------------------------


def test_split_finding_blocks_splits_on_header_lines():
    text = (
        "### [memory] drivers/x/y.c:10 (confidence: high)\n\n"
        "First finding body.\n\n"
        "### [locking] drivers/x/z.c:20 (confidence: low)\n\n"
        "Second finding body.\n\n"
    )
    blocks = AiCodeReview._split_finding_blocks(text)
    assert len(blocks) == 2
    assert blocks[0].startswith("### [memory] drivers/x/y.c:10")
    assert blocks[1].startswith("### [locking] drivers/x/z.c:20")


def test_split_finding_blocks_empty_input():
    assert AiCodeReview._split_finding_blocks("") == []
    assert AiCodeReview._split_finding_blocks("   \n  ") == []


def test_block_confidence_extracts_tag():
    block = "### drivers/x/y.c:10 (confidence: medium)\n\nSome finding text."
    assert AiCodeReview._block_confidence(block) == "medium"


def test_block_confidence_missing_tag_returns_empty():
    block = "### drivers/x/y.c:10\n\nA finding recorded with no confidence tag."
    assert AiCodeReview._block_confidence(block) == ""


# ---------------------------------------------------------------------------
# _filter_by_confidence
# ---------------------------------------------------------------------------


def _block(location: str, confidence: str, body: str = "body") -> str:
    tag = f" (confidence: {confidence})" if confidence else ""
    return f"### {location}{tag}\n\n{body}"


def test_filter_by_confidence_drops_below_threshold():
    text = "\n\n".join(
        [
            _block("a.c:1", "low"),
            _block("b.c:2", "medium"),
            _block("c.c:3", "high"),
        ]
    )
    filtered = AiCodeReview._filter_by_confidence(text, "medium")
    kept = AiCodeReview._split_finding_blocks(filtered)
    assert len(kept) == 2
    assert all("low" not in AiCodeReview._block_confidence(b) for b in kept)
    locations = [b.splitlines()[0] for b in kept]
    assert any("b.c:2" in loc for loc in locations)
    assert any("c.c:3" in loc for loc in locations)


def test_filter_by_confidence_low_threshold_keeps_everything():
    text = "\n\n".join(
        [
            _block("a.c:1", "low"),
            _block("b.c:2", "medium"),
            _block("c.c:3", "high"),
        ]
    )
    filtered = AiCodeReview._filter_by_confidence(text, "low")
    assert len(AiCodeReview._split_finding_blocks(filtered)) == 3


def test_filter_by_confidence_high_threshold_drops_low_and_medium():
    text = "\n\n".join(
        [
            _block("a.c:1", "low"),
            _block("b.c:2", "medium"),
            _block("c.c:3", "high"),
        ]
    )
    filtered = AiCodeReview._filter_by_confidence(text, "high")
    kept = AiCodeReview._split_finding_blocks(filtered)
    assert len(kept) == 1
    assert "c.c:3" in kept[0]


def test_filter_by_confidence_keeps_blocks_with_no_confidence_tag():
    # A block predating this feature (or one the model forgot to tag) must
    # never be silently dropped just because it lacks the tag.
    text = "\n\n".join(
        [
            _block("a.c:1", ""),
            _block("b.c:2", "low"),
        ]
    )
    filtered = AiCodeReview._filter_by_confidence(text, "high")
    kept = AiCodeReview._split_finding_blocks(filtered)
    assert len(kept) == 1
    assert "a.c:1" in kept[0]


def test_filter_by_confidence_empty_input():
    assert AiCodeReview._filter_by_confidence("", "medium") == ""


def test_min_finding_confidence_env_override(monkeypatch):
    review = object.__new__(AiCodeReview)
    # PatchReview.__del__ expects docker_manager.container_name; give it a
    # harmless stand-in so GC-time __del__ does not raise (this bare object
    # never goes through __init__, which is the whole point of testing this
    # method in isolation).
    review.docker_manager = type("_Stub", (), {"container_name": None})()
    monkeypatch.delenv("PATCHWISE_MIN_FINDING_CONFIDENCE", raising=False)
    assert review._min_finding_confidence() == AiCodeReview.MIN_FINDING_CONFIDENCE

    monkeypatch.setenv("PATCHWISE_MIN_FINDING_CONFIDENCE", "high")
    assert review._min_finding_confidence() == "high"

    # An invalid override falls back to the class default rather than being
    # trusted verbatim (it would otherwise rank as "high" via _confidence_rank
    # and silently keep everything, the opposite of what an operator setting
    # a stricter threshold would expect).
    monkeypatch.setenv("PATCHWISE_MIN_FINDING_CONFIDENCE", "extreme")
    assert review._min_finding_confidence() == AiCodeReview.MIN_FINDING_CONFIDENCE


# ---------------------------------------------------------------------------
# Round-trip: Agent._tool_record_finding's write format -> AiCodeReview's parser
# ---------------------------------------------------------------------------


def _bare_agent(label: str) -> Agent:
    """An Agent with no docker/kernel/LLM wiring — _tool_record_finding only
    touches self.current_label and the findings_path_for staticmethod, so
    bypassing __init__ is sufficient and avoids the heavy fixture other tests
    in this package need."""
    agent = object.__new__(Agent)
    agent.current_label = label
    return agent


def test_record_finding_write_format_round_trips_through_the_parser():
    label = "test_confidence_roundtrip"
    path = Agent.findings_path_for(label)
    path.unlink(missing_ok=True)
    try:
        agent = _bare_agent(label)
        agent._tool_record_finding(
            finding="Use-after-free: `foo` is freed on the error path then dereferenced below.",
            location="drivers/x/y.c:42",
            dimension="memory",
            confidence="high",
        )
        agent._tool_record_finding(
            finding="Possibly missing a NULL check here, but I could not confirm the caller's contract.",
            location="drivers/x/y.c:80",
            dimension="memory",
            confidence="low",
        )
        recorded = path.read_text()

        blocks = AiCodeReview._split_finding_blocks(recorded)
        assert len(blocks) == 2
        assert AiCodeReview._block_confidence(blocks[0]) == "high"
        assert AiCodeReview._block_confidence(blocks[1]) == "low"

        filtered = AiCodeReview._filter_by_confidence(recorded, "medium")
        kept = AiCodeReview._split_finding_blocks(filtered)
        assert len(kept) == 1
        assert "drivers/x/y.c:42" in kept[0]
    finally:
        path.unlink(missing_ok=True)


def test_record_finding_without_confidence_is_still_kept_by_the_filter():
    """Backward compatibility: a caller that omits confidence entirely (as
    root_cause_analysis.py's reviewer currently does) must not have its
    findings silently dropped by AiCodeReview's threshold."""
    label = "test_confidence_roundtrip_no_confidence"
    path = Agent.findings_path_for(label)
    path.unlink(missing_ok=True)
    try:
        agent = _bare_agent(label)
        agent._tool_record_finding(
            finding="A finding recorded with no confidence argument at all.",
            location="drivers/x/y.c:5",
        )
        recorded = path.read_text()
        filtered = AiCodeReview._filter_by_confidence(recorded, "high")
        assert AiCodeReview._split_finding_blocks(filtered)
    finally:
        path.unlink(missing_ok=True)
