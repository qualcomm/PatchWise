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

    def __get_dt_checker_logs(
        self, commit: Optional[Commit] = None
    ) -> tuple[Path, Path]:
        # TODO Extract yamllint warnings/errors
        """
        Retrieves and caches dt_checker logs for a given kernel tree and SHA.
        Logs are saved to files in the 'dt-checker-logs' folder. If both logs
        are already cached for `commit`, the cached paths are returned without
        rebuilding. Otherwise the kernel tree is reset to `commit` and the
        checks are run.
        
        Returns (refcheckdocs_log_path, dt_binding_check_log_path).
        """
        logs_dir = Path(SANDBOX_PATH) / "dt-checker-logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        if not commit:
            commit = self.commit

        refcheckdocs_log_path = logs_dir / f"{commit.hexsha}_refcheckdocs.log"
        dt_binding_check_log_path = logs_dir / f"{commit.hexsha}_dt_binding_check.log"

        if refcheckdocs_log_path.exists() and dt_binding_check_log_path.exists():
            self.logger.debug(f"Using cached dt-checker logs for {commit.hexsha}")
            return refcheckdocs_log_path, dt_binding_check_log_path

        super().make_config()

        self.logger.debug(f"Running dt-checker on: {commit.hexsha}")
        try:
            refcheckdocs_logs = self.__make_refcheckdocs()
            refcheckdocs_log_path.write_text(refcheckdocs_logs)
            self.logger.debug(f"Saved refcheckdocs logs to {refcheckdocs_log_path}")
        except KeyboardInterrupt:
            refcheckdocs_log_path.unlink(missing_ok=True)
            raise
        try:
            dt_binding_check_logs = self.__make_dt_binding_check()
            dt_binding_check_log_path.write_text(dt_binding_check_logs)
            self.logger.debug(
                f"Saved dt_binding_check logs to {dt_binding_check_log_path}"
            )
        except KeyboardInterrupt:
            dt_binding_check_log_path.unlink(missing_ok=True)
            raise

        return refcheckdocs_log_path, dt_binding_check_log_path

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

        parent_refcheck_path, parent_binding_path = None, None
        if self.commit.parents:
            super().reset_tree(self.commit.parents[0])
            parent_refcheck_path, parent_binding_path = self.__get_dt_checker_logs(
                self.commit.parents[0]
            )

        super().clean_tree()
        super().reset_tree(self.commit)
        refcheck_path, binding_path = self.__get_dt_checker_logs(self.commit)

        if parent_refcheck_path and parent_binding_path:
            refcheck = super().diff_new_records(parent_refcheck_path, refcheck_path)
            binding = super().diff_new_records(parent_binding_path, binding_path)
        else:
            refcheck = refcheck_path.read_text()
            binding = binding_path.read_text()

        if not refcheck and not binding:
            self.logger.info("No new dt-checker errors")
            return output
        if len(refcheck) > 0:
            output += f"refcheckdocs:\n{refcheck}\n"
        if len(binding) > 0:
            output += f"dt_binding_check:\n{binding}\n"

        return output
