# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from email import utils
from email.message import EmailMessage
import logging
import os
from pathlib import Path
import re
import tempfile
import textwrap
from typing import Callable, Dict, List, Optional
import subprocess
from git import Repo
from email.header import decode_header

from patchwise import SANDBOX_PATH
from patchwise.logger_setup import LOG_PATH
from patchwise.mail_handler.ai_models import get_model_name
from patchwise.mail_handler.config import DeprecatedList, MailConfig
from patchwise.mail_handler.utils import (
    decode_header_value,
    domain_in,
    subject_is_reply,
)
from patchwise.mail_handler.mail_client import MailClient
from patchwise.patch_review.kernel_tree import init_kernel_tree, reset_to_commit
from patchwise.patch_review import (
    fix_reported_issues,
    review_commit,
    PatchReviewResults,
)
from patchwise.patch_review.decorators import (
    LLM_REVIEWS,
    STATIC_ANALYSIS_REVIEWS,
)

logger = logging.getLogger("patchwise.mail_handler.handler")

KERNEL_TREE = os.path.join(SANDBOX_PATH, "kernel")

BASE_COMMIT_RE = re.compile(r"(?m)^base-commit:\s*([0-9a-f]{40})\s*$")


def is_auto_submitted(msg: EmailMessage) -> bool:
    return msg.get("Auto-Submitted") not in [None, "no"]


def subject_is_empty(msg: EmailMessage) -> bool:
    return not msg.get("Subject")


def is_plain_text(message: EmailMessage) -> bool:
    return not message.is_multipart() and message.get_content_type() == "text/plain"


def sent_to_list(message: EmailMessage, test: Callable[[str], bool]) -> bool:
    for header in ["To", "Cc"]:
        if not message.get(header):
            continue
        for address in decode_header_value(message.get(header)).split(","):
            _, email = utils.parseaddr(address.strip())
            if test(email):
                return True
    return False


def find_deprecated_list(
    msg: EmailMessage, deprecated_lists: Dict[str, DeprecatedList]
) -> Optional[DeprecatedList]:
    """Return the deprecation entry to surface for *msg*, or None.

    A list is "deprecated for this message" if the message was sent to it
    and was *not* also sent to its replacement.
    """
    for list_addr, info in deprecated_lists.items():
        sent_to_dep = sent_to_list(msg, lambda addr: addr == list_addr)
        sent_to_repl = sent_to_list(msg, lambda addr: addr == info.replacement)
        if sent_to_dep and not sent_to_repl:
            return info
    return None


# List of checks to determine if we should completely ignore the message
def should_ignore(msg: EmailMessage, config: MailConfig) -> bool:
    if not domain_in(msg["From"], config.accepted_sender_domains):
        logger.info(f"Sender domain not accepted: {msg['From']}")
        return True

    if not sent_to_list(msg, lambda addr: addr in config.accepted_lists):
        logger.info(f"Not sent to any of the accepted lists: {msg['To']}")
        return True

    if is_auto_submitted(msg):
        logger.info(f"Auto-submitted message: {msg['Message-Id']}")
        return True

    if subject_is_empty(msg):
        logger.info(f"Empty subject: {msg['Message-Id']}")
        return True

    if subject_is_reply(msg.get("Subject")):
        logger.info(f"Subject is a reply: {msg['Message-Id']}")
        return True

    if msg.get("From"):
        _, patchwise_from_email = utils.parseaddr(config.from_email)
        _, from_email = utils.parseaddr(msg["From"])
        if (
            re.search(r"patchwise", msg["From"], re.IGNORECASE)
            or patchwise_from_email.lower() == from_email.lower()
        ):
            return True

    return False


def prepare_kernel_tree() -> Repo:
    try:
        repo = init_kernel_tree(Path(KERNEL_TREE))

        # Check and remove the index.lock file if it exists
        lock_file = os.path.join(repo.git_dir, "index.lock")
        if os.path.exists(lock_file):
            logger.warning(f"Lock file exists: {lock_file}. Removing it.")
            os.remove(lock_file)

        # Reset the working tree to FETCH_HEAD
        repo.git.reset("--hard", "FETCH_HEAD")
        logger.debug("Performed a hard reset to FETCH_HEAD.")

        # Remove all untracked files and directories
        repo.git.clean("-fdx")
        logger.debug("Cleaned untracked files and directories.")

    except Exception as e:
        logger.error(f"Error preparing kernel tree: {e}")
        raise

    return repo


