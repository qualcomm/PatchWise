# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from litellm.exceptions import APIError as LitellmAPIError

from patchwise.patch_review.ai_review.fp_tools.config import (
    DEFAULT_LLM_API_BASE,
    DEFAULT_LLM_MODEL,
    DEFAULT_VERIFY_MAX_TOKENS,
    configure_litellm_client,
)
from patchwise.patch_review.ai_agent.agent import Agent
from patchwise.patch_review.ai_review.ai_code_review import AiCodeReview
from patchwise.patch_review.ai_review.fp_tools.false_positive_issue_db import get_fp_db

logger = logging.getLogger(__name__)


class LlmApiError(RuntimeError):
    pass


MODEL = DEFAULT_LLM_MODEL
API_BASE = DEFAULT_LLM_API_BASE
MAX_TOKENS = DEFAULT_VERIFY_MAX_TOKENS

_SYSTEM_PROMPT = """\
You are an expert Linux kernel engineer reviewing patch history.

Your task:
  - You will be given Patchwise AI code reviews from every version of a patch
    series (v1 through vf) and the unified diff of the FINAL accepted version.
  - Read ALL the code review sections across every version.
  - For each distinct issue raised in ANY version, decide whether the FINAL
    diff FULLY resolves it.
  - Return ONLY the issues that are NOT fixed in the final diff.
  - A single patch version may have multiple unfixed issues — emit one entry
    per issue, each with the same patch_title but distinct issue_description.

Output format — strict JSON array only, no markdown fences, no prose:

[
  {
    "patch_title":       "<exact subject line of the patch version where this issue was found>",
    "code_snippet":      "<only the directly affected lines — no context, no diff headers>",
    "issue_description": "<one or two sentences — the specific defect only>",
    "reason_not_fixed":  "<one sentence — what is still wrong in the final diff>"
  }
]

If ALL issues are fixed, return an empty array: []

Rules:
- Output ONLY a valid JSON array — no extra text, no markdown.
- Include an entry only when the final diff does NOT fully address the issue.
- Partial fixes count as not fixed.
- "patch_title" must be the exact subject line printed in the reviews.
- One JSON object per issue — if a version has 3 unfixed issues, emit 3 objects
  all with the same patch_title but each with a distinct issue_description.
- "code_snippet": affected lines only. Empty string if not applicable.
- "issue_description": plain technical terms, max two sentences.
- "reason_not_fixed": one sentence citing the exact location still problematic.
"""

_USER_PROMPT = """\
═══════════════════════════════════════════════════════════════════════
CODE REVIEWS (all versions)
═══════════════════════════════════════════════════════════════════════

{all_reviews}

═══════════════════════════════════════════════════════════════════════
FINAL PATCH DIFF
═══════════════════════════════════════════════════════════════════════

{final_diff}
"""


@dataclass
class UnfixedIssue:
    patch_title: str
    issue_label: str
    code_snippet: str
    issue_description: str
    reason_not_fixed: str
    message_id: str = ""


