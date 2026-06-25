#!/usr/bin/env python3
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""End-to-end pytest suite for every AiCodeReview agent tool.

Boots the full AiCodeReview pipeline (docker + ts_indexer) against a pinned
linux-next checkout cloned into tests/linux/, then exercises each tool exposed
via AiCodeReview.dispatch_tool:

  find_definition / find_callers / find_callees / grep / read_file / list_files
  / git_log / git_show / git_cat_file

Code navigation is pure tree-sitter + ripgrep (no clangd / compile database),
so the suite needs no kernel build.

Run with the patchwise venv active.

    source .venv/bin/activate
    pytest tests/ai_code_review/test_tools.py -v -s

The first run is slow: init_kernel_tree() fetches linux-next.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

TESTS_DIR = Path(__file__).resolve().parent.parent
KERNEL_DIR = TESTS_DIR / "linux"

os.environ["PATCHWISE_SANDBOX_PATH"] = str(TESTS_DIR)

import pytest
from git import InvalidGitRepositoryError, NoSuchPathError, Repo

from patchwise.patch_review.ai_review.ai_code_review import AiCodeReview
from patchwise.patch_review.kernel_tree import init_kernel_tree

# Pin the kernel HEAD so IFDEF_CASES line numbers and other expectations
# stay stable as linux-next advances.
PINNED_COMMIT = "43cfbdda5af60ffc6272a7b8c5c37d1d0a181ca9"


def _clear_stale_index_lock(repo_path: Path) -> None:
    """Remove a leftover git index lock from a previously interrupted run."""
    lock_path = repo_path / ".git" / "index.lock"
    if lock_path.exists():
        lock_path.unlink()


def _checkout_pinned_commit(repo: Any) -> None:
    """Checkout the pinned commit with light recovery for stale lock files."""
    if repo.head.is_valid() and repo.head.commit.hexsha == PINNED_COMMIT:
        return

    for attempt in range(2):
        try:
            repo.git.checkout(PINNED_COMMIT)
            return
        except Exception as exc:
            if attempt == 1 or "index.lock" not in str(exc):
                raise
            _clear_stale_index_lock(Path(repo.working_tree_dir))
            time.sleep(1)

    raise RuntimeError(f"failed to checkout pinned commit {PINNED_COMMIT}")


def _open_or_init_kernel_repo(repo_path: Path) -> Repo:
    """Reuse an existing local kernel repo when present; fetch only on first setup."""
    try:
        return Repo(repo_path)
    except (InvalidGitRepositoryError, NoSuchPathError):
        return init_kernel_tree(repo_path)


@pytest.fixture(scope="session")
def review() -> AiCodeReview:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    print("\n=== Setting up AiCodeReview... ===", flush=True)
    repo = _open_or_init_kernel_repo(KERNEL_DIR)
    _clear_stale_index_lock(KERNEL_DIR)
    _checkout_pinned_commit(repo)
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
    result = review.agent.dispatch_tool("not_a_real_tool", {})
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
    result = review.agent.dispatch_tool("find_definition", {"name": name})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    assert defs, "expected at least one definition"
    paths = [d.get("path", "") for d in defs]
    assert any(
        expected_file in p for p in paths
    ), f"{expected_file!r} not among {paths}"


# Models routinely pass a C type with its tag keyword (`struct inode`); the tool
# strips the keyword and resolves the bare tag, matching the plain-name lookup.
@pytest.mark.parametrize(
    "name,expected_file",
    [
        ("struct inode", "include/linux/fs.h"),
        ("enum pid_type", "include/linux/pid_types.h"),
    ],
    ids=lambda v: str(v),
)
def test_find_definition_strips_type_keyword(
    review: AiCodeReview, name: str, expected_file: str
) -> None:
    result = review.agent.dispatch_tool("find_definition", {"name": name})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    paths = [d.get("path", "") for d in result.get("result", [])]
    assert any(expected_file in p for p in paths), f"{expected_file!r} not among {paths}"


# #ifdef-variant cases: two textual defs in the same file under
# mutually-exclusive branches. find_definition is build-agnostic — it returns
# ALL variants (it does not collapse to the one a given defconfig compiles), so
# the variant at expected_line must appear among the results.
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
    result = review.agent.dispatch_tool("find_definition", {"name": name})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    in_file = [d for d in defs if file_ in d.get("path", "")]
    assert len(in_file) >= 2, f"expected both #ifdef variants in {file_}, got {in_file}"
    lines = [d.get("line") for d in in_file]
    assert expected_line in lines, f"variant at {expected_line} missing; got {lines}"


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
    result = review.agent.dispatch_tool("find_definition", args)
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")


