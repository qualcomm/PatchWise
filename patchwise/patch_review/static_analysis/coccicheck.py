# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
import re

from patchwise.patch_review.decorators import (
    register_short_review,
    register_static_analysis_review,
)

from .static_analysis import StaticAnalysis


@register_static_analysis_review
@register_short_review
class Coccicheck(StaticAnalysis):
    def _prepare_kernel_build(self) -> None:
        """Prepare the kernel build system for coccicheck."""
        self.logger.debug("Preparing kernel build system for coccicheck")
        kernel_dir = self.docker_manager.sandbox_path / "kernel"

        # First, run defconfig to set up basic configuration
        try:
            super().make_config(arch="arm64")
            self.logger.debug("Kernel configuration prepared successfully")
        except Exception as e:
            self.logger.warning(f"Failed to prepare kernel configuration: {e}")

        # Run make scripts to ensure coccicheck infrastructure is available
        try:
            super().run_cmd_with_timer(
                [
                    "make",
                    "-C",
                    str(kernel_dir),
                    f"O={self.docker_manager.build_dir}",
                    "ARCH=arm64",
                    "LLVM=1",
                    "scripts",
                ],
                cwd=str(self.docker_manager.build_dir),
                desc="preparing kernel scripts",
            )
            self.logger.debug("Kernel scripts prepared successfully")
        except Exception as e:
            self.logger.warning(f"Failed to prepare kernel scripts: {e}")
            # Continue anyway, coccicheck might still work

    def _run_coccicheck(self, directory: str) -> str:
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        coccicheck_output = super().run_cmd_with_timer(
            [
                "make",
                "-C",
                str(kernel_dir),
                f"O={self.docker_manager.build_dir}",
                f"-j{os.cpu_count()}",
                "ARCH=arm64",
                "LLVM=1",
                "-s",
                "coccicheck",
                f"M={directory}",
                "MODE=report",
                f"DEBUG_FILE={self.symlink_path}",
            ],
            cwd=str(self.docker_manager.build_dir),
            desc="coccicheck running",
        )
        return coccicheck_output

    def setup(self) -> None:
        # Create symlink /tmp/{package_name}_null -> /dev/null
        # Necessary to trick the coccicheck script into piping stdout to /dev/null otherwise it combines stdout and stderr for some reason
        package_name = __package__ or "coccicheck"
        self.symlink_path = f"/tmp/{package_name}_null"
        target = "/dev/null"
        if os.path.islink(self.symlink_path) or os.path.exists(self.symlink_path):
            os.remove(self.symlink_path)
        os.symlink(target, self.symlink_path)

    def run(self) -> str:
        # TODO make sure that setup() runs in order for run() to run
        self.logger.debug(f"Running cocci_check")

        # First, prepare the kernel build system
        self._prepare_kernel_build()

        output = ""
        modified_files = set(self.commit.stats.files.keys())
        line_re = re.compile(r"^([^:]+):\d+:\d+-\d+:.*")

        directories: set[str] = set()
        for item in self.commit.stats.files:
            dir_path = os.path.dirname(item)
            if dir_path:
                directories.add(dir_path)
        self.logger.debug(f"Directories containing modified files: {directories}")

        for directory in directories:
            self.logger.debug(f"Running coccicheck on directory: '{directory}'")
            cur_output = self._run_coccicheck(directory)
            if not cur_output:
                self.logger.debug(f"No coccicheck output for {directory}, skipping")
                continue

            self.logger.debug(f"Coccicheck output for {directory}:\n{cur_output}")
            for line in cur_output.splitlines():
                match = line_re.match(line)
                if not match:
                    continue
                file_path = match.group(1)
                if file_path.startswith("./"):
                    file_path = file_path[2:]
                full_path = os.path.join(directory, file_path)
                if full_path in modified_files:
                    output += line + "\n"

        return output
