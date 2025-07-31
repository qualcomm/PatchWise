# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
from patchwise.patch_review.patch_review import PatchReview


class StaticAnalysis(PatchReview):
    """
    Base class for performing static analysis on kernel commits.

    This class defines the interface and common methods for all static analysis
    tools. Subclasses should override the `run` method.
    """

    def clean_tree(self, arch: str = "arm"):
        self.logger.debug("Cleaning kernel tree")
        self.run_cmd_with_timer(
            [
                "make",
                f"-j{os.cpu_count()}",
                "-s",
                "ARCH=" + arch,
                "LLVM=1",
                "mrproper",
            ],
            cwd=str(self.repo.working_tree_dir),
            desc="Cleaning tree",
        )

    def make_config(
        self,
        config_type: str = "defconfig",
        arch: str = "arm",
        extra_args: list[str] = [],
    ) -> None:
        self.logger.debug(f"Making {config_type}")
        cmd = [
            "make",
            f"O={self.build_dir}",
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
            cwd=str(self.repo.working_tree_dir),
            desc=config_type,
        )
