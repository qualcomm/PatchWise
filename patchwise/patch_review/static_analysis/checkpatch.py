# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os

from patchwise import SANDBOX_PATH
from patchwise.patch_review.ai_agent.agent import Agent
from patchwise.patch_review.decorators import (
    register_short_review,
    register_static_analysis_review,
)
from patchwise.utils.config import parse_config

from .checkpatch_filter import filter_options, filter_report
from .static_analysis import StaticAnalysis


@register_static_analysis_review
@register_short_review
class Checkpatch(StaticAnalysis):
    """
    Perform static analysis on kernel commits using the checkpatch.pl script.
    """

    def setup(self) -> None:
        pass

    def run(self) -> str:
        raw = self.docker_manager.run_cmd_with_timer(
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
                self.commit.hexsha,
            ],
            cwd=str(self.docker_manager.kernel_dir),
            desc="checkpatch",
        )

        if not raw:
            return raw
        try:
            enabled, model = filter_options(parse_config())
            if not enabled:
                return raw
            # Preserve root-commit support and use the same diff as checkpatch.
            diff = self.repo.git.show(self.commit.hexsha, format="", root=True)
            message = str(self.commit.message)
        except Exception as exc:
            self.logger.warning(
                "Checkpatch AI filter unavailable; keeping original: %s", exc
            )
            return raw

        def complete_json(messages, validate):
            agent = Agent(self.docker_manager.repo_path, self.docker_manager)
            return agent.complete_until_json(messages, validate, model=model)

        return filter_report(
            raw,
            message,
            diff,
            complete_json,
            SANDBOX_PATH / "checkpatch_filter" / self.commit.hexsha,
        )
