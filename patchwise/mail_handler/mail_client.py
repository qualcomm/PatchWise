# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import email
import email.parser
import email.policy
from email.message import EmailMessage
import logging
import os
from smtplib import SMTP, SMTP_SSL
import imaplib
from typing import List, Optional
from imapclient import FLAGGED, IMAPClient
from imapclient.response_types import SearchIds

from patchwise.mail_handler.config import MailConfig
from patchwise.mail_handler.utils import DummySmtp, domain_in
from patchwise.utils.decorators import retry

logger = logging.getLogger("patchwise.mail_handler.mail_client")

_MAX_IMAP_RETRIES = 10


class MailClient:
    """Manages IMAP and SMTP connections.

    send_mode values
    ----------------
    0 - Respond only to the first entry of MailConfig.always_cc.
    1 - Respond to From & MailConfig.always_cc.
    2 - Respond to From, To, Cc (filtered to MailConfig.accepted_sender_domains)
        & MailConfig.always_cc.
    """

    def __init__(self, config: MailConfig, send: bool = False) -> None:
        self._config = config
        self._send = send
        self._imap: IMAPClient

        self._imap_connect()

    def _imap_connect(self) -> None:
        """Establish a fresh IMAP connection and select INBOX."""
        imap = self._config.imap
        self._imap = IMAPClient(imap.server, imap.port, use_uid=True, ssl=imap.ssl)
        self._imap.login(self._config.email, self._config.password)
        self._imap.select_folder("INBOX")
        logger.info(f"Connected to IMAP {imap.server}:{imap.port}")

    def _imap_reconnect(self) -> None:
        """Tear down any existing connection and open a fresh one."""
        logger.info("Reconnecting to IMAP server...")
        try:
            self._imap.logout()
        except Exception:
            pass
        self._imap_connect()

    def _imap_noop_or_reconnect(self, *args, **kwargs) -> None:
        """Send a NOOP to keep the connection alive; reconnect if it fails."""
        try:
            self._imap.noop()
        except Exception:
            self._imap_reconnect()

    def search(self, criteria) -> SearchIds:
        select_info = self._imap.select_folder("INBOX")
        logger.debug(f"{select_info=}")
        search_ids = self._imap.search(criteria)
        logger.info(f"{len(search_ids)} messages to process.")
        return search_ids

    @retry(
        max_retries=_MAX_IMAP_RETRIES,
        exceptions=(imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError, ConnectionError),
        on_retry=_imap_noop_or_reconnect,
    )
    def fetch_message(self, search_id: int) -> EmailMessage:
        message_data = self._imap.fetch(search_id, "RFC822")
        return email.message_from_bytes(
            message_data[search_id][b"RFC822"], policy=email.policy.default
        )

    def _smtp_builder(self) -> SMTP | SMTP_SSL | DummySmtp:
        """Return a fresh authenticated SMTP connection (or a dummy when send=False)."""
        if not self._send:
            return DummySmtp()
        smtp_cfg = self._config.smtp
        if smtp_cfg.ssl:
            smtp = SMTP_SSL(smtp_cfg.server, smtp_cfg.port)
        else:
            smtp = SMTP(smtp_cfg.server, smtp_cfg.port)
            smtp.starttls()
        smtp.login(self._config.email, self._config.password)
        return smtp

    def _apply_recipients(
        self, out: EmailMessage, message: EmailMessage, send_mode: int
    ) -> None:
        """Set ``To`` and ``Cc`` on *out* for a reply to *message* under
        *send_mode*. Capped by ``MailConfig.send_mode``."""
        if self._config.send_mode < send_mode:
            send_mode = self._config.send_mode

        always_cc = self._config.always_cc
        accepted_domains = self._config.accepted_sender_domains

        if send_mode == 0:
            # Fall back to the sender when no fixed recipient is configured, so
            # error replies still go out instead of raising IndexError.
            out["To"] = (
                always_cc[0] if always_cc else (message["Reply-To"] or message["From"])
            )
        elif send_mode == 1:
            out["To"] = message["Reply-To"] or message["From"]
            out["Cc"] = ", ".join(always_cc)
        elif send_mode == 2:
            out["To"] = message["Reply-To"] or message["From"]
            orig_ccs: List[str] = []
            for header in ("To", "Cc"):
                if message[header]:
                    orig_ccs.extend(
                        addr.strip()
                        for addr in message[header].split(",")
                        if domain_in(addr.strip(), accepted_domains)
                    )
            cc_list: List[str] = list(orig_ccs)
            # Add required CCs if not already present (case-insensitive)
            for req_cc in always_cc:
                if not any(req_cc.lower() == addr.lower() for addr in cc_list):
                    cc_list.append(req_cc)
            out["Cc"] = ", ".join(addr for addr in cc_list if addr)
        else:
            raise ValueError(f"Invalid send_mode: {send_mode}")

    def _apply_threading(
        self,
        out: EmailMessage,
        message: EmailMessage,
        reply_to: Optional[EmailMessage],
    ) -> None:
        """Set ``In-Reply-To`` / ``References`` on *out* to thread under
        *reply_to* if provided, otherwise *message*."""
        thread_parent = reply_to if reply_to is not None else message
        if thread_parent.get("Message-Id"):
            out["In-Reply-To"] = thread_parent["Message-Id"]
            out["References"] = " ".join(
                filter(
                    None, [thread_parent.get("References"), thread_parent["Message-Id"]]
                )
            )

    def send_response(
        self,
        message: EmailMessage,
        response: str,
        subject: Optional[str] = None,
        send_mode: Optional[int] = None,
        reply_to: Optional[EmailMessage] = None,
        attachment: Optional[str] = None,
    ) -> EmailMessage:
        """Build and send a reply to *message* via SMTP.

        If *reply_to* is provided the ``In-Reply-To`` / ``References`` headers
        are set to thread the new mail under *reply_to* instead of *message*.

        Returns the sent ``EmailMessage`` so callers can chain replies.
        """
        if send_mode is None:
            send_mode = self._config.send_mode

        reply = EmailMessage(
            # Make line length sufficiently long so script output isn't wrapped
            # we don't want to wrap checkpatch output
            policy=email.policy.SMTPUTF8.clone(max_line_length=240)
        )

        reply["From"] = self._config.from_email
        self._apply_recipients(reply, message, send_mode)

        if subject:
            # Sanitize the subject to remove newlines or carriage returns
            sanitized_subject = subject.replace("\n", " ").replace("\r", " ")
            reply["Subject"] = sanitized_subject
        else:
            if message["Subject"].startswith("Re:"):
                reply["Subject"] = message["Subject"]
            else:
                reply["Subject"] = f"Re: {message['Subject']}"

        self._apply_threading(reply, message, reply_to)

        reply.set_content(
            response, subtype="plain", charset="utf-8", cte="quoted-printable"
        )
        if attachment:
            with open(attachment) as f:
                log_data = f.read()
            reply.add_attachment(
                log_data,
                subtype="plain",
                charset="utf-8",
                filename=os.path.basename(attachment),
            )
        with self._smtp_builder() as smtp:
            smtp.send_message(reply)

        return reply

    def send_patch(
        self,
        message: EmailMessage,
        mbox_patch: str,
        send_mode: Optional[int] = None,
        reply_to: Optional[EmailMessage] = None,
    ) -> EmailMessage:
        """Send an mbox-format patch the way ``git send-email`` would."""
        if send_mode is None:
            send_mode = self._config.send_mode

        text = mbox_patch.lstrip()
        if text.startswith("From "):
            text = text.split("\n", 1)[1] if "\n" in text else ""

        parsed = email.parser.Parser(policy=email.policy.default).parsestr(text)
        body = parsed.get_payload()
        if isinstance(body, list):
            body = "".join(str(p) for p in body)

        out = EmailMessage(policy=email.policy.SMTPUTF8.clone(max_line_length=240))
        out["From"] = self._config.from_email
        patch_author = parsed["From"]
        if patch_author and patch_author != self._config.from_email:
            body = f"From: {patch_author}\n\n{body}"
        out["Subject"] = parsed["Subject"] or message["Subject"]
        if parsed["Date"]:
            out["Date"] = parsed["Date"]

        self._apply_recipients(out, message, send_mode)
        self._apply_threading(out, message, reply_to)

        out.set_content(body, subtype="plain", charset="utf-8", cte="8bit")
        with self._smtp_builder() as smtp:
            smtp.send_message(out)

        return out

    @retry(
        max_retries=_MAX_IMAP_RETRIES,
        exceptions=(imaplib.IMAP4.error, imaplib.IMAP4.abort, OSError, ConnectionError),
        on_retry=_imap_noop_or_reconnect,
    )
    def fetch_patch_series(self, in_reply_to_id: str) -> List[EmailMessage]:
        """Fetch the cover letter plus every sibling of a patch series.

        In b4-style Linux kernel series every patch replies to the cover
        letter, so a single ``Message-Id OR In-Reply-To`` query returns
        the cover (matching by ``Message-Id``) together with all sibling
        patches (matching by ``In-Reply-To``).
        """
        search_ids = self._imap.search(
            [
                "OR",
                "HEADER",
                "Message-Id",
                in_reply_to_id,
                "HEADER",
                "In-Reply-To",
                in_reply_to_id,
            ]
        )
        messages = []
        for search_id in search_ids:
            msg = self.fetch_message(search_id)
            messages.append(msg)
        return messages

    @retry(
        max_retries=_MAX_IMAP_RETRIES,
        exceptions=(imaplib.IMAP4.error, imaplib.IMAP4.abort, OSError, ConnectionError),
        on_retry=_imap_noop_or_reconnect,
    )
    def mark_as_processed(self, search_id) -> None:
        if self._send:
            self._imap.add_flags([search_id], [FLAGGED])
