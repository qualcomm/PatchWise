# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import datetime
import json
import logging
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple, Set
from urllib.parse import unquote, urlparse
import httpx
import litellm
import urllib3

from pathlib import Path

from patchwise import PACKAGE_NAME, SANDBOX_PATH
from patchwise.docker import DockerManager
from patchwise.patch_review.ai_agent.tool_definitions import TOOLS
from patchwise.ui import events
from patchwise.utils.decorators import retry

urllib3.disable_warnings()

# Silence litellm's "Provider List: https://docs.litellm.ai/docs/providers"
# banner (and the rest of its on-exception debug info) — it prints directly to
# the console, repeatedly, and corrupts the live dashboard.
litellm.suppress_debug_info = True

DEFAULT_MODEL = "openai/Pro"
DEFAULT_API_BASE = "https://api.openai.com/v1"
AGENT_MAX_ITERATIONS = 50

# Container-side tree-sitter indexer path
TS_INDEXER_PATH = "/home/patchwise/bin/ts_indexer.py"

REVIEW_PROMPTS_PATH = (
    Path(__file__).resolve().parents[3] / "thirdparty" / "review-prompts"
)
KERNEL_REVIEW_PROMPTS_PATH = REVIEW_PROMPTS_PATH / "kernel"
SUBSYSTEM_REVIEW_PROMPTS_PATH = KERNEL_REVIEW_PROMPTS_PATH / "subsystem"


def uri_to_path(uri: str) -> str:
    """Convert a file:// URI to file path."""
    return unquote(urlparse(uri).path)


