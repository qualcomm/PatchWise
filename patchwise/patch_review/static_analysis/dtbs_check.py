# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
from pathlib import Path
from typing import Optional

from git.objects.commit import Commit

from patchwise import SANDBOX_PATH
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

    def __run_dtbs_check(self, commit: Optional[Commit] = None) -> Path:
        """Retrieves and caches dtbs_check log for a given kernel tree and SHA."""
        logs_dir = Path(SANDBOX_PATH) / "dt-checker-logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        if not commit:
            commit = self.commit

        dtbs_check_log_path = logs_dir / f"{commit.hexsha}_dtbs_check.log"

        if dtbs_check_log_path.exists():
            self.logger.debug(f"Using cached dtbs_check log for {commit.hexsha}")
            return dtbs_check_log_path

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

        self.logger.debug(f"Running dtbs_check on: {commit.hexsha}")
        try:
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
            dtbs_check_log_path.write_text(dtbs_check_output)
            self.logger.debug(f"Saved dtbs_check log to {dtbs_check_log_path}")
        except KeyboardInterrupt:
            dtbs_check_log_path.unlink(missing_ok=True)
            raise

        return dtbs_check_log_path

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

        parent_log = None
        if self.commit.parents:
            super().reset_tree(self.commit.parents[0])
            parent_log = self.__run_dtbs_check(self.commit.parents[0])

        super().clean_tree()
        super().reset_tree(self.commit)
        current_log = self.__run_dtbs_check(self.commit)

        if parent_log:
            output = super().diff_new_records(parent_log, current_log)
        else:
            output = current_log.read_text()

        if not output:
            self.logger.info("No new dtbs_check errors found")

        return output
