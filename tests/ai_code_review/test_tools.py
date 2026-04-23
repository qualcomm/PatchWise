#!/usr/bin/env python3
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""End-to-end pytest suite for every AiCodeReview agent tool.

Boots the full AiCodeReview pipeline (docker + clangd + ts_indexer) against
a pinned linux-next checkout cloned into tests/linux/, then exercises each
tool exposed via AiCodeReview.dispatch_tool:

  find_definition / find_callers / find_calls / grep / read_file / list_files
  / git_log / git_show

Run with the patchwise venv active.

    source .venv/bin/activate
    pytest tests/ai_code_review/test_tools.py -v -s

The first run is slow: init_kernel_tree() fetches linux-next.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

TESTS_DIR = Path(__file__).resolve().parent.parent
KERNEL_DIR = TESTS_DIR / "linux"

os.environ["PATCHWISE_SANDBOX_PATH"] = str(TESTS_DIR)

import pytest

from patchwise.patch_review.ai_review.ai_code_review.ai_code_review import AiCodeReview
from patchwise.patch_review.kernel_tree import init_kernel_tree

# Pin the kernel HEAD so IFDEF_CASES line numbers and other expectations
# stay stable as linux-next advances.
PINNED_COMMIT = "43cfbdda5af60ffc6272a7b8c5c37d1d0a181ca9"


@pytest.fixture(scope="session")
def review() -> AiCodeReview:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    print("\n=== Setting up AiCodeReview... ===", flush=True)
    repo = init_kernel_tree(KERNEL_DIR)
    repo.git.checkout(PINNED_COMMIT)
    head = repo.head.commit
    print(
        f"Using kernel={KERNEL_DIR} head={head.hexsha[:12]} ({head.summary!r})",
        flush=True,
    )
    instance = AiCodeReview(repo_path=str(KERNEL_DIR), commit=head)
    print("=== Running tests... ===\n", flush=True)
    return instance


# ---------------------------------------------------------------------------
# dispatch layer
# ---------------------------------------------------------------------------


def test_dispatch_unknown_tool(review: AiCodeReview) -> None:
    result = review.dispatch_tool("not_a_real_tool", {})
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert "unknown tool" in (result.get("error") or "")


# ---------------------------------------------------------------------------
# find_definition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,kind,expected_file",
    [
        ("do_sys_openat2", "function", "fs/open.c"),
        ("inode", "struct", "include/linux/fs.h"),
        ("LIST_HEAD_INIT", "macro", "include/linux/list.h"),
        ("gfp_t", "typedef", "include/linux/types.h"),
        ("list_for_each_entry", "function-like macro", "include/linux/list.h"),
    ],
    ids=lambda v: str(v),
)
def test_find_definition(
    review: AiCodeReview, name: str, kind: str, expected_file: str
) -> None:
    result = review.dispatch_tool("find_definition", {"name": name})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    definition = result.get("definition") or {}
    path = definition.get("path", "")
    assert expected_file in path, f"resolved to {path}:{definition.get('line')}"


# #ifdef-variant cases: two textual defs in the same file under
# mutually-exclusive branches. arm64 defconfig has CONFIG_OF=y and
# CONFIG_NO_HZ_FULL=n.
@pytest.mark.parametrize(
    "name,file_,expected_line",
    [
        ("rproc_get_by_phandle", "drivers/remoteproc/remoteproc_core.c", 2108),
        ("tick_nohz_full_enabled", "include/linux/tick.h", 278),
    ],
    ids=lambda v: str(v),
)
def test_find_definition_ifdef(
    review: AiCodeReview, name: str, file_: str, expected_line: int
) -> None:
    result = review.dispatch_tool("find_definition", {"name": name})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    definition = result.get("definition") or {}
    path = definition.get("path", "")
    line = definition.get("line")
    assert (
        file_ in path and line == expected_line
    ), f"resolved to {path}:{line}, wanted {file_}:{expected_line}"


@pytest.mark.parametrize(
    "args,expected_error",
    [
        ({"name": "djskaldx_no_such_symbol"}, "not found in index"),
        ({}, "bad arguments"),
        ({"nam": "do_sys_openat2"}, "bad arguments"),
    ],
    ids=["nonexistent", "missing_name", "unknown_kwarg"],
)
def test_find_definition_errors(
    review: AiCodeReview, args: Dict[str, Any], expected_error: str
) -> None:
    result = review.dispatch_tool("find_definition", args)
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")



# ---------------------------------------------------------------------------
# find_callers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,min_count",
    [
        ("rproc_boot", 1),
        ("do_sys_openat2", 1),
    ],
    ids=lambda v: str(v),
)
def test_find_callers(review: AiCodeReview, name: str, min_count: int) -> None:
    result = review.dispatch_tool("find_callers", {"name": name})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    total = result.get("total", 0)
    assert total >= min_count, f"only {total} callers (wanted >= {min_count})"


