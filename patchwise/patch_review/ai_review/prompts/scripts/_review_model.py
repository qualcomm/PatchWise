#!/usr/bin/env python3
"""Data model and HTML parser for the review-commits structural validator.

Contains: FindingCard, CommitBlock, Report, ReviewParser, _CardScopedParser,
parse_report, parse_block_fragment.  No other review logic lives here.
Imported by _review_checks.py and validate_review.py.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

SUB_RULE_TRACE_RE = re.compile(r"(?:Gate 1:|Reachability:)\s*\[sub-rule:\s*[^\]\n]+\]")
RESOURCE_LEAK_EXCEPTION_RE = re.compile(
    r"Always-BUG exception:\s*[^;)]*(?:leak|reference|refcount|"
    r"kref|kobject|of node|device ref|file descriptor|fd leak|"
    r"memory leak|irq leak|dma leak)",
    re.IGNORECASE,
)
# Resource-leak always-BUG findings must state the object-lifetime determination
# that decides whether the leak shortcut applies (bounded vs static/unbounded).
# Non-leak always-BUG classes, such as sleeping-in-atomic and copy_*_user, use
# the normal scope/category text but do not need an object-lifetime result.
OBJECT_LIFETIME_RE = re.compile(r"object-lifetime check:\s*[A-Za-z]", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Minimal DOM extracted from the report.  We only model what we need: the
# verdict banner, each commit-block, and each finding-card inside them.
# ---------------------------------------------------------------------------


class FindingCard:
    __slots__ = ("severity", "title", "body", "file_ref", "suggestion",
                 "anchor_id", "anchor_targets", "attribution", "container",
                 "block_index", "render_violations")

    def __init__(self, container: str, block_index: int) -> None:
        self.severity: str = ""
        self.title: str = ""
        self.body: str = ""
        self.file_ref: str = ""
        self.suggestion: str = ""
        self.anchor_id: str = ""
        self.anchor_targets: list[str] = []
        self.attribution: str = ""
        self.container: str = container          # "banner" or "block"
        self.block_index: int = block_index      # banner = -1
        self.render_violations: list[str] = []


class CommitBlock:
    __slots__ = ("index", "subject", "headers", "step_record",
                 "findings", "raw_html")

    def __init__(self, index: int) -> None:
        self.index: int = index                  # 0-based commit-block index
        self.subject: str = ""
        self.headers: list[str] = []             # ordered <h3> texts
        self.step_record: str = ""               # full STEP_COMPLETION_RECORD body
        self.findings: list[FindingCard] = []
        self.raw_html: str = ""


class Report:
    __slots__ = ("verdict_banner", "stat_chips", "blocks", "verdict", "raw_html")

    def __init__(self) -> None:
        self.verdict_banner: list[FindingCard] = []
        self.stat_chips: dict[str, int] = {}     # "bugs" / "concerns" / "minors" / "nits"
        self.blocks: list[CommitBlock] = []
        self.verdict: str = ""
        # Full unparsed HTML of the report; used by checks that need to scan
        # report-level structure (e.g. the Test Results table) outside of the
        # commit-block scope.  Populated by parse_report; remains "" for
        # block-fragment parses where there is no enclosing report.
        self.raw_html: str = ""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


_SEVERITY_FROM_CLASS = {
    "bug": "BUG",
    "concern": "CONCERN",
    "minor": "MINOR",
    "nit": "NIT",
}

_STAT_CHIP_KEYS = {"bugs", "concerns", "minors", "nits"}
_FINDING_TEXT_SLOTS = {"body", "file_ref", "suggestion"}
_NESTED_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "div",
    "dl",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
}
_RUNTIME_CONFIG_SCHEMA = "patch-review.runtime-config.v1"
_REVIEW_PACKET_MODES = {"packet"}
_DEFAULT_REVIEW_PACKET_MODE = "packet"


def _runtime_override_constants() -> tuple[str, str]:
    """Return (sparse_disabled_marker, sparse_disabled_summary_note).

    Single source of truth is refs/review-constants.json (validated against the
    server defaults by validate_review_constants.py).  Fall back to the known
    literals if the file is unreadable so the validator still works standalone.
    """
    marker = "(sparse disabled by config)"
    note = "disabled by config"
    constants_path = Path(__file__).resolve().parents[1] / "refs" / "review-constants.json"
    try:
        data = json.loads(constants_path.read_text(encoding="utf-8"))
        overrides = data.get("runtime_overrides", {})
        marker = overrides.get("sparse_disabled_marker", marker) or marker
        note = overrides.get("sparse_disabled_summary_note", note) or note
    except Exception:  # noqa: BLE001 - standalone fallback to literals.
        pass
    return marker, note


_SPARSE_DISABLED_MARKER, _SPARSE_DISABLED_SUMMARY_NOTE = _runtime_override_constants()
_SPARSE_DISABLED_SUMMARY_RE = re.compile(
    r"sparse[\s\S]{0,200}?SKIP[\s\S]{0,200}?" + re.escape(_SPARSE_DISABLED_SUMMARY_NOTE),
    re.IGNORECASE,
)


def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
    for k, v in attrs:
        if k == "class" and v:
            return set(v.split())
    return set()


def _attr(attrs: list[tuple[str, str | None]], name: str) -> str:
    for k, v in attrs:
        if k == name and v is not None:
            return v
    return ""


class ReviewParser(HTMLParser):
    """Extract the structures we need from the report HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.report = Report()

        # Cursor state.
        self._in_banner = 0          # nesting depth inside the verdict-banner
        self._in_block: Optional[CommitBlock] = None
        self._block_div_depth = 0
        self._current_card: Optional[FindingCard] = None
        self._card_div_depth = 0
        self._capture_into: Optional[str] = None  # "title" | "body" | "file_ref"
        self._capture_buf: list[str] = []
        self._in_subject = False
        self._subject_buf: list[str] = []
        self._in_h3 = False
        self._h3_buf: list[str] = []

    # ---- helpers --------------------------------------------------------

    def _start_capture(self, slot: str) -> None:
        self._capture_into = slot
        self._capture_buf = []

    def _stop_capture(self) -> str:
        text = "".join(self._capture_buf).strip()
        self._capture_into = None
        self._capture_buf = []
        return text

    # ---- HTMLParser hooks ----------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        cls = _classes(attrs)

        if tag == "div":
            if "verdict-banner" in cls:
                self._in_banner = 1
            elif self._in_banner:
                self._in_banner += 1

            if "commit-block" in cls and self._in_block is None:
                block = CommitBlock(index=len(self.report.blocks))
                self.report.blocks.append(block)
                self._in_block = block
                self._block_div_depth = 1
            elif self._in_block is not None:
                self._block_div_depth += 1

            if "finding-card" in cls:
                container = "banner" if self._in_banner else (
                    "block" if self._in_block else "orphan"
                )
                block_idx = self._in_block.index if self._in_block else -1
                card = FindingCard(container=container, block_index=block_idx)
                # Severity from class set
                for css, sev in _SEVERITY_FROM_CLASS.items():
                    if css in cls:
                        card.severity = sev
                        break
                card.anchor_id = _attr(attrs, "id")
                card.attribution = _attr(attrs, "data-attribution").strip().lower()
                self._current_card = card
                self._card_div_depth = 1
                if container == "banner":
                    self.report.verdict_banner.append(card)
                elif container == "block" and self._in_block is not None:
                    self._in_block.findings.append(card)
            elif self._current_card is not None:
                self._card_div_depth += 1
                if "title" in cls:
                    self._start_capture("title")
                elif "body" in cls:
                    self._start_capture("body")
                elif "file-ref" in cls:
                    self._start_capture("file_ref")
                elif "suggestion" in cls:
                    self._start_capture("suggestion")
                elif "verdict-pill" in cls:
                    self._start_capture("verdict")
            elif self._in_banner and "verdict-pill" in cls:
                self._start_capture("verdict")

        elif tag == "span" and self._current_card is not None:
            if "title" in cls:
                self._start_capture("title")

        elif tag == "h3" and self._in_block is not None and self._current_card is None:
            self._in_h3 = True
            self._h3_buf = []

        elif tag == "h1":
            # The page title — not used.
            pass

        elif tag == "span" and self._in_block is not None and "commit-subject" in cls:
            self._in_subject = True
            self._subject_buf = []

        elif tag == "a" and self._current_card is not None:
            href = _attr(attrs, "href")
            if href.startswith("#"):
                self._current_card.anchor_targets.append(href[1:])

        # Stat chips: <span class="stat-chip bugs"> etc.
        if tag == "span" and self._in_banner and self._current_card is None:
            if "verdict-pill" in cls:
                self._start_capture("verdict")
            for key in _STAT_CHIP_KEYS:
                if key in cls and "stat-chip" in cls:
                    self._start_capture(f"chip:{key}")

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            if self._capture_into == "verdict":
                self.report.verdict = self._stop_capture().upper()
            if self._current_card is not None:
                self._card_div_depth -= 1
                if self._card_div_depth == 0:
                    self._current_card = None
                    if self._capture_into:
                        self._stop_capture()
            # Block depth always decrements when a div closes inside a block —
            # finding-card divs are nested inside the commit-block too.
            if self._in_block is not None:
                self._block_div_depth -= 1
                if self._block_div_depth == 0:
                    self._in_block = None

            if self._in_banner:
                self._in_banner -= 1

        elif tag == "span":
            if self._capture_into == "title" and self._current_card is not None:
                self._current_card.title = self._stop_capture()
            elif self._capture_into == "verdict":
                self.report.verdict = self._stop_capture().upper()
            elif self._capture_into and self._capture_into.startswith("chip:"):
                key = self._capture_into.split(":", 1)[1]
                text = self._stop_capture()
                m = re.match(r"\s*(\d+)\b", text)
                if m:
                    self.report.stat_chips[key] = int(m.group(1))
            if self._in_subject:
                self._in_subject = False
                if self._in_block is not None and not self._in_block.subject:
                    self._in_block.subject = "".join(self._subject_buf).strip()

        elif tag == "h3":
            if self._in_h3:
                self._in_h3 = False
                if self._in_block is not None:
                    h3_text = "".join(self._h3_buf).strip()
                    self._in_block.headers.append(h3_text)
                    # Inject the literal <h3>...</h3> marker into raw_html so
                    # section-scoped regexes like _HARDWARE_SECTION_RE can
                    # locate each section's body.  handle_data only appends
                    # text data (not tags), so without this the section
                    # delimiters never reach raw_html and section-text
                    # extraction always returns empty.
                    self._in_block.raw_html += f"<h3>{h3_text}</h3>\n"

    def handle_data(self, data: str) -> None:
        if self._in_block is not None:
            self._in_block.raw_html += data + "\n"
        if self._capture_into:
            self._capture_buf.append(data)
        if self._in_subject:
            self._subject_buf.append(data)
        if self._in_h3:
            self._h3_buf.append(data)

    def handle_decl(self, decl: str) -> None:  # <!DOCTYPE ...>
        return

    def handle_comment(self, data: str) -> None:
        if "STEP_COMPLETION_RECORD" in data and self._in_block is not None:
            self._in_block.step_record = data


