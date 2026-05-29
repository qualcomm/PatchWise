#!/usr/bin/env python3
"""All validator checks and supporting data for the review-commits skill.

Contains:
  - Constants, regex patterns, REMEDIATION, VALIDATOR_COVERAGE tables
  - Violation class
  - Structural check_* functions (check_gate_traces, check_step_records, …)
  - Shared helper functions used by source-aware checks
  - Source-aware check_* functions (check_*_source_aware)
  - _RULE_CARD_ATTESTATION_MARKERS / _PREDICATE
  - check_rule_card_attestation, check_rule_card_coverage
  - _REPORT_ONLY_CHECKS, _source_aware_violations

Imports: _review_model (data model only).
Imported by: validate_review.py (entry point).
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

# Import all model symbols so check functions can reference any constant or
# regex defined in the model section (e.g. SUB_RULE_TRACE_RE, _HARDWARE_*).
from _review_model import *   # noqa: F401,F403
# Also explicit for IDE type-checking:
from _review_model import (
    FindingCard, CommitBlock, Report,
    ReviewParser, _CardScopedParser,
    parse_report, parse_block_fragment,
    # Explicitly re-export private names that this module uses:
    _CardScopedParser,
    _DEFAULT_REVIEW_PACKET_MODE,
    _RUNTIME_CONFIG_SCHEMA,
    _SPARSE_DISABLED_MARKER,
    _SPARSE_DISABLED_SUMMARY_RE,
)

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
_BUILD_FAILURE_MENTION_RE = re.compile(
    r"\b(?:w=1\s+)?build(?:\s*\([^)]*\))?\s+"
    r"(?:fail|fails|failed|failure)\b"
    r"|\b(?:fail|fails|failed|failure)\b.{0,80}\bbuild\b"
    r"|\bfails\s+to\s+compile\b"
    r"|\bcompile(?:r)?\s+(?:error|fail|fails|failed|failure)\b",
    re.IGNORECASE | re.DOTALL,
)
_PRE_EXISTING_BUILD_PROOF_RE = re.compile(
    r"\bpre[- ]?existing\b"
    r"|\bbase\s+(?:tree|tag|commit|branch|kernel)\b"
    r"|\bbefore\s+applying\s+(?:this\s+)?patch\b"
    r"|\bnot\s+introduced\s+by\s+(?:this\s+)?patch\b"
    r"|\balready\s+(?:fail|fails|failed|broken)\b",
    re.IGNORECASE,
)

# Build logs containing Kconfig syncconfig prompt transcripts are not valid
# W=1 evidence.  run_w1_build.py must seed defconfig and olddefconfig before the
# build phase; after that, "Restart config..." or EOF prompt errors mean the
# artifact captured configuration interaction instead of clean build output.
_INTERACTIVE_KCONFIG_BUILD_PATTERNS = (
    re.compile(r"Restart config\.\.\.", re.IGNORECASE),
    re.compile(r"Error in reading or end of file\.", re.IGNORECASE),
)

_STRONG_HARDWARE_RE = re.compile(
    r"\b(runtime_(?:suspend|resume)|system_(?:suspend|resume)|"
    r"dev_pm_opp_|dev_pm_domain_|pm_runtime_|geni_se_resources_|"
    r"geni_se_clk_|geni_icc_|icc_(?:set|enable|disable)|"
    r"clk_round_rate|get_.*clk_cfg|setup_gsi_xfer|setup_se_xfer|"
    r"dma_request_chan|dmaengine_|pinctrl_pm_|power[-_ ]?domain|"
    r"performance[-_ ]?(?:state|vote)|\bopp\b|"
    r"thermal_(?:of_)?cooling_device_register|thermal_cooling_device_unregister|"
    r"#cooling-cells|tmd-names|cooling-device|cooling-map|"
    r"trip[-_ ]?(?:temp|point)|hysteresis|polling-delay-passive|"
    r"qmi_tmd|max_(?:state|mitigation_level)|set_cur_state)",
    re.IGNORECASE,
)
_HARDWARE_NA_RE = re.compile(
    r"step_3f_hardware_eng:\s*N/A|"
    r"Hardware Engineering Notes\s+Not applicable",
    re.IGNORECASE,
)
_HARDWARE_DONE_RE = re.compile(r"step_3f_hardware_eng:\s*DONE\b", re.IGNORECASE)
_HARDWARE_SECTION_RE = re.compile(
    r"<h3>\s*Hardware Engineering Notes\s*</h3>(.*?)(?=<h3\b|</div><!-- /commit-block -->|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_GENERIC_HARDWARE_NOTE_RE = re.compile(
    r"consistent with platform specifications|"
    r"DTB check passed|"
    r"reviewed[^.]{0,100}found no immediate issue|"
    r"looks (?:ok|okay|good|clean)|"
    r"no (?:hardware )?issues? found",
    re.IGNORECASE,
)
_HARDWARE_EVIDENCE_RE = re.compile(
    r"#cooling-cells|cooling-device|cooling-maps|tmd-names|THERMAL_NO_LIMIT|"
    r"remoteproc_[A-Za-z0-9_]+|tsens\d*|trip[-_]?point\d+|"
    r"hysteresis\s*(?:=|<|\d)|0x[0-9a-f]+|<\s*\d+|"
    r"\b\d+\s*(?:C|mC|ms|us|ns|Hz|kHz|MHz|GHz|mV|V)\b|"
    r"QMI_[A-Z0-9_]+|QCOM_[A-Z0-9_]+|pm_runtime_[A-Za-z0-9_]+|"
    r"dev_pm_opp_[A-Za-z0-9_]+|dma(?:engine)?_[A-Za-z0-9_]+|"
    r"\bIRQ\s*\d+|clk_[A-Za-z0-9_]+|regulator_[A-Za-z0-9_]+|"
    r"power[-_ ]?domain|interconnect|\bicc_[A-Za-z0-9_]+",
    re.IGNORECASE,
)
_THERMAL_HW_CONTEXT_RE = re.compile(
    r"thermal|cooling|#cooling-cells|cooling-device|cooling-maps|"
    r"tmd-names|trip[-_]?point|hysteresis|thermal-sensors|THERMAL_NO_LIMIT|tsens",
    re.IGNORECASE,
)
_THERMAL_HARDWARE_EVIDENCE_RE = re.compile(
    r"#cooling-cells|cooling-device|cooling-maps|tmd-names|THERMAL_NO_LIMIT|"
    r"remoteproc_[A-Za-z0-9_]+|tsens\d*|trip[-_]?point\d+|"
    r"hysteresis\s*(?:=|<|\d)|<\s*\d+|\b\d+\s*(?:C|mC)\b|"
    r"QMI_[A-Z0-9_]+|QCOM_[A-Z0-9_]+",
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
_EXPLICIT_NON_DEFECT_RE = re.compile(
    r"\b(?:not a defect|"
    r"no actual mismatch found|"
    r"this is correct|"
    r"current code is correct|"
    r"correct as written|"
    r"acceptable as[- ]is|"
    r"(?:is|remains)\s+acceptable)\b",
    re.IGNORECASE,
)
_PROCESS_ONLY_RE = re.compile(
    r"\b(?:for completeness|"
    r"worth verifying|"
    r"worth double-checking|"
    r"informational(?: note| only)?|"
    r"process(?: note| concern)?|"
    r"review[- ]strategy|"
    r"maintainer preference)\b",
    re.IGNORECASE,
)
_CONCRETE_HARM_RE = re.compile(
    r"\b(?:crash|NULL deref|dereference|oops|deadlock|hang|leak|"
    r"use-after-free|UAF|double free|data corruption|memory corruption|"
    r"out-of-bounds|OOB|compile failure|build break|bisectability|"
    r"regression|misprogram|invalid state|timeout|pm imbalance|"
    r"resource leak|refcount|use after free)\b",
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
_PLATFORM_ENABLEMENT_TRIGGER_RE = re.compile(
    r"\b(?:add|enable|introduce)\s+(?:support|platform|compatible|descriptor|variant)\b|"
    r"\bnew\s+(?:SoC|compatible|platform|descriptor|variant)\b|"
    r"\bplatform[- ]enablement\b|\badd support for\b",
    re.IGNORECASE,
)
_PLATFORM_ENABLEMENT_SCOPE_RE = re.compile(
    r"\b(?:probe|remove|runtime_(?:resume|suspend)|pm_runtime|clock|clk|reset|"
    r"phy|resource|route|routing|pad|stream|selector|cardinality|"
    r"compatible|descriptor|match[- ]data|of_device_id)\b",
    re.IGNORECASE,
)
_PLATFORM_LIFECYCLE_PROOF_RE = re.compile(
    r"cleanup|teardown|error unwind|unwind|release|remove path|disable path|"
    r"cancel_work_sync|free_|put_|device_unregister|dma_release_channel|"
    r"clk_disable_unprepare|regulator_disable",
    re.IGNORECASE,
)
_PLATFORM_FALLBACK_PROOF_RE = re.compile(
    r"fallback|legacy|old dtb|older dtb|new kernel|backward compat|"
    r"still (?:boots|probes|works)|oneOf|items:|wrapper schema|parent wrapper|"
    r"compatible array|legacy parser|optional resource|compatibility path",
    re.IGNORECASE,
)
_PLATFORM_SELECTOR_CARDINALITY_PROOF_RE = re.compile(
    r"selector|cardinality|pad count|stream count|clock-names|dma-names|"
    r"reset-names|provider array|parent map|route|routing topology|"
    r"count/order|compatible-selected|mode bit|match table|num_[A-Za-z0-9_]+",
    re.IGNORECASE,
)

# A binding review that introduces/changes a `compatible:` defined as a bare
# `const:` must show it cross-checked the parent/wrapper + sibling schemas for
# a SoC fallback array (oneOf/items).  Otherwise an over-strict `const:` that
# rejects a valid `[variant, base]` fallback (failing dtbs_check) slips by.
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
_ESCAPED_LOCAL_REPORT_RE = re.compile(
    r"stack (?:address|local)|local variable|lifetime|dangling pointer|"
    r"use-after-return|temporary object|drvdata|platform_data|clientdata",
    re.IGNORECASE,
)
_SETUP_RETURN_DISCUSSION_RE = re.compile(
    r"unchecked|ignored return|return value|missing guard|error path|"
    r"checked before|guarded before|propagat(?:e|ed)|existing guard|cannot fail",
    re.IGNORECASE,
)
_SILENT_SETTER_FAILURE_REPORT_RE = re.compile(
    r"silent (?:failure|loss|drop)|ignored return|return value|dropped return|"
    r"newly exposed|newly reachable|accepted value|advertised valid value|"
    r"rejects?\s+0|min\s*=\s*0|bulk apply|apply all properties|"
    r"configuration loss|setter failure",
    re.IGNORECASE,
)
_OPTIONAL_CLK_DEAD_ENOENT_REPORT_RE = re.compile(
    r"devm_clk_bulk_get_optional|optional clock|optional clk|optional resource|"
    r"-ENOENT|ENOENT|dead fallback|unreachable fallback|missing optional",
    re.IGNORECASE,
)
_REQUIRED_CLK_ZERO_COUNT_REPORT_RE = re.compile(
    r"(?:devm_clk_bulk_get_all|bulk_get_all)[\s\S]{0,220}?"
    r"(?:zero[- ]?(?:clock|clk|count|resource)|no\s+(?:clocks|clks|resources)|"
    r"returns?\s+0|return(?:ed|ing)?\s+zero|<=\s*0|==\s*0|<\s*1)|"
    r"(?:zero[- ]?(?:clock|clk|count|resource)|no\s+(?:clocks|clks|resources)|"
    r"returns?\s+0|return(?:ed|ing)?\s+zero|<=\s*0|==\s*0|<\s*1)"
    r"[\s\S]{0,220}?(?:devm_clk_bulk_get_all|bulk_get_all)",
    re.IGNORECASE,
)
_REQUIRED_CLK_ZERO_COUNT_ACTION_RE = re.compile(
    r"missing|lacks?|without|unguarded|not\s+handled|not\s+checked|"
    r"must|should|needs?|require|flag|finding|concern|bug|risk|"
    r"underflow|unbalanced|WARN_ON|reject|error\s+out|return\s+-",
    re.IGNORECASE,
)
_REQUIRED_CLK_ZERO_COUNT_SAFE_DISMISSAL_RE = re.compile(
    r"(?:SAFE|safe|no\s+issue|not\s+a\s+problem|ok(?:ay)?|impossible|"
    r"cannot|can't|won't|will\s+not|does\s+not|binding\s+requires|"
    r"schema\s+requires|dtbs_check)[\s\S]{0,180}?"
    r"(?:zero|return(?:s|ed)?\s+0|no\s+(?:clocks|clks|resources))|"
    r"(?:zero|return(?:s|ed)?\s+0|no\s+(?:clocks|clks|resources))"
    r"[\s\S]{0,180}?(?:SAFE|safe|no\s+issue|not\s+a\s+problem|"
    r"ok(?:ay)?|impossible|cannot|can't|won't|will\s+not|does\s+not|"
    r"binding\s+requires|schema\s+requires|dtbs_check)",
    re.IGNORECASE,
)
_FRAMEWORK_STATUS_CALLBACK_REPORT_RE = re.compile(
    r"(?:\.is_enabled|is_enabled|\.get_status|get_status|status\s+callback|"
    r"regulator_is_enabled_regmap)[\s\S]{0,260}?"
    r"(?:read|regmap|MMIO|register)[\s\S]{0,260}?"
    r"(?:before\s+(?:\.?enable|clk_bulk_prepare_enable|clocks?|power)|"
    r"without\s+(?:enabling\s+)?(?:clocks?|power)|"
    r"while\s+(?:clocks?|power)\s+(?:are\s+)?(?:off|disabled|not\s+enabled)|"
    r"unpowered|clock[- ]gated|not\s+accessible|inaccessible|bus\s+(?:fault|hang))|"
    r"(?:before\s+(?:\.?enable|clk_bulk_prepare_enable|clocks?|power)|"
    r"without\s+(?:enabling\s+)?(?:clocks?|power)|"
    r"while\s+(?:clocks?|power)\s+(?:are\s+)?(?:off|disabled|not\s+enabled)|"
    r"unpowered|clock[- ]gated|not\s+accessible|inaccessible|bus\s+(?:fault|hang))"
    r"[\s\S]{0,260}?(?:\.is_enabled|is_enabled|\.get_status|get_status|"
    r"status\s+callback|regulator_is_enabled_regmap)[\s\S]{0,260}?"
    r"(?:read|regmap|MMIO|register)",
    re.IGNORECASE,
)
_FRAMEWORK_STATUS_CALLBACK_ACTION_RE = re.compile(
    r"missing|lacks?|without|unguarded|unsafe|must|should|needs?|require|"
    r"flag|finding|concern|bug|risk|can\s+(?:fail|hang|fault)|may\s+(?:fail|hang|fault)",
    re.IGNORECASE,
)
_FRAMEWORK_STATUS_CALLBACK_SAFE_DISMISSAL_RE = re.compile(
    r"(?:SAFE|safe|no\s+issue|not\s+required|not\s+needed|"
    r"clocks?\s+not\s+required|MMIO\s+accessible|per\s+hardware\s+behavior|"
    r"cannot\s+call|can't\s+call)[\s\S]{0,220}?"
    r"(?:\.is_enabled|is_enabled|\.get_status|get_status|status|"
    r"regulator_is_enabled_regmap|MMIO|clocks?)|"
    r"(?:\.is_enabled|is_enabled|\.get_status|get_status|status|"
    r"regulator_is_enabled_regmap|MMIO|clocks?)[\s\S]{0,220}?"
    r"(?:SAFE|safe|no\s+issue|not\s+required|not\s+needed|"
    r"clocks?\s+not\s+required|MMIO\s+accessible|per\s+hardware\s+behavior|"
    r"cannot\s+call|can't\s+call)",
    re.IGNORECASE,
)
_FRAMEWORK_STATUS_CALLBACK_PROOF_RE = re.compile(
    r"datasheet|TRM|hardware\s+manual|schematic|source[- ](?:proven|backed)|"
    r"always[- ]on\s+(?:domain|bus|register|interconnect)|\bAON\b|"
    r"ungated|not\s+clock[- ]gated|clock[- ]independent|"
    r"accessible\s+without\s+clocks|status\s+register[\s\S]{0,80}?always[- ]on",
    re.IGNORECASE,
)
_OLD_KERNEL_NEW_DTB_FALLBACK_REPORT_RE = re.compile(
    r"(?:old(?:er)?\s+kernel|legacy\s+kernel)[\s\S]{0,260}?"
    r"(?:new\s+(?:DTB|DTS|device\s+tree)|fallback|compatible)|"
    r"(?:new\s+(?:DTB|DTS|device\s+tree)|fallback|compatible)[\s\S]{0,260}?"
    r"(?:old(?:er)?\s+kernel|legacy\s+kernel)|"
    r"unsafe\s+fallback|cannot\s+(?:safely\s+)?fall\s*back|"
    r"wrong\s+(?:descriptor|register|match\s+data)|fallback[\s\S]{0,160}?"
    r"(?:mandatory\s+(?:clock|resource)|unclocked|different\s+(?:register|sequence|ops))",
    re.IGNORECASE,
)
_OLD_KERNEL_NEW_DTB_FALLBACK_SAFE_RE = re.compile(
    r"(?:SAFE|safe|no\s+breakage|backward\s+compat|not\s+(?:an\s+)?ABI\s+regression|"
    r"new[- ]platform\s+bringup|new\s+platform|no\s+deployed|no\s+existing|"
    r"old\s+DTBs?\s+are\s+unaffected)[\s\S]{0,260}?"
    r"(?:fallback|old(?:er)?\s+kernel|new\s+(?:DTB|DTS|device\s+tree)|compatible)|"
    r"(?:fallback|old(?:er)?\s+kernel|new\s+(?:DTB|DTS|device\s+tree)|compatible)"
    r"[\s\S]{0,260}?(?:SAFE|safe|no\s+breakage|backward\s+compat|"
    r"not\s+(?:an\s+)?ABI\s+regression|new[- ]platform\s+bringup|new\s+platform|"
    r"no\s+deployed|no\s+existing|old\s+DTBs?\s+are\s+unaffected)",
    re.IGNORECASE,
)
_OLD_KERNEL_NEW_DTB_FALLBACK_ACTION_RE = re.compile(
    r"unsafe|cannot\s+(?:safely\s+)?fall\s*back|wrong\s+(?:descriptor|register|match\s+data)|"
    r"older?\s+kernel[\s\S]{0,180}?(?:panic|crash|SError|abort|fail|hang|"
    r"unclocked|does\s+not\s+enable|won't\s+enable|missing\s+clock|wrong\s+register)|"
    r"fallback[\s\S]{0,180}?(?:panic|crash|SError|abort|fail|hang|"
    r"unclocked|does\s+not\s+enable|won't\s+enable|missing\s+clock|wrong\s+register)",
    re.IGNORECASE,
)
_BOOTLOADER_REFCOUNT_REPORT_RE = re.compile(
    r"(?:bootloader|firmware|already[- ]on|already\s+enabled|left\s+on|"
    r"hardware\s+enabled|skip(?:s|ped)?\s+(?:the\s+)?(?:enable|clk_bulk_prepare_enable))"
    r"[\s\S]{0,260}?(?:underflow|unbalanced|WARN(?:_ON)?|prepare_count|"
    r"enable_count|disable_unprepare|clk_bulk_disable_unprepare)|"
    r"(?:underflow|unbalanced|WARN(?:_ON)?|prepare_count|enable_count|"
    r"disable_unprepare|clk_bulk_disable_unprepare)[\s\S]{0,260}?"
    r"(?:bootloader|firmware|already[- ]on|already\s+enabled|left\s+on|"
    r"hardware\s+enabled|skip(?:s|ped)?\s+(?:the\s+)?(?:enable|clk_bulk_prepare_enable))",
    re.IGNORECASE,
)
_BOOTLOADER_REFCOUNT_SAFE_RE = re.compile(
    r"(?:SAFE|safe|guarantee|guarantees|reference[- ]counts?|balanced|matching)"
    r"[\s\S]{0,220}?(?:disable_unprepare|disable|clk_bulk|prepare|enable)|"
    r"(?:disable_unprepare|disable|clk_bulk|prepare|enable)[\s\S]{0,220}?"
    r"(?:SAFE|safe|guarantee|guarantees|reference[- ]counts?|balanced|matching)",
    re.IGNORECASE,
)
_COMPAT_STRING_RE = re.compile(r"qcom,[a-z0-9][a-z0-9-]+", re.IGNORECASE)
_FALLBACK_CONST_RE = re.compile(
    r"const:\s*['\"]?(?P<compat>qcom,[a-z0-9][a-z0-9-]+)",
    re.IGNORECASE,
)
_ADDED_COMPAT_LINE_RE = re.compile(
    r"^\+(?!\+\+)[^\n#]*(?P<compat>qcom,[a-z0-9][a-z0-9-]+)",
    re.IGNORECASE | re.MULTILINE,
)
_FALLBACK_RESOURCE_QUIRK_RE = re.compile(
    r"has_clocks\s*=\s*true|devm_clk_bulk_get_all|clk_bulk_prepare_enable|"
    r"clk_bulk_disable_unprepare|REFGEN_REG_REFGEN_STATUS|enable_reg\s*=.*STATUS|"
    r"power-domains|required:\s*(?:\n|.){0,120}?clocks",
    re.IGNORECASE,
)
_STATUS_CALLBACK_REFCOUNT_CONTEXT_RE = re.compile(
    r"regulator_is_enabled_regmap|\.(?:is_enabled|get_status)\s*=",
    re.IGNORECASE,
)
_CLK_BULK_ENABLE_DISABLE_RE = re.compile(
    r"clk_bulk_prepare_enable[\s\S]{0,900}?clk_bulk_disable_unprepare|"
    r"clk_bulk_disable_unprepare[\s\S]{0,900}?clk_bulk_prepare_enable",
    re.IGNORECASE,
)
_MANAGED_DEVICE_LINK_REPORT_RE = re.compile(
    r"device_link_(?:add|remove|del)|DL_FLAG_AUTOREMOVE|auto-?remove|"
    r"managed device link|manual (?:remove|delete|cleanup)",
    re.IGNORECASE,
)
_PROVIDER_CELLS_CONST_REPORT_RE = re.compile(
    r"#(?:interconnect|clock|reset|power-domain|phy|gpio|dma|thermal-sensor)-cells"
    r"[\s\S]{0,160}?(?:const|required|fixed)|"
    r"provider cell(?:-| )count[\s\S]{0,160}?const",
    re.IGNORECASE,
)
_COMPAT_TUPLE_REPORT_RE = re.compile(
    r"compatible[\s\S]{0,160}?(?:tuple|length|order|fallback|parent|wrapper|"
    r"oneOf|items|variant|base)|"
    r"(?:tuple|length|order|fallback|parent|wrapper)[\s\S]{0,160}?compatible",
    re.IGNORECASE,
)
_RETAINED_DYNAMIC_CLEANUP_REPORT_RE = re.compile(
    r"static|global|descriptor|retained|stale pointer|retry|rebind|"
    r"dynamic(?:ally)? allocated|freed object|clear(?:ed)?\s+(?:the\s+)?pointer|"
    r"\bNULL\b|use-after-free|cleanup path",
    re.IGNORECASE,
)
_LEVEL_IRQ_REENABLE_REPORT_RE = re.compile(
    r"level[- ]triggered|interrupt storm|enable_irq|re-enable|reenable|"
    r"clear(?:ed)? (?:the )?(?:IRQ|interrupt|source|status)|"
    r"leave(?:s|ing)? (?:the )?(?:IRQ|interrupt) masked|masked before enable",
    re.IGNORECASE,
)
_DT_PROPERTY_DEF_RE = re.compile(
    r"^\+\s{2,}(?P<name>[A-Za-z0-9][A-Za-z0-9,._+-]*):\s*(?:$|#)",
    re.MULTILINE,
)
_OLD_DTB_RESOURCE_NAME_RE = re.compile(
    r"^(?:clocks?|resets?|power-domains|interconnects|dmas?|interrupts?|"
    r"gpios?|[A-Za-z0-9,._+-]+-supply|[A-Za-z0-9,._+-]+-gpios?)$",
    re.IGNORECASE,
)
_OLD_DTB_PROOF_RE = re.compile(
    r"old dtb|older dtb|legacy dtb|new kernel|backward compat|"
    r"still (?:boots|probes|works)|probe still (?:works|succeeds)|"
    r"keeps? old dtb|compatibility path|fallback path|optional resource|"
    r"no fallback (?:chain|compatible|path)|cannot (?:safely )?fall\s*back|"
    r"standalone compatible|no in-tree (?:users|DTS)|"
    r"does not fall\s*back|unsafe to fall\s*back|"
    r"in-tree DTS|existing DTS|old-DTB compatib|"
    r"DT ABI|stable ABI|no existing users",
    re.IGNORECASE,
)
_ADD_SUPPORT_CONTEXT_RE = re.compile(
    r"add support|enable support|new compatible|of_device_id|match[- ]data|"
    r"descriptor|\.data\s*=|compatible\s*=\s*\"",
    re.IGNORECASE,
)
_SELECTOR_CARDINALITY_SURFACE_RE = re.compile(
    r"clock-names|dma-names|reset-names|power-domain-names|interconnect-names|"
    r"num_[A-Za-z0-9_]+|pad(?:s| count)?|stream(?:s| count)?|parent map|"
    r"provider array|route|routing|selector|cardinality",
    re.IGNORECASE,
)
_SELECTOR_CARDINALITY_PROOF_RE = re.compile(
    r"(?:cross-check|compare|compared|matches|mismatch|aligned|consistent|"
    r"same count|same order|selector|cardinality)"
    r"[\s\S]{0,180}?"
    r"(?:clock-names|dma-names|reset-names|power-domain-names|interconnect-names|"
    r"num_[A-Za-z0-9_]+|pad|stream|provider array|parent map|route|routing|"
    r"compatible|descriptor|match table)"
    r"|"
    r"(?:clock-names|dma-names|reset-names|power-domain-names|interconnect-names|"
    r"num_[A-Za-z0-9_]+|pad|stream|provider array|parent map|route|routing|"
    r"compatible|descriptor|match table)"
    r"[\s\S]{0,180}?"
    r"(?:cross-check|compare|compared|matches|mismatch|aligned|consistent|"
    r"same count|same order|selector|cardinality)",
    re.IGNORECASE,
)
_PEER_DIMENSION_REPORT_RE = re.compile(
    r"peer dimension|missing dimension|admission|capacity|one dimension|"
    r"width|height|input|output|rx|tx|src|dst|source|sink|selector|cardinality",
    re.IGNORECASE,
)
_STALE_STATE_REPORT_RE = re.compile(
    r"stale state|failed[- ](?:start|resume|enable|load|boot|activate)|"
    r"failure leaves|state contamination|stale (?:flag|cache|status|load|vote|rate)|"
    r"started|enabled|active|loaded|cached",
    re.IGNORECASE,
)
_PAIRED_CALLBACK_BACKEND_FINDING_RE = re.compile(
    r"paired callback|same session|per-session|session owner|backend owner|"
    r"backend mismatch|wrong backend|"
    r"stale[\s\S]{0,80}(?:reading|prepared|active)|"
    r"(?:normal|original) (?:backend|cleanup|unprepare|teardown)"
    r"[\s\S]{0,160}(?:stale|skip|bypass|wrong|mismatch|fallback|fall back|early-return|same session|per-session)|"
    r"fallback[\s\S]{0,180}(?:normal|original|backend|cleanup|unprepare)|"
    r"(?:unprepare|cleanup)[\s\S]{0,180}"
    r"(?:fallback|return(?:s|ed)? early|early-return|skip|bypass)[\s\S]{0,180}"
    r"(?:normal|original|backend|cleanup|state)|"
    r"(?:return|goto)\s+-[A-Z0-9_]+\s+when\s+![^.;]*(?:reading|prepared|active)",
    re.IGNORECASE,
)

# --- Aggregate-vs-per-element scale (code-logic.md "Aggregate-vs-per-element
# scale audit"). A per-element bandwidth/length/rate term is divided/scaled by a
# width/size taken from the *container* descriptor (`desc->`, `provider->`,
# `qp->desc->`) while the *element* struct exposes a same-dimension field. We
# only fire when BOTH the container-scaled divide AND a per-element same-
# dimension field are visible in the corpus, so legitimate single-source calcs
# and numerator multipliers are not flagged.
_AGG_SCALE_CONTAINER_DIVISOR_RE = re.compile(
    r"(?:div_u64|do_div|div64_u64|/)\s*\(?[^;\n]*?"
    r"\b(?:desc|provider|qp->desc|qp|fabric|global|soc)\s*->\s*"
    r"[A-Za-z0-9_]*(?:bus_width|buswidth|width|stride|channels)\b",
    re.IGNORECASE,
)
_AGG_SCALE_PER_ELEMENT_FIELD_RE = re.compile(
    r"\b(?:node|qn|n|chan|qnode|port|link)\s*->\s*"
    r"(?:buswidth|bus_width|width|channels|stride)\b"
    r"|\.\s*(?:buswidth|channels)\s*=\s*\d",
    re.IGNORECASE,
)
# Concrete per-element width literals, used to test heterogeneity: if every
# element declares the same width the container divisor is harmless.
_AGG_SCALE_WIDTH_VALUE_RE = re.compile(
    r"\.\s*(?:buswidth|width|channels|stride)\s*=\s*(\d+)",
    re.IGNORECASE,
)
_AGG_SCALE_PROOF_RE = re.compile(
    r"per-node (?:bus\s*)?width|per-element (?:width|size)|node->buswidth|"
    r"qn->buswidth|own (?:bus\s*)?width|narrower (?:link|node|bus|port)|"
    r"bandwidth starvation|starv|mis-?scale|wrong (?:divisor|width)|"
    r"divides? by .*(?:fabric|global|desc).*width|"
    r"buswidth.*(?:mismatch|differ|per node|per-node)",
    re.IGNORECASE,
)
# Width-context anchor: vocabulary that proves a proof token is genuinely about
# the per-element width scale (not a coincidental keyword from an unrelated
# finding — e.g. a clock-enable finding that says hardware "may be starved").
# A proof token only clears the violation when it is co-located with one of
# these anchors; see _proof_is_colocated() and the gate in
# check_aggregate_per_element_scale_source_aware().
_AGG_SCALE_WIDTH_CONTEXT_RE = re.compile(
    r"buswidth|bus[_ ]width|per-node (?:bus\s*)?width|per-element|"
    r"narrower (?:link|node|bus|port)|div_u64|div64_u64|do_div|"
    r"each (?:node|element|link)'s (?:own )?width|n->\s*buswidth",
    re.IGNORECASE,
)
# Strong-citation anchor: when the report DISMISSES the per-element-scale
# concern (vs filing a finding), the discharge must cite the in-tree reference
# that actually performs the per-node divide. A keyword-only "matches icc-rpm.c
# convention" is too weak — the v3 case cleared the prior gate with confident
# but factually wrong analysis that named no part of the divisor function. The
# anchors below are the literal symbols the convention argument must touch:
# the per-node field (`qn->buswidth` / `node->buswidth`), the function that
# does the divide (`qcom_icc_calc_rate` — note: NOT `qcom_icc_bus_aggregate`,
# which is the outer iteration helper that does no width arithmetic), or the
# line range that contains it (`div_u64(...qn->buswidth)`). Without any of
# these IN THE REPORT'S OWN TEXT, a discharge has not grounded itself in the
# reference and must keep the find-or-prove obligation. The check uses only
# the visible report text — the patch's own commit message that name-drops
# the convention does NOT count as the reviewer having verified it.
_AGG_SCALE_STRONG_CITATION_RE = re.compile(
    r"qn\s*->\s*buswidth|node\s*->\s*buswidth|"
    r"qcom_icc_calc_rate"
    r"|div_u64\([^)]*\b(?:qn|node)\s*->\s*buswidth\b",
    re.IGNORECASE,
)
# Dismissal language: the report explicitly concludes the rule does NOT apply.
# When this fires alongside the predicate, the discharge requires the strong
# citation above; a generic "no mis-scale" / "matches convention" without
# pointing at the actual per-node divide is the v3 anchoring failure shape.
_AGG_SCALE_DISMISSAL_RE = re.compile(
    r"no mis-?scale|not (?:a|the) mis-?scale|"
    r"discharge[d]?\s*(?:[:.]|$)|no (?:bug|defect|issue|finding)|"
    r"correct (?:denominator|divisor|width|scale|rate)|"
    r"matches (?:the )?(?:icc-rpm\.c|icc-rpm|reference|convention)|"
    r"per icc[-_]rpm|"
    r"clears? the (?:gate|audit|check)|"
    r"the gate (?:clears|passes)",
    re.IGNORECASE,
)

# --- Cross-instance / cross-provider raw pointer held across independent unbind
# (hardware-eng.md lifecycle table + gate-rules.md clearance row). One driver
# instance stores a raw pointer into a sibling that is independently unbindable.
# Fire when the corpus links peer/cross-provider node pointers AND does not set
# `.suppress_bind_attrs = true`, unless the review proves the lifetime guarantee.
_CROSS_INSTANCE_LINK_RE = re.compile(
    r"icc_link_nodes\s*\(|->\s*link_nodes\b|->\s*links\s*\[|"
    r"cross-?(?:fabric|provider)|peer (?:node|provider|fabric)",
    re.IGNORECASE,
)
_SUPPRESS_BIND_ATTRS_RE = re.compile(
    r"\.suppress_bind_attrs\s*=\s*true", re.IGNORECASE
)
_CROSS_INSTANCE_PROOF_RE = re.compile(
    r"suppress_bind_attrs|independently? unbind|unbind via sysfs|sysfs unbind|"
    r"unbound? via sysfs|use-?after-?free.*unbind|unbind.*use-?after-?free|"
    r"dangling.*(?:unbind|peer|sibling|provider|fabric)|"
    r"(?:peer|sibling|target|cross-?(?:fabric|provider)).*(?:get_device|device_link|refcount)|"
    r"(?:get_device|device_link|refcount).*(?:peer|sibling|target|cross-?(?:fabric|provider))|"
    r"removed together|probed.*removed.*together|coordinated (?:teardown|removal)",
    re.IGNORECASE,
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


def _binding_required_resource_names(patch_corpus: str) -> set[str]:
    resources: set[str] = set()
    for _, body in _iter_binding_diff_bodies(patch_corpus):
        in_required = False
        required_indent = -1
        for raw_line in body.splitlines():
            if not raw_line or raw_line[0] not in "+ ":
                continue
            line = raw_line[1:]
            indent = len(line) - len(line.lstrip(" "))
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "required:":
                in_required = True
                required_indent = indent
                continue
            if in_required and indent <= required_indent:
                in_required = False
            if not in_required or raw_line[0] != "+":
                continue
            if not stripped.startswith("- "):
                continue
            name = stripped[2:].strip()
            if _OLD_DTB_RESOURCE_NAME_RE.match(name):
                resources.add(name)
    return resources


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

_SOURCE_FILE_RE = re.compile(
    r"^\+\+\+\s+b/(?P<path>[^\t\n]+\.(?:c|h|cc|cpp|rs))\b",
    re.MULTILINE,
)
_SOURCE_DIFF_RE = re.compile(
    r"^diff --git a/(?P<old>[^\n]+) b/(?P<path>[^\n]+)\n(?P<body>.*?)(?=^diff --git |\Z)",
    re.MULTILINE | re.DOTALL,
)
_CLK_BULK_GET_ALL_ASSIGN_RE = re.compile(
    r"^\+\s*(?P<lhs>[A-Za-z_][A-Za-z0-9_]*(?:(?:->|\.)[A-Za-z_][A-Za-z0-9_]*)*)"
    r"\s*=\s*devm_clk_bulk_get_all\s*\(",
    re.MULTILINE,
)
_STATUS_REGMAP_CALLBACK_ADD_RE = re.compile(
    r"^\+[^+].*\.(?:is_enabled|get_status)\s*=\s*"
    r"regulator_is_enabled_regmap\b",
    re.MULTILINE,
)
_STATUS_CUSTOM_CALLBACK_ADD_RE = re.compile(
    r"^\+[^+].*\.(?:is_enabled|get_status)\s*=\s*"
    r"(?P<callback>[A-Za-z_][A-Za-z0-9_]*)\b",
    re.MULTILINE,
)
_STATUS_CALLBACK_CLOCK_CONTEXT_RE = re.compile(
    r"^\+[^+].*(?:devm_clk_bulk_get_all|clk_bulk_prepare_enable|"
    r"has_clocks\s*=\s*true|num_clks\b|struct\s+clk_bulk_data)",
    re.MULTILINE,
)
_STATUS_CALLBACK_MMIO_BODY_RE = re.compile(
    r"^\+[^+].*(?:regmap_read|readl(?:_relaxed)?|ioread(?:8|16|32|64)?)\s*\(",
    re.MULTILINE,
)
_REQUIRED_CLK_MATCH_DATA_RE = re.compile(
    r"^\+[^+].*\.(?:num_)?clks?\s*=\s*[1-9][0-9]*\b",
    re.IGNORECASE | re.MULTILINE,
)
_PROVIDER_CELL_NAME_RE = re.compile(
    r"^[+ ](?P<indent>\s*)['\"]?(?P<name>#(?:interconnect|clock|reset|"
    r"power-domain|phy|gpio|dma|thermal-sensor)-cells)['\"]?\s*:",
    re.IGNORECASE,
)
_RETAINED_DYNAMIC_ASSIGN_RE = re.compile(
    r"^\+\s*(?P<target>[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]\n]+\])?"
    r"(?:(?:->|\.)[A-Za-z_][A-Za-z0-9_]*)+)\s*=\s*"
    r"(?P<alloc>[A-Za-z_][A-Za-z0-9_]*(?:create_dyn|alloc|create|register|add)"
    r"[A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)
_RETAINED_DYNAMIC_ALLOC_RE = re.compile(
    r"(?:create_dyn|(?:^|_)alloc(?:_|$)|(?:^|_)create(?:_|$)|(?:^|_)register(?:_|$))",
    re.IGNORECASE,
)
_RETAINED_DYNAMIC_CLEANUP_RE = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*(?:remove|destroy|unregister|free|put|cleanup)"
    r"[A-Za-z0-9_]*\s*\(",
    re.IGNORECASE,
)
_IRQ_SOURCE_QUIESCE_RE = re.compile(
    r"(?:clear|ack|mask|disable_irq(?:_nosync)?|writel|write[lq]?_relaxed|"
    r"regmap_(?:write|update_bits)|irq_[A-Za-z0-9_]*(?:clear|ack|mask))\s*\(",
    re.IGNORECASE,
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

# --- Phase 1 false-clearance teeth -----------------------------------------
# These HTML-text checks fire when a block's visible analysis contains a named
# high-risk hardware-eng pattern AND clears it (no [BUG]/[CONCERN] finding) yet
# does NOT quote the concrete discharge line that makes the code safe.  They
# mirror refs/hardware-eng.md (`device_unregister() pointer hygiene`, `Global
# vote scope vs per-block helpers`) and refs/gate-rules.md (Clearance-proof
# rule).  A false clearance — examining a hazard then writing a positive note
# instead of a finding — is the failure mode they target.

# device_unregister() / put_device() of a caller-owned object whose pointer can
# be observed later (e.g. core->fw_dev, drvdata, a cached handle).
_DEVICE_UNREGISTER_RE = re.compile(
    r"device_unregister\s*\(|platform_device_unregister\s*\(|"
    r"\bput_device\s*\(|\b\w+_unregister\s*\([^)]*->",
    re.IGNORECASE,
)
# The object pointer is caller-owned / re-observable: stored on a struct field,
# drvdata, or a cached handle.  We require this so a bare local `put_device(dev)`
# in an error path (no escape) does not trip the check.
_DEVICE_UNREGISTER_OWNED_PTR_RE = re.compile(
    r"->\s*\w*(?:dev|device|cdev|csdev|child|node|handle|ctx)\b|"
    r"drvdata|platform_get_drvdata|dev_get_drvdata|"
    r"core->\w+|priv->\w+|->fw_dev\b",
    re.IGNORECASE,
)
# Discharge proof: the caller-owned pointer is reset to NULL (or an equivalent
# clear) after the unregister.
_DEVICE_UNREGISTER_NULL_PROOF_RE = re.compile(
    r"(?:->|\b)\w+\s*=\s*NULL|=\s*NULL\s*;|set\w*\s+to\s+NULL|"
    r"clear(?:s|ed|ing)?\s+the\s+(?:stale\s+)?pointer|"
    r"NULL(?:s|ed|ing)?\s+(?:the\s+)?(?:caller(?:-owned)?\s+)?pointer|"
    r"reset(?:s|ting)?\s+\w+\s+to\s+NULL",
    re.IGNORECASE,
)
# A [BUG]/[CONCERN] finding text that names the stale-pointer hazard counts as
# "not cleared" — the obligation is then discharged by the finding itself.  This
# must tie stale/NULL language to the unregister / device-field / reinit context:
# a generic "dangling pointer" elsewhere in the block (e.g. a separate stack
# `&local` escape finding) does NOT discharge the fw_dev-not-NULLed obligation,
# so the bare word "dangling" is intentionally excluded from the stale set here.
_DEVICE_UNREGISTER_STALE_RE = (
    r"(?:stale\s+pointer|not\s+(?:set|reset|cleared)\s+to\s+NULL|"
    r"left\s+(?:dangling|stale)|pointer\s+hygiene|"
    r"use-after-free|UAF)"
)
_DEVICE_UNREGISTER_FIELD_RE = (
    r"(?:device_unregister|put_device|->\s*fw_dev|->\s*\w*(?:cdev|csdev|child)\b|"
    r"reinit|re-?init|deinit|drvdata)"
)
_DEVICE_UNREGISTER_FINDING_RE = re.compile(
    _DEVICE_UNREGISTER_STALE_RE + r"[\s\S]{0,90}?" + _DEVICE_UNREGISTER_FIELD_RE
    + r"|" + _DEVICE_UNREGISTER_FIELD_RE + r"[\s\S]{0,90}?"
    + _DEVICE_UNREGISTER_STALE_RE,
    re.IGNORECASE,
)
# Explicit "no escape" discharge: review states the object is local / not stored.
_DEVICE_UNREGISTER_NO_ESCAPE_RE = re.compile(
    r"not stored|local (?:device|object|pointer) only|does not escape|"
    r"no caller-owned pointer|pointer is not (?:retained|kept|observable)|"
    r"freed in (?:the )?same (?:scope|frame)",
    re.IGNORECASE,
)

# A per-block / per-core power-off helper context.
_PER_BLOCK_HELPER_RE = re.compile(
    r"per-?block|per-?core|per-?codec|"
    r"\b\w*_power_off(?:_\w+)?\s*\(|\b\w*_power_down(?:_\w+)?\s*\(|"
    r"\b\w*disable_power_domain\w*\s*\(|"
    r"(?:vcodec|vpp|core)\[\s*\w+\s*\]|"
    r"for\s*\([^)]*(?:core_id|num_cores|block|i\s*<\s*\w*core)",
    re.IGNORECASE,
)
# A global OPP / performance / genpd / clock-rate vote DROP.
_GLOBAL_VOTE_DROP_RE = re.compile(
    r"dev_pm_opp_set_opp\s*\([^)]*(?:NULL|,\s*0\s*\))|"
    r"\w*opp_set_rate\s*\([^)]*,\s*0\s*\)|"
    r"\w*set_rate\s*\([^)]*,\s*0\s*\)|"
    r"iris_opp_set_rate\s*\([^)]*,\s*0\s*\)|"
    r"pm_runtime_put(?:_sync|_noidle|_autosuspend)?\s*\(|"
    r"(?:performance|perf)[- ]?(?:state|vote)[\s\S]{0,30}?(?:0|zero|drop)|"
    r"drop\w*[\s\S]{0,30}?(?:OPP|opp|performance|perf|vote)|"
    r"(?:OPP|opp)[\s\S]{0,30}?(?:to\s+)?(?:0|zero)",
    re.IGNORECASE,
)
# Discharge proof: the full multi-block sequence is traced, naming sibling
# blocks and proving none stays active when the vote drops.
_PER_BLOCK_VOTE_PROOF_RE = re.compile(
    r"(?:no sibling|all (?:sibling|other) blocks?|every (?:other )?(?:block|core))"
    r"[\s\S]{0,80}?(?:already )?(?:disabled|powered off|inactive|off|torn down)|"
    r"(?:last|only) (?:block|core)[\s\S]{0,60}?(?:vote|opp|drop)|"
    r"controller (?:vote|opp) (?:dropped|released) only (?:after|when)[\s\S]{0,80}?"
    r"(?:all|every|last)|"
    r"multi-?block (?:sequence|teardown)[\s\S]{0,120}?(?:sibling|each block|all blocks)|"
    r"refcount(?:ed)?[\s\S]{0,60}?(?:vote|opp|last put)",
    re.IGNORECASE,
)
# A [BUG]/[CONCERN] finding that names the per-block vote-scope hazard.  Must
# tie the vote drop to a still-active sibling / DVFS violation — merely
# describing "a per-block helper that drops the OPP vote" is NOT the hazard
# being raised, so that descriptive phrasing is excluded.
_PER_BLOCK_VOTE_FINDING_RE = re.compile(
    r"(?:global )?(?:vote|opp|rate)[\s\S]{0,80}?(?:while|when|but)[\s\S]{0,60}?"
    r"(?:sibling|other (?:block|core)|another (?:block|core))[\s\S]{0,40}?"
    r"(?:still )?(?:active|running|powered|on)|"
    r"(?:sibling|other (?:block|core))[\s\S]{0,60}?(?:still )?(?:active|running)"
    r"[\s\S]{0,80}?(?:vote|opp|rate)[\s\S]{0,40}?(?:drop|0|zero)|"
    r"DVFS[\s\S]{0,40}?(?:violation|constraint)|"
    r"drops? the (?:global )?(?:controller )?(?:OPP|vote)[\s\S]{0,60}?"
    r"(?:while|when)[\s\S]{0,60}?(?:running|active|other block)",
    re.IGNORECASE,
)
# Acknowledged "this block drops a global vote" context (so we only fire when
# the report itself raised the topic and then cleared it).
_GLOBAL_VOTE_CONTEXT_RE = re.compile(
    r"\b(?:OPP|opp|performance state|perf state|genpd|"
    r"power[- ]?domain (?:vote|performance)|global (?:vote|rate))\b",
    re.IGNORECASE,
)

# pm_runtime_get_sync() balancing: a failed get_sync has ALREADY incremented the
# usage count, so the error edge must call pm_runtime_put_noidle() (or migrate to
# pm_runtime_resume_and_get).  A review that clears the call as "correct" while
# the cited balancing call is pm_runtime_put_sync()/pm_runtime_put() on the error
# path is a false clearance.  Mirrors refs/hardware-eng.md `pm_runtime bracket`.
_PM_GET_SYNC_CLEARED_RE = re.compile(
    r"pm_runtime_get_sync[\s\S]{0,200}?"
    r"(?:correct(?:\s+usage)?|return is checked|checks? the return|"
    r"balanced|handled|safe|no (?:bug|issue|leak|imbalance))",
    re.IGNORECASE,
)
# A valid get_sync discharge: put_noidle on error, or migration to
# resume_and_get, or an explicit acknowledgement that the count is balanced via
# put_noidle.
_PM_GET_SYNC_NOIDLE_PROOF_RE = re.compile(
    r"put_noidle|pm_runtime_resume_and_get|resume_and_get",
    re.IGNORECASE,
)
# The wrong-discharge tell: the review cites put_sync / plain put as the error
# balance for a get_sync failure.
_PM_GET_SYNC_WRONG_BALANCE_RE = re.compile(
    r"(?:error|fail\w*|on error|<\s*0)[\s\S]{0,80}?"
    r"pm_runtime_put_sync\s*\(|"
    r"pm_runtime_put_sync\s*\([\s\S]{0,80}?(?:on|error|fail)|"
    r"(?:error|fail\w*)[\s\S]{0,60}?pm_runtime_put\s*\(",
    re.IGNORECASE,
)
# A [BUG]/[CONCERN] that names the get_sync imbalance discharges the obligation.
_PM_GET_SYNC_FINDING_RE = re.compile(
    r"put_noidle|usage[- ]?count[\s\S]{0,40}?(?:leak|imbalance|not balanced)|"
    r"get_sync[\s\S]{0,60}?(?:leak|imbalance|not balanced|unbalanced)|"
    r"forced[\s\S]{0,40}?(?:performance|highest)[\s\S]{0,40}?state",
    re.IGNORECASE,
)

# --- Phase 2 architecture / layering ---------------------------------------
# Source-aware backstop: a patch hunk that threads a vendor/driver-specific
# construct into a CORE subsystem (the IOMMU core, the driver core, of/, kernel/,
# mm/) is a layering objection — the most common upstream-rejection reason — and
# must not be silently cleared with a positive note.  Mirrors refs/code-logic.md
# (3c.6 Subsystem Layering / Placement).
#
# We detect, from the diff itself: a hunk whose target file is a core-subsystem
# path AND that adds (a `+` line) either a vendor-named bus/type into a table, a
# driver-private/vendor #include, or a CONFIG_<VENDOR> guard.
_CORE_SUBSYS_FILE_RE = re.compile(
    r"^\+\+\+\s+b/(?P<path>(?:drivers/iommu/|drivers/base/|drivers/of/|"
    r"kernel/|mm/|init/|drivers/pci/probe\.c|include/linux/iommu\.h)"
    r"[^\t\n]*\.(?:c|h))\b",
    re.MULTILINE,
)
# An added line that introduces a vendor/driver-specific construct.  "Vendor"
# here is any lowercase identifier that is not a well-known generic bus
# (platform/pci/amba/cdx/usb/spi/i2c/virtio/acpi).
_CORE_SUBSYS_VENDOR_ADD_RE = re.compile(
    r"^\+\s*&\s*(?P<sym>[a-z][a-z0-9_]*?)_bus_type\b|"
    r"^\+\s*#\s*include\s*<linux/(?P<hdr>[a-z][a-z0-9_]*)_(?:bus|vpu|gpu|dsp|"
    r"npu|venus|iris|adreno)[a-z0-9_]*\.h>|"
    r"^\+\s*#\s*include\s+\"[^\"]*drivers/[^\"]*\"|"
    r"^\+\s*#\s*ifdef\s+CONFIG_(?P<cfg>[A-Z][A-Z0-9_]*)",
    re.MULTILINE,
)
# Generic bus names that are legitimately part of the core tables — adding these
# is not a vendor layering violation.
_GENERIC_BUS_NAMES = frozenset({
    "platform", "pci", "amba", "cdx", "usb", "spi", "i2c", "virtio", "acpi",
    "host1x", "fsl_mc", "cdx", "mhi", "hv", "vmbus", "css", "ccw", "ap",
})
# Config tokens that are not vendor/driver specific (architecture/core options).
_GENERIC_CONFIG_TOKENS = frozenset({
    "PCI", "ACPI", "OF", "PM", "PM_SLEEP", "SMP", "MMU", "NUMA", "DEBUG_FS",
    "SUSPEND", "HOTPLUG_CPU", "COMPAT",
})
# The report acknowledges the layering question (finding or explicit discussion).
_LAYERING_FINDING_RE = re.compile(
    r"layering|abstraction layer|wrong (?:layer|subsystem|place)|"
    r"does not belong in (?:the )?(?:core|iommu|driver core)|"
    r"belongs? in (?:a )?(?:driver|vendor)|"
    r"core (?:framework|subsystem)[\s\S]{0,80}?(?:vendor|driver-specific|private)|"
    r"vendor[\s\S]{0,40}?(?:in|into)[\s\S]{0,40}?core (?:framework|subsystem|table)|"
    r"couples? (?:two )?subsystems|cross-subsystem coupling|"
    r"forces? .{0,40}into (?:the )?(?:core kernel|vmlinux)|"
    r"postcore_initcall[\s\S]{0,60}?(?:module|bloat|vmlinux)|"
    r"generic (?:solution|mechanism|alternative|bus)[\s\S]{0,60}?instead|"
    r"standard platform_device|standardized .{0,20}bus",
    re.IGNORECASE,
)
# An explicit clearance: the placement is generic or maintainer-acknowledged.
_LAYERING_CLEARED_RE = re.compile(
    r"(?:placement|approach) is generic|generic (?:and )?reusable|"
    r"reusable by other drivers|maintainer (?:acked|acknowledged|approved|"
    r"agreed)|acked[- ]by[\s\S]{0,40}?(?:approach|placement|bus)|"
    r"already (?:discussed|acknowledged) (?:in[- ]thread|on the list|upstream)|"
    r"not vendor-specific|behind a (?:non-vendor|generic) name",
    re.IGNORECASE,
)

# --- Phase 3 refactor audit + API-contract pairing -------------------------
# 3a — stack struct passed by pointer to a kernel API without zero-init.
# Detect (from the diff) a stack declaration of a known attach/config descriptor
# struct followed by field assignments but no `= {}`/memset, passed to a *_list/
# *_attach API.  Mirrors refs/code-logic.md (Kernel-API structs, not only
# on-wire).
_STACK_STRUCT_DECL_RE = re.compile(
    r"^\+\s*struct\s+(?P<ty>dev_pm_domain_attach_data|of_phandle_args)\s+"
    r"(?P<var>\w+)\s*;",
    re.MULTILINE,
)
_STACK_STRUCT_ZEROINIT_RE_TMPL = (
    r"struct\s+{ty}\s+{var}\s*=\s*\{{\s*0?\s*\}}|"
    r"memset\s*\(\s*&?\s*{var}\b"
)
_STACK_STRUCT_FIELD_ASSIGN_RE_TMPL = r"^\+\s*{var}\s*\.\s*\w+\s*="
_STACK_STRUCT_REVIEW_PROOF_RE = re.compile(
    r"zero-?init|memset|=\s*\{\s*\}|stack garbage|uninitialized (?:field|member|"
    r"struct)|pd_flags|link_flags|garbage[\s\S]{0,40}?(?:field|member)|"
    r"unset (?:field|member)",
    re.IGNORECASE,
)

# 3b — SCM PAS metadata-release pairing.  When the diff loads PAS firmware via
# qcom_mdt_pas_load()/qcom_scm_pas_init_image() but never calls
# qcom_scm_pas_metadata_release(), the review must flag the metadata leak.
# Mirrors refs/code-logic.md (API alloc/release-pairing contract checklist).
_PAS_LOAD_DIFF_RE = re.compile(
    r"^\+[^\n]*(?:qcom_mdt_pas_load|qcom_scm_pas_init_image)\s*\(",
    re.MULTILINE,
)
_PAS_METADATA_RELEASE_DIFF_RE = re.compile(
    r"qcom_scm_pas_metadata_release\s*\(",
)
_PAS_METADATA_REVIEW_PROOF_RE = re.compile(
    r"qcom_scm_pas_metadata_release|metadata (?:memory )?(?:leak|release|freed|"
    r"not (?:freed|released))|pas[\s\S]{0,30}?metadata[\s\S]{0,30}?"
    r"(?:leak|release|free)",
    re.IGNORECASE,
)

# --- 2026-06-08 Sashiko calibration gaps ----------------------------------
# Keep these source-aware backstops deliberately narrow.  They fire only on
# syntactic shapes that matched confirmed review misses, and any source-visible
# guard/normalization/metadata path suppresses the check to avoid turning
# maintainer-rejected or topology-dependent concerns into validator noise.
# The rule prose lives in the matching ref/*.md file and is intentionally
# generic; the regexes below are the concrete instances we currently know how
# to detect mechanically.
_OWNED_REF_GET_ADDED_RE = re.compile(
    r"^\+[^+].*\b(?:of_clk_get(?:_by_name)?|clk_get|of_reset_control_get(?:_exclusive|_shared|_optional)?|reset_control_get(?:_exclusive|_shared|_optional)?|regulator_get(?:_optional)?)\s*\(",
    re.MULTILINE,
)
_OWNED_REF_PUT_RE = re.compile(
    r"\b(?:clk_put|reset_control_put|regulator_put)\s*\(",
)
_OWNED_REF_REPORT_RE = re.compile(
    r"of_clk_get|clk_put|clock handle|clock ref(?:erence)?|owned (?:clk|reference|handle)|"
    r"devm_clk_get|leak(?:ed)? clock|unbalanced clock|"
    r"reset_control_put|regulator_put|owned ref|reference getter|non-devm",
    re.IGNORECASE,
)
_REPEATABLE_ENABLE_ADDED_RE = re.compile(
    r"^\+[^+].*\b(?:clk_prepare_enable|clk_enable|regulator_enable|reset_control_deassert)\s*\(",
    re.MULTILINE,
)
_REPEATABLE_CALLBACK_HINT_RE = re.compile(
    r"set_sysclk|hw_params|startup|shutdown|trigger|stream|"
    r"\.open\b|\.close\b|\.start\b|\.stop\b|"
    r"runtime_resume|runtime_suspend|"
    r"recover|reload|reconfigure|restart|switch_|set_rate|"
    r"power_on|power_off",
    re.IGNORECASE,
)
_ENABLE_IDEMPOTENCY_GUARD_RE = re.compile(
    r"\b(?:refcount|enable_count|prepare_count|users|usecount|use_count)\b|"
    r"\b(?:atomic_t|refcount_t|atomic_inc_return|atomic_dec_return)\b|"
    r"^\+[^+].*\bif\s*\([^\n]*(?:enabled|prepared|active|on\s*[)&|])|"
    r"\bWARN_ON\s*\([^)]*(?:enabled|count)",
    re.IGNORECASE | re.MULTILINE,
)
_ENABLE_IDEMPOTENCY_REPORT_RE = re.compile(
    r"idempot|enable count|prepare count|refcount|repeated (?:set_sysclk|call|enable)|"
    r"re-?enter|re-?entrant|"
    r"set_sysclk[\s\S]{0,120}?(?:repeat|shutdown|disable|stream|concurrent)|"
    r"clk_prepare_enable[\s\S]{0,120}?(?:already|guard|balanced|disable)|"
    r"enable[\s\S]{0,80}?(?:once|twice|multiple|guard|already)",
    re.IGNORECASE,
)
_ROLE_TYPED_HELPER_ADDED_RE = re.compile(
    r"^\+[^+].*\bsnd_soc_dai_set_(?:sysclk|fmt|tdm_slot|bclk_ratio|pll)\s*\([^\n]*\bcpu_dai\b",
    re.MULTILINE,
)
_ROLE_TYPED_HELPER_HINT_RE = re.compile(
    r"codec_sysclk|codec[_-]?dai|CODEC|codec",
    re.IGNORECASE,
)
_ROLE_TYPED_REPORT_RE = re.compile(
    r"codec DAI|CPU DAI|DAI target|DAI endpoint|clk_id|"
    r"codec_sysclk|cpu_dai|codec_dai|"
    r"role[\s\S]{0,40}?(?:argument|endpoint|target)|"
    r"endpoint[\s\S]{0,80}?(?:CPU|codec|sink|source|master|slave)",
    re.IGNORECASE,
)
_NON_ALLOC_ENOMEM_REPORT_RE = re.compile(
    r"match data[\s\S]{0,120}?(?:-ENOMEM|ENODEV|EINVAL|ENODATA|allocation)|"
    r"-ENOMEM[\s\S]{0,120}?(?:match data|not allocation|wrong errno|lookup|descriptor)|"
    r"(?:ENODEV|EINVAL|ENODATA|ENOENT)[\s\S]{0,120}?(?:match data|lookup|descriptor|missing)|"
    r"errno[\s\S]{0,80}?(?:mismatch|wrong|incorrect)",
    re.IGNORECASE,
)
_PM_POST_GET_RETURN_REPORT_RE = re.compile(
    r"post[- ]get|after (?:successful )?pm_runtime_get_sync|early return|"
    r"direct return|runtime PM cleanup|usage count leak|pm_runtime_put|"
    r"cleanup label|err_pm_runtime",
    re.IGNORECASE,
)
_FIRMWARE_METADATA_REPORT_RE = re.compile(
    r"MODULE_FIRMWARE|firmware metadata|firmware dir(?:ectory)?|fw dir|"
    r"inherited firmware|intentionally omitted|modalias|userspace firmware",
    re.IGNORECASE,
)
_BINDING_CONDITIONAL_COMPAT_REPORT_RE = re.compile(
    r"allOf|if/then|conditional|per-compatible|compatible[\s\S]{0,120}?"
    r"(?:clock|reset|power-domain|interrupt|supply|assigned-clocks|names)|"
    r"(?:clock|reset|power-domain|interrupt|supply|assigned-clocks|names)"
    r"[\s\S]{0,120}?compatible",
    re.IGNORECASE,
)
_POSITIVE_RETURN_NORMALIZED_RE = re.compile(
    r"(?:ret|rc|err)\s*>\s*0[\s\S]{0,80}?(?:=\s*0|return\s+0)|"
    r"max\s*\(\s*(?:ret|rc|err)\s*,\s*0\s*\)|"
    r"\?\s*0\s*:\s*(?:ret|rc|err)|"
    r"(?:ret|rc|err)\s*<\s*0\s*\?\s*(?:ret|rc|err)\s*:\s*0",
)
_POSITIVE_RETURN_FORWARD_RE = re.compile(
    r"^\+[^+].*return\s+pm_runtime_put_sync\s*\(|"
    r"pm_runtime_put_sync\s*\([^;]+;[\s\S]{0,160}?^\+[^+].*return\s+(?:ret|rc|err)\s*;",
    re.MULTILINE,
)
_POSITIVE_RETURN_REPORT_RE = re.compile(
    r"pm_runtime_put_sync|positive (?:success|return)|return 1|normalize[sd]? to 0|"
    r"0/negative|negative errno|ret\s*>\s*0|"
    r"clamp[\s\S]{0,40}?(?:positive|0)|max\s*\(\s*ret\s*,\s*0",
    re.IGNORECASE,
)
_PRINTF_FORMAT_REPORT_RE = re.compile(
    r"format specifier|printf|dev_set_name|snprintf|printk|trace|%u|%d|"
    r"unsigned|signedness|devid|type mismatch",
    re.IGNORECASE,
)

# --- 2026-06-09 fastrpc v8 calibration: relocated teardown step ------------
# A refactor removes a teardown/bookkeeping statement from inside a helper and
# relocates it into some callers; another caller that still reaches the helper
# now skips the step (leak / double-free / stale-pointer / UAF).  Gate-1: a
# removed (`-`) line inside a function body matches a teardown shape AND the
# enclosing helper (from the @@ hunk header) has >=2 call sites in the corpus.
_TEARDOWN_REMOVED_RE = re.compile(
    r"^-\s*(?:"
    r"list_del(?:_init|_rcu)?\s*\(|"
    r"list_move(?:_tail)?\s*\(|"
    r"hlist_del(?:_init|_rcu)?\s*\(|"
    r"(?:kfree|kvfree|kfree_rcu|vfree)\s*\(|"
    r"[A-Za-z_][A-Za-z0-9_]*_free\s*\(|"
    r"dma_free_(?:coherent|noncoherent|attrs)\s*\(|"
    r"(?:kref_put|put_device|of_node_put|fwnode_handle_put|module_put|"
    r"[A-Za-z_][A-Za-z0-9_]*_put)\s*\(|"
    r"[A-Za-z_][A-Za-z0-9_]*_(?:release|destroy|unregister|del|remove|deinit)\s*\(|"
    r"[A-Za-z_][A-Za-z0-9_]*(?:->|\.)[A-Za-z_][A-Za-z0-9_]*\s*=\s*NULL\s*;|"
    r"(?:refcount_dec|atomic_dec|kref_get|refcount_inc|atomic_inc)\s*\("
    r")",
    re.MULTILINE,
)
# Hunk header carrying the enclosing C function name:
#   @@ -a,b +c,d @@ static int helper_name(args...
_HUNK_FUNC_RE = re.compile(
    r"^@@[^@]*@@\s*(?:[A-Za-z_][\w \t\*]*?\b)?"
    r"(?P<func>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
)
_RELOCATED_TEARDOWN_REPORT_RE = re.compile(
    r"every caller|each caller|all callers|caller coverage|"
    r"other call(?:er|-site|\s+site)s?|second caller|alternate caller|"
    r"relocat|moved (?:the )?(?:list_del|free|put|teardown|unlink|cleanup|step)|"
    r"err_assign|still (?:on|in) the (?:list|mmaps)|left (?:on|in) the list|"
    r"freed (?:but|while) (?:still )?(?:linked|on the list)|"
    r"removed (?:from|the) (?:list_del|teardown|step)|"
    r"helper (?:no longer|stopped|does not|doesn't) (?:unlink|free|remove|"
    r"delete|del)",
    re.IGNORECASE,
)
# Context anchor for co-location: the proof must sit next to a mention of the
# specific helper that lost the step (its name) OR an explicit error/unwind
# path that reaches it.  This keeps a generic "use-after-free" or "no other
# callers used a guard" sentence elsewhere in the report from falsely clearing.
_RELOCATED_TEARDOWN_PATH_RE = re.compile(
    r"error path|err(?:_\w+)?:|unwind|cleanup path|goto\s+\w+|"
    r"direct(?:ly)? call|calls? (?:the )?helper|reaches? (?:the )?helper",
    re.IGNORECASE,
)

# --- 2026-06-09 fastrpc v8 calibration: lock-coverage symmetry -------------
# A field is mutated under a lock on one path but set/reset/cleared on another
# path without that lock (set-under-lock / reset-without-lock asymmetry).
# Gate-1 works on the added (`+`) lines of each source diff body: find a field
# lvalue assigned while a lock is held (a lock acquire appears in the added
# lines before the assignment and an unlock has not yet appeared), then find
# the SAME field assigned on another added line with no lock acquire bracketing
# it.  Deliberately added-line only and lvalue-scoped to stay quiet.
_LOCK_ACQUIRE_RE = re.compile(
    r"\b(?:spin_lock(?:_irqsave|_irq|_bh|_nested)?|raw_spin_lock(?:_irqsave|_irq|_bh)?|"
    r"mutex_lock(?:_nested|_interruptible)?|read_lock|write_lock|"
    r"down_read|down_write|down|guard\s*\(\s*(?:mutex|spinlock)|"
    r"scoped_guard\s*\(\s*(?:mutex|spinlock))\b",
)
_LOCK_RELEASE_RE = re.compile(
    r"\b(?:spin_unlock(?:_irqrestore|_irq|_bh)?|raw_spin_unlock(?:_irqrestore|_irq|_bh)?|"
    r"mutex_unlock|read_unlock|write_unlock|up_read|up_write|up)\b",
)
# A simple `obj->field = value;` / `obj.field = value;` assignment on an added
# line.  Captures the lvalue (obj->field tail) so the two paths can be matched.
_FIELD_ASSIGN_RE = re.compile(
    r"^\+\s*(?P<lvalue>[A-Za-z_][A-Za-z0-9_]*(?:(?:->|\.)[A-Za-z_][A-Za-z0-9_]*)+)"
    r"\s*(?:=|\+=|-=|\|=|&=)\s*[^=]",
)
_LOCK_SYMMETRY_REPORT_RE = re.compile(
    r"without (?:holding|taking|the )?(?:the )?(?:lock|spinlock|mutex)|"
    r"outside (?:the )?(?:lock|spinlock|mutex|critical section)|"
    r"not (?:under|holding|protected by) (?:the )?(?:lock|spinlock|mutex)|"
    r"lock(?:ing)? asymmetr|unlocked (?:reset|write|access|store)|"
    r"reset(?:s)? (?:the )?(?:flag|field|state)[^.]{0,60}?(?:without|outside|no) lock|"
    r"data race|torn (?:flag|field|write|read)|set under (?:the )?lock|"
    r"missing (?:the )?(?:lock|spinlock|spin_lock|mutex) (?:on|in|protection)",
    re.IGNORECASE,
)





# here.  Each entry routes a failed check to (a) a one-line "fix" describing the
# concrete repair action and (b) the single ref + anchor to consult.  The
# daemon repair pass (server/patch_review/review_runner.py) reads these entries
# to build a scoped repair prompt that names only the refs the failed checks
# need, instead of pointing the repair agent at every ref.
#
# Ref naming convention: "<ref-file>#<section header text>" so the repair agent
# can jump straight to the governing section.  Keep refs minimal — one per
# entry where possible.  The completeness of this table is enforced by
# test_review_runner.py (a new check added without a remediation entry fails).
REMEDIATION: dict[str, dict[str, str]] = {
    # --- Structural / HTML contract (orchestrator + template owned) ---
    "gate_trace": {
        "fix": "Add the Gate 1/Gate 2/Gate 3 trace (or 'Always-BUG exception:') "
               "inside each non-NIT finding-card .body; NIT cards need a "
               "'Style track:' line. Re-check reachability/harm/severity before "
               "writing the trace — do not fabricate it.",
        "ref": "gate-rules.md#THREE-GATE RULE — FINDING VALIDATION, MANDATORY, SEQUENTIAL, NON-BYPASSABLE",
    },
    "step_record": {
        "fix": "Restore the per-block <!-- STEP_COMPLETION_RECORD --> with all "
               "mandatory step_* fields marked DONE; only mark a step DONE when "
               "the underlying work was actually performed.",
        "ref": "core.md#Your procedure — 7 mandatory steps",
    },
    "conditional_sections": {
        "fix": "Add the missing conditional section header (DT / DT-driver / "
               "Hardware Engineering) the patch triggers; the review packet lists "
               "which are required for this patch.",
        "ref": "core.md#Your procedure — 7 mandatory steps",
    },
    "anchor_id": {
        "fix": "Give every per-commit finding-card id=\"patch-<N>-finding-<K>\" "
               "with 1-based N and K.",
        "ref": "orchestrator-workflow.md#Step 6",
    },
    "banner_dedup": {
        "fix": "Each canonical per-commit finding must appear once in the banner; "
               "remove duplicate banner cards and keep a single anchor link per "
               "finding.",
        "ref": "orchestrator-workflow.md#Step 6",
    },
    "banner_consistency": {
        "fix": "Reconcile banner [BUG]/[CONCERN]/[MINOR] cards and stat-chip "
               "counts to exactly match the per-commit blocks (Step 6.6).",
        "ref": "orchestrator-workflow.md#Step 6",
    },
    "verdict_counts_consistency": {
        "fix": "Make the verdict pill match the bug/concern stat-chip counts: "
               "READY TO APPLY requires 0 bugs AND 0 concerns; NEEDS "
               "DISCUSSION requires 0 bugs AND >=1 concerns; NEEDS FIXES "
               "requires >=1 bugs. Either escalate/downgrade the pill or "
               "add/remove the missing finding-card (Step 6.6).",
        "ref": "orchestrator-workflow.md#Step 6",
    },
    "render_format": {
        "fix": "Keep .body, .file-ref, and .suggestion as prose/inline HTML only. "
               "Move <pre>, lists, tables, headings, and nested <div> blocks to "
               "sibling elements; keep Gate traces in .body.",
        "ref": "html-template.md#Finding-card render-safe pattern",
    },
    "pre_existing_scope": {
        "fix": "Move pre-existing-only issues out of .finding-card and "
               "verdict-banner summaries; keep them as patch-local pre-existing "
               "notes so they do not affect verdict/banner/stats. Add "
               "data-attribution=\"introduced\" or \"newly_exposed\" to real "
               "finding cards; if the patch makes a pre-existing path newly "
               "reachable or worse, state the before-vs-after reachability "
               "delta in the card instead.",
        "ref": "core.md#Your procedure — 7 mandatory steps",
    },
    "block_fragment": {
        "fix": "A block fragment must contain exactly one .commit-block ending "
               "with </div><!-- /commit-block -->.",
        "ref": "core.md#Your procedure — 7 mandatory steps",
    },
    # --- Build / test evidence ---
    "build_break_order": {
        "fix": "When the W=1 build failed because of the patch, the build-break "
               "finding must be the FIRST finding-card in that block (and its "
               "banner card first). If the failure is proven pre-existing, keep "
               "that proof as a non-finding build/test note instead.",
        "ref": "gate-rules.md#Step 4 — Review Each Commit",
    },
    "build_artifact_validity": {
        "fix": "Replace any interactive-Kconfig prompt log with a real "
               "non-interactive W=1 build artifact; rerun run_w1_build.py.",
        "ref": "startup-workflow.md#Step 2",
    },
    # --- Hardware / refactor / risk gates ---
    "hardware_trigger_consistency": {
        "fix": "A patch that touches registers/probe/remove/PM/IRQ/DMA cannot "
               "mark the Hardware Engineering section N/A — add the real HW "
               "analysis.",
        "ref": "hardware-eng.md#Step 3f — Hardware Engineering Perspective",
    },
    "test_results_build_notes_consistency": {
        "fix": "The Test Results card and per-commit Build/Test Notes "
               "disagree about whether Build (W=1) passed. Decide one way: "
               "if the compile actually succeeded and the FAIL row was "
               "triggered by a benign Kconfig syncconfig restart, change the "
               "row to PASS and put the syncconfig explanation in the Notes "
               "cell; if it really failed, quote the compiler error in the "
               "Notes cell so the FAIL is self-evident.",
        "ref": "output-format-mini.md#HTML Block Contract",
    },
    "test_results_fail_evidence": {
        "fix": "When a Test Results row is FAIL, the Notes cell MUST carry "
               "concrete evidence: either quote a compiler/checker diagnostic "
               "(e.g. `error: implicit declaration of function ...`, "
               "`WARNING: line over 100 characters`) directly in the cell, OR "
               "include an explicit pointer like `see Patch N — Build / Test "
               "Notes` (or an anchor link `<a href=\"#patch-N-...\">`). A bare "
               "count like 'failure(s): patch 1' is not actionable.",
        "ref": "html-template.md#HTML skeleton",
    },
    "refactor_coverage": {
        "fix": "A rate/performance abstraction refactor must cover every "
               "alternate path (DMA/GPI). Add the missing path to the coverage "
               "analysis or raise a finding.",
        "ref": "code-logic-interaction.md#3c.4 Interaction Picture",
    },
    "future_risk_gate": {
        "fix": "A row in the current-safe/future-risk table must not be emitted "
               "as a [CONCERN]; downgrade to a note or prove a present-tree harm.",
        "ref": "gate-rules.md#THREE-GATE RULE — FINDING VALIDATION, MANDATORY, SEQUENTIAL, NON-BYPASSABLE",
    },
    "safe_clearance_gate": {
        "fix": "Remove safe/no-action, self-negating, or process-only notes "
               "that were emitted as findings; a cleared or informational item "
               "is not a finding-card.",
        "ref": "gate-rules.md#THREE-GATE RULE — FINDING VALIDATION, MANDATORY, SEQUENTIAL, NON-BYPASSABLE",
    },
    "platform_enablement_ready_to_apply": {
        "fix": "Do not leave a platform-enablement / add-support series at "
               "READY TO APPLY without explicit lifecycle cleanup, compatibility "
               "fallback, and selector/cardinality audit proof in the report.",
        "ref": "gate-rules.md#Step 4 — Review Each Commit",
    },
    "severity_crash_floor": {
        "fix": "A finding describing a crash/NULL-deref/UAF must be at least "
               "[CONCERN]; raise the severity or correct the description.",
        "ref": "gate-rules.md#THREE-GATE RULE — FINDING VALIDATION, MANDATORY, SEQUENTIAL, NON-BYPASSABLE",
    },
    "severity_restore_floor": {
        "fix": "A finding describing a dropped suspend/resume restore must be at "
               "least [CONCERN]; raise the severity or prove the restore happens.",
        "ref": "hardware-eng-pm-register-access.md#3f.1 Device Power State Before Register Access",
    },
    # --- Codebase-audit / evidence proof ---
    "codebase_audit_record": {
        "fix": "Add the codebase_audit: line to the STEP_COMPLETION_RECORD with "
               "entrypoints=/callees=/siblings=/files=[...] for code patches.",
        "ref": "startup-workflow.md#Step 2",
    },
    "codebase_audit_required": {
        "fix": "Add the three 'codebase audit: entrypoints/callees/siblings' "
               "lines, the state/lifecycle workflow line, and the "
               "control-flow/data-flow/before-vs-after delta lines to the "
               "Code Logic Maps for every packet-mode block. "
               "For DTS/YAML-only patches, map entrypoints/callees/siblings "
               "to binding consumers, parent/sibling DTSI/DTS files, schema "
               "refs, or subsystem readers instead of writing N/A.",
        "ref": "startup-workflow.md#Step 2",
    },
    "on_demand_reads_record": {
        "fix": "Record each targeted source read as "
               "'on-demand read: <path> — <reason>' in the Code Logic Maps.",
        "ref": "startup-workflow.md#Step 2",
    },
    "inconclusive_requires_read_attempt": {
        "fix": "Before downgrading a finding to inconclusive or claiming "
               "equivalence/safety, record one targeted on-demand read of the "
               "file that holds the needed fact.",
        "ref": "startup-workflow.md#Step 2",
    },
    "evidence_manifest_record": {
        "fix": "Add 'evidence_manifest: DONE path=<tmp/evidence/patch_N_evidence.json>' "
               "to the STEP_COMPLETION_RECORD.",
        "ref": "startup-workflow.md#Step 2",
    },
    "evidence_required_reads": {
        "fix": "The evidence manifest marks required reads (helper bodies, sibling "
               "paths, parent schemas) that the block must show were read; read "
               "them or raise a finding instead of clearing.",
        "ref": "startup-workflow.md#Step 2",
    },
    # --- Prompt / packet / corpus artifacts (orchestrator setup) ---
    "prompt_artifact": {
        "fix": "Ensure the saved per-patch prompt (tmp/patch_N_prompt.md) exists "
               "and lists every required input file. Re-write it before re-spawn.",
        "ref": "orchestrator-workflow.md#Per-Patch Reviewer Subagent",
    },
    "packet_artifact": {
        "fix": "Ensure the compact reviewer packet (tmp/patch_N_review_packet.md) "
               "exists and passes scripts/validate_review_packet.py for this patch.",
        "ref": "startup-workflow.md#Step 2",
    },
    "rule_card_attestation": {
        "fix": "When a rule card with a mandatory attestation record fires, the "
               "subagent must produce the corresponding attestation record in its "
               "Code Logic Maps or DT/DT-Binding Notes. Re-spawn the subagent "
               "with a note requiring the specific attestation record format.",
        "ref": "rule-cards/runtime-pm-bracket-safety.md#Mandatory Attestation Record",
    },
    "rule_card_coverage": {
        "fix": "Add a Rule Card Coverage section and a rule_card_coverage: "
               "STEP_COMPLETION_RECORD line that name every selected card from "
               "the packet JSON as checked, finding, or inconclusive. If the "
               "packet has focused_review_obligations, visibly disposition every "
               "obligation ID as FINDING, SAFE, or INCONCLUSIVE before claiming "
               "No issues found.",
        "ref": "output-format-mini.md#HTML Block Contract",
    },
    "hardware_notes_specificity": {
        "fix": "When step_3f_hardware_eng is DONE, replace generic hardware "
               "notes with concrete evidence from the patch/context: thermal "
               "trip values, hysteresis, #cooling-cells, tmd-names, provider/"
               "consumer IDs, QMI instance IDs, PM/IRQ/DMA/clock/regulator "
               "facts, or an explicit non-applicability rationale.",
        "ref": "output-format-mini.md#HTML Block Contract",
    },
    "runtime_override_artifact": {
        "fix": "Honor the daemon/runtime override artifact exactly: if sparse is "
               "disabled, keep the sparse artifact as `(sparse disabled by config)` "
               "and report sparse as SKIP/disabled-by-config instead of running it.",
        "ref": "startup-workflow.md#Step 3",
    },
    "source_corpus_required": {
        "fix": "Provide the patch diff/corpus (tmp/review_patches or the patch "
               "diff) so source-aware checks can run; do not downgrade to "
               "HTML-only validation.",
        "ref": "orchestrator-workflow.md#Step 6",
    },
    # --- DT / binding source-aware checks ---
    "binding_parent_compatible_consistency_source_aware": {
        "fix": "Ensure the child binding's compatible is consistent with the "
               "parent wrapper schema's allowed values in the source tree.",
        "ref": "dt-binding-yaml.md#3d.1 DT-Binding Schema (`.yaml`) Rules",
    },
    "old_dtb_compatibility_source_aware": {
        "fix": "When a binding makes resources newly required, state whether an "
               "old DTB still probes with the new kernel and why; otherwise "
               "raise a compatibility finding.",
        "ref": "dt-binding-yaml.md#3d.1 DT-Binding Schema (`.yaml`) Rules",
    },
    "dt_fallback_old_kernel_new_dtb_source_aware": {
        "fix": "For a new compatible added with an existing fallback, prove "
               "the old-kernel/new-DTB fallback descriptor is safe for any "
               "new resources, clocks, register offsets, and sequencing, or "
               "file the unsafe fallback finding.",
        "ref": "rule-cards/dt-compatible-fallback-contract.md",
    },
    "provider_cells_const_source_aware": {
        "fix": "When adding provider #*-cells properties, define the fixed "
               "cell count with const: for the compatible or explicitly prove "
               "variable cell counts are valid.",
        "ref": "dt-binding-yaml.md#3d.1 DT-Binding Schema (`.yaml`) Rules",
    },
    "optional_clk_dead_enoent_fallback": {
        "fix": "Do not keep -ENOENT fallback logic after switching to "
               "devm_clk_bulk_get_optional(); optional getters succeed when "
               "the optional clock is absent, so flag the dead branch or use "
               "a required getter.",
        "ref": "dt-driver.md#Step 3d.3 — Driver `of_match` & `of_*` API Consistency",
    },
    "required_clk_bulk_zero_count_source_aware": {
        "fix": "For compatible-required clocks acquired with "
               "devm_clk_bulk_get_all(), handle both negative errors and a "
               "zero returned clock count before hardware access.",
        "ref": "dt-driver.md#Step 3d.3 — Driver `of_match` & `of_*` API Consistency",
    },
    "framework_status_callback_power_state_source_aware": {
        "fix": "When a regulator/framework status callback reads MMIO in a "
               "clock-gated resource path, prove that the status register is "
               "accessible before enable or file the unpowered-read finding.",
        "ref": "rule-cards/framework-status-callback-power-state.md",
    },
    "framework_status_bootloader_refcount_source_aware": {
        "fix": "When a framework status callback can report hardware already "
               "enabled, prove Linux-side clock/PM counts are synchronized "
               "before any later disable/unprepare path, or file the "
               "underflow/unbalanced-disable finding.",
        "ref": "rule-cards/framework-status-callback-power-state.md",
    },
    "managed_device_link_manual_remove_source_aware": {
        "fix": "Do not pair DL_FLAG_AUTOREMOVE_* device links with manual "
               "device_link_remove()/device_link_del() cleanup unless the "
               "driver-core contract explicitly allows that exact state.",
        "ref": "code-logic-alloc-release.md#API alloc/release-pairing contract checklist",
    },
    "retained_dynamic_object_cleanup_source_aware": {
        "fix": "When a static/global descriptor retains a dynamically "
               "allocated framework object, every cleanup/error path that "
               "frees it must clear the retained pointer or prove retry/rebind "
               "cannot reuse freed state.",
        "ref": "code-logic.md#3c.2 Data-Flow Picture",
    },
    "level_irq_reenable_without_clear_source_aware": {
        "fix": "When an IRQ path exits early on runtime-PM/device-state checks, "
               "clear the asserted source or leave it masked before enable_irq(); "
               "otherwise flag the level-triggered interrupt-storm risk.",
        "ref": "hardware-eng-irq-dma-context.md#3f.5 Interrupt and DMA Context Constraints",
    },
    "alternate_path_state_reset_source_aware": {
        "fix": "For mode/type/selector/config fields set on one path, prove each "
               "alternate path (TPG, loopback, internal source) resets or guards "
               "the field, or file the stale-state finding.",
        "ref": "code-logic-state-machine.md#3c.3 State-Machine / Lifecycle Picture",
    },
    "unvalidated_arithmetic_input_source_aware": {
        "fix": "For GENMASK(count - 1), division, shift, or arithmetic fed by a "
               "zero-capable DT/variant value, prove bounds validation rejects "
               "zero or file the degenerate-input finding.",
        "ref": "code-logic.md#3c.2 Data-Flow Picture",
    },
    "branch_precedence_regression_source_aware": {
        "fix": "Trace the widened/reordered if/else chain: name which input now "
               "lands in the earlier arm and prove the bypassed side effect "
               "still runs, or file the branch-diversion finding.",
        "ref": "code-logic.md#3c.1 Control-Flow Picture",
    },
    "branch_diversion_producer_coupling_source_aware": {
        "fix": "When the producer source shows connect-status and event/IRQ flags "
               "are independent, do not clear diversion by mutual-exclusion prose; "
               "file the finding or cite a producer line that truly couples them.",
        "ref": "code-logic.md#3c.1 Control-Flow Picture",
    },
    "readpath_widening_writer_locked_source_aware": {
        "fix": "Name the writer free site and lock for the widened read window, or "
               "quote a real lifetime guarantee (shared lock, refcount, RCU, "
               "suppress_bind_attrs); otherwise file the UAF/race finding.",
        "ref": "hardware-eng-resource-lifecycle.md#3f.2 Hardware Resource Lifecycle Symmetry",
    },
    "binding_companion_dependency_source_aware": {
        "fix": "A property that requires a companion property (e.g. dmas needs "
               "dma-names) must include it; fix the binding/example or raise a "
               "finding.",
        "ref": "dt-binding-yaml.md#3d.1 DT-Binding Schema (`.yaml`) Rules",
    },
    "dma_names_example": {
        "fix": "A binding example using 'dmas' must also list 'dma-names'; add it "
               "to the example.",
        "ref": "dt-binding-yaml.md#3d.1 DT-Binding Schema (`.yaml`) Rules",
    },
    "dma_names_source_aware": {
        "fix": "Verify dmas/dma-names pairing against the DTS/driver in the "
               "source tree; fix the mismatch or raise a finding.",
        "ref": "dt-binding-yaml.md#3d.1 DT-Binding Schema (`.yaml`) Rules",
    },
    "match_data_guard": {
        "fix": "Guard the device_get_match_data()/of_device_get_match_data() "
               "result against NULL before dereferencing, or raise a finding.",
        "ref": "dt-driver.md#Step 3d.3 — Driver `of_match` & `of_*` API Consistency",
    },
    "match_data_source_aware": {
        "fix": "Confirm in the source tree that the match-data result is "
               "NULL-checked on the touched path; fix or raise a finding.",
        "ref": "dt-driver.md#Step 3d.3 — Driver `of_match` & `of_*` API Consistency",
    },
    "selector_cardinality_source_aware": {
        "fix": "For add-support / new-descriptor work, explicitly compare every "
               "selector/cardinality surface (IDs, counts, names, routes, "
               "provider arrays) or raise a mismatch finding.",
        "ref": "code-logic.md#3c.2 Data-Flow Picture",
    },
    "aggregate_per_element_scale_source_aware": {
        "fix": "When a per-element bandwidth/rate is divided by a width/size "
               "from the container (`desc->`/`provider->`/`qp->desc->`) and the "
               "element exposes its own same-dimension field, compute from the "
               "per-element field (then aggregate) or prove the set is "
               "homogeneous; otherwise raise the mis-scale finding.",
        "ref": "code-logic.md#3c.2 Data-Flow Picture",
    },
    "cross_instance_pointer_unbind_source_aware": {
        "fix": "When a provider stores a cross-provider/peer raw node pointer, "
               "prove a lifetime guarantee against independent sysfs unbind "
               "(`.suppress_bind_attrs = true`, get_device/refcount, managed "
               "device_link, or coordinated teardown) or file the UAF finding.",
        "ref": "hardware-eng-resource-lifecycle.md#3f.2 Hardware Resource Lifecycle Symmetry",
    },
    "peer_dimension_admission_source_aware": {
        "fix": "When an admission or capacity guard validates one dimension, "
               "check each peer dimension that shares the same contract or raise "
               "a finding for the missing peer-dimension guard.",
        "ref": "code-logic.md#3c.2 Data-Flow Picture",
    },
    "duplicate_cleanup_fallthrough_source_aware": {
        "fix": "When an unwind path duplicates teardown/release work through "
               "fallthrough or shared labels, file the double-cleanup risk as "
               "a finding or prove the duplicate call sites are not both "
               "reachable.",
        "ref": "code-logic.md#3c.1 Control-Flow Picture",
    },
    "failed_start_stale_state_source_aware": {
        "fix": "When a start/resume/enable/load path publishes success state "
               "before the operation can fail, clear that state on the failure "
               "edge or file the stale-state contamination as a finding.",
        "ref": "code-logic-state-machine.md#3c.3 State-Machine / Lifecycle Picture",
    },
    "paired_callback_backend_symmetry_source_aware": {
        "fix": "Build a lifecycle workflow matrix for every prepare/open/start "
               "outcome and prove the paired unprepare/release/stop path uses "
               "the same session/resource owner. If an optional backend can "
               "fall back to the normal backend, the optional cleanup must "
               "reject sessions it did not prepare; otherwise file the stale "
               "cleanup/state bug.",
        "ref": "code-logic-state-machine.md#3c.3 State-Machine / Lifecycle Picture",
    },
    # --- Runtime-PM / resource source-aware checks ---
    "pm_runtime_get_sync_check": {
        "fix": "A bare pm_runtime_get_sync() must check its return and "
               "pm_runtime_put on error; fix the bracket or raise a finding.",
        "ref": "hardware-eng-pm-register-access.md#3f.1 Device Power State Before Register Access",
    },
    "device_unregister_pointer_hygiene": {
        "fix": "When a block unregisters/put_device()s a caller-owned object "
               "(->fw_dev, drvdata, cached handle) and clears it as safe, quote "
               "the `<ptr> = NULL` reset line that runs after the unregister, an "
               "explicit no-escape statement, or file a stale-pointer "
               "[BUG]/[CONCERN]. A positive note is not a discharge.",
        "ref": "hardware-eng-resource-lifecycle.md#3f.2 Hardware Resource Lifecycle Symmetry",
    },
    "per_block_vote_scope": {
        "fix": "When a per-block/per-core helper drops a global OPP/perf/genpd/"
               "clock-rate vote and the review clears it as safe, trace the full "
               "multi-block sequence (name each sibling block and prove none "
               "stays active when the vote drops) or file a [BUG]/[CONCERN].",
        "ref": "hardware-eng-pm-register-access.md#3f.1 Device Power State Before Register Access",
    },
    "pm_get_sync_balance": {
        "fix": "A failed pm_runtime_get_sync() leaves the usage count "
               "incremented; the error edge must call pm_runtime_put_noidle() "
               "(or migrate to pm_runtime_resume_and_get). Do not clear a "
               "get_sync as correct while citing put_sync()/put() on the error "
               "path — quote the put_noidle line or file a [BUG]/[CONCERN].",
        "ref": "hardware-eng-pm-register-access.md#3f.1 Device Power State Before Register Access",
    },
    "pm_runtime_get_sync_source_aware": {
        "fix": "Inspect the touched source path: an unchecked "
               "pm_runtime_get_sync() requires review proof or a finding.",
        "ref": "hardware-eng-pm-register-access.md#3f.1 Device Power State Before Register Access",
    },
    "clk_handle_ownership_source_aware": {
        "fix": "A handle returned by a non-devm reference getter (e.g. "
               "of_clk_get()/of_clk_get_by_name()/clk_get(), regulator_get(), "
               "of_reset_control_get()) is an owned reference; require the "
               "matching *_put() on every error/unbind path, convert to the "
               "devm_* variant, or prove ownership is transferred.",
        "ref": "hardware-eng-resource-lifecycle.md#3f.2 Hardware Resource Lifecycle Symmetry",
    },
    "clk_enable_idempotency_source_aware": {
        "fix": "For *_prepare_enable() / *_enable() in re-enterable callbacks "
               "(open/close, hw_params, set-rate, runtime-PM, recovery, stream "
               "restart), prove repeated calls cannot over-increment enable "
               "counts or file the missing idempotency/refcount finding.",
        "ref": "hardware-eng-resource-lifecycle.md#3f.2 Hardware Resource Lifecycle Symmetry",
    },
    "asoc_dai_target_source_aware": {
        "fix": "For role-typed endpoint helpers (currently detected: ASoC "
               "snd_soc_dai_set_*() picking cpu_dai vs codec_dai), validate "
               "the role the surrounding intent actually selects, including "
               "secondary arguments (clk_id/direction/index) and return "
               "handling; file a finding when the chosen role contradicts "
               "nearby flags, names, or commit text.",
        "ref": "code-logic.md#3c.2 Data-Flow Picture",
    },
    "non_alloc_enomem_source_aware": {
        "fix": "Match the errno to the failing operation: reserve -ENOMEM "
               "for genuine allocation failures and prefer -ENODEV/-EINVAL/"
               "-ENODATA/-ENOENT (or preserve the helper's own return) for "
               "absent match data, descriptors, or lookup results.",
        "ref": "coding-style.md#Error Paths & Resource Management",
    },
    "pm_runtime_post_get_return_source_aware": {
        "fix": "After a successful pm_runtime_get_sync(), every newly added "
               "early return must route through pm_runtime_put*()/cleanup or "
               "prove it exits before the get succeeds.",
        "ref": "hardware-eng-pm-register-access.md#3f.1 Device Power State Before Register Access",
    },
    "firmware_metadata_source_aware": {
        "fix": "When a driver adds a new firmware path or hardware firmware "
               "directory, add matching MODULE_FIRMWARE() metadata or document "
               "why the path is inherited/unused.",
        "ref": "hardware-eng-resource-lifecycle.md#3f.2 Hardware Resource Lifecycle Symmetry",
    },
    "binding_compatible_conditional_source_aware": {
        "fix": "For each added binding compatible, reconcile existing allOf/"
               "if/then resource conditionals; add the compatible to the right "
               "conditional or prove generic constraints are sufficient.",
        "ref": "dt-binding-yaml.md#Completeness checks",
    },
    "pm_runtime_positive_return_source_aware": {
        "fix": "Errno-style wrappers must not forward a >=0-success helper "
               "return (currently detected: pm_runtime_put_sync()) without "
               "normalizing positive values to 0; clamp with `ret < 0 ? ret "
               ": 0` / `max(ret, 0)` unless every caller documents and "
               "handles positive returns.",
        "ref": "hardware-eng-pm-register-access.md#3f.1 Device Power State Before Register Access",
    },
    "printf_format_type_source_aware": {
        "fix": "Compare each new printf-like format specifier with the "
               "argument type/signedness; use %u or an intentional cast for "
               "unsigned values instead of %d.",
        "ref": "coding-style.md#Data Structures & Types",
    },
    "relocated_teardown_step_source_aware": {
        "fix": "The patch removed a teardown/bookkeeping step (list_del, free, "
               "put, NULL, decrement) from a helper that has multiple callers. "
               "Audit every caller: prove each re-performs the step or never "
               "needed it, or file the leak/double-free/UAF for the caller "
               "that now skips it.",
        "ref": "code-logic.md#3c.5 Before-vs-After Delta",
    },
    "lock_coverage_symmetry_source_aware": {
        "fix": "A field is mutated under a lock on one path but set/reset/"
               "cleared without that lock on another. Audit every access to "
               "the field, take the same lock on the unlocked path, or prove "
               "the unlocked access is single-threaded/owner-private; otherwise "
               "file the data-race [CONCERN]/[BUG].",
        "ref": "code-logic-interaction.md#3c.4 Interaction Picture",
    },
    "touched_unsafe_pm_source_aware": {
        "fix": "A touched source file with a bare pm_runtime_get_sync() needs "
               "either source-backed review proof or a recorded finding.",
        "ref": "hardware-eng-pm-register-access.md#3f.1 Device Power State Before Register Access",
    },
    "resource_abstraction_bypass_source_aware": {
        "fix": "Do not declare an alternate path safe while saying it bypasses a "
               "new resource/rate/power abstraction unless you prove it is "
               "unreachable or contract-compatible.",
        "ref": "hardware-eng-irq-dma-context.md#3f.5 Interrupt and DMA Context Constraints",
    },
    "core_table_vendor_entry_source_aware": {
        "fix": "When a patch threads a vendor/driver-specific construct into a "
               "core subsystem (core table entry, driver-private/vendor #include, "
               "or CONFIG_<VENDOR> guard in drivers/iommu, drivers/base, of/, "
               "kernel/, mm/), raise the layering question as a [CONCERN] and "
               "name the generic alternative, or state the placement is generic "
               "/ maintainer-acknowledged. Do not clear it with a positive note.",
        "ref": "code-logic.md#3c.6 Subsystem Layering / Placement",
    },
    "stack_struct_zero_init_source_aware": {
        "fix": "A stack struct passed by pointer to a kernel API (e.g. "
               "dev_pm_domain_attach_data -> devm_pm_domain_attach_list) must be "
               "zero-initialized (= {} / memset) before field assignment, or the "
               "review must address the uninitialized-field hazard; otherwise "
               "file a [CONCERN]/[BUG].",
        "ref": "code-logic-wire-protocol.md#Wire protocol struct checklist",
    },
    "pas_metadata_release_source_aware": {
        "fix": "A firmware-load path calling qcom_mdt_pas_load()/"
               "qcom_scm_pas_init_image() must pair it with "
               "qcom_scm_pas_metadata_release() once authentication completes, or "
               "the review must flag the per-load metadata leak as a [BUG].",
        "ref": "code-logic-alloc-release.md#API alloc/release-pairing contract checklist",
    },
    "resource_helper_guard_source_aware": {
        "fix": "Show the resource helper's guard/precondition holds on the "
               "touched path in the source tree, or raise a finding.",
        "ref": "code-logic-pointer-api.md#Pointer-returning API call checklist",
    },
    "helper_replacement_postcondition_source_aware": {
        "fix": "Prove the replacement helper establishes every postcondition the "
               "original did (from the source tree), or raise a finding.",
        "ref": "code-logic-interaction.md#3c.4 Interaction Picture",
    },
    "helper_side_effect_source_aware": {
        "fix": "Account for the helper's side effects observed in the source "
               "tree; a dropped side effect is a finding, not a safe clearance.",
        "ref": "code-logic-interaction.md#3c.4 Interaction Picture",
    },
    "escaped_local_address_source_aware": {
        "fix": "If a patch stores `&local` into longer-lived state, file the "
               "stack/local lifetime bug or prove the address does not escape "
               "the current frame before it is consumed.",
        "ref": "code-logic-stored-pointer.md#Stored pointer / escaped-address checklist",
    },
    "setup_return_guard_source_aware": {
        "fix": "When setup/helper status flows toward publish/register/add "
               "work, state where the return is checked or file a finding for "
               "the unchecked path before publication.",
        "ref": "code-logic-setup-result.md#Setup-result / publication audit",
    },
    "newly_exposed_silent_failure_source_aware": {
        "fix": "When a patch rewires a control/capability to a setter that "
               "rejects an advertised zero/default value, compare the public "
               "contract to the setter preconditions and file the newly exposed "
               "silent failure if the replay/apply path drops the return.",
        "ref": "code-logic-setup-result.md#Setup-result / publication audit",
    },
}

# Fallback ref set used when a failed check has no remediation entry (defensive
# — the completeness test should prevent this).  Includes both startup and
# post-startup workflow owners plus the core render/gate refs.
REMEDIATION_FALLBACK_REFS: tuple[str, ...] = (
    "startup-workflow.md",
    "orchestrator-workflow.md",
    "core.md",
    "html-template.md",
    "gate-rules.md",
)


# ---------------------------------------------------------------------------
# Validator coverage metadata
# ---------------------------------------------------------------------------
# The coverage matrix generator combines this metadata with REMEDIATION.  Keep
# one entry per remediation check so every validator failure remains auditable:
# category explains the rule family, artifacts names the inputs inspected, and
# REMEDIATION supplies the governing ref plus repair action.
VALIDATOR_COVERAGE: dict[str, dict[str, tuple[str, ...] | str]] = {
    "gate_trace": {
        "category": "severity/gate",
        "artifacts": ("html_report",),
    },
    "step_record": {
        "category": "structure",
        "artifacts": ("html_report", "step_completion_record"),
    },
    "conditional_sections": {
        "category": "structure",
        "artifacts": ("html_report", "packet_file"),
    },
    "anchor_id": {
        "category": "structure",
        "artifacts": ("html_report",),
    },
    "banner_dedup": {
        "category": "structure",
        "artifacts": ("html_report",),
    },
    "banner_consistency": {
        "category": "structure",
        "artifacts": ("html_report",),
    },
    "verdict_counts_consistency": {
        "category": "structure",
        "artifacts": ("html_report",),
    },
    "render_format": {
        "category": "rendering",
        "artifacts": ("html_report",),
    },
    "pre_existing_scope": {
        "category": "structure",
        "artifacts": ("html_report",),
    },
    "block_fragment": {
        "category": "structure",
        "artifacts": ("html_report", "block_file"),
    },
    "build_break_order": {
        "category": "severity/gate",
        "artifacts": ("html_report", "tests_file", "build_output"),
    },
    "build_artifact_validity": {
        "category": "evidence",
        "artifacts": ("tests_file", "build_output"),
    },
    "hardware_trigger_consistency": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus", "packet_file"),
    },
    "test_results_build_notes_consistency": {
        "category": "report-structure",
        "artifacts": ("html_report",),
    },
    "test_results_fail_evidence": {
        "category": "report-structure",
        "artifacts": ("html_report",),
    },
    "refactor_coverage": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "future_risk_gate": {
        "category": "severity/gate",
        "artifacts": ("html_report",),
    },
    "safe_clearance_gate": {
        "category": "severity/gate",
        "artifacts": ("html_report",),
    },
    "platform_enablement_ready_to_apply": {
        "category": "severity/gate",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "severity_crash_floor": {
        "category": "severity/gate",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "severity_restore_floor": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "codebase_audit_record": {
        "category": "evidence",
        "artifacts": ("html_report", "step_completion_record"),
    },
    "codebase_audit_required": {
        "category": "evidence",
        "artifacts": ("html_report", "patch_corpus", "step_completion_record"),
    },
    "on_demand_reads_record": {
        "category": "evidence",
        "artifacts": ("html_report", "step_completion_record"),
    },
    "inconclusive_requires_read_attempt": {
        "category": "evidence",
        "artifacts": ("html_report", "step_completion_record"),
    },
    "evidence_manifest_record": {
        "category": "evidence",
        "artifacts": ("html_report", "evidence_manifest", "step_completion_record"),
    },
    "evidence_required_reads": {
        "category": "evidence",
        "artifacts": ("html_report", "evidence_manifest", "step_completion_record"),
    },
    "prompt_artifact": {
        "category": "prompt/packet integrity",
        "artifacts": ("prompt_file",),
    },
    "packet_artifact": {
        "category": "prompt/packet integrity",
        "artifacts": ("packet_file",),
    },
    "rule_card_attestation": {
        "category": "rule card enforcement",
        "artifacts": ("packet_file", "html_report"),
    },
    "rule_card_coverage": {
        "category": "rule card enforcement",
        "artifacts": ("packet_file", "html_report", "step_completion_record"),
    },
    "hardware_notes_specificity": {
        "category": "hardware",
        "artifacts": ("html_report", "step_completion_record"),
    },
    "runtime_override_artifact": {
        "category": "prompt/packet integrity",
        "artifacts": ("runtime_config", "sparse_file", "html_report"),
    },
    "source_corpus_required": {
        "category": "evidence",
        "artifacts": ("patch_corpus", "source_root"),
    },
    "binding_parent_compatible_consistency_source_aware": {
        "category": "dt",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "old_dtb_compatibility_source_aware": {
        "category": "dt",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "dt_fallback_old_kernel_new_dtb_source_aware": {
        "category": "dt",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "provider_cells_const_source_aware": {
        "category": "dt",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "optional_clk_dead_enoent_fallback": {
        "category": "dt",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "required_clk_bulk_zero_count_source_aware": {
        "category": "dt",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "framework_status_callback_power_state_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "framework_status_bootloader_refcount_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "managed_device_link_manual_remove_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "retained_dynamic_object_cleanup_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "level_irq_reenable_without_clear_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "binding_companion_dependency_source_aware": {
        "category": "dt",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "dma_names_example": {
        "category": "dt",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "dma_names_source_aware": {
        "category": "dt",
        "artifacts": ("html_report", "patch_corpus", "evidence_manifest"),
    },
    "match_data_guard": {
        "category": "dt",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "match_data_source_aware": {
        "category": "dt",
        "artifacts": ("html_report", "patch_corpus", "evidence_manifest"),
    },
    "selector_cardinality_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "aggregate_per_element_scale_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus", "source_root"),
    },
    "cross_instance_pointer_unbind_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus", "source_root"),
    },
    "peer_dimension_admission_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "evidence_manifest"),
    },
    "duplicate_cleanup_fallthrough_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "evidence_manifest"),
    },
    "failed_start_stale_state_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "evidence_manifest"),
    },
    "paired_callback_backend_symmetry_source_aware": {
        "category": "code-logic-lifecycle",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "alternate_path_state_reset_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus", "source_root"),
    },
    "unvalidated_arithmetic_input_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus", "source_root"),
    },
    "branch_precedence_regression_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus", "source_root"),
    },
    "branch_diversion_producer_coupling_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus", "source_root"),
    },
    "readpath_widening_writer_locked_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus", "source_root"),
    },
    "pm_runtime_get_sync_check": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "device_unregister_pointer_hygiene": {
        "category": "hardware",
        "artifacts": ("html_report",),
    },
    "per_block_vote_scope": {
        "category": "hardware",
        "artifacts": ("html_report",),
    },
    "pm_get_sync_balance": {
        "category": "hardware",
        "artifacts": ("html_report",),
    },
    "pm_runtime_get_sync_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus", "evidence_manifest"),
    },
    "clk_handle_ownership_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "clk_enable_idempotency_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "asoc_dai_target_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "non_alloc_enomem_source_aware": {
        "category": "style/contracts",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "pm_runtime_post_get_return_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "firmware_metadata_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "binding_compatible_conditional_source_aware": {
        "category": "dt-binding",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "pm_runtime_positive_return_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "printf_format_type_source_aware": {
        "category": "style/contracts",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "relocated_teardown_step_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "lock_coverage_symmetry_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "touched_unsafe_pm_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus", "source_root", "evidence_manifest"),
    },
    "resource_abstraction_bypass_source_aware": {
        "category": "hardware",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "core_table_vendor_entry_source_aware": {
        "category": "architecture",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "stack_struct_zero_init_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "pas_metadata_release_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "resource_helper_guard_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "helper_replacement_postcondition_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "helper_side_effect_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus"),
    },
    "escaped_local_address_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus", "evidence_manifest"),
    },
    "setup_return_guard_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus", "evidence_manifest"),
    },
    "newly_exposed_silent_failure_source_aware": {
        "category": "helper/refactor",
        "artifacts": ("html_report", "patch_corpus", "evidence_manifest"),
    },
}


def remediation_for(check: str) -> Optional[dict[str, str]]:
    """Return the {fix, ref} remediation entry for a check, or None."""
    return REMEDIATION.get(check)


# Entry points whose bodies dispatch checks; used to derive each check's mode.
_DISPATCH_ENTRYPOINTS = ("run", "run_block")
# Helper that runs the report-only check tuple; treated as report-only dispatch.
_REPORT_ONLY_DISPATCHER = "_report_only_violations"
# Helper that runs the patch-corpus (source-aware) checks.
_SOURCE_AWARE_DISPATCHER = "_source_aware_violations"


def _derive_check_modes() -> dict[str, str]:
    """Derive each emitted check name's dispatch mode from this module's own
    source — never a hand-maintained list, so it cannot drift.

    Mode is one of:
      report-only  — dispatched via _REPORT_ONLY_CHECKS / _report_only_violations
      source-aware — dispatched via _source_aware_violations (needs patch_corpus)
      structural   — dispatched directly in run()/run_block() (build, evidence,
                     prompt, rules, banner, runtime-override, inline emissions)

    The mapping is function -> emitted check NAMES (the first string arg of each
    Violation(...) in the function body) -> the dispatch path that calls that
    function.  Function names are NOT check names (e.g. check_gate_traces emits
    "gate_trace"), so we resolve names through emitted Violations, and we also
    pick up names emitted inline in the entry-point bodies themselves.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    # Also include the entry-point module (validate_review.py) so that
    # run() / run_block() function bodies — which were split out of this
    # file in Phase 3 — are still visible when deriving dispatch modes.
    _entry_path = Path(__file__).with_name("validate_review.py")
    if _entry_path.is_file():
        source += "\n" + _entry_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    def emitted_names(node: ast.AST) -> set[str]:
        names: set[str] = set()
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "Violation"
                and call.args
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)
            ):
                names.add(call.args[0].value)
        return names

    def called_funcs(node: ast.AST) -> set[str]:
        return {
            call.func.id
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id.startswith("check_")
        }

    funcs = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    report_only_fns = {fn.__name__ for fn in _REPORT_ONLY_CHECKS}
    source_aware_fns = called_funcs(funcs[_SOURCE_AWARE_DISPATCHER]) if _SOURCE_AWARE_DISPATCHER in funcs else set()
    entrypoint_called = set()
    for ep in _DISPATCH_ENTRYPOINTS:
        if ep in funcs:
            entrypoint_called |= called_funcs(funcs[ep])

    def mode_of(fn_name: str) -> Optional[str]:
        if fn_name in report_only_fns:
            return "report-only"
        if fn_name in source_aware_fns:
            return "source-aware"
        if fn_name in entrypoint_called:
            return "structural"
        return None

    modes: dict[str, str] = {}
    for fn_name, node in funcs.items():
        md = mode_of(fn_name)
        if md is None:
            continue
        for name in emitted_names(node):
            # report-only/source-aware are more specific than structural; do not
            # let a structural duplicate downgrade an already-specific mode.
            if name in modes and modes[name] != "structural":
                continue
            modes[name] = md

    # Names emitted directly in the entry-point bodies (e.g. block_fragment,
    # source_corpus_required) are structural by definition.
    for ep in _DISPATCH_ENTRYPOINTS:
        if ep in funcs:
            for name in emitted_names(funcs[ep]):
                modes.setdefault(name, "structural")

    return modes