@pytest.mark.parametrize(
    "args,expected_error",
    [
        ({"name": "djskaldx_no_such_symbol"}, "not found in index"),
        ({"name": "inode"}, "not a function"),
    ],
    ids=["nonexistent", "struct_not_function"],
)
def test_find_callers_errors(
    review: AiCodeReview, args: Dict[str, Any], expected_error: str
) -> None:
    result = review.dispatch_tool("find_callers", args)
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")


# ---------------------------------------------------------------------------
# find_calls (currently intentionally not-implemented)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# grep
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern,file_,min_hits,must_contain",
    [
        ("EXPORT_SYMBOL\\(rproc_boot\\)", None, 1, "drivers/remoteproc/"),
        ("LIST_HEAD_INIT", "include/linux/list.h", 2, "include/linux/list.h"),
    ],
    ids=lambda v: str(v)[:30],
)
def test_grep(
    review: AiCodeReview,
    pattern: str,
    file_: Optional[str],
    min_hits: int,
    must_contain: str,
) -> None:
    args: Dict[str, Any] = {"pattern": pattern}
    if file_ is not None:
        args["file"] = file_
    result = review.dispatch_tool("grep", args)
    assert result.get("ok"), f"tool returned not-ok: {result}"
    hits = result.get("result", [])
    total = result.get("total", 0)
    assert total >= min_hits, f"only {total} hits (wanted >= {min_hits})"
    assert any(
        must_contain in h["path"] for h in hits
    ), f"no hit touching {must_contain!r}"


def test_grep_glob_dts(review: AiCodeReview) -> None:
    """lpass_wsa2macro is a DT node name; default *.c/*.h must miss it."""
    default = review.dispatch_tool("grep", {"pattern": "lpass_wsa2macro"})
    assert default.get("ok"), f"default grep failed: {default}"
    assert default.get("total", 0) == 0, "lpass_wsa2macro should not appear in *.c/*.h"

    wide = review.dispatch_tool(
        "grep", {"pattern": "lpass_wsa2macro", "glob": "*.dts,*.dtsi"}
    )
    assert wide.get("ok"), f"glob grep failed: {wide}"
    assert (
        wide.get("total", 0) >= 1
    ), "expected lpass_wsa2macro hits in *.dts/*.dtsi files"
    hits = wide.get("result", [])
    assert all(
        h["path"].endswith((".dts", ".dtsi")) for h in hits
    ), "non-DT file slipped through glob filter"


def test_grep_glob_kconfig(review: AiCodeReview) -> None:
    """glob=Kconfig restricts results to Kconfig files."""
    result = review.dispatch_tool("grep", {"pattern": "REMOTEPROC", "glob": "Kconfig"})
    assert result.get("ok"), f"glob grep failed: {result}"
    assert result.get("total", 0) >= 1, "expected REMOTEPROC hits in Kconfig files"
    hits = result.get("result", [])
    assert all(
        "Kconfig" in h["path"] for h in hits
    ), "non-Kconfig file slipped through glob filter"