# Finding-card text slots may contain inline tags such as <code>, <em>, or
# <a>, so we cannot simply close the capture on the first </div>.  Track the
# wrapping div depth and finalize when it pops back to the level where capture
# began.  Block-level HTML in these slots is a rendering-contract violation.
class _CardScopedParser(ReviewParser):
    """Handles nested elements inside finding-card text slots."""

    def __init__(self) -> None:
        super().__init__()
        self._capture_depth: int = 0       # depth of the div that started capture

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if (
            self._capture_into in _FINDING_TEXT_SLOTS
            and self._capture_depth != 0
            and self._current_card is not None
            and tag in _NESTED_BLOCK_TAGS
        ):
            self._current_card.render_violations.append(
                f".{self._capture_into} contains nested <{tag}>"
            )
        super().handle_starttag(tag, attrs)
        if self._capture_into in _FINDING_TEXT_SLOTS and self._capture_depth == 0:
            self._capture_depth = self._card_div_depth

    def handle_endtag(self, tag: str) -> None:
        if (
            tag == "div"
            and self._capture_into in _FINDING_TEXT_SLOTS
            and self._current_card is not None
            and self._card_div_depth == self._capture_depth
        ):
            slot = self._capture_into          # capture BEFORE _stop_capture clears it
            text = self._stop_capture()
            self._capture_depth = 0
            if slot == "body":
                self._current_card.body = text
            elif slot == "file_ref":
                self._current_card.file_ref = text
            elif slot == "suggestion":
                self._current_card.suggestion = text
        super().handle_endtag(tag)


def parse_report(html: str) -> Report:
    parser = _CardScopedParser()
    parser.feed(html)
    parser.close()
    parser.report.raw_html = html
    return parser.report


def parse_block_fragment(html: str, block_index: int = 0) -> Report:
    """Parse a single commit-block fragment as a minimal report.

    Per-patch block files are validated before final HTML assembly.  They are
    fragments, not full documents, and their canonical anchor ids still use the
    real 1-based patch number.  Keep that patch number in ``block.index`` so
    anchor validation remains identical to full-report validation.
    """
    report = parse_report(html)
    if report.blocks:
        report.blocks[0].index = block_index
    return report


