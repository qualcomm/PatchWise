# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import json
import os
import subprocess
import time
from typing import Any, Dict, Optional

from patchwise import SANDBOX_PATH
from patchwise.patch_review.decorators import register_llm_review, register_long_review

from .ai_review import AiReview


@register_llm_review
@register_long_review
class AiCodeReview(AiReview):
    """AI-powered code review for Linux kernel patches using LSP and clangd."""

    PROMPT_TEMPLATE = """
# User Prompt

Review the following patch diff and provide inline feedback on the code changes.

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
        return """
# Kernel Coding Style

Follow Linux kernel coding standards.
"""

    @classmethod
    def get_system_prompt(cls) -> str:
        """Generate the system prompt including kernel coding style guidelines."""
        return """
# System Prompt

You are a Linux kernel maintainer reviewing patches. Provide concise, actionable feedback on bugs and issues only.

""" + cls.get_kernel_coding_style()

    def validate_docker_environment(self) -> bool:
        """Step 1: Validate container is running and has required tools."""
        self.logger.info("=" * 80)
        self.logger.info("STEP 1: Validating Docker Environment")
        self.logger.info("=" * 80)
        
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        
        # Test 1.1: Check container is alive
        self.logger.info("Test 1.1: Checking if container is running...")
        try:
            test_proc = self.docker_manager.run_command(
                ["echo", "container_alive"],
                cwd=str(kernel_dir),
            )
            test_proc.wait()
            if test_proc.returncode != 0:
                self.logger.error("❌ Container is not responding")
                return False
            self.logger.info("✓ Container is running")
        except Exception as e:
            self.logger.error(f"❌ Container check failed: {e}")
            return False

        # Test 1.2: Check clangd is available
        self.logger.info("Test 1.2: Checking if clangd is installed...")
        try:
            test_proc = self.docker_manager.run_command(
                ["which", "clangd"],
                cwd=str(kernel_dir),
            )
            test_proc.wait()
            if test_proc.returncode != 0:
                self.logger.error("❌ clangd not found in container")
                # Show what's available
                ls_proc = self.docker_manager.run_command(
                    ["ls", "-la", "/usr/bin/clang*"],
                    cwd=str(kernel_dir),
                )
                ls_proc.wait()
                if ls_proc.stdout:
                    stdout_output = ls_proc.stdout.read()
                    self.logger.info(f"Available clang tools: {stdout_output}")
                return False
            
            # Get clangd version
            if test_proc.stdout:
                clangd_path = test_proc.stdout.read().strip()
                self.logger.info(f"✓ clangd found at: {clangd_path}")
                
            version_proc = self.docker_manager.run_command(
                ["clangd", "--version"],
                cwd=str(kernel_dir),
            )
            version_proc.wait()
            if version_proc.stdout:
                version_output = version_proc.stdout.read()
                self.logger.info(f"clangd version: {version_output.strip()}")
                
        except Exception as e:
            self.logger.error(f"❌ clangd check failed: {e}")
            return False

        self.logger.info("✓ Docker environment validation passed")
        return True

    def build_kernel(self) -> bool:
        """Step 2 & 3: Build kernel with defconfig."""
        self.logger.info("=" * 80)
        self.logger.info("STEP 2 & 3: Building Kernel")
        self.logger.info("=" * 80)
        
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        build_dir = self.docker_manager.build_dir

        try:
            # Step 2: make defconfig
            self.logger.info("Step 2: Running make defconfig...")
            base_args = [
                "make",
                "-C",
                str(kernel_dir),
                f"O={build_dir}",
                f"-j{os.cpu_count()}",
                "ARCH=arm64",
                "LLVM=1",
            ]
            defconfig_args = base_args + ["defconfig"]
            
            self.run_cmd_with_timer(defconfig_args, "make defconfig", cwd=str(build_dir))
            self.logger.info("✓ make defconfig completed")

            # Step 3: make (build kernel)
            self.logger.info("Step 3: Running make to build kernel...")
            build_args = base_args + ["V=1"]
            
            output = self.run_cmd_with_timer(
                build_args,
                "make V=1",
                cwd=str(build_dir),
            )
            
            # Write build log
            build_log_path = self.build_dir / "build.log"
            container_build_log = str(build_dir / "build.log")
            write_cmd = ["sh", "-c", f"cat > {container_build_log}"]
            process = self.docker_manager.run_command(write_cmd, cwd=str(build_dir))
            if process.stdin:
                process.stdin.write(output)
                process.stdin.close()
            process.wait()
            
            self.logger.info("✓ Kernel build completed")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Kernel build failed: {e}")
            return False

    def generate_and_validate_compile_commands(self) -> bool:
        """Step 4: Generate and validate compile_commands.json."""
        self.logger.info("=" * 80)
        self.logger.info("STEP 4: Generating and Validating compile_commands.json")
        self.logger.info("=" * 80)
        
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        build_dir = self.docker_manager.build_dir
        compile_commands_path = build_dir / "compile_commands.json"

        try:
            # Generate compile_commands.json
            self.logger.info("Generating compile_commands.json...")
            gen_compile_cmd = [
                "python3",
                str(kernel_dir / "scripts" / "clang-tools" / "gen_compile_commands.py"),
                "-d",
                str(build_dir),
                "-o",
                str(compile_commands_path),
            ]
            
            self.run_cmd_with_timer(
                gen_compile_cmd, "generate compile commands", cwd=str(build_dir)
            )
            self.logger.info("✓ compile_commands.json generated")

            # Validate: Check file exists
            self.logger.info("Validating compile_commands.json...")
            check_proc = self.docker_manager.run_command(
                ["test", "-f", str(compile_commands_path)],
                cwd=str(kernel_dir),
            )
            check_proc.wait()

            if check_proc.returncode != 0:
                self.logger.error(f"❌ compile_commands.json NOT FOUND at {compile_commands_path}")
                # List build directory contents
                ls_proc = self.docker_manager.run_command(
                    ["ls", "-la", str(build_dir)],
                    cwd=str(kernel_dir),
                )
                ls_proc.wait()
                if ls_proc.stdout:
                    ls_output = ls_proc.stdout.read()
                    self.logger.info(f"Build directory contents:\n{ls_output}")
                return False

            self.logger.info(f"✓ compile_commands.json exists at {compile_commands_path}")

            # Get file stats
            stat_proc = self.docker_manager.run_command(
                ["stat", str(compile_commands_path)],
                cwd=str(kernel_dir),
            )
            stat_proc.wait()
            if stat_proc.stdout:
                stat_output = stat_proc.stdout.read()
                self.logger.info(f"File stats:\n{stat_output}")

            # Get line count
            wc_proc = self.docker_manager.run_command(
                ["wc", "-l", str(compile_commands_path)],
                cwd=str(kernel_dir),
            )
            wc_proc.wait()
            if wc_proc.stdout:
                wc_output = wc_proc.stdout.read()
                self.logger.info(f"✓ Line count: {wc_output.strip()}")

            # Show first 25 lines
            head_proc = self.docker_manager.run_command(
                ["head", "-n", "25", str(compile_commands_path)],
                cwd=str(kernel_dir),
            )
            head_proc.wait()
            if head_proc.stdout:
                head_output = head_proc.stdout.read()
                self.logger.info(f"First 25 lines:\n{head_output}")

            self.logger.info("✓ compile_commands.json validation passed")
            return True

        except Exception as e:
            self.logger.error(f"❌ compile_commands.json generation/validation failed: {e}")
            return False

    def test_clangd_startup(self) -> Optional[subprocess.Popen[Any]]:
        """Step 5: Start clangd and verify it's running."""
        self.logger.info("=" * 80)
        self.logger.info("STEP 5: Starting clangd LSP Server")
        self.logger.info("=" * 80)
        
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        build_dir = self.docker_manager.build_dir

        try:
            # Clean up any existing clangd processes
            self.docker_manager.cleanup_clangd()

            # Configure clangd
            index_dir = build_dir / ".clangd"
            clangd_args = [
                "clangd",
                "--header-insertion=never",
                "--pretty",
                f"--compile-commands-dir={build_dir}",
                "--background-index",
                f"--index-file={index_dir}/index.idx",
                "--log=error",
                f"--j={os.cpu_count() or 4}",
            ]

            self.logger.info(f"Starting clangd with args: {' '.join(clangd_args)}")
            self.logger.info(f"Working directory: {kernel_dir}")
            self.logger.info(f"Compile commands dir: {build_dir}")

            # Start clangd
            proc = self.docker_manager.start_clangd_lsp(clangd_args, cwd=str(kernel_dir))
            
            self.logger.info(f"✓ clangd started with PID: {proc.pid}")
            return proc

        except Exception as e:
            self.logger.error(f"❌ Failed to start clangd: {e}")
            return None

    def test_lsp_initialization(self, proc: subprocess.Popen[Any]) -> bool:
        """Step 6: Test LSP initialization."""
        self.logger.info("=" * 80)
        self.logger.info("STEP 6: Testing LSP Initialization")
        self.logger.info("=" * 80)
        
        kernel_dir = self.docker_manager.sandbox_path / "kernel"

        try:
            # Send initialize message
            init_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "rootUri": f"file://{kernel_dir}",
                    "capabilities": {
                        "window": {
                            "workDoneProgress": True,
                        }
                    },
                },
            }

            self.logger.info("Sending LSP initialize message...")
            self._send_lsp_message(proc, init_msg)

            # Read response
            self.logger.info("Waiting for initialize response...")
            response = self._read_lsp_response(proc, expected_id=1, timeout=10)
            
            if response.get("result"):
                self.logger.info("✓ LSP initialize successful")
                self.logger.info(f"Server capabilities: {json.dumps(response.get('result', {}).get('capabilities', {}), indent=2)}")
                
                # Send initialized notification
                initialized_msg = {
                    "jsonrpc": "2.0",
                    "method": "initialized",
                    "params": {}
                }
                self._send_lsp_message(proc, initialized_msg)
                self.logger.info("✓ Sent initialized notification")
                return True
            else:
                self.logger.error(f"❌ LSP initialize failed: {response}")
                return False

        except Exception as e:
            self.logger.error(f"❌ LSP initialization failed: {e}")
            return False

    def test_symbol_lookup(self, proc: subprocess.Popen[Any]) -> bool:
        """Step 7: Test looking up a known symbol definition from the patch."""
        self.logger.info("=" * 80)
        self.logger.info("STEP 7: Testing Symbol Definition Lookup")
        self.logger.info("=" * 80)
        
        kernel_dir = self.docker_manager.sandbox_path / "kernel"

        try:
            # Use the actual file and symbol from the patch
            test_file = "drivers/remoteproc/qcom_q6v5.c"
            test_symbol = "qcom_smem_state_update_bits"
            test_line = 265  # Line 266 in 1-indexed, 265 in 0-indexed
            
            test_file_path = kernel_dir / test_file
            
            # Check if test file exists
            self.logger.info(f"Checking if {test_file} exists...")
            check_proc = self.docker_manager.run_command(
                ["test", "-f", str(test_file_path)],
                cwd=str(kernel_dir),
            )
            check_proc.wait()
            
            if check_proc.returncode != 0:
                self.logger.error(f"❌ Test file {test_file} not found")
                return False
            
            self.logger.info(f"✓ Test file {test_file} exists")
            self.logger.info(f"Testing symbol lookup for '{test_symbol}' at line {test_line + 1}")
            
            # Read the file
            read_proc = self.docker_manager.run_command(
                ["cat", str(test_file_path)],
                cwd=str(kernel_dir),
            )
            read_proc.wait()
            
            file_content = ""
            if read_proc.stdout:
                file_content = read_proc.stdout.read()
                lines = file_content.splitlines()
                
                # Verify the line contains our symbol
                if test_line < len(lines):
                    line_content = lines[test_line]
                    self.logger.info(f"Line {test_line + 1} content: {line_content.strip()}")
                    
                    # Find the character position of the symbol
                    char_pos = line_content.find(test_symbol)
                    if char_pos == -1:
                        self.logger.error(f"❌ Symbol '{test_symbol}' not found on line {test_line + 1}")
                        self.logger.info(f"Line content: {line_content}")
                        return False
                    
                    self.logger.info(f"✓ Found '{test_symbol}' at character position {char_pos}")
                else:
                    self.logger.error(f"❌ Line {test_line + 1} is beyond file length ({len(lines)} lines)")
                    return False
            else:
                self.logger.error("❌ Failed to read file content")
                return False
            
            # Open file in LSP
            uri = f"file://{test_file_path}"
            self.logger.info(f"Opening file in LSP: {uri}")
            
            didopen_msg = {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "c",
                        "version": 1,
                        "text": file_content
                    }
                }
            }
            self._send_lsp_message(proc, didopen_msg)
            time.sleep(0.5)
            
            # Request definition
            def_msg = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/definition",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": test_line, "character": char_pos}
                }
            }
            
            self.logger.info(f"Requesting definition for '{test_symbol}' at line {test_line + 1}, character {char_pos}")
            self._send_lsp_message(proc, def_msg)
            
            # Read response
            self.logger.info("Waiting for definition response from clangd...")
            response = self._read_lsp_response(proc, expected_id=2, timeout=15)
            
            if response.get("result"):
                result = response["result"]
                self.logger.info("=" * 80)
                self.logger.info("✓ SYMBOL LOOKUP SUCCESSFUL!")
                self.logger.info("=" * 80)
                
                if isinstance(result, list) and len(result) > 0:
                    for i, location in enumerate(result):
                        self.logger.info(f"\nDefinition location {i + 1}:")
                        self.logger.info(f"  URI: {location.get('uri', 'N/A')}")
                        
                        if 'range' in location:
                            range_info = location['range']
                            start = range_info.get('start', {})
                            end = range_info.get('end', {})
                            self.logger.info(f"  Start: Line {start.get('line', 'N/A') + 1}, Character {start.get('character', 'N/A')}")
                            self.logger.info(f"  End: Line {end.get('line', 'N/A') + 1}, Character {end.get('character', 'N/A')}")
                        
                        # Extract and show the file path
                        uri_str = location.get('uri', '')
                        if uri_str.startswith('file://'):
                            file_path = uri_str[7:]  # Remove 'file://' prefix
                            self.logger.info(f"  File: {file_path}")
                else:
                    self.logger.info(f"Definition result: {json.dumps(result, indent=2)}")
                
                self.logger.info("=" * 80)
                return True
            else:
                self.logger.warning("=" * 80)
                self.logger.warning("⚠ SYMBOL LOOKUP RETURNED NO RESULTS")
                self.logger.warning("=" * 80)
                self.logger.warning(f"Full response: {json.dumps(response, indent=2)}")
                self.logger.warning("\nPossible reasons:")
                self.logger.warning("  1. clangd hasn't finished indexing yet")
                self.logger.warning("  2. The file is not in compile_commands.json")
                self.logger.warning("  3. There's a compilation error preventing indexing")
                self.logger.warning("=" * 80)
                return False

        except Exception as e:
            self.logger.error(f"❌ Symbol lookup test failed: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _make_message_string(self, msg: Dict[str, Any]) -> str:
        """Convert LSP message to string with proper headers."""
        msg_json = json.dumps(msg)
        return f"Content-Length: {len(msg_json.encode('utf-8'))}\r\n\r\n{msg_json}"

    def _send_lsp_message(self, proc: subprocess.Popen[Any], message: Dict[str, Any]) -> None:
        """Send an LSP message to the process."""
        if proc.stdin is None:
            raise RuntimeError("Process stdin is None")
        proc.stdin.write(self._make_message_string(message))
        proc.stdin.flush()

    def _read_lsp_response(
        self,
        proc: subprocess.Popen[Any],
        expected_id: Optional[int] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Read and parse LSP response from process with timeout."""
        import select

        if proc.stdout is None:
            raise RuntimeError("Process stdout is None")

        start_time = time.time()

        while True:
            # Check if process is still alive
            if proc.poll() is not None:
                raise RuntimeError(
                    f"clangd process died with return code {proc.returncode}"
                )

            # Check timeout
            if time.time() - start_time > timeout:
                raise RuntimeError(
                    f"Timeout waiting for LSP response after {timeout} seconds"
                )

            # Use select to check if data is available
            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if not ready:
                continue

            # Read headers
            headers = ""
            while True:
                char = proc.stdout.read(1)
                if not char:
                    if proc.poll() is not None:
                        raise RuntimeError(
                            f"clangd process died with return code {proc.returncode}"
                        )
                    if time.time() - start_time > timeout:
                        raise RuntimeError(
                            f"Timeout reading LSP headers after {timeout} seconds"
                        )
                    time.sleep(0.01)
                    continue
                headers += char

                if "\r\n\r\n" in headers:
                    break
                elif "\n\n" in headers:
                    break

            # Parse content length
            content_length = 0
            for line in headers.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    content_length = int(line.split(":")[1].strip())

            if content_length == 0:
                continue

            # Read content
            content = proc.stdout.read(content_length)
            if content is None or len(content) != content_length:
                raise RuntimeError(
                    f"Failed to read complete content. Expected {content_length}, got {len(content) if content else 0}"
                )

            try:
                msg = json.loads(content)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON in LSP response: {e}")

            # Handle notifications
            if msg.get("method") == "window/workDoneProgress/create":
                # Respond to workDoneProgress request
                response = {"id": msg.get("id"), "jsonrpc": "2.0", "result": None}
                self._send_lsp_message(proc, response)
                continue

            if msg.get("method") in ["textDocument/publishDiagnostics", "$/progress", "textDocument/clangd.fileStatus"]:
                continue

            if expected_id is None or msg.get("id") == expected_id:
                return msg

    def get_context(self) -> None:
        """Generate context for the AI review with step-by-step validation."""
        self.logger.info("\n" + "=" * 80)
        self.logger.info("STARTING CLANGD INTEGRATION DEBUG WORKFLOW")
        self.logger.info("=" * 80 + "\n")

        # Step 1: Validate Docker environment
        if not self.validate_docker_environment():
            self.logger.error("Docker environment validation failed. Aborting.")
            self.context = ""
            return

        # Steps 2 & 3: Build kernel
        if not self.build_kernel():
            self.logger.error("Kernel build failed. Aborting.")
            self.context = ""
            return

        # Step 4: Generate and validate compile_commands.json
        if not self.generate_and_validate_compile_commands():
            self.logger.error("compile_commands.json generation/validation failed. Aborting.")
            self.context = ""
            return

        # Step 5: Start clangd
        proc = self.test_clangd_startup()
        if proc is None:
            self.logger.error("clangd startup failed. Aborting.")
            self.context = ""
            return

        try:
            # Step 6: Test LSP initialization
            if not self.test_lsp_initialization(proc):
                self.logger.error("LSP initialization failed. Aborting.")
                self.context = ""
                return

            # Step 7: Test symbol lookup
            if not self.test_symbol_lookup(proc):
                self.logger.error("Symbol lookup test failed. Aborting.")
                self.context = ""
                return

            self.logger.info("\n" + "=" * 80)
            self.logger.info("✓ ALL VALIDATION STEPS PASSED!")
            self.logger.info("=" * 80 + "\n")

        finally:
            # Clean up clangd process
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)
            except Exception as e:
                self.logger.debug(f"Error terminating clangd: {e}")
                try:
                    proc.kill()
                except Exception:
                    pass

            self.docker_manager.cleanup_clangd()

        # For now, set empty context since we're just testing the pipeline
        self.context = ""

    def setup(self) -> None:
        super().setup()

    def run(self) -> str:
        """Execute the AI code review."""
        self.get_context()

        formatted_prompt = self.PROMPT_TEMPLATE.format(
            diff=self.diff,
            commit_text=self.commit_message,
        )

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
