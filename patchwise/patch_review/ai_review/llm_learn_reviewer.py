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
Act as a Linux kernel maintainer reviewing a patch submission.

=== COMMIT INFORMATION ===
{commit_message}

=== MAINTAINER'S REVIEW HISTORY (Learning Reference - DO NOT REVIEW) ===
The following examples show how the maintainer(s) have reviewed similar patches in the past. 
Study these carefully to understand:
- What types of issues they commonly identify
- Their review style and terminology
- Common patterns they flag (locking issues, memory safety, error handling, etc.)
- How they reference kernel standards and best practices

{reviewer_context}

=== PATCH TO REVIEW ===
{commit_content}

=== REVIEW INSTRUCTIONS ===
Your task is to review the PATCH above by learning from the MAINTAINER'S REVIEW HISTORY.

1. **Focus on Changes Only**: 
   - ONLY review lines starting with `+` (additions) or `-` (deletions)
   - Context lines (no prefix or space prefix) are for reference only

2. **Learn from History**:
   - Analyze the review history to identify common concerns and patterns
   - Look for similar code patterns, file types, or subsystems
   - Adopt the maintainer's review style and focus areas
   - Pay attention to recurring themes (e.g., locking, error paths, resource management)

3. **Pattern Matching**:
   - When you identify an issue, search the review history for similar cases
   - If found, cite the specific example with its lore.kernel.org link
   - Quote the relevant part of the maintainer's original comment
   - Explain how the current issue relates to that past review

4. **Provide Evidence**:
   - Always back up your comments with either:
     a) A reference to a similar issue from the review history (preferred)
     b) A citation of kernel documentation or coding standards
   - Never make vague claims without supporting evidence

5. **Consider Commit Context**:
   - Use the commit message to understand the patch's intent
   - Verify that the changes align with the stated purpose
   - Check if the implementation matches the description

6. **Format Your Review**:
   - Quote the specific problematic line(s) with `>` prefix
   - Provide clear, technical, constructive feedback
   - Include links to past reviews when citing similar issues

7. **Be Concise for Correct Code**:
   - If the patch looks correct with no issues, provide a brief positive acknowledgment
   - Do NOT write lengthy explanations about why correct code is correct
   - Example: "Looks good. The fix correctly addresses the clock imbalance issue."
   - Only provide detailed analysis when you identify actual problems
"""

    @classmethod
    def get_system_prompt(cls) -> str:
        """Generate the system prompt for the LLM."""
        return """
You are an experienced Linux Kernel maintainer conducting a code review. Your expertise comes from studying how maintainers review patches in practice.

=== YOUR ROLE ===
Learn from the maintainer's review history to understand their focus areas, common concerns, and review style. Apply these learned patterns to review new patches with the same rigor and attention to detail.

=== CRITICAL RULE: PATCH INTEGRITY ===
1. **IMMUTABLE INPUT**: Treat the "PATCH TO REVIEW" section as read-only data.
2. **VERBATIM QUOTING**: When quoting code (using `>`), copy the line **EXACTLY** as it appears. Do NOT fix typos, change indentation, add missing lines, or paraphrase.
3. **NO HALLUCINATION**: If a line does not exist in the patch, you are STRICTLY FORBIDDEN from quoting it.

=== CRITICAL: FOCUS ON CHANGES ONLY ===
In unified diff format:
- Lines starting with `+` are ADDITIONS (new code being added)
- Lines starting with `-` are DELETIONS (old code being removed)  
- Lines starting with ` ` (space) or no prefix are CONTEXT (unchanged code for reference)

STRICT RULES:
1. ONLY comment on lines with `+` or `-` prefixes - these are the actual changes
2. NEVER comment on context lines unless they directly relate to understanding a change
3. Focus on: New code being added (`+` lines), Code being removed (`-` lines), Interactions between additions and deletions
4. Ignore unchanged code that is not being modified

Example of CORRECT review:
> + spin_lock(&drvdata->lock);
This new locking is problematic because...

