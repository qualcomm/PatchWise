# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from email import utils
from email.header import decode_header, make_header
from email.message import EmailMessage
from typing import Iterable, Optional
import logging
import re

logger = logging.getLogger("patchwise.mail_handler.handler")


def domain_in(address: str, domains: Iterable[str]) -> bool:
    """True if *address*'s domain equals, or is a subdomain of, one of *domains*.

    Matches on the full domain label so that a configured domain does not also
    match an unrelated domain that merely shares its suffix.
    """
    _, email = utils.parseaddr(address.strip())
    if "@" not in email:
        return False
    host = email.rsplit("@", 1)[1].lower()
    return any(
        host == domain.lower() or host.endswith("." + domain.lower())
        for domain in domains
    )


def decode_header_value(value: Optional[str]) -> str:
    """Decode a possibly MIME-encoded header and collapse whitespace."""
    if not value:
        return ""
    try:
        decoded = str(make_header(decode_header(value)))
    except (ValueError, LookupError, UnicodeDecodeError):
        decoded = value
    return re.sub(r"\s+", " ", decoded).strip()


def subject_is_reply(subject: Optional[str]) -> bool:
    """True if *subject* is a reply (starts with ``Re:`` / ``Re ``)."""
    return bool(re.match(r"^re[:\s]", decode_header_value(subject), re.IGNORECASE))


class DummySmtp:
    def send_message(self, message: EmailMessage):
        logger.debug(f"Dummy SMTP server called with message:")
        logger.debug(message.as_string())

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        pass
