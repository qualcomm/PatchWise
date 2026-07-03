# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Resolve a `--project` git subtree within a broader `--repo-path` mount.

When `--repo-path` is a broad workspace directory (e.g. a Qualcomm
`kernel_platform/` holding the GKI kernel `common` plus out-of-tree module trees)
and `--project` names the kernel git tree inside it (e.g. `common`), the container
mounts the whole `--repo-path` so the agent can navigate every sibling project,
while git operations + the diff use the `--project` subtree. These helpers do the
path resolution and produce the note that tells the agent the in-tree path
prefix."""

from pathlib import Path
from typing import Tuple


def resolve_git_tree(mount_path: str, project: str = "") -> Tuple[Path, Path, str]:
    """Resolve ``(mount_root, git_tree, git_subdir)`` from a mount path and an
    optional project subpath.

    - ``mount_root`` is the directory the container mounts / the agent navigates.
    - ``git_tree`` is the git checkout (has ``.git``) the diff and docker prep use.
    - ``git_subdir`` is ``git_tree`` relative to ``mount_root`` ("" when they are
      the same — the common case, leaving every existing caller unchanged).

    A relative ``project`` is taken under ``mount_root``; an absolute one is used
    as-is but must sit inside ``mount_root``. Raises ``ValueError`` when the
    project escapes the mount or has no ``.git``."""
    root = Path(mount_path).resolve()
    if not project:
        git_tree, git_subdir = root, ""
    else:
        pj = Path(project)
        git_tree = (pj if pj.is_absolute() else root / pj).resolve()
        if git_tree == root:
            git_subdir = ""
        else:
            try:
                git_subdir = git_tree.relative_to(root).as_posix()
            except ValueError:
                raise ValueError(
                    f"--project must be inside --repo-path ({root}): {git_tree}"
                )
    if not (git_tree / ".git").exists():
        raise ValueError(f"--project must be a git tree (has .git): {git_tree}")
    return root, git_tree, git_subdir


def is_repo_managed(path: str) -> bool:
    """Whether ``path`` is a repo(1)-managed (downstream) workspace.

    A pure query; pair with ``require_workspace_root`` to reject a path that is
    neither ``.repo`` nor ``.git``."""
    return (Path(path).resolve() / ".repo").is_dir()


def require_workspace_root(path: str) -> None:
    """Raise unless ``--repo-path`` directly holds ``.repo`` or ``.git``.

    We reject an ambiguous root rather than walking ancestors and guessing."""
    p = Path(path).resolve()
    if not (p / ".repo").is_dir() and not (p / ".git").exists():
        raise ValueError(
            f"--repo-path must contain .repo (downstream) or .git (upstream): {p}"
        )


def repo_project_note(repo_path: str) -> str:
    """Review context listing the workspace's git projects. Empty when not
    repo-managed."""
    project_list = Path(repo_path).resolve() / ".repo" / "project.list"
    if not project_list.is_file():
        return ""
    projects = [ln.strip() for ln in project_list.read_text().splitlines() if ln.strip()]
    if not projects:
        return ""
    listing = "\n".join(projects)
    return (
        "## Workspace projects\n\n"
        "This is a repo(1)-managed workspace with these git projects "
        "(workspace-relative paths). The git tools resolve a file's project from "
        "its path automatically; you only name one of these as `dir` for a "
        "path-less `git_log` search (grep/pickaxe):\n\n"
        f"```\n{listing}\n```\n"
    )


def project_layout_note(git_subdir: str) -> str:
    """Review context: where the diff's files live, and that the git tools resolve
    a file's project from its path."""
    if not git_subdir:
        return (
            "## Repository layout\n\n"
            "The workspace root is the git tree, so the diff's paths are already "
            "workspace-relative. The git tools resolve a file's project from its "
            "path; a path-less `git_log` search takes `dir='.'`.\n"
        )
    return (
        "## Repository layout\n\n"
        f"You are navigating a multi-project workspace. The diff lists its changed "
        f"files tree-relative (unprefixed), and they live under `{git_subdir}/`, so "
        f"prepend `{git_subdir}/` to locate them (a diff path `drivers/foo.c` is "
        f"`{git_subdir}/drivers/foo.c`). `{git_subdir}` is only where this change is "
        f"committed — the code it depends on (definitions, callers, headers) may "
        f"live in other projects, such as the base kernel. Investigate wherever the "
        f"evidence leads: `find_definition`, `find_callers` and `grep` search the "
        f"whole workspace and return full workspace paths, and the git tools "
        f"(`git_log`, `git_show`, `git_cat_file`) resolve each file's project from "
        f"the path you pass. Only a path-less `git_log` search needs a `dir` naming "
        f"the project to search.\n"
    )
