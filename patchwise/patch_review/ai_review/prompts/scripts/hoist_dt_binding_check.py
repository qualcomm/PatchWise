#!/usr/bin/env python3
"""Run a single series-level `make dt_binding_check` and split the output back
into per-patch ``tmp/patch_<N>_dtbinding.txt`` files.

The per-patch loop in ``startup-workflow.md`` Step 2 used to invoke
``make dt_binding_check`` once per patch that touches a Documentation/
devicetree/bindings/*.yaml file.  Each invocation was ~24s of cold dtschema
work — for a series with K DT-binding patches, that meant ``K × 24s`` of
mostly-redundant schema validation.  This helper hoists the work to a single
combined invocation:

    make ARCH=arm64 DT_SCHEMA_FILES=<a.yaml>:<b.yaml>:... dt_binding_check -j<jobs>

then splits the captured output by filename into per-patch files so the
existing ``patch_<N>_dtbinding.txt`` consumer contract is preserved.

Output routing:
- Each output line is matched against any of the series-touched YAML paths.
  A line that names YAML ``X`` is appended to every patch that touched ``X``.
- Lines that do not name any tracked YAML (header noise like ``SCHEMA …``,
  ``DTC …``, summary banners) are appended to every YAML-touching patch's
  file so per-patch readers see the same surrounding context.
- Patches that touch zero YAMLs get no file (matches the previous "if neither
  condition applies, do not create patch_<N>_dtbinding.txt" rule).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def _yaml_paths_per_patch(manifest: dict) -> dict[int, list[str]]:
    """Return ``{patch_number: [yaml_path, ...]}`` for every patch that touched
    at least one Documentation/devicetree/bindings/*.yaml file.
    """
    result: dict[int, list[str]] = {}
    for patch in manifest.get("patches", []):
        n = patch.get("n")
        if not isinstance(n, int):
            continue
        yamls = sorted(
            f for f in patch.get("files", [])
            if isinstance(f, str)
            and f.startswith("Documentation/devicetree/bindings/")
            and (f.endswith(".yaml") or f.endswith(".yml"))
        )
        if yamls:
            result[n] = yamls
    return result


def _run_combined(
    project: Path,
    yamls: list[str],
    *,
    arch: str,
    jobs: int,
    timeout: int,
) -> tuple[int, str]:
    """Run a single combined ``dt_binding_check`` over all YAMLs.  Returns
    ``(returncode, combined_stdout_stderr)``.  Returncode 124 is the timeout
    signal.
    """
    schema_files = ":".join(yamls)
    env = os.environ.copy()
    env.setdefault("LANG", "C")
    env.setdefault("LC_ALL", "C")
    cmd = [
        "timeout", str(timeout),
        "make", f"ARCH={arch}",
        f"DT_SCHEMA_FILES={schema_files}",
        "dt_binding_check",
        f"-j{jobs}",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(project),
        text=True,
        capture_output=True,
        # Same stdin contract as run_w1_build.py / startup-workflow inline
        # makes — feed defaults so a build-triggered Kconfig syncconfig
        # restart cannot dump a prompt transcript into the artifact.
        input="\n" * 4096,
        env=env,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _split_output(
    output: str,
    yaml_paths_per_patch: dict[int, list[str]],
) -> dict[int, list[str]]:
    """Route each output line to the per-patch buckets that touch it.

    A line is attributed to patch N if it mentions any YAML in ``patches[N]``.
    Lines that mention NO tracked YAML are sent to every bucket (they are
    likely shared schema-rebuild noise the reader needs surrounding context).
    """
    all_yamls: set[str] = set()
    yaml_to_patches: dict[str, list[int]] = defaultdict(list)
    for n, yamls in yaml_paths_per_patch.items():
        for y in yamls:
            all_yamls.add(y)
            yaml_to_patches[y].append(n)

    buckets: dict[int, list[str]] = {n: [] for n in yaml_paths_per_patch}
    for line in output.splitlines():
        targeted = [y for y in all_yamls if y in line]
        if targeted:
            seen: set[int] = set()
            for y in targeted:
                for n in yaml_to_patches[y]:
                    if n in seen:
                        continue
                    seen.add(n)
                    buckets[n].append(line)
        else:
            for n in buckets:
                buckets[n].append(line)
    return buckets


def _write_per_patch(
    project: Path,
    buckets: dict[int, list[str]],
    *,
    yaml_paths_per_patch: dict[int, list[str]],
    returncode: int,
    timeout: int,
    schema_files_count: int,
) -> None:
    tmp_dir = project / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    if returncode == 0:
        verdict = "DT binding check: PASS"
    elif returncode == 124:
        verdict = f"DT binding check: TIMEOUT after {timeout}s — manual review required"
    else:
        verdict = f"DT binding check: FAIL status={returncode}"
    for n, lines in buckets.items():
        path = tmp_dir / f"patch_{n}_dtbinding.txt"
        # Write with header (touched YAMLs for this patch), the routed output,
        # and the verdict.  Use append-style so a subsequent CHECK_DTBS run
        # for DTS/DTSI patches can still tack onto the same file.
        header = (
            f"Series-level dt_binding_check (combined run, "
            f"{schema_files_count} schema(s)).\n"
            f"YAMLs touched by patch {n}: "
            + ", ".join(yaml_paths_per_patch[n])
            + "\n"
        )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(header)
            for line in lines:
                fh.write(line)
                fh.write("\n")
            fh.write(verdict + "\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="kernel tree path")
    parser.add_argument(
        "--manifest", type=Path, required=True,
        help="series manifest JSON (tmp/series_manifest_<slug>.json)",
    )
    parser.add_argument("--arch", default="arm64", help="ARCH=<value> for make")
    parser.add_argument("--jobs", type=int, default=64, help="parallelism for make")
    parser.add_argument("--timeout", type=int, default=600, help="overall timeout (s)")
    args = parser.parse_args(argv)

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"hoist_dt_binding_check.py: cannot load manifest: {exc}", file=sys.stderr)
        return 1

    yaml_paths_per_patch = _yaml_paths_per_patch(manifest)
    if not yaml_paths_per_patch:
        # No DT-binding patches in the series — nothing to do, no per-patch
        # files written.  Matches the previous "if neither condition applies,
        # do not create patch_<N>_dtbinding.txt" rule.
        print("(series has no Documentation/devicetree/bindings/*.yaml touches — dt_binding_check skipped)")
        return 0

    all_yamls = sorted({y for yamls in yaml_paths_per_patch.values() for y in yamls})
    # Scale timeout with schema count so a series with K YAMLs gets at least
    # 60s × K (capped by the supplied --timeout if larger).
    scaled_timeout = max(args.timeout, 60 * len(all_yamls))

    rc, output = _run_combined(
        args.project, all_yamls,
        arch=args.arch, jobs=args.jobs, timeout=scaled_timeout,
    )
    buckets = _split_output(output, yaml_paths_per_patch)
    _write_per_patch(
        args.project, buckets,
        yaml_paths_per_patch=yaml_paths_per_patch,
        returncode=rc, timeout=scaled_timeout,
        schema_files_count=len(all_yamls),
    )
    print(
        f"dt_binding_check hoisted: {len(all_yamls)} schema(s) across "
        f"{len(yaml_paths_per_patch)} patch(es); rc={rc}"
    )
    return 0 if rc == 0 else rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
