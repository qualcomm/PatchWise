# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os

from patchwise.patch_review.decorators import register_llm_review, register_short_review

from .ai_review import AiReview


@register_llm_review
@register_short_review
class LLMCommitAudit(AiReview):
    DEPENDENCIES = getattr(AiReview, "DEPENDENCIES", [])

    @staticmethod
    def _load_prompt_template() -> str:
        """Load the prompt template from the markdown file."""
        template_path = os.path.join(
            os.path.dirname(__file__), "prompts", "commit_audit_prompt.md"
        )
        try:
            with open(template_path, "r") as f:
                return f.read()
        except Exception as e:
            raise RuntimeError(f"Failed to load commit audit prompt template: {e}")

    def setup(self) -> None:
        super().setup()

    def run(self) -> str:
        prompt_template = self._load_prompt_template()
        formatted_prompt = prompt_template.format(
            diff=self.diff,
            commit_text=str(self.commit_message),
        )

        result = self.provider_api_call(
            formatted_prompt,
            self.model,
        )

        return self.format_chat_response(result)
