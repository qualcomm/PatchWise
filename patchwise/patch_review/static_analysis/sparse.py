# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
import re
import subprocess

from git import GitCommandError

from patchwise.patch_review.decorators import (
    register_long_review,
    register_static_analysis_review,
)
from .static_analysis import StaticAnalysis


@register_static_analysis_review
@register_long_review
class Sparse(StaticAnalysis):
    """
    Performs static analysis on kernel commits using the sparse tool.

    Methods:
        run():
            Runs sparse and returns the results corresponding to the patch sha.
    """

    def setup(self) -> None:
        pass

    def run(self) -> str:
        logger = self.logger
        kernel_tree = str(self.repo.working_tree_dir)

        logger.debug("Sparse.run() called")

        logger.debug("Running defconfig")
        super().make_config(arch="arm64")  # TODO change back to _make_allmodconfig

        sparse_log_pattern = re.compile(
            r"(?P<filepath>.+):(?P<linenum>\d+):(?P<column>\d+): (?P<message>.+)"
        )

        # TODO use modified_files = set(self.commit.stats.files.keys())
        diff = self.repo.git.diff(
            "--name-only", f"{self.base_commit}..{self.commit}"
        ).splitlines()
        files_changed = [os.path.join(kernel_tree, f.strip()) for f in diff]
        for f in files_changed:
            logger.debug(f"Touching {f}")
            subprocess.run(["touch", f], check=True)

        logger.debug("Running sparse check")
        sparse_warnings = super().run_cmd_with_timer(
            [
                "make",
                f"O={self.build_dir}",
                f"-j{os.cpu_count()}",
                "ARCH=arm64",
                "LLVM=1",
                "C=1",
                "-s",
                "CHECK=sparse",
            ],
            desc="sparse check",
        )

        output = ""
        for line in sparse_warnings.splitlines():
            match = re.match(sparse_log_pattern, line)
            # Avoids make's logs and only processes sparse warnings
            if match:
                filepath = match.group("filepath")
                linenum = match.group("linenum")
                # The git blame call below is expensive; run it only on files changed
                if os.path.join(kernel_tree, filepath.strip()) not in files_changed:
                    continue

                try:
                    blame_output = self.repo.git.blame(
                        f"-L{linenum},+1",
                        f"{self.base_commit}..{self.commit}",
                        "-l",
                        "--",
                        filepath,
                    )
                    # Only include if the current commit is blamed
                    if not blame_output.startswith("^"):
                        # Strip kernel_tree prefix from the line's filepath
                        if line.startswith(kernel_tree + "/"):
                            stripped_line = line[len(kernel_tree) + 1 :]
                        else:
                            stripped_line = line
                        output += stripped_line + "\n"
                except GitCommandError:
                    # File not found in the commit
                    continue

        return output
