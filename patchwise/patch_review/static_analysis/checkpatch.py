# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
from .static_analysis import StaticAnalysis
from patchwise.patch_review.decorators import register_static_analysis_review, register_short_review


@register_static_analysis_review
@register_short_review
class Checkpatch(StaticAnalysis):
    """
    Perform static analysis on kernel commits using the checkpatch.pl script.
    """

    DEPENDENCIES = []

    def setup(self) -> None:
        pass

    def run(self) -> str:
        return self.run_cmd_with_timer(
            [
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
                "--git",
                self.base_commit.hexsha + "..." + self.commit.hexsha,
            ],
            cwd=str(self.repo.working_tree_dir),
            desc="checkpatch",
        )
