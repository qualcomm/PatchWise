# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Typed view of the `mail:` block in patchwise's config."""

from dataclasses import dataclass
from typing import Dict, List

from patchwise.utils.config import parse_config


@dataclass
class ImapConfig:
    server: str
    port: int
    ssl: bool


@dataclass
class SmtpConfig:
    server: str
    port: int
    ssl: bool


@dataclass
class DeprecatedList:
    replacement: str
    message: str


@dataclass
class MailConfig:
    email: str
    password: str
    from_email: str
    accepted_sender_domains: List[str]
    accepted_lists: List[str]
    deprecated_lists: Dict[str, DeprecatedList]
    always_cc: List[str]
    additional_cc: List[str]
    send_mode: int
    imap: ImapConfig
    smtp: SmtpConfig

    @classmethod
    def load(cls) -> "MailConfig":
        raw = parse_config()["mail"]
        deprecated = {
            addr: DeprecatedList(**info)
            for addr, info in (raw.get("deprecated_lists") or {}).items()
        }
        return cls(
            email=raw["email"],
            password=raw["password"],
            from_email=raw["from_email"],
            accepted_sender_domains=list(raw["accepted_sender_domains"]),
            accepted_lists=list(raw["accepted_lists"]),
            deprecated_lists=deprecated,
            always_cc=list(raw["always_cc"]),
            additional_cc=list(raw["additional_cc"]),
            send_mode=int(raw["send_mode"]),
            imap=ImapConfig(**raw["imap"]),
            smtp=SmtpConfig(**raw["smtp"]),
        )
