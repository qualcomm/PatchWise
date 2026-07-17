# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from datetime import datetime, timezone
from email import utils as email_utils
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import List, Optional

from patchwise.mail_handler.utils import decode_header_value, subject_is_reply

logger = logging.getLogger(__name__)

_APPROVAL_RE = re.compile(
    r"(?mi)"
    r"(?:Reviewed-by"
    r"|LGTM"
    r")"
    r"|^[ \t]*(?:Applied|Accepted)\.?[ \t]*$"
)
_PREFIX_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)+", re.IGNORECASE)
_COVER_INDEX_RE = re.compile(r"\[[^\]]*\b0/\d+\b[^\]]*\]", re.IGNORECASE)
_VERSION_RE = re.compile(r"\[[^\]]*\bv(\d+)\b[^\]]*\]", re.IGNORECASE)
_AI_ISSUE_SECTION_HEADER_RE = re.compile(r"\*\*Code Review\*\*\s*:", re.IGNORECASE)


@dataclass
class PatchVersionIssueReport:
    """Patchwise AI code review for one version of a patch."""
    exact_subject: str
    version: str
    ai_review: str
    message_id: str = ""


@dataclass
class PatchReviewHistory:
    """All evidence collected from an approved patch series.

    Contains the unified diff of the final accepted version and the
    Patchwise AI code reviews from every prior version v1..vf.
    """
    patch_title: str
    final_diff: str
    ai_issues: List[PatchVersionIssueReport] = field(default_factory=list)


def is_approval_reply(msg: EmailMessage) -> bool:
    """Return True if *msg* body contains a recognisable approval trailer."""
    body = _remove_quoted_lines(_extract_email_body(msg))
    return bool(_APPROVAL_RE.search(body))


def _extract_email_body(msg: EmailMessage) -> str:
    if msg.is_multipart():
        plain_part = msg.get_body(preferencelist=("plain",))
        if plain_part is not None:
            try:
                return plain_part.get_content()
            except (LookupError, UnicodeDecodeError):
                payload = plain_part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    return payload.decode("utf-8", errors="replace")

    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

    try:
        return msg.get_content()
    except (KeyError, LookupError, UnicodeDecodeError):
        return str(msg.get_payload() or "")


def _remove_quoted_lines(body: str) -> str:
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith(">")
    )


def _bare_subject(subject: str) -> str:
    """Strip all bracket-tag prefixes and return the bare patch title."""
    return _PREFIX_RE.sub("", decode_header_value(subject)).strip()


def _version_label(subject: str) -> str:
    """Return version label ('v1', 'v2', …) from a subject, defaulting to 'v1'."""
    match = _VERSION_RE.search(subject)
    return f"v{match.group(1)}" if match else "v1"


def _version_number(version: str) -> int:
    """Return numeric version from a version label like 'v3' → 3."""
    match = re.search(r"(\d+)", version)
    return int(match.group(1)) if match else 1


def _is_cover_letter(subject: str) -> bool:
    return bool(_COVER_INDEX_RE.search(decode_header_value(subject)))


def _extract_ai_issue_section(body: str) -> Optional[str]:
    """Return everything written below **Code Review**: in *body*, or None."""
    match = _AI_ISSUE_SECTION_HEADER_RE.search(body)
    if not match:
        return None
    text = body[match.end():].strip()
    return text or None


def _message_date(msg: EmailMessage) -> datetime:
    try:
        parsed = email_utils.parsedate_to_datetime(msg["Date"])
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _extract_patch_diff(raw_email: bytes) -> Optional[str]:
    """Extract only the unified diff from a raw patch email via git mailinfo."""
    with tempfile.TemporaryDirectory() as tmp:
        msg_path = tmp + "/msg"
        patch_path = tmp + "/patch"
        try:
            subprocess.run(
                ["git", "mailinfo", msg_path, patch_path],
                input=raw_email,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"git mailinfo failed: {e.stderr.decode(errors='replace')}")
            return None
        with open(patch_path, "rb") as f:
            patch = f.read().decode("utf-8", errors="replace")
    return patch or None


