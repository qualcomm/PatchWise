# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""LLM-as-judge: decide whether fix commits address patchwise issues."""

from __future__ import annotations

import hashlib
import json
import logging
import warnings
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"


@dataclass
class JudgeVerdict:
    matches: bool
    reason: str


def _batch_response_format(n: int) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "judge_verdicts",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "verdicts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "matches": {"type": "boolean"},
                                "reason": {"type": "string"},
                            },
                            "required": ["matches", "reason"],
                            "additionalProperties": False,
                        },
                        "minItems": n,
                        "maxItems": n,
                    },
                },
                "required": ["verdicts"],
                "additionalProperties": False,
            },
        },
    }


_BATCH_PROMPT_HEADER = """\
You are evaluating whether kernel fix commits address specific bugs that a code
review reported on a buggy commit.

The code review reported the following issues on the buggy commit:

{issues_block}

Below are {n} candidate fix commits (each carrying a `Fixes:` tag pointing at
the buggy commit). For EACH candidate, decide whether it addresses the SPECIFIC
bug described in the issue it is paired with.

Ground every verdict in the diff. Identify the exact removed (`-`) and/or
added (`+`) line(s) that resolve the bug, and quote them in your reason.
If no such line exists in the diff, the answer is false.

Rules:
- "matches": true ONLY if you can point to a concrete diff line that fixes
  the SAME defect the issue describes.
- Topical similarity is not enough. Shared vocabulary (same file, same
  subsystem) does not count.
- If the fix removes the offending code entirely (revert / refactor) and
  the removed lines contain the defect, that counts as true.
- If the issue calls out a specific token (e.g. a misspelled word, a symbol
  name, a literal value), the diff must touch that exact token to count.

Candidates:

{candidates_block}

Reply with a JSON object containing a "verdicts" array of exactly {n} objects
in the same order as the candidates above. Each object:
  {{"matches": true | false, "reason": "<one short sentence quoting the specific diff line(s) relied on, or stating no such line exists>"}}
"""

_ISSUE_ITEM = "Issue #{idx}:\n<issue>\n{issue}\n</issue>"

_CANDIDATE_ITEM = """\
Candidate #{idx} (issue #{issue_idx}):
<fix_commit>
Subject: {fix_subject}

{fix_body}

--- diff (truncated) ---
{fix_diff}
</fix_commit>"""


def judge_matches_batch(
    pairs: list[tuple[str, str, str, str]],
    *,
    model: str,
    api_base: str | None,
    cache_dir: Path,
) -> list[JudgeVerdict]:
    """Judge all (issue, fix) pairs for one bug commit in a single LLM call.

    *pairs* is a list of (issue_text, fix_subject, fix_body, fix_diff).
    Returns a list of JudgeVerdict in the same order.
    """
    if not pairs:
        return []

    n = len(pairs)

    # Deduplicate issues for the header block; candidates reference by issue_idx.
    # Since multiple fixes may pair with the same issue text, collect unique issues.
    issue_texts = [p[0] for p in pairs]
    unique_issues: list[str] = []
    issue_idx_map: list[int] = []
    for text in issue_texts:
        if text not in unique_issues:
            unique_issues.append(text)
        issue_idx_map.append(unique_issues.index(text))

    issues_block = "\n\n".join(
        _ISSUE_ITEM.format(idx=i + 1, issue=text)
        for i, text in enumerate(unique_issues)
    )

    candidates_block = "\n\n".join(
        _CANDIDATE_ITEM.format(
            idx=i + 1,
            issue_idx=issue_idx_map[i] + 1,
            fix_subject=pairs[i][1].strip(),
            fix_body=pairs[i][2].strip(),
            fix_diff=pairs[i][3].strip(),
        )
        for i in range(n)
    )

    prompt = _BATCH_PROMPT_HEADER.format(
        issues_block=issues_block,
        n=n,
        candidates_block=candidates_block,
    )

    cache_path = _cache_path(prompt, model, cache_dir)
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return [JudgeVerdict(matches=bool(v["matches"]), reason=v["reason"]) for v in cached]

    import httpx
    import litellm

    from patchwise.utils.decorators import retry

    warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    litellm.client_session = httpx.Client(verify=False)

    @retry(
        max_retries=10,
        exceptions=(
            litellm.Timeout,
            litellm.RateLimitError,
            litellm.InternalServerError,
            litellm.OpenAIError,
        ),
    )
    def _call() -> object:
        return litellm.completion(
            model=model,
            api_base=api_base,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            response_format=_batch_response_format(n),
            allowed_openai_params=["response_format"],
        )

    response = _call()
    raw = response.choices[0].message.content
    verdicts = _parse_verdicts(raw, n)

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps([{"matches": v.matches, "reason": v.reason} for v in verdicts]),
        encoding="utf-8",
    )
    return verdicts


_DECODER = json.JSONDecoder(strict=False)


def _parse_verdicts(raw: str, expected: int) -> list[JudgeVerdict]:
    key_pos = raw.find('"verdicts"')
    if key_pos >= 0:
        start = raw.rfind("{", 0, key_pos)
    else:
        start = raw.find("{")

    if start < 0:
        logger.warning("Judge batch response has no JSON object: %r", raw[:200])
        return [JudgeVerdict(matches=False, reason=f"unparseable: {raw[:80]}")] * expected

    try:
        parsed, _ = _DECODER.raw_decode(raw, start)
    except json.JSONDecodeError as e:
        logger.warning("Judge batch raw_decode failed: %s\nraw: %r", e, raw[:200])
        return [JudgeVerdict(matches=False, reason=f"parse error: {raw[:80]}")] * expected

    items = parsed.get("verdicts", [])
    results: list[JudgeVerdict] = []
    for item in items[:expected]:
        results.append(JudgeVerdict(
            matches=bool(item.get("matches", False)),
            reason=str(item.get("reason", "")).replace("\n", " ").strip(),
        ))
    # Pad if the model returned fewer than expected (shouldn't happen with strict schema)
    while len(results) < expected:
        results.append(JudgeVerdict(matches=False, reason="missing verdict"))
    return results


def _cache_path(prompt: str, model: str, cache_dir: Path) -> Path:
    key = hashlib.sha256((model + "\x00" + prompt).encode()).hexdigest()
    return cache_dir / f"{key}.json"
