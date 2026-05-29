#!/usr/bin/env python3
"""Structural validator for review-commits HTML reports.

Run after Step 6 (final HTML assembly).  Exit non-zero on any contract
violation.  See refs/orchestrator-workflow.md Step 6.7.

Checks:
  1. Per-card Gate trace            (Gate 1/2/3 or Always-BUG exception)
  2. Per-block STEP_COMPLETION_RECORD presence + required fields
  3. Conditional section presence   (DT and HW-eng headers)
  4. Banner stat-chip vs block badge counts ([NIT] excluded)
  5. Per-block finding-card anchor id format
  6. Banner finding-card deduplication + anchor links
  7. Build-break presence/ordering  (build BUG must lead its block + banner)
  8. Build artifact validity        (reject interactive Kconfig prompt logs)
  9. Finding-card render format     (no nested block HTML in text slots)
 10. Hardware-trigger consistency   (HW-looking patches cannot mark HW N/A)
 11. Refactor coverage matrix       (rate abstractions include DMA/GPI paths)
 12. Future-risk gate               (current-safe table entries are not concerns)
 13. Safe-clearance gate            (safe/no-action conclusions are not findings)

Usage:
  validate_review.py <html_path> [--tests <tests_<slug>.txt>]
  validate_review.py --block-file <tmp/patch_N_block.html> \
      [--patch-file <tmp/review_patches/000N-*.patch>] \
      [--prompt-file <tmp/patch_N_prompt.md>] \
      [--evidence-file <tmp/evidence/patch_N_evidence.json>] \
      [--tests <tests_<slug>.txt>] [--build-file <tmp/patch_N_build.txt>] \
      [--source-root <project_path>]
"""

from __future__ import annotations

import argparse
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
                 "anchor_id", "anchor_targets", "container", "block_index",
                 "render_violations")

    def __init__(self, container: str, block_index: int) -> None:
        self.severity: str = ""
        self.title: str = ""
        self.body: str = ""
        self.file_ref: str = ""
        self.suggestion: str = ""
        self.anchor_id: str = ""
        self.anchor_targets: list[str] = []
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
    __slots__ = ("verdict_banner", "stat_chips", "blocks", "verdict")

    def __init__(self) -> None:
        self.verdict_banner: list[FindingCard] = []
        self.stat_chips: dict[str, int] = {}     # "bugs" / "concerns" / "minors" / "nits"
        self.blocks: list[CommitBlock] = []
        self.verdict: str = ""


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
_VALIDATOR_CHECKS = (
    "gate_trace",
    "step_record",
    "conditional_sections",
    "banner_consistency",
    "anchor_id",
    "banner_dedup",
    "build_break_order",
    "build_artifact_validity",
    "render_format",
    "hardware_trigger_consistency",
    "refactor_coverage",
    "future_risk_gate",
    "safe_clearance_gate",
    "compatible_fallback",
    "match_data_guard",
    "pm_runtime_get_sync_check",
    "dma_names_example",
    "fast_path_restore_proof",
    "codebase_audit_record",
    "codebase_audit_required",
    "on_demand_reads_record",
    "inconclusive_requires_read_attempt",
    "severity_crash_floor",
    "severity_restore_floor",
    "helper_equivalence_requires_source_proof",
    "evidence_manifest_record",
    "evidence_required_reads",
    "source_corpus_required",
    "touched_unsafe_pm_source_aware",
    "resource_abstraction_bypass_source_aware",
)