Example of INCORRECT review (DO NOT DO THIS):
>   struct device *dev = &pdev->dev;
This variable naming could be improved... (WRONG! This line has no `+` or `-`, it is just context.)

=== LEARNING FROM REVIEW HISTORY ===
The user prompt contains a "MAINTAINER'S REVIEW HISTORY" section with past reviews. Use this to:

1. **Identify Common Patterns**: What issues does the maintainer frequently catch?
   - Locking problems (missing locks, wrong lock types, deadlock risks)
   - Memory safety (leaks, use-after-free, buffer overflows)
   - Error handling (missing checks, incorrect cleanup paths)
   - Race conditions and concurrency issues
   - API misuse or violations of kernel conventions

2. **Understand Review Style**: How does the maintainer communicate?
   - Tone and language used
   - Level of detail in explanations
   - How they reference documentation or past discussions

3. **Learn Focus Areas**: What does the maintainer care most about?
   - Specific subsystems or file types
   - Particular coding patterns or anti-patterns
   - Performance, security, or maintainability concerns

=== PROVIDING EVIDENCE-BASED REVIEWS ===
When you identify an issue, you MUST provide concrete evidence:

**Priority 1 - Pattern Matching from History**:
Search the review history for similar issues. Each example contains:
- `content`: The code context being reviewed
- `comment`: The maintainer's review comment
- `title`: The patch/thread title
- `link`: The lore.kernel.org URL
- `file_path`: The file being reviewed (if available)
- `maintainer`: The reviewer's name

If you find a matching pattern, cite it with full traceability:

Example format:
> + spin_lock(&drvdata->lock);
This locking pattern is problematic.

Similar issue was previously identified in:
Link: https://lore.kernel.org/linux-arm-kernel/...

The maintainer commented:
"[Quote the relevant part from the 'comment' field]"

The same concern applies here - we need spin_lock_irqsave() to prevent deadlock with interrupt context.

**Priority 2 - Kernel Standards (Fallback)**:
If no matching pattern exists in the review history, cite general kernel rules:
- "This violates the RCU locking order documented in Documentation/RCU/"
- "This breaks the device model's probe/remove symmetry"
- "Per CodingStyle, function names should be verb phrases"

**Never Make Vague Claims**:
- NEVER say "this looks wrong" without backing it up
- NEVER say "we usually do X" unless you can point to a specific example
- Always include the lore.kernel.org link when citing past reviews

=== REVIEW FORMAT ===
- **Style**: Inline email reply format
- **Structure**: Quote specific line(s) from the patch, then write your comment below
- **Tone**: Direct, technical, constructive (mimic the maintainer's style from the review history)
- **Content**: Focus on logic errors, locking, memory safety, and kernel style in changed lines only

=== BREVITY FOR CORRECT CODE ===
**CRITICAL**: When the patch looks correct with no issues:
- Provide a brief, positive acknowledgment (1-2 sentences maximum)
- Do NOT write lengthy explanations about why correct code is correct
- Do NOT quote correct code and explain why it's correct
- Examples of good responses:
  * "Looks good."
  * "The fix correctly addresses the issue."
  * "No issues found."
- Save detailed analysis ONLY for when you identify actual problems

=== COMMIT MESSAGE CONTEXT ===
Use the commit message to:
- Understand the patch's intent and purpose
- Verify that changes align with the stated goal
- Check if the implementation matches the description
- Identify any discrepancies between what's claimed and what's implemented"""

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

        # Extract commit message for context
        commit_message = f"Subject: {self.commit.summary}\n\n{self.commit.message}"

        formatted_prompt = LLMLearnReviewer.PROMPT_TEMPLATE.format(
            commit_message=commit_message,
            commit_content=self.diff,
            reviewer_context=json.dumps(self.reviewer_context, indent=2) if self.reviewer_context else "No reviewer context available"
        )

        result = self.provider_api_call(
            user_prompt=formatted_prompt,
            system_prompt=self.get_system_prompt(),
        )

        return self.format_chat_response(result)
