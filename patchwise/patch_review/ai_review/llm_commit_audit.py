# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from patchwise.patch_review.decorators import register_llm_review, register_short_review
from .ai_review import AiReview


@register_llm_review
@register_short_review
class LLMCommitAudit(AiReview):
    DEPENDENCIES = getattr(AiReview, "DEPENDENCIES", [])

    PROMPT_TEMPLATE = """
**Prompt:**
You are an AI language model tasked with evaluating commit text for patches sent to the Linux Kernel. Your goal is to ensure that the commit text adheres to the Linux Kernel's guidelines. Specifically, you should focus on the following areas:

Justification of Code Changes: Ensure that the commit text clearly explains why the code changes are necessary.
Correct Imperative Tense: Verify that the commit text is written in the correct imperative tense.
Problem Description: Confirm that the commit text sufficiently describes the problem that the code changes aim to address.
Additionally, your suggestions should avoid making the commit text overly detailed or verbose.

**Commit Text:**

```
{commit_text}
```

**Patch Details:**

```
{diff}
```

**Output:**

The format of the output should be as follows:
 - A short review.
 - Rewrite the commit text in imperative mode as needed and incorporates suggestions.
 - Briefly describe the changes made to the commit text.
 - A list of suggestions the author can take to make the commit text even better after incorporating your revisions.
Do not provide a rating.
The output should use only ASCII characters.
"""

    def setup(self) -> None:
        super().setup()

    def run(self) -> str:
        formatted_prompt = LLMCommitAudit.PROMPT_TEMPLATE.format(
            diff=self.diff,
            commit_text=str(self.commit_message),
        )

        result = self.provider_api_call(
            formatted_prompt,
            self.model,
        )

        return self.format_chat_response(result)
