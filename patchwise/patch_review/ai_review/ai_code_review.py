# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from patchwise import KERNEL_PATH, SANDBOX_PATH
from patchwise.patch_review.decorators import register_llm_review, register_long_review
from patchwise.patch_review.patch_review import Dependency

from .ai_review import AiReview


@dataclass
class LSPLocation:
    """Represents an LSP location with file URI and position."""

    uri: str
    line: int
    character: int


@dataclass
class DefinitionRange:
    """Represents a definition with its file location and line range."""

    file_path: str
    start_line: int
    end_line: int
    identifier: str


@register_llm_review
@register_long_review
class AiCodeReview(AiReview):
    """AI-powered code review for Linux kernel patches using LSP and clangd."""

    DEPENDENCIES = getattr(AiReview, "DEPENDENCIES", []) + [
        Dependency(
            name="clangd",
            min_version="14.0.0",
            max_version="20.0.0",
        ),
        Dependency(
            name="clang",
            min_version="14.0.0",
            max_version="20.0.0",
        ),
    ]

    # LSP Configuration
    MAX_GAP = 5

    # File processing
    IDENTIFIER_PATTERN = r"\b[_a-zA-Z][_a-zA-Z0-9]*\b"

    # LSP message IDs
    INIT_MSG_ID = 1
    DEFINITION_MSG_ID = 2
    SYMBOL_MSG_ID = 3
    DOC_SYMBOL_MSG_ID = 100

    @staticmethod
    def _load_prompt_template() -> str:
        """Load the prompt template from the markdown file."""
        template_path = os.path.join(
            os.path.dirname(__file__), "prompts", "code_review_prompt.md"
        )
        try:
            with open(template_path, "r") as f:
                return f.read()
        except Exception as e:
            raise RuntimeError(f"Failed to load prompt template: {e}")

    @staticmethod
    def get_kernel_coding_style() -> str:
        """Load kernel coding style guidelines from documentation."""
        coding_style_path = os.path.join(
            KERNEL_PATH, "Documentation/process/coding-style.rst"
        )
        try:
            with open(coding_style_path, "r") as f:
                return f.read()
        except Exception as e:
            return f"[Could not load kernel coding style guidelines: {e}]"

    @staticmethod
    def _load_system_prompt_template() -> str:
        """Load the system prompt template from the markdown file."""
        template_path = os.path.join(
            os.path.dirname(__file__), "prompts", "system_prompt.md"
        )
        try:
            with open(template_path, "r") as f:
                return f.read()
        except Exception as e:
            raise RuntimeError(f"Failed to load system prompt template: {e}")

    @classmethod
    def get_system_prompt(cls) -> str:
        """Generate the system prompt including kernel coding style guidelines."""
        template = cls._load_system_prompt_template()
        return template.format(kernel_coding_style=cls.get_kernel_coding_style())

    def _read_file_safely(self, file_path: str) -> Optional[str]:
        """Safely read a file and return its contents, or None on error."""
        try:
            with open(file_path, "r") as f:
                return f.read()
        except Exception as e:
            self.logger.error(f"Failed to read {file_path}: {e}")
            return None

    def _get_file_lines(self, file_path: str) -> List[str]:
        """Get file lines as a list, or empty list on error."""
        content = self._read_file_safely(file_path)
        return content.splitlines(keepends=True) if content else []

    def _run_make_command(
        self,
        args: List[str],
        capture_output: bool = True,
        stdout_file: Optional[str] = None,
    ) -> None:
        """Run a make command with consistent arguments."""
        base_args = [
            "make",
            f"O={self.build_dir}",
            f"-j{os.cpu_count()}",
            "ARCH=arm64",
            "LLVM=1",
        ]
        full_args = base_args + args

        desc = " ".join(args)

        if capture_output:
            self.run_cmd_with_timer(full_args, desc, cwd=str(KERNEL_PATH))
        elif stdout_file:
            output = self.run_cmd_with_timer(
                full_args,
                desc,
                cwd=str(KERNEL_PATH),
            )
            with open(stdout_file, "w") as f:
                f.write(output)
        else:
            self.run_cmd_with_timer(full_args, desc, cwd=str(KERNEL_PATH))

    def generate_compile_commands(self) -> None:
        """Generate compile_commands.json for clangd."""
        self.logger.debug("Running make defconfig")
        self._run_make_command(["defconfig"])

        self.logger.debug("Running make")
        build_log_path = self.build_dir / "build.log"
        self._run_make_command(
            ["V=1"], capture_output=False, stdout_file=str(build_log_path)
        )

        self.logger.debug("Generating compile commands")
        subprocess.run(
            [
                "python3",
                os.path.join(
                    KERNEL_PATH, "scripts", "clang-tools", "gen_compile_commands.py"
                ),
                "-d",
                str(self.build_dir),
                "-o",
                str(self.build_dir / "compile_commands.json"),
            ],
            cwd=str(self.build_dir),
        )
        self.logger.debug("compile_commands.json generated")

    def _create_lsp_message(
        self, method: str, params: Dict[str, Any], msg_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Create a standardized LSP message."""
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if msg_id is not None:
            message["id"] = msg_id
        return message

    def _make_message_bytes(self, msg: Dict[str, Any]) -> bytes:
        """Convert LSP message to bytes with proper headers."""
        msg_bytes = json.dumps(msg).encode("utf-8")
        return f"Content-Length: {len(msg_bytes)}\r\n\r\n".encode("utf-8") + msg_bytes

    def send_workDoneProgress_response(self, proc):
        message = {"id": 0, "jsonrpc": "2.0", "result": None}
        self._send_lsp_message(proc, message)

    def _read_lsp_response(
        self, proc: subprocess.Popen[Any], expected_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Read and parse LSP response from process."""

        if proc.stdout is None:
            raise RuntimeError("Process stdout is None")

        while True:
            # Read headers
            headers = b""
            while b"\r\n\r\n" not in headers:
                chunk = proc.stdout.read(1)
                if chunk is None:
                    raise RuntimeError("Failed to read from process stdout (header)")
                headers += chunk

            # Parse content length
            content_length = 0
            for line in headers.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    content_length = int(line.split(b":")[1].strip())

            # Read content
            content = proc.stdout.read(content_length)
            if content is None:
                raise RuntimeError("Failed to read content from process stdout")

            msg = json.loads(content.decode("utf-8"))

            if expected_id is None or msg.get("id") == expected_id:
                return msg

            # Log and handle progress notifications and workDoneProgress
            if msg.get("method") == "window/workDoneProgress/create":
                token = msg.get("params", {}).get("token")
                self.logger.debug(f"LSP workDoneProgress created for token: {token}")
                self.send_workDoneProgress_response(proc)
                continue  # Don't return, keep waiting for expected response

            if msg.get("method") == "textDocument/publishDiagnostics":
                self.logger.debug(f"Received diagnostics: {json.dumps(msg, indent=2)}")
                continue

            if msg.get("method") == "textDocument/clangd.fileStatus":
                self.logger.debug(
                    f"Received clangd fileStatus notification: {json.dumps(msg)}"
                )
                continue

            if msg.get("method") == "$/progress" and "params" in msg:
                params = msg["params"]
                token = params.get("token")
                # value = params.get("value", {})
                if token == "backgroundIndexProgress":
                    self.logger.debug(f"Background index progress: {json.dumps(msg)}")
                    continue

            self.logger.debug(
                (
                    f"Received LSP message with id {msg.get('id')}, "
                    f"expected {expected_id}: "
                    f"{json.dumps(msg, indent=2)}"
                )
            )

    def _send_lsp_message(
        self, proc: subprocess.Popen[Any], message: Dict[str, Any]
    ) -> None:
        """Send an LSP message to the process."""
        if proc.stdin is None:
            raise RuntimeError("Process stdin is None")
        proc.stdin.write(self._make_message_bytes(message))
        proc.stdin.flush()

    def _initialize_lsp(
        self, proc: subprocess.Popen[Any], project_root: os.PathLike[str]
    ) -> None:
        """Initialize LSP connection."""
        self.logger.debug("Initializing LSP connection")

        init_msg = self._create_lsp_message(
            "initialize",
            {
                "rootUri": f"file://{project_root}",
                "capabilities": {
                    "window": {
                        "showDocument": {"support": True},
                        "showMessage": {
                            "messageActionItem": {"additionalPropertiesSupport": True}
                        },
                        "workDoneProgress": True,
                    }
                },
                "initializationOptions": {
                    "clangdFileStatus": True,
                    "fallbackFlags": [],
                },
            },
            self.INIT_MSG_ID,
        )

        self._send_lsp_message(proc, init_msg)
        init_response = self._read_lsp_response(proc, expected_id=self.INIT_MSG_ID)

        initialized_msg = self._create_lsp_message("initialized", {})
        self._send_lsp_message(proc, initialized_msg)
        self.logger.debug("LSP initialized")

    def _open_file_in_lsp(
        self,
        proc: subprocess.Popen[Any],
        uri: str,
        text: Optional[str] = None,
        language: str = "c",
    ) -> None:
        """
        Open a file in the LSP server.
        If text is not provided, omit it from the message.
        """
        self.logger.debug(f"Opening file in LSP: {uri}")
        text_document = {"uri": uri, "languageId": language, "version": 1}
        if text is not None:
            text_document["text"] = text
        didopen_msg = self._create_lsp_message(
            "textDocument/didOpen", {"textDocument": text_document}
        )
        self._send_lsp_message(proc, didopen_msg)
        time.sleep(0.1)  # Allow LSP to process

    def _find_definition(
        self, proc: subprocess.Popen[Any], uri: str, line: int, character: int
    ) -> Dict[str, Any]:
        """Find definition using LSP."""
        def_msg = self._create_lsp_message(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
            self.DEFINITION_MSG_ID,
        )

        self._send_lsp_message(proc, def_msg)
        return self._read_lsp_response(proc, expected_id=self.DEFINITION_MSG_ID)

    def _find_actual_definition(
        self,
        proc: subprocess.Popen[Any],
        uri: str,
        line: int,
        character: int,
        identifier: str,
    ) -> Dict[str, Any]:
        # Log the original identifier location
        self.logger.debug(
            (
                f"Looking up definition for identifier '{identifier}' at location: "
                f"{uri}:{line}:{character}"
            )
        )
        current_location = LSPLocation(uri, line, character)

        resp_second = self._find_definition(
            proc,
            current_location.uri,
            current_location.line,
            current_location.character,
        )
        self.logger.debug(
            (
                "Clangd response for definition request (used result): "
                f"{json.dumps(resp_second, indent=2)}"
            )
        )

        if resp_second.get("result") and len(resp_second["result"]) > 0:
            loc = resp_second["result"][0]
            new_location = LSPLocation(
                loc["uri"],
                loc["range"]["start"]["line"],
                loc["range"]["start"]["character"],
            )
            self.logger.debug(
                (
                    f"Found at {new_location.uri}:{new_location.line}:"
                    f"{new_location.character} (after forced retry)"
                )
            )
        else:
            self.logger.debug(
                f"No definition found for {identifier} after forced retry."
            )
        return resp_second

    def _get_document_symbols(
        self, proc: subprocess.Popen[Any], uri: str, text: str, identifier: str
    ) -> Optional[Dict[str, Any]]:
        """Get document symbols and find specific identifier."""
        self._open_file_in_lsp(proc, uri, text, language="c")

        doc_symbol_msg = self._create_lsp_message(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": uri}},
            self.SYMBOL_MSG_ID,
        )

        self._send_lsp_message(proc, doc_symbol_msg)
        symbol_resp = self._read_lsp_response(proc, expected_id=self.SYMBOL_MSG_ID)

        if symbol_resp.get("result"):
            for sym in symbol_resp["result"]:
                if sym.get("name") == identifier:
                    return sym
        return None

    def parse_diff(self, diff_lines: List[str]) -> Dict[str, Set[int]]:
        """Parse diff lines to extract file additions and their line numbers."""
        file_adds: Dict[str, Set[int]] = {}
        current_file: Optional[str] = None
        new_line: Optional[int] = None

        for line in diff_lines:
            if line.startswith("+++ b/"):
                current_file = line[6:].strip()
                file_adds[current_file] = set()
            elif line.startswith("@@"):
                match = re.match(r"@@ -\d+(,\d+)? \+(\d+)(,\d+)? @@", line)
                if match:
                    new_line = int(match.group(2)) - 1
            elif (
                line.startswith("+")
                and not line.startswith("+++")
                and current_file is not None
                and new_line is not None
            ):
                file_adds[current_file].add(new_line)
                new_line += 1
            elif (
                not line.startswith("-")
                and not line.startswith("---")
                and not line.startswith("+++")
                and new_line is not None
            ):
                new_line += 1

        return file_adds

    def extract_identifiers_with_positions(
        self, line: str, line_number: int
    ) -> List[Tuple[str, int, int]]:
        """Extract all identifiers from a line with their positions."""
        results: List[Tuple[str, int, int]] = []
        for match in re.finditer(self.IDENTIFIER_PATTERN, line):
            identifier = match.group(0)
            char_offset = match.start()
            results.append((identifier, line_number, char_offset))
        return results

    def _find_symbol_and_parent(
        self, symbols: List[Dict[str, Any]], identifier: str, line: int
    ) -> Optional[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
        """
        Recursively search the symbol tree for the symbol matching identifier
        at the given line.
        """

        def helper(
            nodes: List[Dict[str, Any]], parent: Optional[Dict[str, Any]] = None
        ) -> Optional[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
            for node in nodes:
                rng = node.get("range")
                if (
                    node.get("name") == identifier
                    and rng
                    and rng["start"]["line"] <= line <= rng["end"]["line"]
                ):
                    return (node, parent)
                if "children" in node:
                    found = helper(node["children"], node)
                    if found:
                        return found
            return None

        return helper(symbols)

    def _collect_definition(
        self,
        def_file: str,
        start: int,
        end: int,
        identifier: str,
        collected_defs: Dict[str, List[Tuple[int, int, str]]],
        parent_range: Optional[Tuple[int, int]] = None,
    ) -> None:
        """Collect definition information for later context building."""
        if def_file not in collected_defs:
            collected_defs[def_file] = []

        if parent_range:
            collected_defs[def_file].append(
                (parent_range[0], parent_range[1], f"parent_of_{identifier}")
            )
        else:
            collected_defs[def_file].append((start, end, identifier))

    def _build_essential_lines(
        self,
        collected_defs: Dict[str, List[Tuple[int, int, str]]],
        diff_line_numbers: Dict[str, Set[int]],
        def_file: str,
    ) -> Set[int]:
        """
        Build set of essential lines to print: diff lines + all definition regions.
        """
        essential_lines: Set[int] = set()

        # Add diff lines
        diff_lines = diff_line_numbers.get(
            os.path.relpath(def_file, KERNEL_PATH), set()
        )
        essential_lines.update(diff_lines)

        # Add definition ranges
        for start, end, _ in collected_defs.get(def_file, []):
            essential_lines.update(range(start, end + 1))

        return essential_lines

    def _fill_context_gaps(self, essential_lines: Set[int]) -> Set[int]:
        """Fill gaps of MAX_GAP or less between essential lines."""
        if not essential_lines:
            return essential_lines

        sorted_lines = sorted(essential_lines)
        print_lines = set(essential_lines)

        for i in range(len(sorted_lines) - 1):
            current_line = sorted_lines[i]
            next_line = sorted_lines[i + 1]
            gap_size = next_line - current_line - 1

            # Fill gaps of MAX_GAP or less
            if 0 < gap_size <= self.MAX_GAP:
                print_lines.update(range(current_line + 1, next_line))

        return print_lines

    def _format_file_context(self, def_file: str, print_lines: Set[int]) -> List[str]:
        """Format file context with proper gap indicators."""
        lines = self._get_file_lines(def_file)
        if not lines:
            return []

        file_context: List[str] = []
        n_lines = len(lines)
        i = 0

        while i < n_lines:
            if i in print_lines:
                # Start of a region to print
                region_start = i
                while i < n_lines and i in print_lines:
                    i += 1
                region_end = i
                file_context.extend(lines[region_start:region_end])
            else:
                # Start of a gap
                gap_start = i
                while i < n_lines and i not in print_lines:
                    i += 1
                gap_len = i - gap_start

                if gap_len > self.MAX_GAP:
                    # Convert 0-based to 1-based line numbers for display
                    start_line = gap_start + 1
                    end_line = gap_start + gap_len
                    file_context.append(f"// skipping lines {start_line}-{end_line}\n")

        return file_context

    def _get_definition_context(
        self,
        collected_defs: Dict[str, List[Tuple[int, int, str]]],
        diff_line_numbers: Dict[str, Set[int]],
    ) -> List[str]:
        """Build context strings for all found definitions."""
        context_parts: List[str] = []

        for def_file in collected_defs:
            essential_lines = self._build_essential_lines(
                collected_defs, diff_line_numbers, def_file
            )
            if not essential_lines:
                continue

            print_lines = self._fill_context_gaps(essential_lines)
            file_context = self._format_file_context(def_file, print_lines)

            if file_context:
                rel_path = os.path.relpath(def_file, KERNEL_PATH).lstrip("/\\")
                context_parts.append(
                    f"{rel_path} (definition/diff context):\n\n```c\n"
                    + "".join(file_context)
                    + "```\n"
                )

        return context_parts

    def _merge_and_build_context(
        self,
        collected_defs: Dict[str, List[Tuple[int, int, str]]],
        file_adds: Dict[str, Set[int]],
    ) -> str:
        """Build the final context string from collected definitions."""
        diff_line_numbers = {file: set(lines) for file, lines in file_adds.items()}
        context_parts = self._get_definition_context(collected_defs, diff_line_numbers)
        return "\n\n".join(context_parts)

    def _setup_lsp_client(self) -> subprocess.Popen[Any]:
        """
        Set up and initialize the LSP client, and start background
        notification logger.
        """
        proc = subprocess.Popen(
            [
                "clangd",
                "--header-insertion=never",
                "--pretty",
                f"--compile-commands-dir={self.build_dir}",
                "--background-index",
                "--print-all-options",
                # "--log=verbose",
                "--log=error",
                # "--completion-parse=always"
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(KERNEL_PATH),
        )

        def _stderr_reader(stderr, logger):
            log_path = os.path.join(SANDBOX_PATH, "clangd_stderr.log")
            try:
                with open(log_path, "w") as log_file:
                    while True:
                        line = stderr.readline(4096)
                        if not line:
                            break
                        decoded_line = line.decode(errors="replace").rstrip()
                        # Print to console for explicit visibility
                        logger.debug(f"clangd stderr: {decoded_line}")
                        log_file.write(decoded_line + "\n")
            except Exception as e:
                logger.error(f"Error reading clangd stderr: {e}")

        stderr_thread = threading.Thread(
            target=_stderr_reader, args=(proc.stderr, self.logger), daemon=True
        )
        stderr_thread.start()

        self._initialize_lsp(proc, KERNEL_PATH)
        return proc

    def _process_file_identifiers(
        self,
        proc: subprocess.Popen[Any],
        filename: str,
        lines: Set[int],
        collected_defs: Dict[str, List[Tuple[int, int, str]]],
        printed_defs: Set[str],
        printed_locations: Set[Tuple[str, int, int]],
    ) -> None:
        """Process identifiers in a specific file."""
        abs_path = os.path.join(KERNEL_PATH, filename)
        uri = f"file://{abs_path}"

        if not os.path.exists(abs_path):
            return

        file_lines = self._get_file_lines(abs_path)
        if not file_lines:
            return

        self._open_file_in_lsp(proc, uri, "".join(file_lines))

        # Extract identifiers from added lines
        idents_with_pos: List[Tuple[str, int, int]] = []
        for lnum in lines:
            if lnum < len(file_lines):
                idents_with_pos.extend(
                    self.extract_identifiers_with_positions(file_lines[lnum], lnum)
                )

        # Get document symbols for the file
        doc_symbol_msg = self._create_lsp_message(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": uri}},
            self.DOC_SYMBOL_MSG_ID,
        )

        self._send_lsp_message(proc, doc_symbol_msg)
        symbol_resp = self._read_lsp_response(proc, expected_id=self.DOC_SYMBOL_MSG_ID)
        symbols = symbol_resp.get("result", [])

        for ident, lnum, col in idents_with_pos:
            self.logger.debug(
                f"Processing identifier '{ident}' at {uri}:{lnum + 1}:{col + 1}"
            )

            resp = self._find_actual_definition(proc, uri, lnum, col, ident)
            if not resp.get("result") or len(resp["result"]) == 0:
                continue
            loc = resp["result"][0]
            def_file = loc["uri"].replace("file://", "")
            if not os.path.exists(def_file):
                continue
            header_contents = self._read_file_safely(def_file)
            if not header_contents:
                continue
            def_symbol = self._get_document_symbols(
                proc, loc["uri"], header_contents, ident
            )

        self.logger.debug("Sleeping and trying again")
        time.sleep(15)

        # Process each identifier
        for ident, lnum, col in idents_with_pos:
            self.logger.debug(
                f"Processing identifier '{ident}' at {uri}:{lnum + 1}:{col + 1}"
            )

            if (
                ident in printed_defs
            ):  # TODO we shouldn't be skipping all matching identifiers, we should be
                # only skipping duplicate definitions. It's possible that 2 matching
                # identifiers (at different positions) actually have different
                # definitions.
                continue

            resp = self._find_actual_definition(proc, uri, lnum, col, ident)
            if not resp.get("result") or len(resp["result"]) == 0:
                self.logger.debug(
                    f"No definition found for {ident} in {uri} at line "
                    f"{lnum + 1}, column {col + 1}."
                )
                continue

            loc = resp["result"][0]
            def_file = loc["uri"].replace("file://", "")

            if not os.path.exists(def_file):
                continue

            header_contents = self._read_file_safely(def_file)
            if not header_contents:
                continue

            def_symbol = self._get_document_symbols(
                proc, loc["uri"], header_contents, ident
            )

            if def_symbol:
                start = def_symbol["location"]["range"]["start"]["line"]
                end = def_symbol["location"]["range"]["end"]["line"]
            else:
                self.logger.debug(
                    f"Definition for {ident}, {lnum}, {col} not found in {def_file}."
                )
                start = loc["range"]["start"]["line"]
                end = loc["range"]["end"]["line"]

            def_loc = (def_file, start, end)
            if def_loc in printed_locations:
                continue

            # Find parent symbol range
            parent_range = None
            if symbols:
                found = self._find_symbol_and_parent(symbols, ident, start)
                if found and found[1]:
                    parent = found[1]
                    prng = parent.get("range")
                    if prng:
                        parent_range = (prng["start"]["line"], prng["end"]["line"])

            self._collect_definition(
                def_file, start, end, ident, collected_defs, parent_range
            )
            printed_defs.add(ident)
            printed_locations.add(def_loc)

    def wait_for_diagnostics(
        self, proc: subprocess.Popen[Any], file_uri: str, timeout: int = 10
    ) -> Optional[dict]:
        """
        Wait for textDocument/publishDiagnostics for the given file URI.
        Returns the diagnostics params dict, or None if timeout.
        """
        self.logger.debug(
            f"Waiting for diagnostics for {file_uri} with timeout {timeout} seconds"
        )
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                msg = self._read_lsp_response(proc)
            except Exception as e:
                self.logger.debug(f"Exception while waiting for diagnostics: {e}")
                break
            if msg.get("method") == "textDocument/publishDiagnostics":
                params = msg.get("params", {})
                if params.get("uri") == file_uri:
                    self.logger.debug(
                        (
                            f"Received diagnostics for {file_uri}: "
                            f"{json.dumps(msg, indent=2)}"
                        )
                    )
                    return params
            self.logger.debug(
                (
                    f"Received message that wasn't a diagnostic message for {file_uri}:"
                    f" {json.dumps(msg)}"
                )
            )
        self.logger.warning(f"Timeout waiting for diagnostics for {file_uri}")
        return None

    def wait_for_clangd_indexing(
        self,
        proc: subprocess.Popen[Any],
        max_total_wait: int = 600,
        max_stale_time: int = 60,
        interval: int = 1,
        max_interval: int = 10,
    ) -> None:
        """
        Wait for clangd background indexing progress notifications,
        using exponential backoff.
        Reads all available messages from proc.stdout without pausing,
        only sleeps when no messages are available.
        Breaks if:
          - percentage reaches 100
          - no $/progress notification is received for max_wait seconds
          - the value does not change from the last message for max_wait seconds
        """
        import select

        last_percentage = None
        last_value = None
        waited = 0
        current_interval = interval
        start_time = time.time()
        while time.time() - start_time < max_total_wait:
            message_read = False
            while True:
                # Check if there's data to read from proc.stdout
                ready = select.select([proc.stdout], [], [], 0)[0]
                if not ready:
                    break
                try:
                    msg = self._read_lsp_response(proc)
                    message_read = True
                except Exception as e:
                    self.logger.debug(
                        f"Exception while waiting for clangd indexing: {e}"
                    )
                    break
                # Only interested in $/progress notifications
                if msg.get("method") == "$/progress":
                    params = msg.get("params", {})
                    token = params.get("token")
                    value = params.get("value", {})
                    if token == "backgroundIndexProgress" and isinstance(value, dict):
                        percentage = value.get("percentage")
                        if percentage is not None:
                            if percentage == 100:
                                return
                            if last_percentage == percentage and last_value == value:
                                # No progress since last check
                                waited += current_interval
                                if current_interval >= max_stale_time:
                                    self.logger.error(
                                        (
                                            f"No progress in {max_stale_time} seconds, "
                                            "giving up."
                                        )
                                    )
                                    return
                            else:
                                waited = 0
                                current_interval = interval
                            last_percentage = percentage
                            last_value = value
                        else:
                            # No percentage, just continue
                            self.logger.debug(
                                (
                                    "Received backgroundIndexProgress without"
                                    f" percentage: {json.dumps(value, indent=2)}"
                                )
                            )
                            pass
                    else:
                        # Not a backgroundIndexProgress, just continue
                        self.logger.debug(
                            (
                                f"Received $/progress with token {token} but not "
                                f"backgroundIndexProgress: {json.dumps(msg, indent=2)}"
                            )
                        )
                        pass
                else:
                    # Not a $/progress message, just continue
                    self.logger.debug(
                        f"Received non-progress message: {json.dumps(msg, indent=2)}"
                    )
                    pass
            # If no message was read, sleep with exponential backoff
            if not message_read:
                time.sleep(current_interval)
                current_interval = min(current_interval * 2, max_interval)
                waited += current_interval
        if time.time() - start_time >= max_total_wait:
            self.logger.warning(
                (
                    f"Clangd indexing did not complete within {max_total_wait} seconds,"
                    " giving up."
                )
            )

    def trick_clangd(
        self, proc: subprocess.Popen[Any], file_adds: Dict[str, Set[int]]
    ) -> None:
        """
        Trick clangd into indexing definitions by making a dummy pass and reading
        messages for 15 seconds.
        """
        # Dummy query: open the first file if any
        first_file = next(iter(file_adds), None)
        if first_file:
            abs_path = os.path.join(KERNEL_PATH, first_file)
            if os.path.exists(abs_path):
                file_lines = self._get_file_lines(abs_path)
                if file_lines:
                    self._open_file_in_lsp(
                        proc, f"file://{abs_path}", "".join(file_lines)
                    )

        self.wait_for_clangd_indexing(proc)
        # Read LSP messages for 15 seconds

    def _collect_definitions(
        self, file_adds: Dict[str, Set[int]]
    ) -> Dict[str, List[Tuple[int, int, str]]]:
        """
        Collect all definitions from the diff using LSP, but wait after a dummy pass
        before real querying.
        """
        # Start the LSP client and make a dummy query to trigger indexing
        proc = self._setup_lsp_client()

        # Now process all identifiers as normal
        printed_defs: Set[str] = set()
        printed_locations: Set[Tuple[str, int, int]] = set()
        collected_defs: Dict[str, List[Tuple[int, int, str]]] = {}
        for filename, lines in file_adds.items():
            self._process_file_identifiers(
                proc, filename, lines, collected_defs, printed_defs, printed_locations
            )
        proc.terminate()
        return collected_defs

    def process_diff_and_print_definitions(self, diff_lines: List[str]) -> None:
        """Process diff and collect definitions for context building."""
        file_adds = self.parse_diff(diff_lines)
        if not file_adds:
            self.logger.error("No additions found in diff.")
            return

        collected_defs = self._collect_definitions(file_adds)
        self.context = self._merge_and_build_context(collected_defs, file_adds)

    def delete_cache(self) -> None:
        """Remove the .cache directory under KERNEL_PATH"""
        import os

        cache_dir = os.path.join(KERNEL_PATH, ".cache")
        try:
            import shutil

            shutil.rmtree(cache_dir, ignore_errors=True)
            self.logger.debug(f"Removed cache directory: {cache_dir}")
        except Exception as e:
            self.logger.error(f"Failed to remove cache directory {cache_dir}: {e}")

    def get_context(self) -> None:
        """Generate context for the AI review."""
        self.delete_cache()  # TEMP DELETE

        self.generate_compile_commands()  # TEMP uncomment
        if not hasattr(self, "context"):
            self.context = ""
        # Split self.diff into lines and strip trailing newlines
        diff_lines = [line.rstrip("\n") for line in self.diff.splitlines()]
        self.process_diff_and_print_definitions(diff_lines)
        self.logger.debug(f"Context after processing diff: {self.context}")

    def setup(self) -> None:
        super().setup()

    def run(self) -> str:
        """Execute the AI code review."""
        self.get_context()

        prompt_template = self._load_prompt_template()
        formatted_prompt = prompt_template.format(
            diff=self.diff, commit_text=self.commit_message, context=self.context
        )

        # self.logger.debug(f"System prompt:\n{self.get_system_prompt()}") # TEMP
        self.logger.debug(f"Formatted prompt for AI review:\n{formatted_prompt}")

        # Write prompts to sandbox for debugging
        prompt_path = os.path.join(SANDBOX_PATH, "prompt.md")
        with open(prompt_path, "w") as f:
            f.write(formatted_prompt)

        system_prompt_path = os.path.join(SANDBOX_PATH, "system_prompt.md")
        with open(system_prompt_path, "w") as f:
            f.write(self.get_system_prompt())

        result = self.provider_api_call(
            user_prompt=formatted_prompt,
            system_prompt=self.get_system_prompt(),
        )

        return self.format_chat_response(result)
