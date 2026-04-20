# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, unquote

from patchwise import SANDBOX_PATH
from patchwise.patch_review.decorators import register_llm_review, register_long_review
from patchwise.utils.decorators import lru_cache_cb

from ..ai_review import AiReview
from .tool_definitions import TOOLS

# Container-side tree-sitter indexer path
TS_INDEXER_PATH = "/home/patchwise/bin/ts_indexer.py"

# Max open documents in clangd before LRU eviction
_CLANGD_OPEN_FILE_CAPACITY = 16


def path_to_uri(path: str) -> str:
    """Convert a file path to a file:// URI."""
    return Path(path).absolute().as_uri()


def uri_to_path(uri: str) -> str:
    """Convert a file:// URI to file path."""
    return unquote(urlparse(uri).path)


@register_llm_review
@register_long_review
class AiCodeReview(AiReview):
    """AI-powered code review for Linux kernel patches using LSP and clangd."""

    # LSP message IDs
    INIT_MSG_ID = 1
    DEFINITION_MSG_ID = 2
    SYMBOL_MSG_ID = 3
    REFERENCE_MSG_ID = 4
    DECLARATION_MSG_ID = 5
    PREPARE_CALL_HIERARCHY_MSG_ID = 6
    INCOMING_CALLS_MSG_ID = 7
    OUTGOING_CALLS_MSG_ID = 8

    PROMPT_TEMPLATE = """
# User Prompt

Review the following patch diff and provide inline feedback on the code changes. Additional context will be provided to help you understand the code and its purpose.

## Commit text

{commit_text}

## Patch Diff to review

```diff
{diff}
```

"""

    def get_kernel_coding_style(self) -> str:
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
            doc_path = os.path.join(self.kernel_path, doc["path"])
            guidelines_doc += f"## {doc['name']}:\n\n"
            try:
                with open(doc_path, "r") as f:
                    guidelines_doc += f.read()
            except Exception as e:
                guidelines_doc += f"[Could not load {doc['name']} file {doc_path}: {e}]"
            guidelines_doc += "\n"

        return guidelines_doc

    def get_system_prompt(self) -> str:
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

## Available Tools

You have access to code-navigation tools, use them aggressively. The diff alone is never enough context to review a kernel patch.

Tools (all paths are kernel-relative, e.g. `drivers/mtd/nand/raw/qcom_nandc.c`):

- `find_definition(name, file?)`
- `find_callers(name, file?)`
- `find_calls(name, file?)`
- `find_references(name, file?)`
- `grep(pattern, file?)`
- `read_file(path, start?, end?)`
- `list_files(path, recursive?)`

Only write your review once you have verified your findings against the code. Do not speculate — if you cannot confirm a bug by reading the relevant definitions, do not comment on it.
Tool results include file paths and snippets; use the paths as `file=` hints on follow-up calls to disambiguate symbols that exist in multiple subsystems. Prefer several targeted tool calls over guessing.

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

