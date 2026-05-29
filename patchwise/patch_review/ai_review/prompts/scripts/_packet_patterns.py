"""Shared diff and path-classification patterns for the review-commits skill.

This module is the single source of truth for utilities and regex patterns
that were previously duplicated across select_rule_cards.py,
prepare_patch_series.py, and assemble_review_packet.py.  Import from here
rather than re-defining.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Diff text extraction
# ---------------------------------------------------------------------------

def changed_diff_text(diff_text: str) -> str:
    """Return only added/removed source lines from a unified diff, stripped of
    the leading +/- marker.  Excludes diff header lines (+++/---).
    """
    changed_lines: list[str] = []
    for line in diff_text.splitlines():
        if not line or line[0] not in {"+", "-"}:
            continue
        if line.startswith(("+++", "---")):
            continue
        changed_lines.append(line[1:])
    return "\n".join(changed_lines)


# ---------------------------------------------------------------------------
# Path classification regexes
# ---------------------------------------------------------------------------

DT_RE = re.compile(r"(^|/)Documentation/devicetree/bindings/|\.(dts|dtsi)$")
DT_BINDING_HEADER_RE = re.compile(r"(^|/)include/dt-bindings/.+\.h$")

# Match real OF/DT API usage, not incidental "of_" substrings like number_of_,
# out_of_, or copy_of_ that appear in ordinary C diffs.
OF_API_RE = re.compile(
    r"\bof_match_table\b|"
    r"\bdevice_get_match_data\b|"
    r"\bof_(match_device|match_node|device_get_match_data|device_is_compatible|"
    r"find_compatible_node|find_node_by|get_property|property_read|property_present|"
    r"property_count|node_|parse_phandle|address_to_resource|iomap|irq_get|irq_parse|"
    r"alias_get|get_child|for_each_)\w*\b|"
    r"\bfor_each_\w*child_of_node\b"
)

HARDWARE_PATH_RE = re.compile(
    r"(^|/)(drivers|arch|sound|net|block|crypto|firmware|soc|kernel|lib|mm|virt|include)/"
)

SUBSYSTEM_PATH_PREFIXES = (
    "drivers/", "arch/", "firmware/", "soc/", "sound/",
    "net/", "block/", "crypto/",
)