# Patch-source-aware backstops. These complement the HTML-text checks above:
# they fire when the patch's own diff contains a known trigger token but the
# report (whole HTML, all blocks combined) shows no acknowledgement at all.
# They are robust against the model eliding the trigger token from the report
# (which silences the corresponding HTML-only check).
_VALIDATOR_CHECKS_SOURCE_AWARE = (
    "pm_runtime_get_sync_source_aware",
    "dma_names_source_aware",
    "binding_companion_dependency_source_aware",
    "binding_compatible_shape_source_aware",
    "match_data_source_aware",
    "resource_helper_guard_source_aware",
    "helper_side_effect_source_aware",
    "touched_unsafe_pm_source_aware",
    "resource_abstraction_bypass_source_aware",
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
                    self._in_block.headers.append("".join(self._h3_buf).strip())

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


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


_STEP_RECORD_REQUIRED = (
    "step_1_read_diff",
    "step_2_read_context",
    "step_3_read_tests",
    "step_3b_coding_style",
    "step_3c_code_logic",
    "step_3d_dt_binding",
    "step_3e_commit_message",
    "step_3f_hardware_eng",
    "step_4_gate_applied",
    "step_5_html_written",
    "codebase_audit",
    "self_audit",
    "validator_will_check",
)

_BUILD_BREAK_PATTERNS = (
    "build break",
    "build-break",
    "build (w=1)",
    "fails to compile",
    "compile error",
    "compile-error",
    "implicit declaration",
    "-werror",
    "rray_size",     # the canonical example
)

_INTERACTIVE_KCONFIG_BUILD_PATTERNS = (
    re.compile(r"^\*\s*Restart config\.\.\.", re.MULTILINE),
    re.compile(r"choice\[[^\n]*\]:", re.IGNORECASE),
    re.compile(r"Error in reading or end of file\.", re.IGNORECASE),
)

_STRONG_HARDWARE_RE = re.compile(
    r"\b(runtime_(?:suspend|resume)|system_(?:suspend|resume)|"
    r"dev_pm_opp_|dev_pm_domain_|pm_runtime_|geni_se_resources_|"
    r"geni_se_clk_|geni_icc_|icc_(?:set|enable|disable)|"
    r"clk_round_rate|get_.*clk_cfg|setup_gsi_xfer|setup_se_xfer|"
    r"dma_request_chan|dmaengine_|pinctrl_pm_|power[-_ ]?domain|"
    r"performance[-_ ]?(?:state|vote)|\bopp\b)",
    re.IGNORECASE,
)
_HARDWARE_NA_RE = re.compile(
    r"step_3f_hardware_eng:\s*N/A|"
    r"Hardware Engineering Notes\s+Not applicable",
    re.IGNORECASE,
)
_REFACTOR_RATE_RE = re.compile(
    r"\bset_rate\b.*(?:Call-path coverage matrix|new abstraction|ops table|descriptor)|"
    r"(?:Call-path coverage matrix|new abstraction|ops table|descriptor).*\bset_rate\b",
    re.IGNORECASE | re.DOTALL,
)
_DMA_GPI_COVERAGE_RE = re.compile(
    r"DMA/GPI|GPI DMA|setup_gsi_xfer|gsi_xfer|\bGSI\b",
    re.IGNORECASE,
)
# A coverage row that actually resolves the DMA/GPI path to a verdict
# (reached / not-reached / safe / bypass), not merely naming the token.
_DMA_GPI_VERDICT_RE = re.compile(
    r"(?:DMA/GPI|GPI DMA|setup_gsi_xfer|gsi_xfer|\bGSI\b)"
    r"[\s\S]{0,200}?"
    r"(?:reached|not reached|covered|safe|bypass|same helper|shared path)",
    re.IGNORECASE,
)
# Evidence that the review actually inspected the *named* GPI/GSI setup
# routine (or explicitly stated the driver has no such routine), as opposed
# to a generic "DMA/GPI path is safe" sentence that the model can produce
# without ever opening the file.
_GSI_ROUTINE_NAMED_RE = re.compile(
    r"setup_gsi_xfer|setup_gsi\w*|gsi_xfer|\w+_gpi_setup|\w+_gsi_setup|"
    r"no (?:GSI|GPI)(?:/(?:GPI|GSI))? (?:setup|routine|path|consumer)|"
    r"driver (?:has|contains) no (?:GSI|GPI)|"
    r"(?:GSI|GPI) (?:routine|path) does not exist|"
    r"only (?:FIFO|SE-DMA|PIO) (?:transfer|path|mode)s? (?:exists|are present)",
    re.IGNORECASE,
)
# A DMA/GPI row that claims the path is SAFE while UNCONVERTED — the most
# error-prone verdict: "old DMA helpers remain; safe", "not converted ... safe",
# "DMA programming unchanged".  Such a claim must be backed by nested-call-site
# proof (below), or an unconverted sibling that still calls the abstracted
# helper (e.g. a GPI setup routine calling the old clock-config helper) slips by.
_DMA_GPI_SAFE_UNCONVERTED_RE = re.compile(
    r"(?:not[ -]?converted|unconverted|old (?:dma )?helpers? remain|"
    r"(?:dma|descriptor|channel)[ -]?(?:programming|setup) (?:is )?unchanged|"
    r"(?:does not|doesn't|do not|don't|no) (?:call|use|invoke|reach|touch)[\s\S]{0,60}?"
    r"(?:clock|clk|rate|opp|set_rate|helper|config)(?:[\s\S]{0,30}?at all)?|"
    r"(?:bypass(?:es)?|skips?)[\s\S]{0,60}?"
    r"(?:clock|clk|rate|opp|set_rate|helper|config))"
    r"[\s\S]{0,160}?(?:safe|not affected|no impact|not[ -]?reached)"
    r"|(?:safe|not affected|no impact|not[ -]?reached)[\s\S]{0,160}?"
    r"(?:not[ -]?converted|unconverted|old (?:dma )?helpers? remain|"
    r"(?:dma|descriptor|channel)[ -]?(?:programming|setup) (?:is )?unchanged|"
    r"(?:does not|doesn't|do not|don't|no) (?:call|use|invoke|reach|touch)[\s\S]{0,60}?"
    r"(?:clock|clk|rate|opp|set_rate|helper|config)(?:[\s\S]{0,30}?at all)?|"
    r"(?:bypass(?:es)?|skips?)[\s\S]{0,60}?"
    r"(?:clock|clk|rate|opp|set_rate|helper|config))",
    re.IGNORECASE,
)
# Proof that the report actually inspected the unconverted path for nested
# call sites of the abstracted helper (clock/rate/OPP config), rather than
# only reasoning about DMA channel/descriptor programming.
_NESTED_CALLSITE_PROOF_RE = re.compile(
    r"get_spi_clk_cfg|clk_freq_match|set_rate\b[\s\S]{0,80}?(?:call site|callsite|"
    r"also call|still call|direct call|grep|no other call)|"
    r"setup_gsi_xfer[\s\S]{0,120}?(?:does not call|no call to|also calls|still calls)|"
    r"(?:no|every|each) (?:other |remaining )?call site",
    re.IGNORECASE,
)
# A "not reached for <platform>" claim about a GPI/DMA entry-point must name
# the selector that makes the entry-point unreachable for that platform. Naming
# only a downstream helper ("does not call get_spi_clk_cfg directly") is not
# enough; the proof must mention the mode/capability/init-time condition that
# prevents the entry-point itself from being chosen.
_DMA_GPI_NOT_REACHED_RE = re.compile(
    r"(?:DMA/GPI|GPI DMA|setup_gsi_xfer|gsi_xfer|\bGSI\b)"
    r"[\s\S]{0,200}?(?:not reached|unreachable|cannot reach|does not reach)",
    re.IGNORECASE,
)
_DMA_GPI_SELECTOR_PROOF_RE = re.compile(
    r"FIFO_IF_DISABLE|GENI_GPI_DMA|SE_DMA|FIFO mode|PIO mode|cur_xfer_mode|"
    r"xfer mode|selected in spi_geni_init|mode bit|"
    r"capability bit|init-time condition|"
    r"only when[\s\S]{0,40}?(?:GPI|DMA|FIFO|PIO)|"
    r"if[\s\S]{0,60}?(?:GPI|DMA|FIFO_IF_DISABLE|cur_xfer_mode)",
    re.IGNORECASE,
)
_FUTURE_TABLE_RE = re.compile(
    r"device_get_match_data|match[- ]data|of_device_id|descriptor|table|callback slot",
    re.IGNORECASE,
)
_CURRENT_SAFE_RE = re.compile(
    r"all current|currently all|current tree safe|no crash path exists|"
    r"not reached in current tree|every current call path is safe",
    re.IGNORECASE,
)
_SAFE_CLEARANCE_RE = re.compile(
    r"\b(?:verified safe|"
    r"no (?:functional|behavioral) regression|"
    r"no defect found|"
    r"unchanged and safe|"
    r"every current call path is safe|"
    r"no crash path exists|"
    r"current (?:tree|path|behavior|implementation)\s+(?:is|remains)\s+safe|"
    r"guard verified[\s\S]{0,40}?(?:safe|sufficient|no (?:functional|behavioral) regression)|"
    r"existing guard[\s\S]{0,40}?(?:safe|sufficient|no (?:functional|behavioral) regression)|"
    r"Gate 1:\s*[\s\S]{0,120}?(?:not reached in current tree|fails?)|"
    r"Gate 2:\s*no (?:functional|behavioral) regression)\b",
    re.IGNORECASE,
)
_NO_ACTION_NEEDED_RE = re.compile(
    r"\b(?:no action needed|no code change needed|no fix needed|"
    r"leave as[- ]is|keep as[- ]is)\b",
    re.IGNORECASE,
)
# A future-risk dismissal phrased without the literal word "future": the
# finding asserts only a later/hypothetical caller could ever trigger it.
_FUTURE_PHRASING_RE = re.compile(
    r"\bfuture\b|hypothetical|not yet (?:added|wired|called)|"
    r"once a (?:new )?(?:caller|driver|client) (?:is )?(?:added|wired)|"
    r"if a (?:future|later|new) caller|would (?:only )?(?:trigger|matter) (?:if|when)|"
    r"only reachable after|when someone adds",
    re.IGNORECASE,
)

# A binding review that introduces/changes a `compatible:` defined as a bare
# `const:` must show it cross-checked the parent/wrapper + sibling schemas for
# a SoC fallback array (oneOf/items).  Otherwise an over-strict `const:` that
# rejects a valid `[variant, base]` fallback (failing dtbs_check) slips by.
_COMPAT_CONST_RE = re.compile(
    r"compatible[\s\S]{0,40}?\bconst\b",
    re.IGNORECASE,
)
_COMPAT_FALLBACK_PROOF_RE = re.compile(
    r"oneOf|compatible[\s\S]{0,80}?items:|\bfallback\b|parent (?:wrapper|schema|node)|"
    r"-geni-se-qup|wrapper schema|sibling (?:binding|schema)|"
    r"\bcontains:\s*\{|no (?:parent|wrapper) (?:oneOf|fallback)|"
    r"(?:parent|wrapper)[\s\S]{0,60}?(?:const only|bare const|no fallback)",
    re.IGNORECASE,
)
_COMPAT_DT_CONTEXT_RE = re.compile(
    r"\.yaml|dt[- ]?binding|devicetree/bindings|dtbs_check|dt_binding_check",
    re.IGNORECASE,
)
# When the review *dismisses* the fallback ("not needed", "no fallback",
# "no announced base variant"), it must cite a concrete parent/wrapper
# YAML path that was actually inspected (e.g. `*-geni-se-qup.yaml`,
# `*-qup.yaml`, `qcom,*.yaml`).  A generic "no oneOf is needed" sentence is
# not evidence; this gate stops the reviewer from concluding without
# reading the wrapper file.
_COMPAT_FALLBACK_DISMISS_RE = re.compile(
    r"(?:not\s+needed|no(?:t)?\s+(?:announced|present|defined|required)\s+"
    r"(?:base\s+)?(?:variant|fallback|oneOf|parent))|"
    r"(?:standalone\s+(?:automotive\s+)?SoC|single-?compatible\s+(?:approach|"
    r"is\s+correct))[\s\S]{0,80}?(?:no\s+(?:oneOf|fallback|variant))|"
    r"(?:const:\s*form\s+is\s+correct)|"
    r"(?:no\s+oneOf:\s*\[[^\]]+\]\s+is\s+needed)",
    re.IGNORECASE,
)
# Evidence the reviewer opened a *parent/wrapper* schema file (NOT the
# patch's own binding file).  We require either:
#   - a wrapper-named YAML path (`*-qup.yaml`, `*-wrapper.yaml`,
#     `*-controller.yaml`, `*-bus.yaml`, `*-hub.yaml`, `*-geni-se*.yaml`,
#     `*-parent.yaml`); these naming conventions correspond to vendor
#     wrappers that aggregate child device bindings, OR
#   - explicit prose stating the reviewer opened/read/grepped the parent
#     or wrapper schema, OR
#   - an explicit declaration that no parent wrapper exists for this
#     binding (e.g. `no parent wrapper schema exists`).
# We deliberately do NOT accept a bare `.yaml` path, because the patch's
# own binding file would otherwise satisfy the gate trivially.
_COMPAT_PARENT_PATH_RE = re.compile(
    r"[\w,/.-]*-(?:qup|wrapper|controller|parent|bus|hub|geni-se)[\w,.-]*\.yaml|"
    r"(?:opened|read|grep(?:ped)?|inspected|checked)\s+"
    r"(?:the\s+)?(?:parent|wrapper)[\s\S]{0,40}?(?:\.yaml|schema|binding)|"
    r"(?:parent|wrapper)\s+(?:schema|binding|yaml)\s+(?:at\s+)?"
    r"[\w/,.-]+\.yaml|"
    r"no\s+parent\s+(?:wrapper\s+)?(?:schema|binding|yaml)(?:\s+exists)?|"
    r"this\s+binding\s+has\s+no\s+(?:parent|wrapper)",
    re.IGNORECASE,
)
_GENERIC_PARENT_PATH_BASENAMES = {
    "bus.yaml",
    "controller.yaml",
    "i2c-controller.yaml",
    "serial-controller.yaml",
    "spi-controller.yaml",
}

# A finding/analysis that touches an unconditional `device_get_match_data()`
# (or `of_device_get_match_data()`) dereference must not be dismissed as
# unreachable without proving the non-OF bind paths (manual sysfs `bind`,
# `driver_override`, ACPI when no acpi_match_table, future table entry with
# no `.data`) are also rejected.  This enforces refs/dt-driver.md's match-data
# contract so the rule fires every run, not only when the model happens to
# trace the bind path.
_MATCH_DATA_REF_RE = re.compile(
    r"device_get_match_data|of_device_get_match_data",
    re.IGNORECASE,
)
_MATCH_DATA_DISMISS_RE = re.compile(
    r"unreachable|not reached|always (?:populated|set|non[- ]?NULL)|"
    r"cannot be NULL|never NULL|guaranteed (?:non[- ]?NULL|populated)|"
    r"NULL[\s\S]{0,40}?(?:impossible|unreachable|cannot occur)|"
    r"no (?:NULL|null)[- ]?deref(?:erence)? (?:path|risk|possible)|"
    r"safe[\s\S]{0,40}?(?:OF|match|dt|devicetree)",
    re.IGNORECASE,
)
_MATCH_DATA_GUARD_PROOF_RE = re.compile(
    r"driver_override|sysfs[\s -]*bind|manual(?:ly)?[\s -]*bind|"
    r"non[- ]?OF (?:bind|probe|path)|"
    r"ACPI (?:bind|probe|companion|match)|has_acpi_companion|"
    r"future (?:table )?entry[\s\S]{0,40}?(?:without|missing|no) \.?data|"
    r"every (?:bind|probe|non[- ]?OF) (?:mode|path) (?:is )?(?:rejected|impossible|"
    r"blocked|ruled out)|"
    r"only path[\s\S]{0,40}?(?:OF|of_device_id|match table)",
    re.IGNORECASE,
)

# When a patch's diff context contains an unchecked `pm_runtime_get_sync(`
# (followed by MMIO / register access / read), the review must show it
# considered the return-value pitfall: either flag the unchecked call as
# `[BUG]`, or quote the safe pattern (`pm_runtime_resume_and_get`,
# `put_noidle` on the error path, or "return value checked / negative
# errno").  Mirrors the rule in refs/hardware-eng.md (`pm_runtime bracket`).
_PM_RUNTIME_GET_SYNC_RE = re.compile(r"pm_runtime_get_sync\s*\(", re.IGNORECASE)
_PM_RUNTIME_GET_SYNC_PROOF_RE = re.compile(
    r"pm_runtime_resume_and_get|put_noidle|"
    r"(?:return\s+value|ret(?:urn)?)\s*(?:value\s*)?(?:check(?:ed)?|guard(?:ed)?|"
    r"unchecked|not\s+check(?:ed)?)|"
    r"negative\s+(?:errno|return)|"
    r"if\s*\(\s*ret\s*<\s*0|if\s*\(\s*ret\s*\)\s*\{?\s*pm_runtime_put|"
    r"unchecked[\s\S]{0,40}?pm_runtime|pm_runtime[\s\S]{0,40}?unchecked|"
    r"already\s+(?:checks|guards|handles)[\s\S]{0,40}?pm_runtime|"
    r"pm_runtime_get_sync[\s\S]{0,80}?(?:already (?:checked|guarded)|"
    r"checked below|unchanged from previous|pre-existing)",
    re.IGNORECASE,
)

# When a DT-binding patch defines BOTH a `dmas:` schema property AND a
# `dma-names:` property AND the `examples:` block uses `dmas =` (concrete
# example), the review's example-analysis must mention `dma-names` (e.g.
# noting it is required in the example, or proving the example correctly
# omits it for a documented reason).  Mirrors refs/dt-binding.md (`dmas`
# without `dma-names` is a reportable schema/example defect).
_DMA_BINDING_DEFINES_RE = re.compile(
    r"dma-?names\s*:[\s\S]{0,300}?dmas\s*:|dmas\s*:[\s\S]{0,300}?dma-?names\s*:",
    re.IGNORECASE,
)
_DMA_EXAMPLE_HAS_DMAS_RE = re.compile(r"dmas\s*=\s*<", re.IGNORECASE)
_DMA_EXAMPLE_HAS_DMA_NAMES_RE = re.compile(r"dma-?names\s*=\s*[\"<]", re.IGNORECASE)
_DMA_NAMES_REVIEW_PROOF_RE = re.compile(
    r"dma-?names\s+(?:is\s+)?(?:missing|absent|omitted|not\s+(?:present|set))\s+"
    r"(?:in|from)\s+(?:the\s+)?example|"
    r"example[\s\S]{0,80}?(?:is\s+)?(?:missing|lacks|omits|does\s+not\s+include|"
    r"does\s+not\s+(?:set|specify)|without)[\s\S]{0,40}?dma-?names|"
    r"example[\s\S]{0,160}?\bdma-?names\b\s*=|"
    r"\bdma-?names\b\s*=[\s\S]{0,40}?example|"
    r"add\s+dma-?names|require\s+dma-?names|need\s+dma-?names",
    re.IGNORECASE,
)
_DT_PROPERTY_DEF_RE = re.compile(
    r"^\+\s{2,}(?P<name>[A-Za-z0-9][A-Za-z0-9,._+-]*):\s*(?:$|#)",
    re.MULTILINE,
)


def _companion_name_candidates(property_name: str) -> set[str]:
    candidates = {f"{property_name}-names"}
    if property_name.endswith("ies") and len(property_name) > 3:
        candidates.add(f"{property_name[:-3]}y-names")
    if property_name.endswith("s") and len(property_name) > 1:
        candidates.add(f"{property_name[:-1]}-names")
    return candidates


def _binding_companion_property_pairs(patch_corpus: str) -> list[tuple[str, str]]:
    properties = {
        match.group("name")
        for match in _DT_PROPERTY_DEF_RE.finditer(patch_corpus)
        if not match.group("name").endswith("-names")
    }
    defined = {match.group("name") for match in _DT_PROPERTY_DEF_RE.finditer(patch_corpus)}
    pairs: list[tuple[str, str]] = []
    for property_name in sorted(properties):
        for companion in sorted(_companion_name_candidates(property_name)):
            if companion in defined:
                pairs.append((property_name, companion))
    return pairs


def _example_assigns_property(patch_corpus: str, property_name: str) -> bool:
    return bool(re.search(
        rf"^\+.*\b{re.escape(property_name)}\s*=",
        patch_corpus,
        re.MULTILINE,
    ))


def _schema_dependency_mentions_pair(
    text: str,
    property_name: str,
    companion: str,
) -> bool:
    property_re = re.escape(property_name)
    companion_re = re.escape(companion)
    return bool(re.search(
        rf"(?:dependencies|dependentRequired)\s*:[\s\S]{{0,220}}?"
        rf"{property_re}\s*:\s*(?:\[[^\]]*{companion_re}|"
        rf"[\s\S]{{0,120}}?-\s*{companion_re})|"
        rf"required\s*:[\s\S]{{0,260}}?(?:-\s*{property_re}"
        rf"[\s\S]{{0,160}}?-\s*{companion_re}|-\s*{companion_re}"
        rf"[\s\S]{{0,160}}?-\s*{property_re}|\[[^\]]*{property_re}"
        rf"[^\]]*{companion_re}[^\]]*\])|"
        rf"{property_re}[\s\S]{{0,120}}?(?:requires|depends on|dependent)"
        rf"[\s\S]{{0,120}}?{companion_re}",
        text,
        re.IGNORECASE,
    ))


def _review_mentions_companion_dependency(
    text: str,
    property_name: str,
    companion: str,
) -> bool:
    property_re = re.escape(property_name)
    companion_re = re.escape(companion)
    structural_terms = (
        r"(?:dependency|dependentRequired|required\s+list|schema\s+require|"
        r"schema[\s\S]{0,80}?(?:lack|missing|without|does\s+not\s+enforce|"
        r"doesn't\s+enforce|not\s+enforced)|"
        r"(?:lack|missing|without|not\s+enforced)[\s\S]{0,80}?schema|"
        r"optional[\s\S]{0,80}?(?:by\s+design|documented|intentional|allowed))"
    )
    pair_forward = rf"{property_re}[\s\S]{{0,180}}?{companion_re}"
    pair_reverse = rf"{companion_re}[\s\S]{{0,180}}?{property_re}"
    return bool(re.search(
        rf"(?:{pair_forward}|{pair_reverse})[\s\S]{{0,180}}?{structural_terms}|"
        rf"{structural_terms}[\s\S]{{0,180}}?(?:{pair_forward}|{pair_reverse})",
        text,
        re.IGNORECASE,
    ))


# When a refactor consolidates suspend/resume helpers and the review
# acknowledges that the resume helper does NOT restore an OPP / performance /
# voltage / clock-rate vote that the old code restored, it must show which
# concrete next-call restores it -- specifically excluding the cached
# fast-path skip (`if (rate == cur_*)`).  Otherwise OPP-not-restored-on-resume
# regressions slip by.  Mirrors refs/hardware-eng.md (cached fast path) and
# refs/code-logic.md (cached fast-path skip).
_FAST_PATH_RESUME_CONTEXT_RE = re.compile(
    r"(?:does\s+not|doesn't|does\s+NOT|no\s+longer)\s+(?:restore|re-?vote|"
    r"re-?request|re-?program|re-?set|re-?apply)[\s\S]{0,80}?"
    r"(?:OPP|opp|performance|perf|rate|vote|cur_sclk|cur_speed)|"
    r"(?:OPP|opp|performance|perf|rate|vote|cur_sclk|cur_speed)[\s\S]{0,80}?"
    r"(?:not\s+restored|not\s+re-?voted|not\s+re-?applied|not\s+re-?set)|"
    r"(?:rate\s+is\s+re-?set\s+on\s+next\s+transfer)|"
    r"(?:re-?set\s+on\s+next\s+(?:transfer|set_rate|call))",
    re.IGNORECASE,
)
_FAST_PATH_SKIP_RE = re.compile(
    r"if\s*\(\s*(?:clk_hz|rate|speed|freq)[\s\S]{0,30}?==\s*(?:mas->)?cur_(?:speed|sclk)|"
    r"fast[- ]path|cached\s+(?:rate|speed|freq)|short[- ]?circuit|"
    r"return\s+0;?\s*(?:/\*[\s\S]{0,40}?(?:cached|fast))",
    re.IGNORECASE,
)
_FAST_PATH_PROOF_RE = re.compile(
    r"(?:setup_se_xfer|setup_fifo|setup_pio|first\s+transfer|next\s+transfer)"
    r"[\s\S]{0,200}?(?:set_rate|geni_spi_set_clock|opp_set_rate)[\s\S]{0,200}?"
    r"(?:bypass|skip|short[- ]?circuit|fast[- ]?path|cur_speed|cur_sclk|"
    r"defeat|disabled|forced|re-?set|always)|"
    r"(?:bypass|skip|short[- ]?circuit|fast[- ]?path|cur_speed|cur_sclk)"
    r"[\s\S]{0,200}?(?:setup_se_xfer|setup_fifo|setup_pio|next\s+transfer)|"
    r"\[(?:BUG|CONCERN)\][\s\S]{0,160}?(?:OPP|opp|performance|perf|rate)"
    r"[\s\S]{0,80}?(?:not\s+restored|not\s+re-?voted|fast[- ]?path|skip)",
    re.IGNORECASE,
)
# A helper-equivalence claim without source proof is not acceptable when the
# block is reviewing hardware/resource side effects. This catches "reasonable
# assumption", "self-contained in diff", or "helper encapsulates the sequence"
# claims made without an on-demand read of the helper body.
_HELPER_EQUIVALENCE_CLAIM_RE = re.compile(
    r"reasonable assumption|self-contained in the diff|self-contained in diff|"
    r"behavioral equivalence|functionally equivalent|equivalent sequence|"
    r"helper encapsulates|encapsulates the above sequence|same series",
    re.IGNORECASE,
)
_ON_DEMAND_NONE_RE = re.compile(
    r"on_demand_reads:\s*none needed",
    re.IGNORECASE,
)
_ON_DEMAND_ZERO_RE = re.compile(
    r"on_demand_reads:\s*0\b",
    re.IGNORECASE,
)
# Severity floors for currently reachable crash / dropped-state regressions.
_SEVERITY_CRASH_FLOOR_RE = re.compile(
    r"NULL dereference|ERR_PTR dereference|kernel panic|kernel crash|"
    r"\boops\b|panic|dereference.*ERR_PTR|dereference.*NULL",
    re.IGNORECASE,
)
_SEVERITY_RESTORE_FLOOR_RE = re.compile(
    r"(?:resume|runtime PM|runtime_resume)[\s\S]{0,180}?"
    r"(?:not restored|removed|missing|dropped|no longer restores)[\s\S]{0,120}?"
    r"(?:rate|vote|state|opp|performance|clock)|"
    r"(?:rate|vote|state|opp|performance|clock)[\s\S]{0,180}?"
    r"(?:not restored|removed|missing|dropped)[\s\S]{0,120}?"
    r"(?:resume|runtime PM|runtime_resume)",
    re.IGNORECASE,
)
_HELPER_BODY_PROOF_RE = re.compile(
    r"(?:read|opened|inspected|checked|grepped?)\s+[\w/.,:-]+\.(?:c|h)|"
    r"(?:helper|callee|replacement)\s+(?:body|source)\s+(?:shows|reads|contains)|"
    r"(?:inside|within)\s+\w+\s*\([^)]*\)\s*,?\s*(?:it\s+)?"
    r"(?:calls|invokes|restores|re-?votes|re-?programs|re-?sets|writes|guards)|"
    r"\w+\s*\([^)]*\)[\s\S]{0,80}?"
    r"(?:calls|invokes|restores|re-?votes|re-?programs|re-?sets|writes|guards)\s+"
    r"\w+\s*\(",
    re.IGNORECASE,
)
_HARDWARE_RESOURCE_CONTEXT_RE = re.compile(
    r"\b(?:pm|runtime_pm|resume|suspend|clock|clk|opp|performance|vote|"
    r"dma|gpi|gsi|irq|regulator|icc|bandwidth|resource|transfer mode)\b",
    re.IGNORECASE,
)

_SOURCE_FILE_RE = re.compile(
    r"^\+\+\+\s+b/(?P<path>[^\t\n]+\.(?:c|h|cc|cpp|rs))\b",
    re.MULTILINE,
)
_RESOURCE_ABSTRACTION_INTRO_RE = re.compile(
    r"^\+[^+].*(?:"
    r"\(\*\s*\w*(?:rate|clk|clock|opp|perf|power|resource|bw)\w*\s*\)|"
    r"\.\s*\w*(?:rate|clk|clock|opp|perf|power|resource|bw)\w*\s*=|"
    r"->\s*\w*(?:rate|clk|clock|opp|perf|power|resource|bw)\w*\s*\()",
    re.IGNORECASE | re.MULTILINE,
)
_RESOURCE_ABSTRACTION_BYPASS_SAFE_RE = re.compile(
    r"(?:alternate|sibling|mode|path|DMA|GPI|GSI|IRQ|PM|resume|suspend|"
    r"setup_\w+|transfer\w*|xfer\w*)[\s\S]{0,260}?"
    r"(?:does\s+not|doesn't|do\s+not|don't|no)\s+"
    r"(?:call|use|invoke|reach|touch)[\s\S]{0,100}?"
    r"(?:abstraction|ops|descriptor|callback|set_rate|rate|clock|clk|opp|perf|resource)"
    r"[\s\S]{0,260}?(?:safe|architecturally correct|no regression|not affected|"
    r"unchanged|orthogonal)|"
    r"(?:safe|architecturally correct|no regression|not affected|unchanged|orthogonal)"
    r"[\s\S]{0,260}?(?:alternate|sibling|mode|path|DMA|GPI|GSI|IRQ|PM|resume|"
    r"suspend|setup_\w+|transfer\w*|xfer\w*)[\s\S]{0,260}?"
    r"(?:does\s+not|doesn't|do\s+not|don't|no)\s+"
    r"(?:call|use|invoke|reach|touch)[\s\S]{0,100}?"
    r"(?:abstraction|ops|descriptor|callback|set_rate|rate|clock|clk|opp|perf|resource)",
    re.IGNORECASE,
)
_RESOURCE_ABSTRACTION_BYPASS_FINDING_RE = re.compile(
    r"bypass|does\s+not\s+call|not\s+converted|old\s+helper|unconverted|"
    r"missing[\s\S]{0,40}?(?:abstraction|ops|descriptor|callback|set_rate|rate|clock|opp|resource)",
    re.IGNORECASE,
)
_PM_RUNTIME_BARE_GET_SYNC_RE = re.compile(
    r"^\s*pm_runtime_get_sync\s*\([^;]+\);",
    re.MULTILINE,
)
_PM_RUNTIME_FINDING_RE = re.compile(
    r"pm_runtime_get_sync|pm_runtime bracket|runtime PM[\s\S]{0,80}?unchecked|"
    r"unchecked[\s\S]{0,80}?runtime PM|resume_and_get",
    re.IGNORECASE,
)


class Violation:
    __slots__ = ("check", "where", "message")

    def __init__(self, check: str, where: str, message: str) -> None:
        self.check: str = check
        self.where: str = where
        self.message: str = message

    def __str__(self) -> str:  # pragma: no cover
        return f"  [{self.check}] {self.where}: {self.message}"


def check_gate_traces(report: Report) -> list[Violation]:
    """Check #1 — per-card Gate 1/2/3 trace.  NIT findings are exempt.

    Banner finding-cards are summaries that point to a canonical block card
    via <a href="#...">; the canonical card carries the trace.  We only
    require the trace on block cards (and on banner cards that lack an
    anchor target — those would be undocumented duplicates).
    """
    violations: list[Violation] = []
    cards: list[FindingCard] = []
    for block in report.blocks:
        cards.extend(block.findings)
    # Banner cards only need a trace if they don't anchor-link to a block card
    # (the block card check below will catch missing traces in the canonical
    # location).
    for c in report.verdict_banner:
        if not c.anchor_targets:
            cards.append(c)

    for c in cards:
        if c.severity == "NIT":
            # NIT uses the style track, validated below.
            if "Style track:" not in c.body:
                violations.append(Violation(
                    "gate_trace",
                    f"{c.container}#{c.block_index} '{c.title[:60]}'",
                    "NIT finding missing 'Style track:' marker",
                ))
            continue
        body = c.body
        has_gates = ("Gate 1:" in body and "Gate 2:" in body and "Gate 3:" in body)
        has_exception = "Always-BUG exception:" in body
        if not (has_gates or has_exception):
            violations.append(Violation(
                "gate_trace",
                f"{c.container}#{c.block_index} '{c.title[:60]}'",
                "missing 'Gate 1:/Gate 2:/Gate 3:' or 'Always-BUG exception:' trace",
            ))
            continue
        # Every non-NIT finding must name which Gate 1 sub-rule governed
        # reachability (or "none").  Require the tag directly in the Gate 1 or
        # always-BUG Reachability trace so an unrelated "sub-rule:" mention in
        # prose cannot satisfy validation accidentally.
        if not SUB_RULE_TRACE_RE.search(body):
            violations.append(Violation(
                "gate_trace",
                f"{c.container}#{c.block_index} '{c.title[:60]}'",
                "missing '[sub-rule: ...]' tag in Gate 1 / Reachability trace "
                "(name the matching Gate 1 sub-rule or 'none')",
            ))
        # Resource-leak always-BUG findings must state the object-lifetime
        # determination.  Other always-BUG classes, such as sleeping in atomic
        # context or unsafe copy_*_user, still need reachability/scope text but
        # do not have an object lifetime to classify.
        if (
            has_exception
            and RESOURCE_LEAK_EXCEPTION_RE.search(body)
            and not OBJECT_LIFETIME_RE.search(body)
        ):
            violations.append(Violation(
                "gate_trace",
                f"{c.container}#{c.block_index} '{c.title[:60]}'",
                "resource-leak always-BUG finding missing "
                "'object-lifetime check: <result>' "
                "(state bounded vs static/unbounded lifetime)",
            ))
    return violations


def check_step_records(report: Report) -> list[Violation]:
    """Check #2 — every commit-block has a complete STEP_COMPLETION_RECORD."""
    violations: list[Violation] = []
    for block in report.blocks:
        where = f"block#{block.index} '{block.subject[:60]}'"
        if not block.step_record:
            violations.append(Violation(
                "step_record",
                where,
                "missing <!-- STEP_COMPLETION_RECORD -->",
            ))
            continue
        for field in _STEP_RECORD_REQUIRED:
            if field not in block.step_record:
                violations.append(Violation(
                    "step_record",
                    where,
                    f"STEP_COMPLETION_RECORD missing field '{field}'",
                ))

        if not re.search(
            r"step_4_gate_applied:\s*DONE\s+bugs=\d+\s+concerns=\d+\s+"
            r"minors=\d+\s+nits=\d+\s*(?:\n|$)",
            block.step_record,
        ):
            violations.append(Violation(
                "step_record",
                where,
                "step_4_gate_applied must use 'DONE bugs=<n> concerns=<n> "
                "minors=<n> nits=<n>'",
            ))
        if not re.search(
            r"self_audit:\s*(?:PASS|CORRECTED\s+\d+\s+mismatches)\s*(?:\n|$)",
            block.step_record,
        ):
            violations.append(Violation(
                "step_record",
                where,
                "self_audit must be 'PASS' or 'CORRECTED <n> mismatches'",
            ))
        validator_line = re.search(
            r"validator_will_check:\s*([^\n]+)",
            block.step_record,
        )
        if validator_line:
            listed = set(validator_line.group(1).split())
            missing = [check for check in _VALIDATOR_CHECKS if check not in listed]
            if missing:
                violations.append(Violation(
                    "step_record",
                    where,
                    "validator_will_check missing: " + " ".join(missing),
                ))
    return violations


def check_conditional_sections(report: Report) -> list[Violation]:
    """Check #3 — DT and HW-eng headers present in every commit-block.

    Per the chosen policy, both sections are always emitted with an explicit
    fallback body when the trigger is absent.  Validator only verifies that
    the <h3> headers appear.
    """
    violations: list[Violation] = []
    required_headers = (
        "Hardware Engineering Notes",
        "DT / DT-Binding Notes",
    )
    for block in report.blocks:
        for needed in required_headers:
            if not any(needed in h for h in block.headers):
                violations.append(Violation(
                    "conditional_sections",
                    f"block#{block.index} '{block.subject[:60]}'",
                    f"missing <h3>{needed}</h3>",
                ))
    return violations


def check_banner_consistency(report: Report) -> list[Violation]:
    """Check #4 — stat-chip counts match the per-block badge totals.

    [NIT] is intentionally excluded from verdict-banner stat chips by the
    report contract. NIT findings stay in per-commit Minor / Style sections.
    """
    violations: list[Violation] = []
    counts = {"BUG": 0, "CONCERN": 0, "MINOR": 0, "NIT": 0}
    for block in report.blocks:
        for c in block.findings:
            if c.severity in counts:
                counts[c.severity] += 1

    expected = {
        "bugs": counts["BUG"],
        "concerns": counts["CONCERN"],
        "minors": counts["MINOR"],
    }
    for key, want in expected.items():
        got = report.stat_chips.get(key)
        if got is None:
            if want > 0:
                violations.append(Violation(
                    "banner_consistency",
                    "verdict-banner",
                    f"stat chip '{key}' missing (blocks contain {want})",
                ))
        elif got != want:
            violations.append(Violation(
                "banner_consistency",
                "verdict-banner",
                f"stat chip '{key}' = {got} but blocks contain {want}",
            ))
    if report.stat_chips.get("nits", 0):
        violations.append(Violation(
            "banner_consistency",
            "verdict-banner",
            "stat chip 'nits' must be omitted; [NIT] findings are excluded "
            "from verdict-banner stats",
        ))
    return violations


def check_block_anchor_ids(report: Report) -> list[Violation]:
    """Check #5 — every block finding has canonical patch-N-finding-K id."""
    violations: list[Violation] = []
    seen: set[str] = set()
    for block in report.blocks:
        for finding_index, card in enumerate(block.findings, start=1):
            expected = f"patch-{block.index + 1}-finding-{finding_index}"
            if not card.anchor_id:
                violations.append(Violation(
                    "anchor_id",
                    f"block#{block.index} '{card.title[:60]}'",
                    f"missing id='{expected}' on commit-block finding-card",
                ))
            elif card.anchor_id != expected:
                violations.append(Violation(
                    "anchor_id",
                    f"block#{block.index} '{card.title[:60]}'",
                    f"id='{card.anchor_id}' but expected id='{expected}'",
                ))
            if card.anchor_id:
                if card.anchor_id in seen:
                    violations.append(Violation(
                        "anchor_id",
                        f"block#{block.index} '{card.title[:60]}'",
                        f"duplicate finding-card id='{card.anchor_id}'",
                    ))
                seen.add(card.anchor_id)
    return violations


def check_banner_dedup(report: Report) -> list[Violation]:
    """Check #6 — every banner finding-card is an anchor pointer to a block card.

    A banner finding-card MUST:
      - contain at least one <a href="#..."> targeting an id that exists on a
        block-level finding-card (the canonical detail), AND
      - have a body whose visible text is <= 250 chars (a one-sentence summary).
    """
    violations: list[Violation] = []
    block_ids: set[str] = set()
    for block in report.blocks:
        for c in block.findings:
            if c.anchor_id:
                block_ids.add(c.anchor_id)

    for c in report.verdict_banner:
        if not c.anchor_targets:
            violations.append(Violation(
                "banner_dedup",
                f"banner '{c.title[:60]}'",
                "no <a href='#...'> link to canonical commit-block card",
            ))
            continue
        if not any(t in block_ids for t in c.anchor_targets):
            violations.append(Violation(
                "banner_dedup",
                f"banner '{c.title[:60]}'",
                f"anchor targets {c.anchor_targets!r} not found on any "
                "commit-block finding-card (canonical detail must live in a block)",
            ))
        if len(c.body) > 250:
            violations.append(Violation(
                "banner_dedup",
                f"banner '{c.title[:60]}'",
                f"body is {len(c.body)} chars; banner cards must be <=250-char "
                "summaries (full body lives in the commit-block)",
            ))
    return violations


def check_render_format(report: Report) -> list[Violation]:
    """Check #8 — finding-card text slots use render-safe inline content only."""
    violations: list[Violation] = []
    cards: list[FindingCard] = []
    cards.extend(report.verdict_banner)
    for block in report.blocks:
        cards.extend(block.findings)

    for card in cards:
        where = f"{card.container}#{card.block_index} '{card.title[:60]}'"
        for message in card.render_violations:
            violations.append(Violation(
                "render_format",
                where,
                message + "; move code/list/table blocks outside the text div",
            ))
        if re.search(r"Gate\s+[123]\s*:", card.suggestion):
            violations.append(Violation(
                "render_format",
                where,
                "Gate trace appears in .suggestion; put Gate 1:/2:/3: in .body",
            ))
        if re.search(r"Gate\s+[123]\s*\(", card.body):
            violations.append(Violation(
                "render_format",
                where,
                "Gate trace must use literal 'Gate N:' labels, not 'Gate N (...)'",
            ))
    return violations


def check_hardware_trigger_consistency(report: Report) -> list[Violation]:
    """Check #9 — hardware-looking commits must not mark HW review N/A.

    This catches reports that discuss PM, OPP, clocks, ICC, DMA, or resource
    helper changes in Code Logic Maps while claiming Hardware Engineering Notes
    are not applicable.
    """
    violations: list[Violation] = []
    for block in report.blocks:
        if "dt-bindings" in block.subject.lower():
            continue
        # The `validator_will_check:` metadata line lists check NAMES that
        # legitimately contain hardware tokens (e.g. `pm_runtime_get_sync_check`).
        # Strip it before matching so we only see review CONTENT, not metadata.
        clean_record = re.sub(
            r"validator_will_check:[^\n]*",
            "validator_will_check: <stripped>",
            block.step_record,
        )
        visible = f"{block.subject}\n{block.raw_html}\n{clean_record}"
        if _STRONG_HARDWARE_RE.search(visible) and _HARDWARE_NA_RE.search(visible):
            violations.append(Violation(
                "hardware_trigger_consistency",
                f"block#{block.index} '{block.subject[:60]}'",
                "hardware-facing PM/clock/OPP/ICC/DMA/resource-helper terms are "
                "present, but Hardware Engineering Notes or step_3f is marked N/A",
            ))
    return violations


def check_refactor_coverage(report: Report) -> list[Violation]:
    """Check #10 — rate/ops refactor matrices cover DMA/GPI paths."""
    violations: list[Violation] = []
    for block in report.blocks:
        visible = f"{block.subject}\n{block.raw_html}"
        if not _REFACTOR_RATE_RE.search(visible):
            continue
        if not _DMA_GPI_VERDICT_RE.search(visible):
            # A bare DMA/GPI keyword is not enough: the coverage matrix must
            # resolve the DMA/GPI path to a verdict (reached / not-reached /
            # safe / shares the same helper), or old-helper bypasses slip by.
            hint = (
                " (DMA/GPI token present but not resolved to a verdict)"
                if _DMA_GPI_COVERAGE_RE.search(visible)
                else ""
            )
            violations.append(Violation(
                "refactor_coverage",
                f"block#{block.index} '{block.subject[:60]}'",
                "set_rate/ops-table refactor coverage lacks an explicit "
                "alternative-execution-mode row resolved to "
                "reached/not-reached/safe; old helper bypasses can be missed"
                + hint,
            ))
            continue
        # A "safe because unconverted/unchanged" DMA/GPI verdict must prove the
        # unconverted path was grepped for nested call sites of the abstracted
        # helper (clock/rate/OPP config), not just reason about DMA channel
        # programming.  Otherwise a GPI path still calling the old clock helper
        # on a newly supported platform is wrongly cleared.
        if (
            _DMA_GPI_SAFE_UNCONVERTED_RE.search(visible)
            and not _NESTED_CALLSITE_PROOF_RE.search(visible)
        ):
            violations.append(Violation(
                "refactor_coverage",
                f"block#{block.index} '{block.subject[:60]}'",
                "an alternative execution mode is declared safe-because-"
                "unconverted, but the row does not prove the unconverted path "
                "lacks a nested call to the abstracted clock/rate/state helper; "
                "unchanged buffer/descriptor programming does not cover "
                "clock/rate/state configuration",
            ))
        # A "not reached for <platform>" verdict must prove which selector
        # keeps the *entry-point* unreachable for that platform. Naming only a
        # downstream helper or saying the path is "standard" is not enough.
        not_reached = _DMA_GPI_NOT_REACHED_RE.search(visible)
        if not_reached and _GSI_ROUTINE_NAMED_RE.search(visible):
            # Require selector proof local to the "not reached" row. Otherwise
            # unrelated tokens from a neighboring matrix row (for example
            # "SE-DMA" from a FIFO row) can falsely clear the check.
            window_start = max(0, not_reached.start() - 80)
            window_end = min(len(visible), not_reached.end() + 260)
            not_reached_window = visible[window_start:window_end]
            if not _DMA_GPI_SELECTOR_PROOF_RE.search(not_reached_window):
                violations.append(Violation(
                    "refactor_coverage",
                    f"block#{block.index} '{block.subject[:60]}'",
                    "an alternative execution mode is declared not reached for "
                    "a descriptor/platform, but the report does not name the "
                    "selector that makes the entry-point unreachable; proving "
                    "only that a downstream helper is not called directly is "
                    "insufficient",
                ))
        # When DMA/GPI is in scope, require the report to name a concrete
        # GSI/GPI setup routine (e.g. `setup_gsi_xfer`) or to state that no
        # such routine exists in the driver.  A generic "DMA/GPI path is
        # safe" sentence is not evidence the model opened the file.
        if (
            _DMA_GPI_COVERAGE_RE.search(visible)
            and not _GSI_ROUTINE_NAMED_RE.search(visible)
        ):
            violations.append(Violation(
                "refactor_coverage",
                f"block#{block.index} '{block.subject[:60]}'",
                "alternative execution mode coverage is discussed but no "
                "concrete mode entry-point routine is named and the report "
                "does not state the driver has no such routine; the coverage "
                "claim is not grounded in source",
            ))
    return violations


def check_future_risk_gate(report: Report) -> list[Violation]:
    """Check #11 — current-safe table/match-data hypotheticals are not concerns."""
    violations: list[Violation] = []
    cards: list[FindingCard] = []
    for block in report.blocks:
        cards.extend(block.findings)
    for card in cards:
        text = f"{card.title}\n{card.body}"
        if (
            card.severity == "CONCERN"
            and _FUTURE_PHRASING_RE.search(text)
            and _FUTURE_TABLE_RE.search(text)
            and _CURRENT_SAFE_RE.search(text)
        ):
            violations.append(Violation(
                "future_risk_gate",
                f"block#{card.block_index} '{card.title[:60]}'",
                "future-only table/match-data concern states current paths are "
                "safe; dismiss it or downgrade to local defensive style",
            ))
    return violations


def check_safe_clearance_gate(report: Report) -> list[Violation]:
    """Check #12 — safe/no-action conclusions are not BUG/CONCERN findings."""
    violations: list[Violation] = []
    cards: list[FindingCard] = []
    for block in report.blocks:
        cards.extend(block.findings)
    for card in cards:
        if card.severity not in ("BUG", "CONCERN"):
            continue
        text = f"{card.title}\n{card.body}\n{card.suggestion}"
        if not (
            _SAFE_CLEARANCE_RE.search(text)
            or _NO_ACTION_NEEDED_RE.search(card.suggestion)
        ):
            continue
        violations.append(Violation(
            "safe_clearance_gate",
            f"block#{card.block_index} '{card.title[:60]}'",
            "finding concludes the current path is safe or needs no action; "
            "dismiss it or convert it to a positive note instead of "
            "[BUG]/[CONCERN]",
        ))
    return violations


def check_compatible_fallback(report: Report) -> list[Violation]:
    """Check #13 — bare `compatible: const:` must prove a parent/sibling fallback cross-check."""
    violations: list[Violation] = []
    for block in report.blocks:
        visible = f"{block.subject}\n{block.raw_html}"
        if not _COMPAT_DT_CONTEXT_RE.search(visible):
            continue
        if not _COMPAT_CONST_RE.search(visible):
            continue
        if not _COMPAT_FALLBACK_PROOF_RE.search(visible):
            violations.append(Violation(
                "compatible_fallback",
                f"block#{block.index} '{block.subject[:60]}'",
                "binding uses `compatible: const:` but the review does not show a "
                "parent/wrapper + sibling cross-check for a SoC fallback array "
                "(oneOf/items: [variant, base]); an over-strict const that rejects "
                "valid variant DTS (dtbs_check failure) can be missed",
            ))
            continue
        # If the review dismisses the fallback ("no oneOf is needed",
        # "no announced base variant", "const is correct"), it must cite
        # the concrete parent/wrapper YAML it inspected.  A generic
        # dismissal without a parent file path is not evidence; many
        # vendor wrappers (e.g. *-geni-se-qup.yaml) actually define the
        # fallback that the bare const would reject.
        if (
            _COMPAT_FALLBACK_DISMISS_RE.search(visible)
            and not _has_specific_parent_wrapper_path(visible)
        ):
            violations.append(Violation(
                "compatible_fallback",
                f"block#{block.index} '{block.subject[:60]}'",
                "binding's bare `compatible: const:` is dismissed as correct "
                "(\"no fallback needed\"/\"no announced variant\") but the "
                "review does not cite a concrete parent/wrapper YAML path it "
                "inspected; quote the wrapper file (e.g. *-qup.yaml) and its "
                "`compatible:` block before clearing this finding",
            ))
    return violations


def check_match_data_guard(report: Report) -> list[Violation]:
    """Check #13 — when the review touches `device_get_match_data()` /
    `of_device_get_match_data()` and dismisses the unguarded dereference as
    unreachable, it must show it ruled out the non-OF bind paths
    (`driver_override`, manual sysfs bind, ACPI without acpi_match_table,
    future of_device_id entry without `.data`).  Mirrors the rule at
    refs/dt-driver.md (Match-data / descriptor contract)."""
    violations: list[Violation] = []
    for block in report.blocks:
        visible = f"{block.subject}\n{block.raw_html}"
        if not _MATCH_DATA_REF_RE.search(visible):
            continue
        if not _MATCH_DATA_DISMISS_RE.search(visible):
            continue
        if not _MATCH_DATA_GUARD_PROOF_RE.search(visible):
            violations.append(Violation(
                "match_data_guard",
                f"block#{block.index} '{block.subject[:60]}'",
                "review dismisses an unguarded `device_get_match_data()` "
                "dereference as unreachable but does not show the non-OF "
                "bind paths (driver_override, manual sysfs bind, ACPI, "
                "future table entry without `.data`) are rejected; "
                "see refs/dt-driver.md Match-data / descriptor contract",
            ))
    return violations


def check_pm_runtime_get_sync(report: Report) -> list[Violation]:
    """Check #14 — when a block's diff context contains `pm_runtime_get_sync(`,
    the review must show it considered the unchecked-return pitfall
    (refs/hardware-eng.md `pm_runtime bracket`).  Acceptable proofs are: a
    `[BUG]`/`[CONCERN]` finding citing the unchecked call, or evidence that
    the call's return is checked / replaced with `pm_runtime_resume_and_get`,
    or that `put_noidle` is used on the error path."""
    violations: list[Violation] = []
    for block in report.blocks:
        visible = f"{block.subject}\n{block.raw_html}"
        if not _PM_RUNTIME_GET_SYNC_RE.search(visible):
            continue
        if not _PM_RUNTIME_GET_SYNC_PROOF_RE.search(visible):
            violations.append(Violation(
                "pm_runtime_get_sync_check",
                f"block#{block.index} '{block.subject[:60]}'",
                "diff/context contains `pm_runtime_get_sync(` but the review "
                "does not show it considered the unchecked-return pitfall "
                "(missing return check, `pm_runtime_resume_and_get` migration, "
                "or `put_noidle` on the error path); see refs/hardware-eng.md "
                "`pm_runtime bracket`",
            ))
    return violations


def check_dma_names_example(report: Report) -> list[Violation]:
    """Check #15 — when a DT-binding diff defines BOTH `dmas:` and
    `dma-names:` properties AND the binding's `examples:` block uses
    `dmas = <...>`, the review's example analysis must address `dma-names`
    (either confirming it appears in the example or flagging its absence).
    Mirrors refs/dt-binding.md (a DT example with `dmas` but no `dma-names`
    is a reportable schema/example defect)."""
    violations: list[Violation] = []
    for block in report.blocks:
        visible = f"{block.subject}\n{block.raw_html}"
        if not _COMPAT_DT_CONTEXT_RE.search(visible):
            continue
        if not _DMA_BINDING_DEFINES_RE.search(visible):
            continue
        if not _DMA_EXAMPLE_HAS_DMAS_RE.search(visible):
            continue
        # If the example already contains `dma-names = ...`, the binding is
        # complete and no review-side action is required.
        if _DMA_EXAMPLE_HAS_DMA_NAMES_RE.search(visible):
            continue
        if not _DMA_NAMES_REVIEW_PROOF_RE.search(visible):
            violations.append(Violation(
                "dma_names_example",
                f"block#{block.index} '{block.subject[:60]}'",
                "binding defines `dmas:` and `dma-names:`, the example uses "
                "`dmas = <...>` but does not include `dma-names = ...`, and "
                "the review does not flag the missing example property; "
                "see refs/dt-binding.md (`dmas` without `dma-names` is a "
                "reportable schema/example defect)",
            ))
    return violations


def check_fast_path_restore_proof(report: Report) -> list[Violation]:
    """Check #16 — when the review acknowledges that a runtime-PM resume
    helper does NOT restore an OPP / performance / clock-rate vote that the
    old code restored, AND the driver has a cached fast-path skip
    (`if (rate == cur_*)` / `return 0`), the review must explicitly prove
    which call restores the dropped vote despite the fast path, or file a
    `[BUG]`/`[CONCERN]`.  Mirrors refs/hardware-eng.md (cached fast path)
    and refs/code-logic.md `3c.5 Before-vs-After Delta`."""
    violations: list[Violation] = []
    for block in report.blocks:
        visible = f"{block.subject}\n{block.raw_html}"
        if not _FAST_PATH_RESUME_CONTEXT_RE.search(visible):
            continue
        if not _FAST_PATH_SKIP_RE.search(visible):
            # No cached fast path is present in the visible text -- nothing
            # for the review to defeat.  Skip.
            continue
        if not _FAST_PATH_PROOF_RE.search(visible):
            violations.append(Violation(
                "fast_path_restore_proof",
                f"block#{block.index} '{block.subject[:60]}'",
                "resume helper acknowledged not to restore an OPP/perf/rate "
                "vote and a cached fast-path skip is in scope, but the review "
                "does not prove which call defeats the fast path or files a "
                "[BUG]/[CONCERN]; see refs/hardware-eng.md `cached fast path`",
            ))
    return violations


def check_build_break_order(
    report: Report,
    tests_text: str,
    *,
    require_banner: bool = True,
) -> list[Violation]:
    """Check #7 — build-break findings lead their commit-block and banner.

    Block-mode validation runs before the verdict banner exists, so it enforces
    only the per-commit ordering.  Full-report validation keeps the banner
    requirement enabled.
    """
    violations: list[Violation] = []
    if not tests_text:
        return violations
    lt = tests_text.lower()
    if "build" not in lt or "fail" not in lt:
        return violations

    def looks_like_build_break(c: FindingCard) -> bool:
        if c.severity != "BUG":
            return False
        text = (c.title + " " + c.body).lower()
        return any(p in text for p in _BUILD_BREAK_PATTERNS)

    block_breaks: list[tuple[int, int]] = []

    # Find which block contains the build break.
    for block in report.blocks:
        block_break = next(
            (i for i, c in enumerate(block.findings) if looks_like_build_break(c)),
            None,
        )
        if block_break is None:
            continue
        block_breaks.append((block.index, block_break))
        if block_break != 0:
            violations.append(Violation(
                "build_break_order",
                f"block#{block.index} '{block.subject[:60]}'",
                f"build-break finding is at position {block_break}; must be first",
            ))

    if not block_breaks:
        violations.append(Violation(
            "build_break_order",
            "commit-blocks",
            "Build (W=1) failed but no [BUG] build-break finding was found "
            "in any commit-block",
        ))
        return violations

    if not require_banner:
        return violations

    # Banner: if any banner card is a build break, it must be first.
    banner_break = next(
        (i for i, c in enumerate(report.verdict_banner) if looks_like_build_break(c)),
        None,
    )
    if banner_break is not None and banner_break != 0:
        violations.append(Violation(
            "build_break_order",
            "verdict-banner",
            f"build-break finding is at position {banner_break}; must be first",
        ))
    elif banner_break is None:
        violations.append(Violation(
            "build_break_order",
            "verdict-banner",
            "Build (W=1) failed but no banner [BUG] build-break finding was found",
        ))
    return violations


def _build_logs_for_report(report: Report, tmp_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for index in range(1, len(report.blocks) + 1):
        path = tmp_dir / f"patch_{index}_build.txt"
        if path.exists():
            paths.append(path)
    for path in sorted(tmp_dir.glob("review_*_build.txt")):
        paths.append(path)
    return paths


def _build_log_has_interactive_kconfig(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INTERACTIVE_KCONFIG_BUILD_PATTERNS)


def check_build_artifact_validity(report: Report, tmp_dir: Optional[Path]) -> list[Violation]:
    """Reject build logs that are really interactive Kconfig transcripts."""
    if tmp_dir is None or not tmp_dir.is_dir():
        return []

    violations: list[Violation] = []
    for path in _build_logs_for_report(report, tmp_dir):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _build_log_has_interactive_kconfig(text):
            continue
        violations.append(Violation(
            "build_artifact_validity",
            path.name,
            "build log shows interactive Kconfig prompts instead of compiler "
            "output (`Restart config...`, `choice[...]`, `Error in reading or "
            "end of file.`). Build verification is invalid; refresh `.config` "
            "non-interactively with `make ARCH=arm64 olddefconfig` at this "
            "tree state before rerunning the build.",
        ))
    return violations


def _load_patch_corpus(
    patches_dir: Optional[Path],
    series_id: str = "",
) -> str:
    """Concatenate `.mbox` / `.patch` files found directly under
    `patches_dir` into a single text blob.  Returns `""` on missing dir.
    When `series_id` is provided, only files whose name starts with the
    series_id prefix are included — this prevents cross-contamination from
    other series stored in the same tmp directory."""
    if not patches_dir or not patches_dir.is_dir():
        return ""
    candidates: list[Path] = []
    for ext in ("*.mbox", "*.patch"):
        candidates.extend(sorted(patches_dir.glob(ext)))

    def read(paths: list[Path], *, scoped: bool) -> list[str]:
        chunks: list[str] = []
        for path in paths:
            if scoped and series_id and not path.name.startswith(series_id):
                continue
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        return chunks

    chunks = read(candidates, scoped=True)
    if not chunks and candidates and patches_dir.name == "review_patches":
        # `git format-patch --output-directory tmp/review_patches` commonly
        # emits generic 0001-*.patch names.  Do not let the series-id filename
        # filter silently disable source-aware checks for the canonical in-tree
        # patch corpus.
        chunks = read(candidates, scoped=False)
    return "\n".join(chunks)


def _source_files_from_patch_corpus(patch_corpus: str) -> list[str]:
    seen: set[str] = set()
    files: list[str] = []
    for match in _SOURCE_FILE_RE.finditer(patch_corpus):
        path = match.group("path").strip()
        if path not in seen:
            seen.add(path)
            files.append(path)
    return files


_ON_DEMAND_READS_RE = re.compile(
    r"on_demand_reads:\s*(\d+)\s*(\[[^\]]*\]|\(no cross-file facts needed\))",
    re.IGNORECASE,
)
_CODEBASE_AUDIT_DONE_RE = re.compile(
    r"codebase_audit:\s*DONE\s+entrypoints=(\d+)\s+callees=(\d+)\s+"
    r"siblings=(\d+)\s+files=\[([^\]]+)\]",
    re.IGNORECASE,
)
_CODEBASE_AUDIT_NA_RE = re.compile(
    r"codebase_audit:\s*N/A\s+no function-level code changes",
    re.IGNORECASE,
)
_EVIDENCE_MANIFEST_RE = re.compile(
    r"evidence_manifest:\s*DONE\s+path=([^\s]+)",
    re.IGNORECASE,
)
_CODEBASE_AUDIT_ENTRY_LINE_RE = re.compile(
    r"codebase audit:\s*entrypoints?\b",
    re.IGNORECASE,
)
_CODEBASE_AUDIT_CALLEE_LINE_RE = re.compile(
    r"codebase audit:\s*callees?\b",
    re.IGNORECASE,
)
_CODEBASE_AUDIT_SIBLING_LINE_RE = re.compile(
    r"codebase audit:\s*siblings?\b",
    re.IGNORECASE,
)
_NO_FUNCTION_LEVEL_CHANGES_RE = re.compile(
    r"No function-level changes\s+[—-]\s*N/A\.",
    re.IGNORECASE,
)
_INCONCLUSIVE_BODY_RE = re.compile(
    r"source not in context files|"
    r"unable to verify failure encoding|"
    r"call chain ends at .* — source not in context files|"
    r"\binconclusive\b",
    re.IGNORECASE,
)


def _block_has_function_level_changes(block: CommitBlock) -> bool:
    visible = block.raw_html
    if _NO_FUNCTION_LEVEL_CHANGES_RE.search(visible):
        return False
    maps_match = re.search(
        r"step_3c_code_logic:\s*DONE\s+maps_written=(\d+)",
        block.step_record,
        re.IGNORECASE,
    )
    if maps_match and int(maps_match.group(1)) > 0:
        return True
    return bool(re.search(r"File:\s+[^<\n]+\.(?:c|h)\b", visible, re.IGNORECASE))


def _codebase_audit_files(block: CommitBlock) -> set[str]:
    match = _CODEBASE_AUDIT_DONE_RE.search(block.step_record or "")
    if not match:
        return set()
    files_blob = match.group(4)
    return {
        item.strip().strip("`'")
        for item in files_blob.split(",")
        if item.strip() and item.strip() != "..."
    }


def _load_evidence_manifest(path: Optional[Path]) -> Optional[dict[str, object]]:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"_invalid_path": str(path)}
    if not isinstance(data, dict):
        return {"_invalid_path": str(path)}
    data.setdefault("_path", str(path))
    return data


def _load_evidence_dir(path: Optional[Path]) -> dict[int, dict[str, object]]:
    manifests: dict[int, dict[str, object]] = {}
    if path is None or not path.is_dir():
        return manifests
    for manifest_path in sorted(path.glob("patch_*_evidence.json")):
        manifest = _load_evidence_manifest(manifest_path)
        if not manifest:
            continue
        try:
            patch_number = int(manifest.get("patch_number", 0))
        except (TypeError, ValueError):
            continue
        if patch_number >= 1:
            manifests[patch_number - 1] = manifest
    return manifests


def _required_evidence_reads(manifest: dict[str, object]) -> list[str]:
    reads = manifest.get("required_reads")
    if not isinstance(reads, list):
        return []
    paths: list[str] = []
    for item in reads:
        if not isinstance(item, dict):
            continue
        if item.get("required") is False:
            continue
        path = item.get("path")
        if isinstance(path, str) and path:
            paths.append(path)
    return paths


def _manifest_has_function_changes(manifest: dict[str, object]) -> bool:
    for key in ("changed_source_files", "changed_functions", "helper_candidates"):
        value = manifest.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def check_evidence_manifest_record(
    report: Report,
    evidence_by_block: dict[int, dict[str, object]],
) -> list[Violation]:
    if not evidence_by_block:
        return []
    violations: list[Violation] = []
    for block in report.blocks:
        manifest = evidence_by_block.get(block.index)
        if manifest is None:
            continue
        invalid_path = manifest.get("_invalid_path")
        if isinstance(invalid_path, str):
            violations.append(Violation(
                "evidence_manifest_record",
                f"block#{block.index} '{block.subject[:60]}'",
                f"evidence manifest is unreadable or invalid JSON: {invalid_path}",
            ))
            continue
        if manifest.get("schema") != "review-commits.evidence-manifest.v1":
            violations.append(Violation(
                "evidence_manifest_record",
                f"block#{block.index} '{block.subject[:60]}'",
                "evidence manifest has an unknown or missing schema",
            ))
            continue
        match = _EVIDENCE_MANIFEST_RE.search(block.step_record or "")
        if not match:
            violations.append(Violation(
                "evidence_manifest_record",
                f"block#{block.index} '{block.subject[:60]}'",
                "STEP_COMPLETION_RECORD must include "
                "`evidence_manifest: DONE path=<tmp/evidence/patch_N_evidence.json>` "
                "when an evidence manifest is supplied",
            ))
            continue
        manifest_path = str(manifest.get("_path") or manifest.get("output") or "")
        recorded_path = match.group(1).strip()
        if manifest_path and Path(recorded_path).name != Path(manifest_path).name:
            violations.append(Violation(
                "evidence_manifest_record",
                f"block#{block.index} '{block.subject[:60]}'",
                "STEP_COMPLETION_RECORD evidence manifest path does not match "
                f"the supplied manifest ({recorded_path} vs {manifest_path})",
            ))
    return violations


def check_evidence_required_reads(
    report: Report,
    evidence_by_block: dict[int, dict[str, object]],
) -> list[Violation]:
    if not evidence_by_block:
        return []
    violations: list[Violation] = []
    for block in report.blocks:
        manifest = evidence_by_block.get(block.index)
        if not manifest or manifest.get("_invalid_path"):
            continue
        if _manifest_has_function_changes(manifest) and _CODEBASE_AUDIT_NA_RE.search(block.step_record or ""):
            violations.append(Violation(
                "evidence_required_reads",
                f"block#{block.index} '{block.subject[:60]}'",
                "evidence manifest records function/source changes, but "
                "codebase_audit is marked N/A",
            ))
        audited_files = _codebase_audit_files(block)
        missing = [
            required
            for required in _required_evidence_reads(manifest)
            if required not in audited_files
        ]
        if missing:
            violations.append(Violation(
                "evidence_required_reads",
                f"block#{block.index} '{block.subject[:60]}'",
                "codebase_audit files=[...] is missing required evidence reads "
                "from the manifest: " + ", ".join(missing[:8]),
            ))
    return violations


def check_codebase_audit_record(report: Report) -> list[Violation]:
    """Check #17 — every block must carry a well-formed `codebase_audit:` line."""
    violations: list[Violation] = []
    for block in report.blocks:
        if not block.step_record:
            continue
        done_match = _CODEBASE_AUDIT_DONE_RE.search(block.step_record)
        na_match = _CODEBASE_AUDIT_NA_RE.search(block.step_record)
        if not (done_match or na_match):
            violations.append(Violation(
                "codebase_audit_record",
                f"block#{block.index} '{block.subject[:60]}'",
                "STEP_COMPLETION_RECORD is missing a well-formed "
                "`codebase_audit:` line; expected either "
                "`DONE entrypoints=<n> callees=<n> siblings=<n> files=[...]` "
                "or `N/A no function-level code changes`",
            ))
            continue
        if done_match:
            files_blob = done_match.group(4).strip()
            if not files_blob or files_blob == "...":
                violations.append(Violation(
                    "codebase_audit_record",
                    f"block#{block.index} '{block.subject[:60]}'",
                    "`codebase_audit:` must list the actual inspected files in "
                    "`files=[...]`; placeholder values are not allowed",
                ))
    return violations


def check_codebase_audit_required(report: Report) -> list[Violation]:
    """Check #18 — code patches must prove surrounding-code inspection."""
    violations: list[Violation] = []
    for block in report.blocks:
        if not block.step_record or not _block_has_function_level_changes(block):
            continue

        done_match = _CODEBASE_AUDIT_DONE_RE.search(block.step_record)
        if not done_match:
            violations.append(Violation(
                "codebase_audit_required",
                f"block#{block.index} '{block.subject[:60]}'",
                "block appears to review function-level code changes but "
                "`codebase_audit:` is not marked DONE; diff-only review is not "
                "allowed for code patches",
            ))
            continue

        visible = block.raw_html
        missing_lines: list[str] = []
        if not _CODEBASE_AUDIT_ENTRY_LINE_RE.search(visible):
            missing_lines.append("entrypoints")
        if not _CODEBASE_AUDIT_CALLEE_LINE_RE.search(visible):
            missing_lines.append("callees")
        if not _CODEBASE_AUDIT_SIBLING_LINE_RE.search(visible):
            missing_lines.append("siblings")
        if missing_lines:
            violations.append(Violation(
                "codebase_audit_required",
                f"block#{block.index} '{block.subject[:60]}'",
                "Code Logic Maps missing mandatory surrounding-code audit line(s): "
                + ", ".join(missing_lines),
            ))
    return violations


def check_on_demand_reads_record(report: Report) -> list[Violation]:
    """Check #19 — every commit block's STEP_COMPLETION_RECORD must include
    a well-formed `on_demand_reads:` line.  Format:
      `on_demand_reads: <count> [<path1>, ...]` (count >= 1), or
      `on_demand_reads: 0 (no cross-file facts needed)` (count == 0).
    Mirrors refs/core.md "Rules for the completion record"."""
    violations: list[Violation] = []
    for block in report.blocks:
        if not block.step_record:
            # Already caught by check_step_records; skip to avoid noise.
            continue
        match = _ON_DEMAND_READS_RE.search(block.step_record)
        if not match:
            violations.append(Violation(
                "on_demand_reads_record",
                f"block#{block.index} '{block.subject[:60]}'",
                "STEP_COMPLETION_RECORD is missing a well-formed "
                "`on_demand_reads: <count> [<paths>]` or "
                "`on_demand_reads: 0 (no cross-file facts needed)` line; "
                "see refs/core.md `Rules for the completion record`",
            ))
    return violations


def check_inconclusive_requires_read_attempt(
    report: Report,
) -> list[Violation]:
    """Check #20 — when any finding body in a block claims source unavailable
    or marks itself inconclusive, the block's `on_demand_reads:` count MUST
    be ≥ 1.  Mirrors refs/code-logic.md and refs/gate-rules.md: the model
    must attempt one targeted read before downgrading."""
    violations: list[Violation] = []
    for block in report.blocks:
        if not block.step_record:
            continue
        match = _ON_DEMAND_READS_RE.search(block.step_record)
        if not match:
            # Already flagged by check_on_demand_reads_record.
            continue
        count = int(match.group(1))
        if count >= 1:
            continue
        # count == 0; check no finding claims inconclusive.
        offending: list[str] = []
        for finding in block.findings:
            body_text = finding.body or ""
            if _INCONCLUSIVE_BODY_RE.search(body_text):
                offending.append(finding.title[:60] or "(untitled)")
        if offending:
            violations.append(Violation(
                "inconclusive_requires_read_attempt",
                f"block#{block.index} '{block.subject[:60]}'",
                "block claims `on_demand_reads: 0` but contains finding(s) "
                f"marked source-unavailable / inconclusive: {offending}.  "
                "The rules require attempting one on-demand `Read` under "
                "`<project_path>` before downgrading; see "
                "refs/code-logic.md and refs/gate-rules.md",
            ))
    return violations


def check_severity_crash_floor(report: Report) -> list[Violation]:
    """Crash-class findings must not be downgraded below CONCERN."""
    violations: list[Violation] = []
    for block in report.blocks:
        for finding in block.findings:
            text = f"{finding.title}\n{finding.body}"
            if not _SEVERITY_CRASH_FLOOR_RE.search(text):
                continue
            if finding.severity in ("NIT", "MINOR"):
                violations.append(Violation(
                    "severity_crash_floor",
                    f"block#{block.index} '{finding.title[:60]}'",
                    f"finding describes a currently reachable crash/dereference "
                    f"class issue but is filed as [{finding.severity}]; severity "
                    "must be at least [CONCERN]",
                ))
    return violations


def check_severity_restore_floor(report: Report) -> list[Violation]:
    """Dropped restore/revote/reprogram issues in resume paths must not be MINOR/NIT."""
    violations: list[Violation] = []
    for block in report.blocks:
        for finding in block.findings:
            text = f"{finding.title}\n{finding.body}"
            if not _SEVERITY_RESTORE_FLOOR_RE.search(text):
                continue
            if finding.severity in ("NIT", "MINOR"):
                violations.append(Violation(
                    "severity_restore_floor",
                    f"block#{block.index} '{finding.title[:60]}'",
                    f"finding describes a dropped restore/revote/reprogram "
                    f"regression in a resume/runtime-PM path but is filed as "
                    f"[{finding.severity}]; severity must be at least [CONCERN]",
                ))
    return violations


def check_helper_equivalence_requires_source_proof(
    report: Report,
) -> list[Violation]:
    """Hardware/resource helper-equivalence claims need source-backed proof."""
    violations: list[Violation] = []
    for block in report.blocks:
        visible = f"{block.subject}\n{block.raw_html}"
        if not _HELPER_EQUIVALENCE_CLAIM_RE.search(visible):
            continue
        if not _HARDWARE_RESOURCE_CONTEXT_RE.search(visible):
            continue

        has_on_demand_read = False
        if block.step_record:
            has_on_demand_read = bool(
                _ON_DEMAND_READS_RE.search(block.step_record)
                and not _ON_DEMAND_NONE_RE.search(block.step_record)
                and not _ON_DEMAND_ZERO_RE.search(block.step_record)
            )
        has_helper_body_proof = bool(_HELPER_BODY_PROOF_RE.search(visible))
        if has_on_demand_read or has_helper_body_proof:
            continue

        violations.append(Violation(
            "helper_equivalence_requires_source_proof",
            f"block#{block.index} '{block.subject[:60]}'",
            "review claims helper/replacement equivalence for hardware/resource "
            "behavior without source-backed proof; cite the helper body or record "
            "an on-demand source read instead of relying on name/context-based "
            "equivalence",
        ))
    return violations


def check_pm_runtime_get_sync_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Source-aware backstop for #14.  When the patch corpus introduces
    `pm_runtime_get_sync(` (added line in diff), at least one block must
    show the unchecked-return pitfall was considered.  Robust against the
    model eliding the call from the visible report text."""
    if not patch_corpus:
        return []
    diff_added_re = re.compile(
        r"^\+[^+].*pm_runtime_get_sync\s*\(", re.MULTILINE
    )
    if not diff_added_re.search(patch_corpus):
        return []
    visible_all = "\n".join(
        f"{b.subject}\n{b.raw_html}" for b in report.blocks
    )
    if _PM_RUNTIME_GET_SYNC_PROOF_RE.search(visible_all):
        return []
    return [Violation(
        "pm_runtime_get_sync_source_aware",
        "report (corpus-derived)",
        "patch series introduces `pm_runtime_get_sync(` (added in diff) but "
        "no block shows the unchecked-return pitfall was considered "
        "(missing return check, `pm_runtime_resume_and_get` migration, or "
        "`put_noidle` on the error path); see refs/hardware-eng.md "
        "`pm_runtime bracket`",
    )]


def check_dma_names_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Source-aware backstop for #15.  When the patch corpus contains a
    YAML binding diff that defines BOTH `dmas:` and `dma-names:` AND its
    example uses `dmas = <...>` without `dma-names = ...`, at least one
    report block must flag the missing example property."""
    if not patch_corpus:
        return []
    if not re.search(r"^\+\+\+\s+b/.+\.yaml\b", patch_corpus, re.MULTILINE):
        return []
    if not _DMA_BINDING_DEFINES_RE.search(patch_corpus):
        return []
    if not _DMA_EXAMPLE_HAS_DMAS_RE.search(patch_corpus):
        return []
    if _DMA_EXAMPLE_HAS_DMA_NAMES_RE.search(patch_corpus):
        return []
    visible_all = "\n".join(
        f"{b.subject}\n{b.raw_html}" for b in report.blocks
    )
    if _DMA_NAMES_REVIEW_PROOF_RE.search(visible_all):
        return []
    return [Violation(
        "dma_names_source_aware",
        "report (corpus-derived)",
        "patch series binding diff defines `dmas:` and `dma-names:`, "
        "the example uses `dmas = <...>` without `dma-names = ...`, and "
        "no review block flags the missing example property; see "
        "refs/dt-binding.md (`dmas` without `dma-names` is a reportable "
        "schema/example defect)",
    )]



# When the patch corpus adds a new YAML binding with `compatible:\n    const:`
# the review MUST discuss the compatible shape and cite a parent/wrapper schema.
# This backstop fires even when the model never wrote the word "const" in the
# report (which prevents _COMPAT_CONST_RE from triggering the inline check).
_CORPUS_COMPAT_CONST_SIMPLE_RE = re.compile(
    r"^\+\s+compatible:\s*$\s+\+\s+const:",
    re.MULTILINE,
)




def check_binding_companion_dependency_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Require review acknowledgement for schema/property coupling gaps.

    When a binding diff defines a property together with its companion naming
    property, and examples exercise the primary property, the review must either
    show the schema enforces the relationship or explicitly discuss why the
    relationship is optional/documented.
    """
    if not patch_corpus:
        return []
    if not re.search(r"^\+\+\+\s+b/.+\.yaml\b", patch_corpus, re.MULTILINE):
        return []

    visible_all = "\n".join(
        f"{b.subject}\n{b.raw_html}" for b in report.blocks
    )
    violations: list[Violation] = []
    for property_name, companion in _binding_companion_property_pairs(patch_corpus):
        if not _example_assigns_property(patch_corpus, property_name):
            continue
        if _schema_dependency_mentions_pair(patch_corpus, property_name, companion):
            continue
        if _review_mentions_companion_dependency(visible_all, property_name, companion):
            continue
        violations.append(Violation(
            "binding_companion_dependency_source_aware",
            f"report (corpus-derived: {property_name}/{companion})",
            "binding diff defines a property and its companion naming property, "
            "and examples exercise the primary property, but neither the schema "
            "nor the review explains whether the companion relationship is "
            "required, optional, or enforced elsewhere",
        ))
    return violations


def check_binding_compatible_shape_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Source-aware backstop for binding compatible-shape review.
    When the patch corpus adds a new YAML binding that uses a single-string
    compatible schema (`compatible: const:`), the review must discuss the
    compatible shape and cite a parent/wrapper schema (or declare none exists).
    Fires even when the model omits the literal word `const` from the report,
    which would otherwise silence the HTML-only check."""
    if not patch_corpus:
        return []
    if not re.search(r"^\+\+\+\s+b/.+\.yaml\b", patch_corpus, re.MULTILINE):
        return []
    if not _CORPUS_COMPAT_CONST_SIMPLE_RE.search(patch_corpus):
        return []
    # Check all blocks together
    visible_all = "\n".join(
        f"{b.subject}\n{b.raw_html}" for b in report.blocks
    )
    # The review must either: discuss the compatible shape (mention const/oneOf/
    # fallback/parent wrapper) AND cite a parent wrapper path, OR declare no
    # parent wrapper exists.
    has_discussion = bool(_COMPAT_FALLBACK_PROOF_RE.search(visible_all))
    has_parent_path = _has_specific_parent_wrapper_path(visible_all)
    no_parent_declared = bool(re.search(
        r"no\s+parent\s+(?:wrapper\s+)?(?:schema|binding|yaml)(?:\s+exists)?|"
        r"this\s+binding\s+has\s+no\s+(?:parent|wrapper)",
        visible_all, re.IGNORECASE,
    ))
    if no_parent_declared:
        return []
    if has_discussion and has_parent_path:
        return []
    return [Violation(
        "binding_compatible_shape",
        "report (corpus-derived)",
        "patch series adds a new YAML binding with a single-string compatible "
        "schema, but the review does not discuss compatible shape "
        "(oneOf/fallback/parent wrapper) and does not cite a parent/wrapper "
        "schema path; an over-strict compatible contract can reject valid DTS "
        "users and slip through review — see refs/dt-binding.md",
    )]


# Source-aware backstop for PM resume OPP regression.
# Fires when the patch corpus shows a runtime_resume function that:
#   - removed a dev_pm_opp_set_rate() call (old body had it, new body doesn't)
# AND the review does not flag this as a bug or concern.
_RESUME_FUNC_RE = re.compile(
    r"runtime_resume|pm_resume|resume_noirq",
    re.IGNORECASE,
)
_OPP_SET_RATE_REMOVED_RE = re.compile(
    r"^-.*dev_pm_opp_set_rate",
    re.MULTILINE,
)
_OPP_SET_RATE_ADDED_RE = re.compile(
    r"^\+.*dev_pm_opp_set_rate",
    re.MULTILINE,
)

_RESOURCE_SETUP_HELPER_ADDED_RE = re.compile(
    r"^\+[^+].*\b\w*(?:resources?|init|setup|prepare|acquire)\w*\s*\(",
    re.MULTILINE,
)
_RESOURCE_GET_REMOVED_RE = re.compile(
    r"^-.*?\b(?:devm_)?(?P<resource>[A-Za-z][A-Za-z0-9]*)_get\s*\(",
    re.MULTILINE,
)
_RESOURCE_GET_GUARD_EXCLUSIONS = {
    "device",
    "dev",
    "fwnode",
    "of",
    "platform",
    "pm_runtime",
}


def _removed_get_resource_types(patch_corpus: str) -> set[str]:
    return {
        match.group("resource")
        for match in _RESOURCE_GET_REMOVED_RE.finditer(patch_corpus)
        if match.group("resource") not in _RESOURCE_GET_GUARD_EXCLUSIONS
    }


def _resource_api_use(text: str, resource: str) -> bool:
    return bool(re.search(
        rf"\b{re.escape(resource)}_[A-Za-z0-9_]+\s*\(",
        text,
        re.IGNORECASE,
    ))


def _resource_guard_added(patch_corpus: str, resource: str) -> bool:
    return bool(re.search(
        rf"^\+[^+].*(?:IS_ERR(?:_OR_NULL)?|PTR_ERR)\s*\([^)]*"
        rf"{re.escape(resource)}[^)]*\)",
        patch_corpus,
        re.IGNORECASE | re.MULTILINE,
    ))


def _resource_guard_review_proof(text: str, resource: str) -> bool:
    resource_re = re.escape(resource)
    resource_mention = (
        rf"(?:\b{resource_re}\b|\b{resource_re}_[A-Za-z0-9_]*\b|"
        rf"(?:->|\.){resource_re}\b)"
    )
    guard_terms = r"(?:IS_ERR|ERR_PTR|PTR_ERR|error pointer|guard|unchecked|dereference|null)"
    return bool(re.search(
        rf"{resource_mention}[\s\S]{{0,180}}?{guard_terms}|"
        rf"{guard_terms}[\s\S]{{0,180}}?{resource_mention}",
        text,
        re.IGNORECASE,
    ))
_MATCH_DATA_ASSIGN_ADDED_RE = re.compile(
    r"^\+\s*(?:[\w\s\*]+?\s+)?(?P<expr>\w+(?:->\w+)*)\s*=\s*"
    r"(?:device_get_match_data|of_device_get_match_data)\s*\(",
    re.MULTILINE,
)


def _has_specific_parent_wrapper_path(text: str) -> bool:
    for match in _COMPAT_PARENT_PATH_RE.finditer(text):
        token = match.group(0).strip()
        basename = token.rsplit("/", 1)[-1].lower()
        if basename in _GENERIC_PARENT_PATH_BASENAMES:
            continue
        return True
    return False


def _resume_side_effect_block(block: CommitBlock) -> bool:
    visible = f"{block.subject}\n{block.raw_html}"
    has_resume_context = bool(re.search(
        r"runtime_resume|resume path|resume helper|geni_se_resources_activate",
        visible,
        re.IGNORECASE,
    ))
    has_removed_vote_context = bool(re.search(
        r"dev_pm_opp_set_rate|performance state|OPP rate|cur_sclk_hz",
        visible,
        re.IGNORECASE,
    ))
    return has_resume_context and has_removed_vote_context


def _match_data_block(block: CommitBlock) -> bool:
    visible = f"{block.subject}\n{block.raw_html}"
    return bool(_MATCH_DATA_REF_RE.search(visible))


def check_resource_helper_guard_source_aware(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path] = None,
) -> list[Violation]:
    """Require review proof for helper-populated resource handle guards.

    If a patch removes direct resource acquisition, replaces setup with a helper,
    and touched code still calls APIs for that resource type, the review must
    either flag the missing error guard or prove the helper-populated handle is
    guarded before use.
    """
    if not patch_corpus:
        return []
    if not _RESOURCE_SETUP_HELPER_ADDED_RE.search(patch_corpus):
        return []

    resource_types = _removed_get_resource_types(patch_corpus)
    if not resource_types:
        return []

    searched_text = patch_corpus
    if source_root is not None:
        for relpath in _source_files_from_patch_corpus(patch_corpus):
            path = source_root / relpath
            if not path.is_file():
                continue
            try:
                searched_text += "\n" + path.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                continue

    violations: list[Violation] = []
    for resource in sorted(resource_types):
        if not _resource_api_use(searched_text, resource):
            continue
        if _resource_guard_added(patch_corpus, resource):
            continue
        finding_has_proof = False
        for block in report.blocks:
            for finding in block.findings:
                if finding.severity not in ("BUG", "CONCERN"):
                    continue
                finding_text = f"{finding.title}\n{finding.body}"
                if _resource_guard_review_proof(finding_text, resource):
                    finding_has_proof = True
                    break
            if finding_has_proof:
                break
        if finding_has_proof:
            continue
        violations.append(Violation(
            "resource_helper_guard_source_aware",
            f"report (corpus-derived: {resource})",
            "patch removes direct resource acquisition and routes setup through "
            "a helper while touched source still calls APIs for that resource "
            "type; the review must flag or prove the required error/pointer "
            "guard for helper-populated resource handles",
        ))
    return violations


