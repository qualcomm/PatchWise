# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from email.message import EmailMessage

import pytest

from patchwise.mail_handler import handler
from patchwise.mail_handler.config import (
    DeprecatedList,
    ImapConfig,
    MailConfig,
    SmtpConfig,
)

LIST = "linux-arm-msm@vger.kernel.org"


def _config(**overrides) -> MailConfig:
    values = dict(
        email="bot@example.com",
        password="",
        from_email="PatchWise <bot@example.com>",
        accepted_sender_domains=["example.org"],
        accepted_lists=[LIST],
        deprecated_lists={},
        always_cc=[],
        additional_cc=[],
        send_mode=0,
        imap=ImapConfig(server="", port=0, ssl=True),
        smtp=SmtpConfig(server="", port=0, ssl=True),
    )
    values.update(overrides)
    return MailConfig(**values)


def _patch(to: str, cc: str = "") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "Dev <dev@example.org>"
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = "[PATCH] arm64: dts: fix"
    msg["Message-Id"] = "<patch@example.org>"
    msg.set_content("patch body")
    return msg


@pytest.mark.parametrize(
    "to, cc",
    [
        (LIST, ""),
        ("Linux-ARM-MSM@vger.kernel.org", ""),
        ("linux-arm-msm@VGER.KERNEL.ORG", ""),
        ('"MSM, Arm" <linux-arm-msm@vger.kernel.org>', ""),
        ('"Doe, Jane" <jane@example.org>', f"Arm MSM <{LIST}>"),
    ],
)
def test_should_ignore_accepts_list_address_variants(to: str, cc: str) -> None:
    assert not handler.should_ignore(_patch(to, cc), _config())


def test_should_ignore_matches_mixed_case_configured_list() -> None:
    config = _config(accepted_lists=["Linux-ARM-MSM@vger.kernel.org"])
    assert not handler.should_ignore(_patch(LIST), config)


def test_should_ignore_rejects_other_lists() -> None:
    assert handler.should_ignore(_patch("linux-kernel@vger.kernel.org"), _config())


def test_find_deprecated_list_ignores_case() -> None:
    info = DeprecatedList(replacement="new-list@example.org", message="moved")
    deprecated = {"old-list@example.org": info}

    assert (
        handler.find_deprecated_list(_patch("Old-List@example.org"), deprecated) is info
    )
    assert (
        handler.find_deprecated_list(
            _patch("Old-List@example.org", "New-List@Example.org"), deprecated
        )
        is None
    )
