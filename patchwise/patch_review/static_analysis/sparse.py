# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
import re
import subprocess
import tempfile
from git import GitCommandError

from .static_analysis import StaticAnalysis
from patchwise.patch_review.decorators import register_static_analysis_review, register_long_review
from patchwise import SANDBOX_PATH
from patchwise.patch_review.patch_review import Dependency

MINIMUM_CLANG_VERSION = 14
MINIMUM_SPARSE_VERSION = "0.6.4"

class SparseDependency(Dependency):

    # TODO if installing to SANDBOX_PATH and the version still does not work, the user will need to manually clear the SANDBOX_PATH folder because SANDBOX_PATH is at the start of the PATH
    def install_from_source(self) -> None:
        """
        Install sparse from source.
        """
        self.logger.info(f"Installing {self.name} from source...")
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = os.path.join(tmpdir, "sparse")
            subprocess.run(["git", "clone", "git://git.kernel.org/pub/scm/devel/sparse/sparse.git", src_dir], check=True)
            subprocess.run(["make"], cwd=src_dir, check=True)
            subprocess.run(["sudo", "make", f"PREFIX={SANDBOX_PATH}", "install"], cwd=src_dir, check=True)

    def _do_install(self) -> None:
        super().install_from_pkg_manager()
        # Check if the correct version of sparse is installed
        try:
            super().check()
        except ImportError as e:
            self.logger.warning(f"{e}")
            self.install_from_source()

@register_static_analysis_review
@register_long_review
class Sparse(StaticAnalysis):
    """
    Performs static analysis on kernel commits using the sparse tool.

    Methods:
        run():
            Runs sparse and returns the results corresponding to the patch sha.
    """

    DEPENDENCIES = [
        Dependency(
            name="llvm-config",
            min_version=MINIMUM_CLANG_VERSION,
        ),
        Dependency(
            name="clang",
            min_version=MINIMUM_CLANG_VERSION,
        ),
        Dependency(
            name="ld.lld",
            min_version=MINIMUM_CLANG_VERSION,
        ),
        # Dependency(
        #     name="lld",
        # ),
        SparseDependency(
            name="sparse",
            min_version=MINIMUM_SPARSE_VERSION,
        ),
    ]

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
            cwd=str(self.repo.working_tree_dir),
            desc="sparse check",
            # stdout=subprocess.DEVNULL,
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
                            stripped_line = line[len(kernel_tree) + 1:]
                        else:
                            stripped_line = line
                        output += stripped_line + "\n"
                except GitCommandError:
                    # File not found in the commit
                    continue

        return output
