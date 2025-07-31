# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
from pathlib import Path
from git.objects.commit import Commit
from .static_analysis import StaticAnalysis
from patchwise import SANDBOX_PATH
from patchwise.patch_review.decorators import register_static_analysis_review, register_long_review


@register_static_analysis_review
@register_long_review
class DtCheck(StaticAnalysis):
    """
    Performs static analysis on kernel commits to check Device Tree bindings
    using dt_binding_check.
    """

    DEPENDENCIES = []

    def __make_refcheckdocs(self) -> str:
        self.logger.debug("Making refcheckdocs")
        output = super().run_cmd_with_timer(
            [
                "make",
                f"-j{os.cpu_count()}",
                "-s",
                f"O={self.build_dir}",
                "ARCH=arm",
                "LLVM=1",
                "refcheckdocs",
            ],
            cwd=str(self.repo.working_tree_dir),
            desc="refcheckdocs",
        )
        return output.strip()

    def __make_dt_binding_check(self) -> str:
        self.logger.debug("Making dt_binding_check")
        output = super().run_cmd_with_timer(
            cmd=[
                "make",
                f"-j{os.cpu_count()}",
                "-s",
                f"O={self.build_dir}",
                "ARCH=arm",
                "LLVM=1",
                "DT_CHECKER_FLAGS=-m",
                "dt_binding_check",
            ],
            cwd=str(self.repo.working_tree_dir),
            desc="dt_binding_check",
        )
        return output.strip()

    def __get_unique_lines(self, baseline_log: str, new_log: str) -> str:
        last_lines = set(baseline_log.splitlines())
        current_lines = set(new_log.splitlines())
        unique_lines = current_lines - last_lines
        return "\n".join(unique_lines)

    def __get_dt_checker_logs(self, commit: Commit) -> tuple[str, str]:
        # TODO Extract yamllint warnings/errors
        """
        Retrieves and caches dt_checker logs for a given kernel tree and SHA.
        Logs are saved to files in the 'dt-checker-logs' folder.
        """
        logs_dir = Path(SANDBOX_PATH) / "dt-checker-logs"
        refcheckdocs_log_path = logs_dir / f"{commit.hexsha}_refcheckdocs.log"
        dt_binding_check_log_path = logs_dir / f"{commit.hexsha}_dt_binding_check.log"

        self.logger.debug(f"Running dt-checker on: {commit.hexsha}")

        logs_dir.mkdir(parents=True, exist_ok=True)

        if dt_binding_check_log_path.exists() and refcheckdocs_log_path.exists():
            self.logger.debug(f"Using cached dt_binding_check logs for: {commit.hexsha}")
        else:
            self.apply_patches([commit])
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
        super().make_config() # TODO change back to _make_allmodconfig
        base_refcheck, base_binding = self.__get_dt_checker_logs(self.base_commit)
        patch_refcheck, patch_binding = self.__get_dt_checker_logs(self.commit)

        refcheckdocs_output = self.__get_unique_lines(base_refcheck, patch_refcheck)
        dt_binding_check_output = self.__get_unique_lines(base_binding, patch_binding)

        if not refcheckdocs_output and not dt_binding_check_output:
            self.logger.info("No dt-checker errors")
            return output
        if len(refcheckdocs_output) > 0:
            output += f"refcheckdocs:\n{refcheckdocs_output}\n"
        if len(dt_binding_check_output) > 0:
            output += f"dt_binding_check:\n{dt_binding_check_output}\n"

        return output