def apply_patch_from_email(message: EmailMessage, repo: Repo) -> str:
    try:
        # Abort any ongoing git am session if it exists
        if repo.git_dir and os.path.exists(os.path.join(repo.git_dir, "rebase-apply")):
            repo.git.am("--abort")

        # Use git am to apply the patch directly from the email content
        raw_email = message.as_bytes()
        process = subprocess.run(
            ["git", "am", "--committer-date-is-author-date"],
            input=raw_email,
            check=True,
            capture_output=True,
            cwd=repo.working_tree_dir,
        )

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to apply patch with git am: {e.stderr.decode()}")
        return ""
    except Exception as e:
        logger.error(f"Unexpected error while applying patch: {e}")
        return ""

    return repo.head.commit.hexsha


def split_mail_diff_and_message(
    raw_email: bytes,
) -> tuple[Optional[str], Optional[str]]:
    """Split a raw patch email into (patch, log_message) via git mailinfo."""
    with tempfile.TemporaryDirectory() as tmp:
        msg_path = os.path.join(tmp, "msg")
        patch_path = os.path.join(tmp, "patch")
        try:
            subprocess.run(
                ["git", "mailinfo", msg_path, patch_path],
                input=raw_email,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"git mailinfo failed: {e.stderr.decode(errors='replace')}")
            return None, None

        with open(patch_path, "rb") as f:
            patch = f.read().decode("utf-8", errors="replace")
        with open(msg_path, "rb") as f:
            log_message = f.read().decode("utf-8", errors="replace")

    return (patch or None, log_message or None)


def format_static_analysis_output(
    message: EmailMessage,
    static_reviews: Dict,
    sha: str,
):
    sections = []
    for review, output in static_reviews.items():
        sections.append(f"**{review}**:\n---\n{output}---")
    response = "\n\n".join(sections) + f"\n\nKernel version tested on: {sha}"
    subject = f"Re: [Patchwise Static Analysis] {message['Subject']}"
    return response, subject


def format_ai_review_output(
    message: EmailMessage,
    ai_reviews: Dict,
):
    HEADER = f"""
The following response is generated by Patchwise (using {get_model_name()}).
AI-generated content. Be sure to check for accuracy.

"""

    patch, log_message = split_mail_diff_and_message(message.as_bytes())

    if not patch:
        return

    quoted = f"{message['Subject']}\n"
    if log_message:
        quoted += f"\n{log_message.rstrip()}\n"

    response = textwrap.indent(quoted, "> ", predicate=lambda _: True) + HEADER
    if "LLMCommitAudit" in ai_reviews:
        response += (
            "**Commit Analysis**:" + "\n\n" + ai_reviews["LLMCommitAudit"] + "\n\n"
        )
    if "AiCodeReview" in ai_reviews:
        response += "**Code Review**:" + "\n\n" + ai_reviews["AiCodeReview"] + "\n\n"
    subject = f"Re: [Patchwise AI Review] {message['Subject']}"
    return response, subject


def format_ai_patch_fix_output(mbox_patch: str) -> str:
    """Prepend the Patchwise AI Patch Fix prefix to the mbox's Subject line."""
    return re.sub(
        r"^(Subject:\s*)",
        r"\1[Patchwise AI Patch Fix] ",
        mbox_patch,
        count=1,
        flags=re.MULTILINE,
    )


def get_patch_series(
    message: EmailMessage, mail_client: "MailClient"
) -> tuple[List[EmailMessage], Optional[str]]:
    """Return ``(series, base_commit)`` for *message*.

    *series* is the ordered list of every patch in the mailing-list
    series (including *message* itself). For a standalone patch the list
    contains just *message*.

    *base_commit* is the SHA read from the cover letter's ``base-commit:``
    trailer, or ``None``.
    """
    in_reply_to = (message.get("In-Reply-To") or "").strip()
    if not in_reply_to:
        return [message], None

    siblings = mail_client.fetch_patch_series(in_reply_to)
    if not siblings:
        return [message], None

    cover: Optional[EmailMessage] = None
    patches: List[EmailMessage] = []
    for sibling in siblings:
        if subject_is_reply(sibling.get("Subject", "")):
            continue
        if sibling.get("Message-Id") == in_reply_to:
            cover = sibling
        else:
            patches.append(sibling)

    patches.sort(key=lambda m: utils.parsedate_to_datetime(m["Date"]))

    base_commit: Optional[str] = None
    if cover:
        body = cover.get_payload(decode=True)
        if isinstance(body, bytes):
            body = body.decode(cover.get_content_charset() or "utf-8", errors="replace")
        match = BASE_COMMIT_RE.search(body or "")
        if match:
            base_commit = match.group(1)

    return patches, base_commit