class Agent:
    model: str = DEFAULT_MODEL
    api_base: str = DEFAULT_API_BASE

    @classmethod
    def get_logger(cls) -> logging.Logger:
        return logging.getLogger(f"{PACKAGE_NAME}.{cls.__name__.lower()}")

    # TODO: remove kernel_path and use docker instead
    def __init__(
        self,
        kernel_path: str,
        docker_manager: DockerManager,
        enable_edit_tools: bool = False,
    ):
        self.model = Agent.model
        os.environ["OTEL_SDK_DISABLED"] = "true"
        litellm.client_session = httpx.Client(verify=False)
        self.logger = self.get_logger()
        self.docker_manager = docker_manager
        self.enable_edit_tools = enable_edit_tools
        self.ts_daemon: Optional[subprocess.Popen[Any]] = None
        self.seen_files: Set[str] = set()

        # Per-review token ceiling shared across every run_agent_loop call on this
        # Agent (the multi-phase review fans out many loops). None means unbounded;
        # iteration caps still bound each loop. Aborts gracefully when exhausted.
        self.token_budget: Optional[int] = None
        self.tokens_used: int = 0

        # Context-window guard (distinct from token_budget, which is cumulative
        # cost). context_token_limit caps the *per-request input size* — the
        # prompt tokens of a single completion, which is what the model's context
        # window (e.g. 1M for gpt-5) actually bounds. last_prompt_tokens /
        # peak_prompt_tokens track the input size the provider reported.
        self.context_token_limit: Optional[int] = None
        self.last_prompt_tokens: int = 0
        self.peak_prompt_tokens: int = 0

        # Label and iteration of the current phase/subtask (e.g. "planner",
        # "exec:t2"), tagged onto every tool-call log line so per-subtask tool
        # usage is traceable. Set per-loop by run_agent_loop. The review runs the
        # phases sequentially on this one Agent, so plain instance attributes
        # suffice.
        self.current_label: str = ""
        self.current_iteration: int = 0

        self.seen_files |= self._files_in_diff()

        self.kernel_path = kernel_path

    @retry(
        max_retries=10,
        exceptions=(
            litellm.Timeout,
            litellm.RateLimitError,
            litellm.InternalServerError,
            litellm.OpenAIError,
        ),
    )
    def completion_with_retry(self, **kwargs) -> Any:
        kwargs.setdefault("model", Agent.model)
        kwargs.setdefault("api_base", Agent.api_base)
        self.logger.debug(
            f"Making API call with model: {self.model}, api_base: {Agent.api_base}"
        )
        response = litellm.completion(**kwargs)
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.tokens_used += getattr(usage, "total_tokens", 0) or 0
            pt = getattr(usage, "prompt_tokens", 0) or 0
            self.last_prompt_tokens = pt
            self.peak_prompt_tokens = max(self.peak_prompt_tokens, pt)
        return response

    def budget_remaining(self) -> bool:
        """True while the per-review token budget is unset or not yet exhausted."""
        return self.token_budget is None or self.tokens_used < self.token_budget

    # TODO: rename to loop()
    def run_agent_loop(
        self,
        messages: list[dict],
        force_tool_usage=False,
        max_iterations: Optional[int] = None,
        use_tools: bool = True,
        allowed_tools: Optional[List[str]] = None,
        label: Optional[str] = None,
    ) -> str:
        """Run the agent loop, calling the LLM iteratively until it stops requesting tools.

        Args:
            messages: Initial message list (system + user turns).
            force_tool_usage: Require a tool call on the first iteration.
            max_iterations: Per-call iteration cap (defaults to AGENT_MAX_ITERATIONS).
                The multi-phase review uses smaller caps for plan/critic/filter
                loops than for execution subagents.
            use_tools: When False, run without any tools (a single completion
                from the prompt). The planner uses this so it divides the work
                from the diff alone rather than investigating.
            allowed_tools: When set (and use_tools is True), restrict the loop to
                only these tool names; an empty list means no tools. E.g. the
                plan critic is given only `get_subsystem_review_guide` (to load
                guides for coverage) while the code-navigation tools are withheld
                so it can't go hunting specific bugs.
            label: Phase/subtask label for tool-call logging. Defaults to the
                current instance `current_label` if not given.

        Returns:
            The final assistant text response.
        """
        # Logging context for this loop (phases run sequentially on one Agent).
        if label is not None:
            self.current_label = label
        self.current_iteration = 0

        max_iters = max_iterations or AGENT_MAX_ITERATIONS
        tools = self.get_tools(allowed_tools) if use_tools else None

        completion_kwargs: dict = {
            "messages": messages,
            "stream": False,
        }

        if tools:
            completion_kwargs["tools"] = tools
            # Force tool usage to get additional context on the first iteration
            completion_kwargs["tool_choice"] = (
                "required" if force_tool_usage else "auto"
            )
            completion_kwargs["allowed_openai_params"] = ["tools", "tool_choice"]

        for iteration in range(1, max_iters + 1):
            self.current_iteration = iteration
            self.logger.debug(f"Agent iteration {iteration}/{max_iters}")
            events.emit(
                events.ITERATION, label=self.current_label, n=iteration,
                cap=max_iters, tokens=self.tokens_used,
                budget=self.token_budget, peak=self.peak_prompt_tokens,
            )

            if not self.budget_remaining():
                self.logger.warning(
                    f"Token budget exhausted ({self.tokens_used}/{self.token_budget}). "
                    "Forcing final response without tools."
                )
                break

            # Context-window guard: stop before the next request's input would
            # approach the model's context limit. last_prompt_tokens is the input
            # size the provider reported for the previous call; the next call is
            # strictly larger (it appends the new tool calls + results), so this
            # is a conservative pre-check.
            if (
                self.context_token_limit is not None
                and self.last_prompt_tokens >= self.context_token_limit
            ):
                self.logger.warning(
                    f"Context window near limit (prompt={self.last_prompt_tokens} "
                    f">= {self.context_token_limit}). Forcing final response without tools."
                )
                break

            response = self.completion_with_retry(**completion_kwargs)
            msg = response.choices[0].message
            # Bedrock rejects toolUse.name outside [a-zA-Z0-9_-]; scrub here so a
            # hallucinated name with invalid chars cannot poison replayed history.
            for tool_call in msg.tool_calls or []:
                tool_call.function.name = re.sub(
                    r"[^a-zA-Z0-9_-]", "_", tool_call.function.name
                )
            messages.append(msg.model_dump())

            if not msg.tool_calls:
                return msg.content or ""

            if force_tool_usage and iteration == 1:
                completion_kwargs["tool_choice"] = "auto"

            # Dispatch each tool call and append results
            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                    self.logger.debug(f"Tool call: {name}({args})")
                    result = self.dispatch_tool(name, args)
                    self.logger.debug(f"Tool result: {name} -> {result}")
                except json.JSONDecodeError as e:
                    self.logger.error(f"Error parsing tool args for '{name}': {e}")
                    result = {
                        "ok": False,
                        "error": f"Invalid JSON arguments `{args}` for tool '{name}'",
                    }
                except Exception as e:
                    self.logger.error(f"Error executing tool '{name}': {e}")
                    result = {
                        "ok": False,
                        "error": f"Internal error executing tool '{name}({args})'",
                    }

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": name,
                        "content": json.dumps(result),
                    }
                )

        # Max iterations (or budget) reached: force a final response by disallowing tool calls
        self.logger.warning(
            f"Agent reached max iterations ({max_iters}) or budget. Forcing final response without tools."
        )

        completion_kwargs["tool_choice"] = "none"

        messages.append(
            {
                "role": "user",
                "content": "Maximum tool iterations reached. Please provide your final response based on the available information.",
            }
        )

        response = self.completion_with_retry(**completion_kwargs)
        return response.choices[0].message.content or ""

    # TODO: read from docker container / use docker_manager.read_file()
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

    def _kernel_rel(self, path_or_uri: str) -> str:
        """Normalize any path/URI to a kernel-relative POSIX string."""
        s = path_or_uri
        if s.startswith("file://"):
            s = uri_to_path(s)
        kernel_dir = str(self.docker_manager.kernel_dir)
        if s.startswith(kernel_dir + "/"):
            s = s[len(kernel_dir) + 1 :]
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

    def _container_kernel_path(self, rel: str) -> str:
        """Return a kernel-relative path anchored at the container kernel root."""
        return str(self.docker_manager.kernel_dir / rel)

    def _validate_existing_kernel_path(self, path: str) -> str:
        """Validate and normalize a kernel-relative path that must exist."""
        self._abs_in_kernel(path)

        rel = self._kernel_rel(path)
        container_path = self._container_kernel_path(rel)
        check = self.docker_manager.run_command(
            ["test", "-e", container_path], cwd=None
        )
        check.communicate()
        if check.returncode != 0:
            raise ValueError(f"path not found: {rel}")
        return rel

    def _resolve_git_commit(self, rev: str) -> str:
        """Resolve a revision to a commit SHA, rejecting invalid or option-like refs."""
        if not isinstance(rev, str) or not rev.strip():
            raise ValueError("rev must be a non-empty string")
        if rev.startswith("-"):
            raise ValueError(f"invalid rev: {rev}")
        if any(c in rev for c in ("\x00", "\n", "\r")):
            raise ValueError(f"invalid rev: {rev}")

        proc = self.docker_manager.run_command(
            [
                "git",
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{rev}^{{commit}}",
            ],
            cwd=self.docker_manager._git_workdir,
        )
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            detail = stderr.strip() or stdout.strip() or rev
            raise ValueError(f"invalid rev: {detail}")
        return stdout.strip()

    def _validate_git_path(self, path: str) -> str:
        """Validate a kernel-relative path for git object access."""
        self._abs_in_kernel(path)
        return self._kernel_rel(path)

    def _git_tree_rel(self, rel: str) -> str:
        """Strip the kernel git subtree prefix from a mount-relative path so git
        (which runs inside that subtree, `_git_workdir`) sees a tree-relative
        path. The agent refers to files relative to the mounted root (matching
        read/grep and the prefixed diff from `_files_in_diff`), e.g.
        `msm-kernel/foo.c` when `--kernel-tree msm-kernel`; this is the inverse of
        that prefixing. A no-op when the mount root is the git tree."""
        subdir = self.docker_manager.git_subdir
        if subdir and (rel == subdir or rel.startswith(subdir + "/")):
            return rel[len(subdir):].lstrip("/")
        return rel

    def _split_git_object_spec(self, rev: str) -> Tuple[str, Optional[str]]:
        """Split `rev[:path]` syntax into commit rev and optional kernel-relative path."""
        if not isinstance(rev, str) or not rev.strip():
            raise ValueError("rev must be a non-empty string")
        if rev.startswith("-"):
            raise ValueError(f"invalid rev: {rev}")
        if any(c in rev for c in ("\x00", "\n", "\r")):
            raise ValueError(f"invalid rev: {rev}")

        if ":" not in rev:
            return rev, None

        commit_rev, rel_path = rev.split(":", 1)
        if not commit_rev or not rel_path:
            raise ValueError(f"invalid rev: {rev}")
        return commit_rev, self._validate_git_path(rel_path)

    def _resolve_git_object_spec(self, rev: str) -> Tuple[str, Optional[str], str]:
        """Resolve a git commit or commit:path object spec."""
        commit_rev, rel_path = self._split_git_object_spec(rev)
        resolved_rev = self._resolve_git_commit(commit_rev)
        if rel_path is None:
            return resolved_rev, None, resolved_rev
        git_rel = self._git_tree_rel(rel_path)
        return resolved_rev, git_rel, f"{resolved_rev}:{git_rel}"

    def _git_command(self, *args: str) -> List[str]:
        """Run git with paging disabled so tool output is deterministic."""
        return ["git", "--no-pager", *args]

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
            # The daemon has exited, so its stderr is drained to EOF without
            # blocking; surface it so the real cause (missing file, ImportError,
            # …) is visible instead of an opaque generic failure.
            stderr = self.ts_daemon.stderr.read() if self.ts_daemon.stderr else ""
            raise RuntimeError(
                "ts_indexer daemon exited before ready signal"
                + (f":\n{stderr.strip()}" if stderr.strip() else "")
            )
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

    # TODO: Do we need this now that LSP/clangd is removed?
    def _ensure_navigation_stack(self, need_ts: bool = True) -> None:
        """Lazily start the tree-sitter index daemon on first use."""
        if need_ts and getattr(self, "ts_daemon", None) is None:
            self._start_ts_daemon()

    def _ts_lookup(self, name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Return up to `limit` index entries matching `name`."""
        resp = self._ts_query(op="lookup", name=name, limit=limit)
        if "error" in resp:
            raise RuntimeError(f"ts_indexer error: {resp['error']}")
        return resp.get("candidates", [])

    @staticmethod
    def _strip_type_keyword(name: str) -> str:
        """Drop a leading C tag keyword the model often includes.

        Models routinely pass a type as `struct foo`/`union foo`/`enum foo`, but
        the tree-sitter index keys it under the bare tag `foo`. Strip the keyword
        so the lookup matches; a bare name is returned unchanged.
        """
        return re.sub(r"^\s*(?:struct|union|enum)\s+", "", name.strip())

    def _ts_funcs_in_file(self, rel_path: str) -> List[Dict[str, Any]]:
        """Return function ranges for a single kernel-relative file."""
        resp = self._ts_query(op="funcs_in_file", path=rel_path)
        if "error" in resp:
            raise RuntimeError(f"ts_indexer error: {resp['error']}")
        return resp.get("funcs", [])

    def _ts_callees(
        self, rel_path: str, start_line: int, end_line: int
    ) -> List[Dict[str, Any]]:
        """Return the calls made within [start_line, end_line] of a file."""
        resp = self._ts_query(
            op="callees", path=rel_path, start_line=start_line, end_line=end_line
        )
        if "error" in resp:
            raise RuntimeError(f"ts_indexer error: {resp['error']}")
        return resp.get("callees", [])

    def _split_file_arg(self, file: Optional[str]) -> List[str]:
        """Parse a `file` argument into normalized kernel-relative paths.

        Like grep, the name-taking tools accept one OR several whitespace/comma-
        separated paths in `file` (kernel paths never contain spaces). Used as a
        ranking/disambiguation hint, so no existence check here.
        """
        if not file:
            return []
        return [self._kernel_rel(t) for t in re.split(r"[,\s]+", file.strip()) if t]

    def _rank_candidates(
        self, candidates: List[Dict[str, Any]], file_hints: List[str]
    ) -> List[Dict[str, Any]]:
        """Sort candidates by disambiguation tier (1 = best).

        file_hints are kernel-relative paths the caller passed (where the symbol
        was seen); an exact hit on any of them is the strongest signal, and the
        hints also feed the directory/subsystem proximity tiers.
        """
        hints = set(file_hints)
        seen = self.seen_files | hints

        # TO-DO: add a tier for "#include files of a seen file

        def _prefixes(p: str) -> Set[str]:
            """Same subsystem (drivers/mtd, net/ipv4, drivers/gpio)"""
            parts = p.split("/")
            return {"/".join(parts[:k]) for k in range(2, len(parts) + 1)}

        same_dirs: Set[str] = set()
        seen_prefixes: Set[str] = set()
        for f in seen:
            same_dirs.add(os.path.dirname(f))
            seen_prefixes |= _prefixes(f)

        def tier(cand: Dict[str, Any]) -> int:
            cf = cand["file"]
            if cf in hints:
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
            key=lambda c: (tier(c), c["file"], c["start_line"]),
        )

    _TS_LOOKUP_LIMIT = 100

    def get_tools(
        self, allowed: Optional[List[str]] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Return tool schemas."""
        if allowed is None:
            return TOOLS
        allowed_set = set(allowed)
        filtered = [t for t in TOOLS if t.get("function", {}).get("name") in allowed_set]
        return filtered or None

    _DEFINITION_LIMIT = 50
    _CALLEES_LIMIT = 200
    _CALLERS_LIMIT = 100  # max caller entries and max file-scope references each
    _GREP_LIMIT = 100  # max grep hits returned
    _READ_MAX_LINES = 256  # max lines returned per read_file / git_cat_file call

    def _tool_find_definition(
        self, name: str, file: Optional[str] = None
    ) -> Dict[str, Any]:
        # Pure tree-sitter: return EVERY definition of `name` across the tree —
        # all arch/#ifdef variants — ranked by proximity to files already seen.
        # We deliberately do not collapse to the config-active variant: a kernel
        # review must weigh all of them, not just what one defconfig compiles.
        self._ensure_navigation_stack(need_ts=True)
        name = self._strip_type_keyword(name)
        candidates = self._ts_lookup(name, limit=self._TS_LOOKUP_LIMIT)
        if not candidates:
            return {"ok": False, "error": f"symbol '{name}' not found in index"}
        ranked = self._rank_candidates(candidates, self._split_file_arg(file))
        total = len(ranked)
        definitions: List[Dict[str, Any]] = []
        for c in ranked[: self._DEFINITION_LIMIT]:
            self.seen_files.add(c["file"])
            definitions.append(
                {
                    "name": c["name"],
                    "kind": c["kind"],
                    "path": c["file"],
                    # The definition spans [line, end]; read_file(path, line,
                    # end) returns it whole instead of guessing a window.
                    "line": c["start_line"],
                    "end": c["end_line"],
                    "snippet": self._snippet_for_range(
                        c["file"], c["start_line"], c["end_line"], ctx=0
                    ),
                }
            )
        return {
            "ok": True,
            "result": definitions,
            "total": total,
            "truncated": total > self._DEFINITION_LIMIT,
        }

    # TODO: This is almost the same as grep(), remove if models don't call this often
    def _tool_find_callers(
        self, name: str, file: Optional[str] = None
    ) -> Dict[str, Any]:
        # Callers = every function whose body references `name`. ripgrep the bare
        # identifier tree-wide (or within `file`) and attribute each hit to its
        # enclosing function via the tree-sitter index, grouping multiple call
        # sites in the same function. Hits at file scope (function-pointer wiring
        # like `.release = name`, macro bodies, ops tables) have no enclosing
        # function — kept as `references`, since that wiring is often how `name`
        # actually gets invoked.
        self._ensure_navigation_stack(need_ts=True)
        name = self._strip_type_keyword(name)
        pattern = rf"\b{re.escape(name)}\b"
        hits, error = self._rg_search(pattern, file, glob=None)
        if error is not None:
            return {"ok": False, "error": error}
        callers: Dict[Tuple[str, str], Dict[str, Any]] = {}
        references: List[Dict[str, Any]] = []
        for h in hits:
            fn = h["enclosing_function"]
            if fn is None:
                references.append(
                    {"path": h["path"], "line": h["line"], "snippet": h["snippet"]}
                )
                continue
            # Key on the definition line too: #ifdef/#else variants share a name
            # in one file but are distinct functions — keep them as separate
            # callers rather than merging their call sites.
            key = (h["path"], fn, h["enclosing_function_line"])
            entry = callers.get(key)
            if entry is None:
                entry = {
                    "function": fn,
                    "path": h["path"],
                    "function_line": h["enclosing_function_line"],
                    "lines": [],
                    "snippet": h["snippet"],
                }
                callers[key] = entry
            entry["lines"].append(h["line"])
        caller_list = list(callers.values())
        limit = self._CALLERS_LIMIT
        for c in caller_list[:limit]:
            self.seen_files.add(c["path"])
        return {
            "ok": True,
            "result": {
                "callers": caller_list[:limit],
                "references": references[:limit],
            },
            "total_callers": len(caller_list),
            "total_references": len(references),
            "truncated": len(caller_list) > limit or len(references) > limit,
        }

    # TODO: Do models prefer reading the whole function with read_file()?
    def _tool_find_callees(
        self, name: str, file: Optional[str] = None
    ) -> Dict[str, Any]:
        # Callees = the calls made inside `name`'s own body. Local and purely
        # syntactic: locate the function definition(s) in the tree-sitter index
        # and extract their call expressions — direct `foo()` and indirect
        # `ops->fn()` alike (the latter is the dominant kernel call style, which
        # a semantic call graph would miss).
        self._ensure_navigation_stack(need_ts=True)
        name = self._strip_type_keyword(name)
        candidates = self._ts_lookup(name, limit=self._TS_LOOKUP_LIMIT)
        funcs = [c for c in candidates if c.get("kind") == "function"]
        hints = self._split_file_arg(file)
        if hints:
            scoped = [c for c in funcs if c["file"] in set(hints)]
            funcs = scoped or funcs
        if not funcs:
            return {
                "ok": False,
                "error": f"no function definition named '{name}' in index",
            }
        ranked = self._rank_candidates(funcs, hints)
        definitions: List[Dict[str, Any]] = []
        for c in ranked[:10]:
            callees = self._ts_callees(c["file"], c["start_line"], c["end_line"])
            self.seen_files.add(c["file"])
            definitions.append(
                {
                    "path": c["file"],
                    "line": c["start_line"],
                    "callees": callees[: self._CALLEES_LIMIT],
                    "truncated": len(callees) > self._CALLEES_LIMIT,
                }
            )
        return {
            "ok": True,
            "result": definitions,
            "total_definitions": len(ranked),
        }

    def _rg_search(
        self,
        pattern: str,
        file: Optional[str] = None,
        glob: Optional[str] = None,
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """Run ripgrep and attribute each hit to its enclosing function.

        Returns (hits, None) on success or (None, error_message). Each hit is
        {path, enclosing_function, line, snippet}, deduped by (path, line);
        enclosing_function is None for hits outside any function body. No result
        cap — callers truncate as they see fit.
        """
        # ripgrep validates the pattern itself (Rust regex dialect). We do NOT
        # pre-validate with Python's `re`: its dialect differs (lookaround and
        # backrefs compile in Python but ripgrep rejects them, and vice versa),
        # so a Python precheck both false-rejects rg-valid patterns and lets
        # rg-invalid ones through. Let rg be the authority.

        # `file` may name one OR several whitespace/comma-separated paths — the
        # model routinely scopes a search to several subsystems at once, and rg
        # takes multiple search roots natively. (Kernel paths never contain
        # spaces, so splitting on whitespace is safe.)
        file_paths: List[str] = []  # validated, kernel-relative, existing
        any_dir = False
        if file:
            for tok in (t for t in re.split(r"[,\s]+", file.strip()) if t):
                try:
                    self._abs_in_kernel(tok)
                except ValueError as e:
                    return None, str(e)
                rel = self._kernel_rel(tok)
                container_path = str(self.docker_manager.kernel_dir / rel)
                check = self.docker_manager.run_command(
                    [
                        "sh",
                        "-c",
                        (
                            'if [ -f "$1" ]; then echo file; '
                            'elif [ -d "$1" ]; then echo dir; '
                            "else echo missing; fi"
                        ),
                        "sh",
                        container_path,
                    ],
                    cwd=None,
                )
                stdout, _ = check.communicate()
                kind = stdout.strip()
                if kind == "missing":
                    return None, f"file not found: {rel}"
                if kind == "dir":
                    any_dir = True
                file_paths.append(rel)

        kernel_dir = self.docker_manager.kernel_dir

        rg_cmd: List[str] = [
            "rg",
            "--line-number",
            "--no-heading",
            "--with-filename",
            "--max-count",
            "500",
        ]
        # Apply glob filters when searching a directory (or the whole tree). When
        # every path is a concrete file, search them directly so a glob can't
        # filter an explicitly-named file out.
        if any_dir or not file_paths:
            globs = [g.strip() for g in glob.split(",")] if glob else ["*.c", "*.h"]
            for g in globs:
                rg_cmd += ["--glob", g]
        rg_cmd += ["-e", pattern]
        if file_paths:
            rg_cmd += [str(kernel_dir / p) for p in file_paths]
        else:
            rg_cmd.append(str(kernel_dir))

        proc = self.docker_manager.run_command(rg_cmd, cwd=str(kernel_dir))
        output, err = proc.communicate()
        # rg exit codes: 0 = matches, 1 = no matches, 2 = error (e.g. bad regex).
        # Surface a real error rather than silently returning zero hits — a
        # silent 0 on a malformed pattern reads as "nothing found".
        if proc.returncode == 2:
            detail = (err or "").strip().splitlines()
            return None, f"invalid regex or search error: {detail[0] if detail else ''}"

        file_to_funcs: Dict[str, List[Tuple[int, int, str]]] = {}

        def funcs_for(rel_path: str) -> List[Tuple[int, int, str]]:
            if rel_path not in file_to_funcs:
                funcs = self._ts_funcs_in_file(rel_path)
                file_to_funcs[rel_path] = [
                    (f["start_line"], f["end_line"], f["name"]) for f in funcs
                ]
            return file_to_funcs[rel_path]

        hits: List[Dict[str, Any]] = []
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
            enclosing_start: Optional[int] = None
            enclosing_end: Optional[int] = None
            for s, e, fname in funcs_for(rel):
                if s <= hit_line <= e:
                    enclosing = fname
                    enclosing_start = s
                    enclosing_end = e
                    break

            hits.append(
                {
                    "path": rel,
                    "enclosing_function": enclosing,
                    # Definition line range of the enclosing function. Two
                    # #ifdef/#else variants share a name in one file but have
                    # distinct ranges — the start keeps them apart, and the end
                    # lets a caller read the whole function in one precise read.
                    "enclosing_function_line": enclosing_start,
                    "enclosing_function_end": enclosing_end,
                    "line": hit_line,
                    "snippet": text.strip()[:240],
                }
            )
        return hits, None

    def _tool_grep(
        self,
        pattern: str,
        file: Optional[str] = None,
        glob: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._ensure_navigation_stack(need_ts=True)
        hits, error = self._rg_search(pattern, file, glob)
        if error is not None:
            return {"ok": False, "error": error}
        total = len(hits)
        # Project to grep's documented schema. enclosing_function_start/end are
        # the line range of the function the hit sits in (null at file scope),
        # so the model can read the whole function in one precise read_file
        # instead of guessing a window around the hit.
        results = [
            {
                "path": h["path"],
                "enclosing_function": h["enclosing_function"],
                "enclosing_function_start": h["enclosing_function_line"],
                "enclosing_function_end": h["enclosing_function_end"],
                "line": h["line"],
                "snippet": h["snippet"],
            }
            for h in hits[: self._GREP_LIMIT]
        ]
        for r in results:
            self.seen_files.add(r["path"])
        return {
            "ok": True,
            "result": results,
            "total": total,
            "truncated": total > self._GREP_LIMIT,
        }

    # TODO: mark "truncated" only when we do not give what the AI wants (within bounds)
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
        if content is False:
            return {"ok": False, "error": f"not a file: {path}"}

        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        start_1 = max(1, start)
        cap_end = start_1 + self._READ_MAX_LINES - 1
        request_end = end if end is not None else cap_end
        effective_end = min(request_end, cap_end, total_lines)
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

    def _tool_read_doc(self, path: str) -> Dict[str, Any]:
        """Read a whole kernel `Documentation/` file. Scoped to Documentation/, so
        a caller given only this tool cannot read source. No line cap."""
        try:
            self._abs_in_kernel(path)  # validation only; reject "../" escapes
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        rel = self._kernel_rel(path)
        # Documentation/ lives under the kernel git subtree (e.g.
        # msm-kernel/Documentation/) when --kernel-tree puts the tree below the
        # mounted root, and at the root otherwise. Re-anchor whatever the model
        # passed under <subdir>/Documentation/: strip a leading subdir, then
        # (since the model often drops the Documentation/ prefix, e.g.
        # "filesystems/locking.rst") ensure it, then prepend the subdir back —
        # so both "Documentation/x.rst" and "msm-kernel/Documentation/x.rst"
        # resolve. The escape check above already ran, so re-anchoring can't
        # widen scope.
        subdir = self.docker_manager.git_subdir
        if subdir and (rel == subdir or rel.startswith(subdir + "/")):
            rel = rel[len(subdir):].lstrip("/")
        if not (rel == "Documentation" or rel.startswith("Documentation/")):
            rel = "Documentation/" + rel
        rel = "/".join(filter(None, [subdir, rel]))
        container_path = str(self.docker_manager.kernel_dir / rel)
        content = self.docker_manager.read_file(container_path)
        if content is False:
            return {"ok": False, "error": f"not a file: {path}"}
        self.seen_files.add(rel)
        return {"ok": True, "result": {"path": rel, "content": content}}

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

    def _tool_get_subsystem_review_guide(self, subsystem_file: str) -> Dict[str, Any]:
        """Load a subsystem review guide from thirdparty/review-prompts/kernel/subsystem/."""
        available = sorted(p.name for p in SUBSYSTEM_REVIEW_PROMPTS_PATH.glob("*.md"))
        avail_str = ", ".join(available)
        safe_name = os.path.basename(subsystem_file)
        if safe_name != subsystem_file or not safe_name.endswith(".md"):
            return {
                "ok": False,
                "error": (
                    f"subsystem_file must be a bare .md filename from the "
                    f"Subsystem Review Guide Index (got {subsystem_file!r}); "
                    f"available: {avail_str}"
                ),
            }
        guide_path = SUBSYSTEM_REVIEW_PROMPTS_PATH / safe_name
        try:
            with open(guide_path, "r") as f:
                content = f.read()
        except FileNotFoundError:
            return {
                "ok": False,
                "error": (
                    f"no subsystem guide named {safe_name!r}; "
                    f"available: {avail_str}"
                ),
            }
        return {
            "ok": True,
            "result": {"name": safe_name, "content": content},
        }

    def _log_tool_call(self, name: str, args: dict, result: dict) -> None:
        """Append a tool-call record to SANDBOX_PATH/tool_calls.log.

        Always written (a dedicated file, one line per call) and tagged with the
        active phase/subtask label so per-subtask tool usage is traceable.
        """
        log_path = SANDBOX_PATH / "tool_calls.log"
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        label = self.current_label or "-"
        iteration = self.current_iteration
        try:
            args_json = json.dumps(args, ensure_ascii=False)
        except Exception:
            args_json = str(args)
        ok = bool(result.get("ok"))
        events.emit(events.TOOL_CALL, label=label, iter=iteration, name=name,
                    args=args, ok=ok)
        line = f"{ts} | task={label} | iter={iteration} | call={name}({args_json}) | ok={ok}\n"
        try:
            with open(log_path, "a") as f:
                f.write(line)
        except Exception as e:
            self.logger.debug(f"Failed to write tool_calls.log: {e}")

    def _tool_git_log(self, path: str) -> Dict[str, Any]:
        try:
            rel = self._validate_existing_kernel_path(path)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        log_cmd = [
            *self._git_command("log"),
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "--max-count",
            "101",
            "--format=%H%x1f%an%x1f%ad%x1f%s",
            "--date=short",
            "--",
            self._git_tree_rel(rel),
        ]
        proc = self.docker_manager.run_command(
            log_cmd, cwd=self.docker_manager._git_workdir
        )
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            detail = stderr.strip() or "git log failed"
            return {"ok": False, "error": detail}

        commits: List[Dict[str, str]] = []
        for line in stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) != 4:
                continue
            commits.append(
                {
                    "rev": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "subject": parts[3],
                }
            )

        total = len(commits)
        truncated = total > 100
        return {
            "ok": True,
            "result": commits[:100],
            "total": total,
            "truncated": truncated,
        }

    def _tool_git_show(self, rev: str, name_only: bool = False) -> Dict[str, Any]:
        try:
            resolved_rev, rel_path, object_spec = self._resolve_git_object_spec(rev)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        if name_only and rel_path is not None:
            return {
                "ok": False,
                "error": "name_only is only supported for commit revisions, not rev:path",
            }

        if name_only:
            show_cmd = [
                *self._git_command("show"),
                "--format=",
                "--name-only",
                "--no-ext-diff",
                "--no-textconv",
                "--no-color",
                resolved_rev,
            ]
        else:
            show_cmd = [
                *self._git_command("show"),
                "--no-ext-diff",
                "--no-textconv",
                "--no-color",
                "--stat=80,20",
                "--format=medium",
                "--unified=3",
                object_spec,
            ]
        proc = self.docker_manager.run_command(
            show_cmd, cwd=self.docker_manager._git_workdir
        )
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            detail = stderr.strip() or "git show failed"
            return {"ok": False, "error": detail}

        if name_only:
            prefix = self.docker_manager.git_subdir
            paths = [
                f"{prefix}/{p}" if prefix else p
                for p in (
                    line.strip() for line in stdout.splitlines() if line.strip()
                )
            ]
            total = len(paths)
            return {
                "ok": True,
                "result": {
                    "rev": resolved_rev,
                    "paths": paths[:200],
                    "truncated": total > 200,
                },
            }

        lines = stdout.splitlines(keepends=True)
        total_lines = len(lines)
        end = min(total_lines, 200)
        return {
            "ok": True,
            "result": {
                "rev": object_spec,
                "content": "".join(lines[:end]),
                "truncated": total_lines > 200,
            },
        }

    # TODO: mark "truncated" only when we do not give what the AI wants (withing bounds)
    def _tool_git_cat_file(
        self, rev: str, path: str, start: int = 1, end: Optional[int] = None
    ) -> Dict[str, Any]:
        try:
            resolved_rev = self._resolve_git_commit(rev)
            rel = self._validate_git_path(path)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        object_spec = f"{resolved_rev}:{self._git_tree_rel(rel)}"
        proc = self.docker_manager.run_command(
            self._git_command("cat-file", "-p", object_spec),
            cwd=self.docker_manager._git_workdir,
        )
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            detail = stderr.strip() or "git cat-file failed"
            if not detail.startswith("git cat-file failed"):
                detail = f"git cat-file failed: {detail}"
            return {"ok": False, "error": detail}

        lines = stdout.splitlines(keepends=True)
        total_lines = len(lines)
        start_1 = max(1, start)
        cap_end = start_1 + self._READ_MAX_LINES - 1
        request_end = end if end is not None else cap_end
        effective_end = min(request_end, cap_end, total_lines)
        return {
            "ok": True,
            "result": {
                "rev": resolved_rev,
                "path": rel,
                "start": start_1,
                "end": effective_end,
                "content": "".join(lines[start_1 - 1 : effective_end]),
                "truncated": effective_end < total_lines,
            },
        }

    def _tool_run_checkpatch(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """Run scripts/checkpatch.pl on current changes to verify fixes."""
        # Validate optional kernel-relative path (for future filtering)
        if file_path:
            try:
                self._validate_existing_kernel_path(file_path)
            except ValueError as e:
                return {"ok": False, "error": str(e)}

        kernel_dir = str(self.docker_manager.kernel_dir)

        try:
            # Ensure checkpatch.pl exists in the container kernel tree
            checkpatch_path = os.path.join(kernel_dir, "scripts", "checkpatch.pl")
            check_proc = self.docker_manager.run_command(
                ["test", "-x", checkpatch_path],
                cwd=None,
            )
            check_proc.communicate()
            if check_proc.returncode != 0:
                return {"ok": False, "error": "checkpatch.pl not found in kernel tree"}

            # Pipe current diff directly into checkpatch.pl inside the container
            proc = self.docker_manager.run_command(
                ["sh", "-c", "git diff HEAD | scripts/checkpatch.pl -"],
                cwd=kernel_dir,
            )
            stdout, _ = proc.communicate()

            output = stdout if stdout else b""
            if isinstance(output, bytes):
                output_str = output.decode(errors="ignore")
            else:
                output_str = str(output)

            if not output_str.strip():
                return {
                    "ok": True,
                    "result": "No changes to check. Make some edits first.",
                }

            if "total: 0 errors, 0 warnings" in output_str:
                return {
                    "ok": True,
                    "result": "✓ SUCCESS: All checkpatch issues fixed! No errors or warnings remain.",
                }
            return {
                "ok": True,
                "result": (
                    f"Checkpatch output:\n{output_str}\n\n"
                    "Issues remain. Please fix them and run checkpatch again."
                ),
            }
        except Exception as e:
            self.logger.error(f"Error running checkpatch: {e}")
            return {"ok": False, "error": f"Error running checkpatch: {e}"}

    def _container_path(self, file: str) -> str:
        return f"{self.docker_manager.kernel_dir}/{file}"

    def _read(self, container_path: str) -> str:
        text = self.docker_manager.read_file(container_path)
        if text is False:
            raise RuntimeError(f"Failed to read {container_path} from container")
        return text

    def _write(self, container_path: str, content: str) -> None:
        if not self.docker_manager.write_file(container_path, content):
            raise RuntimeError(f"Failed to write {container_path} in container")

    def _tool_write_file_str(
        self, file: str, old_content: str, new_content: str
    ) -> dict:
        """Replace old_content with new_content in a container file (exact match)."""
        container_path = self._container_path(file)
        existing = self._read(container_path)

        count = existing.count(old_content)
        if count == 0:
            return {"ok": False, "error": "old_content not found in file"}
        if count > 1:
            return {
                "ok": False,
                "error": f"old_content matches {count} times; be more specific",
            }

        self._write(container_path, existing.replace(old_content, new_content, 1))
        return {"ok": True}

    @staticmethod
    def findings_path_for(label: str) -> Path:
        """Sandbox path of the per-phase findings file for `label`, used by both
        the record_finding tool and the review that reads the file back.

        The label may originate from model-generated data (a plan's task id), so
        the name is sanitized AND the resolved path is asserted to stay inside
        SANDBOX_PATH — a defence-in-depth guard against `../`-style escapes."""
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", label or "unit")
        base = Path(SANDBOX_PATH).resolve()
        path = (base / f"findings_{safe}.md").resolve()
        if path.parent != base:
            raise ValueError(f"findings path escapes sandbox: {path}")
        return path

    def _tool_record_finding(
        self, finding: str, location: str = "", dimension: str = ""
    ) -> dict:
        """Append one confirmed review finding to the per-phase findings file in
        the sandbox, so findings are persisted as the reviewer works rather than
        only returned in one block at the end. The file is keyed by the active
        phase/subtask label (the same label `_log_tool_call` uses), so a single
        reviewer's findings accumulate in one file."""
        path = self.findings_path_for(self.current_label or "unit")
        head = " ".join(p for p in (f"[{dimension}]" if dimension else "", location) if p)
        block = f"### {head}\n\n{finding}\n\n" if head else f"{finding}\n\n"
        with open(path, "a") as f:
            f.write(block)
        events.emit(events.FINDING, label=self.current_label,
                    dimension=dimension, location=location, text=finding)
        return {"ok": True, "recorded": location or dimension or "finding"}

    @staticmethod
    def verdicts_path_for(label: str) -> Path:
        """Sandbox path of the per-phase verdicts file (JSONL) for `label`, used
        by the false-positive filter's record_verdict tool and the review that
        reads it back. Same sandbox-escape guard as findings_path_for."""
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", label or "unit")
        base = Path(SANDBOX_PATH).resolve()
        path = (base / f"verdicts_{safe}.jsonl").resolve()
        if path.parent != base:
            raise ValueError(f"verdicts path escapes sandbox: {path}")
        return path

    def _tool_record_verdict(
        self,
        finding: str,
        impact: str = "",
        verdict: str = "",
        reason: str = "",
        proof: str = "",
    ) -> dict:
        """Record one false-positive-filter verdict as the filter works through
        the findings one at a time. Each call appends a structured JSON line to
        the per-phase verdicts file, so verdicts are durable and read back
        reliably (no giant array to parse, no markdown to re-split).
        `impact` is its severity; `verdict` is keep/drop; `proof` substantiates a
        drop. The keep/drop policy is applied by the review."""
        path = self.verdicts_path_for(self.current_label or "unit")
        record = {
            "finding": finding,
            "impact": impact,
            "verdict": verdict,
            "reason": reason,
            "proof": proof,
        }
        with open(path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        events.emit(events.VERDICT, label=self.current_label, finding=finding,
                    impact=impact, verdict=verdict, reason=reason)
        return {"ok": True, "recorded": verdict or "verdict"}

    def dispatch_tool(self, name: str, args: dict) -> dict:
        """Dispatch an agent tool by name. Returns {ok, ...}."""
        read_tools = {
            "find_definition": self._tool_find_definition,
            "find_callers": self._tool_find_callers,
            "find_callees": self._tool_find_callees,
            "grep": self._tool_grep,
            "read_file": self._tool_read_file,
            "read_doc": self._tool_read_doc,
            "list_files": self._tool_list_files,
            "get_subsystem_review_guide": self._tool_get_subsystem_review_guide,
            "git_log": self._tool_git_log,
            "git_show": self._tool_git_show,
            "git_cat_file": self._tool_git_cat_file,
            "run_checkpatch": self._tool_run_checkpatch,
            "record_finding": self._tool_record_finding,
            "record_verdict": self._tool_record_verdict,
        }
        tool_fn = read_tools.get(name)

        if tool_fn is None:
            if self.enable_edit_tools:
                write_tools = {
                    "write_file_str": self._tool_write_file_str,
                }
                tool_fn = write_tools.get(name)

        if tool_fn is None:
            result = {"ok": False, "error": f"unknown tool: {name}"}
        else:
            try:
                result = tool_fn(**args)
            except TypeError as e:
                result = {"ok": False, "error": f"bad arguments for '{name}': {e}"}
            except Exception as e:
                self.logger.error(f"tool '{name}' raised: {e}")
                result = {"ok": False, "error": str(e)}
        self._log_tool_call(name, args, result)
        return result

    def _files_in_diff(self) -> Set[str]:
        """Return the set of mount-relative file paths touched by the commit.

        Git runs in the kernel git tree (which may be a subdirectory of the
        mounted root when reviewing inside a broader workspace), and the
        tree-relative paths it reports are prefixed with that subdirectory so they
        match the paths the agent's read/grep tools use (which are relative to the
        mounted root). With no subdirectory this is exactly `git diff` at the
        root."""
        git_wd = self.docker_manager._git_workdir
        log_cmd = [*self._git_command("diff"), "--name-only", "HEAD^..HEAD"]
        proc = self.docker_manager.run_command(log_cmd, cwd=git_wd)
        stdout, _ = proc.communicate()
        prefix = self.docker_manager.git_subdir
        return {
            f"{prefix}/{f}" if prefix else f
            for f in stdout.strip().splitlines()
        }

