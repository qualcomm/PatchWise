# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import email
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from email.policy import default
from typing import Any, Dict

import requests

from patchwise import SANDBOX_PATH

DEFAULT_SOURCE_URL = "https://lore.kernel.org/all/"

# Regex patterns that indicate C/kernel-style code. Shared by both
# _has_code_snippet (matches inside a comment body) and _has_code_context
# (matches inside a quoted diff/context block).
_CODE_REGEX_PATTERNS = (
    r"\bif\s*\(",
    r"\belse\s+if\s*\(",
    r"\bwhile\s*\(",
    r"\bfor\s*\(",
    r"\bswitch\s*\(",
    r"\breturn\s+\w+",
    r"\w+\s*\([^)]*\)",
    r"\w+\s*\[\w*\]",
    r"\w+\s*->\s*\w+",
    r"[{};]\s*$",
    r"==|!=|<=|>=|&&|\|\|",
    r"\bstruct\s+\w+",
    r"\b0x[0-9a-fA-F]+",
    r"#define\b",
    r"#include\b",
)

# Plain substrings characteristic of a quoted diff/context block.
_DIFF_CONTEXT_SUBSTRINGS = (
    "diff --git",
    "+++",
    "---",
    "@@",
    "static ",
    "void ",
    "int ",
)


def _matches_code_pattern(text: str) -> bool:
    return any(re.search(p, text) for p in _CODE_REGEX_PATTERNS)