def format_series_context(
    current: EmailMessage,
    series: List[EmailMessage],
) -> str:
    """Return a numbered listing of subject lines for *series*, marking
    *current*. For a standalone patch the result is a one-line listing."""
    current_id = current.get("Message-Id")
    lines = []
    for i, patch in enumerate(series, start=1):
        subject = decode_header_value(patch.get("Subject", ""))
        marker = (
            " <-- current patch under review"
            if patch.get("Message-Id") == current_id
            else ""
        )
        lines.append(f"{i}. {subject}{marker}")
    return "## Patch Series\n\n" + "\n".join(lines)


def test_patch_from_mail(
    patch: EmailMessage,
    series: List[EmailMessage],
    base_commit: Optional[str],
    reviews: set[str],
    additional_context: Optional[str] = "",
) -> PatchReviewResults | None:

    repo = prepare_kernel_tree()

    if base_commit:
        reset_to_commit(repo, base_commit)

    current_id = patch.get("Message-Id")
    current_sha: Optional[str] = None
    for sibling in series:
        sha = apply_patch_from_email(sibling, repo)
        if not sha:
            logger.error(f"Failed to apply patch: {sibling.get('Subject', '')}")
        else:
            logger.debug(f"Applied patch: {sibling.get('Subject', '')}")
            if sibling.get("Message-Id") == current_id:
                current_sha = sha

    if current_sha is None:
        return None

    results = review_commit(
        reviews,
        repo.commit(current_sha),
        str(repo.working_tree_dir),
        additional_context=additional_context,
    )

    return results


def decode_single_header(contents):
    if contents:
        value, encoding = decode_header(contents)[0]
        if isinstance(value, bytes):
            return value.decode(encoding if encoding else "utf-8")
        else:
            return value
    return None


def process_mail(
    criteria,
    reviews: set[str],
    config: MailConfig,
    send: bool = False,
    fix: bool = False,
):
    logger.info(f"IMAP: {config.imap.server}:{config.imap.port}")
    logger.info(f"SMTP: {config.smtp.server}:{config.smtp.port}")

    mail_client = MailClient(config, send=send)

    search_ids = mail_client.search(criteria)

    for search_id in search_ids:
        msg = mail_client.fetch_message(search_id)
        message_id = decode_single_header(msg["Message-Id"])
        logger.info(f"Handling {message_id} ({msg['Subject']})")

        # Check if we can handle the message
        if should_ignore(msg, config):
            mail_client.mark_as_processed(search_id)
            continue

        if not is_plain_text(msg):
            logger.warning(f"Not a plain text email: {message_id}")
            mail_client.send_response(
                msg,
                "No MIME, no links, no compression, no attachments. Just plain text.",
                send_mode=1,
            )
            mail_client.mark_as_processed(search_id)
            continue

        deprecation = find_deprecated_list(msg, config.deprecated_lists)
        if deprecation:
            mail_client.send_response(msg, deprecation.message, send_mode=1)

        series, base_commit = get_patch_series(msg, mail_client)
        additional_context = format_series_context(msg, series)
        try:
            patch_results = test_patch_from_mail(
                msg, series, base_commit, reviews, additional_context
            )
        except Exception as e:
            logger.exception(f"test_patch_from_mail raised for {message_id}: {e}")
            mail_client.send_response(
                msg,
                f"An internal error occurred while reviewing this patch:\n\n{e}",
                subject=f"[Patchwise {type(e).__name__}] {decode_single_header(msg['Subject'])}",
                send_mode=0,
                attachment=LOG_PATH,
            )
            raise

        if patch_results:
            ai_reviews = dict()
            static_reviews = dict()
            for review, output in patch_results.results.items():
                if not output:
                    continue
                name = type(review).__name__
                if isinstance(review, tuple(STATIC_ANALYSIS_REVIEWS)):
                    static_reviews[name] = output
                elif isinstance(review, tuple(LLM_REVIEWS)):
                    ai_reviews[name] = output
                else:
                    raise RuntimeError(f"Unknown review type for review: {review}")
            if static_reviews:
                response, subject = format_static_analysis_output(
                    msg, static_reviews, patch_results.commit
                )
                mail_client.send_response(msg, response, subject, 2)

            fix_results = fix_reported_issues(patch_results) if fix else {}

            if ai_reviews:
                result = format_ai_review_output(msg, ai_reviews)
                if result:
                    response, subject = result
                    ai_review_mail = mail_client.send_response(
                        msg, response, subject, 2
                    )
                else:
                    ai_review_mail = None

                patch_fix = fix_results.get("AiPatchFix")
                if patch_fix:
                    mail_client.send_patch(
                        msg,
                        format_ai_patch_fix_output(patch_fix),
                        send_mode=1,
                        reply_to=ai_review_mail,
                    )

        mail_client.mark_as_processed(search_id)
        logger.info(f"Successfully processed: {message_id}")
