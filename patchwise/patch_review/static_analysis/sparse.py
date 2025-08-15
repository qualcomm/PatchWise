# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import os
import re

from patchwise.patch_review.decorators import (
    register_long_review,
    register_static_analysis_review,
)
from .static_analysis import StaticAnalysis


@register_static_analysis_review
@register_long_review
class Sparse(StaticAnalysis):
    """
    Performs static analysis on kernel commits using the sparse tool.

    Methods:
        run():
            Runs sparse and returns the results corresponding to the patch sha.
    """

    def setup(self) -> None:
        pass

    def run(self) -> str:
        logger = self.logger
        kernel_dir = self.docker_manager.sandbox_path / "kernel"
        build_dir = self.docker_manager.build_dir

        logger.info("=== SPARSE DEBUG: Starting sparse analysis ===")
        logger.info(f"Docker kernel dir: {kernel_dir}")
        logger.info(f"Docker build dir: {build_dir}")
        logger.info(f"Commit: {self.commit.hexsha}")

        logger.info("Running defconfig")
        super().make_config(arch="arm64")  # TODO change back to _make_allmodconfig

        sparse_log_pattern = re.compile(
            r"(?P<filepath>.+):(?P<linenum>\d+):(?P<column>\d+): (?P<message>.+)"
        )

        # Get list of changed files (relative paths)
        diff = self.repo.git.diff(
            "--name-only", f"{self.commit.parents[0]}..{self.commit}"
        ).splitlines()
        files_changed = [f.strip() for f in diff]

        logger.info(f"Files changed in commit: {len(files_changed)}")
        for f in files_changed:
            logger.info(f"  Changed file: {f}")

        # Touch changed files inside the Docker container
        if files_changed:
            logger.info("Touching changed files in Docker container...")
            for f in files_changed:
                touch_cmd = ["touch", str(kernel_dir / f)]
                try:
                    super().run_cmd_with_timer(
                        touch_cmd,
                        desc=f"touch {f}",
                    )
                    logger.debug(f"Touched {f} in container")
                except Exception as e:
                    logger.warning(f"Failed to touch {f}: {e}")

        # Build the sparse command (following dt_check.py pattern)
        sparse_cmd = [
            "make",
            "-C",
            str(kernel_dir),
            f"O={build_dir}",
            f"-j{os.cpu_count()}",
            "ARCH=arm64",
            "LLVM=1",
            "C=1",
            "-s",
            "CHECK=sparse",
        ]

        logger.info(f"Running sparse command: {' '.join(sparse_cmd)}")
        logger.info("This may take a while...")

        try:
            sparse_warnings = super().run_cmd_with_timer(
                sparse_cmd,
                cwd=str(build_dir),
                desc="sparse check",
            )

            logger.debug(
                f"Sparse command completed. Output length: {len(sparse_warnings)} characters"
            )
            # logger.debug("=== RAW SPARSE OUTPUT START ===")
            # logger.debug(sparse_warnings)
            # logger.debug("=== RAW SPARSE OUTPUT END ===")

        except Exception as e:
            logger.error(f"Sparse command failed: {e}")
            return f"ERROR: Sparse execution failed: {e}"

        # Process the output
        output = ""
        total_lines = len(sparse_warnings.splitlines())
        matched_lines = 0
        filtered_lines = 0

        logger.info(f"Processing {total_lines} lines of sparse output...")

        for line_num, line in enumerate(sparse_warnings.splitlines(), 1):
            logger.debug(f"Line {line_num}: {line}")

            match = re.match(sparse_log_pattern, line)
            if match:
                matched_lines += 1
                filepath = match.group("filepath")
                logger.debug(f"Matched sparse warning: {filepath}")

                # Check if this file was changed in the commit (use relative paths)
                # Remove any leading path components to get relative path
                relative_filepath = filepath
                if filepath.startswith("/"):
                    # If it's an absolute path, try to make it relative
                    if str(kernel_dir) in filepath:
                        relative_filepath = filepath.replace(str(kernel_dir) + "/", "")
                    else:
                        # Try to find the relative part
                        path_parts = filepath.split("/")
                        for i, part in enumerate(path_parts):
                            if (
                                part in files_changed[0].split("/")
                                if files_changed
                                else []
                            ):
                                relative_filepath = "/".join(path_parts[i:])
                                break

                if relative_filepath not in files_changed:
                    logger.debug(
                        f"Filtering out warning for unchanged file: {relative_filepath}"
                    )
                    filtered_lines += 1
                    continue

                # Clean up the line for output (remove container paths)
                cleaned_line = line
                if str(kernel_dir) in line:
                    cleaned_line = line.replace(str(kernel_dir) + "/", "")

                logger.info(f"Including sparse warning: {cleaned_line}")
                output += cleaned_line + "\n"
            else:
                logger.debug(f"Line didn't match sparse pattern: {line}")

        logger.info(f"=== SPARSE PROCESSING SUMMARY ===")
        logger.info(f"Total output lines: {total_lines}")
        logger.info(f"Lines matching sparse pattern: {matched_lines}")
        logger.info(f"Lines filtered (unchanged files): {filtered_lines}")
        logger.info(f"Final warnings included: {len(output.splitlines())}")
        logger.info(f"=== FINAL SPARSE OUTPUT ===")
        logger.info(output if output else "(no warnings)")
        logger.info("=== SPARSE DEBUG: Complete ===")

        return output
