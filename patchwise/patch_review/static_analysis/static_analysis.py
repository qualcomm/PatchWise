# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
import re
from pathlib import Path

from git.objects.commit import Commit

from patchwise.patch_review.patch_review import PatchReview


# Matches the first line of a dt-schema record: a non-indented path ending in
# .yaml/.dtb/.dtbo followed by ':' (format_error's separator). Rejects Python
# tracebacks, make errors, and other stderr chatter which don't have this shape.
#
# Matches:
#   /home/.../foo.yaml: title: 'X' should not be valid under ...
#   /home/.../bar.dtb: pinctrl@13800 (...): reg: ... is too long
#   arch/.../baz.dtb: /soc/.../x: failed to match any schema with compatible: [...]
#   /path/to/file.yaml:42:7: title: ...                  (linecol form)
#   overlay.dtbo: ...
#
# Rejects:
#   '  File "/.../dtb_validate.py", line 89, in check_subtree'   (indented frame)
#   'Traceback (most recent call last):'                         (no .yaml/.dtb/.dtbo:)
#   'jsonschema.exceptions._WrappedReferencingError: ...'        (no .yaml/.dtb/.dtbo:)
#   'make[2]: *** [Makefile:14: ...] Error 1'                    (no .yaml/.dtb/.dtbo:)
#   "warning: python package 'yamllint' not installed, skipping" (no .yaml/.dtb/.dtbo:)
_DT_RECORD_ANCHOR_RE = re.compile(r"^\S.*\.(?:yaml|dtb|dtbo):")


class StaticAnalysis(PatchReview):
    """
    Base class for performing static analysis on kernel commits.

    This class defines the interface and common methods for all static analysis
    tools. Subclasses should override the `run` method.
    """

    def reset_tree(self, commit: Commit) -> None:
        """Reset the in-container kernel tree to the given commit."""
        self.logger.debug(f"Reset tree to {commit.hexsha}")
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        proc = self.docker_manager.run_command(
            ["git", "reset", "--hard", commit.hexsha],
            cwd=str(kernel_dir),
        )
        proc.communicate()

    def group_records(self, text: str) -> list[str]:
        """
        Group each anchor line (matching `_DT_RECORD_ANCHOR_RE`) with its
        subsequent indented continuation lines into a single record. Blank
        lines and any non-indented line that is not an anchor are dropped.
        Single-line outputs (refcheckdocs) degenerate to one record per line.
        """
        records: list[str] = []
        current: list[str] = []
        for line in text.splitlines():
            if not line:
                if current:
                    records.append("\n".join(current))
                    current = []
            elif line.startswith("\t"):
                if current:
                    current.append(line)
            elif _DT_RECORD_ANCHOR_RE.match(line):
                if current:
                    records.append("\n".join(current))
                current = [line]
            else:
                if current:
                    records.append("\n".join(current))
                    current = []
        if current:
            records.append("\n".join(current))
        return records

    def diff_new_records(self, baseline_path: Path, current_path: Path) -> str:
        """
        Return records present in `current_path` but not in `baseline_path`,
        preserving current's order.
        """
        baseline = set(self.group_records(baseline_path.read_text()))
        new = [
            r
            for r in self.group_records(current_path.read_text())
            if r not in baseline
        ]
        return "\n".join(new)

    def clean_tree(self, arch: str = "arm"):
        self.logger.debug("Cleaning kernel tree")
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        self.run_cmd_with_timer(
            [
                "make",
                "-C",
                str(kernel_dir),
                f"O={self.docker_manager.build_dir}",
                f"-j{os.cpu_count()}",
                "-s",
                "ARCH=" + arch,
                "LLVM=1",
                "mrproper",
            ],
            cwd=str(self.docker_manager.build_dir),
            desc="Cleaning tree",
        )

    def make_config(
        self,
        config_type: str = "defconfig",
        arch: str = "arm",
        extra_args: list[str] = [],
    ) -> None:
        self.logger.debug(f"Making {config_type}")
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        cmd = [
            "make",
            "-C",
            str(kernel_dir),
            f"O={self.docker_manager.build_dir}",
            f"-j{os.cpu_count()}",
            "-s",
            "ARCH=" + arch,
            "LLVM=1",
            config_type,
        ]
        if extra_args:
            cmd.extend(extra_args)
        self.run_cmd_with_timer(
            cmd,
            cwd=str(self.docker_manager.build_dir),
            desc=config_type,
        )
