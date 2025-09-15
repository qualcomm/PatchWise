# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os

from patchwise.patch_review.decorators import (
    register_long_review,
    register_static_analysis_review,
)

from .static_analysis import StaticAnalysis


@register_static_analysis_review
@register_long_review
class DtbsCheck(StaticAnalysis):
    """
    Performs static analysis on kernel commits to check Device Tree bindings
    using dtbs_check for both arm and arm64 architectures.
    """

    DEPENDENCIES = []

    def __run_dtbs_check(self, sha: str) -> str:
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
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
                "-C",
                str(kernel_dir),
                f"-j{os.cpu_count()}",
                "-s",
                f"O={self.docker_manager.build_dir}",
                f"ARCH={arch}",
                "LLVM=1",
                "dtbs_check",
            ]
            + cfg_opts,
            cwd=str(self.docker_manager.build_dir),
            desc=f"dtbs_check",
        )
        # logfile.write_text(dtbs_check_output) # TODO log to file and check for cache
        return dtbs_check_output

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

        self.logger.debug(f"Running dtbs_check for commit: {self.commit.message}")
        output = self.__run_dtbs_check(self.commit.hexsha)

        if not output:
            self.logger.info("No dtbs_check errors found")

        return output
