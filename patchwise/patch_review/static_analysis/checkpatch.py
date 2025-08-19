# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os

from patchwise.patch_review.decorators import (
    register_short_review,
    register_static_analysis_review,
    register_patch_files_review,
)

from .static_analysis import StaticAnalysis


@register_static_analysis_review
@register_short_review
@register_patch_files_review
class Checkpatch(StaticAnalysis):
    """
    Perform static analysis on kernel commits using the checkpatch.pl script.
    """

    DEPENDENCIES = []

    def setup(self) -> None:
        pass

    def run(self) -> str:
        checkpatch_cmd = [
            os.path.join("scripts", "checkpatch.pl"),
            "--quiet",
            "--subjective",
            "--strict",
            "--showfile",
            "--show-types",
            "--codespell",
            "--mailback",
            "--ignore",
            ",".join(
                [
                    # We review patches one at a time and don't try to apply to
                    # tree. So, checkpatch will not see that earlier patch adds
                    # the DT string
                    "UNDOCUMENTED_DT_STRING",
                    "FILE_PATH_CHANGES",
                    "CONFIG_DESCRIPTION",
                ]
            ),
        ]

        if self.commit and self.base_commit:
            self.logger.debug("Checkpatch: Running in Git commit mode.")
            checkpatch_cmd.append("--git")
            checkpatch_cmd.append(self.base_commit.hexsha + "..." + self.commit.hexsha)
            current_working_directory = str(self.repo.working_tree_dir) if self.repo else os.getcwd()
        elif self.patch_files:
            self.logger.debug("Checkpatch: Running in patch file mode.")
            checkpatch_cmd.extend(map(str, self.patch_files))
            current_working_directory = str(self.repo.working_tree_dir) if self.repo else os.getcwd()

        else:
            self.logger.error("No valid input (commits or patch_files) for Checkpatch review.")
            return "Error: No input provided for Checkpatch review."

        return self.run_cmd_with_timer(
            checkpatch_cmd,
            cwd=current_working_directory,
            desc="checkpatch",
        )