def check_helper_side_effect_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Source-aware backstop for replaced-helper side effects.
    When the patch corpus removes a side-effecting call from a resume-style
    function without adding it back, the review must flag the missing side
    effect as a bug or concern. This catches helper-equivalence claims made
    without reading the replacement helper source."""
    if not patch_corpus:
        return []
    # Must have a resume function in scope
    if not _RESUME_FUNC_RE.search(patch_corpus):
        return []
    # Must have removed a dev_pm_opp_set_rate call
    if not _OPP_SET_RATE_REMOVED_RE.search(patch_corpus):
        return []
    # If the patch also adds dev_pm_opp_set_rate back, it's handled
    if _OPP_SET_RATE_ADDED_RE.search(patch_corpus):
        return []
    candidate_blocks = [b for b in report.blocks if _resume_side_effect_block(b)]
    if not candidate_blocks:
        candidate_blocks = report.blocks
    # Only an actual BUG/CONCERN finding clears this backstop. A before/after
    # diff summary that merely repeats the removed dev_pm_opp_set_rate() call
    # is not evidence that the regression was recognized.
    for block in candidate_blocks:
        for finding in block.findings:
            text = f"{finding.title} {finding.body}".lower()
            mentions_restore_regression = (
                "opp" in text
                or "dev_pm_opp_set_rate" in text
                or "performance state" in text
                or ("resume" in text and "rate" in text)
            ) and any(
                token in text for token in (
                    "not restored",
                    "missing",
                    "dropped",
                    "removed",
                    "no longer restores",
                )
            )
            if finding.severity in ("BUG", "CONCERN") and mentions_restore_regression:
                return []
    return [Violation(
        "helper_side_effect_source_aware",
        "report (corpus-derived)",
        "patch corpus removes a side-effecting call from a resume-style "
        "function without restoring it, but no review block flags the missing "
        "side effect as a [BUG] or [CONCERN]; replacement helpers must be "
        "checked from source, not assumed equivalent by name or context",
    )]


def check_match_data_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Source-aware backstop for unguarded match-data dereferences.

    When a patch adds `device_get_match_data()` and then dereferences the
    returned pointer without adding a NULL guard, the review must flag the
    risk as a [BUG]/[CONCERN]. Naming `driver_override` or future table
    maintenance in prose is not sufficient evidence that the dereference is
    actually safe.
    """
    if not patch_corpus:
        return []
    vars_needing_findings: set[str] = set()
    for match in _MATCH_DATA_ASSIGN_ADDED_RE.finditer(patch_corpus):
        expr = match.group("expr")
        deref_re = re.compile(rf"^\+.*{re.escape(expr)}\s*->", re.MULTILINE)
        guard_re = re.compile(
            rf"^\+.*(?:if\s*\(\s*!\s*{re.escape(expr)}\s*\)|"
            rf"IS_ERR_OR_NULL\s*\(\s*{re.escape(expr)}\s*\)|"
            rf"!{re.escape(expr)}\s*\?)",
            re.MULTILINE,
        )
        if deref_re.search(patch_corpus) and not guard_re.search(patch_corpus):
            vars_needing_findings.add(expr)
    if not vars_needing_findings:
        return []

    candidate_blocks = [b for b in report.blocks if _match_data_block(b)]
    if not candidate_blocks:
        candidate_blocks = report.blocks
    for block in candidate_blocks:
        for finding in block.findings:
            text = f"{finding.title} {finding.body}".lower()
            if finding.severity in ("BUG", "CONCERN") and (
                "device_get_match_data" in text
                or "of_device_get_match_data" in text
                or "match_data" in text
                or "driver_override" in text
                or "manual bind" in text
                or "sysfs bind" in text
                or "future table" in text
                or "missing .data" in text
            ):
                return []

    return [Violation(
        "match_data_source_aware",
        "report (corpus-derived)",
        "patch corpus adds `device_get_match_data()` and dereferences the "
        "result without adding a NULL guard, but no review block flags the "
        "risk as a [BUG] or [CONCERN]; manual/non-OF bind paths and future "
        "match-table changes keep this dereference reviewable",
    )]


