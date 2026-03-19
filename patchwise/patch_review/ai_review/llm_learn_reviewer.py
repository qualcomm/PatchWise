# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import json
import os
import subprocess
import tempfile
from pathlib import Path

from git.objects.commit import Commit

from patchwise import SANDBOX_PATH
from patchwise.patch_review.decorators import register_llm_review
from .ai_review import AiReview
from .fetch_reviewer_comment import LoreCrawler

@register_llm_review
class LLMLearnReviewer(AiReview):

    PROMPT_TEMPLATE = """
Act as Linux kernel maintainer.

=== REFERENCE CONTEXT (Past Reviews with Links - DO NOT REVIEW) ===
-{reviewer_context}

=== PATCH TO REVIEW (Immutable Target) ===
-{commit_text}

Instructions: Review the 'PATCH TO REVIEW' above.
1. ONLY examine lines that start with `+` (additions) or `-` (deletions).
2. Ignore all context lines (lines without `+` or `-` prefix) - they are just for reference.
3. Find specific issues in the CHANGED lines only.
4. Quote the problematic line exactly (with its `+` or `-` prefix) starting with `>`.
5. Search the REFERENCE CONTEXT examples for similar issues.
6. If a match is found:  Include the lore.kernel.org link from that example, Quote the relevant part of Suzuki's original comment, Explain the connection to the current issue.
7. If no match, cite the relevant kernel standard.
8. Remember: Only review what is being CHANGED (+ or - lines), not the surrounding context.
"""

    @classmethod
    def get_system_prompt(cls) -> str:
        """Generate the system prompt for the LLM."""
        return """
You are a rigorous Linux Kernel maintainer. Your task is to REVIEW the provided patch.

=== CRITICAL RULE: PATCH INTEGRITY ===
1. **IMMUTABLE INPUT**: You must treating the "PATCH TO REVIEW" section as read-only data.
2. **VERBATIM QUOTING**: When you quote code to comment on it (using `>`), you must copy the line **EXACTLY** as it appears in the input. Do NOT fix typos in the quote. Do NOT change indentation. Do NOT add missing lines. Do NOT paraphrase.
3. **NO HALLUCINATION**: If a line does not exist in the "PATCH TO REVIEW" text provided by the user, you are STRICTLY FORBIDDEN from quoting it.

=== CRITICAL: FOCUS ON CHANGES ONLY ===
YOU MUST ONLY REVIEW LINES THAT ARE BEING MODIFIED IN THE PATCH. In a unified diff format: Lines starting with `+` are ADDITIONS (new code being added). Lines starting with `-` are DELETIONS (old code being removed). Lines starting with ` ` (space) or no prefix are CONTEXT (unchanged code for reference).

STRICT RULES:
1. ONLY comment on lines with `+` or `-` prefixes - these are the actual changes.
2. NEVER comment on context lines (lines without `+` or `-`) unless they directly relate to understanding a change.
3. Focus your review on: New code being added (`+` lines), Code being removed (`-` lines) - check if the removal is safe, The interaction between additions and deletions.
4. Ignore unchanged code - do not review existing code that is not being modified.

Example of CORRECT review:
> + spin_lock(&drvdata->lock);
This new locking is problematic because...

Example of INCORRECT review (DO NOT DO THIS):
>   struct device *dev = &pdev->dev;
This variable naming could be improved... (WRONG! This line has no `+` or `-`, it is just context.)

=== REVIEW STYLE ===
Format: Inline email reply. Quote the specific line(s) from the patch, then write your comment below. Tone: Direct, technical, constructive (mimicking the persona from "REFERENCE CONTEXT"). Content: Focus on logic errors, locking, memory safety, and kernel style in the changed lines only.

=== JUSTIFICATION & REFERENCES (CRITICAL) ===
When you flag an issue, you MUST provide concrete evidence for your reasoning:

1. Pattern Matching (Priority): Search the "REFERENCE CONTEXT" examples for similar issues that Suzuki has previously commented on. Each example in the context contains: Title (The patch/thread title), Link (The lore.kernel.org URL), Code context (The original code being reviewed), Suzuki's comment (The actual review comment). If you find a matching pattern, cite it with full traceability: Include the link to the original discussion, Quote the relevant part of Suzuki's original comment, Explain how the current issue mirrors that past case.

Example format: > + spin_lock(&drvdata->lock); This locking pattern is problematic.

Similar issue was raised in Link: https://lore.kernel.org/linux-arm-kernel/...

In that review, commented:
"[Quote the relevant part from 'Suzuki's comment' field]"

The same concern applies here - we need spin_lock_irqsave() to prevent deadlock with interrupt context.

2. Kernel Standards (Fallback): If no matching pattern exists in the reference examples, cite general kernel rules: "This violates the RCU locking order documented in Documentation/RCU/", "This breaks the device model's probe/remove symmetry", "Per CodingStyle, function names should be verb phrases".

3. No Vague Claims: NEVER say "this looks wrong" without backing it up. NEVER say "we usually do X" unless you can point to a specific example showing it. Always include the lore.kernel.org link when citing past reviews."""

    def fetch_reviewer_comment(self) -> None:
        # Check if reviewers list is empty to avoid division by zero
        if not self.reviewers:
            self.logger.warning("No reviewers found, skipping comment fetching")
            return

        self.logger.debug(f"Fetching reviewer comments for {len(self.reviewers)} reviewer(s)")
        all_docs = []

        # Process each reviewer
        for idx, maintainer in enumerate(self.reviewers, 1):
            self.logger.debug(f"Processing reviewer {idx}/{len(self.reviewers)}: {maintainer}")

            # Update config for this maintainer
            self.crawler_config["MAINTAINER"] = maintainer
            limit_per_reviewer = self.crawler_config["MAX_COMMENT"] // len(self.reviewers)
            self.crawler_config["LIMIT_PER_REVIEWER"] = limit_per_reviewer
            # Initialize crawler for this maintainer
            crawler = LoreCrawler(self.crawler_config, self.logger)

            # Check for cached data
            maintainer_name = maintainer.replace(" ", "_").replace("@", "_at_")
            cache_file = os.path.join(SANDBOX_PATH, f"crawled_{maintainer_name}.json")
            raw_docs = []

            if os.path.exists(cache_file):
                self.logger.debug(f"  Found cached data: {cache_file}")
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        cached_data = json.load(f)
                        raw_docs = cached_data[:limit_per_reviewer]
                        self.logger.debug(f"  Loaded {len(raw_docs)} cached records for {maintainer} (limited from {len(cached_data)})")
                except Exception as e:
                    self.logger.warning(f"  Failed to read cache: {e}, starting online crawling...")
                    raw_docs = crawler.run()
            else:
                self.logger.debug(f"  No cache found, starting LoreCrawler for {maintainer}...")
                raw_docs = crawler.run()

            if raw_docs:
                for doc in raw_docs:
                    doc["maintainer"] = maintainer
                all_docs.extend(raw_docs)
                self.logger.debug(f"  ✓ Added {len(raw_docs)} items from {maintainer}")
            else:
                self.logger.warning(f"  Could not get reviewer data for {maintainer}")
        if not all_docs:
            self.logger.warning("Could not get any reviewer data from any reviewer")
            return

        self.logger.debug(f"✓ Total captured: {len(all_docs)} reviewer context items from {len(self.reviewers)} reviewer(s)")
        self.reviewer_context = all_docs

    def get_reviewers_from_maintainer_script(self, commit: Commit, repo_path: str) -> None:
        """
        Use the kernel's get_maintainer.pl script to find reviewers for a commit.
        Args:
            commit: The git commit object
            repo_path: Path to the kernel repository
        Returns:
            List of reviewer names (without email addresses)
        """
        try:
            # Create a temporary file for the patch
            with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as tmp_file:
                # Generate patch for the commit
                patch_content = commit.repo.git.format_patch(
                    '-1', commit.hexsha, '--stdout'
                )
                tmp_file.write(patch_content)
                tmp_file_path = tmp_file.name
    
            # Path to get_maintainer.pl script
            get_maintainer_script = Path(repo_path) / 'scripts' / 'get_maintainer.pl'
    
            if not get_maintainer_script.exists():
                self.logger.warning(f"get_maintainer.pl script not found at {get_maintainer_script}")
                self.reviewers = []
                return
    
            # Run get_maintainer.pl script
            result = subprocess.run(
                ['perl', str(get_maintainer_script), tmp_file_path],
                capture_output=True,
                text=True,
                cwd=repo_path
            )
    
            # Clean up temporary file
            Path(tmp_file_path).unlink(missing_ok=True)
    
            if result.returncode != 0:
                self.logger.error(f"get_maintainer.pl failed: {result.stderr}")
                self.reviewers = []
                return
    
            # Parse output to extract reviewer names only
            # Filter out mailing lists (lines containing "open list")
            reviewers = []
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line and 'list' not in line.lower():
                    # get_maintainer.pl outputs lines like:
                    # "Name <email@domain.com> (role)"
                    # Extract only the name part before '<'
                    name = line.split('<')[0].strip()
                    # Remove any trailing quotes if present
                    name = name.strip('"').strip("'").strip()
                    if name:
                        reviewers.append(name)
    
            self.reviewers = reviewers
            self.logger.info(f"Found {len(reviewers)} reviewers: {reviewers}")
    
        except Exception as e:
            self.logger.error(f"Error running get_maintainer.pl: {e}")
            self.reviewers = []

    def setup(self) -> None:
        super().setup()

        # Initialize crawler configuration
        self.crawler_config = {
            "MAINTAINER": "",  # Will be set per reviewer
            "MAX_COMMENT": 20,  # Total comments to fetch across all reviewers
            "PROXY": None,
            "LIMIT_PER_REVIEWER": "",  # 0 means no limitation per crawler run
            "NOISE_KEYWORDS": [
                "applied", "applied, thanks", "applied, thanks.",
                "queued", "queued for", "thanks", "thanks.",
                "lgtm", "looks good to me",
                "acked", "picked up", "merged", "fine", "cheers", "...", "^^^", "reviewed-by", "+1"
            ],
            "NOISE_TECH": ["should", "could", "need", "issue", "problem", "bug",
                            "fix", "change", "modify", "suggest", "consider",
                            "however", "but", "instead", "better", "improve"],
            "NOISE_LENGTH": 100,
            "MAX_CONTEXT_LINES": 40
        }

        # Initialize reviewers list
        self.reviewers = []
        self.reviewer_context = []

    def run(self) -> str:
        self.get_reviewers_from_maintainer_script(self.commit, self.repo.working_dir)
        self.fetch_reviewer_comment()

        formatted_prompt = LLMLearnReviewer.PROMPT_TEMPLATE.format(
            diff=self.diff,
            commit_text=str(self.commit_message),
            reviewer_context=json.dumps(self.reviewer_context, indent=2) if self.reviewer_context else "No reviewer context available"
        )

        result = self.provider_api_call(
            user_prompt=formatted_prompt,
            system_prompt=self.get_system_prompt(),
        )

        return self.format_chat_response(result)