class LoreCrawler:
    def __init__(self, config: Dict[str, Any], logger):
        self.config = config
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "FetchReviewerComment/1.0"})
        self.max_context_lines = config.get("MAX_CONTEXT_LINES", 40)
        self.source_url = config.get(
            "SOURCE_URL",
            os.environ.get("PATCHWISE_LORE_URL", DEFAULT_SOURCE_URL),
        )
        self.cache_dir = config.get(
            "CACHE_DIR",
            os.environ.get("PATCHWISE_CACHE_DIR", str(SANDBOX_PATH)),
        )
        if config.get("PROXY"):
            self.session.proxies = {"http": config["PROXY"], "https": config["PROXY"]}

    def _is_email_header(self, line):
        patterns = [
            r"^On\s+.+\s+wrote:$",
            r"^On\s+\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}",
            r"^On\s+\w{3},\s+\d{1,2}\s+\w{3}\s+\d{4}",
            r"^On\s+\w{3},\s+\w{3}\s+\d{1,2},\s+\d{4}",
        ]

        for pattern in patterns:
            if re.match(pattern, line, re.IGNORECASE):
                return True
        return False

    def _parse_email_segments(self, body):
        if not body:
            return []
        lines = body.splitlines()
        segments = []
        context_buffer = []
        current_comment = []

        for line in lines:
            stripped = line.strip()

            if stripped.startswith(">"):
                if current_comment:
                    context_lines = context_buffer[-self.max_context_lines:] if len(context_buffer) > self.max_context_lines else context_buffer
                    context_lines = [line for line in context_lines if line.strip()]
                    context = "\n".join(context_lines).strip()

                    comment_lines = [line for line in current_comment if line.strip()]
                    comment = "\n".join(current_comment).strip()

                    if context and comment:
                        if self._has_code_context(context):
                            file_path = self._extract_file_path(context)
                        else:
                            file_path = None
                        segments.append((context, comment, file_path))
                    current_comment = []

                content = stripped.lstrip(">").strip()
                if content.startswith("diff --git"):
                    context_buffer = []
                if content:
                    context_buffer.append(content)

            elif stripped:
                if self._is_email_header(stripped):
                    continue

                if stripped in ["--", "---", "Best regards,", "Thanks,", "Cheers,"]:
                    continue

                current_comment.append(stripped)

        if current_comment:
            context_lines = context_buffer[-self.max_context_lines:] if len(context_buffer) > self.max_context_lines else context_buffer
            context_lines = [line for line in context_lines if line.strip()]
            context = "\n".join(context_lines).strip()

            comment_lines = [line for line in current_comment if line.strip()]
            comment = "\n".join(current_comment).strip()

            if context and comment:
                if self._has_code_context(context):
                    file_path = self._extract_file_path(context)
                else:
                    file_path = None
                segments.append((context, comment, file_path))

        return segments

    def _extract_file_path(self, context):
        lines = context.split("\n")

        for line in lines:
            if line.startswith("diff --git"):
                match = re.search(r"b/([^\s]+)", line)
                if match:
                    return match.group(1)

            if line.startswith("+++") or line.startswith("---"):
                match = re.search(r"[ab]/([^\s]+)", line)
                if match:
                    return match.group(1)

        return None

    def _has_code_snippet(self, comment):
        return _matches_code_pattern(comment)

    def _has_code_context(self, context):
        if not context:
            return False

        context_lower = context.lower()
        if any(sub in context_lower for sub in _DIFF_CONTEXT_SUBSTRINGS):
            return True
        if "#include" in context_lower:
            return True

        if _matches_code_pattern(context):
            return True

        lines = context.split("\n")
        indented_lines = sum(1 for line in lines if line.startswith("    ") or line.startswith("\t"))
        if lines and indented_lines / len(lines) > 0.3:
            return True

        return False

    def _fetch_raw_body(self, link):
        raw_link = link.rstrip("/") + "/raw"
        try:
            r = self.session.get(raw_link, timeout=10)
            r.raise_for_status()
            msg = email.message_from_bytes(r.content, policy=default)
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body += payload.decode("utf-8", errors="replace")
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")
            return body
        except Exception:
            return None

    def _is_valid_comment(self, text):
        if not text:
            return False

        lines = [
            line.strip()
            for line in text.splitlines()
            if not line.strip().startswith(">") and line.strip()
        ]
        clean_text = " ".join(lines).lower()

        if not clean_text:
            return False

        if clean_text.strip().lower() in ["suzuki"]:
            return False

        status_keywords = ["applied"]
        if any(keyword in clean_text for keyword in status_keywords):
            return False
        if len(clean_text) < self.config["NOISE_LENGTH"]:
            for keyword in self.config["NOISE_KEYWORDS"]:
                if (keyword in clean_text) and ("but" not in clean_text) and (self._has_code_snippet(clean_text) is False):
                    return False

        return True

    def _fetch_all_entries(self, query):
        all_entries = []
        offset = 0
        page = 1
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        while True:
            self.logger.debug(f"[*] Crawler: fetching page {page} (offset={offset})...")

            try:
                params = {"q": query, "x": "A", "o": offset}

                res = self.session.get(self.source_url, params=params, timeout=15)
                res.raise_for_status()

                root = ET.fromstring(res.content)
                entries = root.findall("atom:entry", ns)

                if not entries:
                    self.logger.debug(f"[*] Crawler: Page {page} no result, page end")
                    break

                all_entries.extend(entries)
                self.logger.debug(f"[*] Crawler: Page {page} has {len(entries)} comments")

                if len(entries) < 200:
                    self.logger.debug("[*] Crawler: Fetched all results")
                    break

                offset += len(entries)
                page += 1
                time.sleep(1)
            except Exception as e:
                self.logger.debug(f"[!] Crawler: Facing issue while fetching page {page}: {e}")
                break
        return all_entries

    def run(self):
        query = f'f:"{self.config["MAINTAINER"]}"'
        self.logger.debug(f"[*] Crawler: searching {query} on {self.source_url}...")
        documents = []
        limit = self.config.get("LIMIT_PER_REVIEWER", 0)

        try:
            offset = 0
            page = 1
            total_entries_processed = 0
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            while True:
                if limit > 0 and len(documents) >= limit:
                    self.logger.debug(f"[*] Crawler: The valid comment limit ({limit}) has been reached. Stopping crawling.")
                    break

                self.logger.debug(f"[*] Crawler: Fetching page {page} (offset={offset})...")

                try:
                    params = {"q": query, "x": "A", "o": offset}

                    res = self.session.get(self.source_url, params=params, timeout=15)
                    res.raise_for_status()

                    root = ET.fromstring(res.content)
                    entries = root.findall("atom:entry", ns)

                    if not entries:
                        self.logger.debug(f"[*] Crawler: No results on page {page}; stopping crawl.")
                        break

                    self.logger.debug(f"[*] Crawler: Page {page} returned {len(entries)} entries. Beginning processing...")

                    for i, entry in enumerate(entries):
                        if limit > 0 and len(documents) >= limit:
                            self.logger.debug(f"*] Crawler: The valid comment limit ({limit}) has been reached. Stopping processing.")
                            break

                        total_entries_processed += 1
                        link = entry.find("atom:link", ns).attrib["href"]
                        title = entry.find("atom:title", ns).text
                        body = self._fetch_raw_body(link)

                        if body:
                            segments = self._parse_email_segments(body)
                            valid_count = 0
                            for seg_idx, (context, comment, file_path) in enumerate(segments):
                                if limit > 0 and len(documents) >= limit:
                                    break
                                if comment and context and self._is_valid_comment(comment):
                                    doc = {
                                        "content": context,
                                        "comment": comment,
                                        "title": title,
                                        "file_path": file_path,
                                        "link": link,
                                    }

                                    documents.append(doc)
                                    valid_count += 1

                            if valid_count > 0:
                                self.logger.debug(f"[{total_entries_processed}] Kept as valid ({valid_count} comment segments) - Current total: {len(documents)}")
                                self.logger.debug(f"Title: {title}")
                                self.logger.debug(f"Link: {link}")

                            else:
                                self.logger.debug(f"[{total_entries_processed}] - Filtered out")
                                self.logger.debug(f"Title: {title}")
                                self.logger.debug(f"Link: {link}")
                        time.sleep(0.5)

                    if limit > 0 and len(documents) >= limit:
                        break

                    if len(entries) < 200:
                        self.logger.debug("[*] Crawler: All available data has been processed")
                        break

                    offset += len(entries)
                    page += 1
                    time.sleep(1)

                except Exception as e:
                    self.logger.debug(f"[!] Crawler: Error occurred while fetching page {page}: {e}")
                    break
        except Exception as e:
            self.logger.error(f"[!] Crawler Error: {e}")

        self.logger.debug(f"[*] Crawler: Task completed. Processed a total of {total_entries_processed} raw records and generated {len(documents)} valid comment documents.")

        if documents:
            maintainer_name = self.config["MAINTAINER"].replace(" ", "_").replace("@", "_at_")
            os.makedirs(self.cache_dir, exist_ok=True)
            json_filename = os.path.join(self.cache_dir, f"crawled_{maintainer_name}.json")

            with open(json_filename, "w", encoding="utf-8") as f:
                json.dump(documents, f, ensure_ascii=False, indent=2)
            self.logger.debug(f"[*] Saved JSON file: {json_filename}")

        return documents
