# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
import re
from .static_analysis import StaticAnalysis
from patchwise.patch_review.decorators import (
    register_static_analysis_review,
    register_short_review,
)


@register_static_analysis_review
@register_short_review
class Coccicheck(StaticAnalysis):

    DEPENDENCIES = []

    def _run_coccicheck(self, directory: str) -> str:
        coccicheck_output = super().run_cmd_with_timer(
            [
                "make",
                f"O={self.build_dir}",
                f"-j{os.cpu_count()}",
                "ARCH=arm64",
                "LLVM=1",
                "-s",
                "coccicheck",
                f"M={directory}",
                "MODE=report",
                f"DEBUG_FILE={self.symlink_path}",  # if hasattr(self, 'symlink_path') else "DEBUG_FILE=/dev/null",
            ],
            cwd=str(self.repo.working_tree_dir),
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
