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
    """`file` is an array of paths; an exact hit on any ranks first."""
    result = review.agent.dispatch_tool(
        "find_definition",
        {"name": "inode", "file": ["fs/open.c", "include/linux/fs.h"]},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    assert defs, "expected at least one definition"
    assert "include/linux/fs.h" in defs[0]["path"], f"hint not ranked first: {defs[0]}"


@pytest.mark.parametrize(
    "file_arg",
    [
        ["../../../etc/passwd", "does/not/exist.c"],  # escaping + nonexistent
        [],  # no hints
    ],
    ids=["bad_paths", "empty"],
)
def test_find_definition_bad_hint_is_advisory(
    review: AiCodeReview, file_arg: list
) -> None:
    """A `file` scope that matches no candidate never fails the lookup: the
    filter is skipped and the definition is still returned."""
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
        {"name": "inode", "file": ["include/linux/fs.h", "does/not/exist.c"]},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    assert defs, "expected at least one definition"
    assert (
        "include/linux/fs.h" in defs[0]["path"]
    ), f"valid hint not ranked first: {defs[0]}"


def test_find_definition_returns_span(review: AiCodeReview) -> None:
    """Each definition carries its line range [line, end] so the function can be
    read whole in one read_file call."""
    result = review.agent.dispatch_tool("find_definition", {"name": "do_sys_openat2"})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    assert defs, "expected at least one definition"
    d = defs[0]
    assert isinstance(d.get("line"), int) and isinstance(d.get("end"), int), d
    assert d["end"] >= d["line"], f"end before start: {d}"


def test_find_definition_hint_does_not_scope(review: AiCodeReview) -> None:
    """`file` is a ranking hint only — it never filters. A symbol defined
    outside the hinted directory is still returned (find_definition surfaces
    every definition)."""
    result = review.agent.dispatch_tool(
        "find_definition", {"name": "do_sys_openat2", "file": ["drivers/soc"]}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    paths = [d["path"] for d in result.get("result", [])]
    assert any("fs/open.c" in p for p in paths), f"definition was scoped away: {paths}"


@pytest.mark.parametrize(
    "name,kind,expected_file",
    [
        ("inode", "struct", "include/linux/fs.h"),
        ("gfp_t", "typedef", "include/linux/types.h"),
        ("LIST_HEAD_INIT", "macro", "include/linux/list.h"),
        ("do_sys_openat2", "function", "fs/open.c"),
        # An ops-table / aggregate initializer is a findable definition too — a
        # `static const struct file_operations simple_dir_operations = {...}`.
        ("simple_dir_operations", "initializer", "fs/libfs.c"),
    ],
    ids=lambda v: str(v),
)
def test_find_definition_granular_kind(
    review: AiCodeReview, name: str, kind: str, expected_file: str
) -> None:
    """find_definition reports a granular kind (struct/typedef/macro/function),
    not a lumped 'other'."""
    result = review.agent.dispatch_tool("find_definition", {"name": name})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    match = [
        d
        for d in result.get("result", [])
        if expected_file in d.get("path", "") and d.get("kind") == kind
    ]
    assert match, f"no {kind!r} for {name!r} in {expected_file}; got {result.get('result')}"


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
    # Each caller carries the calling function's full range, so it can be read
    # whole in one call.
    assert isinstance(first.get("function_start"), int), first
    assert isinstance(first.get("function_end"), int), first
    assert first["function_start"] <= first["function_end"], first
    assert all(first["function_start"] <= ln <= first["function_end"]
               for ln in first["lines"]), first


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
        {"name": "rproc_boot", "file": ["drivers/remoteproc", "drivers/soc"]},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    callers = result.get("result", {}).get("callers", [])
    refs = result.get("result", {}).get("references", [])
    assert all(
        h["path"].startswith(("drivers/remoteproc/", "drivers/soc/"))
        for h in callers + refs
    ), "hit outside the requested directories"


def test_find_callers_skips_missing_path(review: AiCodeReview) -> None:
    """One missing path is dropped (and reported), not fatal — the valid path's
    callers still come back."""
    result = review.agent.dispatch_tool(
        "find_callers",
        {"name": "rproc_boot", "file": ["drivers/remoteproc", "does/not/exist"]},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    assert "does/not/exist" in result.get("skipped_paths", [])
    assert result.get("total_callers", 0) >= 1, "valid path's callers were lost"


# A path that escapes the tree is still fatal (security), and an all-missing
# scope still fails — but a *partial* miss is now skipped (see above).
@pytest.mark.parametrize(
    "file_arg,expected_error",
    [
        (["drivers/remoteproc", "../../../etc/passwd"], "escapes kernel tree"),
        (["does/not/exist", "also/missing"], "file not found"),
    ],
    ids=["escape_in_list", "all_missing"],
)
def test_find_callers_multi_file_errors(
    review: AiCodeReview, file_arg: list, expected_error: str
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
        {"name": "do_sys_openat2", "file": ["fs/open.c", "fs/read_write.c"]},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    defs = result.get("result", [])
    assert defs and all(
        "fs/open.c" in d["path"] for d in defs
    ), f"expected only the fs/open.c variant: {[d['path'] for d in defs]}"


@pytest.mark.parametrize(
    "file_arg",
    [
        ["drivers/remoteproc", "drivers/soc"],  # valid paths, no variant lives there
        ["../../../etc/passwd"],  # bogus path
    ],
    ids=["nonmatching", "bad_path"],
)
def test_find_callees_hint_falls_back(review: AiCodeReview, file_arg: list) -> None:
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
        {"name": "do_sys_openat2", "file": ["fs/open.c", "does/not/exist.c"]},
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


def test_grep_file_array_comma_in_name(review: AiCodeReview) -> None:
    """A path whose filename contains a comma is one array element — not split.
    This is the case the old delimiter-based parsing corrupted."""
    binding = "Documentation/devicetree/bindings/remoteproc/qcom,adsp.yaml"
    result = review.agent.dispatch_tool(
        "grep", {"pattern": "qcom,msm8226-adsp-pil", "file": [binding]}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    hits = result.get("result", [])
    assert result.get("total", 0) >= 1, "comma-named binding path was not searched"
    assert all(h["path"] == binding for h in hits), f"hit outside {binding}: {hits}"


def test_grep_returns_enclosing_span(review: AiCodeReview) -> None:
    """A hit inside a function is attributed via `enclosing` (kind 'function')
    with start <= hit_line <= end, so the whole function can be read at once."""
    result = review.agent.dispatch_tool(
        "grep", {"pattern": "do_sys_openat2", "file": ["fs/open.c"]}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    in_func = [
        h
        for h in result.get("result", [])
        if (h.get("enclosing") or {}).get("kind") == "function"
    ]
    assert in_func, "expected at least one hit inside a function"
    enc = in_func[0]["enclosing"]
    assert isinstance(enc["start"], int) and isinstance(enc["end"], int)
    assert enc["start"] <= in_func[0]["line"] <= enc["end"], in_func[0]


def test_grep_enclosing_macro(review: AiCodeReview) -> None:
    """A hit on a macro definition attributes to that macro (kind 'macro') —
    a file-scope construct that has no enclosing function."""
    result = review.agent.dispatch_tool(
        "grep", {"pattern": "LIST_HEAD_INIT", "file": ["include/linux/list.h"]}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    macro_hits = [
        h
        for h in result.get("result", [])
        if (h.get("enclosing") or {}).get("kind") == "macro"
        and h["enclosing"]["name"] == "LIST_HEAD_INIT"
    ]
    assert macro_hits, f"no macro-scoped hit: {result.get('result')}"


def test_grep_enclosing_ops_table(review: AiCodeReview) -> None:
    """A hit inside an ops-table / aggregate initializer attributes to that
    initializer (kind 'initializer') — the .release=foo wiring case that was
    previously null."""
    result = review.agent.dispatch_tool(
        "grep", {"pattern": "dcache_dir_close", "file": ["fs/libfs.c"]}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    table_hits = [
        h
        for h in result.get("result", [])
        if (h.get("enclosing") or {}).get("kind") == "initializer"
        and h["enclosing"]["name"] == "simple_dir_operations"
    ]
    assert table_hits, f"no initializer-scoped hit: {result.get('result')}"


def test_grep_skips_missing_path(review: AiCodeReview) -> None:
    """One missing path is dropped and reported; the valid path's hits remain."""
    binding = "Documentation/devicetree/bindings/remoteproc/qcom,adsp.yaml"
    result = review.agent.dispatch_tool(
        "grep",
        {"pattern": "qcom,msm8226-adsp-pil", "file": [binding, "does/not/exist.yaml"]},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    assert "does/not/exist.yaml" in result.get("skipped_paths", [])
    assert result.get("total", 0) >= 1, "valid path's hits were lost"


# Bad inputs must surface an error, never a silent ok/total=0.
@pytest.mark.parametrize(
    "args,expected_error",
    [
        ({"pattern": "(unclosed"}, "invalid regex"),
        (
            {"pattern": "anything", "file": ["does/not/exist/nowhere.yaml"]},
            "file not found",
        ),
        (
            {"pattern": "anything", "file": ["../../../etc/passwd"]},
            "escapes kernel tree",
        ),
    ],
    ids=["invalid_regex", "all_missing", "path_escape"],
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


def test_read_file_position_triple(review: AiCodeReview) -> None:
    """read_file reports start/end/total (lines start..end of total) and no
    longer ships the ambiguous `truncated` flag — end < total means more."""
    result = review.agent.dispatch_tool(
        "read_file", {"path": "fs/open.c", "start": 1, "end": 10}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    payload = result.get("result", {})
    assert payload["start"] == 1 and payload["end"] == 10
    assert payload["total"] == 1581, f"unexpected total: {payload['total']}"
    assert "truncated" not in payload, "truncated should be gone for the reader"
    assert payload["end"] < payload["total"], "end<total signals more remains"


def test_read_file_caps_at_256(review: AiCodeReview) -> None:
    """With no `end`, a long file is capped at 256 lines (not 200), and total
    reflects the whole file."""
    result = review.agent.dispatch_tool("read_file", {"path": "fs/open.c", "start": 1})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    payload = result.get("result", {})
    assert payload["end"] == 256, f"cap not 256: {payload['end']}"
    assert payload["total"] == 1581
    assert payload["content"].count("\n") <= 256


def test_read_file_eof_reaches_total(review: AiCodeReview) -> None:
    """Reading to the end yields end == total (the EOF signal)."""
    result = review.agent.dispatch_tool(
        "read_file", {"path": "fs/open.c", "start": 1570, "end": 5000}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    payload = result.get("result", {})
    assert payload["end"] == payload["total"] == 1581, payload


# ---------------------------------------------------------------------------
# read_doc
# ---------------------------------------------------------------------------


def test_read_doc_reads_file(review: AiCodeReview) -> None:
    """read_doc returns a Documentation/ file whole."""
    result = review.agent.dispatch_tool(
        "read_doc", {"path": "Documentation/filesystems/mmap_prepare.rst"}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    payload = result.get("result", {})
    assert payload["path"].endswith("Documentation/filesystems/mmap_prepare.rst")
    assert payload["content"].strip(), "expected non-empty doc content"


def test_read_doc_miss_points_to_search(review: AiCodeReview) -> None:
    """A guessed path that misses points the model at search_docs/read_binding."""
    result = review.agent.dispatch_tool(
        "read_doc", {"path": "Documentation/filesystems/no_such_doc.rst"}
    )
    assert not result.get("ok"), f"expected miss, got: {result}"
    assert "search_docs" in result.get("error", "")


# ---------------------------------------------------------------------------
# search_docs
# ---------------------------------------------------------------------------


def test_search_docs_finds_doc_by_topic(review: AiCodeReview) -> None:
    """A topic word surfaces the doc that covers it."""
    result = review.agent.dispatch_tool("search_docs", {"query": "mmap_prepare"})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    paths = [h["path"] for h in result.get("result", [])]
    assert any(
        p.endswith("Documentation/filesystems/mmap_prepare.rst") for p in paths
    ), f"expected mmap_prepare.rst among hits: {paths[:10]}"


def test_search_docs_by_compatible(review: AiCodeReview) -> None:
    """A compatible string surfaces its binding yaml."""
    result = review.agent.dispatch_tool(
        "search_docs", {"query": "qcom,msm8226-adsp-pil"}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    paths = [h["path"] for h in result.get("result", [])]
    assert any(
        p.endswith("Documentation/devicetree/bindings/remoteproc/qcom,adsp.yaml")
        for p in paths
    ), f"expected qcom,adsp.yaml among hits: {paths[:10]}"


# ---------------------------------------------------------------------------
# read_binding
# ---------------------------------------------------------------------------


def test_read_binding_resolves_compatible(review: AiCodeReview) -> None:
    """A literal compatible resolves to its binding yaml and returns it whole."""
    result = review.agent.dispatch_tool(
        "read_binding", {"compatible": "qcom,msm8226-adsp-pil"}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    matches = result.get("result", {}).get("matches", [])
    paths = [m["path"] for m in matches]
    assert any(
        p.endswith("Documentation/devicetree/bindings/remoteproc/qcom,adsp.yaml")
        for p in paths
    ), f"expected qcom,adsp.yaml among matches: {paths}"
    # The resolved binding is returned whole, not just located.
    inlined = [m for m in matches if "content" in m]
    assert inlined, "expected at least one match to carry content"
    assert "compatible" in inlined[0]["content"]


def test_read_binding_alternation_dedup(review: AiCodeReview) -> None:
    """An alternation over compatibles sharing one binding yields one match."""
    result = review.agent.dispatch_tool(
        "read_binding",
        {"compatible": "qcom,msm8226-adsp-pil|qcom,sdm845-adsp-pas"},
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    paths = [m["path"] for m in result.get("result", {}).get("matches", [])]
    binding = "Documentation/devicetree/bindings/remoteproc/qcom,adsp.yaml"
    # Both compatibles live in qcom,adsp.yaml, so it appears exactly once.
    assert sum(1 for p in paths if p.endswith(binding)) == 1, paths


def test_read_binding_miss(review: AiCodeReview) -> None:
    """A compatible no binding matches fails loudly with an actionable error."""
    result = review.agent.dispatch_tool(
        "read_binding", {"compatible": "acme,nonexistent-widget-9000"}
    )
    assert not result.get("ok"), f"expected miss, got: {result}"
    assert "no binding matches" in result.get("error", "")


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


def test_git_log_grep(review: AiCodeReview) -> None:
    """--grep searches commit messages; no path needed."""
    result = review.agent.dispatch_tool("git_log", {"grep": "open"})
    assert result.get("ok"), f"tool returned not-ok: {result}"
    assert result.get("total", 0) >= 1, "expected message matches for 'open'"


# Pickaxe searches are scoped to fs/open.c so they walk only that file's
# history (fast) rather than all of mainline.
def test_git_log_pickaxe_added_removed(review: AiCodeReview) -> None:
    """-S finds the commit(s) that added or removed an exact string."""
    result = review.agent.dispatch_tool(
        "git_log", {"pickaxe": "do_sys_openat2", "path": "fs/open.c"}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    assert result.get("total", 0) >= 1, "expected the commit that introduced it"


def test_git_log_pickaxe_regex(review: AiCodeReview) -> None:
    """-G finds commits whose diff adds/removes a line matching a regex."""
    result = review.agent.dispatch_tool(
        "git_log", {"pickaxe_regex": "do_sys_openat2", "path": "fs/open.c"}
    )
    assert result.get("ok"), f"tool returned not-ok: {result}"
    assert result.get("total", 0) >= 1, "expected diff-content matches"


def test_git_log_requires_a_criterion(review: AiCodeReview) -> None:
    """With neither path nor a search term, git_log refuses rather than dumping
    unscoped history."""
    result = review.agent.dispatch_tool("git_log", {})
    assert not result.get("ok"), f"unexpectedly ok: {result}"
    assert "at least one" in (result.get("error") or "")


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
    # Same position-triple contract as read_file: total present, no truncated.
    assert payload.get("start") == 1 and payload.get("end") == 20
    assert isinstance(payload.get("total"), int) and payload["total"] >= 20
    assert "truncated" not in payload


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
