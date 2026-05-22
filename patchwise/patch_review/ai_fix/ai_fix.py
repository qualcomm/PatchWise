# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import logging
from pathlib import Path

from patchwise import PACKAGE_NAME
from patchwise.patch_review.ai_agent.agent import Agent
from patchwise.patch_review.patch_review import PatchReview


class AiFix:
    @classmethod
    def get_logger(cls) -> logging.Logger:
        return logging.getLogger(f"{PACKAGE_NAME}.{cls.__name__.lower()}")

    def __init__(self, patch_review: PatchReview, review_result: str):
        self.logger = self.get_logger()
        self.patch_review = patch_review
        self.review_result = review_result
        self.agent = Agent(
            Path(self.patch_review.repo.working_dir),
            self.patch_review.docker_manager,
            enable_edit_tools=True,
        )

    def run(self):
        # subclasses override and fix the issues in review_result
        pass