""" + self.get_kernel_coding_style()

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
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        build_dir = self.docker_manager.build_dir

        self.logger.debug("Running make defconfig")
        self._run_make_command(["defconfig"])

        self.logger.debug("Running make prepare")
        self._run_make_command(["prepare"])

        self.logger.debug("Generating compile commands using compiledb")
        make_dryrun_cmd = [
            "make",
            "-nwk",
            f"-j{os.cpu_count() or 4}",
            "-C",
            str(kernel_dir),
            f"O={build_dir}",
            "ARCH=arm64",
            "LLVM=1",
        ]
        build_log = self.run_cmd_with_timer(
            make_dryrun_cmd, "make dry-run for compile commands", cwd=str(build_dir)
        )

        compiledb_cmd = [
            "compiledb",
            "-o",
            str(build_dir / "compile_commands.json"),
        ]
        compiledb_proc = self.docker_manager.run_interactive_command(
            compiledb_cmd, cwd=str(build_dir)
        )
        stdout, stderr = compiledb_proc.communicate(input=build_log)
        if compiledb_proc.returncode != 0:
            raise RuntimeError(
                f"compiledb failed (rc={compiledb_proc.returncode}): {stderr}"
            )
        if stdout:
            self.logger.debug(stdout)
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

            if msg.get("method") == "textDocument/publishDiagnostics":
                continue

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
                "rootUri": path_to_uri(project_root),
                "capabilities": {
                    "textDocument": {
                        "declaration": {
                            "dynamicRegistration": False,
                            "linkSupport": True,
                        },
                        "callHierarchy": {
                            "dynamicRegistration": False,
                        },
                        "references": {
                            "container": True,
                        },
                    },
                },
                "initializationOptions": {
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

    def _close_file_in_lsp(self, proc: subprocess.Popen[Any], uri: str) -> None:
        """Close a file in the LSP server."""
        self.logger.debug(f"Closing file in LSP: {uri}")
        didclose_msg = self._create_lsp_message(
            "textDocument/didClose", {"textDocument": {"uri": uri}}
        )
        self._send_lsp_message(proc, didclose_msg)

    def _find_definition(
        self, proc: subprocess.Popen[Any], uri: str, line: int, character: int
    ) -> Dict[str, Any]:
        """Find definition using LSP."""
        self._open_document(uri)
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

    def _find_references(
        self, proc: subprocess.Popen[Any], uri: str, line: int, character: int
    ) -> Dict[str, Any]:
        """Find references using LSP."""
        self._open_document(uri)
        ref_msg = self._create_lsp_message(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": False},
            },
            self.REFERENCE_MSG_ID,
        )
        self.logger.debug(f"Sending LSP references request: {json.dumps(ref_msg)}")
        self._send_lsp_message(proc, ref_msg)
        return self._read_lsp_response(proc, expected_id=self.REFERENCE_MSG_ID)

    def _find_declaration(
        self, proc: subprocess.Popen[Any], uri: str, line: int, character: int
    ) -> Dict[str, Any]:
        """Find the declaration location."""
        self._open_document(uri)
        decl_msg = self._create_lsp_message(
            "textDocument/declaration",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
            self.DECLARATION_MSG_ID,
        )
        self.logger.debug(f"Sending LSP declaration request: {json.dumps(decl_msg)}")
        self._send_lsp_message(proc, decl_msg)
        response = self._read_lsp_response(proc, expected_id=self.DECLARATION_MSG_ID)
        self.logger.debug(f"Received LSP declaration response: {json.dumps(response)}")
        return response

    def _prepare_call_hierarchy(
        self, proc: subprocess.Popen[Any], uri: str, line: int, character: int
    ) -> List[Dict[str, Any]]:
        """Resolve a CallHierarchyItem for the symbol at the position (file must be open)."""
        prepare_msg = self._create_lsp_message(
            "textDocument/prepareCallHierarchy",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
            self.PREPARE_CALL_HIERARCHY_MSG_ID,
        )
        self.logger.debug(f"Sending prepareCallHierarchy: {json.dumps(prepare_msg)}")
        self._send_lsp_message(proc, prepare_msg)
        response = self._read_lsp_response(
            proc, expected_id=self.PREPARE_CALL_HIERARCHY_MSG_ID
        )
        result = response.get("result") or []
        if isinstance(result, dict):
            result = [result]
        return result

    def _get_callers(
        self, proc: subprocess.Popen[Any], uri: str, line: int, character: int
    ) -> Dict[str, Any]:
        """Incoming call hierarchy."""
        self._open_document(uri)
        items = self._prepare_call_hierarchy(proc, uri, line, character)
        if not items:
            return {
                "result": [],
                "note": "No call hierarchy item found at this position",
            }

        incoming_msg = self._create_lsp_message(
            "callHierarchy/incomingCalls",
            {"item": items[0]},
            self.INCOMING_CALLS_MSG_ID,
        )
        self.logger.debug(f"Sending incomingCalls: {json.dumps(incoming_msg)}")
        self._send_lsp_message(proc, incoming_msg)
        response = self._read_lsp_response(proc, expected_id=self.INCOMING_CALLS_MSG_ID)
        calls = response.get("result") or []
        if isinstance(calls, dict):
            calls = [calls]
        return {"result": calls}

    def _get_callees(
        self, proc: subprocess.Popen[Any], uri: str, line: int, character: int
    ) -> Dict[str, Any]:
        """Outgoing call hierarchy. Document lifetime is LRU-cached."""
        self._open_document(uri)
        items = self._prepare_call_hierarchy(proc, uri, line, character)
        if not items:
            return {
                "result": [],
                "note": "No call hierarchy item found at this position",
            }

        outgoing_msg = self._create_lsp_message(
            "callHierarchy/outgoingCalls",
            {"item": items[0]},
            self.OUTGOING_CALLS_MSG_ID,
        )
        self.logger.debug(f"Sending outgoingCalls: {json.dumps(outgoing_msg)}")
        self._send_lsp_message(proc, outgoing_msg)
        response = self._read_lsp_response(proc, expected_id=self.OUTGOING_CALLS_MSG_ID)
        calls = response.get("result") or []
        if isinstance(calls, dict):
            calls = [calls]
        return {"result": calls}

    def _kernel_rel(self, path_or_uri: str) -> str:
        """Normalize any path/URI to a kernel-relative POSIX string."""
        s = path_or_uri
        if s.startswith("file://"):
            s = uri_to_path(s)
        if s.startswith("/home/patchwise/kernel/"):
            s = s[len("/home/patchwise/kernel/") :]
        kp = str(self.kernel_path).rstrip("/")
        if s.startswith(kp + "/"):
            s = s[len(kp) + 1 :]
        if s.startswith("a/") or s.startswith("b/"):
            s = s[2:]
        return s.lstrip("/")

    def _abs_in_kernel(self, rel: str) -> Path:
        """Safe-join a kernel-relative path under kernel_path, rejecting .. escapes."""
        rel_norm = self._kernel_rel(rel)
        target = (Path(self.kernel_path) / rel_norm).resolve()
        base = Path(self.kernel_path).resolve()
        if not str(target).startswith(str(base)):
            raise ValueError(f"Path escapes kernel tree: {rel}")
        return target

    def _snippet_for_range(
        self, rel_path: str, start_line: int, end_line: int, ctx: int = 2
    ) -> str:
        """Return lines [start-ctx, end+ctx] for a kernel-relative path, capped at 200 lines."""
        try:
            path = self._abs_in_kernel(rel_path)
        except Exception:
            return ""
        lines = self._get_file_lines(str(path))
        if not lines:
            return ""
        lo = max(0, start_line - 1 - ctx)
        hi = min(len(lines), end_line + ctx)
        if hi - lo > 200:
            hi = lo + 200
        return "".join(lines[lo:hi])

    def _start_ts_daemon(self) -> None:
        """Spawn the container-side tree-sitter index daemon.

        The daemon builds the index once, then serves JSON-RPC queries over
        stdin/stdout.
        """
        if getattr(self, "ts_daemon", None) is not None:
            return
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        self.logger.info("tree-sitter: starting index daemon in container")
        start = time.time()
        self.ts_daemon = self.docker_manager.run_interactive_command(
            ["python3", TS_INDEXER_PATH, str(kernel_dir)],
            cwd=str(kernel_dir),
        )
        # Block on the `ready` line the daemon emits after it finishes building.
        ready_line = self.ts_daemon.stdout.readline() if self.ts_daemon.stdout else ""
        if not ready_line:
            raise RuntimeError("ts_indexer daemon exited before ready signal")
        try:
            ready = json.loads(ready_line)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"ts_indexer ready signal not JSON: {e}\nline: {ready_line!r}"
            )
        if not ready.get("ready"):
            raise RuntimeError(f"ts_indexer ready signal malformed: {ready}")
        self.logger.info(
            f"tree-sitter: daemon ready in {time.time() - start:.1f}s — "
            f"{ready.get('unique_names', 0)} unique names, "
            f"{ready.get('entries', 0)} entries, "
            f"{ready.get('files_parsed', 0)} parsed, "
            f"{ready.get('files_skipped', 0)} skipped"
        )

    def _ts_query(self, **req: Any) -> Dict[str, Any]:
        """Send one JSON-RPC request to the ts_indexer daemon and read its reply."""
        if getattr(self, "ts_daemon", None) is None:
            raise RuntimeError("ts_indexer daemon not started")
        proc = self.ts_daemon
        if proc.stdin is None or proc.stdout is None:
            raise RuntimeError("ts_indexer daemon has no stdio")
        if proc.poll() is not None:
            raise RuntimeError(f"ts_indexer daemon has exited (rc={proc.returncode})")
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("ts_indexer daemon closed stdout")
        return json.loads(line)

    def _ts_lookup(self, name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Return up to `limit` index entries matching `name`."""
        resp = self._ts_query(op="lookup", name=name, limit=limit)
        if "error" in resp:
            raise RuntimeError(f"ts_indexer error: {resp['error']}")
        return resp.get("candidates", [])

    def _ts_funcs_in_file(self, rel_path: str) -> List[Dict[str, Any]]:
        """Return function ranges for a single kernel-relative file."""
        resp = self._ts_query(op="funcs_in_file", path=rel_path)
        if "error" in resp:
            raise RuntimeError(f"ts_indexer error: {resp['error']}")
        return resp.get("funcs", [])

    @lru_cache_cb(maxsize=_CLANGD_OPEN_FILE_CAPACITY, on_evict="_close_document")
    def _open_document(self, uri: str) -> None:
        """Send didOpen to clangd for `uri`. Cached per-instance, LRU-evicted.

        On eviction, `_close_document` sends the matching didClose. Callers
        invoke this to kick off Clangd's dynamic indexing.
        """
        docker_path = uri_to_path(uri)
        contents = self.docker_manager.read_file(docker_path)
        if contents is None:
            raise RuntimeError(f"Unable to read document for LSP: {uri}")
        # Callers must not route non-C sources through this path.
        self._open_file_in_lsp(self.agent_lsp_proc, uri, contents, language="c")

    def _close_document(self, key: Tuple[str, ...], _: Any) -> None:
        """Eviction callback for `_open_document`: send didClose to clangd."""
        (uri,) = key
        proc = getattr(self, "agent_lsp_proc", None)
        if proc is None or proc.poll() is not None:
            return
        try:
            self._close_file_in_lsp(proc, uri)
        except Exception as e:
            self.logger.debug(f"close failed for {uri}: {e}")

    def _rank_candidates(
        self, candidates: List[Dict[str, Any]], file_hint: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Sort candidates by disambiguation tier (1 = best)."""
        hint = self._kernel_rel(file_hint) if file_hint else None
        seen = self.seen_files

        # TO-DO: add a tier for "#include files of a seen file

        # "Same subsystem" (drivers/mtd, net/ipv4, drivers/gpio)
        def _prefixes(p: str) -> Set[str]:
            parts = p.split("/")
            return {"/".join(parts[:k]) for k in range(2, len(parts) + 1)}

        same_dirs: Set[str] = set()
        seen_prefixes: Set[str] = set()
        for f in seen:
            same_dirs.add(os.path.dirname(f))
            seen_prefixes |= _prefixes(f)

        def tier(cand: Dict[str, Any]) -> int:
            cf = cand["file"]
            if hint and cf == hint:
                return 1
            if cf in seen:
                return 2
            if os.path.dirname(cf) in same_dirs:
                return 3
            if _prefixes(cf) & seen_prefixes:
                return 4
            return 5

        return sorted(
            candidates,
            key=lambda c: (tier(c), c["file"]),
        )

    _TS_LOOKUP_LIMIT = 100

    def _resolve_name_to_location(
        self, name: str, file_hint: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Resolve a bare name to (best_candidate, alternatives)."""
        candidates = self._ts_lookup(name, limit=self._TS_LOOKUP_LIMIT)
        if not candidates:
            return None
        ranked = self._rank_candidates(candidates, file_hint)
        best = ranked[0]
        alternatives: List[Dict[str, Any]] = []
        if best["file"] not in self.seen_files and len(ranked) > 1:
            seen_alt_files: Set[str] = {best["file"]}
            for c in ranked[1:]:
                if c["file"] in seen_alt_files:
                    continue
                alternatives.append(c)
                seen_alt_files.add(c["file"])
                if len(alternatives) == 5:
                    break
        return {"best": best, "alternatives": alternatives}

    def _name_to_clangd_position(
        self, name: str, file_hint: Optional[str]
    ) -> Optional[Tuple[str, int, int, Dict[str, Any]]]:
        """Resolve name to (docker_uri, line_0based, character_0based, best_candidate)."""
        resolved = self._resolve_name_to_location(name, file_hint)
        if resolved is None:
            return None
        best = resolved["best"]
        uri = path_to_uri(str(self.docker_manager.kernel_dir / best["file"]))
        line = best["name_line"] - 1
        character = best["name_col"]
        return uri, line, character, best

    def _resolve_definition_via_clangd(
        self, ts_candidate: Dict[str, Any], name: str
    ) -> Optional[Dict[str, Any]]:
        """Ask clangd for the active definition at a tree-sitter-picked position.

        Tree-sitter sees every textual definition, including every #ifdef
        branch. For symbols defined under mutually-exclusive CONFIG_* macros,
        only clangd knows which branch the current build selects.
        """
        uri = path_to_uri(str(self.docker_manager.kernel_dir / ts_candidate["file"]))
        try:
            resp = self._find_definition(
                self.agent_lsp_proc,
                uri,
                ts_candidate["name_line"] - 1,
                ts_candidate["name_col"],
            )
        except Exception as e:
            self.logger.debug(f"clangd definition probe failed for {name}: {e}")
            return None
        result = resp.get("result") or []
        if isinstance(result, dict):
            result = [result]
        if not result:
            return None
        loc = result[0]
        loc_uri = loc.get("uri") or loc.get("targetUri") or ""
        rng = loc.get("range") or loc.get("targetRange") or {}
        start = rng.get("start") or {}
        if not loc_uri or "line" not in start:
            return None
        active_rel = self._kernel_rel(loc_uri)
        active_line = start["line"] + 1
        # Use tree-sitter entry to get the body range.
        for entry in self._ts_lookup(name, limit=self._TS_LOOKUP_LIMIT):
            if entry["file"] == active_rel and (
                entry["start_line"] == active_line
                or entry["start_line"] <= active_line <= entry["end_line"]
            ):
                return entry
        raise ValueError(
            f"clangd definition for '{name}' at {active_rel}:{active_line} "
            f"has no matching tree-sitter entry."
        )

    def get_tools(self) -> Optional[List[Dict[str, Any]]]:
        return TOOLS

    def _format_call_hierarchy_results(
        self, calls: List[Dict[str, Any]], item_key: str
    ) -> List[Dict[str, Any]]:
        formatted: List[Dict[str, Any]] = []
        for c in calls:
            item = c.get(item_key) or {}
            u = item.get("uri", "")
            rng = item.get("range") or item.get("selectionRange") or {}
            start = rng.get("start") or {}
            line_num = start.get("line", -1) + 1
            rel = self._kernel_rel(u)
            self.seen_files.add(rel)
            formatted.append(
                {
                    "name": item.get("name"),
                    "path": rel,
                    "line": line_num,
                    "snippet": self._snippet_for_range(rel, line_num, line_num, ctx=2),
                }
            )
        return formatted

    def _tool_find_definition(
        self, name: str, file: Optional[str] = None
    ) -> Dict[str, Any]:
        resolved = self._resolve_name_to_location(name, file)
        if resolved is None:
            return {"ok": False, "error": f"symbol '{name}' not found in index"}
        best = resolved["best"]
        alternatives = resolved["alternatives"]

        # Prefer clangd over tree-sitter: for symbols with multiple textual
        # definitions (e.g. #ifdef CONFIG_* variants), only clangd knows
        # which branch compile_commands.json selects.
        active = self._resolve_definition_via_clangd(best, name)
        if active is not None:
            best = active
            alternatives = []

        self.seen_files.add(best["file"])

        definition = {
            "path": best["file"],
            "line": best["start_line"],
            "snippet": self._snippet_for_range(
                best["file"], best["start_line"], best["end_line"], ctx=0
            ),
        }

        declaration: Optional[Dict[str, Any]] = None
        try:
            if not best["file"].endswith((".c", ".h")):
                raise RuntimeError(f"skip non-C declaration lookup: {best['file']}")
            docker_uri = path_to_uri(str(self.docker_manager.kernel_dir / best["file"]))
            decl_response = self._find_declaration(
                self.agent_lsp_proc,
                docker_uri,
                best["name_line"] - 1,
                best["name_col"],
            )
            decl_result = decl_response.get("result") or []
            if isinstance(decl_result, dict):
                decl_result = [decl_result]
            if decl_result:
                loc = decl_result[0]
                loc_uri = loc.get("uri") or loc.get("targetUri") or ""
                rng = loc.get("range") or loc.get("targetRange") or {}
                start = rng.get("start") or {}
                if loc_uri and "line" in start:
                    decl_rel = self._kernel_rel(loc_uri)
                    decl_line = start["line"] + 1
                    if decl_rel != best["file"] or decl_line != best["start_line"]:
                        declaration = {
                            "path": decl_rel,
                            "line": decl_line,
                            "snippet": self._snippet_for_range(
                                decl_rel, decl_line, decl_line, ctx=2
                            ),
                        }
                        self.seen_files.add(decl_rel)
        except Exception as e:
            self.logger.debug(f"declaration lookup failed for {name}: {e}")

        result: Dict[str, Any] = {
            "declaration": declaration,
            "definition": definition,
        }
        if alternatives:
            result["alternatives"] = [
                {"path": c["file"], "line": c["start_line"]} for c in alternatives
            ]
        return {"ok": True, **result}

    def _tool_find_references(
        self, name: str, file: Optional[str] = None
    ) -> Dict[str, Any]:
        pos = self._name_to_clangd_position(name, file)
        if pos is None:
            return {"ok": False, "error": f"symbol '{name}' not found in index"}
        uri, line, character, best = pos
        self.seen_files.add(best["file"])

        response = self._find_references(self.agent_lsp_proc, uri, line, character)
        refs = response.get("result") or []
        if isinstance(refs, dict):
            refs = [refs]

        total = len(refs)
        truncated = total > 100
        refs = refs[:100]

        formatted: List[Dict[str, Any]] = []
        for r in refs:
            u = r.get("uri") or r.get("targetUri") or ""
            rng = r.get("range") or r.get("targetRange") or {}
            start = rng.get("start") or {}
            line_num = start.get("line", -1) + 1
            rel = self._kernel_rel(u)
            self.seen_files.add(rel)
            formatted.append(
                {
                    "path": rel,
                    "line": line_num,
                    "container": r.get("containerName"),
                    "snippet": self._snippet_for_range(rel, line_num, line_num, ctx=2),
                }
            )
        return {
            "ok": True,
            "result": formatted,
            "total": total,
            "truncated": truncated,
        }

    def _tool_find_callers(
        self, name: str, file: Optional[str] = None
    ) -> Dict[str, Any]:
        pos = self._name_to_clangd_position(name, file)
        if pos is None:
            return {"ok": False, "error": f"symbol '{name}' not found in index"}
        uri, line, character, best = pos
        if best["kind"] != "function":
            return {
                "ok": False,
                "error": (
                    f"'{name}' is not a function; clangd's call hierarchy "
                    f"only covers callables. Use find_references for "
                    f"non-function symbols."
                ),
            }
        self.seen_files.add(best["file"])

        response = self._get_callers(self.agent_lsp_proc, uri, line, character)
        calls = response.get("result") or []
        if isinstance(calls, dict):
            calls = [calls]

        total = len(calls)
        truncated = total > 100
        formatted = self._format_call_hierarchy_results(calls[:100], "from")
        return {
            "ok": True,
            "result": formatted,
            "total": total,
            "truncated": truncated,
        }

    def _tool_find_calls(self, name: str, file: Optional[str] = None) -> Dict[str, Any]:
        # TO-DO: implement outgoing-call discovery via tree-sitter  or by
        # upgrading the container's clangd to a version (>= 20) that has a
        # working callHierarchy/outgoingCalls implementation.
        del name, file
        return {"ok": False, "error": "find_calls not implemented"}

    def _tool_grep(self, pattern: str, file: Optional[str] = None) -> Dict[str, Any]:
        try:
            re.compile(pattern)
        except re.error as e:
            return {"ok": False, "error": f"invalid regex: {e}"}

        file_filter = self._kernel_rel(file) if file else None
        kernel_dir = self.docker_manager.sandbox_path / "kernel"

        rg_cmd: List[str] = [
            "rg",
            "--line-number",
            "--no-heading",
            "--with-filename",
            "--max-count",
            "500",
        ]
        if file_filter:
            rg_cmd += ["-e", pattern, f"/home/patchwise/kernel/{file_filter}"]
        else:
            rg_cmd += [
                "--glob",
                "*.c",
                "--glob",
                "*.h",
                "-e",
                pattern,
                str(kernel_dir),
            ]

        try:
            output = self.run_cmd_with_timer(
                rg_cmd, f"grep '{pattern}'", cwd=str(kernel_dir)
            )
        except Exception as e:
            return {"ok": False, "error": f"ripgrep failed: {e}"}

        file_to_funcs: Dict[str, List[Tuple[int, int, str]]] = {}

        def funcs_for(rel_path: str) -> List[Tuple[int, int, str]]:
            if rel_path not in file_to_funcs:
                funcs = self._ts_funcs_in_file(rel_path)
                file_to_funcs[rel_path] = [
                    (f["start_line"], f["end_line"], f["name"]) for f in funcs
                ]
            return file_to_funcs[rel_path]

        results: List[Dict[str, Any]] = []
        seen_hits: Set[Tuple[str, int]] = set()
        for raw in output.splitlines():
            parts = raw.split(":", 2)
            if len(parts) != 3:
                continue
            hit_path, line_no_str, text = parts
            try:
                hit_line = int(line_no_str)
            except ValueError:
                continue
            rel = self._kernel_rel(hit_path)
            if (rel, hit_line) in seen_hits:
                continue
            seen_hits.add((rel, hit_line))

            enclosing: Optional[str] = None
            for s, e, fname in funcs_for(rel):
                if s <= hit_line <= e:
                    enclosing = fname
                    break

            results.append(
                {
                    "path": rel,
                    "enclosing_function": enclosing,
                    "line": hit_line,
                    "snippet": text.strip()[:240],
                }
            )

        total = len(results)
        truncated = total > 100
        results = results[:100]
        for r in results:
            self.seen_files.add(r["path"])
        return {
            "ok": True,
            "result": results,
            "total": total,
            "truncated": truncated,
        }

    def _tool_read_file(
        self, path: str, start: int = 1, end: Optional[int] = None
    ) -> Dict[str, Any]:
        try:
            # Validation only, rejects "../" escapes
            self._abs_in_kernel(path)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        rel = self._kernel_rel(path)
        container_path = str(self.docker_manager.kernel_dir / rel)
        content = self.docker_manager.read_file(container_path)
        if content is None:
            return {"ok": False, "error": f"not a file: {path}"}

        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        start_1 = max(1, start)
        request_end = end if end is not None else start_1 + 199
        effective_end = min(request_end, start_1 + 199, total_lines)
        content = "".join(lines[start_1 - 1 : effective_end])
        self.seen_files.add(rel)
        return {
            "ok": True,
            "result": {
                "path": rel,
                "start": start_1,
                "end": effective_end,
                "content": content,
                "truncated": effective_end < total_lines,
            },
        }

    def _tool_list_files(self, path: str, recursive: bool = False) -> Dict[str, Any]:
        try:
            self._abs_in_kernel(path)  # validation only; reject "../" escapes
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        rel = self._kernel_rel(path)
        container_path = str(self.docker_manager.kernel_dir / rel)

        check = self.docker_manager.run_command(
            ["test", "-d", container_path], cwd=None
        )
        check.communicate()
        if check.returncode != 0:
            return {"ok": False, "error": f"not a directory: {path}"}

        find_cmd = ["find", container_path, "-mindepth", "1"]
        if not recursive:
            find_cmd += ["-maxdepth", "1"]
        find_cmd += ["-printf", "%P\t%y\n"]
        proc = self.docker_manager.run_command(find_cmd, cwd=None)
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            return {"ok": False, "error": f"find failed: {stderr.strip()}"}

        entries: List[Dict[str, str]] = []
        for line in stdout.splitlines():
            name, sep, kind = line.partition("\t")
            if not sep:
                continue
            if any(part.startswith(".") for part in name.split("/")):
                continue
            entries.append(
                {
                    "name": name,
                    "type": "dir" if kind == "d" else "file",
                }
            )

        entries.sort(key=lambda e: e["name"])

        total = len(entries)
        truncated = total > 100
        entries = entries[:100]
        return {
            "ok": True,
            "result": {
                "entries": entries,
                "total": total,
                "truncated": truncated,
            },
        }

    def dispatch_tool(self, name: str, args: dict) -> dict:
        """Dispatch an agent tool by name. Returns {ok, ...}."""
        tool_map = {
            "find_definition": self._tool_find_definition,
            "find_references": self._tool_find_references,
            "find_callers": self._tool_find_callers,
            "find_calls": self._tool_find_calls,
            "grep": self._tool_grep,
            "read_file": self._tool_read_file,
            "list_files": self._tool_list_files,
        }
        tool_fn = tool_map.get(name)
        if tool_fn is None:
            return {"ok": False, "error": f"unknown tool: {name}"}

        try:
            if not hasattr(self, "agent_lsp_proc") or self.agent_lsp_proc is None:
                self.agent_lsp_proc = self._setup_lsp_client()
            return tool_fn(**args)
        except TypeError as e:
            return {"ok": False, "error": f"bad arguments for '{name}': {e}"}
        except Exception as e:
            self.logger.error(f"tool '{name}' raised: {e}")
            return {"ok": False, "error": str(e)}

    def _files_in_diff(self) -> Set[str]:
        """Return the set of kernel-relative file paths touched by the commit."""
        parent = self.commit.parents[0]
        return {d.b_path for d in parent.diff(self.commit) if d.b_path}

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
        self._initialize_lsp(proc, self.docker_manager.kernel_dir)
        return proc

    def setup(self) -> None:
        super().setup()
        self.kernel_path = Path(self.repo.working_dir)

        # Per-review agent state.
        self.ts_daemon: Optional[subprocess.Popen[Any]] = None
        self.seen_files: Set[str] = set()

        self.seen_files |= self._files_in_diff()

        self.generate_compile_commands()
        self._start_ts_daemon()

    def run(self) -> str:
        """Execute the AI code review."""
        formatted_prompt = self.PROMPT_TEMPLATE.format(
            diff=self.diff, commit_text=self.commit_message
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

        messages = [
            {"role": "system", "content": self.get_system_prompt()},
            {"role": "user", "content": formatted_prompt},
        ]
        result = self.run_agent_loop(messages)

        return self.format_chat_response(result)