def check_touched_unsafe_pm_source_aware(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path] = None,
) -> list[Violation]:
    """Source-aware backstop for touched unsafe runtime-PM get patterns.

    When a patch touches a source file and the diff/context shows a bare
    `pm_runtime_get_sync()` statement, the review must either flag it or prove
    the return is checked/balanced.  This intentionally covers pre-existing
    hazards exposed by the touched execution path, not only newly added lines.
    """
    if not patch_corpus:
        return []
    touched_files = _source_files_from_patch_corpus(patch_corpus)
    if not touched_files:
        return []
    searched_text = patch_corpus
    source_hits: list[str] = []
    if source_root is not None:
        for relpath in touched_files:
            path = source_root / relpath
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            searched_text += "\n" + text
            if _PM_RUNTIME_BARE_GET_SYNC_RE.search(text):
                source_hits.append(relpath)
    if not _PM_RUNTIME_BARE_GET_SYNC_RE.search(searched_text):
        return []

    visible_all = "\n".join(
        f"{b.subject}\n{b.raw_html}" for b in report.blocks
    )
    if (
        _PM_RUNTIME_FINDING_RE.search(visible_all)
        and _PM_RUNTIME_GET_SYNC_PROOF_RE.search(visible_all)
    ):
        return []

    return [Violation(
        "touched_unsafe_pm_source_aware",
        "report (corpus-derived)",
        "patch corpus touches source code whose diff/context contains a bare "
        "`pm_runtime_get_sync()` statement, but the report does not flag or "
        "prove the return-value/balancing contract; touched pre-existing "
        "runtime-PM hazards must be reviewed when the changed path can still "
        "reach them"
        + (f" (post-apply source hits: {', '.join(source_hits)})" if source_hits else ""),
    )]


