# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""CLI plumbing for the mail-handler mode of `patchwise --mail`."""

import argparse
import datetime
import logging
import time
from typing import Set

from patchwise.mail_handler.config import MailConfig
from patchwise.mail_handler.handler import process_mail
from patchwise.patch_review import get_selected_reviews_from_args

logger = logging.getLogger(__name__)

WATCH_INTERVAL = datetime.timedelta(minutes=10)


def add_mail_arguments(
    parser_or_group: argparse.ArgumentParser | argparse._ArgumentGroup,
):
    parser_or_group.add_argument(
        "--all",
        action="store_true",
        help="Search for all mail, not just unflagged mail. (default: %(default)s)",
    )
    parser_or_group.add_argument(
        "--since",
        type=datetime.date.fromisoformat,
        help="Filter only messages after the date specified. Date should be in ISO 8601 format (e.g. `YYYY-MM-DD`)",
    )
    parser_or_group.add_argument(
        "--before",
        type=datetime.date.fromisoformat,
        help="Filter only messages before the date specified. Date should be in ISO 8601 format (e.g. `YYYY-MM-DD`)",
    )
    parser_or_group.add_argument(
        "--message-id",
        type=str,
        nargs="+",
        help="Search for messages with specific message IDs. "
        "Message-IDs should be in the following format: "
        "`20250408-trace-noc-v6-1-526c61a207f6@quicinc.com`",
    )
    parser_or_group.add_argument(
        "--watch",
        "-w",
        action="store_true",
        help="Watch for new mail and process it in a loop. (default: %(default)s)",
    )
    parser_or_group.add_argument(
        "--send",
        action=argparse.BooleanOptionalAction,
        help="Send messages or print them to stdout instead. "
        "`WARNING:` This will actually send emails and modify the user's mailbox. "
        "Use with caution!",
        default=False,
    )


def build_criteria(args: argparse.Namespace):
    """Build IMAP search criteria from parsed mail arguments."""
    criteria = []

    if args.all:
        criteria.append(b"ALL")
    else:
        criteria.append(b"UNFLAGGED")

    if args.message_id:
        if len(args.message_id) > 1:
            criteria.extend([b"OR"] * (len(args.message_id) - 1))
        for message_id in args.message_id:
            criteria.extend([b"HEADER", b"Message-ID", message_id.encode()])

    if args.since:
        criteria.extend([b"SINCE", args.since])

    if args.before:
        criteria.extend([b"BEFORE", args.before])

    return criteria


def _process_loop(
    criteria,
    reviews: Set[str],
    config: MailConfig,
    send: bool,
    watch: bool,
    fix: bool,
) -> None:
    """Process mail in a loop or once based on the watch flag."""
    try:
        while True:
            process_mail(criteria, reviews, config, send=send, fix=fix)

            if watch:
                logger.info(f"Sleeping for {WATCH_INTERVAL}")
                time.sleep(WATCH_INTERVAL.total_seconds())
            else:
                break
    except KeyboardInterrupt:
        logger.info("Interrupted, quitting")
    logger.info("Done processing mail.")


def run_mail_mode(args: argparse.Namespace) -> None:
    """Entry point for `patchwise --mail`."""
    criteria = build_criteria(args)
    reviews = get_selected_reviews_from_args(args)
    config = MailConfig.load()
    _process_loop(criteria, reviews, config, args.send, args.watch, fix=args.fix)
