# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from patchwise import KERNEL_PATH, SANDBOX_PATH
from patchwise.patch_review.decorators import register_llm_review, register_long_review

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

    # LSP Configuration
    MAX_GAP = 5

    # File processing
    IDENTIFIER_PATTERN = r"\b[_a-zA-Z][_a-zA-Z0-9]*\b"

    # LSP message IDs
    INIT_MSG_ID = 1
    DEFINITION_MSG_ID = 2
    SYMBOL_MSG_ID = 3
    DOC_SYMBOL_MSG_ID = 100

    PROMPT_TEMPLATE = """
# User Prompt

Review the following patch diff and provide inline feedback on the code changes. Additional context will be provided to help you understand the code and its purpose.

## Relevant context

{context}

## Commit text

{commit_text}

## Patch Diff to review

```diff
{diff}
```

"""

    @staticmethod
    def get_kernel_coding_style() -> str:
        """Load kernel coding style guidelines from documentation."""
        coding_style_docs = [
            {
                "name": "Kernel Coding Style Guidelines",
                "path": "Documentation/process/coding-style.rst",
            },
            {
                "name": "Devicetree Coding Style Guidelines",
                "path": "Documentation/devicetree/bindings/dts-coding-style.rst",
            },
            {
                "name": "Kernel Rust Coding Style Guidelines",
                "path": "Documentation/rust/coding-guidelines.rst",
            },
        ]
        guidelines_doc = ""
        for doc in coding_style_docs:
            doc_path = os.path.join(KERNEL_PATH, doc["path"])
            guidelines_doc += f"## {doc['name']}:\n\n"
            try:
                with open(doc_path, "r") as f:
                    guidelines_doc += f.read()
            except Exception as e:
                guidelines_doc += f"[Could not load {doc['name']} file {doc_path}: {e}]"
            guidelines_doc += "\n"

        return guidelines_doc

    @classmethod
    def get_system_prompt(cls) -> str:
        """Generate the system prompt including kernel coding style guidelines."""
        return """
# System Prompt

## Instructions

You are a Linux kernel maintainer reviewing patches sent to the Linux kernel mailing list. You will receive a patch diff and your task is to provide inline feedback on the code changes. Your task is to find issues in the code, if any. Is it imperative that your diagnosis is accurate, that you correctly identify real bugs that must be addressed and do not provide false positives. You should NOT provide suggestions that place any burden of investigation onto the developer such as "verify" or "you should consider", if it is not worth being concrete and direct about, it's not worth mentioning. Most changes will have few to no bugs, so be very careful with pointing out issues as false positives are strictly not acceptable.

- Do NOT compliment the code.
- Do not comment on what the code is doing, your comments should exclusively be problems.
- Do not summarize the change.
- Do not comment on how the change makes a difference, you are providing feedback to the developer, not the maintainer.
- Your output must strictly be comments on bugs and what is incorrect.
- Only point out specific issues in the code.
- Keep your feedback minimal and to the point.
- Do NOT comment on what the code does correctly.
- Stay focused on the issues that need to be fixed.
- You should not provide a summary or a list of issues outside the inline comments.
- Do NOT summarize the code or your feedback at the end of the review.
- Your comments should not be C comments, they should be unquoted, interleaved between the lines of the quoted text (the lines that start with '>').
- MAKE SURE THAT YOUR SUGGESTIONS FOLLOW KERNEL CODING STYLE GUIDELINES.
- Use correct grammar and only ASCII characters.
- Do not tell developers to add comments.

### Positive Feedback

You have been doing a good job of only providing feedback when you are absolutely confident and not commenting on things you are not sure about. You have been doing a great job at keeping each of your comments short and to the point, without unnecessary explanations or compliments. You have been following the Linux kernel coding style guidelines and providing feedback that is relevant to the code changes. You have been doing a great job at providing feedback that is actionable and can be easily understood by the developer.

### Constructive Feedback

You need to work on providing feedback that is more specific and actionable. **You can also do a better job at not summarizing or stating what's correct.** It is not appropriate to tell developers that their code is correct or that they have done a good job. Instead, focus on the specific issues that need to be fixed and provide actionable feedback.

## Example Feedback from Maintainers

```
> diff --git a/arch/arm64/Kconfig.platforms b/arch/arm64/Kconfig.platforms
> index a541bb029..0ffd65e36 100644
> --- a/arch/arm64/Kconfig.platforms
> +++ b/arch/arm64/Kconfig.platforms
> @@ -270,6 +270,7 @@ config ARCH_QCOM
>  	select GPIOLIB
>  	select PINCTRL
>  	select HAVE_PWRCTRL if PCI
> +	select PCI_PWRCTRL_SLOT if PCI

PWRCTL isn't a fundamental feature of ARCH_QCOM, so why do we select it
here?

> diff --git a/arch/arm64/boot/dts/qcom/sm8550-hdk.dts b/arch/arm64/boot/dts/qcom/sm8550-hdk.dts
> index 29bc1ddfc7b25f203c9f3b530610e45c44ae4fb2..fe46699804b3a8fb792edc06b58b961778cd8d70 100644
> --- a/arch/arm64/boot/dts/qcom/sm8550-hdk.dts
> +++ b/arch/arm64/boot/dts/qcom/sm8550-hdk.dts
> @@ -857,10 +857,10 @@ vreg_l5n_1p8: ldo5 {{
>  			regulator-initial-mode = <RPMH_REGULATOR_MODE_HPM>;
>  		}};
>
> -		vreg_l6n_3p3: ldo6 {{
> -			regulator-name = "vreg_l6n_3p3";
> +		vreg_l6n_3p2: ldo6 {{

Please follow the naming from the board's schematics for the label and
regulator-name.

> +			regulator-name = "vreg_l6n_3p2";
>  			regulator-min-microvolt = <2800000>;
```

""" + cls.get_kernel_coding_style()

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
        """Run a make command with consistent arguments using Docker container."""
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        build_dir = self.docker_manager.build_dir

        base_args = [
            "make",
            "-C",
            str(kernel_dir),
            f"O={build_dir}",
            f"-j{os.cpu_count()}",
            "ARCH=arm64",
            "LLVM=1",
        ]
        full_args = base_args + args

        desc = " ".join(args)

        if capture_output:
            self.run_cmd_with_timer(full_args, desc, cwd=str(build_dir))
        elif stdout_file:
            output = self.run_cmd_with_timer(
                full_args,
                desc,
                cwd=str(build_dir),
            )
            # Write to container path, not host path
            container_stdout_file = stdout_file.replace(
                str(self.build_dir), str(build_dir)
            )
            write_cmd = ["sh", "-c", f"cat > {container_stdout_file}"]
            process = self.docker_manager.run_command(write_cmd, cwd=str(build_dir))
            if process.stdin:
                process.stdin.write(output)
                process.stdin.close()
            process.wait()
        else:
            self.run_cmd_with_timer(full_args, desc, cwd=str(build_dir))

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
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        build_dir = self.docker_manager.build_dir

        gen_compile_cmd = [
            "python3",
            str(kernel_dir / "scripts" / "clang-tools" / "gen_compile_commands.py"),
            "-d",
            str(build_dir),
            "-o",
            str(build_dir / "compile_commands.json"),
        ]

        self.run_cmd_with_timer(
            gen_compile_cmd, "generate compile commands", cwd=str(build_dir)
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

    def _make_message_string(self, msg: Dict[str, Any]) -> str:
        """Convert LSP message to string with proper headers for text mode subprocess."""
        msg_json = json.dumps(msg)
        return f"Content-Length: {len(msg_json.encode('utf-8'))}\r\n\r\n{msg_json}"

    def send_workDoneProgress_response(self, proc: subprocess.Popen[Any]) -> None:
        message = {"id": 0, "jsonrpc": "2.0", "result": None}
        self._send_lsp_message(proc, message)

    def _read_lsp_response(
        self,
        proc: subprocess.Popen[Any],
        expected_id: Optional[int] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Read and parse LSP response from process with timeout."""
        import select
        import time

        if proc.stdout is None:
            raise RuntimeError("Process stdout is None")

        start_time = time.time()

        while True:
            # Check if process is still alive
            if proc.poll() is not None:
                # Read any remaining stderr for debugging
                if proc.stderr:
                    stderr_output = proc.stderr.read()
                    if stderr_output:
                        self.logger.error(f"clangd stderr: {stderr_output}")
                raise RuntimeError(
                    f"clangd process died with return code {proc.returncode}"
                )

            # Check timeout
            if time.time() - start_time > timeout:
                raise RuntimeError(
                    f"Timeout waiting for LSP response after {timeout} seconds"
                )

            # Use select to check if data is available with timeout
            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if not ready:
                # No data available, check if we should continue waiting
                continue

            # Read headers character by character until we find the end of headers
            headers = ""
            while True:
                try:
                    # Read one character at a time to avoid readline hanging
                    char = proc.stdout.read(1)
                    if not char:
                        # Check if process died
                        if proc.poll() is not None:
                            raise RuntimeError(
                                f"clangd process died with return code {proc.returncode}"
                            )
                        # Check timeout
                        if time.time() - start_time > timeout:
                            raise RuntimeError(
                                f"Timeout reading LSP headers after {timeout} seconds"
                            )
                        time.sleep(0.01)  # Very short sleep
                        continue
                    headers += char

                    # Reduce header logging noise - only log if there's an issue
                    pass

                    # Check for different possible header endings
                    if "\r\n\r\n" in headers:
                        self.logger.debug("Found \\r\\n\\r\\n header separator")
                        break
                    elif "\n\n" in headers:
                        self.logger.debug("Found \\n\\n header separator")
                        break
                    elif headers.startswith('{"jsonrpc"'):
                        # This means there are no headers, just JSON content
                        self.logger.debug(
                            "No LSP headers found, appears to be direct JSON response"
                        )
                        # Treat the entire thing as content, no headers
                        content = headers
                        # Continue reading until we have a complete JSON object
                        brace_count = content.count("{") - content.count("}")
                        while brace_count > 0:
                            char = proc.stdout.read(1)
                            if not char:
                                break
                            content += char
                            if char == "{":
                                brace_count += 1
                            elif char == "}":
                                brace_count -= 1

                        self.logger.debug(
                            f"Read complete JSON without headers: {content[:200]}..."
                        )
                        try:
                            msg = json.loads(content)
                            if expected_id is None or msg.get("id") == expected_id:
                                return msg
                            continue  # Continue to next message
                        except json.JSONDecodeError as e:
                            self.logger.error(f"Failed to parse JSON: {e}")
                            raise RuntimeError(f"Invalid JSON in LSP response: {e}")

                except Exception as e:
                    # Check timeout on any exception
                    if time.time() - start_time > timeout:
                        raise RuntimeError(
                            f"Timeout reading LSP headers after {timeout} seconds: {e}"
                        )
                    time.sleep(0.01)
                    continue

            # Parse content length
            content_length = 0
            for line in headers.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    content_length = int(line.split(":")[1].strip())

            if content_length == 0:
                self.logger.warning("Received LSP message with no content length")
                continue

            # Read content
            content = proc.stdout.read(content_length)
            if content is None or len(content) != content_length:
                raise RuntimeError(
                    f"Failed to read complete content from process stdout. Expected {content_length}, got {len(content) if content else 0}"
                )

            try:
                msg = json.loads(content)
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to parse LSP message: {content}")
                raise RuntimeError(f"Invalid JSON in LSP response: {e}")

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
                    continue
                    self.logger.debug(f"Background index progress: {json.dumps(msg)}")

            self.logger.debug(
                f"Received LSP message with id {msg.get('id')}, expected {expected_id}: {json.dumps(msg, indent=2)}"
            )

    def _send_lsp_message(
        self, proc: subprocess.Popen[Any], message: Dict[str, Any]
    ) -> None:
        """Send an LSP message to the process."""
        if proc.stdin is None:
            raise RuntimeError("Process stdin is None")
        proc.stdin.write(self._make_message_string(message))
        proc.stdin.flush()

    def _initialize_lsp(
        self, proc: subprocess.Popen[Any], project_root: os.PathLike[str]
    ) -> None:
        """Initialize LSP connection with enhanced error handling."""
        self.logger.debug("Initializing LSP connection")

        # Check if clangd process is still alive before sending messages
        if proc.poll() is not None:
            raise RuntimeError(
                f"clangd process died before initialization with return code {proc.returncode}"
            )

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

        self.logger.debug(
            f"Sending LSP initialize message: {json.dumps(init_msg, indent=2)}"
        )

        try:
            self._send_lsp_message(proc, init_msg)
            self.logger.debug("Initialize message sent, waiting for response...")

            # Test if clangd is responding at all by checking if there's any data available
            import select

            self.logger.debug("Checking if clangd has any response data available...")
            ready, _, _ = select.select([proc.stdout], [], [], 2.0)  # Wait 2 seconds
            if not ready:
                self.logger.error(
                    "No response from clangd after 2 seconds - clangd may not be processing LSP messages"
                )
                # Try to read stderr to see if there are any error messages
                if proc.stderr:
                    try:
                        # Use non-blocking read to check stderr
                        stderr_ready, _, _ = select.select([proc.stderr], [], [], 0.1)
                        if stderr_ready:
                            stderr_output = proc.stderr.read()
                            if stderr_output:
                                self.logger.error(f"clangd stderr: {stderr_output}")
                    except Exception as e:
                        self.logger.debug(f"Could not read stderr: {e}")

                raise RuntimeError("clangd is not responding to LSP initialize message")

            self.logger.debug("clangd has response data available, reading...")

            # Use shorter timeout for initialization to fail fast if there's an issue
            init_response = self._read_lsp_response(
                proc, expected_id=self.INIT_MSG_ID, timeout=10
            )
            self.logger.debug(
                f"Received initialize response: {json.dumps(init_response, indent=2)}"
            )

            initialized_msg = self._create_lsp_message("initialized", {})
            self.logger.debug("Sending initialized notification...")
            self._send_lsp_message(proc, initialized_msg)

            self.logger.debug("LSP initialized successfully")

        except Exception as e:
            # If initialization fails, try to get stderr for debugging
            if proc.stderr:
                try:
                    stderr_output = proc.stderr.read()
                    if stderr_output:
                        self.logger.error(
                            f"clangd stderr during initialization: {stderr_output}"
                        )
                except Exception:
                    pass

            self.logger.error(f"LSP initialization failed: {e}")
            raise RuntimeError(f"Failed to initialize LSP connection: {e}")

    def _open_file_in_lsp(
        self,
        proc: subprocess.Popen[Any],
        uri: str,
        text: Optional[str] = None,
        language: str = "c",
    ) -> None:
        """Open a file in the LSP server. If text is not provided, omit it from the message."""
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

        self.logger.debug(
            f"Sending LSP definition request: {json.dumps(def_msg, indent=2)}"
        )
        self._send_lsp_message(proc, def_msg)
        response = self._read_lsp_response(proc, expected_id=self.DEFINITION_MSG_ID)
        self.logger.debug(
            f"Received LSP definition response: {json.dumps(response, indent=2)}"
        )
        return response

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
            f"Looking up definition for identifier '{identifier}' at location: {uri}:{line}:{character}"
        )
        current_location = LSPLocation(uri, line, character)

        # # Always perform two definition lookups and only use the second result (first is assumed cache miss)
        # resp_first = self._find_definition(proc, current_location.uri, current_location.line, current_location.character)
        # self.logger.debug(f"Clangd response for definition request (assumed cache miss): {json.dumps(resp_first, indent=2)}")

        # # If the first response has a result, open the file containing the supposed definition in the LSP
        # def_file_uri = None
        # def_file_text = None
        # if resp_first.get("result") and len(resp_first["result"]) > 0:
        #     loc = resp_first["result"][0]
        #     def_file_uri = loc["uri"]
        #     def_file_path = def_file_uri.replace("file://", "")
        #     if os.path.exists(def_file_path):
        #         def_file_text = self._read_file_safely(def_file_path)
        #         self._open_file_in_lsp(proc, def_file_uri, def_file_text)
        #         self.wait_for_diagnostics(proc, def_file_uri, timeout=15)
        # else:
        #     self.logger.warning(f"No definition found for {identifier} at {current_location.uri}:{current_location.line}:{current_location.character}.")

        # Wait for clangd indexing for 1 second before retrying
        # # self.wait_for_clangd_indexing(proc, max_total_wait=15) # TEMP reset to max_total_wait=1
        resp_second = self._find_definition(
            proc,
            current_location.uri,
            current_location.line,
            current_location.character,
        )
        self.logger.debug(
            f"Clangd response for definition request (used result): {json.dumps(resp_second, indent=2)}"
        )

        if resp_second.get("result") and len(resp_second["result"]) > 0:
            loc = resp_second["result"][0]
            new_location = LSPLocation(
                loc["uri"],
                loc["range"]["start"]["line"],
                loc["range"]["start"]["character"],
            )
            self.logger.debug(
                f"Found at {new_location.uri}:{new_location.line}:{new_location.character} (after forced retry)"
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
        """Recursively search the symbol tree for the symbol matching identifier at the given line."""

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
        """Build set of essential lines to print: diff lines + all definition regions."""
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
        # Debug what definitions were collected
        self.logger.info(
            f"Building context from {len(collected_defs)} files with definitions:"
        )
        for def_file, defs in collected_defs.items():
            rel_path = os.path.relpath(def_file, KERNEL_PATH)
            self.logger.info(f"  {rel_path}: {len(defs)} definitions")
            for start, end, identifier in defs[:3]:  # Show first 3 definitions per file
                self.logger.info(f"    - {identifier} (lines {start}-{end})")

        diff_line_numbers = {file: set(lines) for file, lines in file_adds.items()}
        context_parts = self._get_definition_context(collected_defs, diff_line_numbers)

        self.logger.info(f"Generated {len(context_parts)} context parts")
        for i, part in enumerate(context_parts):
            # Log first line of each context part to see what files are included
            first_line = part.split("\n")[0] if part else ""
            self.logger.info(f"  Context part {i + 1}: {first_line}")

        return "\n\n".join(context_parts)

    def _setup_lsp_client(self) -> subprocess.Popen[Any]:
        """Set up and initialize the LSP client using Docker exec."""
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        build_dir = self.docker_manager.build_dir

        # First, test if the container is still running
        self.logger.debug("Checking if container is still running...")
        try:
            # Simple test to see if container is alive
            test_proc = self.docker_manager.run_command(
                ["echo", "container_alive"],
                cwd=str(kernel_dir),
            )
            test_proc.wait()
            if test_proc.returncode != 0:
                raise RuntimeError("Docker container is not responding")
        except Exception as e:
            raise RuntimeError(
                f"Docker container appears to have died during build process: {e}"
            )

        # Now test if clangd is available in the container
        self.logger.debug("Testing clangd availability in container...")
        try:
            test_proc = self.docker_manager.run_command(
                ["which", "clangd"],
                cwd=str(kernel_dir),
            )
            test_proc.wait()
            if test_proc.returncode != 0:
                # Try to get more information about what's available
                self.logger.debug("clangd not found, checking what's installed...")
                ls_proc = self.docker_manager.run_command(
                    ["ls", "-la", "/usr/bin/clang*"],
                    cwd=str(kernel_dir),
                )
                ls_proc.wait()
                if ls_proc.stdout:
                    stdout_output = ls_proc.stdout.read()
                    self.logger.debug(f"Available clang tools: {stdout_output}")

                raise RuntimeError(
                    "clangd not found in Docker container - container may have crashed during build"
                )
        except Exception as e:
            raise RuntimeError(f"Failed to test clangd availability: {e}")

        # Comprehensive compile_commands.json debugging
        compile_commands_path = build_dir / "compile_commands.json"
        self.logger.info(f"=== COMPILE_COMMANDS.JSON DEBUGGING ===")
        self.logger.info(f"Expected path: {compile_commands_path}")
        self.logger.info(
            f"clangd will be started with --compile-commands-dir={build_dir}"
        )

        # Check if file exists
        check_proc = self.docker_manager.run_command(
            ["test", "-f", str(compile_commands_path)],
            cwd=str(kernel_dir),
        )
        check_proc.wait()

        if check_proc.returncode != 0:
            self.logger.error(
                f"compile_commands.json NOT FOUND at {compile_commands_path}"
            )
            # List what files are actually in the build directory
            ls_proc = self.docker_manager.run_command(
                ["ls", "-la", str(build_dir)],
                cwd=str(kernel_dir),
            )
            ls_proc.wait()
            if ls_proc.stdout:
                ls_output = ls_proc.stdout.read()
                self.logger.info(f"Build directory contents: {ls_output}")
        else:
            self.logger.info(f"compile_commands.json EXISTS at {compile_commands_path}")

            # Get file stats
            stat_proc = self.docker_manager.run_command(
                ["stat", str(compile_commands_path)],
                cwd=str(kernel_dir),
            )
            stat_proc.wait()
            if stat_proc.stdout:
                stat_output = stat_proc.stdout.read()
                self.logger.info(f"File stats: {stat_output}")

            # Get file size and first few lines
            wc_proc = self.docker_manager.run_command(
                ["wc", "-l", str(compile_commands_path)],
                cwd=str(kernel_dir),
            )
            wc_proc.wait()
            if wc_proc.stdout:
                wc_output = wc_proc.stdout.read()
                self.logger.info(f"File line count: {wc_output}")

            # Show first few entries
            head_proc = self.docker_manager.run_command(
                ["head", "-20", str(compile_commands_path)],
                cwd=str(kernel_dir),
            )
            head_proc.wait()
            if head_proc.stdout:
                head_output = head_proc.stdout.read()
                self.logger.info(f"First 20 lines: {head_output}")

            # Check if qcom_eud.c is in the compile commands
            grep_proc = self.docker_manager.run_command(
                ["grep", "-n", "qcom_eud.c", str(compile_commands_path)],
                cwd=str(kernel_dir),
            )
            grep_proc.wait()
            if grep_proc.stdout:
                grep_output = grep_proc.stdout.read()
                if grep_output:
                    self.logger.info(f"qcom_eud.c entries found: {grep_output}")
                else:
                    self.logger.warning("qcom_eud.c NOT found in compile_commands.json")
            else:
                self.logger.warning(
                    "Could not search for qcom_eud.c in compile_commands.json"
                )

        self.logger.info(f"=== END COMPILE_COMMANDS.JSON DEBUGGING ===")

        # Clean up any existing clangd processes
        self.docker_manager.cleanup_clangd()

        # Configure clangd with persistent index in build directory
        index_dir = build_dir / ".clangd"
        clangd_args = [
            "clangd",
            "--header-insertion=never",
            "--pretty",
            f"--compile-commands-dir={build_dir}",
            "--background-index",
            f"--index-file={index_dir}/index.idx",
            "--log=error",
            f"--j={os.cpu_count() or 4}",  # Parallel indexing
        ]

        self.logger.debug(
            f"Starting clangd LSP server with args: {' '.join(clangd_args)}"
        )

        # Start clangd via docker exec with direct stdin/stdout
        proc = self.docker_manager.start_clangd_lsp(clangd_args, cwd=str(kernel_dir))

        # Initialize LSP connection
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

        # Extract identifiers from added lines AND surrounding context
        idents_with_pos: List[Tuple[str, int, int]] = []

        # Process added lines
        for lnum in lines:
            if lnum < len(file_lines):
                idents_with_pos.extend(
                    self.extract_identifiers_with_positions(file_lines[lnum], lnum)
                )

        # Also process the entire file to find all function calls and identifiers
        # This ensures we catch functions like qcom_scm_io_writel that might be used
        # in existing code but not in the added lines
        self.logger.info(f"Also scanning entire file for additional identifiers...")
        for lnum, line in enumerate(file_lines):
            # Skip lines we already processed
            if lnum not in lines:
                idents_with_pos.extend(
                    self.extract_identifiers_with_positions(line, lnum)
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

        # Check if we have the specific identifier we're looking for
        target_identifiers = [
            "qcom_scm_io_writel",
            "usb_role_switch_set_role",
            "platform_device",
            "devm_add_action_or_reset",
        ]
        found_targets = [
            ident for ident, _, _ in idents_with_pos if ident in target_identifiers
        ]

        self.logger.info(f"Found {len(idents_with_pos)} identifiers in {filename}")

        # Log the actual added lines to see what we're working with
        self.logger.info(f"Processing added lines: {sorted(lines)}")
        for lnum in sorted(lines)[:5]:  # Show first 5 added lines
            if lnum < len(file_lines):
                self.logger.info(f"  Line {lnum + 1}: {repr(file_lines[lnum].strip())}")

        # Log all identifiers found to see if qcom_scm_io_writel is there with a different name
        all_identifiers = [ident for ident, _, _ in idents_with_pos]
        qcom_identifiers = [
            ident for ident in all_identifiers if "qcom" in ident.lower()
        ]
        if qcom_identifiers:
            self.logger.info(f"Found qcom-related identifiers: {qcom_identifiers}")

        if found_targets:
            self.logger.info(f"Found target identifiers: {found_targets}")
        else:
            self.logger.info(
                f"No target identifiers found. Looking for: {target_identifiers}"
            )

        # Wait for clangd to index the file
        time.sleep(5)

        # Process only target identifiers first to see what's happening
        definitions_found = 0
        external_definitions_found = 0

        for ident, lnum, col in idents_with_pos:
            if ident in printed_defs:
                continue

            # Focus on target identifiers for detailed logging
            is_target = ident in target_identifiers

            # Log detailed information for each identifier
            self.logger.info(f"=== PROCESSING IDENTIFIER ===")
            self.logger.info(f"Identifier: '{ident}'")
            self.logger.info(f"Location: {filename}:{lnum + 1}:{col + 1}")
            if lnum < len(file_lines):
                line_content = file_lines[lnum].strip()
                self.logger.info(f"Line content: {repr(line_content)}")
            self.logger.info(f"Is target identifier: {is_target}")

            try:
                resp = self._find_actual_definition(proc, uri, lnum, col, ident)

                # Log the complete LSP response for this identifier
                self.logger.info(f"LSP Definition Response for '{ident}':")
                self.logger.info(json.dumps(resp, indent=2))

                if not resp.get("result") or len(resp["result"]) == 0:
                    self.logger.warning(
                        f"No definition found for identifier '{ident}' at {uri}:{lnum + 1}:{col + 1}"
                    )
                    if is_target:
                        self.logger.error(
                            f"TARGET IDENTIFIER '{ident}' HAS NO DEFINITION!"
                        )
                    continue

                loc = resp["result"][0]
                def_file = loc["uri"].replace("file://", "")

                # Check if this is an external definition (different file)
                is_external = def_file != abs_path
                if is_external:
                    external_definitions_found += 1

                if is_target or is_external:
                    self.logger.info(
                        f"Found definition for '{ident}' in {def_file} (external: {is_external})"
                    )

                # Debug: Log ALL external definitions found
                if is_external:
                    self.logger.warning(
                        f"EXTERNAL DEFINITION: '{ident}' found in {def_file} at lines {loc['range']['start']['line']}-{loc['range']['end']['line']}"
                    )

                if not os.path.exists(def_file):
                    if is_target or is_external:
                        self.logger.warning(
                            f"Definition file does not exist: {def_file}"
                        )
                        # Try to find the file in common kernel locations
                        possible_paths = [
                            def_file,
                            def_file.replace(
                                "/home/patchwise/kernel/", str(KERNEL_PATH) + "/"
                            ),
                            def_file.replace(
                                "/home/patchwise/", str(KERNEL_PATH.parent) + "/"
                            ),
                        ]
                        for alt_path in possible_paths:
                            if os.path.exists(alt_path):
                                self.logger.info(f"Found alternative path: {alt_path}")
                                def_file = alt_path
                                break
                        else:
                            self.logger.error(
                                f"Could not find definition file anywhere: {def_file}"
                            )
                            continue

                header_contents = self._read_file_safely(def_file)
                if not header_contents:
                    if is_target:
                        self.logger.warning(
                            f"Could not read definition file: {def_file}"
                        )
                    continue

                def_symbol = self._get_document_symbols(
                    proc, loc["uri"], header_contents, ident
                )

                if def_symbol:
                    start = def_symbol["location"]["range"]["start"]["line"]
                    end = def_symbol["location"]["range"]["end"]["line"]
                else:
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
                definitions_found += 1

                if is_target or is_external:
                    self.logger.info(
                        f"Successfully collected definition for '{ident}' (total: {definitions_found})"
                    )

            except Exception as e:
                if is_target:
                    self.logger.error(
                        f"Error processing target identifier '{ident}': {e}"
                    )
                continue

        self.logger.info(
            f"Finished processing {filename}: found {definitions_found} definitions ({external_definitions_found} external) out of {len(idents_with_pos)} identifiers"
        )

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
                        f"Received diagnostics for {file_uri}: {json.dumps(msg, indent=2)}"
                    )
                    return params
            self.logger.debug(
                f"Received message that wasn't a diagnostic message for {file_uri}: {json.dumps(msg)}"
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
        Wait for clangd background indexing progress notifications, using exponential backoff.
        Reads all available messages from proc.stdout without pausing, only sleeps when no messages are available.
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
                            # self.logger.debug(f"clangd indexing progress: {percentage}%")
                            if percentage == 100:
                                return
                            if last_percentage == percentage and last_value == value:
                                # No progress since last check
                                waited += current_interval
                                if current_interval >= max_stale_time:
                                    self.logger.error(
                                        f"No progress in {max_stale_time} seconds, giving up."
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
                                f"Received backgroundIndexProgress without percentage: {json.dumps(value, indent=2)}"
                            )
                            pass
                    else:
                        # Not a backgroundIndexProgress, just continue
                        self.logger.debug(
                            f"Received $/progress with token {token} but not backgroundIndexProgress: {json.dumps(msg, indent=2)}"
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
                f"Clangd indexing did not complete within {max_total_wait} seconds, giving up."
            )

    def trick_clangd(
        self, proc: subprocess.Popen[Any], file_adds: Dict[str, Set[int]]
    ) -> None:
        """Trick clangd into indexing definitions by making a dummy pass and reading messages for 15 seconds."""
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
        # start_time = time.time()
        # while time.time() - start_time < 15:
        #     try:
        #         self._read_lsp_response(proc)
        #     except Exception as e:
        #         self.logger.debug(f"Exception while reading LSP response: {e}")
        #         # break

    def _collect_definitions(
        self, file_adds: Dict[str, Set[int]]
    ) -> Dict[str, List[Tuple[int, int, str]]]:
        """Collect all definitions from the diff using LSP with Docker exec."""
        # Start the LSP client using Docker exec
        proc = self._setup_lsp_client()

        try:
            # Process all identifiers using direct process communication
            printed_defs: Set[str] = set()
            printed_locations: Set[Tuple[str, int, int]] = set()
            collected_defs: Dict[str, List[Tuple[int, int, str]]] = {}

            for filename, lines in file_adds.items():
                self._process_file_identifiers(
                    proc,
                    filename,
                    lines,
                    collected_defs,
                    printed_defs,
                    printed_locations,
                )

            return collected_defs

        finally:
            # Clean up clangd process
            try:
                if proc.poll() is None:  # Process is still running
                    proc.terminate()
                    proc.wait(timeout=5)
            except Exception as e:
                self.logger.debug(f"Error terminating clangd process: {e}")
                try:
                    proc.kill()
                except Exception:
                    pass

            # Clean up any remaining clangd processes in container
            self.docker_manager.cleanup_clangd()

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

        formatted_prompt = self.PROMPT_TEMPLATE.format(
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