def validator_manifest() -> dict[str, dict[str, object]]:
    """Self-describing inventory of every validator check.

    Single source of truth: the dispatch wiring (for ``mode``) plus the
    REMEDIATION / VALIDATOR_COVERAGE registry (for ``category``/``ref``/``fix``/
    ``artifacts``).  Nothing here is hand-maintained, so the inventory cannot
    drift from what the validator actually runs.  Keyed by check name.
    """
    modes = _derive_check_modes()
    manifest: dict[str, dict[str, object]] = {}
    for check in sorted(set(REMEDIATION) | set(VALIDATOR_COVERAGE)):
        cov = VALIDATOR_COVERAGE.get(check, {})
        rem = REMEDIATION.get(check, {})
        manifest[check] = {
            "mode": modes.get(check, "unknown"),
            "category": cov.get("category", ""),
            "artifacts": cov.get("artifacts", ()),
            "ref": rem.get("ref", ""),
            "fix": rem.get("fix", ""),
        }
    return manifest


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


def check_verdict_counts_consistency(report: Report) -> list[Violation]:
    """Reject verdict pills that contradict the bug/concern stat-chip counts.

    The skill's report contract maps verdict to severity content as follows:

    - ``READY TO APPLY``     -> 0 bugs AND 0 concerns
    - ``NEEDS DISCUSSION``   -> 0 bugs AND >= 1 concerns
    - ``NEEDS FIXES``        -> >= 1 bugs
    - ``CANNOT APPLY``       -> apply-failure path; no body content gate

    A 2026-06-07 row-465 v3 re-review surfaced a structural lie: verdict
    ``NEEDS DISCUSSION`` with stat chips ``0 bugs / 0 concerns``. The
    existing ``banner_consistency`` check confirmed the chips matched the
    per-block finding-card counts, but no check confronted the verdict pill
    with those counts. This gate closes that hole.

    Reads stat chips rather than re-counting per-block findings: any chip
    drift from per-block findings is already separately caught by
    ``banner_consistency`` (check #4), so duplicating the count here would
    just multiply the violation; pulling from chips means a single root
    cause produces a single, targeted error message.
    """
    if report.verdict == "CANNOT APPLY":
        # Apply-failure verdict has its own validation path; the body need
        # not contain bug/concern findings.
        return []
    if not report.verdict:
        # Missing verdict is caught by the verdict-banner parsing gates;
        # do not pile on here.
        return []

    bugs = report.stat_chips.get("bugs")
    concerns = report.stat_chips.get("concerns")
    # If chips are missing entirely, banner_consistency will already have
    # filed a violation; bail out instead of producing a confusing error
    # against an unparsable banner.
    if bugs is None or concerns is None:
        return []

    violations: list[Violation] = []
    if report.verdict == "READY TO APPLY":
        if bugs > 0 or concerns > 0:
            violations.append(Violation(
                "verdict_counts_consistency",
                "verdict-banner",
                f"verdict 'READY TO APPLY' contradicts stat chips "
                f"(bugs={bugs}, concerns={concerns}); must be 0/0. Either "
                f"escalate the verdict to NEEDS FIXES (bugs>0) or "
                f"NEEDS DISCUSSION (concerns>0), or remove the contradicting "
                f"finding-cards.",
            ))
    elif report.verdict == "NEEDS DISCUSSION":
        if bugs > 0:
            violations.append(Violation(
                "verdict_counts_consistency",
                "verdict-banner",
                f"verdict 'NEEDS DISCUSSION' contradicts stat chips "
                f"(bugs={bugs}); a [BUG] must escalate the verdict to "
                f"NEEDS FIXES.",
            ))
        elif concerns == 0:
            violations.append(Violation(
                "verdict_counts_consistency",
                "verdict-banner",
                f"verdict 'NEEDS DISCUSSION' contradicts stat chips "
                f"(bugs=0, concerns=0); NEEDS DISCUSSION requires >=1 "
                f"[CONCERN] finding-card. Either downgrade the verdict to "
                f"READY TO APPLY or file the [CONCERN] that motivated the "
                f"verdict.",
            ))
    elif report.verdict == "NEEDS FIXES":
        if bugs == 0:
            violations.append(Violation(
                "verdict_counts_consistency",
                "verdict-banner",
                f"verdict 'NEEDS FIXES' contradicts stat chips (bugs=0); "
                f"NEEDS FIXES requires >=1 [BUG] finding-card. Either "
                f"downgrade the verdict (READY TO APPLY when concerns=0, "
                f"NEEDS DISCUSSION when concerns>0) or file the [BUG] that "
                f"motivated the verdict.",
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


_PRE_EXISTING_RE = re.compile(r"\bpre[- ]?existing\b", re.IGNORECASE)
# A finding-card may legitimately mention "pre-existing" only when it documents
# a path this patch makes newly reachable / materially worsens — gate-rules.md
# *requires* such a card to explain the before-vs-after reachability delta.
# Recognise that mandated vocabulary so the scope check does not reject the very
# findings the rules ask for.  A bare "pre-existing" mention with none of these
# markers is a pre-existing-only note that belongs outside finding cards.
_NEWLY_EXPOSED_PATTERNS = (
    re.compile(r"newly\s+(?:reachable|exposed|required|user-visible)", re.IGNORECASE),
    re.compile(r"(?:reachability|before-vs-after|before/after)\s+delta", re.IGNORECASE),
    re.compile(r"exposed\s+by\s+this\s+(?:patch|series)", re.IGNORECASE),
    re.compile(r"(?:materially\s+)?worsen(?:s|ed)?", re.IGNORECASE),
    re.compile(
        r"makes?\s+(?:the\s+|an?\s+)?\S.*?\b(?:reachable|required|user-visible)\b",
        re.IGNORECASE,
    ),
)
_NEGATED_DELTA_PREFIX_RE = re.compile(
    r"\b(?:does|do|did|will|would|can|could|is|are|was|were)\s+not\b"
    r"(?:\W+\w+){0,8}\W*$"
    r"|\b(?:doesn't|don't|didn't|won't|wouldn't|can't|cannot|couldn't)\b"
    r"(?:\W+\w+){0,8}\W*$"
    r"|\b(?:no|without|never)\b(?:\W+\w+){0,8}\W*$"
    r"|\bnot\b(?!\s+only\b)(?:\W+\w+){0,8}\W*$",
    re.IGNORECASE,
)
_VALID_FINDING_ATTRIBUTIONS = {"introduced", "newly_exposed", "pre_existing_only"}


def _has_affirmative_newly_exposed_delta(text: str) -> bool:
    for pattern in _NEWLY_EXPOSED_PATTERNS:
        for match in pattern.finditer(text):
            prefix = text[max(0, match.start() - 120):match.start()]
            if not _NEGATED_DELTA_PREFIX_RE.search(prefix):
                return True
    return False


def check_pre_existing_scope(report: Report) -> list[Violation]:
    """Pre-existing issues must stay out of finding cards and banner summaries.

    Exception: a card that explains how the patch makes a pre-existing path
    newly reachable or materially worse is reportable per gate-rules.md, so it
    is allowed to name the pre-existing origin.
    """
    violations: list[Violation] = []
    cards: list[FindingCard] = []
    cards.extend(report.verdict_banner)
    for block in report.blocks:
        cards.extend(block.findings)

    for card in cards:
        if card.attribution:
            if card.attribution not in _VALID_FINDING_ATTRIBUTIONS:
                where = (
                    f"banner '{card.title[:60]}'"
                    if card.container == "banner"
                    else f"block#{card.block_index} '{card.title[:60]}'"
                )
                violations.append(Violation(
                    "pre_existing_scope",
                    where,
                    "finding-card data-attribution must be one of: "
                    "introduced, newly_exposed, pre_existing_only",
                ))
                continue
            if card.attribution == "pre_existing_only":
                where = (
                    f"banner '{card.title[:60]}'"
                    if card.container == "banner"
                    else f"block#{card.block_index} '{card.title[:60]}'"
                )
                violations.append(Violation(
                    "pre_existing_scope",
                    where,
                    "pre-existing-only issues must not be emitted as `.finding-card`s; "
                    "move this to a patch-local `.preexisting-note` outside verdict/banner/stats",
                ))
                continue
            continue

        text = "\n".join(
            part
            for part in (card.title, card.body, card.file_ref, card.suggestion)
            if part
        )
        if not _PRE_EXISTING_RE.search(text):
            continue
        # Allowed: the card frames the issue as newly reachable / worsened by
        # this patch (the mandated reachability-delta finding).
        if _has_affirmative_newly_exposed_delta(text):
            continue
        where = (
            f"banner '{card.title[:60]}'"
            if card.container == "banner"
            else f"block#{card.block_index} '{card.title[:60]}'"
        )
        violations.append(Violation(
            "pre_existing_scope",
            where,
            "pre-existing-only issues must not be emitted as `.finding-card`s "
            "or banner summaries; move them to a patch-local pre-existing note "
            "so they do not affect verdict/banner/stats. If the patch makes the "
            "path newly reachable or materially worse, state the before-vs-after "
            "reachability delta in the card so it reads as a patch-introduced "
            "regression",
        ))
    return violations


def _section_plain_text(raw_html: str, section_re: re.Pattern[str]) -> str:
    # If the same <h3>...</h3> marker appears more than once in raw_html (e.g.
    # the agent embedded an HTML-escaped section header inside a <pre> block,
    # which the parser un-escapes back into a tag-shaped string and now
    # collides with the real injected marker), pick the longest non-empty
    # body across all matches so the real section content wins.
    best = ""
    for match in section_re.finditer(raw_html):
        text = re.sub(r"<[^>]+>", " ", match.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > len(best):
            best = text
    return best


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


# Test Results card vs per-block Build/Test Notes consistency.
#
# Catches the failure mode where the Test Results card says
# `<td>Build (W=1)</td><td><span class="result-fail">FAIL</span></td>`
# but a per-commit block's Build/Test Notes prose explicitly contradicts it
# ("Build (W=1): PASS — ... Restart config ... benign ... not a build failure").
# The agent's two passes reached opposite conclusions and never reconciled the
# card; without this check the saved report ships with a misleading FAIL row
# whose Notes cell has no concrete error evidence.
_TEST_RESULTS_BUILD_ROW_RE = re.compile(
    r"<td>\s*Build\s*\(W=1\)\s*</td>\s*"
    r"<td>\s*<span\s+class=\"result-fail\">\s*FAIL\s*</span>\s*</td>\s*"
    r"<td>([^<]*)</td>",
    re.IGNORECASE | re.DOTALL,
)
_BUILD_NOTES_PASS_RE = re.compile(
    r"<strong>\s*Build\s*\(W=1\)\s*:\s*</strong>\s*PASS\b"
    r"|build proceeded to successful completion"
    r"|benign\s+(?:<code>)?\s*Restart\s+config[^<]*not\s+(?:a\s+)?build\s+failure"
    r"|not\s+(?:a\s+)?build\s+failure"
    r"|build\s+failure\s+reported\s+in\s+the\s+assembled\s+report\s+header\s+was\s+not\s+introduced",
    re.IGNORECASE | re.DOTALL,
)
_BUILD_NOTES_REAL_ERROR_RE = re.compile(
    r"\berror:\s*\S|\bfails?\s+to\s+compile\b|\bimplicit\s+declaration\b"
    r"|\bundefined\s+reference\b|\bcompile\s*error\b",
    re.IGNORECASE,
)


def check_test_results_vs_build_notes(report: Report) -> list[Violation]:
    """Reject reports where Test Results card says Build FAIL but per-block
    Build/Test Notes say it was a benign syncconfig restart and the build
    actually passed. Forces the agent to reconcile the contradiction so the
    saved report does not ship a misleading FAIL row.
    """
    violations: list[Violation] = []
    if not report.raw_html:
        return violations
    row = _TEST_RESULTS_BUILD_ROW_RE.search(report.raw_html)
    if not row:
        return violations
    notes_cell = row.group(1)
    # If the Test Results Notes cell already quotes a concrete compiler error,
    # the FAIL is well-evidenced — do not flag.
    if _BUILD_NOTES_REAL_ERROR_RE.search(notes_cell):
        return violations
    # Otherwise: scan every per-block Build/Test Notes for a PASS / "not a
    # build failure" narrative. Any such block contradicts the FAIL row.
    contradicting_blocks: list[str] = []
    for block in report.blocks:
        if _BUILD_NOTES_PASS_RE.search(block.raw_html):
            contradicting_blocks.append(f"block#{block.index} '{block.subject[:60]}'")
    if not contradicting_blocks:
        return violations
    for where in contradicting_blocks:
        violations.append(Violation(
            "test_results_build_notes_consistency",
            where,
            "Test Results card says Build (W=1) FAIL with no concrete compiler "
            "error in its Notes cell, but this block's Build/Test Notes assert "
            "PASS / benign syncconfig restart. Reconcile: if the build actually "
            "passed, change the Test Results row to PASS and explain the "
            "syncconfig prompts in the Notes cell; if it really failed, quote "
            "the compiler error in the Notes cell.",
        ))
    return violations


# Test Results FAIL rows must carry concrete evidence in their Notes cell —
# either a quoted compiler/checker diagnostic, or an explicit pointer to the
# per-block detail section that explains the failure.  A bare "failure(s):
# patch N" count or a lone "FAIL" is not actionable and forces the reader to
# go grep the build log themselves to figure out what failed.
_TEST_RESULTS_ANY_FAIL_ROW_RE = re.compile(
    r"<tr>\s*"
    r"<td>\s*([^<]+?)\s*</td>\s*"                             # Test name
    r"<td>\s*<span\s+class=\"result-fail\">\s*FAIL\s*</span>\s*</td>\s*"
    r"<td>([^<]*(?:<[^>]+>[^<]*)*?)</td>\s*"                  # Notes (may have inline tags)
    r"</tr>",
    re.IGNORECASE | re.DOTALL,
)
# Concrete evidence shapes accepted in a FAIL Notes cell:
#   1. quoted compiler/checker diagnostic
#   2. explicit pointer to a per-block details section/anchor
_FAIL_EVIDENCE_QUOTE_RE = re.compile(
    r"\berror\s*:\s*\S"
    r"|\bwarning\s*:\s*\S"
    r"|\bimplicit\s+declaration\b"
    r"|\bundefined\s+reference\b"
    r"|\bfails?\s+to\s+compile\b"
    r"|\bcompile\s*error\b"
    r"|\bWARNING\b\s*:\s*\S"
    r"|\bCHECK\b\s*:\s*\S",
    re.IGNORECASE,
)
_FAIL_EVIDENCE_POINTER_RE = re.compile(
    r"see\s+(?:Patch|patch|block|<h3>|the?\s+Build\s*/\s*Test\s+Notes|below|the?\s+per[- ]?(?:patch|commit)\s+(?:notes?|section))"
    r"|Build\s*/\s*Test\s+Notes\b"
    r"|<a\s+href=\"#"
    r"|patch[- ]?\d+[- ]?finding[- ]?\d+",
    re.IGNORECASE,
)


def check_test_results_fail_evidence(report: Report) -> list[Violation]:
    """Every FAIL row in the Test Results card must show concrete evidence in
    its Notes cell — either a quoted compiler/checker diagnostic ("error: …",
    "WARNING: …") or an explicit pointer ("see Patch N", "Build / Test Notes",
    or an anchor link) to the per-block section that explains the failure.

    Bare counts ("Per-patch W=1 build artifact failure(s): patch 1") force the
    reader to go grep the build log to find out what actually failed; the saved
    report should be self-contained.
    """
    violations: list[Violation] = []
    if not report.raw_html:
        return violations
    for match in _TEST_RESULTS_ANY_FAIL_ROW_RE.finditer(report.raw_html):
        test_name = match.group(1).strip()
        notes_cell = match.group(2)
        # Strip inline HTML tags but keep their text content for the evidence
        # check, so <code>error: foo</code> still counts as a quoted diagnostic.
        notes_text = re.sub(r"<[^>]+>", " ", notes_cell)
        notes_text = re.sub(r"\s+", " ", notes_text).strip()
        has_quote = bool(_FAIL_EVIDENCE_QUOTE_RE.search(notes_text))
        has_pointer = bool(_FAIL_EVIDENCE_POINTER_RE.search(notes_cell))
        if has_quote or has_pointer:
            continue
        violations.append(Violation(
            "test_results_fail_evidence",
            f"test-row '{test_name}'",
            f"Test Results card has '{test_name}' = FAIL but the Notes cell "
            f"({notes_text[:120]!r}) has no concrete failure evidence — "
            "neither a quoted compiler/checker diagnostic ('error: …', "
            "'WARNING: …', 'implicit declaration', etc.) nor an explicit "
            "pointer ('see Patch N', 'see Build / Test Notes', or an anchor "
            "link) to the per-block section that explains the failure.",
        ))
    return violations


def check_hardware_notes_specificity(report: Report) -> list[Violation]:
    """DONE hardware review notes must contain concrete evidence, not boilerplate."""
    violations: list[Violation] = []
    for block in report.blocks:
        if not block.step_record or not _HARDWARE_DONE_RE.search(block.step_record):
            continue
        note = _section_plain_text(block.raw_html, _HARDWARE_SECTION_RE)
        if not note:
            violations.append(Violation(
                "hardware_notes_specificity",
                f"block#{block.index} '{block.subject[:60]}'",
                "step_3f_hardware_eng is DONE but Hardware Engineering Notes "
                "are missing or empty",
            ))
            continue

        reasons: list[str] = []
        if _GENERIC_HARDWARE_NOTE_RE.search(note) and not _HARDWARE_EVIDENCE_RE.search(note):
            reasons.append("generic hardware note has no concrete patch/context evidence")

        visible = f"{block.subject}\n{block.raw_html}"
        if (
            _THERMAL_HW_CONTEXT_RE.search(visible)
            and not _THERMAL_HARDWARE_EVIDENCE_RE.search(note)
        ):
            reasons.append(
                "thermal/cooling review must cite concrete values or wiring "
                "(#cooling-cells, tmd-names, trip/hysteresis values, "
                "providers/consumers, or QMI IDs)"
            )

        if reasons:
            violations.append(Violation(
                "hardware_notes_specificity",
                f"block#{block.index} '{block.subject[:60]}'",
                "; ".join(reasons),
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
    """Check #12 — non-defect/process-only conclusions are not findings."""
    violations: list[Violation] = []
    cards: list[FindingCard] = []
    for block in report.blocks:
        cards.extend(block.findings)
    for card in cards:
        # The safe-clearance gate exists to protect verdict/banner/stat
        # integrity, which is driven solely by BUG/CONCERN findings.  MINOR/NIT
        # cards never move the verdict, and their natural register ("worth
        # verifying", "acceptable as-is", gate-trace prose that says a call
        # "fails") collides with every trigger here — including the
        # safe-clearance phrasing, which false-positives on gate-trace
        # boilerplate.  Restrict the whole gate to BUG/CONCERN so a low-severity
        # note can never force a blocking repair/abort over wording alone.
        if card.severity not in ("BUG", "CONCERN"):
            continue
        text = f"{card.title}\n{card.body}\n{card.suggestion}"
        has_concrete_harm = bool(_CONCRETE_HARM_RE.search(text))
        has_patch_delta = _has_affirmative_newly_exposed_delta(text)
        reason = ""
        if _SAFE_CLEARANCE_RE.search(text) or _NO_ACTION_NEEDED_RE.search(card.suggestion):
            reason = (
                "finding concludes the current path is safe or needs no action"
            )
        elif (
            _EXPLICIT_NON_DEFECT_RE.search(text)
            and not has_concrete_harm
            and not has_patch_delta
        ):
            reason = (
                "finding says the cited point is correct as written or not a defect"
            )
        elif _PROCESS_ONLY_RE.search(text) and not _CONCRETE_HARM_RE.search(text):
            reason = (
                "finding is only a process/informational note without concrete harm"
            )
        if not reason:
            continue
        violations.append(Violation(
            "safe_clearance_gate",
            f"block#{card.block_index} '{card.title[:60]}'",
            reason + "; dismiss it or move it to Positive Notes / patch-local "
            "prose instead of a counted finding-card",
        ))
    return violations


def check_platform_enablement_ready_to_apply(report: Report) -> list[Violation]:
    """Reject under-justified READY TO APPLY verdicts on add-support series."""
    if report.verdict != "READY TO APPLY":
        return []

    visible_all = _visible_report_text(report)
    if not _PLATFORM_ENABLEMENT_TRIGGER_RE.search(visible_all):
        return []
    if not _PLATFORM_ENABLEMENT_SCOPE_RE.search(visible_all):
        return []

    missing: list[str] = []
    if not _PLATFORM_LIFECYCLE_PROOF_RE.search(visible_all):
        missing.append("lifecycle cleanup/unwind proof")
    if not _PLATFORM_FALLBACK_PROOF_RE.search(visible_all):
        missing.append("compatibility fallback / old-DTB proof")
    if not _PLATFORM_SELECTOR_CARDINALITY_PROOF_RE.search(visible_all):
        missing.append("selector/cardinality proof")

    if not missing:
        return []

    return [Violation(
        "platform_enablement_ready_to_apply",
        "report verdict READY TO APPLY",
        "platform-enablement / add-support series is left READY TO APPLY "
        "without explicit audit proof for: " + ", ".join(missing),
    )]


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
                "or `put_noidle` on the error path); see refs/hardware-eng-pm-register-access.md "
                "`pm_runtime bracket`",
            ))
    return violations


def _block_has_finding(block: CommitBlock, pattern: re.Pattern) -> bool:
    """True when any [BUG]/[CONCERN] card in the block matches ``pattern``."""
    return any(
        card.severity in ("BUG", "CONCERN")
        and pattern.search(f"{card.title}\n{card.body}")
        for card in block.findings
    )


def check_device_unregister_pointer_hygiene(report: Report) -> list[Violation]:
    """Phase 1 false-clearance teeth — `device_unregister()` pointer hygiene.

    When a block's analysis unregisters / `put_device()`s a caller-owned object
    whose pointer can be observed later (e.g. ``core->fw_dev``, drvdata, a cached
    handle) it may only be cleared as safe by quoting the concrete ``<ptr> =
    NULL`` reset line, an explicit no-escape statement, or by filing a
    `[BUG]`/`[CONCERN]` for the stale pointer.  A positive note or "symmetric
    cleanup" prose is not a discharge.  Mirrors refs/hardware-eng.md
    (`device_unregister() pointer hygiene`) and refs/gate-rules.md
    (Clearance-proof rule).
    """
    violations: list[Violation] = []
    for block in report.blocks:
        visible = f"{block.subject}\n{block.raw_html}"
        if not _DEVICE_UNREGISTER_RE.search(visible):
            continue
        if not _DEVICE_UNREGISTER_OWNED_PTR_RE.search(visible):
            # No caller-owned/re-observable pointer in scope — a local
            # put_device() on an error path needs no NULL reset.
            continue
        # Discharged by a finding that names the stale-pointer hazard?
        if _block_has_finding(block, _DEVICE_UNREGISTER_FINDING_RE):
            continue
        if _DEVICE_UNREGISTER_FINDING_RE.search(visible):
            # The hazard is named somewhere in the block's prose (finding or
            # pre-existing note) — not a silent clearance.
            continue
        # Cleared as safe: require a quoted discharge line.
        if _DEVICE_UNREGISTER_NULL_PROOF_RE.search(visible):
            continue
        if _DEVICE_UNREGISTER_NO_ESCAPE_RE.search(visible):
            continue
        violations.append(Violation(
            "device_unregister_pointer_hygiene",
            f"block#{block.index} '{block.subject[:60]}'",
            "block unregisters/put_device()s a caller-owned object (e.g. "
            "->fw_dev / drvdata / cached handle) and clears it as safe without "
            "quoting the `<ptr> = NULL` reset line, an explicit no-escape "
            "statement, or filing a stale-pointer [BUG]/[CONCERN]; see "
            "refs/hardware-eng-resource-lifecycle.md `device_unregister() pointer hygiene`",
        ))
    return violations


def check_per_block_vote_scope(report: Report) -> list[Violation]:
    """Phase 1 false-clearance teeth — global vote dropped in a per-block helper.

    When a block's analysis shows a global OPP/performance/genpd/clock-rate vote
    DROP inside a per-block / per-core helper that a multi-block sequence calls
    once per block, it may only be cleared as safe by tracing the full
    multi-block sequence (naming siblings and proving none stays active) or by
    filing a `[BUG]`/`[CONCERN]`.  Local symmetry inside one helper is not a
    discharge.  Mirrors refs/hardware-eng.md (`Global vote scope vs per-block
    helpers`) and refs/gate-rules.md (Clearance-proof rule).
    """
    violations: list[Violation] = []
    for block in report.blocks:
        visible = f"{block.subject}\n{block.raw_html}"
        if not _PER_BLOCK_HELPER_RE.search(visible):
            continue
        if not _GLOBAL_VOTE_DROP_RE.search(visible):
            continue
        if not _GLOBAL_VOTE_CONTEXT_RE.search(visible):
            # The vote-drop token is present but the block never frames it as a
            # global OPP/perf/genpd vote — nothing to clear.
            continue
        if _block_has_finding(block, _PER_BLOCK_VOTE_FINDING_RE):
            continue
        if _PER_BLOCK_VOTE_FINDING_RE.search(visible):
            continue
        if _PER_BLOCK_VOTE_PROOF_RE.search(visible):
            continue
        violations.append(Violation(
            "per_block_vote_scope",
            f"block#{block.index} '{block.subject[:60]}'",
            "block drops a global OPP/performance/genpd/clock-rate vote inside a "
            "per-block/per-core helper and clears it as safe without tracing the "
            "full multi-block sequence (naming siblings and proving none stays "
            "active) or filing a [BUG]/[CONCERN]; see refs/hardware-eng-pm-register-access.md "
            "`Global vote scope vs per-block helpers`",
        ))
    return violations


def check_pm_get_sync_balance(report: Report) -> list[Violation]:
    """Phase 1 false-clearance teeth — `pm_runtime_get_sync()` error balancing.

    A failed ``pm_runtime_get_sync()`` has already incremented the usage count,
    so the error edge must call ``pm_runtime_put_noidle()`` (or migrate to
    ``pm_runtime_resume_and_get``).  When a block clears a ``get_sync`` call as
    "correct" but the cited balancing call on the error path is
    ``pm_runtime_put_sync()`` / ``pm_runtime_put()`` — which does NOT balance an
    already-incremented count after a failed resume — it is a false clearance.
    Mirrors refs/hardware-eng.md `pm_runtime bracket` and refs/gate-rules.md
    (Clearance-proof rule).  This complements ``check_pm_runtime_get_sync``,
    which only requires the topic to be considered; this check rejects the
    specific wrong-discharge.
    """
    violations: list[Violation] = []
    for block in report.blocks:
        visible = f"{block.subject}\n{block.raw_html}"
        if not _PM_GET_SYNC_CLEARED_RE.search(visible):
            continue
        # A correct discharge (put_noidle / resume_and_get) anywhere in scope.
        if _PM_GET_SYNC_NOIDLE_PROOF_RE.search(visible):
            continue
        # Discharged by a finding naming the imbalance.
        if _block_has_finding(block, _PM_GET_SYNC_FINDING_RE):
            continue
        # Fire only when the wrong balance (put_sync/put on error) is the cited
        # discharge — otherwise check_pm_runtime_get_sync already covers it.
        if _PM_GET_SYNC_WRONG_BALANCE_RE.search(visible):
            violations.append(Violation(
                "pm_get_sync_balance",
                f"block#{block.index} '{block.subject[:60]}'",
                "block clears a `pm_runtime_get_sync()` as correct but cites "
                "`pm_runtime_put_sync()`/`pm_runtime_put()` on the error path; a "
                "failed get_sync leaves the usage count incremented and must be "
                "balanced with `pm_runtime_put_noidle()` (or migrate to "
                "`pm_runtime_resume_and_get`).  Quote the put_noidle line or file "
                "a [BUG]/[CONCERN]; see refs/hardware-eng-pm-register-access.md `pm_runtime bracket`",
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


def _documents_pre_existing_build_failure(report: Report, tests_text: str) -> bool:
    """Return True when the report proves a build failure is not patch-caused.

    The proof may be in the same text as the failure mention (windowed search)
    OR in a different text (e.g. the subagent writes the explanation in a
    per-commit block while the failure mention lives in the tests summary).
    When the windowed search fails, fall back to a global proof search across
    all block HTML to handle this cross-text case.
    """
    texts = [tests_text]
    texts.extend(f"{block.subject}\n{block.raw_html}" for block in report.blocks)
    found_failure_mention = False
    for text in texts:
        for match in _BUILD_FAILURE_MENTION_RE.finditer(text):
            found_failure_mention = True
            window = text[max(0, match.start() - 240): match.end() + 480]
            if _PRE_EXISTING_BUILD_PROOF_RE.search(window):
                return True
    # Cross-text fallback: if a build failure was mentioned anywhere (including
    # the simple "build" + "fail" substring test that gates the caller), search
    # all block texts globally for proof language.  This handles:
    # (1) tests_text says "Build (W=1) FAIL" but proof is in block HTML;
    # (2) tests_text is synthetic ("Build: FAIL") and regex doesn't match but
    #     blocks contain the full "base tree" / "not introduced" explanation.
    if found_failure_mention or ("build" in tests_text.lower() and "fail" in tests_text.lower()):
        for text in texts[1:]:  # skip tests_text (already windowed)
            if _PRE_EXISTING_BUILD_PROOF_RE.search(text):
                return True
    return False


def check_build_break_order(
    report: Report,
    tests_text: str,
    *,
    require_banner: bool = True,
) -> list[Violation]:
    """Check #7 — introduced build-break findings lead their block/banner.

    Block-mode validation runs before the verdict banner exists, so it enforces
    only the per-commit ordering.  Full-report validation keeps the banner
    requirement enabled.  A W=1 failure that is explicitly proven pre-existing is
    not a patch finding and should stay in test/build notes instead of forcing a
    synthetic [BUG].
    """
    violations: list[Violation] = []
    if not tests_text:
        return violations
    lt = tests_text.lower()
    if "build" not in lt or "fail" not in lt:
        return violations
    if _documents_pre_existing_build_failure(report, tests_text):
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
            "build log shows a Kconfig syncconfig prompt transcript "
            "(`Restart config...` or `Error in reading or end of file.`) "
            "instead of clean W=1 compiler output. Build verification is "
            "invalid; rerun run_w1_build.py so it seeds `make ARCH=arm64 "
            "defconfig`, runs `make ARCH=arm64 olddefconfig`, then rebuilds.",
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


def _augment_with_source_root(patch_corpus: str, source_root: Optional[Path]) -> str:
    """Append the contents of each touched file under ``source_root`` to the
    patch corpus, so source-aware checks can inspect unchanged context (struct
    definitions, driver flags) that the diff only references.

    Missing files and unreadable files are skipped silently — the corpus alone
    remains the fallback search text.
    """
    searched_text = patch_corpus
    if isinstance(source_root, Path):
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
    return searched_text


def _iter_source_diff_bodies(patch_corpus: str) -> list[tuple[str, str]]:
    diffs: list[tuple[str, str]] = []
    for match in _SOURCE_DIFF_RE.finditer(patch_corpus):
        path = match.group("path")
        if path.endswith((".c", ".h", ".cc", ".cpp", ".rs")):
            diffs.append((path, match.group("body")))
    return diffs


def _visible_diff_lines(body: str) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    for raw_line in body.splitlines():
        if not raw_line or raw_line[0] not in "+ ":
            continue
        lines.append((raw_line[0], raw_line[1:]))
    return lines


def _added_diff_text(body: str) -> str:
    return "\n".join(
        raw_line[1:]
        for raw_line in body.splitlines()
        if raw_line.startswith("+") and not raw_line.startswith("+++")
    )


def _contextual_diff_text(body: str) -> str:
    return "\n".join(line for _sign, line in _visible_diff_lines(body))


_PAIRED_PREPARE_FALLBACK_RE = re.compile(
    r"\b(?P<ops>[A-Za-z_]\w*)\s*=\s*READ_ONCE\([^;]*\)\s*;\s*"
    r"if\s*\(\s*(?P=ops)\s*\)\s*\{\s*"
    r"(?P<ret>[A-Za-z_]\w*)\s*=\s*(?P=ops)->(?P<prepare>[A-Za-z_]\w*prepare)\s*\([^;]*\)\s*;\s*"
    r"if\s*\(\s*!\s*(?P=ret)\s*\|\|\s*(?P=ret)\s*==\s*-[A-Z0-9_]+\s*\)\s*"
    r"return\s+(?P=ret)\s*;\s*"
    r"(?P=ret)\s*=\s*0\s*;\s*\}",
    re.DOTALL,
)
_PAIRED_UNPREPARE_EARLY_RETURN_RE = re.compile(
    r"\b(?P<ops>[A-Za-z_]\w*)\s*=\s*READ_ONCE\([^;]*\)\s*;\s*"
    r"if\s*\(\s*(?P=ops)\s*\)\s*(?:\{\s*)?"
    r"if\s*\(\s*!\s*(?P=ops)->(?P<unprepare>[A-Za-z_]\w*unprepare)\s*\([^;]*\)\s*\)\s*"
    r"return\s+0\s*;",
    re.DOTALL,
)
_PAIRED_NORMAL_STATE_SET_RE = re.compile(
    r"->\s*(?:reading|prepared|active|started|enabled)\s*=\s*true\s*;",
    re.IGNORECASE,
)
_PAIRED_NORMAL_STATE_CLEAR_RE = re.compile(
    r"->\s*(?:reading|prepared|active|started|enabled)\s*=\s*false\s*;",
    re.IGNORECASE,
)
_PAIRED_SESSION_STATE_RE = re.compile(
    r"(?:->|\.)\s*(?:reading|prepared|active|started)\b",
    re.IGNORECASE,
)
_PAIRED_UNPREPARE_SAFE_REJECT_RE = re.compile(
    r"if\s*\([^)]*!\s*[^)]*(?:->|\.)\s*(?:reading|prepared|active|started)\b[^)]*\)"
    r"\s*(?:\{\s*)?(?:return\s+-[A-Z0-9_]+|goto\s+[A-Za-z_]\w*)\s*;",
    re.IGNORECASE | re.DOTALL,
)
_PAIRED_RETURN_ZERO_RE = re.compile(r"\breturn\s+0\s*;", re.IGNORECASE)


def _extract_added_c_function_bodies(added: str) -> dict[str, str]:
    bodies: dict[str, str] = {}
    header_re = re.compile(
        r"(?:^|\n)\s*(?:static\s+)?(?:inline\s+)?[A-Za-z_][\w\s\*]*\s+"
        r"(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{",
        re.MULTILINE,
    )
    for match in header_re.finditer(added):
        name = match.group("name")
        brace = match.end() - 1
        depth = 0
        end = brace
        for index in range(brace, len(added)):
            char = added[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end > brace:
            bodies[name] = added[brace:end]
    return bodies


def _paired_unprepare_callbacks(added: str) -> set[str]:
    callbacks: set[str] = set()
    for match in re.finditer(
        r"\.\s*(?:[A-Za-z_]\w*unprepare|release|stop)\s*=\s*([A-Za-z_]\w*)",
        added,
        re.IGNORECASE,
    ):
        callbacks.add(match.group(1))
    if callbacks:
        return callbacks
    return set(re.findall(r"\b([A-Za-z_]\w*unprepare[A-Za-z_]\w*)\s*\(", added))


def _unprepare_callback_rejects_unprepared_session(function_body: str) -> bool:
    first_success = _PAIRED_RETURN_ZERO_RE.search(function_body)
    search_region = function_body[: first_success.start()] if first_success else function_body
    return bool(_PAIRED_UNPREPARE_SAFE_REJECT_RE.search(search_region))


def _paired_callback_backend_symmetry_hits(patch_corpus: str) -> list[str]:
    added = _added_diff_text(patch_corpus)
    contextual = _contextual_diff_text(patch_corpus)
    function_bodies = _extract_added_c_function_bodies(added)
    unprepare_callbacks = _paired_unprepare_callbacks(added)
    hits: list[str] = []
    for prepare_match in _PAIRED_PREPARE_FALLBACK_RE.finditer(added):
        ops = prepare_match.group("ops")
        unprepare_match = None
        for candidate in _PAIRED_UNPREPARE_EARLY_RETURN_RE.finditer(added):
            if candidate.group("ops") == ops:
                unprepare_match = candidate
                break
        if unprepare_match is None:
            continue
        if not (_PAIRED_NORMAL_STATE_SET_RE.search(contextual) and _PAIRED_NORMAL_STATE_CLEAR_RE.search(contextual)):
            continue
        callback_bodies = [
            function_bodies[name]
            for name in sorted(unprepare_callbacks)
            if name in function_bodies and re.search(r"(?:unprepare|release|stop)", name, re.IGNORECASE)
        ]
        stateful_callback_bodies = [
            body for body in callback_bodies if _PAIRED_SESSION_STATE_RE.search(body)
        ]
        if stateful_callback_bodies and all(
            _unprepare_callback_rejects_unprepared_session(body)
            for body in stateful_callback_bodies
        ):
            continue
        hits.append(
            f"{ops}->{prepare_match.group('prepare')} falls back; "
            f"{ops}->{unprepare_match.group('unprepare')} can early-return without "
            "a source-proven !reading/!prepared session reject"
        )
    return hits


def _visible_report_text(report: Report) -> str:
    return "\n".join(f"{block.subject}\n{block.raw_html}" for block in report.blocks)


def _review_has_finding_or_discussion(report: Report, pattern: re.Pattern[str]) -> bool:
    return bool(pattern.search(_visible_report_text(report)))


def _iter_report_findings_text(report: Report):
    for card in report.verdict_banner:
        yield "\n".join((card.severity, card.title, card.body, card.file_ref, card.suggestion))
    for block in report.blocks:
        for card in block.findings:
            yield "\n".join((card.severity, card.title, card.body, card.file_ref, card.suggestion))


def _regex_windows(text: str, pattern: re.Pattern[str], radius: int = 260):
    for match in pattern.finditer(text):
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        yield text[start:end]


def _review_has_required_clk_zero_count_discussion(report: Report) -> bool:
    """Return True only for counted BUG/CONCERN zero-count findings.

    The rule targets required resources: a MINOR note or SAFE prose that says
    the binding should require clocks must not discharge the validator, because
    the runtime path still silently accepts an invalid DT/overlay/old DTB.
    """
    for card in report.verdict_banner:
        finding_text = "\n".join((card.severity, card.title, card.body, card.file_ref, card.suggestion))
        if (
            card.severity in {"BUG", "CONCERN"}
            and _REQUIRED_CLK_ZERO_COUNT_REPORT_RE.search(finding_text)
        ):
            return True
    for block in report.blocks:
        for card in block.findings:
            finding_text = "\n".join((card.severity, card.title, card.body, card.file_ref, card.suggestion))
            if (
                card.severity in {"BUG", "CONCERN"}
                and _REQUIRED_CLK_ZERO_COUNT_REPORT_RE.search(finding_text)
            ):
                return True
    return False


_UNSOURCED_PROOF_HEDGE_RE = re.compile(
    r"requires?\s+verification|needs?\s+verification|should\s+verify|"
    r"must\s+verify|assumption|unclear|unknown|if\s+[^.]{0,120}?"
    r"(?:always[- ]on|accessible|ungated|clock[- ]independent)|"
    r"(?:may|might|could)\s+[^.]{0,120}?(?:always[- ]on|accessible|ungated)",
    re.IGNORECASE,
)


def _has_framework_status_callback_power_proof(text: str) -> bool:
    if not _FRAMEWORK_STATUS_CALLBACK_PROOF_RE.search(text):
        return False
    return not _UNSOURCED_PROOF_HEDGE_RE.search(text)


def _review_has_framework_status_callback_power_discussion(report: Report) -> bool:
    for card in report.verdict_banner:
        finding_text = "\n".join((card.severity, card.title, card.body, card.file_ref, card.suggestion))
        if not _FRAMEWORK_STATUS_CALLBACK_REPORT_RE.search(finding_text):
            continue
        if card.severity in {"BUG", "CONCERN"}:
            return True
        if _has_framework_status_callback_power_proof(finding_text):
            return True
    for block in report.blocks:
        for card in block.findings:
            finding_text = "\n".join((card.severity, card.title, card.body, card.file_ref, card.suggestion))
            if not _FRAMEWORK_STATUS_CALLBACK_REPORT_RE.search(finding_text):
                continue
            if card.severity in {"BUG", "CONCERN"}:
                return True
            if _has_framework_status_callback_power_proof(finding_text):
                return True

    visible = _visible_report_text(report)
    for window in _regex_windows(visible, _FRAMEWORK_STATUS_CALLBACK_REPORT_RE):
        if _has_framework_status_callback_power_proof(window):
            return True
        if _FRAMEWORK_STATUS_CALLBACK_SAFE_DISMISSAL_RE.search(window):
            continue
    return False


def _framework_status_callback_power_hits(patch_corpus: str) -> list[str]:
    hits: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        if not _STATUS_CALLBACK_CLOCK_CONTEXT_RE.search(body):
            continue
        has_direct_regmap_status = bool(_STATUS_REGMAP_CALLBACK_ADD_RE.search(body))
        has_custom_status_mmio = (
            bool(_STATUS_CUSTOM_CALLBACK_ADD_RE.search(body))
            and bool(_STATUS_CALLBACK_MMIO_BODY_RE.search(body))
        )
        if has_direct_regmap_status or has_custom_status_mmio:
            hits.append(path)
    return hits


def _review_has_old_kernel_new_dtb_fallback_discussion(report: Report) -> bool:
    for card in report.verdict_banner:
        finding_text = "\n".join((card.severity, card.title, card.body, card.file_ref, card.suggestion))
        if (
            card.severity in {"BUG", "CONCERN"}
            and _OLD_KERNEL_NEW_DTB_FALLBACK_REPORT_RE.search(finding_text)
        ):
            return True
    for block in report.blocks:
        for card in block.findings:
            finding_text = "\n".join((card.severity, card.title, card.body, card.file_ref, card.suggestion))
            if (
                card.severity in {"BUG", "CONCERN"}
                and _OLD_KERNEL_NEW_DTB_FALLBACK_REPORT_RE.search(finding_text)
            ):
                return True

    visible = _visible_report_text(report)
    for window in _regex_windows(visible, _OLD_KERNEL_NEW_DTB_FALLBACK_REPORT_RE):
        if _OLD_KERNEL_NEW_DTB_FALLBACK_SAFE_RE.search(window):
            continue
        if _OLD_KERNEL_NEW_DTB_FALLBACK_ACTION_RE.search(window):
            return True
    return False


def _fallback_from_source_neighbor(
    source_root: Optional[Path],
    binding_path: str,
    neighbor_compat: str,
) -> str:
    if source_root is None:
        return ""
    try:
        text = (source_root / binding_path).read_text(encoding="utf-8")
    except OSError:
        return ""
    start = text.find(neighbor_compat)
    if start < 0:
        return ""
    match = _FALLBACK_CONST_RE.search(text[start:start + 1200])
    return match.group("compat") if match else ""


def _new_compat_fallback_hits(
    patch_corpus: str,
    source_root: Optional[Path] = None,
) -> list[str]:
    if not _FALLBACK_RESOURCE_QUIRK_RE.search(patch_corpus):
        return []
    hits: list[str] = []
    for path, body in _iter_binding_diff_bodies(patch_corpus):
        for match in _ADDED_COMPAT_LINE_RE.finditer(body):
            primary = match.group("compat")
            window = body[match.start():match.start() + 1200]
            fallback_match = _FALLBACK_CONST_RE.search(window)
            fallback = fallback_match.group("compat") if fallback_match else ""
            if not fallback:
                neighbors = [
                    compat for compat in _COMPAT_STRING_RE.findall(window)
                    if compat.lower() != primary.lower()
                ]
                if neighbors:
                    fallback = _fallback_from_source_neighbor(source_root, path, neighbors[0])
            if not fallback or fallback.lower() == primary.lower():
                continue
            if primary not in patch_corpus:
                continue
            hits.append(f"{path}:{primary}->{fallback}")
    return hits


def _review_has_bootloader_refcount_discussion(report: Report) -> bool:
    for finding_text in _iter_report_findings_text(report):
        if _BOOTLOADER_REFCOUNT_REPORT_RE.search(finding_text):
            return True

    visible = _visible_report_text(report)
    for window in _regex_windows(visible, _BOOTLOADER_REFCOUNT_REPORT_RE):
        if _BOOTLOADER_REFCOUNT_SAFE_RE.search(window):
            continue
        return True
    return False


def _framework_status_bootloader_refcount_hits(patch_corpus: str) -> list[str]:
    hits: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        if not _STATUS_CALLBACK_REFCOUNT_CONTEXT_RE.search(body):
            continue
        if not _CLK_BULK_ENABLE_DISABLE_RE.search(body):
            continue
        hits.append(path)
    return hits


def _contains_zero_count_guard(text: str, lhs: str) -> bool:
    lhs_re = re.escape(lhs)
    tail = lhs.rsplit("->", 1)[-1].rsplit(".", 1)[-1]
    tail_re = re.escape(tail)
    return bool(re.search(
        rf"(?:{lhs_re}|{tail_re})\s*(?:<=|==)\s*0|"
        rf"!\s*(?:{lhs_re}|{tail_re})\b|"
        rf"(?:{lhs_re}|{tail_re})\s*<\s*1",
        text,
        re.IGNORECASE,
    ))


def _required_clock_context(patch_corpus: str) -> bool:
    required = _binding_required_resource_names(patch_corpus)
    return (
        any(name.lower() in {"clocks", "clock-names"} for name in required)
        or bool(_REQUIRED_CLK_MATCH_DATA_RE.search(patch_corpus))
    )


def _binding_compatible_tuples_from_body(path: str, body: str) -> list[tuple[str, tuple[str, ...]]]:
    tuples: list[tuple[str, tuple[str, ...]]] = []
    lines = _visible_diff_lines(body)
    in_compatible = False
    compatible_indent = -1
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            tuples.append((path, tuple(current)))
            current = []

    for _marker, line in lines:
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "compatible:":
            flush()
            in_compatible = True
            compatible_indent = indent
            continue
        if in_compatible and indent <= compatible_indent:
            flush()
            in_compatible = False
        if not in_compatible:
            continue
        if re.match(r"^-?\s*items:\s*$", stripped):
            flush()
            continue
        match = re.match(r"^-?\s*const:\s*['\"]?(?P<compat>[^'\"#\s]+)", stripped)
        if match:
            current.append(match.group("compat"))
    flush()
    return tuples


def _binding_compatible_tuple_conflicts(
    patch_corpus: str,
) -> list[tuple[str, list[tuple[str, tuple[str, ...]]]]]:
    by_first: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for path, body in _iter_binding_diff_bodies(patch_corpus):
        for tuple_path, compat_tuple in _binding_compatible_tuples_from_body(path, body):
            if not compat_tuple:
                continue
            by_first.setdefault(compat_tuple[0], []).append((tuple_path, compat_tuple))

    conflicts: list[tuple[str, list[tuple[str, tuple[str, ...]]]]] = []
    for first, entries in sorted(by_first.items()):
        unique = {compat_tuple for _path, compat_tuple in entries}
        if len(unique) <= 1:
            continue
        lengths = {len(compat_tuple) for compat_tuple in unique}
        suffixes = {compat_tuple[1:] for compat_tuple in unique}
        if len(lengths) > 1 or len(suffixes) > 1:
            conflicts.append((first, entries))
    return conflicts


def _provider_cell_properties_without_const(patch_corpus: str) -> list[tuple[str, str]]:
    missing: list[tuple[str, str]] = []
    for path, body in _iter_binding_diff_bodies(patch_corpus):
        lines = body.splitlines()
        for index, raw_line in enumerate(lines):
            if not raw_line.startswith("+"):
                continue
            match = _PROVIDER_CELL_NAME_RE.match(raw_line)
            if not match:
                continue
            name = match.group("name")
            property_indent = len(match.group("indent"))
            window: list[str] = []
            for next_raw in lines[index + 1:index + 18]:
                if not next_raw or next_raw[0] not in "+ ":
                    continue
                line = next_raw[1:]
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip(" "))
                if indent <= property_indent and re.match(r"['\"]?[A-Za-z0-9_#,+.-]+['\"]?\s*:", stripped):
                    break
                window.append(stripped)
            if not any(re.match(r"const\s*:", item) for item in window):
                missing.append((path, name))
    return missing


def _retained_target_base_and_field(target: str) -> tuple[str, str]:
    base = re.split(r"(?:->|\.|\[)", target, maxsplit=1)[0]
    field = re.split(r"(?:->|\.)", target)[-1]
    return base, field


def _retained_target_cleared(body: str, base: str, field: str) -> bool:
    return bool(re.search(
        rf"^\+[^+].*\b{re.escape(base)}\b[^;\n]*(?:->|\.)"
        rf"{re.escape(field)}\s*=\s*(?:NULL|0)\b",
        body,
        re.MULTILINE,
    ))


def _retained_dynamic_cleanup_candidates(patch_corpus: str) -> list[str]:
    candidates: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        if not _RETAINED_DYNAMIC_CLEANUP_RE.search(body):
            continue
        for match in _RETAINED_DYNAMIC_ASSIGN_RE.finditer(body):
            target = match.group("target")
            alloc = match.group("alloc")
            if not _RETAINED_DYNAMIC_ALLOC_RE.search(alloc):
                continue
            base, field = _retained_target_base_and_field(target)
            cleanup_refs_base = bool(re.search(
                rf"\b[A-Za-z_][A-Za-z0-9_]*(?:remove|destroy|unregister|free|put|cleanup)"
                rf"[A-Za-z0-9_]*\s*\([^;]*\b{re.escape(base)}\b",
                body,
                re.IGNORECASE,
            ))
            if not cleanup_refs_base:
                continue
            if _retained_target_cleared(body, base, field):
                continue
            candidates.append(f"{path}:{target}<-{alloc}")
    return candidates


def _visible_diff_text(body: str) -> str:
    return "\n".join(line for _marker, line in _visible_diff_lines(body))


def _level_irq_reenable_candidates(patch_corpus: str) -> list[str]:
    candidates: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        if not re.search(r"^\+[^+].*enable_irq\s*\(", body, re.MULTILINE):
            continue
        visible = _visible_diff_text(body)
        if "enable_irq" not in visible or "IRQ_" not in visible:
            continue
        for match in re.finditer(r"enable_irq\s*\([^;]+;", visible):
            prefix = visible[max(0, match.start() - 700):match.start()]
            suffix = visible[match.end():match.end() + 240]
            if not re.search(
                r"if\s*\([\s\S]{0,260}(?:pm_runtime|suspend|ready|active|powered|state)",
                prefix,
                re.IGNORECASE,
            ):
                continue
            if not re.search(r"return\s+IRQ_[A-Z_]+\s*;", suffix):
                continue
            tail = prefix.rsplit("{", 1)[-1]
            if _IRQ_SOURCE_QUIESCE_RE.search(tail):
                continue
            candidates.append(path)
            break
    return sorted(set(candidates))


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
_CODE_LOGIC_CONTROL_FLOW_LINE_RE = re.compile(
    r"control-flow:\s*\S",
    re.IGNORECASE,
)
_CODE_LOGIC_DATA_FLOW_LINE_RE = re.compile(
    r"data-flow:\s*\S",
    re.IGNORECASE,
)
_CODE_LOGIC_STATE_LIFECYCLE_LINE_RE = re.compile(
    r"state/lifecycle:\s*\S",
    re.IGNORECASE,
)
_CODE_LOGIC_BEFORE_AFTER_LINE_RE = re.compile(
    r"before-vs-after\s+delta:\s*\S",
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


def _on_demand_read_files(block: CommitBlock) -> set[str]:
    match = _ON_DEMAND_READS_RE.search(block.step_record or "")
    if not match:
        return set()
    files_blob = match.group(2).strip()
    if not files_blob.startswith("["):
        return set()
    return {
        item.strip().strip("`'")
        for item in files_blob.strip("[]").split(",")
        if item.strip() and item.strip() != "..."
    }


def _read_record_blobs(block: CommitBlock) -> list[str]:
    blobs: list[str] = []
    audit_match = _CODEBASE_AUDIT_DONE_RE.search(block.step_record or "")
    if audit_match:
        blobs.append(audit_match.group(4))
    reads_match = _ON_DEMAND_READS_RE.search(block.step_record or "")
    if reads_match and reads_match.group(2).strip().startswith("["):
        blobs.append(reads_match.group(2).strip().strip("[]"))
    return blobs


def _required_read_recorded(block: CommitBlock, required: str) -> bool:
    if required in (_codebase_audit_files(block) | _on_demand_read_files(block)):
        return True
    # Some kernel paths contain commas (for example qcom,<soc>-*.yaml), so
    # comma-tokenizing files=[...] is not sufficient.  Match the full required
    # path inside the recorded blob with delimiter/end boundaries.
    pattern = re.compile(r"(?<![A-Za-z0-9_./+-])" + re.escape(required) + r"(?=\s*(?:,|$))")
    return any(pattern.search(blob) for blob in _read_record_blobs(block))


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
    function_sources = manifest.get("function_level_source_files")
    if isinstance(function_sources, list):
        if function_sources:
            return True
    else:
        # Backward compatibility for older manifests generated before
        # function-level sources were separated from DT binding headers.
        changed_sources = manifest.get("changed_source_files")
        if isinstance(changed_sources, list) and changed_sources:
            return True

    for key in ("changed_functions", "helper_candidates"):
        value = manifest.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def _manifest_values(
    evidence_by_block: Optional[dict[int, dict[str, object]]], key: str
) -> list[object]:
    if not evidence_by_block:
        return []
    values: list[object] = []
    for manifest in evidence_by_block.values():
        if not isinstance(manifest, dict):
            continue
        value = manifest.get(key)
        if value is not None:
            values.append(value)
    return values


def _structured_runtime_pm_added_get_sync(
    evidence_by_block: Optional[dict[int, dict[str, object]]],
) -> Optional[bool]:
    saw_structured = False
    for value in _manifest_values(evidence_by_block, "runtime_pm_facts"):
        if not isinstance(value, dict):
            continue
        saw_structured = True
        calls = value.get("added_get_sync_calls")
        if isinstance(calls, list) and calls:
            return True
    return False if saw_structured else None


def _structured_runtime_pm_bare_hits(
    evidence_by_block: Optional[dict[int, dict[str, object]]],
) -> Optional[list[str]]:
    saw_structured = False
    hits: list[str] = []
    seen: set[str] = set()
    for value in _manifest_values(evidence_by_block, "runtime_pm_facts"):
        if not isinstance(value, dict):
            continue
        saw_structured = True
        paths = value.get("bare_get_sync_files")
        if not isinstance(paths, list):
            continue
        for item in paths:
            if isinstance(item, str) and item and item not in seen:
                seen.add(item)
                hits.append(item)
    return hits if saw_structured else None


def _structured_dma_example_gap(
    evidence_by_block: Optional[dict[int, dict[str, object]]],
) -> Optional[bool]:
    saw_structured = False
    for value in _manifest_values(evidence_by_block, "dt_facts"):
        if not isinstance(value, list):
            continue
        saw_structured = True
        for item in value:
            if not isinstance(item, dict):
                continue
            if (
                item.get("defines_dmas")
                and item.get("defines_dma_names")
                and item.get("example_has_dmas")
                and not item.get("example_has_dma_names")
            ):
                return True
    return False if saw_structured else None


def _structured_match_data_unguarded_exprs(
    evidence_by_block: Optional[dict[int, dict[str, object]]],
) -> Optional[set[str]]:
    saw_structured = False
    exprs: set[str] = set()
    for value in _manifest_values(evidence_by_block, "match_data_facts"):
        if not isinstance(value, dict):
            continue
        saw_structured = True
        derefs = value.get("unguarded_dereferences")
        if not isinstance(derefs, list):
            continue
        for item in derefs:
            if not isinstance(item, dict):
                continue
            expr = item.get("expr")
            if isinstance(expr, str) and expr:
                exprs.add(expr)
    return exprs if saw_structured else None


def _structured_escaped_local_address_facts(
    evidence_by_block: Optional[dict[int, dict[str, object]]],
) -> Optional[list[dict[str, str]]]:
    saw_structured = False
    facts: list[dict[str, str]] = []
    for value in _manifest_values(evidence_by_block, "lifetime_facts"):
        if not isinstance(value, dict):
            continue
        saw_structured = True
        stores = value.get("escaped_local_address_stores")
        if not isinstance(stores, list):
            continue
        for item in stores:
            if not isinstance(item, dict):
                continue
            facts.append({
                "path": str(item.get("path", "")),
                "local": str(item.get("local", "")),
                "target": str(item.get("target", "")),
                "store_kind": str(item.get("store_kind", "")),
            })
    return facts if saw_structured else None


def _structured_unchecked_setup_before_publish(
    evidence_by_block: Optional[dict[int, dict[str, object]]],
) -> Optional[list[dict[str, str]]]:
    saw_structured = False
    facts: list[dict[str, str]] = []
    for value in _manifest_values(evidence_by_block, "setup_flow_facts"):
        if not isinstance(value, dict):
            continue
        saw_structured = True
        items = value.get("unchecked_setup_before_publish")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            facts.append({
                "path": str(item.get("path", "")),
                "status_var": str(item.get("status_var", "")),
                "helper": str(item.get("helper", "")),
                "publish_call": str(item.get("publish_call", "")),
            })
    return facts if saw_structured else None


def _structured_newly_exposed_silent_failure_facts(
    evidence_by_block: Optional[dict[int, dict[str, object]]],
) -> Optional[list[dict[str, str]]]:
    saw_structured = False
    facts: list[dict[str, str]] = []
    for value in _manifest_values(evidence_by_block, "setter_contract_facts"):
        if not isinstance(value, dict):
            continue
        saw_structured = True
        items = value.get("newly_exposed_silent_failures")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            replay_paths = item.get("replay_paths")
            replay_path = ""
            if isinstance(replay_paths, list) and replay_paths:
                first = replay_paths[0]
                if isinstance(first, dict):
                    replay_path = str(first.get("path", ""))
            facts.append({
                "path": str(item.get("path", "")),
                "cap_id": str(item.get("cap_id", "")),
                "setter": str(item.get("setter", "")),
                "min_value": str(item.get("min_value", "")),
                "default_value": str(item.get("default_value", "")),
                "reject_guard": str(item.get("reject_guard", "")),
                "setter_definition_path": str(item.get("setter_definition_path", "")),
                "replay_path": replay_path,
            })
    return facts if saw_structured else None


def _structured_duplicate_teardown_facts(
    evidence_by_block: Optional[dict[int, dict[str, object]]],
) -> Optional[list[dict[str, str]]]:
    saw_structured = False
    facts: list[dict[str, str]] = []
    for value in _manifest_values(evidence_by_block, "resource_facts"):
        if not isinstance(value, dict):
            continue
        saw_structured = True
        items = value.get("duplicate_teardown_calls")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            call = item.get("call")
            path = item.get("path")
            if not isinstance(call, str) or not call:
                continue
            facts.append({
                "path": str(path or ""),
                "call": call,
            })
    return facts if saw_structured else None


def _structured_peer_dimension_admission_facts(
    evidence_by_block: Optional[dict[int, dict[str, object]]],
) -> Optional[list[dict[str, str]]]:
    saw_structured = False
    facts: list[dict[str, str]] = []
    for value in _manifest_values(evidence_by_block, "admission_control_facts"):
        if not isinstance(value, dict):
            continue
        saw_structured = True
        items = value.get("missing_peer_dimension_checks")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            facts.append({
                "path": str(item.get("path", "")),
                "checked_dimension": str(item.get("checked_dimension", "")),
                "missing_dimension": str(item.get("missing_dimension", "")),
            })
    return facts if saw_structured else None


def _structured_failed_start_stale_state_facts(
    evidence_by_block: Optional[dict[int, dict[str, object]]],
) -> Optional[list[dict[str, str]]]:
    saw_structured = False
    facts: list[dict[str, str]] = []
    for value in _manifest_values(evidence_by_block, "stale_state_facts"):
        if not isinstance(value, dict):
            continue
        saw_structured = True
        items = value.get("failed_start_stale_state")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            facts.append({
                "path": str(item.get("path", "")),
                "state_target": str(item.get("state_target", "")),
                "operation": str(item.get("operation", "")),
                "status_var": str(item.get("status_var", "")),
            })
    return facts if saw_structured else None


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
        missing = [
            required
            for required in _required_evidence_reads(manifest)
            if not _required_read_recorded(block, required)
        ]
        if missing:
            violations.append(Violation(
                "evidence_required_reads",
                f"block#{block.index} '{block.subject[:60]}'",
                "STEP_COMPLETION_RECORD does not prove required evidence reads "
                "from the manifest via codebase_audit files=[...] or "
                "on_demand_reads: " + ", ".join(missing[:8]),
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
    """Check #18 — every block must prove Code Logic Map coverage.

    Packet-mode blocks use refs/output-format-mini.md as the subagent-visible
    contract.  That contract requires the visible Code Logic Maps <pre> to
    carry three surrounding-code audit lines, a lifecycle/workflow line, and
    three analytical lines for
    every patch, including DTS/YAML-only patches.  Pure data/schema changes may
    still use `codebase_audit: N/A no function-level code changes` in the
    STEP_COMPLETION_RECORD, but that record-level summary is not a substitute
    for visible entrypoint/callee/sibling audit proof.
    """
    violations: list[Violation] = []
    for block in report.blocks:
        if not block.step_record:
            continue

        visible = block.raw_html
        missing_lines: list[str] = []
        if not _CODEBASE_AUDIT_ENTRY_LINE_RE.search(visible):
            missing_lines.append("entrypoints")
        if not _CODEBASE_AUDIT_CALLEE_LINE_RE.search(visible):
            missing_lines.append("callees")
        if not _CODEBASE_AUDIT_SIBLING_LINE_RE.search(visible):
            missing_lines.append("siblings")
        if not _CODE_LOGIC_CONTROL_FLOW_LINE_RE.search(visible):
            missing_lines.append("control-flow")
        if not _CODE_LOGIC_DATA_FLOW_LINE_RE.search(visible):
            missing_lines.append("data-flow")
        if not _CODE_LOGIC_STATE_LIFECYCLE_LINE_RE.search(visible):
            missing_lines.append("state/lifecycle")
        if not _CODE_LOGIC_BEFORE_AFTER_LINE_RE.search(visible):
            missing_lines.append("before-vs-after delta")
        if missing_lines:
            violations.append(Violation(
                "codebase_audit_required",
                f"block#{block.index} '{block.subject[:60]}'",
                "Code Logic Maps missing mandatory audit/analysis line(s): "
                + ", ".join(missing_lines),
            ))

        if _block_has_function_level_changes(block) and not _CODEBASE_AUDIT_DONE_RE.search(block.step_record):
            violations.append(Violation(
                "codebase_audit_required",
                f"block#{block.index} '{block.subject[:60]}'",
                "block appears to review function-level code changes but "
                "`codebase_audit:` is not marked DONE; diff-only review is not "
                "allowed for code patches",
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


# A bare `pm_runtime_get_sync(` added by the diff (new `+` line, not context).
_PM_RUNTIME_GET_SYNC_DIFF_ADDED_RE = re.compile(
    r"^\+[^+].*pm_runtime_get_sync\s*\(", re.MULTILINE
)


def check_pm_runtime_get_sync_source_aware(
    report: Report,
    patch_corpus: str,
    evidence_by_block: Optional[dict[int, dict[str, object]]] = None,
) -> list[Violation]:
    """Source-aware backstop for #14.  When the patch corpus introduces
    `pm_runtime_get_sync(` (added line in diff), at least one block must
    show the unchecked-return pitfall was considered.  Robust against the
    model eliding the call from the visible report text."""
    if not patch_corpus:
        return []
    structured_added = _structured_runtime_pm_added_get_sync(evidence_by_block)
    if structured_added is None:
        if not _PM_RUNTIME_GET_SYNC_DIFF_ADDED_RE.search(patch_corpus):
            return []
    elif not structured_added:
        return []
    visible_all = _visible_report_text(report)
    if _PM_RUNTIME_GET_SYNC_PROOF_RE.search(visible_all):
        return []
    return [Violation(
        "pm_runtime_get_sync_source_aware",
        "report (corpus-derived)",
        "patch series introduces `pm_runtime_get_sync(` (added in diff) but "
        "no block shows the unchecked-return pitfall was considered "
        "(missing return check, `pm_runtime_resume_and_get` migration, or "
        "`put_noidle` on the error path); see refs/hardware-eng-pm-register-access.md "
        "`pm_runtime bracket`",
    )]


def check_clk_handle_ownership_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require non-devm reference handles to be released or discussed."""
    if not patch_corpus:
        return []
    hits: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        if not _OWNED_REF_GET_ADDED_RE.search(body):
            continue
        if _OWNED_REF_PUT_RE.search(body):
            continue
        hits.append(path)
    if not hits:
        return []
    if _review_has_finding_or_discussion(report, _OWNED_REF_REPORT_RE):
        return []
    return [Violation(
        "clk_handle_ownership_source_aware",
        "report (corpus-derived)",
        "patch adds a non-devm reference getter (e.g. of_clk_get / "
        "of_reset_control_get / regulator_get) without a visible matching "
        f"*_put() release path ({', '.join(sorted(set(hits))[:4])}); the "
        "review must treat the returned handle as an owned reference, require "
        "the matching release on every error/unbind path, or prove the "
        "lifetime is deliberately transferred",
    )]


def check_clk_enable_idempotency_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require repeatable enable paths to discuss enable-count safety."""
    if not patch_corpus:
        return []
    hits: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        if not _REPEATABLE_ENABLE_ADDED_RE.search(body):
            continue
        if not _REPEATABLE_CALLBACK_HINT_RE.search(body):
            continue
        if _ENABLE_IDEMPOTENCY_GUARD_RE.search(body):
            continue
        hits.append(path)
    if not hits:
        return []
    if _review_has_finding_or_discussion(report, _ENABLE_IDEMPOTENCY_REPORT_RE):
        return []
    return [Violation(
        "clk_enable_idempotency_source_aware",
        "report (corpus-derived)",
        "patch adds a *_prepare_enable() / *_enable() in a re-enterable "
        "callback (open/close, hw_params, set-rate, runtime-PM, recovery, "
        f"stream restart) without a visible idempotency guard or refcount ({', '.join(sorted(set(hits))[:4])}); "
        "the review must check repeated calls, concurrent sessions, and "
        "whether shutdown/error paths disable exactly the acquired count",
    )]


def check_asoc_dai_target_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require role-typed endpoint helpers to validate the chosen role.

    Concrete instance currently detected: ASoC snd_soc_dai_set_*() picking
    cpu_dai while nearby flags or names imply a CODEC-side configuration.
    The underlying rule is generic (role-typed helpers), but the regex stays
    narrow to what we can flag without false positives.
    """
    if not patch_corpus:
        return []
    hits: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        if "sound/soc/" not in path and not re.search(r"snd_soc|ASoC", body, re.IGNORECASE):
            continue
        if not _ROLE_TYPED_HELPER_ADDED_RE.search(body):
            continue
        if not _ROLE_TYPED_HELPER_HINT_RE.search(body):
            continue
        hits.append(path)
    if not hits:
        return []
    if _review_has_finding_or_discussion(report, _ROLE_TYPED_REPORT_RE):
        return []
    return [Violation(
        "asoc_dai_target_source_aware",
        "report (corpus-derived)",
        "patch addresses one role of a role-typed helper while nearby code "
        "or naming implies the opposite role (e.g. snd_soc_dai_set_sysclk() "
        f"on cpu_dai with CODEC-sysclk hints) ({', '.join(sorted(set(hits))[:4])}); "
        "the review must validate which endpoint the surrounding intent "
        "actually selects, including secondary arguments (clk_id, direction) "
        "and return handling",
    )]


def check_non_alloc_enomem_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Catch -ENOMEM returns for non-allocation lookup/descriptor failures."""
    if not patch_corpus:
        return []
    hits: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        for match in re.finditer(
            r"(?:of_)?device_get_match_data\s*\([^;]+;[\s\S]{0,240}?return\s+-ENOMEM\s*;",
            body,
            re.IGNORECASE,
        ):
            window = match.group(0)
            if re.search(r"alloc|kzalloc|kmalloc|devm_k|ENOMEM\s+from", window, re.IGNORECASE):
                continue
            hits.append(path)
            break
    if not hits:
        return []
    if _review_has_finding_or_discussion(report, _NON_ALLOC_ENOMEM_REPORT_RE):
        return []
    return [Violation(
        "non_alloc_enomem_source_aware",
        "report (corpus-derived)",
        "patch returns -ENOMEM after a non-allocation failure (lookup/"
        f"descriptor/match-data absent) without a visible allocation site ({', '.join(sorted(set(hits))[:4])}); "
        "the review must match the errno to the failing operation — prefer "
        "-ENODEV/-EINVAL/-ENODATA/-ENOENT, or preserve the helper's own "
        "return value, instead of relabelling it as -ENOMEM",
    )]


def check_pm_runtime_post_get_return_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Catch newly added returns after a PM runtime get and before cleanup."""
    if not patch_corpus:
        return []
    hits: list[str] = []
    cleanup_re = re.compile(r"pm_runtime_put|pm_runtime_disable|goto\s+\w*(?:put|pm|err|disable)", re.IGNORECASE)
    for path, body in _iter_source_diff_bodies(patch_corpus):
        lines = _visible_diff_lines(body)
        for index, (_marker, line) in enumerate(lines):
            if "pm_runtime_get_sync" not in line:
                continue
            for offset, (next_marker, next_line) in enumerate(lines[index + 1:index + 35], start=1):
                if cleanup_re.search(next_line):
                    break
                if next_marker != "+" or not re.search(r"\breturn\b", next_line):
                    continue
                previous_line = lines[index + offset - 1][1] if index + offset - 1 >= 0 else ""
                if re.search(r"if\s*\([^\n]*(?:ret|rc|err)\s*(?:<\s*0|!=\s*0|\))", previous_line):
                    continue
                hits.append(path)
                break
    if not hits:
        return []
    if _review_has_finding_or_discussion(report, _PM_POST_GET_RETURN_REPORT_RE):
        return []
    return [Violation(
        "pm_runtime_post_get_return_source_aware",
        "report (corpus-derived)",
        "patch adds a direct return after pm_runtime_get_sync() and before a "
        f"visible pm_runtime_put()/cleanup label ({', '.join(sorted(set(hits))[:4])}); "
        "the review must prove the return exits before the PM get succeeds, "
        "routes through cleanup, or file the runtime-PM usage-count leak",
    )]


def _added_firmware_paths(body: str) -> list[str]:
    paths: list[str] = []
    for raw_line in body.splitlines():
        if not raw_line.startswith("+") or raw_line.startswith("+++"):
            continue
        line = raw_line[1:]
        if "MODULE_FIRMWARE" in line:
            continue
        if not re.search(r"fw|firmware|hw\d", line, re.IGNORECASE):
            continue
        for quoted in re.findall(r"[\"']([^\"']*(?:/[^\"']+|fw|firmware|hw\d)[^\"']*)[\"']", line, re.IGNORECASE):
            if quoted and quoted not in paths:
                paths.append(quoted)
    return paths


def check_firmware_metadata_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require MODULE_FIRMWARE metadata for newly requested firmware paths."""
    if not patch_corpus:
        return []
    hits: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        if not re.search(r"drivers/(?:net/wireless|media|remoteproc|soc|firmware)/", path):
            continue
        added_paths = _added_firmware_paths(body)
        if not added_paths:
            continue
        if "MODULE_FIRMWARE" in body:
            continue
        hits.extend(f"{path}:{firmware_path}" for firmware_path in added_paths[:3])
    if not hits:
        return []
    if _review_has_finding_or_discussion(report, _FIRMWARE_METADATA_REPORT_RE):
        return []
    return [Violation(
        "firmware_metadata_source_aware",
        "report (corpus-derived)",
        "patch adds a firmware directory/name without visible MODULE_FIRMWARE() "
        f"metadata ({', '.join(hits[:4])}); the review must require matching "
        "firmware metadata or explicitly prove the new hardware reuses an "
        "existing advertised path",
    )]


def check_binding_compatible_conditional_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require new compatible strings to be reconciled with allOf conditionals."""
    if not patch_corpus:
        return []
    hits: list[str] = []
    resource_re = re.compile(
        r"clock|reset|power-domain|interrupt|assigned-clocks|supply|dma|names",
        re.IGNORECASE,
    )
    for path, body in _iter_binding_diff_bodies(patch_corpus):
        if not re.search(r"allOf\s*:|\bif\s*:|\bthen\s*:", body):
            continue
        if not resource_re.search(body):
            continue
        compatibles: set[str] = set()
        for _binding_path, const_compatibles in _binding_added_const_compatibles(
            f"diff --git a/{path} b/{path}\n{body}"
        ):
            compatibles.update(const_compatibles)
        compatibles.update(
            match.group("compat")
            for match in re.finditer(
                r"^\+\s*-\s+(?P<compat>[a-z0-9][a-z0-9.+-]*,[A-Za-z0-9][A-Za-z0-9,._+-]*)\s*$",
                body,
                re.MULTILINE,
            )
        )
        for compat in sorted(compatibles):
            compat_hits = [match.start() for match in re.finditer(re.escape(compat), body)]
            if len(compat_hits) > 1:
                continue
            hits.append(f"{path}:{compat}")
    if not hits:
        return []
    if _review_has_finding_or_discussion(report, _BINDING_CONDITIONAL_COMPAT_REPORT_RE):
        return []
    return [Violation(
        "binding_compatible_conditional_source_aware",
        "report (corpus-derived)",
        "binding diff adds compatible string(s) while the same schema has "
        "resource-bearing allOf/if/then conditionals, but the compatible is "
        f"not visibly propagated into those conditionals ({', '.join(hits[:4])}); "
        "the review must check whether generic constraints are sufficient or "
        "require the matching conditional update",
    )]


def check_pm_runtime_positive_return_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Catch errno-style wrappers that forward a >=0-success helper return.

    Concrete instance currently detected: pm_runtime_put_sync().  The general
    rule (see hardware-eng.md Hardware Resource Lifecycle Symmetry) covers any
    helper that documents a positive-success return.
    """
    if not patch_corpus:
        return []
    hits: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        if not re.search(r"^\+[^+].*pm_runtime_put_sync\s*\(", body, re.MULTILINE):
            continue
        if _POSITIVE_RETURN_NORMALIZED_RE.search(body):
            continue
        if _POSITIVE_RETURN_FORWARD_RE.search(body):
            hits.append(path)
    if not hits:
        return []
    if _review_has_finding_or_discussion(report, _POSITIVE_RETURN_REPORT_RE):
        return []
    return [Violation(
        "pm_runtime_positive_return_source_aware",
        "report (corpus-derived)",
        "patch forwards a helper that may return positive on success "
        "(currently detected: pm_runtime_put_sync()) from an errno-style "
        f"wrapper without visible normalization to 0 ({', '.join(sorted(set(hits))[:4])}); "
        "the review must check whether callers expect 0/negative errno and "
        "clamp positive success values when appropriate",
    )]


def check_printf_format_type_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Catch obvious signedness mismatches in newly added printf-like calls."""
    if not patch_corpus:
        return []
    hits: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        unsigned_names = set(re.findall(r"\b(?:unsigned\s+(?:int|short|long)|u(?:8|16|32|64))\s+(\w+)\b", body))
        if not unsigned_names:
            continue
        for raw_line in body.splitlines():
            if not raw_line.startswith("+") or raw_line.startswith("+++"):
                continue
            line = raw_line[1:]
            if not re.search(r"\b(?:dev_set_name|snprintf|scnprintf|sprintf|dev_(?:err|warn|info|dbg)|pr_(?:err|warn|info|debug)|trace_printk)\s*\(", line):
                continue
            if "%d" not in line:
                continue
            for name in unsigned_names:
                if re.search(rf"\(\s*int\s*\)\s*(?:\w+->|\w+\.)?{re.escape(name)}\b", line):
                    continue
                if re.search(rf"(?:\b{name}\b|->\s*{re.escape(name)}\b|\.\s*{re.escape(name)}\b)", line):
                    hits.append(f"{path}:{name}")
                    break
    if not hits:
        return []
    if _review_has_finding_or_discussion(report, _PRINTF_FORMAT_REPORT_RE):
        return []
    return [Violation(
        "printf_format_type_source_aware",
        "report (corpus-derived)",
        "patch adds a printf-like call using %d for a visible unsigned value "
        f"({', '.join(hits[:4])}); the review must compare format specifiers "
        "against argument signedness/width or cite an intentional cast",
    )]


def _helpers_losing_teardown_step(patch_corpus: str) -> list[tuple[str, str]]:
    """Return (helper_name, sample_removed_line) for each function whose body
    loses a teardown/bookkeeping statement in the diff.

    Walks each source diff body line by line, tracking the enclosing function
    from the most recent ``@@ ... func(`` hunk header, and records a hit when a
    removed (`-`) line matches a teardown shape.
    """
    hits: list[tuple[str, str]] = []
    for _path, body in _iter_source_diff_bodies(patch_corpus):
        current_func = ""
        for raw_line in body.splitlines():
            header = _HUNK_FUNC_RE.match(raw_line)
            if header:
                current_func = header.group("func")
                continue
            if not current_func:
                continue
            if _TEARDOWN_REMOVED_RE.match(raw_line):
                # Ignore a removed line that is paired with the SAME statement
                # re-added inside the same helper (pure move within the helper).
                hits.append((current_func, raw_line[1:].strip()))
    return hits


def _count_call_sites(patch_corpus: str, func: str) -> int:
    """Count call sites of ``func(`` across all source diff bodies — counting
    visible/context and added lines (callers the patch touches or shows), not
    the helper's own definition hunk header."""
    call_re = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(func)}\s*\(")
    count = 0
    for _path, body in _iter_source_diff_bodies(patch_corpus):
        for raw_line in body.splitlines():
            if raw_line.startswith("@@"):
                continue
            if not raw_line or raw_line[0] not in "+ -":
                continue
            text = raw_line[1:]
            # Skip the function definition line itself (return type + func + ( + args + brace/no semicolon)
            if re.match(rf"\s*(?:static\s+|inline\s+|const\s+|struct\s+\w+\s+\**)*[\w\*]+\s+{re.escape(func)}\s*\(", text):
                continue
            if call_re.search(text):
                count += 1
    return count


def check_relocated_teardown_step_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Flag a teardown/bookkeeping step removed from a multi-caller helper.

    When a refactor strips a list_del / free / put / NULL / decrement from a
    helper body and the helper still has multiple call sites, a caller that
    relied on the removed step may now leak / double-free / leave a freed
    object linked.  The review must audit every caller or file the finding.
    """
    if not patch_corpus:
        return []
    helpers = _helpers_losing_teardown_step(patch_corpus)
    if not helpers:
        return []
    flagged: list[str] = []
    flagged_funcs: list[str] = []
    for func, removed in helpers:
        # Only fire when the helper is reachable from more than one call site —
        # a single-caller helper cannot strand a second caller.
        if _count_call_sites(patch_corpus, func) >= 2:
            flagged.append(f"{func}() drops `{removed[:48]}`")
            flagged_funcs.append(func)
    if not flagged:
        return []
    # Clearance requires the review to engage with the RELOCATION specifically:
    # a proof token (missing-step / other-caller vocabulary) co-located with
    # either the helper's own name or an explicit error/unwind path that reaches
    # it.  A bare "use-after-free" or "no other callers used a guard" sentence
    # elsewhere in the report (describing the race the patch *fixes*, or an
    # unrelated finding) must NOT clear this — that proof-token collision is the
    # exact false-clear that let the fastrpc v8 2/4 err_assign UAF through.
    report_text = _visible_report_text(report)
    helper_name_re = re.compile(
        "|".join(re.escape(f) for f in dict.fromkeys(flagged_funcs)),
    )
    cleared = _proof_is_colocated(
        report_text, _RELOCATED_TEARDOWN_REPORT_RE, helper_name_re, window=240
    ) or _proof_is_colocated(
        report_text, _RELOCATED_TEARDOWN_REPORT_RE, _RELOCATED_TEARDOWN_PATH_RE, window=200
    )
    if cleared:
        return []
    return [Violation(
        "relocated_teardown_step_source_aware",
        "report (corpus-derived)",
        "patch removes a teardown/bookkeeping step from a helper that has "
        f"multiple call sites ({', '.join(flagged[:4])}); the review must audit "
        "every caller of that helper — prove each re-performs the step or never "
        "needed it, or file the leak/double-free/use-after-free for the caller "
        "that now skips it",
    )]


def _locked_and_unlocked_field_assigns(body: str) -> list[str]:
    """Return field lvalues that are assigned BOTH under a held lock and on an
    added line with no lock held, within a single source diff body.

    Walks the added/context lines tracking lock depth: a lock-acquire token
    increments depth, a release decrements it.  A field assignment on a `+`
    line is classified as locked (depth>0) or unlocked (depth==0).  A field
    that appears in both buckets is the set-under-lock / reset-without-lock
    asymmetry shape.
    """
    locked: set[str] = set()
    unlocked: set[str] = set()
    depth = 0
    for raw_line in body.splitlines():
        if not raw_line or raw_line[0] not in "+ ":
            # A `-` or hunk line: only reset depth on a hunk boundary so we do
            # not carry a lock across functions.
            if raw_line.startswith("@@"):
                depth = 0
            continue
        text = raw_line[1:]
        # Update lock depth from BOTH context and added lines so an added
        # assignment inside a pre-existing locked region is seen as locked.
        acquires = len(_LOCK_ACQUIRE_RE.findall(text))
        releases = len(_LOCK_RELEASE_RE.findall(text))
        assign = _FIELD_ASSIGN_RE.match(raw_line)
        if assign:
            lvalue = assign.group("lvalue")
            # Classify by lock depth BEFORE applying this line's release (a
            # `spin_unlock` after the assignment on the same line still means
            # the assignment was inside the lock — but that is rare; use the
            # pre-line depth plus this line's acquires).
            effective = depth + acquires
            if effective > 0:
                locked.add(lvalue)
            else:
                unlocked.add(lvalue)
        depth = max(0, depth + acquires - releases)
    return sorted(locked & unlocked)


def check_lock_coverage_symmetry_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Flag a field mutated under a lock on one path and without it on another.

    Set-under-lock / reset-without-lock asymmetry is a data race on the shared
    field.  The review must take the lock on the unlocked path, prove the
    unlocked access is single-threaded/owner-private, or file the finding.
    """
    if not patch_corpus:
        return []
    flagged: list[str] = []
    for _path, body in _iter_source_diff_bodies(patch_corpus):
        for lvalue in _locked_and_unlocked_field_assigns(body):
            flagged.append(lvalue)
    if not flagged:
        return []
    # Clearance requires the review to engage with the lock-coverage gap on the
    # SAME field: a lock-asymmetry proof token co-located with one of the
    # flagged field names.  A generic "data race" sentence elsewhere does not
    # clear it (proof-token-collision discipline, as for the teardown check).
    report_text = _visible_report_text(report)
    tails = {lv.rsplit("->", 1)[-1].rsplit(".", 1)[-1] for lv in flagged}
    field_name_re = re.compile(
        "|".join(re.escape(t) for t in dict.fromkeys(tails) if t),
    )
    if _proof_is_colocated(
        report_text, _LOCK_SYMMETRY_REPORT_RE, field_name_re, window=240
    ):
        return []
    return [Violation(
        "lock_coverage_symmetry_source_aware",
        "report (corpus-derived)",
        "patch assigns a field under a lock on one path and without that lock "
        f"on another ({', '.join(sorted(set(flagged))[:4])}); the review must "
        "take the same lock on the unlocked path, prove that access is "
        "single-threaded/owner-private, or file the data-race finding",
    )]


def check_dma_names_source_aware(
    report: Report,
    patch_corpus: str,
    evidence_by_block: Optional[dict[int, dict[str, object]]] = None,
) -> list[Violation]:
    """Source-aware backstop for #15.  When the patch corpus contains a
    YAML binding diff that defines BOTH `dmas:` and `dma-names:` AND its
    example uses `dmas = <...>` without `dma-names = ...`, at least one
    report block must flag the missing example property."""
    if not patch_corpus:
        return []
    structured_gap = _structured_dma_example_gap(evidence_by_block)
    if structured_gap is None:
        if not re.search(r"^\+\+\+\s+b/.+\.yaml\b", patch_corpus, re.MULTILINE):
            return []
        if not _DMA_BINDING_DEFINES_RE.search(patch_corpus):
            return []
        if not _DMA_EXAMPLE_HAS_DMAS_RE.search(patch_corpus):
            return []
        if _DMA_EXAMPLE_HAS_DMA_NAMES_RE.search(patch_corpus):
            return []
    elif not structured_gap:
        return []
    visible_all = _visible_report_text(report)
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



_BINDING_DIFF_RE = re.compile(
    r"^diff --git a/(?P<old>[^\n]+) b/(?P<path>[^\n]+)\n(?P<body>.*?)(?=^diff --git |\Z)",
    re.MULTILINE | re.DOTALL,
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

    visible_all = _visible_report_text(report)
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


def _iter_binding_diff_bodies(
    patch_corpus: str,
) -> list[tuple[str, str]]:
    diffs: list[tuple[str, str]] = []
    for match in _BINDING_DIFF_RE.finditer(patch_corpus):
        path = match.group("path")
        if "Documentation/devicetree/bindings/" not in path or not path.endswith(".yaml"):
            continue
        diffs.append((path, match.group("body")))
    return diffs


def _binding_added_const_compatibles(
    patch_corpus: str,
) -> list[tuple[str, list[str]]]:
    bindings: list[tuple[str, list[str]]] = []
    for path, body in _iter_binding_diff_bodies(patch_corpus):
        consts: list[str] = []
        in_compatible = False
        compatible_indent = -1
        for raw_line in body.splitlines():
            if not raw_line:
                continue
            if raw_line[0] not in "+ ":
                continue
            line = raw_line[1:]
            indent = len(line) - len(line.lstrip(" "))
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "compatible:":
                in_compatible = True
                compatible_indent = indent
                continue
            if in_compatible and indent <= compatible_indent:
                in_compatible = False
            if not in_compatible or raw_line[0] != "+":
                continue
            if stripped.startswith("const:"):
                value = stripped.split(":", 1)[1].strip().strip("\"'")
                if value:
                    consts.append(value)
        if consts:
            bindings.append((path, consts))
    return bindings


def _binding_parent_compatible_hits(
    source_root: Path,
    binding_path: str,
    compat_strings: list[str],
) -> list[str]:
    bindings_root = source_root / "Documentation" / "devicetree" / "bindings"
    if not bindings_root.is_dir():
        return []

    binding_rel = Path(binding_path)
    binding_abs = source_root / binding_rel
    candidate_dirs: list[Path] = []
    if binding_abs.parent.is_dir():
        candidate_dirs.append(binding_abs.parent)
    if bindings_root not in candidate_dirs:
        candidate_dirs.append(bindings_root)

    seen: set[Path] = set()
    hits: list[str] = []
    for directory in candidate_dirs:
        try:
            paths = sorted(directory.rglob("*.yaml"))
        except OSError:
            continue
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            if path == binding_abs:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for compat in compat_strings:
                for match in re.finditer(re.escape(compat), text):
                    start = max(0, match.start() - 320)
                    end = min(len(text), match.end() + 320)
                    window = text[start:end]
                    if "oneOf" not in window and "items:" not in window and "contains:" not in window:
                        continue
                    if len(re.findall(r"\bconst:", window)) < 2:
                        continue
                    rel = path.relative_to(source_root).as_posix()
                    if rel not in hits:
                        hits.append(rel)
                    break
                if hits and hits[-1] == path.relative_to(source_root).as_posix():
                    break
    return hits


_PARENT_COMPAT_ISSUE_TERMS_RE = re.compile(
    r"reject|mismatch|over-?strict|fallback|oneOf|items:|array|multi-string|"
    r"variant|base|dtbs_check|schema",
    re.IGNORECASE,
)


def _review_covers_parent_compatible_consistency(
    text: str,
    compat_strings: list[str],
    wrapper_hits: list[str],
) -> bool:
    if not _COMPAT_FALLBACK_PROOF_RE.search(text):
        return False
    compat_mentioned = any(compat in text for compat in compat_strings)
    wrapper_mentioned = any(path in text for path in wrapper_hits)
    if not compat_mentioned and not wrapper_mentioned:
        return False
    if _PARENT_COMPAT_ISSUE_TERMS_RE.search(text):
        return True
    return False


def check_binding_parent_compatible_consistency_source_aware(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path] = None,
) -> list[Violation]:
    """Require review to reconcile child compatible shape with parent wrappers.

    If a new binding introduces a single-string compatible schema and the
    checked-in source tree already contains a wrapper/parent schema that allows
    a multi-string fallback for that compatible, the review must explicitly
    discuss that contract mismatch or file a finding.  The same requirement
    applies when the patch corpus itself adds contradictory tuple lengths or
    fallback order for the same leading compatible across schemas.
    """
    if not patch_corpus:
        return []
    visible_all = _visible_report_text(report)
    violations: list[Violation] = []

    for compat, entries in _binding_compatible_tuple_conflicts(patch_corpus):
        paths = sorted({path for path, _tuple in entries})
        tuple_text = "; ".join(
            f"{path}=[{', '.join(compat_tuple)}]"
            for path, compat_tuple in entries[:4]
        )
        if (
            _COMPAT_TUPLE_REPORT_RE.search(visible_all)
            and (compat in visible_all or any(path in visible_all for path in paths))
        ):
            continue
        violations.append(Violation(
            "binding_parent_compatible_consistency_source_aware",
            f"report (corpus-derived: {compat})",
            "patch adds incompatible compatible tuple lengths/order for the "
            f"same leading compatible across schemas ({tuple_text}); the "
            "review must reconcile the parent/wrapper and child binding "
            "contracts instead of validating each YAML in isolation",
        ))

    if source_root is None or not isinstance(source_root, Path):
        return violations
    for binding_path, compat_strings in _binding_added_const_compatibles(patch_corpus):
        wrapper_hits = _binding_parent_compatible_hits(
            source_root,
            binding_path,
            compat_strings,
        )
        if not wrapper_hits:
            continue
        if _review_covers_parent_compatible_consistency(
            visible_all,
            compat_strings,
            wrapper_hits,
        ):
            continue
        violations.append(Violation(
            "binding_parent_compatible_consistency_source_aware",
            f"report (source-derived: {binding_path})",
            "new binding uses a single-string compatible schema, but the "
            "post-apply source tree already contains a parent/wrapper schema "
            f"with a multi-string fallback for the same compatible ({', '.join(wrapper_hits[:3])}); "
            "the review must reconcile that contract explicitly instead of "
            "clearing the child binding in isolation",
        ))
    return violations


def check_old_dtb_compatibility_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require explicit old-DTB/new-kernel proof when bindings add required resources."""
    if not patch_corpus:
        return []
    required_resources = sorted(_binding_required_resource_names(patch_corpus))
    if not required_resources:
        return []

    visible_all = _visible_report_text(report)
    if _OLD_DTB_PROOF_RE.search(visible_all):
        return []

    return [Violation(
        "old_dtb_compatibility_source_aware",
        "report (corpus-derived)",
        "binding diff makes resources newly required "
        f"({', '.join(required_resources[:4])}), but the review does not "
        "state whether an old DTB still works with the new kernel or why a "
        "compatibility path exists",
    )]


def check_dt_fallback_old_kernel_new_dtb_source_aware(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path] = None,
) -> list[Violation]:
    """Require old-kernel/new-DTB proof for fallback tuples with new quirks."""
    if not patch_corpus:
        return []
    hits = _new_compat_fallback_hits(patch_corpus, source_root)
    if not hits:
        return []
    if _review_has_old_kernel_new_dtb_fallback_discussion(report):
        return []
    return [Violation(
        "dt_fallback_old_kernel_new_dtb_source_aware",
        "report (corpus-derived)",
        "new compatible is added with an existing fallback while the series "
        f"adds new resources/register behavior ({', '.join(hits[:4])}); the "
        "review must analyze old-kernel + new-DTB fallback safety, not only "
        "new-kernel + old-DTB compatibility or the new driver's primary match",
    )]


def check_provider_cells_const_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require fixed provider #*-cells contracts to use explicit const values."""
    if not patch_corpus:
        return []
    missing = _provider_cell_properties_without_const(patch_corpus)
    if not missing:
        return []
    if _review_has_finding_or_discussion(report, _PROVIDER_CELLS_CONST_REPORT_RE):
        return []
    examples = ", ".join(f"{path}:{name}" for path, name in missing[:4])
    return [Violation(
        "provider_cells_const_source_aware",
        "report (corpus-derived)",
        "binding diff adds provider cell-count properties without an explicit "
        f"const ({examples}); the review must require a fixed #*-cells "
        "contract or explain why variable cell counts are valid for this provider",
    )]


def check_optional_clk_dead_enoent_fallback(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Catch dead -ENOENT fallback logic after optional clock bulk getters."""
    if not patch_corpus:
        return []
    hits: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        if not re.search(r"^\+[^+].*devm_clk_bulk_get_optional\s*\(", body, re.MULTILINE):
            continue
        if not re.search(r"-ENOENT|ENOENT", body):
            continue
        if not re.search(r"(?:==|!=)\s*-ENOENT|-ENOENT\s*(?:==|!=)", body):
            continue
        hits.append(path)
    if not hits:
        return []
    if _review_has_finding_or_discussion(report, _OPTIONAL_CLK_DEAD_ENOENT_REPORT_RE):
        return []
    return [Violation(
        "optional_clk_dead_enoent_fallback",
        "report (corpus-derived)",
        "patch uses devm_clk_bulk_get_optional() while keeping -ENOENT "
        f"fallback/error logic ({', '.join(sorted(set(hits))[:4])}); optional "
        "clock getters return success for missing clocks, so the review must "
        "flag the dead fallback or prove this branch is reached by another error",
    )]


def check_required_clk_bulk_zero_count_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require zero-count handling for get-all clocks in required-clock contexts."""
    if not patch_corpus or not _required_clock_context(patch_corpus):
        return []
    missing: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        for match in _CLK_BULK_GET_ALL_ASSIGN_RE.finditer(body):
            lhs = match.group("lhs")
            window = body[match.start():match.start() + 900]
            if _contains_zero_count_guard(window, lhs):
                continue
            missing.append(f"{path}:{lhs}")
    if not missing:
        return []
    if _review_has_required_clk_zero_count_discussion(report):
        return []
    return [Violation(
        "required_clk_bulk_zero_count_source_aware",
        "report (corpus-derived)",
        "required-clock context uses devm_clk_bulk_get_all() without a visible "
        f"zero-count guard ({', '.join(missing[:4])}); the review must require "
        "both negative-error and zero-resource handling before later hardware access",
    )]


def check_framework_status_callback_power_state_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require proof for framework status callbacks that read MMIO before clocks."""
    if not patch_corpus:
        return []
    hits = _framework_status_callback_power_hits(patch_corpus)
    if not hits:
        return []
    if _review_has_framework_status_callback_power_discussion(report):
        return []
    return [Violation(
        "framework_status_callback_power_state_source_aware",
        "report (corpus-derived)",
        "clock-gated framework status callback reads MMIO before the driver's "
        f"enable path has prepared clocks ({', '.join(sorted(set(hits))[:4])}); "
        "the review must require source-backed always-accessible status proof or "
        "file the unpowered status-read finding",
    )]


def check_framework_status_bootloader_refcount_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require Linux-side refcount sync when status can skip enable."""
    if not patch_corpus:
        return []
    hits = _framework_status_bootloader_refcount_hits(patch_corpus)
    if not hits:
        return []
    if _review_has_bootloader_refcount_discussion(report):
        return []
    return [Violation(
        "framework_status_bootloader_refcount_source_aware",
        "report (corpus-derived)",
        "framework status callback plus clk_bulk enable/disable can skip the "
        "driver's enable path when firmware left hardware already on, then later "
        f"call disable/unprepare without Linux-side clock counts ({', '.join(sorted(set(hits))[:4])}); "
        "the review must require bootloader-state synchronization proof or file "
        "the underflow/unbalanced-disable finding",
    )]


def check_managed_device_link_manual_remove_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Catch manual teardown paired with auto-remove managed device links."""
    if not patch_corpus:
        return []
    hits: list[str] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        adds_autoremove = re.search(r"^\+[^+].*DL_FLAG_AUTOREMOVE_(?:CONSUMER|SUPPLIER)", body, re.MULTILINE)
        adds_manual_remove = re.search(r"^\+[^+].*device_link_(?:remove|del)\s*\(", body, re.MULTILINE)
        if not (adds_autoremove or adds_manual_remove):
            continue
        if not re.search(r"DL_FLAG_AUTOREMOVE_(?:CONSUMER|SUPPLIER)", body):
            continue
        if not re.search(r"device_link_(?:remove|del)\s*\(", body):
            continue
        hits.append(path)
    if not hits:
        return []
    if _review_has_finding_or_discussion(report, _MANAGED_DEVICE_LINK_REPORT_RE):
        return []
    return [Violation(
        "managed_device_link_manual_remove_source_aware",
        "report (corpus-derived)",
        "patch combines DL_FLAG_AUTOREMOVE_* device links with manual "
        f"device_link_remove()/device_link_del() cleanup ({', '.join(sorted(set(hits))[:4])}); "
        "the review must check the driver-core lifetime contract or file the "
        "managed/manual cleanup bug",
    )]


def check_retained_dynamic_object_cleanup_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require clearing retained pointers after cleanup frees dynamic objects."""
    if not patch_corpus:
        return []
    candidates = _retained_dynamic_cleanup_candidates(patch_corpus)
    if not candidates:
        return []
    if _review_has_finding_or_discussion(report, _RETAINED_DYNAMIC_CLEANUP_REPORT_RE):
        return []
    return [Violation(
        "retained_dynamic_object_cleanup_source_aware",
        "report (corpus-derived)",
        "patch stores dynamically allocated framework objects in retained "
        f"descriptor state and has cleanup paths without a visible pointer reset ({', '.join(candidates[:4])}); "
        "the review must require clearing the retained pointer or prove retry/rebind cannot reuse freed state",
    )]


def check_level_irq_reenable_without_clear_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require IRQ source clear/mask before re-enabling after early PM/state exits."""
    if not patch_corpus:
        return []
    candidates = _level_irq_reenable_candidates(patch_corpus)
    if not candidates:
        return []
    if _review_has_finding_or_discussion(report, _LEVEL_IRQ_REENABLE_REPORT_RE):
        return []
    return [Violation(
        "level_irq_reenable_without_clear_source_aware",
        "report (corpus-derived)",
        "patch adds an early runtime-PM/device-state IRQ exit that calls "
        f"enable_irq() before a visible source clear or mask ({', '.join(candidates[:4])}); "
        "for level-triggered IRQs this can immediately retrigger, so the review "
        "must require clear/mask proof or file the interrupt-storm risk",
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
_HELPER_REPLACEMENT_SIDE_EFFECT_CALL_RE = re.compile(
    r"^-.*?\b(?P<call>("
    r"clk_(?:prepare_enable|enable|disable|prepare|set_rate|set_parent|round_rate)|"
    r"(?:devm_)?dev_pm_opp_(?:set_rate|set_opp|set_clkname)|"
    r"(?:\w+_)?icc_(?:set_bw|enable|disable)|"
    r"regulator_(?:enable|disable)|"
    r"pm_runtime_(?:get_sync|resume_and_get|put|put_sync|put_noidle|enable|disable)|"
    r"dma_request_chan|request_irq|irq_set_[A-Za-z0-9_]+"
    r"))\s*\(",
    re.MULTILINE,
)
_HELPER_REPLACEMENT_CATEGORY_TERMS = {
    "clock": re.compile(r"\b(?:clk|clock|rate|freq|frequency)\b", re.IGNORECASE),
    "opp_perf": re.compile(r"\b(?:opp|performance|perf|voltage|rate)\b", re.IGNORECASE),
    "icc_bw": re.compile(r"\b(?:icc|bandwidth|avg_bw|vote)\b", re.IGNORECASE),
    "regulator": re.compile(r"\bregulator\b", re.IGNORECASE),
    "pm_runtime": re.compile(r"\bpm_runtime|runtime pm|runtime[- ]resume|runtime[- ]suspend\b", re.IGNORECASE),
    "dma_irq": re.compile(r"\b(?:dma|irq|interrupt)\b", re.IGNORECASE),
}
_HELPER_REPLACEMENT_PROOF_TERMS_RE = re.compile(
    r"calls|invokes|restores|re-?sets|re-?programs|re-?votes|enables|disables|"
    r"guards|checks|preserves|missing|dropped|removed|not\s+restored|"
    r"not\s+preserved|changed|regression",
    re.IGNORECASE,
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


# Maps a side-effect category to the prefix pattern that classifies a call name.
_HELPER_REPLACEMENT_SIDE_EFFECT_CATEGORY_MAP = {
    "clock": re.compile(r"^clk_", re.IGNORECASE),
    "opp_perf": re.compile(r"^(?:devm_)?dev_pm_opp_", re.IGNORECASE),
    "icc_bw": re.compile(r"(?:^|_)icc_", re.IGNORECASE),
    "regulator": re.compile(r"^regulator_", re.IGNORECASE),
    "pm_runtime": re.compile(r"^pm_runtime_", re.IGNORECASE),
    "dma_irq": re.compile(r"^(?:dma_|request_irq|irq_set_)", re.IGNORECASE),
}


def _helper_replacement_side_effect_categories(
    patch_corpus: str,
) -> dict[str, set[str]]:
    categories: dict[str, set[str]] = {}
    for match in _HELPER_REPLACEMENT_SIDE_EFFECT_CALL_RE.finditer(patch_corpus):
        call = match.group("call")
        for category, pattern in _HELPER_REPLACEMENT_SIDE_EFFECT_CATEGORY_MAP.items():
            if not pattern.search(call):
                continue
            categories.setdefault(category, set()).add(call)
            break
    return categories


def _report_covers_helper_postcondition(
    text: str,
    category: str,
    calls: set[str],
    *,
    require_helper_source_proof: bool,
) -> bool:
    category_re = _HELPER_REPLACEMENT_CATEGORY_TERMS.get(category)
    if category_re is None:
        return False
    call_re = re.compile("|".join(re.escape(call) for call in sorted(calls)), re.IGNORECASE)
    has_call_or_category = bool(call_re.search(text) or category_re.search(text))
    if not has_call_or_category:
        return False
    if not _HELPER_REPLACEMENT_PROOF_TERMS_RE.search(text):
        return False
    if require_helper_source_proof:
        return bool(_HELPER_BODY_PROOF_RE.search(text))
    return True


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

    searched_text = _augment_with_source_root(patch_corpus, source_root)

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


def check_helper_replacement_postcondition_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require helper replacements to preserve or discuss removed postconditions.

    When a patch removes direct side-effecting calls and replaces them with a
    helper/setup routine, the review must either prove the helper preserves the
    removed postcondition from source or file a finding about the changed
    behavior.
    """
    if not patch_corpus:
        return []
    if not _RESOURCE_SETUP_HELPER_ADDED_RE.search(patch_corpus):
        return []

    removed_categories = _helper_replacement_side_effect_categories(patch_corpus)
    if not removed_categories:
        return []

    visible_all = _visible_report_text(report)
    missing: list[str] = []
    for category, calls in sorted(removed_categories.items()):
        if _report_covers_helper_postcondition(
            visible_all,
            category,
            calls,
            require_helper_source_proof=True,
        ):
            continue
        has_finding = False
        for block in report.blocks:
            for finding in block.findings:
                if finding.severity not in ("BUG", "CONCERN"):
                    continue
                text = f"{finding.title}\n{finding.body}"
                if _report_covers_helper_postcondition(
                    text,
                    category,
                    calls,
                    require_helper_source_proof=False,
                ):
                    has_finding = True
                    break
            if has_finding:
                break
        if not has_finding:
            missing.append(f"{category} ({', '.join(sorted(calls))})")
    if not missing:
        return []
    return [Violation(
        "helper_replacement_postcondition_source_aware",
        "report (corpus-derived)",
        "patch replaces direct side-effecting setup/resume/resource calls with "
        "a helper, but the review does not prove the helper preserves the "
        f"removed postcondition(s) or file a finding about the change: {'; '.join(missing[:4])}",
    )]


def check_match_data_source_aware(
    report: Report,
    patch_corpus: str,
    evidence_by_block: Optional[dict[int, dict[str, object]]] = None,
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
    structured_exprs = _structured_match_data_unguarded_exprs(evidence_by_block)
    if structured_exprs is None:
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
    else:
        vars_needing_findings = structured_exprs
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


def check_selector_cardinality_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require explicit selector/cardinality discussion for add-support work."""
    if not patch_corpus:
        return []
    if not _ADD_SUPPORT_CONTEXT_RE.search(patch_corpus):
        return []

    surfaces = sorted(set(match.group(0) for match in _SELECTOR_CARDINALITY_SURFACE_RE.finditer(patch_corpus)))
    if not surfaces:
        return []

    visible_all = _visible_report_text(report)
    if _SELECTOR_CARDINALITY_PROOF_RE.search(visible_all):
        return []

    return [Violation(
        "selector_cardinality_source_aware",
        "report (corpus-derived)",
        "add-support / new-descriptor patch touches selector/cardinality "
        f"surfaces ({', '.join(surfaces[:4])}), but the review does not "
        "explicitly compare the affected IDs/counts/names/routes across the "
        "relevant tables or bindings",
    )]


def _proof_is_colocated(
    text: str,
    proof_re: "re.Pattern[str]",
    context_re: "re.Pattern[str]",
    window: int = 200,
) -> bool:
    """True when a ``proof_re`` hit sits within ``window`` chars of a
    ``context_re`` hit.

    The aggregate-scale and similar source-aware checks clear their violation
    when the report "addresses" the issue. A bare keyword match anywhere in the
    block is too weak: an unrelated finding using a shared word (e.g. a clock
    finding that says hardware "may be starved") would falsely satisfy the
    proof. Requiring the proof token to be co-located with width-context
    vocabulary keeps the exemption honest. If either side never matches, there
    is no co-location and the caller must keep the find-or-prove obligation.
    """
    proof_spans = [m.start() for m in proof_re.finditer(text)]
    if not proof_spans:
        return False
    context_spans = [m.start() for m in context_re.finditer(text)]
    if not context_spans:
        return False
    return any(
        abs(p - c) <= window for p in proof_spans for c in context_spans
    )


def check_aggregate_per_element_scale_source_aware(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path] = None,
) -> list[Violation]:
    """Flag container-width divisors when a per-element width field exists.

    Mirrors refs/code-logic.md "Aggregate-vs-per-element scale audit": a rate/
    bandwidth/length term divided by a fabric/global/descriptor width while the
    element struct exposes its own same-dimension field silently mis-scales the
    non-typical elements. Fires when the container-scaled divide is in the diff
    and a per-element same-dimension field is visible in the diff OR the touched
    source, and the review never addresses the per-element width — so numerator
    multipliers and homogeneous single-source calcs are not flagged.

    Source-aware: the per-element field and its concrete values often live in an
    unchanged struct/table the diff only references. Reading the touched files
    lets the check (a) find the per-element field when it is not in the hunk and
    (b) confirm the values are heterogeneous, which is the actual bug condition —
    a uniform width makes the container divisor harmless.
    """
    if not patch_corpus:
        return []
    if not _AGG_SCALE_CONTAINER_DIVISOR_RE.search(patch_corpus):
        return []

    searched_text = _augment_with_source_root(patch_corpus, source_root)

    if not _AGG_SCALE_PER_ELEMENT_FIELD_RE.search(searched_text):
        return []

    # Heterogeneity gate: the mis-scale only harms when elements carry differing
    # widths. If every per-element width literal is identical (uniform fabric),
    # the container divisor is equivalent and there is no defect to demand. Only
    # apply this exemption when concrete values are actually visible; if none are
    # (field exists but values are computed/elsewhere), keep the find-or-prove
    # obligation rather than silently clearing.
    width_values = set(_AGG_SCALE_WIDTH_VALUE_RE.findall(searched_text))
    if len(width_values) == 1:
        return []

    visible_all = _visible_report_text(report)

    # ---- Discharge-correctness check (Phase-2 gate) ----
    # When the report explicitly DISMISSES the rule (says "no mis-scale",
    # "correct denominator", "matches icc-rpm.c convention", or similar
    # discharge language), require a strong citation grounding the dismissal
    # in the actual reference: the per-node divisor function, field, or
    # invocation. The v3 post-Phase-1 report cleared the prior keyword-proof
    # gate by inventing a two-tier "fabric vs aggregate" model that does not
    # exist in icc-rpm.c; that anchoring failure must surface as its own
    # violation rather than silently passing.
    if _AGG_SCALE_DISMISSAL_RE.search(visible_all) and not (
        _AGG_SCALE_STRONG_CITATION_RE.search(visible_all)
    ):
        return [Violation(
            "aggregate_per_element_scale_source_aware",
            "report (corpus-derived)",
            "report dismisses the per-element-scale concern (e.g. 'no "
            "mis-scale', 'matches icc-rpm.c convention', 'correct "
            "denominator') but the discharge does not cite the actual "
            "per-node divisor — `qn->buswidth` / `qcom_icc_calc_rate` / "
            "`div_u64(...qn->buswidth)` — that the in-tree reference uses. "
            "A keyword-level 'matches the convention' is anchoring on the "
            "rule name, not grounding in the source: file the finding or "
            "quote the canonical divisor",
        )]

    # ---- Standard proof gate (Phase-1) ----
    # The report only clears this violation when a proof token is co-located
    # with width-context vocabulary. A bare proof keyword elsewhere in the
    # block (e.g. an unrelated clock finding saying hardware "may be
    # starved") must NOT satisfy the per-element-width discussion obligation.
    if _proof_is_colocated(
        visible_all, _AGG_SCALE_PROOF_RE, _AGG_SCALE_WIDTH_CONTEXT_RE
    ):
        return []

    return [Violation(
        "aggregate_per_element_scale_source_aware",
        "report (corpus-derived)",
        "patch divides a per-element bandwidth/rate by a container/fabric width "
        "(`desc->`/`provider->`/`qp->desc->`) while the element struct exposes "
        "its own same-dimension width field with differing values, but the "
        "review does not compare the per-element width or prove the elements are "
        "homogeneous — possible silent mis-scale of narrower/wider elements",
    )]


def check_cross_instance_pointer_unbind_source_aware(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path] = None,
) -> list[Violation]:
    """Flag cross-instance raw node pointers without an unbind lifetime guard.

    Mirrors refs/hardware-eng.md "Cross-instance raw pointer held across
    independent unbind" and the gate-rules.md clearance row: one provider stores
    a raw pointer into a sibling that is independently unbindable. Fires when the
    diff creates peer/cross-provider links and `.suppress_bind_attrs = true` is
    set neither in the diff nor in the touched source, unless the review proves
    the lifetime guarantee (suppress_bind_attrs, refcount/get_device,
    device_link, or coordinated teardown).

    Source-aware: `.suppress_bind_attrs = true` and the platform_driver struct
    frequently sit in an unchanged hunk of the touched file, so a diff-only scan
    would false-fire. Reading the touched source confirms whether the unbind
    guard actually exists before demanding a finding.
    """
    if not patch_corpus:
        return []
    if not _CROSS_INSTANCE_LINK_RE.search(patch_corpus):
        return []

    searched_text = _augment_with_source_root(patch_corpus, source_root)

    if _SUPPRESS_BIND_ATTRS_RE.search(searched_text):
        return []

    visible_all = _visible_report_text(report)
    if _CROSS_INSTANCE_PROOF_RE.search(visible_all):
        return []

    return [Violation(
        "cross_instance_pointer_unbind_source_aware",
        "report (corpus-derived)",
        "patch stores a cross-provider/peer raw node pointer "
        "(icc_link_nodes/link_nodes/links[]) without `.suppress_bind_attrs = "
        "true`, but the review does not prove a lifetime guarantee against "
        "independent sysfs unbind (suppress_bind_attrs, get_device/refcount, "
        "device_link, or coordinated teardown) — possible use-after-free of a "
        "freed peer node",
    )]



def check_peer_dimension_admission_source_aware(
    report: Report,
    patch_corpus: str,
    evidence_by_block: Optional[dict[int, dict[str, object]]] = None,
) -> list[Violation]:
    """Require review discussion for missing peer-dimension admission guards."""
    del patch_corpus
    missing = _structured_peer_dimension_admission_facts(evidence_by_block)
    if missing is None:
        return []
    if not missing:
        return []

    visible_all = _visible_report_text(report)
    for fact in missing:
        checked = fact.get("checked_dimension", "")
        peer = fact.get("missing_dimension", "")
        checked_re = re.escape(checked) if checked else r"$^"
        peer_re = re.escape(peer) if peer else r"$^"
        if re.search(
            rf"(?:{checked_re}|{peer_re})[\s\S]{{0,180}}(?:peer dimension|missing dimension|admission|capacity)|"
            rf"(?:peer dimension|missing dimension|admission|capacity)[\s\S]{{0,180}}(?:{checked_re}|{peer_re})",
            visible_all,
            re.IGNORECASE,
        ):
            return []
        for block in report.blocks:
            for finding in block.findings:
                if finding.severity not in ("BUG", "CONCERN"):
                    continue
                text = f"{finding.title}\n{finding.body}"
                if _PEER_DIMENSION_REPORT_RE.search(text) and (
                    (checked and re.search(rf"\b{checked_re}\b", text, re.IGNORECASE))
                    or (peer and re.search(rf"\b{peer_re}\b", text, re.IGNORECASE))
                ):
                    return []

    sample = missing[0]
    checked = sample.get("checked_dimension") or "one dimension"
    peer = sample.get("missing_dimension") or "peer dimension"
    path = sample.get("path") or "touched source"
    return [Violation(
        "peer_dimension_admission_source_aware",
        "report (evidence-manifest-derived)",
        "patch adds an admission/capacity guard for "
        f"`{checked}` in `{path}` while the peer dimension `{peer}` is present "
        "on the same contract, but no review block flags or proves the missing "
        "peer-dimension check as a [BUG] or [CONCERN]",
    )]


def check_duplicate_cleanup_fallthrough_source_aware(
    report: Report,
    patch_corpus: str,
    evidence_by_block: Optional[dict[int, dict[str, object]]] = None,
) -> list[Violation]:
    """Require explicit review discussion for duplicated unwind/cleanup work."""
    del patch_corpus
    duplicates = _structured_duplicate_teardown_facts(evidence_by_block)
    if duplicates is None:
        return []
    if not duplicates:
        return []

    visible_all = _visible_report_text(report)
    for fact in duplicates:
        call = fact.get("call", "")
        path = fact.get("path", "")
        call_re = re.escape(call) if call else r"$^"
        if re.search(
            rf"\b(?:duplicate|double|twice|fallthrough|fall through|unwind|cleanup|teardown|error path)\b"
            rf"[\s\S]{{0,120}}{call_re}|{call_re}[\s\S]{{0,120}}"
            rf"\b(?:duplicate|double|twice|fallthrough|fall through|unwind|cleanup|teardown|error path)\b",
            visible_all,
            re.IGNORECASE,
        ):
            return []
        if call and re.search(rf"\b{call_re}\b", visible_all, re.IGNORECASE):
            for block in report.blocks:
                for finding in block.findings:
                    text = f"{finding.title} {finding.body}"
                    if finding.severity in ("BUG", "CONCERN") and re.search(
                        rf"\b{call_re}\b",
                        text,
                        re.IGNORECASE,
                    ):
                        return []

    sample = duplicates[0]
    call = sample.get("call") or "cleanup helper"
    path = sample.get("path") or "touched source"
    return [Violation(
        "duplicate_cleanup_fallthrough_source_aware",
        "report (evidence-manifest-derived)",
        "patch duplicates teardown/unwind work for "
        f"`{call}` in `{path}`, but no review block flags the duplicate "
        "cleanup/fallthrough risk as a [BUG] or [CONCERN]",
    )]


def check_failed_start_stale_state_source_aware(
    report: Report,
    patch_corpus: str,
    evidence_by_block: Optional[dict[int, dict[str, object]]] = None,
) -> list[Violation]:
    """Require review discussion for success state left stale after failure."""
    del patch_corpus
    stale = _structured_failed_start_stale_state_facts(evidence_by_block)
    if stale is None:
        return []
    if not stale:
        return []

    visible_all = _visible_report_text(report)
    for fact in stale:
        state = fact.get("state_target", "")
        operation = fact.get("operation", "")
        state_re = re.escape(state) if state else r"$^"
        operation_re = re.escape(operation) if operation else r"$^"
        if re.search(
            rf"(?:stale state|failed[- ](?:start|resume|enable|load|boot|activate)|failure leaves|state contamination)"
            rf"[\s\S]{{0,180}}(?:{state_re}|{operation_re})|"
            rf"(?:{state_re}|{operation_re})[\s\S]{{0,180}}"
            rf"(?:stale state|failed[- ](?:start|resume|enable|load|boot|activate)|failure leaves|state contamination)",
            visible_all,
            re.IGNORECASE,
        ):
            return []
        for block in report.blocks:
            for finding in block.findings:
                if finding.severity not in ("BUG", "CONCERN"):
                    continue
                text = f"{finding.title}\n{finding.body}"
                if _STALE_STATE_REPORT_RE.search(text) and (
                    (state and re.search(rf"\b{state_re}\b", text, re.IGNORECASE))
                    or (operation and re.search(rf"\b{operation_re}\b", text, re.IGNORECASE))
                ):
                    return []

    sample = stale[0]
    state = sample.get("state_target") or "success state"
    operation = sample.get("operation") or "start/resume operation"
    path = sample.get("path") or "touched source"
    return [Violation(
        "failed_start_stale_state_source_aware",
        "report (evidence-manifest-derived)",
        "patch sets success state "
        f"`{state}` before `{operation}` can fail in `{path}`, but no review "
        "block flags the failed-start stale-state contamination as a [BUG] or "
        "[CONCERN]",
    )]


def _review_has_paired_callback_backend_symmetry_discussion(report: Report) -> bool:
    for block in report.blocks:
        for finding in block.findings:
            if finding.severity not in ("BUG", "CONCERN"):
                continue
            text = f"{finding.title}\n{finding.body}\n{finding.suggestion}"
            lowered = text.lower()
            if (
                "prepare" in lowered
                and "unprepare" in lowered
                and _PAIRED_CALLBACK_BACKEND_FINDING_RE.search(text)
            ):
                return True
    return False


def check_paired_callback_backend_symmetry_source_aware(
    report: Report,
    patch_corpus: str,
) -> list[Violation]:
    """Require same-backend cleanup proof for prepare/unprepare fallback wrappers."""
    hits = _paired_callback_backend_symmetry_hits(patch_corpus)
    if not hits:
        return []
    if _review_has_paired_callback_backend_symmetry_discussion(report):
        return []
    return [Violation(
        "paired_callback_backend_symmetry_source_aware",
        "report (corpus-derived)",
        "patch adds a lifecycle workflow where prepare can fall back to the "
        "normal backend after an optional backend error, while unprepare can "
        "return early through the optional backend; the review must prove every "
        "prepare outcome is paired with cleanup selected from the same "
        "session/resource owner or file the "
        f"stale cleanup/state bug ({'; '.join(hits[:3])})",
    )]


def check_escaped_local_address_source_aware(
    report: Report,
    patch_corpus: str,
    evidence_by_block: Optional[dict[int, dict[str, object]]] = None,
) -> list[Violation]:
    """Require a finding for stack/local addresses stored in retained state."""
    del patch_corpus
    escaped = _structured_escaped_local_address_facts(evidence_by_block)
    if escaped is None:
        return []
    if not escaped:
        return []

    for block in report.blocks:
        for finding in block.findings:
            if finding.severity not in ("BUG", "CONCERN"):
                continue
            text = f"{finding.title}\n{finding.body}"
            if not _ESCAPED_LOCAL_REPORT_RE.search(text):
                continue
            for fact in escaped:
                local = fact.get("local", "")
                target = fact.get("target", "")
                if (
                    (local and re.search(rf"\b{re.escape(local)}\b", text, re.IGNORECASE))
                    or (target and re.search(rf"\b{re.escape(target)}\b", text, re.IGNORECASE))
                    or ("drvdata" in text.lower())
                    or ("platform_data" in text.lower())
                ):
                    return []

    sample = escaped[0]
    target = sample.get("target") or "retained state"
    local = sample.get("local") or "local object"
    return [Violation(
        "escaped_local_address_source_aware",
        "report (evidence-manifest-derived)",
        "patch stores the address of a stack/local object into longer-lived "
        f"state (`{target}` <- `&{local}`), but no review block files the "
        "lifetime bug as a [BUG] or [CONCERN]",
    )]


def check_setup_return_guard_source_aware(
    report: Report,
    patch_corpus: str,
    evidence_by_block: Optional[dict[int, dict[str, object]]] = None,
) -> list[Violation]:
    """Require review discussion when setup return codes flow into publish paths."""
    del patch_corpus
    unchecked = _structured_unchecked_setup_before_publish(evidence_by_block)
    if unchecked is None:
        return []
    if not unchecked:
        return []

    visible_all = _visible_report_text(report)
    missing: list[str] = []
    for fact in unchecked:
        helper = fact.get("helper", "")
        publish_call = fact.get("publish_call", "")
        status_var = fact.get("status_var", "")
        helper_re = re.escape(helper) if helper else ""
        publish_re = re.escape(publish_call) if publish_call else ""
        mentions_flow = bool(re.search(
            rf"(?:{helper_re}|{publish_re}|{re.escape(status_var)})" if (helper or publish_call or status_var) else r"$^",
            visible_all,
            re.IGNORECASE,
        ))
        if mentions_flow and _SETUP_RETURN_DISCUSSION_RE.search(visible_all):
            continue

        found_issue = False
        for block in report.blocks:
            for finding in block.findings:
                if finding.severity not in ("BUG", "CONCERN"):
                    continue
                text = f"{finding.title}\n{finding.body}"
                if not _SETUP_RETURN_DISCUSSION_RE.search(text):
                    continue
                if re.search(
                    rf"(?:{helper_re}|{publish_re}|{re.escape(status_var)})" if (helper or publish_call or status_var) else r"$^",
                    text,
                    re.IGNORECASE,
                ):
                    found_issue = True
                    break
            if found_issue:
                break
        if not found_issue:
            flow_bits = [item for item in (helper, publish_call, status_var) if item]
            missing.append(" -> ".join(flow_bits) if flow_bits else "setup-return flow")

    if not missing:
        return []
    return [Violation(
        "setup_return_guard_source_aware",
        "report (evidence-manifest-derived)",
        "patch captures a setup/helper status code and reaches a publish/"
        "registration step without an in-hunk check, but the review does not "
        "discuss whether that return is guarded or file a finding about the "
        f"unchecked flow(s): {'; '.join(missing[:4])}",
    )]


def check_newly_exposed_silent_failure_source_aware(
    report: Report,
    patch_corpus: str,
    evidence_by_block: Optional[dict[int, dict[str, object]]] = None,
) -> list[Violation]:
    """Require review discussion for rewired setters that silently reject valid values."""
    del patch_corpus
    facts = _structured_newly_exposed_silent_failure_facts(evidence_by_block)
    if facts is None:
        return []
    if not facts:
        return []

    visible_all = _visible_report_text(report)
    missing: list[str] = []
    for fact in facts:
        cap_id = fact.get("cap_id", "")
        setter = fact.get("setter", "")
        reject_guard = fact.get("reject_guard", "")
        replay_path = fact.get("replay_path", "")
        path = fact.get("path", "")
        flow_terms = [term for term in (cap_id, setter, reject_guard, replay_path, path) if term]
        flow_re = "|".join(re.escape(term) for term in flow_terms) if flow_terms else r"$^"

        found_issue = False
        for block in report.blocks:
            for finding in block.findings:
                if finding.severity not in ("BUG", "CONCERN"):
                    continue
                text = f"{finding.title}\n{finding.body}"
                if not _SILENT_SETTER_FAILURE_REPORT_RE.search(text):
                    continue
                if re.search(flow_re, text, re.IGNORECASE) if flow_terms else False:
                    found_issue = True
                    break
            if found_issue:
                break

        if not found_issue:
            missing.append(" -> ".join(term for term in (cap_id, setter, replay_path) if term) or setter or path or "setter contract")

    if not missing:
        return []
    return [Violation(
        "newly_exposed_silent_failure_source_aware",
        "report (evidence-manifest-derived)",
        "patch rewires a control/capability to a setter that rejects an "
        "advertised zero/default value while a callback replay path ignores the "
        "setter return, but no review block flags the newly exposed silent "
        f"configuration-loss flow(s): {'; '.join(missing[:4])}",
    )]


def check_touched_unsafe_pm_source_aware(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path] = None,
    evidence_by_block: Optional[dict[int, dict[str, object]]] = None,
) -> list[Violation]:
    """Source-aware backstop for touched unsafe runtime-PM get patterns.

    When a patch touches a source file and the diff/context shows a bare
    `pm_runtime_get_sync()` statement, the review must either flag it or prove
    the return is checked/balanced.  This intentionally covers pre-existing
    hazards exposed by the touched execution path, not only newly added lines.
    """
    if not patch_corpus:
        return []
    structured_hits = _structured_runtime_pm_bare_hits(evidence_by_block)
    if structured_hits is None:
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
    else:
        source_hits = structured_hits
        if not source_hits:
            return []

    visible_all = _visible_report_text(report)
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


def check_core_table_vendor_entry_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Phase 2 — vendor/driver construct threaded into a core subsystem.

    When a patch hunk targets a core-subsystem file (the IOMMU core, the driver
    core, of/, kernel/, mm/) and adds a vendor-named bus/type into a core table,
    a driver-private/vendor `#include`, or a `CONFIG_<VENDOR>` guard, the review
    must raise the layering question (a `[CONCERN]`/`[BUG]` or explicit
    discussion) rather than clearing it with a positive note.  Mirrors
    refs/code-logic.md (3c.6 Subsystem Layering / Placement).
    """
    if not patch_corpus:
        return []
    if not _CORE_SUBSYS_FILE_RE.search(patch_corpus):
        return []

    # Confirm at least one genuinely vendor-specific addition (filter out the
    # generic buses / core config tokens that legitimately live in core tables).
    vendor_hit = False
    for m in _CORE_SUBSYS_VENDOR_ADD_RE.finditer(patch_corpus):
        sym = (m.group("sym") or "").lower()
        cfg = (m.group("cfg") or "").upper()
        hdr = (m.group("hdr") or "").lower()
        if sym and sym not in _GENERIC_BUS_NAMES:
            vendor_hit = True
            break
        if hdr and hdr not in _GENERIC_BUS_NAMES:
            vendor_hit = True
            break
        if cfg and cfg not in _GENERIC_CONFIG_TOKENS:
            vendor_hit = True
            break
        if m.group(0).lstrip().startswith("+") and "drivers/" in m.group(0):
            vendor_hit = True
            break
    if not vendor_hit:
        return []

    visible_all = _visible_report_text(report)
    # A finding or explicit layering discussion anywhere in the report
    # discharges the obligation.
    if _LAYERING_FINDING_RE.search(visible_all):
        return []
    has_finding = any(
        card.severity in ("BUG", "CONCERN")
        and _LAYERING_FINDING_RE.search(f"{card.title}\n{card.body}")
        for block in report.blocks
        for card in block.findings
    )
    if has_finding:
        return []
    # Only an explicit, justified clearance is acceptable.
    if _LAYERING_CLEARED_RE.search(visible_all):
        return []

    return [Violation(
        "core_table_vendor_entry_source_aware",
        "report (corpus-derived)",
        "patch threads a vendor/driver-specific construct into a core subsystem "
        "(core table entry, driver-private/vendor #include, or CONFIG_<VENDOR> "
        "guard in drivers/iommu, drivers/base, of/, kernel/ or mm/) but the "
        "report neither raises the layering question as a [CONCERN]/[BUG] nor "
        "states the placement is generic / maintainer-acknowledged; layering "
        "objections are a top upstream-rejection reason — see refs/code-logic.md "
        "3c.6 Subsystem Layering / Placement",
    )]


def check_stack_struct_zero_init_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Phase 3 — stack struct passed to a kernel API without zero-init.

    When the diff declares a known attach/config descriptor struct on the stack
    (e.g. ``struct dev_pm_domain_attach_data``), assigns some fields, but neither
    zero-initializes it (``= {}`` / ``memset``) nor has the review discuss the
    uninitialized-field hazard, flag it.  Mirrors refs/code-logic.md (Kernel-API
    structs, not only on-wire).
    """
    if not patch_corpus:
        return []
    violations: list[Violation] = []
    for decl in _STACK_STRUCT_DECL_RE.finditer(patch_corpus):
        ty = decl.group("ty")
        var = decl.group("var")
        zeroinit_re = re.compile(
            _STACK_STRUCT_ZEROINIT_RE_TMPL.format(ty=re.escape(ty), var=re.escape(var))
        )
        if zeroinit_re.search(patch_corpus):
            continue
        field_re = re.compile(
            _STACK_STRUCT_FIELD_ASSIGN_RE_TMPL.format(var=re.escape(var)),
            re.MULTILINE,
        )
        if not field_re.search(patch_corpus):
            # Declared but not field-assigned in the diff — nothing to flag.
            continue
        visible_all = _visible_report_text(report)
        if _STACK_STRUCT_REVIEW_PROOF_RE.search(visible_all):
            continue
        violations.append(Violation(
            "stack_struct_zero_init_source_aware",
            "report (corpus-derived)",
            f"diff declares `struct {ty} {var};` on the stack and assigns "
            "individual fields without a preceding `= {}`/`memset()`, but the "
            "review does not address the uninitialized-field hazard (unset "
            "members carry stack garbage into the kernel API); see "
            "refs/code-logic.md (Kernel-API structs, not only on-wire)",
        ))
        break
    return violations


def check_pas_metadata_release_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Phase 3 — SCM PAS firmware-metadata release pairing.

    When the diff loads PAS firmware via ``qcom_mdt_pas_load()`` /
    ``qcom_scm_pas_init_image()`` but never calls
    ``qcom_scm_pas_metadata_release()``, the review must flag the per-load
    metadata leak.  Mirrors refs/code-logic.md (API alloc/release-pairing
    contract checklist).
    """
    if not patch_corpus:
        return []
    if not _PAS_LOAD_DIFF_RE.search(patch_corpus):
        return []
    if _PAS_METADATA_RELEASE_DIFF_RE.search(patch_corpus):
        # The release counterpart is present in the diff — paired.
        return []
    visible_all = _visible_report_text(report)
    if _PAS_METADATA_REVIEW_PROOF_RE.search(visible_all):
        return []
    return [Violation(
        "pas_metadata_release_source_aware",
        "report (corpus-derived)",
        "diff calls qcom_mdt_pas_load()/qcom_scm_pas_init_image() (which "
        "allocate firmware-metadata memory the caller must free) but neither the "
        "diff nor the review pairs it with qcom_scm_pas_metadata_release(); this "
        "leaks metadata on every load — see refs/code-logic.md (API "
        "alloc/release-pairing contract checklist)",
    )]



def _added_diff_source(body: str) -> str:
    """Return only added source lines from a unified diff body."""
    return "\n".join(
        line[1:] for line in body.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def _iter_qcom_clk_added_sources(patch_corpus: str) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    for path, body in _iter_source_diff_bodies(patch_corpus):
        if not path.startswith("drivers/clk/qcom/") or not path.endswith((".c", ".h")):
            continue
        added = _added_diff_source(body)
        if added:
            sources.append((path, added))
    return sources


_C_STRUCT_INIT_RE = re.compile(
    r"static\s+(?:const\s+)?struct\s+(?P<type>[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\s*\[[^\]]*\])?\s*=\s*\{"
    r"(?P<body>.*?)\n\};",
    re.DOTALL,
)


def _iter_c_struct_initializers(source: str, struct_type: str) -> list[tuple[str, str]]:
    return [
        (match.group("name"), match.group("body"))
        for match in _C_STRUCT_INIT_RE.finditer(source)
        if match.group("type") == struct_type
    ]


def _report_has_bug_concern_finding(report: Report, *patterns: re.Pattern[str]) -> bool:
    for block in report.blocks:
        for finding in block.findings:
            if finding.severity not in ("BUG", "CONCERN"):
                continue
            text = f"{finding.title}\n{finding.body}"
            if all(pattern.search(text) for pattern in patterns):
                return True
    return False


def check_qcom_clock_hw_clk_ctrl_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Require a finding for AHB/XO RCGs marked as hardware controlled.

    This is intentionally narrow: the known false-clearance pattern is a newly
    added Qcom clk_rcg2 source clock named as a software bus/XO source while
    also setting .hw_clk_ctrl = true.  A PASS attestation is not enough; the
    block must file a counted finding or validation fails and triggers repair.
    """
    hits: list[str] = []
    for path, source in _iter_qcom_clk_added_sources(patch_corpus):
        for name, body in _iter_c_struct_initializers(source, "clk_rcg2"):
            if ".hw_clk_ctrl" not in body or "true" not in body:
                continue
            if not name.endswith("_ahb_clk_src"):
                continue
            if re.search(r"_(?:fast|slow)_ahb_clk_src$", name):
                continue
            hits.append(f"{path}:{name}")

    if not hits:
        return []
    if _report_has_bug_concern_finding(
        report,
        re.compile(r"hw_clk_ctrl", re.IGNORECASE),
        re.compile(r"ahb|xo|software|timeout|update_config", re.IGNORECASE),
    ):
        return []
    return [Violation(
        "qcom_clock_hw_clk_ctrl_source_aware",
        "report (corpus-derived)",
        ".hw_clk_ctrl = true is added on software-looking Qcom RCG source(s) "
        f"({', '.join(hits[:6])}), but the review did not file a [BUG]/[CONCERN]. "
        "The qcom-clock-controller-framework card requires proving the clock is "
        "hardware-triggered with sibling evidence; otherwise update_config() can "
        "timeout waiting for a hardware acknowledgement.",
    )]


def _parent_array_entries(body: str) -> list[str]:
    return [match.group(1) for match in re.finditer(r"\{\s*(P_[A-Za-z0-9_]+)\s*,", body)]


def _parent_data_targets(body: str) -> list[str]:
    targets: list[str] = []
    for item in re.finditer(r"\{\s*(.*?)\s*\}\s*,?", body, re.DOTALL):
        text = item.group(1)
        hw = re.search(r"\.hw\s*=\s*&([A-Za-z_][A-Za-z0-9_]*)\.clkr\.hw", text)
        if hw:
            targets.append(hw.group(1))
        elif ".index" in text or ".fw_name" in text or ".name" in text:
            targets.append("<external>")
        else:
            targets.append("<unknown>")
    return targets


def check_qcom_clock_out_even_parent_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Require a finding when P_*_OUT_EVEN shares the main PLL .hw target."""
    hits: list[str] = []
    for path, source in _iter_qcom_clk_added_sources(patch_corpus):
        parent_maps = {
            name: _parent_array_entries(body)
            for name, body in _iter_c_struct_initializers(source, "parent_map")
        }
        parent_data = {
            name: _parent_data_targets(body)
            for name, body in _iter_c_struct_initializers(source, "clk_parent_data")
        }
        for map_name, parents in parent_maps.items():
            data_name = map_name.replace("parent_map", "parent_data", 1)
            targets = parent_data.get(data_name)
            if not targets:
                continue
            paired = list(zip(parents, targets))
            target_by_parent = {parent: target for parent, target in paired}
            for parent, target in paired:
                if not re.search(r"_OUT_(?:EVEN|ODD|AUX)$", parent):
                    continue
                main_parent = re.sub(r"_OUT_(?:EVEN|ODD|AUX)$", "_OUT_MAIN", parent)
                main_target = target_by_parent.get(main_parent)
                if target != "<external>" and main_target and target == main_target:
                    hits.append(f"{path}:{map_name}/{data_name}:{parent}->{target}")

    if not hits:
        return []
    if _report_has_bug_concern_finding(
        report,
        re.compile(r"OUT_(?:EVEN|ODD|AUX)|postdiv|parent_data", re.IGNORECASE),
        re.compile(r"main PLL|wrong.*rate|divider|postdiv|\.clkr\.hw", re.IGNORECASE),
    ):
        return []
    return [Violation(
        "qcom_clock_out_even_parent_source_aware",
        "report (corpus-derived)",
        "Qcom parent_data maps a divided PLL parent to the same main PLL .hw "
        f"target as OUT_MAIN ({', '.join(hits[:6])}), but the review did not "
        "file a [BUG]/[CONCERN]. The qcom-clock-controller-framework card "
        "requires OUT_EVEN/OUT_ODD/OUT_AUX parents to use a separate postdiv "
        "clock so CCF reports the post-divided rate.",
    )]


def check_qcom_clock_camcc_use_rpm_source_aware(
    report: Report, patch_corpus: str
) -> list[Violation]:
    """Require a finding for new CAMCC qcom_cc_desc blocks missing .use_rpm."""
    hits: list[str] = []
    for path, source in _iter_qcom_clk_added_sources(patch_corpus):
        basename = path.rsplit("/", 1)[-1]
        for name, body in _iter_c_struct_initializers(source, "qcom_cc_desc"):
            is_full_camcc = basename.startswith("camcc-") or name.startswith("cam_cc_")
            if not is_full_camcc:
                continue
            if ".gdscs" not in body or ".num_gdscs" not in body:
                continue
            if re.search(r"\.use_rpm\s*=\s*true", body):
                continue
            hits.append(f"{path}:{name}")

    if not hits:
        return []
    if _report_has_bug_concern_finding(
        report,
        re.compile(r"use_rpm", re.IGNORECASE),
        re.compile(r"runtime PM|RPM|power|abort|unpowered", re.IGNORECASE),
    ):
        return []
    return [Violation(
        "qcom_clock_camcc_use_rpm_source_aware",
        "report (corpus-derived)",
        "new CAMCC qcom_cc_desc with GDSCs omits .use_rpm = true "
        f"({', '.join(hits[:4])}), but the review did not file a [BUG]/[CONCERN]. "
        "The qcom-clock-controller-framework card requires sibling comparison; "
        "without runtime PM enabled before PLL/GDSC register writes, access to an "
        "unpowered block can fault.",
    )]


def _iter_dts_diff_bodies(patch_corpus: str) -> list[tuple[str, str]]:
    diffs: list[tuple[str, str]] = []
    for match in _SOURCE_DIFF_RE.finditer(patch_corpus):
        path = match.group("path")
        if path.endswith((".dts", ".dtsi")):
            diffs.append((path, match.group("body")))
    return diffs


def _source_file_text(source_root: Optional[Path], relpath: str) -> str:
    if not isinstance(source_root, Path):
        return ""
    path = source_root / relpath
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _containing_unit_address(source_text: str, label: str) -> Optional[int]:
    lines = source_text.splitlines()
    target_index = None
    label_re = re.compile(rf"\b{re.escape(label)}\s*:")
    for index, line in enumerate(lines):
        if label_re.search(line):
            target_index = index
            break
    if target_index is None:
        return None

    # Track every node brace, not only unit-addressed nodes.  Otherwise closing
    # braces for non-unit containers (ports/endpoints) desynchronize the stack.
    stack: list[Optional[int]] = []
    node_re = re.compile(
        r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*:\s*)?[A-Za-z0-9,_-]+"
        r"(?:@(?P<addr>[0-9a-fA-F]+))?\s*\{"
    )
    for line in lines[:target_index + 1]:
        stripped = line.strip()
        while stripped.startswith("};") and stack:
            stack.pop()
            stripped = stripped[2:].lstrip()
        match = node_re.match(line)
        if match:
            addr = match.group("addr")
            stack.append(int(addr, 16) if addr is not None else None)

    unit_addrs = [addr for addr in stack if addr is not None]
    if not unit_addrs:
        return None
    # Ignore tiny bus-local unit addresses like port@1.  For a hunk anchored
    # inside mdss_dp0_out, the relevant same-parent sibling anchor is the outer
    # MMIO node (mdss@ae00000), not endpoint/port children.
    mmio_addrs = [addr for addr in unit_addrs if addr >= 0x10000]
    return mmio_addrs[0] if mmio_addrs else unit_addrs[0]


def check_dts_unit_address_insertion_order_source_aware(
    report: Report, patch_corpus: str, source_root: Optional[Path]
) -> list[Violation]:
    """Catch DTS nodes inserted after a higher-address sibling anchor."""
    hits: list[str] = []
    hunk_re = re.compile(r"^@@[^@]*@@\s*(?P<context>.*)$", re.MULTILINE)
    added_node_re = re.compile(
        r"^\+\s*(?:(?P<label>[A-Za-z_][A-Za-z0-9_]*):\s*)?"
        r"[A-Za-z0-9,_-]+@(?P<addr>[0-9a-fA-F]+)\s*\{",
        re.MULTILINE,
    )
    for path, body in _iter_dts_diff_bodies(patch_corpus):
        source_text = _source_file_text(source_root, path)
        if not source_text:
            continue
        hunk_starts = list(hunk_re.finditer(body))
        for idx, hunk in enumerate(hunk_starts):
            context = hunk.group("context")
            label_match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:", context)
            if not label_match:
                continue
            anchor_addr = _containing_unit_address(source_text, label_match.group(1))
            if anchor_addr is None:
                continue
            end = hunk_starts[idx + 1].start() if idx + 1 < len(hunk_starts) else len(body)
            hunk_text = body[hunk.end():end]
            for added in added_node_re.finditer(hunk_text):
                added_addr = int(added.group("addr"), 16)
                if added_addr < anchor_addr:
                    label = added.group("label") or f"@{added.group('addr')}"
                    hits.append(
                        f"{path}:{label}@0x{added_addr:x} inserted after anchor "
                        f"{label_match.group(1)}@0x{anchor_addr:x}"
                    )

    if not hits:
        return []
    if _report_has_bug_concern_finding(
        report,
        re.compile(r"unit-address|node-order|ordering", re.IGNORECASE),
        re.compile(r"DTS|dtsi|address|sorted|order", re.IGNORECASE),
    ):
        return []
    return [Violation(
        "dts_unit_address_insertion_order_source_aware",
        "report (corpus-derived)",
        "DTS diff inserts lower-address unit nodes after a higher-address sibling "
        f"anchor ({', '.join(hits[:6])}), but the review did not file a "
        "[BUG]/[CONCERN]. The dt-dts-ordering-indentation card requires checking "
        "same-parent unit-address order, not only order among the newly added nodes.",
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


# --- Alternate-path state reset: mode-dependent field set on one path while
# an alternate path (TPG, loopback, internal source) can reach the consumer
# without resetting it.
_ALT_PATH_FIELD_ASSIGN_RE = re.compile(
    r"^\+\s*\w+->"
    r"(?:[\w.]*(?:mode|type|sel|phy_cfg|format|config|state))\s*=",
    re.MULTILINE,
)
_ALT_PATH_INDICATOR_RE = re.compile(
    r"\btpg\b|test.?gen|test.?pattern|loopback|internal.?source|"
    r"fallback.?mode|diag(?:nostic)?.?mode|pattern.?gen|\balt.?pad\b|"
    r"tpg_linked",
    re.IGNORECASE,
)
_ALT_PATH_PROOF_RE = re.compile(
    r"alternate.path.*reset|reset.*alternate|"
    r"(?:TPG|test.?pattern|loopback|internal).*(reset|clear|zero|re-?init)|"
    r"(?:reset|clear|zero|re-?init).*(TPG|test.?pattern|loopback|internal)|"
    r"stale.*(?:mode|type|sel|phy|config)|"
    r"(?:mode|type|sel|phy|config).*stale|"
    r"alternate.*path.*guard|guard.*alternate|"
    r"(?:TPG|loopback|internal).*does not.*(?:mode|type|sel|phy)|"
    r"(?:mode|type|sel|phy).*not.*(?:TPG|loopback|internal)",
    re.IGNORECASE,
)


def check_alternate_path_state_reset_source_aware(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path] = None,
) -> list[Violation]:
    """Flag mode-dependent field assignments when an alternate path exists.

    Fires when the diff assigns a mode/type/sel/config enum field AND the
    diff or touched source contains an alternate-path indicator (TPG,
    loopback, testgen, internal source, etc.), but the report does not
    discuss whether the alternate path resets the field or is guarded.
    """
    if not patch_corpus:
        return []
    if not _ALT_PATH_FIELD_ASSIGN_RE.search(patch_corpus):
        return []

    searched_text = _augment_with_source_root(patch_corpus, source_root)
    if not _ALT_PATH_INDICATOR_RE.search(searched_text):
        return []

    visible_all = _visible_report_text(report)
    if _ALT_PATH_PROOF_RE.search(visible_all):
        return []

    return [Violation(
        "alternate_path_state_reset_source_aware",
        "report (corpus-derived)",
        "patch assigns a mode/type/sel/config field on one operational path "
        "while the diff or touched source contains an alternate-path indicator "
        "(TPG, loopback, testgen, internal source), but the report does not "
        "discuss whether the alternate path resets the field or the consumer "
        "is guarded — possible stale mode-dependent hardware programming on "
        "the alternate path",
    )]


# --- Macro arithmetic on unvalidated input: GENMASK(count - 1, 0) where count
# can be 0, or division/shift by a DT-parsed / variant-provided value that
# can be zero without bounds validation.
_GENMASK_MINUS_ONE_RE = re.compile(
    r"GENMASK\s*\([^)]*-\s*1",
)
_DEGENERATE_ZERO_DEFAULT_RE = re.compile(
    r"=\s*0\s*;.*(?:bits_per|per_lane|slot_width|num_|count|channels)",
    re.IGNORECASE,
)
_UNVALIDATED_ARITH_PROOF_RE = re.compile(
    r"validate.*(?:zero|>= *1|> *0)|"
    r"(?:zero|>= *1|> *0).*validate|"
    r"minimum:\s*1|"
    r"if\s*\(\s*!\s*\w+\s*\)|if\s*\(\s*\w+\s*==\s*0|"
    r"GENMASK.*guard|guard.*GENMASK|"
    r"underflow|division by zero|degenerate.*default|"
    r"(?:bits_per|per_lane|slot_width).*(?:check|valid|reject|error)",
    re.IGNORECASE,
)


def check_unvalidated_arithmetic_input_source_aware(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path] = None,
) -> list[Violation]:
    """Flag GENMASK(count-1) or degenerate-zero-default patterns without proof.

    Fires when the diff contains GENMASK(expr - 1, ...) or an explicit
    zero-default for a field used in arithmetic, and the report does not
    discuss bounds validation or the degenerate case.
    """
    if not patch_corpus:
        return []
    has_genmask = bool(_GENMASK_MINUS_ONE_RE.search(patch_corpus))
    has_zero_default = bool(_DEGENERATE_ZERO_DEFAULT_RE.search(patch_corpus))
    if not has_genmask and not has_zero_default:
        return []

    visible_all = _visible_report_text(report)
    if _UNVALIDATED_ARITH_PROOF_RE.search(visible_all):
        return []

    detail = []
    if has_genmask:
        detail.append("GENMASK(count-1, 0) with unvalidated count")
    if has_zero_default:
        detail.append("explicit zero-default for arithmetic operand")
    return [Violation(
        "unvalidated_arithmetic_input_source_aware",
        "report (corpus-derived)",
        f"patch contains {' and '.join(detail)}, but the report does not "
        "discuss whether the degenerate value (zero) is reachable and what "
        "happens when it reaches the macro/arithmetic — possible undefined "
        "behaviour, division by zero, or hardware misconfiguration",
    )]


# --- Branch-precedence / condition-widening diversion: a patch widens a branch
# guard with a new `||` disjunct AND reorders an if/else-if chain so an input
# that used to fall to a later, side-effectful arm is now captured by an earlier
# arm that omits that side effect (PHY/power init, lock, state flag, setup).
# Gate-1 is a hunk-local reorder signature, deliberately narrow: within one hunk
# the diff must (a) add an OR-widened branch guard, AND (b) remove a plain `if`
# guard whose condition reappears as an added `else if` (the branch moved down).
# This is the precise widen+reorder shape; plain new conditions do not fire.
_BRANCH_ADD_WIDENED_RE = re.compile(
    r"^\+\s*\}?\s*(?:else\s+)?if\s*\(.*\|\|",
    re.MULTILINE,
)
_BRANCH_REMOVED_IF_RE = re.compile(
    r"^-\s*\}?\s*if\s*\((.*?)\)?\s*\{?\s*$",
)
_BRANCH_ADDED_ELSEIF_RE = re.compile(
    r"^\+\s*\}?\s*else\s+if\s*\((.*?)\)?\s*\{?\s*$",
)
# Proof requires the harm chain itself, not generic branch vocabulary. A weak
# two-concept co-occurrence (e.g. the word "reorder" near "pm_runtime") is NOT
# enough — the wrong dismissal ("reordering is correct, both paths route
# correctly, prioritizes IRQ before replug") contains those words without ever
# tracing the diverted input. The harm-chain clear demands one of: (a) the
# bypassed setup named together with skip/never/without/still-runs; (b) a
# concrete consequence (-ENXIO, a state flag left false); or (c) the diverted
# input class analysed (initial/fresh/first connect carrying the new flag).
# A separate mutual-exclusivity path (d) clears only when it also names the NEW
# disjunct's operand. The wrong-dismissal shapes ("takes priority", "mutually
# exclusive return values", "correctly handled", "logically correct",
# "independent paths") satisfy none of these.
_BRANCH_PROOF_RE = re.compile(
    # (b) concrete consequence of the skipped setup
    r"-ENXIO|"
    r"\b\w*plugged\b[^.\n]{0,30}?(?:stays?|remains?|left|is|never|not)\s*"
    r"(?:false|unset|cleared|0\b)|"
    r"(?:stays?|remains?|left|never set|not set|uninitiali)\w*[^.\n]{0,20}?"
    r"\b\w*plugged\b|"
    # (a) bypassed setup named together with skip/never/without/still-runs
    r"(?:never|not|skip\w*|without|bypass\w*|fails? to|no longer)\s+\w*\s*"
    r"(?:call\w*\s+)?(?:\w*plug_handle|phy[ _-]?init|host_phy_init|hpd_plug)|"
    r"(?:\w*plug_handle|phy[ _-]?init|host_phy_init|hpd_plug)\b[^.\n]{0,60}?"
    r"(?:never|not\s+(?:run|call)|skip\w*|without|bypass\w*|still\s+"
    r"(?:run|happen|call)|also\s+(?:run|call))|"
    # (c) the diverted input class analysed (connect carrying the new flag)
    r"(?:initial|fresh|first)\s+connect[^.\n]{0,80}?"
    r"(?:irq|extra_status|skip|bypass|plug|phy|flag)",
    re.IGNORECASE,
)
# (d) a mutual-exclusivity producer — clears only when it also names the NEW
# disjunct operand (handled in the check body), so an "old values are mutually
# exclusive" dismissal that ignores the OR-ed flag does not clear.
_BRANCH_MUTEX_PRODUCER_RE = re.compile(
    r"mutually exclusive[^.\n]{0,60}?(?:because|since|set by|only set|"
    r"caller|firmware sets|cannot both|hardware only)|"
    r"(?:provably|proven)\s+(?:mutually\s+)?exclusive|"
    r"flag is only (?:ever )?set",
    re.IGNORECASE,
)


def _norm_cond(text: str) -> str:
    """Strip whitespace from a guard condition for cross-arm comparison."""
    return re.sub(r"\s+", "", text)[:60]


def _iter_diff_hunks(corpus: str):
    """Yield each unified-diff hunk (``@@`` header + body lines) in *corpus*."""
    cur: list[str] | None = None
    for line in corpus.splitlines():
        if line.startswith("@@"):
            if cur:
                yield "\n".join(cur)
            cur = [line]
        elif cur is not None:
            cur.append(line)
    if cur:
        yield "\n".join(cur)


def _has_branch_reorder_signature(corpus: str) -> bool:
    """True when a hunk both OR-widens a guard and moves a plain ``if`` down.

    The reorder is detected structurally: a plain ``if`` guard removed in the
    hunk has its condition reappear as an added ``else if`` (so the branch was
    pushed below a newly-inserted earlier arm), and the hunk also adds an
    ``||``-widened guard. This is the condition-widening + reorder shape.
    """
    for hunk in _iter_diff_hunks(corpus):
        if not _BRANCH_ADD_WIDENED_RE.search(hunk):
            continue
        removed = set()
        added_elseif = set()
        for line in hunk.splitlines():
            m = _BRANCH_REMOVED_IF_RE.match(line)
            if m and m.group(1).strip():
                removed.add(_norm_cond(m.group(1)))
            m = _BRANCH_ADDED_ELSEIF_RE.match(line)
            if m and m.group(1).strip():
                added_elseif.add(_norm_cond(m.group(1)))
        if removed & added_elseif:
            return True
    return False


# Identifiers introduced by the new ``||`` disjunct, excluding the operands that
# already existed in the moved-down arm. A mutual-exclusivity dismissal must
# name at least one of these to be about the NEW disjunct rather than the old
# branch values.
_BRANCH_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Operators/keywords that are never the distinguishing operand of a disjunct.
_BRANCH_IDENT_STOPWORDS = frozenset({
    "if", "else", "return", "case", "switch", "while", "for", "do",
})


def _branch_new_disjunct_tokens(corpus: str) -> set[str]:
    """Return identifiers unique to the newly-added ``||``-widened guard.

    For each reorder hunk, collect identifiers across the whole added widened
    guard expression (the ``+`` line that opens ``if (... ||`` plus its added
    continuation lines up to the arm-opening ``{``) and subtract identifiers
    that already appear in a removed/moved guard arm. The remainder is the
    operand(s) the disjunct newly introduces — e.g. ``extra_status`` /
    ``DRM_CONNECTOR_DP_IRQ_HPD`` — which a genuine mutual-exclusivity proof
    must reference. Multi-line guards are handled: the widened condition often
    wraps, so the distinguishing operand sits on a continuation line.
    """
    tokens: set[str] = set()
    for hunk in _iter_diff_hunks(corpus):
        lines = hunk.splitlines()
        widened: set[str] = set()
        pre_existing: set[str] = set()
        i = 0
        while i < len(lines):
            line = lines[i]
            # Operands present in removed lines or in any added non-widened
            # guard arm (the moved-down else-if) already existed before.
            if line.startswith("-") or _BRANCH_ADDED_ELSEIF_RE.match(line):
                pre_existing.update(
                    t for t in _BRANCH_IDENT_RE.findall(line)
                    if t not in _BRANCH_IDENT_STOPWORDS
                )
            if _BRANCH_ADD_WIDENED_RE.match(line):
                # Gather the full added guard expression, including added
                # continuation lines, until the arm-opening brace.
                widened.update(
                    t for t in _BRANCH_IDENT_RE.findall(line)
                    if t not in _BRANCH_IDENT_STOPWORDS
                )
                while "{" not in line and i + 1 < len(lines) and lines[i + 1].startswith("+"):
                    i += 1
                    line = lines[i]
                    widened.update(
                        t for t in _BRANCH_IDENT_RE.findall(line)
                        if t not in _BRANCH_IDENT_STOPWORDS
                    )
            i += 1
        if widened:
            tokens |= widened - pre_existing
    return tokens


def check_branch_precedence_regression_source_aware(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path] = None,
) -> list[Violation]:
    """Flag a widened+reordered branch guard without diversion analysis.

    Fires on the hunk-local reorder signature (an OR-widened guard added while a
    plain ``if`` guard is moved down to an ``else if``), when the report does
    not show it traced which input now lands in an earlier arm and whether the
    bypassed arm's side effect (init/lock/flag/setup) is still performed.

    Cleared by the harm chain itself (the bypassed setup named with skip/never/
    without, a concrete consequence like -ENXIO or a state flag left false, or
    the diverted input class analysed) or by a mutual-exclusivity producer that
    actually references the NEW disjunct's operand. Not cleared by "takes
    priority" / "mutually exclusive return values" / "correctly handled" /
    "independent paths" surface language, and not by a mutual-exclusivity claim
    that only covers the pre-existing branch values while ignoring the OR-ed
    flag.
    """
    if not patch_corpus:
        return []
    if not _has_branch_reorder_signature(patch_corpus):
        return []

    visible_all = _visible_report_text(report)
    if _BRANCH_PROOF_RE.search(visible_all):
        return []
    if _BRANCH_MUTEX_PRODUCER_RE.search(visible_all):
        # A mutual-exclusivity dismissal only clears when it is about the NEW
        # disjunct, not the old branch values. Require the proof to name at
        # least one operand the widened guard newly introduced. If the diff
        # exposes no distinguishing new token (degenerate parse), fall back to
        # the prior permissive behaviour rather than over-firing.
        new_tokens = _branch_new_disjunct_tokens(patch_corpus)
        if not new_tokens:
            return []
        if any(tok in visible_all for tok in new_tokens):
            return []

    return [Violation(
        "branch_precedence_regression_source_aware",
        "report (corpus-derived)",
        "patch widens a branch guard with a new `||` disjunct and reorders an "
        "if/else-if chain, so an input that previously fell to a later arm may "
        "now be captured by an earlier arm; the report does not trace which "
        "input changes arms or prove the bypassed arm's side effect "
        "(PHY/power init, lock acquisition, state flag, resource setup) is "
        "still performed — possible skipped initialization, unlocked shared "
        "state, or a functionally-wrong handler for the diverted input",
    )]


# --- Branch-diversion producer coupling (source-aware factual refutation):
# the branch_precedence check above can be cleared by a *well-shaped but false*
# mutual-exclusivity dismissal — e.g. "the new flag is only set for genuine IRQ
# events, never together with a fresh connect". That claim is a statement of
# fact about the PRODUCER that sets the flag, and a text regex cannot judge its
# truth. This check refutes it from source: if the producer parses the
# connect-status field and the diverted-flag field as INDEPENDENT values from
# one notification (two FIELD_GET of distinct state/irq masks from the same
# word, or two adjacent `:1` bitfields), the two CAN co-occur, so the dangerous
# combination is reachable and a finding must be filed regardless of the
# dismissal's wording. Grounded in source fact + did-you-file, not proof-language.
_PRODUCER_FIELD_GET_RE = re.compile(
    r"FIELD_GET\(\s*([A-Za-z0-9_]+)\s*,\s*([A-Za-z0-9_>.\-]+)\s*\)",
)
_PRODUCER_BITFIELD_RE = re.compile(
    r"\b([a-z0-9_]+)\s*:\s*1\s*;",
    re.IGNORECASE,
)
_PRODUCER_STATE_CONCEPT_RE = re.compile(r"STATE|PLUG|CONN|PRESENT|HOTPLUG", re.IGNORECASE)
_PRODUCER_IRQ_CONCEPT_RE = re.compile(r"IRQ|EVENT|ATTENTION|SERVICE", re.IGNORECASE)
# The report files a real finding about this diversion when a BUG/CONCERN card
# names a generic diversion concept on the widened/reordered chain — the
# diverted input class, the bypassed arm's setup that the taken arm omits, the
# control-flow change itself, or a concrete failure-mode keyword. Subsystem
# vocabulary (specific helper names, specific flags) is not required: any of
# these generic concepts in a counted finding satisfies the source-aware
# refutation.
_DIVERSION_FINDING_RE = re.compile(
    r"\[(?:BUG|CONCERN)\][^\[]{0,400}?(?:"
    r"diverted|divert\w*|"
    r"bypass\w*|"
    r"widen\w*|"
    r"reorder\w*|"
    r"branch[- ]precedence|"
    r"earlier (?:branch|arm)|first branch|"
    r"new disjunct|OR-?ed|short-?circuit|"
    r"(?:never|not)\s+(?:run|call\w*|reach\w*|init\w*)|"
    r"skips? the|skipped\s+(?:plug|init|setup|lock|unplug|connect|alloc)|"
    r"captured by|lands? in|steals? the|"
    r"falls? through|fall-through|"
    r"undefined behaviour|undefined behavior|"
    r"-ENXIO|deref|null deref|use-after|UAF|"
    r"initial connect|fresh connect|"
    r"missing\s+(?:init|setup|lock|guard))",
    re.IGNORECASE | re.DOTALL,
)


def _producer_has_independent_status_event_fields(searched_text: str) -> bool:
    """True when the producer parses connect-status and event/irq as independent.

    Two structural signatures, either sufficient:
      * two ``FIELD_GET(mask, word)`` calls from the SAME source word, one mask
        naming a state/connect concept and another naming an irq/event concept
        — independent bits of one notification register; or
      * two ``:1`` bitfields whose names carry the two concepts — independent
        single-bit flags in one struct.
    """
    by_word: dict[str, list[str]] = {}
    for m in _PRODUCER_FIELD_GET_RE.finditer(searched_text):
        mask, word = m.group(1), m.group(2)
        by_word.setdefault(word, []).append(mask)
    for masks in by_word.values():
        has_state = any(
            _PRODUCER_STATE_CONCEPT_RE.search(x)
            and not _PRODUCER_IRQ_CONCEPT_RE.search(x)
            for x in masks
        )
        has_irq = any(_PRODUCER_IRQ_CONCEPT_RE.search(x) for x in masks)
        if has_state and has_irq:
            return True

    names = [m.group(1) for m in _PRODUCER_BITFIELD_RE.finditer(searched_text)]
    has_state_bf = any(
        _PRODUCER_STATE_CONCEPT_RE.search(n) and not _PRODUCER_IRQ_CONCEPT_RE.search(n)
        for n in names
    )
    has_irq_bf = any(_PRODUCER_IRQ_CONCEPT_RE.search(n) for n in names)
    return has_state_bf and has_irq_bf


def check_branch_diversion_producer_coupling_source_aware(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path] = None,
) -> list[Violation]:
    """Refute a false mutual-exclusivity dismissal of a branch-diversion bug.

    Fires when (1) the branch-reorder signature is present, (2) the producer
    source proves the connect-status field and the diverted-flag field are
    independent (so the dangerous combination is reachable), and (3) the report
    does NOT file a BUG/CONCERN finding about the diversion — i.e. it cleared
    the hazard by claiming the two cannot co-occur, which the source refutes.

    Unlike the text-only branch_precedence check, this cannot be satisfied by
    well-worded prose: the clear requires an actual filed finding, and the
    trigger requires source evidence of independence.
    """
    if not patch_corpus:
        return []
    if not _has_branch_reorder_signature(patch_corpus):
        return []

    searched_text = _augment_with_source_root(patch_corpus, source_root)
    if not _producer_has_independent_status_event_fields(searched_text):
        return []

    visible_all = _visible_report_text(report)
    if _DIVERSION_FINDING_RE.search(visible_all):
        return []

    return [Violation(
        "branch_diversion_producer_coupling_source_aware",
        "report (corpus-derived + source)",
        "patch reorders a branch chain so a connect event carrying the new flag "
        "is diverted to an earlier arm, and the producer parses the "
        "connect-status field and the flag as INDEPENDENT bits of one "
        "notification (distinct FIELD_GET masks / separate `:1` bitfields) — so "
        "the two CAN co-occur and the dangerous combination is reachable; the "
        "report cleared the hazard without filing a finding, which the producer "
        "source refutes. A 'the flag is only set for genuine events, never with "
        "a fresh connect' dismissal is disqualified: name the producer line that "
        "couples the two fields, or file the diversion finding",
    )]


# --- Read-path widening of a writer-locked pointer: the patch widens an
# `if (ctx->FIELD)` block to add new dereferences of the same field, while a
# sibling teardown function (HPD/work/IRQ/timer/disconnect) frees the field
# under a lock the read-path function does not acquire. The widened block
# extends the deref window across helpers that the original code did not call,
# so a pre-existing race becomes newly observable after the patch. Detection
# is hunk-local (widening) plus source-aware (writer + lock asymmetry).
_RW_REMOVED_BARE_IF_RE = re.compile(
    r"^-\s*if\s*\(\s*([A-Za-z_][\w>.\-]*)\s*\)\s*$",
    re.MULTILINE,
)
_RW_ADDED_OPEN_IF_RE = re.compile(
    r"^\+\s*if\s*\(\s*([A-Za-z_][\w>.\-]*)\s*\)\s*\{\s*$",
    re.MULTILINE,
)
_RW_LOCK_RE = re.compile(
    r"\bguard\s*\(\s*mutex\s*\)\s*\(|"
    r"\bmutex_lock(_interruptible|_killable|_nested)?\s*\(|"
    r"\bspin_lock(_irq|_irqsave|_bh)?\s*\(|"
    r"\bdown(_read|_write|_interruptible)?\s*\(|"
    r"\brcu_read_lock\s*\(",
)


def _rw_lvalue_tail(lvalue: str) -> str:
    """Return the trailing identifier of a struct-deref lvalue (``a->b->c`` -> ``c``)."""
    return lvalue.split("->")[-1].split(".")[-1]


def _rw_added_uses_inside_block(corpus: str, lvalue: str) -> int:
    """Count added (`+`) lines that re-use the lvalue's tail token.

    Excludes the opening ``if (...) {`` line itself. A widening adds at least
    one new use; the original ``if (X)`` was a single test followed by one
    statement.
    """
    tail = _rw_lvalue_tail(lvalue)
    count = 0
    for line in corpus.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if _RW_ADDED_OPEN_IF_RE.match(line):
            continue
        if tail and tail in line:
            count += 1
    return count


def _rw_extract_function_body(text: str, fn_name: str) -> str:
    """Return the body of ``fn_name`` from a C source blob (best-effort).

    Matches a top-level definition ``... fn_name(...)\\n{ ... \\n}\\n`` using
    the first balanced top-level closing brace. Returns ``""`` if not found.
    """
    pat = re.compile(
        r"(?ms)^[A-Za-z_][\w \*\t]*\b" + re.escape(fn_name) + r"\s*\([^)]*\)\s*\n\{.*?\n\}\n"
    )
    m = pat.search(text)
    return m.group(0) if m else ""


def _rw_writer_functions_with_field(searched_text: str, field_tail: str) -> list[str]:
    """Find all functions that call a free-helper on ``->field_tail`` or null it.

    A struct field is often freed in multiple places: the same function that
    owns it may free-and-reread (same-thread), while a separate teardown
    function frees it concurrently from an HPD/work/IRQ path. Return every
    candidate so the caller can check writer-side locking on each.

    The free helper is recognised by its NAMING convention, not an enumerated
    allow-list — any identifier whose name signals release (``kfree*``,
    ``vfree``, ``kvfree``, ``*_free``, ``*_put``, ``put_*``, ``free_*``,
    ``release_*``, ``*_release``, ``*_destroy``, ``destroy_*``, ``devm_kfree``,
    ``dma_free_*``) called with an argument that dereferences ``->field_tail``,
    or an explicit ``->field_tail = NULL`` assignment, qualifies.
    """
    free_pat = re.compile(
        r"\b(?:"
        r"kfree\w*|kvfree|vfree|"
        r"\w*_free|free_\w+|"
        r"\w*_put|put_\w+|"
        r"\w*_release|release_\w+|"
        r"\w*_destroy|destroy_\w+|"
        r"devm_kfree|dma_free_\w+"
        r")\s*\([^;)]*->\s*"
        + re.escape(field_tail)
        + r"\b"
    )
    null_pat = re.compile(r"->\s*" + re.escape(field_tail) + r"\s*=\s*NULL\s*;")
    bodies: list[str] = []
    for fn_match in re.finditer(
        r"(?ms)^([A-Za-z_][\w\* \t]*\b(\w+))\s*\([^)]*\)\s*\n\{(.*?)\n\}\n",
        searched_text,
    ):
        body = fn_match.group(0)
        if free_pat.search(body) or null_pat.search(body):
            bodies.append(body)
    return bodies


def _rw_writer_has_locked_caller(writer_name: str, searched_text: str) -> bool:
    """True when ``writer_name`` is called and a lock is acquired in the ~400
    characters immediately preceding the call site."""
    for call in re.finditer(r"\b" + re.escape(writer_name) + r"\s*\(", searched_text):
        back = searched_text[max(0, call.start() - 400) : call.start()]
        if _RW_LOCK_RE.search(back):
            return True
    return False


def _rw_writer_has_locked_caller_in_tree(
    writer_name: str,
    source_root: Path,
    patched_paths: list[str],
) -> bool:
    """Scan .c files near ``patched_paths`` under ``source_root`` for a
    lock-preceded call of ``writer_name``.

    Augmentation only loads files the patch corpus mentions; a typical writer
    (``msm_dp_panel_unplugged``) lives in one .c file but is called under a
    guard/mutex from a sibling file (``dp_display.c``). Scan restricts to the
    immediate directories of patched files plus their parent directory's .c
    files — almost always covers the call site without walking the kernel.
    Capped at 256 files for safety.
    """
    if not isinstance(source_root, Path) or not source_root.is_dir():
        return False
    call_re = re.compile(r"\b" + re.escape(writer_name) + r"\s*\(")
    candidates: list[Path] = []
    seen_dirs: set[Path] = set()
    for relpath in patched_paths:
        patch_file = source_root / relpath
        for d in (patch_file.parent, patch_file.parent.parent):
            if d in seen_dirs or not d.is_dir():
                continue
            seen_dirs.add(d)
            try:
                for entry in d.iterdir():
                    if entry.is_file() and entry.suffix == ".c":
                        candidates.append(entry)
            except OSError:
                continue
    if not candidates:
        return False
    candidates = candidates[:256]
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if writer_name not in text:
            continue
        for call in call_re.finditer(text):
            back = text[max(0, call.start() - 400) : call.start()]
            if _RW_LOCK_RE.search(back):
                return True
    return False


def check_readpath_widening_writer_locked_source_aware(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path] = None,
) -> list[Violation]:
    """Flag a widened `if (ptr)` deref window when the writer frees under a lock.

    Fires when the diff widens an existing ``if (X->FIELD)`` test into a
    multi-statement block adding new dereferences of the same field, AND the
    augmented source contains a function that frees ``->FIELD`` (kfree /
    drm_edid_free / put_device / etc.) under a mutex/spinlock/RCU lock that
    the read-path function does not acquire, AND the report does not file a
    BUG/CONCERN finding naming the writer or a lifetime/lock-asymmetry concern.

    Cleared by an actual filed finding, or by source evidence that the read
    function itself (or all its callers) holds the same lock — both checked
    against the augmented source, not against report prose.
    """
    if not patch_corpus:
        return []

    removed = set(_RW_REMOVED_BARE_IF_RE.findall(patch_corpus))
    added = set(_RW_ADDED_OPEN_IF_RE.findall(patch_corpus))
    widened = removed & added
    if not widened:
        return []

    # Require at least one added new use of the same field's tail token.
    field = next(iter(widened))
    if _rw_added_uses_inside_block(patch_corpus, field) < 1:
        return []

    field_tail = _rw_lvalue_tail(field)
    searched_text = _augment_with_source_root(patch_corpus, source_root)

    # The READ function is the one whose @@-hunk contains the widened `if`.
    # The diff hunk header carries the enclosing function signature directly.
    reader_name = ""
    for m in re.finditer(r"^@@[^@]+@@\s*([^\n]+)", patch_corpus, re.MULTILINE):
        ctx = m.group(1)
        sig = re.search(r"\b(\w+)\s*\(", ctx)
        if sig:
            reader_name = sig.group(1)
            break
    if not reader_name:
        return []

    reader_body = _rw_extract_function_body(searched_text, reader_name)
    # When the reader body is found in source, require it has no lock — if it
    # does, the asymmetry claim is moot. When the body is not in source (e.g.
    # synthetic test corpora, files outside source_root), fall back to checking
    # only the patch's added lines for a lock that the diff itself introduces;
    # context lines from neighbouring hunks must not be conflated.
    if reader_body:
        if _RW_LOCK_RE.search(reader_body):
            return []
    else:
        added_lines = "\n".join(
            ln[1:] for ln in patch_corpus.splitlines()
            if ln.startswith("+") and not ln.startswith("+++")
        )
        if _RW_LOCK_RE.search(added_lines):
            return []

    # Collect every writer function that frees ->field_tail. At least one of
    # them must be a CONCURRENT writer — i.e., NOT the reader itself, AND
    # reach the free under a lock (in its own body or its callers' bodies).
    writers = _rw_writer_functions_with_field(searched_text, field_tail)
    concurrent_locked_writer = False
    for writer_body in writers:
        head = re.match(r"(?ms)^[A-Za-z_][\w\* \t]*\b(\w+)\s*\(", writer_body)
        writer_name = head.group(1) if head else ""
        if not writer_name or writer_name == reader_name:
            continue
        if _RW_LOCK_RE.search(writer_body):
            concurrent_locked_writer = True
            break
        # Look at callers: a lock acquired in the ~400 chars before any call
        # of the writer is the typical pattern (e.g. an HPD handler takes the
        # lock then calls the writer). Check the augmented text first; if the
        # writer is called from another file under source_root, scan that too.
        if _rw_writer_has_locked_caller(writer_name, searched_text):
            concurrent_locked_writer = True
            break
        if source_root is not None and _rw_writer_has_locked_caller_in_tree(
            writer_name, source_root, _source_files_from_patch_corpus(patch_corpus)
        ):
            concurrent_locked_writer = True
            break
    if not concurrent_locked_writer:
        return []

    # Cleared if the report files a real finding about lifetime / locking /
    # UAF / free of the same field.
    finding_re = re.compile(
        r"\[(?:BUG|CONCERN)\][^\[]{0,500}?(?:"
        r"use[- ]after[- ]free|UAF|race|concurren|lock|mutex|"
        r"freed?|lifetime|" + re.escape(field_tail) + r")",
        re.IGNORECASE | re.DOTALL,
    )
    visible_all = _visible_report_text(report)
    if finding_re.search(visible_all):
        return []

    return [Violation(
        "readpath_widening_writer_locked_source_aware",
        "report (corpus-derived + source)",
        "patch widens an `if (ptr)` block to add new dereferences of a struct "
        "field whose writer frees the same field under a mutex/spinlock/RCU "
        "lock the read-path function does not acquire — concurrent UAF risk "
        "newly widened by the longer deref window; the report did not file a "
        "BUG/CONCERN naming the writer's free site or the lock asymmetry. "
        "Name the writer's free line and the lock it holds, or quote a "
        "lifetime guarantee (refcount, RCU, suppress_bind_attrs, all callers "
        "lock) on the field — pattern-alignment / API-correctness arguments "
        "do not establish lifetime",
    )]


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
    parts: list[str] = []
    if tests_path and tests_path.exists():
        parts.append(tests_path.read_text(encoding="utf-8", errors="replace"))
    if html:
        match = re.search(
            r"Build[^<]*</td>\s*<td[^>]*>\s*<span[^>]*>([A-Z]+)</span>",
            html,
        )
        if match:
            parts.append(f"Build: {match.group(1)}")
    return "\n".join(part for part in parts if part)


def _print_violations(
    name: str, violations: list[Violation], output_format: str = "human"
) -> int:
    by_check: dict[str, list[Violation]] = {}
    for violation in violations:
        by_check.setdefault(violation.check, []).append(violation)

    if output_format == "json":
        payload = {
            "result": "FAIL",
            "name": name,
            "violation_count": len(violations),
            "failed_checks": sorted(by_check),
            "violations": [
                {
                    "check": v.check,
                    "where": v.where,
                    "message": v.message,
                    "fix": (remediation_for(v.check) or {}).get("fix", ""),
                    "ref": (remediation_for(v.check) or {}).get("ref", ""),
                }
                for v in violations
            ],
            "remediation": [
                {
                    "check": check,
                    "count": len(items),
                    "fix": (remediation_for(check) or {}).get("fix", ""),
                    "ref": (remediation_for(check) or {}).get("ref", ""),
                }
                for check, items in sorted(by_check.items())
            ],
        }
        print(json.dumps(payload, indent=2))
        return 1

    print(f"FAIL: {name} — {len(violations)} violations:")
    for check, items in by_check.items():
        print(f"\n[{check}] ({len(items)} violations)")
        for violation in items[:30]:
            print(violation)
        if len(items) > 30:
            print(f"  ... and {len(items) - 30} more")
        remedy = remediation_for(check)
        if remedy:
            print(f"  → fix: {remedy['fix']}")
            print(f"  → ref: {remedy['ref']}")
    return 1


def _load_patch_file(path: Optional[Path]) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _load_runtime_config(runtime_config: Path) -> tuple[Optional[dict[str, object]], list[Violation]]:
    if not runtime_config.exists():
        return None, [Violation(
            "runtime_override_artifact",
            str(runtime_config),
            "runtime config artifact is referenced but does not exist",
        )]
    try:
        payload = json.loads(runtime_config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [Violation(
            "runtime_override_artifact",
            str(runtime_config),
            f"runtime config artifact is not valid JSON: {exc}",
        )]
    violations: list[Violation] = []
    if payload.get("schema") != _RUNTIME_CONFIG_SCHEMA:
        violations.append(Violation(
            "runtime_override_artifact",
            str(runtime_config),
            f"runtime config schema must be {_RUNTIME_CONFIG_SCHEMA!r}, got {payload.get('schema')!r}",
        ))
    if not isinstance(payload.get("sparse_check"), bool):
        violations.append(Violation(
            "runtime_override_artifact",
            str(runtime_config),
            "runtime config sparse_check must be a boolean",
        ))
    dt_check_jobs = payload.get("dt_check_jobs", 64)
    if not isinstance(dt_check_jobs, int) or isinstance(dt_check_jobs, bool) or dt_check_jobs < 1:
        violations.append(Violation(
            "runtime_override_artifact",
            str(runtime_config),
            "runtime config dt_check_jobs must be an integer >= 1",
        ))
    packet_mode = payload.get("review_packet_mode", _DEFAULT_REVIEW_PACKET_MODE)
    if packet_mode != _DEFAULT_REVIEW_PACKET_MODE:
        violations.append(Violation(
            "runtime_override_artifact",
            str(runtime_config),
            "runtime config review_packet_mode is packet-only; got "
            f"{packet_mode!r}",
        ))
    if violations:
        return None, violations
    return payload, []



def check_prompt_file(
    *,
    prompt_file: Optional[Path],
    block_file: Path,
    patch_number: int,
    tests_path: Optional[Path],
    build_file: Optional[Path],
    evidence_file: Optional[Path],
    runtime_config: Optional[Path],
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
    try:
        if prompt_file.stat().st_mtime > block_file.stat().st_mtime:
            violations.append(Violation(
                "prompt_artifact",
                str(prompt_file),
                "per-patch prompt is newer than the block file; prompt must be "
                "generated and saved before patch review/block creation",
            ))
    except OSError:
        violations.append(Violation(
            "prompt_artifact",
            str(prompt_file),
            "could not stat prompt/block files to verify prompt-before-block ordering",
        ))
    expected_artifact = f"patch_{patch_number}_review_packet.md"
    expected_kind = "review packet"
    if not (first_nonblank.startswith("Read ") and expected_artifact in first_nonblank):
        violations.append(Violation(
            "prompt_artifact",
            str(prompt_file),
            "first non-empty prompt line must read the matching "
            f"`{expected_artifact}` {expected_kind}",
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
    if runtime_config is not None:
        required_fragments.extend(["Runtime config:", str(runtime_config), runtime_config.name])
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


_PACKET_GENERATED_MARKER = "Generated by scripts/assemble_review_packet.py"
_PACKET_REQUIRED_MARKERS = (
    "<!-- BEGIN packet-metadata -->",
    "<!-- BEGIN reviewer-base -->",
    "<!-- BEGIN output-format-mini -->",
    "<!-- BEGIN focused-review-obligations -->",
    "<!-- BEGIN focused-rule-evidence -->",
    "<!-- BEGIN context-coverage -->",
    "<!-- BEGIN selected-rule-cards -->",
    "<!-- BEGIN patch-diff -->",
)


def check_packet_file(
    *,
    packet_file: Optional[Path],
    patch_number: int,
) -> list[Violation]:
    """Validate the mandatory compact per-patch review packet."""
    if packet_file is None:
        return [Violation(
            "packet_artifact",
            f"patch_{patch_number}_review_packet.md",
            "per-patch review packet is required for packet-only block validation",
        )]
    if not packet_file.exists():
        return [Violation(
            "packet_artifact",
            str(packet_file),
            f"per-patch review packet patch_{patch_number}_review_packet.md is referenced "
            "but does not exist in <project_path>/tmp",
        )]
    text = packet_file.read_text(encoding="utf-8", errors="replace")
    missing = [
        marker for marker in (_PACKET_GENERATED_MARKER, *_PACKET_REQUIRED_MARKERS)
        if marker not in text
    ]
    if missing:
        return [Violation(
            "packet_artifact",
            str(packet_file),
            "per-patch review packet is present but incomplete; missing marker(s): "
            + ", ".join(missing),
        )]
    return []


# Map rule card IDs to their mandatory attestation record markers.
# Only cards with explicit "## Mandatory Attestation Record" sections are listed.
# The marker is a substring that MUST appear in the block's raw_html when the card
# fires.  The validator checks the block for any of the listed markers.
_RULE_CARD_ATTESTATION_MARKERS: dict[str, tuple[str, ...]] = {
    "qcom-clock-controller-framework": (
        "qcom_clock_audit:",
        "parent_data_distinct:",
        "desc_sibling_compare:",
        "hw_clk_ctrl_check:",
        "use_rpm_check:",
    ),
    "runtime-pm-bracket-safety": (
        "pm_bracket_audit:",
    ),
    "dt-old-dtb-compatibility": (
        "old_dtb_audit:",
    ),
    "resource-acquire-release-symmetry": (
        "resource_symmetry_audit:",
    ),
    "register-field-access": (
        "register_field_audit:",
    ),
    "dt-dts-ordering-indentation": (
        "node-ordering:",
    ),
    "shared-scratch-serialization": (
        "scratch_serialization_audit:",
    ),
    "dt-binding-schema-basics": (
        "required_per_compatible_audit:",
    ),
}

# Some cards fire for multiple reasons but only need the attestation when a
# specific diff shape is present.  Map card_id -> regex; the attestation
# requirement is enforced only if the regex matches at least one of the
# patch diffs in the packet.  Cards absent from this map have unconditional
# attestation.
_RULE_CARD_ATTESTATION_PREDICATE: dict[str, re.Pattern[str]] = {
    "dt-binding-schema-basics": re.compile(
        r"(?m)^\+\s+-\s+['\"]?#[a-z][a-z0-9-]*-cells['\"]?\s*$"
    ),
}

_RULE_CARD_COVERAGE_SECTION_RE = re.compile(
    r"<h3>\s*Rule Card Coverage\s*</h3>(.*?)(?=<h3\b|</div><!-- /commit-block -->|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _packet_rule_card_ids(packet_json_path: Optional[Path]) -> list[str]:
    if packet_json_path is None or not packet_json_path.exists():
        return []
    try:
        packet_meta = json.loads(
            packet_json_path.read_text(encoding="utf-8", errors="replace")
        )
    except (json.JSONDecodeError, OSError):
        return []
    fired_cards = packet_meta.get("rule_cards", [])
    if not isinstance(fired_cards, list):
        return []
    card_ids: list[str] = []
    seen: set[str] = set()
    for card in fired_cards:
        card_id = card.get("id") if isinstance(card, dict) else card
        if isinstance(card_id, str) and card_id and card_id not in seen:
            seen.add(card_id)
            card_ids.append(card_id)
    return card_ids


def _packet_focused_obligations(packet_json_path: Optional[Path]) -> list[dict[str, str]]:
    if packet_json_path is None or not packet_json_path.exists():
        return []
    try:
        packet_meta = json.loads(
            packet_json_path.read_text(encoding="utf-8", errors="replace")
        )
    except (json.JSONDecodeError, OSError):
        return []
    raw_obligations = packet_meta.get("focused_review_obligations", [])
    if not isinstance(raw_obligations, list):
        return []
    obligations: list[dict[str, str]] = []
    for item in raw_obligations:
        if not isinstance(item, dict):
            continue
        obligation_id = item.get("id")
        card_id = item.get("card")
        if isinstance(obligation_id, str) and obligation_id and isinstance(card_id, str) and card_id:
            obligations.append({"id": obligation_id, "card": card_id})
    return obligations


def _contains_card_id(text: str, card_id: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9_-]){re.escape(card_id)}(?![A-Za-z0-9_-])", text))


def check_rule_card_attestation(
    report: Report,
    packet_json_path: Optional[Path],
    patch_corpus: str = "",
) -> list[Violation]:
    """Enforce mandatory attestation records for fired rule cards.

    When a rule card with a mandatory attestation section fires (listed in
    the packet JSON's rule_cards), the corresponding block MUST contain the
    attestation record markers.  Without this enforcement, subagents can
    ignore the attestation requirement and self-audit as PASS.

    A card listed in `_RULE_CARD_ATTESTATION_PREDICATE` only requires its
    attestation when that predicate matches the patch diff — used for cards
    (e.g. dt-binding-schema-basics) that fire for several reasons but only
    need the audit on a specific diff shape (an added `required:` cell-count
    entry).  Cards absent from the predicate map require attestation
    unconditionally whenever they fire.
    """
    violations: list[Violation] = []
    fired_ids = set(_packet_rule_card_ids(packet_json_path))

    # Check which attestation-bearing cards fired
    cards_needing_attestation = fired_ids & set(_RULE_CARD_ATTESTATION_MARKERS)
    if not cards_needing_attestation:
        return violations

    # Search all blocks for attestation markers
    all_block_text = "\n".join(
        f"{block.subject}\n{block.raw_html}" for block in report.blocks
    )

    for card_id in sorted(cards_needing_attestation):
        predicate = _RULE_CARD_ATTESTATION_PREDICATE.get(card_id)
        if predicate is not None and not predicate.search(patch_corpus):
            # The card fired for an unrelated reason; the conditional
            # attestation is not required for this diff shape.
            continue
        markers = _RULE_CARD_ATTESTATION_MARKERS[card_id]
        missing = [marker for marker in markers if marker not in all_block_text]
        if missing:
            violations.append(Violation(
                "rule_card_attestation",
                f"card:{card_id}",
                f"Rule card '{card_id}' fired but its mandatory attestation record "
                f"is incomplete. Missing marker(s): {', '.join(missing)}. "
                f"The subagent must produce every mandatory marker to prove "
                f"the check was actually executed.",
            ))

    return violations


def check_rule_card_coverage(
    report: Report,
    packet_json_path: Optional[Path],
) -> list[Violation]:
    """Require explicit reviewer coverage for every selected packet card.

    Packet mode deliberately keeps rule selection in the JSON sidecar.  This
    check closes the gap where a subagent reads the diff and writes a plausible
    block while silently ignoring selected rule cards.

    For each `checked` coverage entry, also require evidence-bearing prose so
    the entry cannot be a single-token escape hatch ("dt-resource-abi-matrix:
    checked — schema/driver/DT counts align." would pass naming but not show
    that the agent actually enumerated anything).  The evidence test accepts
    any of: a file path with a source extension, a hex constant, an
    UPPER/SNAKE_CASE symbol with at least one underscore, a quoted vendor
    compatible string, or an inline `<code>...</code>` citation.  Cards that
    already have an enforced Mandatory Attestation Record (handled by
    `check_rule_card_attestation`) are exempt from this evidence check to
    avoid double-burdening the attestation prose.  `finding`/`inconclusive`
    statuses are also exempt: a `finding` carries its own evidence in the
    finding-card; `inconclusive` is governed by the inconclusive-format rules.
    """
    card_ids = _packet_rule_card_ids(packet_json_path)
    if not card_ids:
        return []

    violations: list[Violation] = []
    attestation_cards = set(_RULE_CARD_ATTESTATION_MARKERS)
    for block in report.blocks:
        section_text = _section_plain_text(block.raw_html, _RULE_CARD_COVERAGE_SECTION_RE)
        if not section_text:
            violations.append(Violation(
                "rule_card_coverage",
                f"block#{block.index} '{block.subject[:60]}'",
                "selected packet rule cards require a visible "
                "<h3>Rule Card Coverage</h3> section",
            ))
            continue

        missing_visible = [card_id for card_id in card_ids if not _contains_card_id(section_text, card_id)]
        missing_record: list[str] = []
        if "rule_card_coverage:" not in block.step_record:
            missing_record = card_ids
        else:
            missing_record = [card_id for card_id in card_ids if not _contains_card_id(block.step_record, card_id)]

        if missing_visible:
            violations.append(Violation(
                "rule_card_coverage",
                f"block#{block.index} '{block.subject[:60]}'",
                "Rule Card Coverage section does not name selected card(s): "
                + ", ".join(missing_visible),
            ))
        if missing_record:
            violations.append(Violation(
                "rule_card_coverage",
                f"block#{block.index} '{block.subject[:60]}'",
                "STEP_COMPLETION_RECORD rule_card_coverage line is missing "
                "selected card(s): " + ", ".join(missing_record),
            ))

        # Evidence-bearing-prose check for `checked` entries.  The section
        # arrives as plain text (tags stripped by the HTML parser).
        section_match = _RULE_CARD_COVERAGE_SECTION_RE.search(block.raw_html)
        if not section_match:
            continue
        section_text_body = section_match.group(1)
        for card_id in card_ids:
            if card_id in attestation_cards:
                continue  # attestation marker enforcement covers this
            entry = _coverage_entry_for_card(section_text_body, card_id, card_ids)
            if entry is None:
                continue  # missing-card already flagged above
            status = _coverage_status(entry)
            if status != "checked":
                continue  # finding/inconclusive carry their own evidence
            # Strip the status word so the evidence test sees only the
            # justification prose (the card-id itself is already excluded —
            # the entry starts after it).
            evidence_prose = re.sub(r"\bchecked\b", " ", entry, flags=re.IGNORECASE)
            if not _COVERAGE_EVIDENCE_RE.search(evidence_prose):
                violations.append(Violation(
                    "rule_card_coverage",
                    f"block#{block.index} '{block.subject[:60]}'",
                    f"Rule Card Coverage entry for `{card_id}` is `checked` "
                    "but its evidence sentence has no concrete diff token "
                    "(file path, SNAKE_CASE/UPPER_CASE symbol, hex constant, "
                    "or quoted vendor compatible) — "
                    "claim 'checked' requires showing what was inspected.",
                ))
    return violations


def check_focused_review_obligations(
    report: Report,
    packet_json_path: Optional[Path],
) -> list[Violation]:
    """Require visible disposition for every trigger-specific packet obligation.

    Rule Card Coverage proves the selected card was acknowledged; focused
    obligations prove the subagent inspected the exact trigger evidence that
    selected that card.  Each obligation ID must appear with FINDING, SAFE, or
    INCONCLUSIVE so a generic PASS cannot skip the risky diff shape.
    """
    obligations = _packet_focused_obligations(packet_json_path)
    if not obligations:
        return []

    violations: list[Violation] = []
    disposition_re = re.compile(r"\b(?:FINDING|SAFE|INCONCLUSIVE)\b", re.IGNORECASE)
    for block in report.blocks:
        block_text = f"{block.raw_html}\n{block.step_record}"
        for obligation in obligations:
            obligation_id = obligation["id"]
            index = block_text.find(obligation_id)
            if index < 0:
                violations.append(Violation(
                    "rule_card_coverage",
                    f"block#{block.index} '{block.subject[:60]}'",
                    f"Focused review obligation `{obligation_id}` for card "
                    f"`{obligation['card']}` is not visibly dispositioned. The "
                    "subagent must start from focused-review-obligations and "
                    "mark each obligation ID as FINDING, SAFE, or INCONCLUSIVE.",
                ))
                continue
            window = block_text[max(0, index - 80): index + 320]
            if not disposition_re.search(window):
                violations.append(Violation(
                    "rule_card_coverage",
                    f"block#{block.index} '{block.subject[:60]}'",
                    f"Focused review obligation `{obligation_id}` is named but "
                    "has no FINDING/SAFE/INCONCLUSIVE disposition near the ID.",
                ))
    return violations


# A coverage entry for a single card_id.  Note: the HTML parser stores only
# text data in block.raw_html (tags like <li>/<code> are dropped), so the
# Rule Card Coverage section arrives as plain text with the card-id and its
# "status — prose" on adjacent lines.  Extract from the card-id up to the next
# all-card-ids boundary so the evidence test sees this entry's prose only.
def _coverage_entry_for_card(
    section_text: str, card_id: str, all_card_ids: list[str]
) -> Optional[str]:
    idx = section_text.find(card_id)
    if idx < 0:
        return None
    rest = section_text[idx + len(card_id):]
    # Truncate at the next other-card-id mention so we don't absorb the next
    # entry's prose.
    cut = len(rest)
    for other in all_card_ids:
        if other == card_id:
            continue
        j = rest.find(other)
        if 0 <= j < cut:
            cut = j
    return rest[:cut]


def _coverage_status(entry_text: str) -> str:
    """Return 'checked', 'finding', 'inconclusive', or '' if none recognized."""
    text = re.sub(r"\s+", " ", entry_text).lower()
    for status in ("inconclusive", "finding", "checked"):
        if re.search(rf"\b{status}\b", text):
            return status
    return ""


# Evidence shapes that prove the agent actually inspected something concrete:
#   - file path with a source extension (drivers/foo/bar.c, qcom,bar.yaml, …)
#   - hex constant (0x1234)
#   - UPPER_CASE / SNAKE_CASE symbol with at least one underscore
#   - quoted vendor compatible ("qcom,foo-bar")
# (No <code> alternative: the HTML parser strips tags from raw_html, so only
#  text content is available here.)
_COVERAGE_EVIDENCE_RE = re.compile(
    r"[A-Za-z0-9_./-]+\.(?:[ch]|ya?ml|dts|dtsi|S|rs|json)\b"
    r"|\b0x[0-9a-fA-F]+\b"
    r"|\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b"
    r"|\b[a-z][a-z0-9]+(?:_[a-z0-9]+){2,}\b"
    r"|[\"'][a-z][a-z0-9]*,[a-z0-9][a-z0-9.,_-]+[\"']"
)


def check_runtime_override_artifact(
    *,
    runtime_config: Optional[Path],
    sparse_file: Optional[Path],
    html_text: str,
    require_summary_row: bool,
) -> list[Violation]:
    if runtime_config is None:
        return []

    payload, violations = _load_runtime_config(runtime_config)
    if sparse_file is not None and not sparse_file.exists():
        violations.append(Violation(
            "runtime_override_artifact",
            str(sparse_file),
            "sparse artifact path was provided but the file does not exist",
        ))
    if payload is None:
        return violations

    if payload["sparse_check"]:
        if sparse_file is not None and sparse_file.exists():
            sparse_text = sparse_file.read_text(encoding="utf-8", errors="replace").strip()
            if sparse_text == _SPARSE_DISABLED_MARKER:
                violations.append(Violation(
                    "runtime_override_artifact",
                    str(sparse_file),
                    "runtime config enables sparse, but the sparse artifact claims it was disabled",
                ))
        return violations

    if sparse_file is None:
        violations.append(Violation(
            "runtime_override_artifact",
            str(runtime_config),
            "runtime config disables sparse, but validator did not receive a sparse artifact path",
        ))
        return violations
    if not sparse_file.exists():
        return violations

    sparse_text = sparse_file.read_text(encoding="utf-8", errors="replace").strip()
    if sparse_text != _SPARSE_DISABLED_MARKER:
        violations.append(Violation(
            "runtime_override_artifact",
            str(sparse_file),
            "when sparse is disabled by config, the sparse artifact must contain exactly "
            f"{_SPARSE_DISABLED_MARKER!r}",
        ))
    if require_summary_row and not _SPARSE_DISABLED_SUMMARY_RE.search(html_text):
        violations.append(Violation(
            "runtime_override_artifact",
            "html report",
            "final report must show sparse as SKIP with the note 'disabled by config'",
        ))
    return violations


def _source_aware_violations(
    report: Report,
    patch_corpus: str,
    source_root: Optional[Path],
    evidence_by_block: Optional[dict[int, dict[str, object]]] = None,
) -> list[Violation]:
    violations: list[Violation] = []
    if not patch_corpus:
        return violations
    violations.extend(check_pm_runtime_get_sync_source_aware(report, patch_corpus, evidence_by_block))
    violations.extend(check_clk_handle_ownership_source_aware(report, patch_corpus))
    violations.extend(check_clk_enable_idempotency_source_aware(report, patch_corpus))
    violations.extend(check_asoc_dai_target_source_aware(report, patch_corpus))
    violations.extend(check_non_alloc_enomem_source_aware(report, patch_corpus))
    violations.extend(check_pm_runtime_post_get_return_source_aware(report, patch_corpus))
    violations.extend(check_firmware_metadata_source_aware(report, patch_corpus))
    violations.extend(check_binding_compatible_conditional_source_aware(report, patch_corpus))
    violations.extend(check_pm_runtime_positive_return_source_aware(report, patch_corpus))
    violations.extend(check_printf_format_type_source_aware(report, patch_corpus))
    violations.extend(check_relocated_teardown_step_source_aware(report, patch_corpus))
    violations.extend(check_lock_coverage_symmetry_source_aware(report, patch_corpus))
    violations.extend(check_dma_names_source_aware(report, patch_corpus, evidence_by_block))
    violations.extend(check_binding_companion_dependency_source_aware(report, patch_corpus))
    violations.extend(check_binding_parent_compatible_consistency_source_aware(report, patch_corpus, source_root))
    violations.extend(check_old_dtb_compatibility_source_aware(report, patch_corpus))
    violations.extend(check_dt_fallback_old_kernel_new_dtb_source_aware(report, patch_corpus, source_root))
    violations.extend(check_provider_cells_const_source_aware(report, patch_corpus))
    violations.extend(check_optional_clk_dead_enoent_fallback(report, patch_corpus))
    violations.extend(check_required_clk_bulk_zero_count_source_aware(report, patch_corpus))
    violations.extend(check_framework_status_callback_power_state_source_aware(report, patch_corpus))
    violations.extend(check_framework_status_bootloader_refcount_source_aware(report, patch_corpus))
    violations.extend(check_managed_device_link_manual_remove_source_aware(report, patch_corpus))
    violations.extend(check_retained_dynamic_object_cleanup_source_aware(report, patch_corpus))
    violations.extend(check_level_irq_reenable_without_clear_source_aware(report, patch_corpus))
    violations.extend(check_match_data_source_aware(report, patch_corpus, evidence_by_block))
    violations.extend(check_selector_cardinality_source_aware(report, patch_corpus))
    violations.extend(check_aggregate_per_element_scale_source_aware(report, patch_corpus, source_root))
    violations.extend(check_cross_instance_pointer_unbind_source_aware(report, patch_corpus, source_root))
    violations.extend(check_peer_dimension_admission_source_aware(report, patch_corpus, evidence_by_block))
    violations.extend(check_duplicate_cleanup_fallthrough_source_aware(report, patch_corpus, evidence_by_block))
    violations.extend(check_failed_start_stale_state_source_aware(report, patch_corpus, evidence_by_block))
    violations.extend(check_paired_callback_backend_symmetry_source_aware(report, patch_corpus))
    violations.extend(check_resource_helper_guard_source_aware(report, patch_corpus, source_root))
    violations.extend(check_helper_side_effect_source_aware(report, patch_corpus))
    violations.extend(check_helper_replacement_postcondition_source_aware(report, patch_corpus))
    violations.extend(check_escaped_local_address_source_aware(report, patch_corpus, evidence_by_block))
    violations.extend(check_setup_return_guard_source_aware(report, patch_corpus, evidence_by_block))
    violations.extend(check_newly_exposed_silent_failure_source_aware(report, patch_corpus, evidence_by_block))
    violations.extend(check_touched_unsafe_pm_source_aware(report, patch_corpus, source_root, evidence_by_block))
    violations.extend(check_resource_abstraction_bypass_source_aware(report, patch_corpus))
    violations.extend(check_alternate_path_state_reset_source_aware(report, patch_corpus, source_root))
    violations.extend(check_unvalidated_arithmetic_input_source_aware(report, patch_corpus, source_root))
    violations.extend(check_branch_precedence_regression_source_aware(report, patch_corpus, source_root))
    violations.extend(check_branch_diversion_producer_coupling_source_aware(report, patch_corpus, source_root))
    violations.extend(check_readpath_widening_writer_locked_source_aware(report, patch_corpus, source_root))
    violations.extend(check_core_table_vendor_entry_source_aware(report, patch_corpus))
    violations.extend(check_stack_struct_zero_init_source_aware(report, patch_corpus))
    violations.extend(check_pas_metadata_release_source_aware(report, patch_corpus))
    violations.extend(check_qcom_clock_hw_clk_ctrl_source_aware(report, patch_corpus))
    violations.extend(check_qcom_clock_out_even_parent_source_aware(report, patch_corpus))
    violations.extend(check_qcom_clock_camcc_use_rpm_source_aware(report, patch_corpus))
    violations.extend(check_dts_unit_address_insertion_order_source_aware(report, patch_corpus, source_root))
    return violations


# Report-only checks shared verbatim by run() and run_block().  Each takes the
# parsed Report and returns a list[Violation].  Keeping them in one ordered
# tuple removes the dual-maintenance hazard between the two entry points: a new
# report-only check is added here once and runs in both modes.  Checks that need
# extra arguments (build_break_order/build_artifact_validity → tests_text/tmp_dir,
# the evidence/runtime/prompt/rules checks, and banner-only checks) stay as
# explicit per-mode calls in each entry point.
_REPORT_ONLY_CHECKS: tuple = (
    check_gate_traces,
    check_step_records,
    check_conditional_sections,
    check_block_anchor_ids,
    check_render_format,
    check_pre_existing_scope,
    check_hardware_trigger_consistency,
    check_hardware_notes_specificity,
    check_test_results_vs_build_notes,
    check_test_results_fail_evidence,
    check_refactor_coverage,
    check_future_risk_gate,
    check_safe_clearance_gate,
    check_platform_enablement_ready_to_apply,
    check_match_data_guard,
    check_pm_runtime_get_sync,
    check_device_unregister_pointer_hygiene,
    check_per_block_vote_scope,
    check_pm_get_sync_balance,
    check_dma_names_example,
    check_codebase_audit_record,
    check_codebase_audit_required,
    check_on_demand_reads_record,
    check_inconclusive_requires_read_attempt,
    check_severity_crash_floor,
    check_severity_restore_floor,
)


def _report_only_violations(report: Report) -> list[Violation]:
    """Run every report-only check in canonical order (shared by both modes)."""
    violations: list[Violation] = []
    for check in _REPORT_ONLY_CHECKS:
        violations.extend(check(report))
    return violations