class PatchIssueCollector:
    """Extract false-positive evidence from approval reply emails."""

    def __init__(self, mail_client) -> None:
        self._mail = mail_client

    def collect_patch_review_history(
        self, approval_msg: EmailMessage
    ) -> List[PatchReviewHistory]:
        """Return one PatchReviewHistory per patch touched by *approval_msg*."""
        in_reply_to = (approval_msg.get("In-Reply-To") or "").strip()
        if not in_reply_to:
            logger.warning("Approval mail has no In-Reply-To; skipping.")
            return []

        final_patch = self._mail.fetch_message_by_id(in_reply_to)
        if final_patch is None:
            logger.warning("Could not fetch In-Reply-To=%s", in_reply_to)
            return []

        final_patch_subject = decode_header_value(final_patch.get("Subject", ""))

        if _is_cover_letter(final_patch_subject):
            logger.debug("FP Case 2 — cover-letter approval: %s", final_patch_subject)
            siblings = self._mail.fetch_patch_series(in_reply_to)
            patches = [
                msg
                for msg in siblings
                if not _is_cover_letter(decode_header_value(msg.get("Subject", "")))
                and not subject_is_reply(decode_header_value(msg.get("Subject", "")))
            ]
            patches.sort(key=_message_date)
        else:
            logger.debug("FP Case 1 — single-patch approval: %s", final_patch_subject)
            patches = [final_patch]

        patch_review_history_list: List[PatchReviewHistory] = []
        for patch_msg in patches:
            patch_review_history = self._collect_single_patch_review_history(patch_msg)
            if patch_review_history is not None:
                patch_review_history_list.append(patch_review_history)
        return patch_review_history_list

    def _collect_single_patch_review_history(
        self, patch_msg: EmailMessage
    ) -> Optional[PatchReviewHistory]:
        """Build PatchReviewHistory for a single approved patch message."""
        final_diff = _extract_patch_diff(patch_msg.as_bytes())
        if final_diff is None:
            subject = decode_header_value(patch_msg.get("Subject", ""))
            logger.warning("No diff extracted from: %s", subject)
            return None

        final_subject = decode_header_value(patch_msg.get("Subject", ""))
        patch_title = _bare_subject(final_subject)
        version_reviews = find_ai_patch_issue_reports(final_subject, self._mail)

        return PatchReviewHistory(
            patch_title=patch_title,
            final_diff=final_diff,
            ai_issues=version_reviews,
        )


def find_ai_patch_issue_reports(
    final_subject: str,
    mail_client,
) -> List[PatchVersionIssueReport]:
    """Find Patchwise AI code reviews for all patch versions up to and including vf.

    Searches the inbox by bare patch title and, for each version found, immediately
    fetches its AI review mail and extracts the **Code Review**: section.  Returns
    versions sorted oldest-first.
    """
    bare_title = _bare_subject(final_subject)
    if not bare_title:
        logger.warning("Could not derive bare title from: %s", final_subject)
        return []

    final_version_num = _version_number(_version_label(final_subject))

    reviews: List[PatchVersionIssueReport] = []
    for ai_msg in mail_client.search_by_subject("[Patchwise AI Review]", bare_title):
        subject = decode_header_value(ai_msg.get("Subject", ""))
        if not re.search(r"patchwise", ai_msg.get("From", ""), re.IGNORECASE):
            continue
        if _version_number(_version_label(subject)) > final_version_num:
            continue

        body = _extract_email_body(ai_msg)
        section = _extract_ai_issue_section(body)
        if section:
            msg_id = decode_header_value(ai_msg.get("Message-ID", "")).strip()
            version = _version_label(subject)
            reviews.append(
                PatchVersionIssueReport(
                    exact_subject=subject,
                    version=version,
                    ai_review=section,
                    message_id=msg_id,
                )
            )
            logger.debug("Captured Code Review for %s (%s)", subject, version)

    reviews.sort(key=lambda r: _version_number(r.version))
    return reviews