def test_find_definition_multi_file_hint(review: AiCodeReview) -> None:
    """`file` may list several paths; an exact hit on any ranks first."""
    result = review.agent.dispatch_tool(
        "find_definition",
        {"name": "inode", "file": "fs/open.c, include/linux/fs.h"},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    assert defs, "expected at least one definition"
    assert "include/linux/fs.h" in defs[0]["path"], f"hint not ranked first: {defs[0]}"


@pytest.mark.parametrize(
    "file_arg",
    [
        "../../../etc/passwd, does/not/exist.c",  # escaping + nonexistent
        "   ,  ",  # only separators -> empty hint list
    ],
    ids=["bad_paths", "blank"],
)
def test_find_definition_bad_hint_is_advisory(
    review: AiCodeReview, file_arg: str
) -> None:
    """The `file` hint is advisory only: bogus paths never fail the lookup."""
    result = review.agent.dispatch_tool(
        "find_definition", {"name": "inode", "file": file_arg}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    assert any(
        "include/linux/fs.h" in d["path"] for d in defs
    ), "inode should still resolve despite a bad hint"


def test_find_definition_valid_and_invalid_hint(review: AiCodeReview) -> None:
    """A valid + invalid path combo: the valid hint still ranks first, the bad
    one is ignored (advisory hints are never validated, so no error)."""
    result = review.agent.dispatch_tool(
        "find_definition",
        {"name": "inode", "file": "include/linux/fs.h, does/not/exist.c"},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    assert defs, "expected at least one definition"
    assert (
        "include/linux/fs.h" in defs[0]["path"]
    ), f"valid hint not ranked first: {defs[0]}"


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
    result = review.agent.dispatch_tool("find_callers", {"name": name})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    payload = result.get("result", {})
    callers = payload.get("callers", [])
    total = result.get("total_callers", 0)
    assert total >= min_count, f"only {total} callers (wanted >= {min_count})"
    assert callers, "expected at least one caller entry"
    first = callers[0]
    assert first.get("function"), f"missing function name in {first}"
    assert first.get("lines"), f"missing call-site lines in {first}"


def test_find_callers_references(review: AiCodeReview) -> None:
    """A non-function symbol still works: it has references, not callers.

    `file_operations` is a struct used widely as a typed variable, so its
    references (at file scope) far outnumber any in-function uses.
    """
    result = review.agent.dispatch_tool("find_callers", {"name": "file_operations"})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    payload = result.get("result", {})
    total = result.get("total_callers", 0) + result.get("total_references", 0)
    assert total >= 1, "expected references to file_operations"
    assert payload.get("references"), "expected file-scope references"


def test_find_callers_nonexistent(review: AiCodeReview) -> None:
    """An unreferenced/typo'd symbol is not an error — just zero hits."""
    result = review.agent.dispatch_tool(
        "find_callers", {"name": "djskaldx_no_such_symbol"}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    assert result.get("total_callers", 0) == 0
    assert result.get("total_references", 0) == 0


def test_find_callers_multi_file_scope(review: AiCodeReview) -> None:
    """`file` may list several directories to scope the search."""
    result = review.agent.dispatch_tool(
        "find_callers",
        {"name": "rproc_boot", "file": "drivers/remoteproc, drivers/soc"},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    callers = result.get("result", {}).get("callers", [])
    refs = result.get("result", {}).get("references", [])
    assert all(
        h["path"].startswith(("drivers/remoteproc/", "drivers/soc/"))
        for h in callers + refs
    ), "hit outside the requested directories"


# Unlike the advisory hint on find_definition/find_callees, find_callers' `file`
# scopes the search, so every path in the list is validated — one bad token
# fails the call rather than being silently ignored.
@pytest.mark.parametrize(
    "file_arg,expected_error",
    [
        ("drivers/remoteproc, ../../../etc/passwd", "escapes kernel tree"),
        ("drivers/remoteproc, does/not/exist", "file not found"),
    ],
    ids=["escape_in_list", "missing_in_list"],
)
def test_find_callers_multi_file_errors(
    review: AiCodeReview, file_arg: str, expected_error: str
) -> None:
    result = review.agent.dispatch_tool(
        "find_callers", {"name": "rproc_boot", "file": file_arg}
    )
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")


# ---------------------------------------------------------------------------
# find_callees
# ---------------------------------------------------------------------------


def test_find_callees(review: AiCodeReview) -> None:
    """do_sys_openat2's body calls build_open_flags then opens the file."""
    result = review.agent.dispatch_tool("find_callees", {"name": "do_sys_openat2"})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    assert defs, "expected at least one function definition"
    names = {c["name"] for d in defs for c in d.get("callees", [])}
    assert (
        "build_open_flags" in names
    ), f"build_open_flags not among callees: {sorted(names)}"


def test_find_callees_multi_file_hint(review: AiCodeReview) -> None:
    """`file` may list several paths to scope which variant(s) to expand."""
    result = review.agent.dispatch_tool(
        "find_callees",
        {"name": "do_sys_openat2", "file": "fs/open.c, fs/read_write.c"},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    assert defs and all(
        "fs/open.c" in d["path"] for d in defs
    ), f"expected only the fs/open.c variant: {[d['path'] for d in defs]}"


@pytest.mark.parametrize(
    "file_arg",
    [
        "drivers/remoteproc, drivers/soc",  # valid paths, but no variant lives there
        "../../../etc/passwd",  # bogus path
    ],
    ids=["nonmatching", "bad_path"],
)
def test_find_callees_hint_falls_back(review: AiCodeReview, file_arg: str) -> None:
    """When the hint matches no variant, fall back to all definitions, not error."""
    result = review.agent.dispatch_tool(
        "find_callees", {"name": "do_sys_openat2", "file": file_arg}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    assert any(
        "fs/open.c" in d["path"] for d in defs
    ), "should fall back to the real definition"


def test_find_callees_valid_and_invalid_hint(review: AiCodeReview) -> None:
    """A valid + invalid path combo scopes to the matching variant (fs/open.c);
    the bad path is ignored, not an error."""
    result = review.agent.dispatch_tool(
        "find_callees",
        {"name": "do_sys_openat2", "file": "fs/open.c, does/not/exist.c"},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    assert defs and all(
        "fs/open.c" in d["path"] for d in defs
    ), f"expected only the fs/open.c variant: {[d['path'] for d in defs]}"


@pytest.mark.parametrize(
    "args,expected_error",
    [
        ({"name": "djskaldx_no_such_symbol"}, "no function definition"),
        ({"name": "inode"}, "no function definition"),
    ],
    ids=["nonexistent", "struct_not_function"],
)
def test_find_callees_errors(
    review: AiCodeReview, args: Dict[str, Any], expected_error: str
) -> None:
    result = review.agent.dispatch_tool("find_callees", args)
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")


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
    result = review.agent.dispatch_tool("grep", args)
    assert result.get("ok"), f"tool returned not-ok: {result}"
    hits = result.get("result", [])
    total = result.get("total", 0)
    assert total >= min_hits, f"only {total} hits (wanted >= {min_hits})"
    assert any(
        must_contain in h["path"] for h in hits
    ), f"no hit touching {must_contain!r}"


def test_grep_glob_dts(review: AiCodeReview) -> None:
    """lpass_wsa2macro is a DT node name; default *.c/*.h must miss it."""
    default = review.agent.dispatch_tool("grep", {"pattern": "lpass_wsa2macro"})
    assert default.get("ok"), f"default grep failed: {default}"
    assert default.get("total", 0) == 0, "lpass_wsa2macro should not appear in *.c/*.h"

    wide = review.agent.dispatch_tool(
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
    result = review.agent.dispatch_tool(
        "grep", {"pattern": "REMOTEPROC", "glob": "Kconfig"}
    )
    assert result.get("ok"), f"glob grep failed: {result}"
    assert result.get("total", 0) >= 1, "expected REMOTEPROC hits in Kconfig files"
    hits = result.get("result", [])
    assert all(
        "Kconfig" in h["path"] for h in hits
    ), "non-Kconfig file slipped through glob filter"


def test_grep_directory_filter_honors_glob(review: AiCodeReview) -> None:
    """file=<dir> searches inside that subtree and still applies glob filters."""
    result = review.agent.dispatch_tool(
        "grep",
        {
            "pattern": "qcom,msm8226-adsp-pil",
            "file": "Documentation/devicetree/bindings/remoteproc",
            "glob": "*.yaml",
        },
    )
    assert result.get("ok"), f"directory-scoped grep failed: {result}"
    hits = result.get("result", [])
    assert result.get("total", 0) >= 1, "expected YAML hits under remoteproc bindings"
    assert all(
        h["path"].startswith("Documentation/devicetree/bindings/remoteproc/")
        for h in hits
    ), "hit outside requested directory slipped through file filter"
    assert all(
        h["path"].endswith(".yaml") for h in hits
    ), "non-YAML file slipped through glob filter"


def test_grep_glob_star_no_hits(review: AiCodeReview) -> None:
    """glob=* with a garbage pattern returns ok with zero hits."""
    result = review.agent.dispatch_tool(
        "grep", {"pattern": "dsajkdjsaiojwoqjo", "glob": "*"}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    assert result.get("total", 0) == 0, f"expected 0 hits, got {result.get('total')}"


def test_grep_glob_star_qcom_msm8226_adsp_pil(review: AiCodeReview) -> None:
    """glob=* finds qcom,msm8226-adsp-pil across C, DT, and YAML files."""
    result = review.agent.dispatch_tool(
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
    ],
    ids=["invalid_regex", "missing_file", "path_escape"],
)
def test_grep_errors(
    review: AiCodeReview, args: Dict[str, Any], expected_error: str
) -> None:
    result = review.agent.dispatch_tool("grep", args)
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,start,end,must_contain",
    [
        ("include/linux/list.h", 20, 40, "LIST_HEAD_INIT"),
        ("fs/open.c", 1, 50, "#include <linux/string.h>"),
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
    result = review.agent.dispatch_tool(
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
    result = review.agent.dispatch_tool("read_file", {"path": path})
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
    result = review.agent.dispatch_tool(
        "list_files", {"path": path, "recursive": recursive}
    )
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
    result = review.agent.dispatch_tool("list_files", {"path": path})
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
    result = review.agent.dispatch_tool("git_log", {"path": path})
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
def test_git_log_errors(review: AiCodeReview, path: str, expected_error: str) -> None:
    result = review.agent.dispatch_tool("git_log", {"path": path})
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")


# ---------------------------------------------------------------------------
# git_show
# ---------------------------------------------------------------------------


def test_git_show(review: AiCodeReview) -> None:
    result = review.agent.dispatch_tool("git_show", {"rev": PINNED_COMMIT})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    payload = result.get("result", {})
    assert payload.get("rev") == PINNED_COMMIT
    content = payload.get("content", "")
    assert f"commit {PINNED_COMMIT}" in content


def test_git_show_name_only(review: AiCodeReview) -> None:
    result = review.agent.dispatch_tool(
        "git_show", {"rev": PINNED_COMMIT, "name_only": True}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    payload = result.get("result", {})
    assert payload.get("rev") == PINNED_COMMIT
    paths = payload.get("paths", [])
    assert paths, "expected changed file paths"


def test_git_show_object_path(review: AiCodeReview) -> None:
    rev = f"{PINNED_COMMIT}:fs/open.c"
    result = review.agent.dispatch_tool("git_show", {"rev": rev})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    payload = result.get("result", {})
    assert payload.get("rev") == rev
    content = payload.get("content", "")
    assert "diff --git" not in content


@pytest.mark.parametrize(
    "args,expected_error",
    [
        ({"rev": "not_a_real_rev"}, "invalid rev"),
        ({"rev": "-n1"}, "invalid rev"),
        ({"rev": f"{PINNED_COMMIT}:fs/open.c", "name_only": True}, "name_only"),
    ],
    ids=["missing_rev", "option_like_rev", "name_only_with_object_spec"],
)
def test_git_show_errors(
    review: AiCodeReview, args: Dict[str, Any], expected_error: str
) -> None:
    result = review.agent.dispatch_tool("git_show", args)
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")


# ---------------------------------------------------------------------------
# git_cat_file
# ---------------------------------------------------------------------------


def test_git_cat_file(review: AiCodeReview) -> None:
    result = review.agent.dispatch_tool(
        "git_cat_file",
        {"rev": PINNED_COMMIT, "path": "fs/open.c", "start": 1, "end": 20},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    payload = result.get("result", {})
    assert payload.get("rev") == PINNED_COMMIT
    assert payload.get("path") == "fs/open.c"
    assert "#include <linux/string.h>" in payload.get("content", "")


@pytest.mark.parametrize(
    "args,expected_error",
    [
        ({"rev": "not_a_real_rev", "path": "fs/open.c"}, "invalid rev"),
        ({"rev": PINNED_COMMIT, "path": "../../../etc/passwd"}, "escapes kernel tree"),
        ({"rev": PINNED_COMMIT, "path": "does/not/exist.c"}, "git cat-file failed"),
    ],
    ids=["missing_rev", "path_escape", "missing_path_in_commit"],
)
def test_git_cat_file_errors(
    review: AiCodeReview, args: Dict[str, Any], expected_error: str
) -> None:
    result = review.agent.dispatch_tool("git_cat_file", args)
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert expected_error in (result.get("error") or "")
