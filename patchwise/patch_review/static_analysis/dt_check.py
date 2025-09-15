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
class DtCheck(StaticAnalysis):
    """
    Performs static analysis on kernel commits to check Device Tree bindings
    using dt_binding_check.
    """

    def __make_refcheckdocs(self) -> str:
        self.logger.debug("Making refcheckdocs")
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        output = super().run_cmd_with_timer(
            [
                "make",
                "-C",
                str(kernel_dir),
                f"-j{os.cpu_count()}",
                "-s",
                f"O={self.docker_manager.build_dir}",
                "ARCH=arm",
                "LLVM=1",
                "refcheckdocs",
            ],
            cwd=str(self.docker_manager.build_dir),
            desc="refcheckdocs",
        )
        return output.strip()

    def __make_dt_binding_check(self) -> str:
        self.logger.debug("Making dt_binding_check")
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        output = super().run_cmd_with_timer(
            [
                "make",
                "-C",
                str(kernel_dir),
                f"-j{os.cpu_count()}",
                "-s",
                f"O={self.docker_manager.build_dir}",
                "ARCH=arm",
                "LLVM=1",
                "DT_CHECKER_FLAGS=-m",
                "dt_binding_check",
            ],
            cwd=str(self.docker_manager.build_dir),
            desc="dt_binding_check",
        )
        return output.strip()

    def __get_dt_checker_logs(self, commit: Optional[Commit] = None) -> tuple[str, str]:
        # TODO Extract yamllint warnings/errors
        """
        Retrieves and caches dt_checker logs for a given kernel tree and SHA.
        Logs are saved to files in the 'dt-checker-logs' folder.
        """
        logs_dir = Path(SANDBOX_PATH) / "dt-checker-logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        if not commit:
            commit = self.commit

        refcheckdocs_log_path = logs_dir / f"{commit.hexsha}_refcheckdocs.log"
        dt_binding_check_log_path = logs_dir / f"{commit.hexsha}_dt_binding_check.log"

        self.logger.debug(f"Running dt-checker on: {commit.hexsha}")
        refcheckdocs_logs = self.__make_refcheckdocs()
        refcheckdocs_log_path.write_text(refcheckdocs_logs)
        self.logger.debug(f"Saved refcheckdocs logs to {refcheckdocs_log_path}")
        dt_binding_check_logs = self.__make_dt_binding_check()
        dt_binding_check_log_path.write_text(dt_binding_check_logs)
        self.logger.debug(f"Saved dt_binding_check logs to {dt_binding_check_log_path}")

        return refcheckdocs_log_path.read_text(), dt_binding_check_log_path.read_text()

    def setup(self) -> None:
        self.logger.debug("Setting up dt-check")
        self.dt_files = [
            f
            for f in self.commit.stats.files.keys()
            if str(f).startswith("Documentation") and str(f).endswith(".yaml")
        ]
        if not self.dt_files:
            self.logger.debug("No modified dt files")
            return

        self.logger.debug(f"Modified dt files: {self.dt_files}")

    def run(self) -> str:
        output = ""

        if not self.dt_files:
            self.logger.debug("No modified dt files")
            return output

        self.logger.debug(f"Preparing kernel tree for dt checks")
        # super().clean_tree()
        super().make_config()  # TODO change back to _make_allmodconfig
        refcheck, binding = self.__get_dt_checker_logs(self.commit)

        if not refcheck and not binding:
            self.logger.info("No dt-checker errors")
            return output
        if len(refcheck) > 0:
            output += f"refcheckdocs:\n{refcheck}\n"
        if len(binding) > 0:
            output += f"dt_binding_check:\n{binding}\n"

        return output