def test_grep_glob_star_no_hits(review: AiCodeReview) -> None:
    """glob=* with a garbage pattern returns ok with zero hits."""
    result = review.dispatch_tool(
        "grep", {"pattern": "dsajkdjsaiojwoqjo", "glob": "*"}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    assert result.get("total", 0) == 0, f"expected 0 hits, got {result.get('total')}"


def test_grep_glob_star_qcom_msm8226_adsp_pil(review: AiCodeReview) -> None:
    """glob=* finds qcom,msm8226-adsp-pil across C, DT, and YAML files."""
    result = review.dispatch_tool(
        "grep", {"pattern": "qcom,msm8226-adsp-pil", "glob": "*"}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    hits = result.get("result", [])

    def count_in(suffix: str) -> int:
        return sum(1 for h in hits if h["path"].endswith(suffix))

    assert count_in("arch/arm/boot/dts/qcom/qcom-msm8226.dtsi") == 1
    assert count_in("Documentation/devicetree/bindings/remoteproc/qcom,adsp.yaml") == 5
    assert count_in("drivers/remoteproc/qcom_q6v5_pas.c") == 1


# Bad inputs must surface an error, never a silent ok/total=0.
@pytest.mark.parametrize(
    "args,expected_error",
    [
        ({"pattern": "(unclosed"}, "invalid regex"),
        (
            {"pattern": "anything", "file": "does/not/exist/nowhere.yaml"},
            "file not found",
        ),
        (
            {"pattern": "anything", "file": "../../../etc/passwd"},
            "escapes kernel tree",
        ),
        (
            {"pattern": "anything", "file": "drivers/remoteproc"},
            "file not found",
        ),
    ],
    ids=["invalid_regex", "missing_file", "path_escape", "file_is_directory"],
)
def test_grep_errors(
    review: AiCodeReview, args: Dict[str, Any], expected_error: str
) -> None:
    result = review.dispatch_tool("grep", args)
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,start,end,must_contain",
    [
        ("include/linux/list.h", 20, 40, "LIST_HEAD_INIT"),
        ("fs/open.c", 1, 50, "Copyright"),
    ],
    ids=lambda v: str(v),
)
def test_read_file(
    review: AiCodeReview,
    path: str,
    start: int,
    end: int,
    must_contain: str,
) -> None:
    result = review.dispatch_tool(
        "read_file", {"path": path, "start": start, "end": end}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    content = result.get("result", {}).get("content", "")
    assert (
        must_contain in content
    ), f"substring {must_contain!r} not in content; preview={content[:200]!r}"


@pytest.mark.parametrize(
    "path,expected_error",
    [
        ("../../../etc/passwd", "escapes kernel tree"),
        ("does/not/exist.c", "not a file"),
        ("drivers/remoteproc", "not a file"),
    ],
    ids=["path_escape", "missing", "path_is_directory"],
)
def test_read_file_errors(review: AiCodeReview, path: str, expected_error: str) -> None:
    result = review.dispatch_tool("read_file", {"path": path})
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------


# list_files caps output at 100 entries sorted alphabetically, so expected
# names must fall within the first 100 of the chosen directory or the
# directory must be small enough to fit.
@pytest.mark.parametrize(
    "path,recursive,expected",
    [
        ("drivers/remoteproc", False, "remoteproc_core.c"),
        ("kernel/printk", False, "printk.c"),
    ],
    ids=lambda v: str(v),
)
def test_list_files(
    review: AiCodeReview,
    path: str,
    recursive: bool,
    expected: str,
) -> None:
    result = review.dispatch_tool("list_files", {"path": path, "recursive": recursive})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    entries = result.get("result", {}).get("entries", [])
    assert any(
        e["name"] == expected for e in entries
    ), f"{expected!r} not among {len(entries)} entries"


@pytest.mark.parametrize(
    "path,expected_error",
    [
        ("../../etc", "escapes kernel tree"),
        ("does/not/exist", "not a directory"),
        ("fs/open.c", "not a directory"),
    ],
    ids=["path_escape", "missing", "path_is_file"],
)
def test_list_files_errors(
    review: AiCodeReview, path: str, expected_error: str
) -> None:
    result = review.dispatch_tool("list_files", {"path": path})
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")


# ---------------------------------------------------------------------------
# git_log
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,min_count",
    [
        ("fs/open.c", 1),
        ("include/linux/list.h", 1),
    ],
    ids=lambda v: str(v),
)
def test_git_log(review: AiCodeReview, path: str, min_count: int) -> None:
    result = review.dispatch_tool("git_log", {"path": path})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    commits = result.get("result", [])
    total = result.get("total", 0)
    assert total >= min_count, f"only {total} commits (wanted >= {min_count})"
    assert commits, "expected at least one commit entry"
    first = commits[0]
    assert first.get("rev"), f"missing rev in {first}"
    assert first.get("author"), f"missing author in {first}"
    assert first.get("date"), f"missing date in {first}"
    assert first.get("subject"), f"missing subject in {first}"


@pytest.mark.parametrize(
    "path,expected_error",
    [
        ("../../../etc/passwd", "escapes kernel tree"),
        ("does/not/exist", "path not found"),
    ],
    ids=["path_escape", "missing_path"],
)
def test_git_log_errors(
    review: AiCodeReview, path: str, expected_error: str
) -> None:
    result = review.dispatch_tool("git_log", {"path": path})
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")


# ---------------------------------------------------------------------------
# git_show
# ---------------------------------------------------------------------------


def test_git_show(review: AiCodeReview) -> None:
    result = review.dispatch_tool("git_show", {"rev": PINNED_COMMIT})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    payload = result.get("result", {})
    assert payload.get("rev") == PINNED_COMMIT
    content = payload.get("content", "")
    assert f"commit {PINNED_COMMIT}" in content


@pytest.mark.parametrize(
    "rev,expected_error",
    [
        ("not_a_real_rev", "invalid rev"),
        ("-n1", "invalid rev"),
    ],
    ids=["missing_rev", "option_like_rev"],
)
def test_git_show_errors(
    review: AiCodeReview, rev: str, expected_error: str
) -> None:
    result = review.dispatch_tool("git_show", {"rev": rev})
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")