def check_resource_abstraction_bypass_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Source-aware backstop for resource abstraction bypasses.

    If a patch introduces or routes through a resource/rate/power abstraction,
    a report may not clear an alternate mode/path as safe merely because that
    path does not call the new abstraction.  It must either file a finding or
    prove the path is unreachable/contract-compatible with concrete selector
    and callee evidence.
    """
    if not patch_corpus:
        return []
    if not _RESOURCE_ABSTRACTION_INTRO_RE.search(patch_corpus):
        return []

    violations: list[Violation] = []
    for block in report.blocks:
        visible = f"{block.subject}\n{block.raw_html}"
        if not _RESOURCE_ABSTRACTION_BYPASS_SAFE_RE.search(visible):
            continue

        has_finding = any(
            finding.severity in ("BUG", "CONCERN")
            and _RESOURCE_ABSTRACTION_BYPASS_FINDING_RE.search(
                f"{finding.title}\n{finding.body}"
            )
            for finding in block.findings
        )
        if has_finding:
            continue

        violations.append(Violation(
            "resource_abstraction_bypass_source_aware",
            f"block#{block.index} '{block.subject[:60]}'",
            "report clears an alternate execution path as safe while saying it "
            "does not call/use the new resource/rate/power abstraction.  A safe "
            "dismissal must prove the path is unreachable for the affected "
            "descriptor/platform or that every old-helper side effect remains "
            "contract-compatible; otherwise file a [BUG]/[CONCERN]",
        ))
    return violations

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------



def _infer_patch_number(path: Path, html: str = "") -> int:
    for text in (path.name, html):
        match = re.search(r"patch[-_](\d+)(?:[-_]finding|[-_]block)?", text)
        if match:
            return int(match.group(1))
    return 1


def _tests_text_from(tests_path: Optional[Path], html: str = "") -> str:
    if tests_path and tests_path.exists():
        return tests_path.read_text(encoding="utf-8", errors="replace")
    if html:
        match = re.search(
            r"Build[^<]*</td>\s*<td[^>]*>\s*<span[^>]*>([A-Z]+)</span>",
            html,
        )
        if match:
            return f"Build: {match.group(1)}"
    return ""


def _print_violations(name: str, violations: list[Violation]) -> int:
    by_check: dict[str, list[Violation]] = {}
    for violation in violations:
        by_check.setdefault(violation.check, []).append(violation)

    print(f"FAIL: {name} — {len(violations)} violations:")
    for check, items in by_check.items():
        print(f"\n[{check}] ({len(items)} violations)")
        for violation in items[:30]:
            print(violation)
        if len(items) > 30:
            print(f"  ... and {len(items) - 30} more")
    return 1


def _load_patch_file(path: Optional[Path]) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def check_prompt_file(
    *,
    prompt_file: Optional[Path],
    block_file: Path,
    patch_number: int,
    tests_path: Optional[Path],
    build_file: Optional[Path],
    evidence_file: Optional[Path],
) -> list[Violation]:
    """Validate the saved per-patch prompt used to create a block.

    This makes the prompt itself an artifact: block repair can re-open exactly
    what the reviewer saw, and early validation can catch missing per-patch
    inputs before final report assembly.
    """
    if prompt_file is None:
        return []
    if not prompt_file.exists():
        return [Violation(
            "prompt_artifact",
            str(prompt_file),
            "per-patch prompt file is referenced but does not exist",
        )]
    prompt = prompt_file.read_text(encoding="utf-8", errors="replace")
    first_nonblank = next((line.strip() for line in prompt.splitlines() if line.strip()), "")
    violations: list[Violation] = []
    if not (first_nonblank.startswith("Read ") and f"patch_{patch_number}_rules.md" in first_nonblank):
        violations.append(Violation(
            "prompt_artifact",
            str(prompt_file),
            "first non-empty prompt line must read the matching "
            f"`patch_{patch_number}_rules.md` rules brief",
        ))

    required_fragments = [
        "Patch hash:",
        "Patch subject:",
        "Patch type:",
        f"patch_{patch_number}_diff.txt",
        "Context files:",
        "Series summary:",
        "Tests file:",
        "Build file:",
        "Sparse file:",
        "Block file:",
        "Sidecar file:",
    ]
    if evidence_file is not None:
        required_fragments.extend(["Evidence file:", str(evidence_file), evidence_file.name])
    if tests_path is not None:
        required_fragments.append(str(tests_path))
    if build_file is not None:
        required_fragments.append(str(build_file))
    required_fragments.extend([str(block_file), block_file.name])

    missing = [fragment for fragment in required_fragments if fragment not in prompt]
    if missing:
        violations.append(Violation(
            "prompt_artifact",
            str(prompt_file),
            "per-patch prompt is missing required input reference(s): "
            + ", ".join(missing[:12]),
        ))
    return violations


def _source_aware_violations(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path],
) -> list[Violation]:
    violations: list[Violation] = []
    if not patch_corpus:
        return violations
    violations.extend(check_pm_runtime_get_sync_source_aware(report, patch_corpus))
    violations.extend(check_dma_names_source_aware(report, patch_corpus))
    violations.extend(check_binding_companion_dependency_source_aware(report, patch_corpus))
    violations.extend(check_binding_compatible_shape_source_aware(report, patch_corpus))
    violations.extend(check_match_data_source_aware(report, patch_corpus))
    violations.extend(check_resource_helper_guard_source_aware(report, patch_corpus, source_root))
    violations.extend(check_helper_side_effect_source_aware(report, patch_corpus))
    violations.extend(check_touched_unsafe_pm_source_aware(report, patch_corpus, source_root))
    violations.extend(check_resource_abstraction_bypass_source_aware(report, patch_corpus))
    return violations


def run_block(
    block_file: Path,
    tests_path: Optional[Path],
    patch_file: Optional[Path] = None,
    prompt_file: Optional[Path] = None,
    build_file: Optional[Path] = None,
    evidence_file: Optional[Path] = None,
    require_patches: bool = False,
    source_root: Optional[Path] = None,
) -> int:
    html = block_file.read_text(encoding="utf-8", errors="replace")
    patch_number = _infer_patch_number(block_file, html)
    report = parse_block_fragment(html, block_index=patch_number - 1)
    tests_text = _tests_text_from(tests_path)
    tmp_dir = block_file.parent
    if tests_path is not None:
        tmp_dir = tests_path.parent
    if build_file is not None:
        tmp_dir = build_file.parent

    violations: list[Violation] = []
    if len(report.blocks) != 1:
        violations.append(Violation(
            "block_fragment",
            str(block_file),
            f"block-mode validation expects exactly one commit-block, found {len(report.blocks)}",
        ))
    violations.extend(check_gate_traces(report))
    violations.extend(check_step_records(report))
    violations.extend(check_conditional_sections(report))
    violations.extend(check_block_anchor_ids(report))
    violations.extend(check_build_break_order(report, tests_text, require_banner=False))
    violations.extend(check_build_artifact_validity(report, tmp_dir))
    violations.extend(check_render_format(report))
    violations.extend(check_hardware_trigger_consistency(report))
    violations.extend(check_refactor_coverage(report))
    violations.extend(check_future_risk_gate(report))
    violations.extend(check_safe_clearance_gate(report))
    violations.extend(check_compatible_fallback(report))
    violations.extend(check_match_data_guard(report))
    violations.extend(check_pm_runtime_get_sync(report))
    violations.extend(check_dma_names_example(report))
    violations.extend(check_fast_path_restore_proof(report))
    violations.extend(check_codebase_audit_record(report))
    violations.extend(check_codebase_audit_required(report))
    violations.extend(check_on_demand_reads_record(report))
    violations.extend(check_inconclusive_requires_read_attempt(report))
    violations.extend(check_severity_crash_floor(report))
    violations.extend(check_severity_restore_floor(report))
    violations.extend(check_helper_equivalence_requires_source_proof(report))
    violations.extend(check_prompt_file(
        prompt_file=prompt_file,
        block_file=block_file,
        patch_number=patch_number,
        tests_path=tests_path,
        build_file=build_file,
        evidence_file=evidence_file,
    ))
    evidence_manifest = _load_evidence_manifest(evidence_file)
    evidence_by_block = {patch_number - 1: evidence_manifest} if evidence_manifest else {}
    violations.extend(check_evidence_manifest_record(report, evidence_by_block))
    violations.extend(check_evidence_required_reads(report, evidence_by_block))

    patch_corpus = _load_patch_file(patch_file)
    if require_patches and not patch_corpus:
        violations.append(Violation(
            "source_corpus_required",
            f"block#{patch_number}",
            "block-mode validation requires the patch diff/corpus for this "
            "patch so source-aware checks can run before final assembly",
        ))
    violations.extend(_source_aware_violations(report, patch_corpus, source_root))

    if not violations:
        print(
            f"PASS: {block_file.name} — patch {patch_number}, "
            f"{sum(len(b.findings) for b in report.blocks)} findings"
        )
        return 0
    return _print_violations(block_file.name, violations)


def run(
    html_path: Path,
    tests_path: Optional[Path],
    patches_dir: Optional[Path] = None,
    require_patches: bool = False,
    source_root: Optional[Path] = None,
    evidence_dir: Optional[Path] = None,
) -> int:
    html = html_path.read_text(encoding="utf-8")
    report = parse_report(html)

    if report.verdict == "CANNOT APPLY" and not report.blocks:
        print(f"PASS: {html_path.name} — CANNOT APPLY report")
        return 0

    tests_text = _tests_text_from(tests_path, html)

    tmp_dir: Optional[Path] = None
    if tests_path is not None:
        tmp_dir = tests_path.parent
    elif (Path.cwd() / "tmp").is_dir():
        tmp_dir = Path.cwd() / "tmp"

    violations: list[Violation] = []
    violations.extend(check_gate_traces(report))
    violations.extend(check_step_records(report))
    violations.extend(check_conditional_sections(report))
    violations.extend(check_banner_consistency(report))
    violations.extend(check_block_anchor_ids(report))
    violations.extend(check_banner_dedup(report))
    violations.extend(check_build_break_order(report, tests_text))
    violations.extend(check_build_artifact_validity(report, tmp_dir))
    violations.extend(check_render_format(report))
    violations.extend(check_hardware_trigger_consistency(report))
    violations.extend(check_refactor_coverage(report))
    violations.extend(check_future_risk_gate(report))
    violations.extend(check_safe_clearance_gate(report))
    violations.extend(check_compatible_fallback(report))
    violations.extend(check_match_data_guard(report))
    violations.extend(check_pm_runtime_get_sync(report))
    violations.extend(check_dma_names_example(report))
    violations.extend(check_fast_path_restore_proof(report))
    violations.extend(check_codebase_audit_record(report))
    violations.extend(check_codebase_audit_required(report))
    violations.extend(check_on_demand_reads_record(report))
    violations.extend(check_inconclusive_requires_read_attempt(report))
    violations.extend(check_severity_crash_floor(report))
    violations.extend(check_severity_restore_floor(report))
    violations.extend(check_helper_equivalence_requires_source_proof(report))
    evidence_by_block = _load_evidence_dir(evidence_dir)
    violations.extend(check_evidence_manifest_record(report, evidence_by_block))
    violations.extend(check_evidence_required_reads(report, evidence_by_block))

    # Derive series_id from the Message-ID in the HTML to scope the
    # patch corpus to only this series' mbox files, avoiding cross-
    # contamination from other series in the same tmp directory.
    # Extract series_id from the Message-ID header in the report table.
    # Two formats seen in the wild:
    #   <code>&lt;msgid@host&gt;</code>  (HTML-encoded angle brackets)
    #   <code>msgid@host</code>           (plain, no angle brackets)
    _mid_re = re.compile(
        r"Message-ID.*?<code>(?:&lt;)?([^&<>@\s]+@[^&<>\s]+?)(?:&gt;)?</code>",
        re.IGNORECASE | re.DOTALL,
    )
    _mid_m = _mid_re.search(html)
    series_id = _mid_m.group(1) if _mid_m else ""
    patch_corpus = _load_patch_corpus(patches_dir, series_id=series_id)
    if require_patches and not patch_corpus:
        violations.append(Violation(
            "source_corpus_required",
            "report (daemon validation)",
            "daemon validation requires a non-empty patch corpus so source-aware "
            "backstops cannot be silently downgraded to HTML-only validation",
        ))
    if patch_corpus:
        violations.extend(_source_aware_violations(report, patch_corpus, source_root))

    if not violations:
        print(
            f"PASS: {html_path.name} — "
            f"{len(report.blocks)} commit-blocks, "
            f"{sum(len(b.findings) for b in report.blocks)} findings, "
            f"{len(report.verdict_banner)} banner cards"
        )
        return 0

    return _print_violations(html_path.name, violations)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "html_path",
        type=Path,
        nargs="?",
        help="path to the assembled review HTML",
    )
    ap.add_argument(
        "--block-file",
        type=Path,
        default=None,
        help="single tmp/patch_N_block.html fragment to validate before final assembly",
    )
    ap.add_argument(
        "--patch-file",
        type=Path,
        default=None,
        help="single patch diff/mbox for --block-file source-aware validation",
    )
    ap.add_argument(
        "--prompt-file",
        type=Path,
        default=None,
        help="saved per-patch subagent prompt for --block-file validation",
    )
    ap.add_argument(
        "--build-file",
        type=Path,
        default=None,
        help="per-patch build log for --block-file validation",
    )
    ap.add_argument(
        "--evidence-file",
        type=Path,
        default=None,
        help="per-patch evidence manifest for --block-file validation",
    )
    ap.add_argument(
        "--tests",
        type=Path,
        default=None,
        help="path to tests_<slug>.txt for build-break detection (optional)",
    )
    ap.add_argument(
        "--patches-dir",
        type=Path,
        default=None,
        help="directory containing the patch series mbox/.patch files; "
             "enables source-aware backstops for touched PM, DT, helper, "
             "and resource-abstraction checks (optional unless "
             "--require-patches is set)",
    )
    ap.add_argument(
        "--require-patches",
        action="store_true",
        help="fail if --patches-dir does not yield a non-empty patch corpus; "
             "daemon reviews should set this so validation cannot downgrade "
             "to HTML-only checks",
    )
    ap.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help="post-apply source tree root; enables source-aware checks that "
             "must inspect touched files beyond patch hunk context",
    )
    ap.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
        help="directory containing patch_<N>_evidence.json manifests for "
             "assembled-report validation",
    )
    args = ap.parse_args(argv)

    if args.block_file is not None:
        if not args.block_file.exists():
            print(f"error: {args.block_file} does not exist", file=sys.stderr)
            return 2
        return run_block(
            args.block_file,
            args.tests,
            patch_file=args.patch_file,
            prompt_file=args.prompt_file,
            build_file=args.build_file,
            evidence_file=args.evidence_file,
            require_patches=args.require_patches,
            source_root=args.source_root,
        )

    if args.html_path is None:
        print("error: html_path is required unless --block-file is used", file=sys.stderr)
        return 2
    if not args.html_path.exists():
        print(f"error: {args.html_path} does not exist", file=sys.stderr)
        return 2
    return run(
        args.html_path,
        args.tests,
        args.patches_dir,
        args.require_patches,
        args.source_root,
        args.evidence_dir,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
