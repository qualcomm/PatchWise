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

    @classmethod
    def _strip_trailers(cls, msg: str) -> str:
        """Drop attribution and routing trailers from a commit message.

        Shared by all AI fixers that amend the current HEAD commit message
        before generating an mbox-format patch.
        """
        stripped_trailers = (
            "co-authored-by",
            "signed-off-by",
            "reviewed-by",
            "acked-by",
            "tested-by",
            "cc",
            "change-id",
        )
        kept: list[str] = []
        for line in msg.splitlines():
            lower = line.strip().lower()
            if any(lower.startswith(f"{t}:") for t in stripped_trailers):
                continue
            kept.append(line)
        # Strip trailing blank lines
        while kept and not kept[-1].strip():
            kept.pop()
        return "\n".join(kept) + "\n"

    def _generate_git_patch(self) -> str:
        """Produce an mbox-format patch reflecting the AI's working-tree edits.

        The AI writes to the working tree via write tools inside the container.
        ``git format-patch`` only sees committed history, so we must first fold
        those working-tree edits into HEAD (amending the original patch commit)
        before formatting. Returns an empty string if there are no working-tree
        changes to commit.
        """
        kernel_dir = str(self.patch_review.docker_manager.kernel_dir)

        # No-op if the AI made no changes
        proc = self.patch_review.docker_manager.run_command(
            ["git", "diff", "--quiet", "HEAD"], cwd=kernel_dir
        )
        proc.communicate()
        if proc.returncode == 0:
            self.logger.debug("No working-tree changes from AI; no patch fix.")
            return ""

        # Read current commit message and strip trailers
        proc = self.patch_review.docker_manager.run_command(
            ["git", "log", "-1", "--format=%B"], cwd=kernel_dir
        )
        orig_msg, stderr = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git log failed: {stderr}")
        new_msg = self._strip_trailers(orig_msg)

        # Amend HEAD with the AI's edits
        proc = self.patch_review.docker_manager.run_interactive_command(
            ["git", "commit", "-a", "--amend", "-F", "-"],
            cwd=kernel_dir,
        )
        _stdout, stderr = proc.communicate(input=new_msg)
        if proc.returncode != 0:
            raise RuntimeError(f"git commit --amend failed: {stderr}")

        # Emit the updated patch as mbox
        proc = self.patch_review.docker_manager.run_command(
            [
                "git",
                "format-patch",
                "HEAD~1",
                "--stdout",
            ],
            cwd=kernel_dir,
        )
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git format-patch failed: {stderr}")
        return stdout.strip()

    def run(self):
        # subclasses override and fix the issues in review_result
        pass