class UnfixedIssueCollector:
    """Collect and store unfixed review issues for one patch."""

    def __init__(
        self,
        model: Optional[str] = MODEL,
        api_base: Optional[str] = API_BASE,
    ) -> None:
        self._model = model
        self._api_base = api_base

    def extract_and_store(self, patch_issues) -> None:
        db = get_fp_db()
        if not db.is_available():
            logger.warning("FalsePositiveDB unavailable — skipping '%s'", patch_issues.patch_title)
            return

        unfixed_issues = self.unfixed_issue_collector(patch_issues, db=db)
        if not unfixed_issues:
            logger.debug("All issues fixed in vf for '%s'", patch_issues.patch_title)
            return

        stored = 0
        for issue in unfixed_issues:
            try:
                if db.add_false_positive_issue(
                    patch_title=issue.patch_title,
                    code_snippet=issue.code_snippet,
                    issue_description=issue.issue_description,
                    reason=issue.reason_not_fixed,
                    issue_label=issue.issue_label,
                    message_id=issue.message_id,
                ):
                    stored += 1
            except ValueError as exc:
                logger.warning("Skipping '%s': %s", issue.issue_label, exc)
        logger.info("Stored %d unfixed issue(s) for '%s'", stored, patch_issues.patch_title)

    def unfixed_issue_collector(self, patch_issues, db=None) -> List[UnfixedIssue]:
        if not patch_issues.ai_issues:
            return []

        new_reviews = (
            [review for review in patch_issues.ai_issues if not db.has_review_message_id(review.message_id)]
            if db is not None
            else list(patch_issues.ai_issues)
        )
        if not new_reviews:
            logger.debug("All versions already indexed for '%s'", patch_issues.patch_title)
            return []

        msg_id_by_subject = {r.exact_subject: r.message_id for r in new_reviews}

        try:
            raw_issue_dicts = self._identify_unfixed_issues(new_reviews, patch_issues.final_diff)
        except (LlmApiError, json.JSONDecodeError, ValueError) as exc:
            logger.error("LLM error for '%s': %s", patch_issues.patch_title, exc)
            return []

        unfixed_issues = [
            UnfixedIssue(
                patch_title=str(raw_issue.get("patch_title", "")),
                issue_label=str(raw_issue.get("patch_title", "")),
                code_snippet=str(raw_issue.get("code_snippet", "")),
                issue_description=str(raw_issue.get("issue_description", "")),
                reason_not_fixed=str(raw_issue.get("reason_not_fixed", "")),
                message_id=msg_id_by_subject.get(str(raw_issue.get("patch_title", "")), ""),
            )
            for raw_issue in raw_issue_dicts
            if isinstance(raw_issue, dict) and raw_issue.get("issue_description", "").strip()
        ]

        counts = Counter(issue.patch_title for issue in unfixed_issues)
        seen: Counter = Counter()
        for issue in unfixed_issues:
            if counts[issue.patch_title] > 1:
                seen[issue.patch_title] += 1
                issue.issue_label = f"{issue.patch_title}_({seen[issue.patch_title]})"

        logger.debug("%d unfixed issue(s) for '%s'", len(unfixed_issues), patch_issues.patch_title)
        return unfixed_issues

    def _identify_unfixed_issues(self, version_reviews, final_diff: str) -> list:
        all_reviews = "\n\n".join(
            f"--- {review.exact_subject} ---\n\n{review.ai_review.strip()}"
            for review in version_reviews
        )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _USER_PROMPT.format(
                    all_reviews=all_reviews,
                    final_diff=final_diff,
                ),
            },
        ]
        return self._request_unfixed_issue_analysis(messages)

    def _request_unfixed_issue_analysis(self, messages: list) -> list:
        try:
            configure_litellm_client()
            logger.debug(
                f"Making API call with model: {self._model}, api_base: {self._api_base}"
            )
            response = Agent.completion_with_retry(
                model=self._model,
                api_base=self._api_base,
                messages=messages,
                stream=False,
                max_tokens=MAX_TOKENS,
            )
        except LitellmAPIError as exc:
            raise LlmApiError(str(exc)) from exc

        llm_response_text = response.choices[0].message.content or ""
        result = AiCodeReview._extract_json(llm_response_text)
        if result is None:
            raise ValueError("Could not parse LLM response as JSON")
        if not isinstance(result, list):
            raise ValueError(f"Expected JSON array, got {type(result).__name__}")
        return result


class _PatchReviewHistoryProxy:
    class _PatchVersionIssueReport:
        def __init__(self, d: dict) -> None:
            self.exact_subject: str = d.get("exact_subject", "")
            self.ai_review: str = d.get("ai_review", "")
            self.message_id: str = d.get("message_id", "")

    def __init__(self, d: dict) -> None:
        self.patch_title: str = d.get("patch_title", "")
        self.final_diff: str = d.get("final_diff", "")
        self.ai_issues = [self._PatchVersionIssueReport(vr) for vr in d.get("ai_issues", [])]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect unfixed issues from a PatchReviewHistory JSON and emit JSONL.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        required=True,
        help="PatchReviewHistory JSON file.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="JSONL output (default: stdout).",
    )
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--api-base", default=API_BASE, dest="api_base")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if not args.input.exists():
        logger.error("Input file not found: %s", args.input)
        sys.exit(1)

    try:
        input_json = json.loads(args.input.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse input JSON: %s", exc)
        sys.exit(1)

    unfixed_issues = UnfixedIssueCollector(model=args.model, api_base=args.api_base).unfixed_issue_collector(
        _PatchReviewHistoryProxy(input_json)
    )
    if not unfixed_issues:
        logger.debug("All issues fixed — nothing to emit.")
        return

    output_file = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout
    try:
        for issue in unfixed_issues:
            output_file.write(json.dumps(asdict(issue), ensure_ascii=False) + "\n")
    finally:
        if args.output:
            output_file.close()
            logger.info("Results → %s", args.output)


if __name__ == "__main__":
    main()
