# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
from pathlib import Path
from .static_analysis import StaticAnalysis
from patchwise import SANDBOX_PATH
from patchwise.patch_review.decorators import (
    register_static_analysis_review,
    register_long_review,
)


@register_static_analysis_review
@register_long_review
class DtbsCheck(StaticAnalysis):
    """
    Performs static analysis on kernel commits to check Device Tree bindings
    using dtbs_check for both arm and arm64 architectures.
    """

    DEPENDENCIES = []

    def __run_dtbs_check(self, sha: str) -> str:
        kernel_tree = str(self.repo.working_tree_dir)
        log_dir = Path(SANDBOX_PATH) / "dtbs-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        logfile = log_dir / f"build-dtbs-{sha}.log"
        cfg_opts = [
            "CONFIG_ARM64_ERRATUM_843419=n",
            "CONFIG_ARM64_USE_LSE_ATOMICS=n",
            "CONFIG_BROKEN_GAS_INST=n",
        ]

        arch = "arm64"  # TODO loop through both arm and arm64
        super().make_config(
            arch=arch, extra_args=cfg_opts
        )  # TODO use _make_allmodconfig
        dtbs_check_output = super().run_cmd_with_timer(
            cmd=[
                "make",
                f"-j{os.cpu_count()}",
                "-s",
                f"O={self.build_dir}",
                f"ARCH={arch}",
                "LLVM=1",
                "dtbs_check",
            ]
            + cfg_opts,
            cwd=kernel_tree,
            desc=f"dtbs_check",
        )
        # logfile.write_text(dtbs_check_output) # TODO log to file and check for cache
        return dtbs_check_output

    def __get_unique_lines(self, baseline_log: str, new_log: str) -> str:
        last_lines = set(baseline_log.splitlines())
        current_lines = set(new_log.splitlines())
        unique_lines = current_lines - last_lines
        return "\n".join(unique_lines)

    def setup(self) -> None:
        pass

    def run(self) -> str:
        self.logger.debug("Running dtbs_check analysis")

        modified_files = [str(f) for f in self.commit.stats.files.keys()]
        dt_files = [f for f in modified_files if f.endswith((".yaml", ".dts", ".dtsi"))]
        if not dt_files:
            self.logger.debug("No modified DT schema files found, skipping dtbs_check")
            return ""
        self.logger.debug(f"Modified DT files: {dt_files}")

        self.logger.debug(
            f"Running dtbs_check for base commit: {self.base_commit.message}"
        )
        self.apply_patches([self.base_commit])
        baseline_output = self.__run_dtbs_check(self.base_commit.hexsha)

        self.logger.debug(f"Running dtbs_check for patch commit: {self.commit.message}")
        self.apply_patches([self.commit])
        patch_output = self.__run_dtbs_check(self.commit.hexsha)

        diff_output = self.__get_unique_lines(baseline_output, patch_output)
        if not diff_output:
            self.logger.info("No dtbs_check errors found")

        return diff_output
