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


def project_layout_note(git_subdir: str) -> str:
    """A note, for the agent, describing the in-tree path prefix when the kernel
    git tree sits under a subdirectory of the navigable mount. Empty when the
    mount root is itself the kernel tree (nothing to prefix)."""
    if not git_subdir:
        return ""
    return (
        "## Repository layout\n\n"
        f"You are navigating a multi-project workspace. The kernel tree under "
        f"review lives under `{git_subdir}/`, so prefix paths to its source with "
        f"`{git_subdir}/` (e.g. `{git_subdir}/kernel/events/core.c`, "
        f"`{git_subdir}/drivers/...`, `{git_subdir}/Documentation/...`). Other "
        f"top-level directories are sibling projects, including out-of-tree "
        f"modules, that you can read at their own paths when the evidence points "
        f"there.\n"
    )
