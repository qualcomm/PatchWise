#!/usr/bin/env python3
"""Validate a review-commits Mode A/B patch-series manifest.

The manifest is the orchestrator's source of truth for patch identity, rule
selection, artifact paths, and dependency groups.  Keep this validator strict:
an invalid manifest should stop review preparation before subagents receive
incorrect patch metadata.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
import re

from select_rule_cards import select_rule_cards

SCHEMA = "review-commits.patch-series-manifest.v1"
MODES = {"A", "B"}
PACKET_MODES = {"packet"}
PATH_KEYS = {
    "diff": "tmp/patch_{n}_diff.txt",
    "build": "tmp/patch_{n}_build.txt",
    "dtbinding": "tmp/patch_{n}_dtbinding.txt",
    "packet": "tmp/patch_{n}_review_packet.md",
    "packet_json": "tmp/patch_{n}_review_packet.json",
    "block": "tmp/patch_{n}_block.html",
}


def load_known_rule_cards(skill_dir: Path) -> dict[str, str]:
    index_path = skill_dir / "refs" / "rule-index.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    cards = data.get("rule_cards", [])
    if not isinstance(cards, list):
        raise ValueError("refs/rule-index.json: rule_cards must be a list")
    known: dict[str, str] = {}
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            raise ValueError(f"refs/rule-index.json: rule_cards[{index}] must be an object")
        card_id = card.get("id")
        card_path = card.get("card")
        if not isinstance(card_id, str) or not card_id:
            raise ValueError(f"refs/rule-index.json: rule_cards[{index}].id must be non-empty")
        if not isinstance(card_path, str) or not card_path.startswith("refs/rule-cards/"):
            raise ValueError(f"refs/rule-index.json: rule card {card_id} has invalid path")
        if not (skill_dir / card_path).is_file():
            raise ValueError(f"refs/rule-index.json: rule card file missing: {card_path}")
        known[card_id] = card_path
    return known


def run_git(project: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(project),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.rstrip("\n")


def split_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line]


def patch_diff_text(project: Path | None, patch: dict[str, Any]) -> str | None:
    paths = patch.get("paths")
    diff_path = paths.get("diff") if isinstance(paths, dict) else None
    if isinstance(diff_path, str) and diff_path:
        candidate = Path(diff_path)
        if not candidate.is_absolute() and project is not None:
            candidate = project / candidate
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    commit = patch.get("hash")
    if project is not None and isinstance(commit, str) and commit:
        try:
            return run_git(project, ["show", "--format=", "--find-renames", commit])
        except subprocess.CalledProcessError:
            return None
    return None


def patch_message_text(project: Path | None, patch: dict[str, Any]) -> str:
    commit = patch.get("hash")
    if project is not None and isinstance(commit, str) and commit:
        try:
            return run_git(project, ["log", "--format=%B", "-1", commit])
        except subprocess.CalledProcessError:
            pass
    subject = patch.get("subject")
    return str(subject or "")


def expected_packet_rule_cards(
    *,
    skill_dir: Path,
    project: Path | None,
    patch: dict[str, Any],
) -> list[dict[str, Any]] | None:
    files = patch.get("files")
    if not isinstance(files, list) or not all(isinstance(path, str) for path in files):
        return None
    diff_text = patch_diff_text(project, patch)
    if diff_text is None:
        return None
    return select_rule_cards(
        skill_dir=skill_dir,
        paths=files,
        diff_text=diff_text,
        message=patch_message_text(project, patch),
    )



def validate_path(path: str) -> str | None:
    if not path:
        return "empty path"
    if path.startswith("/"):
        return "absolute path is not allowed"
    parts = Path(path).parts
    if ".." in parts:
        return "parent-directory component is not allowed"
    return None


def validate_manifest(manifest: Any, args: argparse.Namespace) -> list[str]:
    errors: list[str] = []
    skill_dir = args.skill_dir.expanduser().resolve()
    project = args.project.expanduser().resolve() if args.project else None
    try:
        known_rule_cards = load_known_rule_cards(skill_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot load rule card index: {exc}"]
    if not isinstance(manifest, dict):
        return ["manifest root must be a JSON object"]

    schema = manifest.get("schema")
    if schema != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}, got {schema!r}")

    mode = manifest.get("mode")
    if mode not in MODES:
        errors.append(f"mode must be one of {sorted(MODES)}, got {mode!r}")
    if args.mode and mode != args.mode:
        errors.append(f"mode mismatch: expected {args.mode!r}, got {mode!r}")

    slug = manifest.get("slug")
    if not isinstance(slug, str) or not slug:
        errors.append("slug must be a non-empty string")
    if args.slug and slug != args.slug:
        errors.append(f"slug mismatch: expected {args.slug!r}, got {slug!r}")

    review_base = manifest.get("review_base")
    review_tip = manifest.get("review_tip")
    packet_mode = manifest.get("packet_mode")
    if packet_mode != "packet":
        errors.append(f"packet_mode must be 'packet', got {packet_mode!r}")
    if args.packet_mode and packet_mode != args.packet_mode:
        errors.append(f"packet_mode mismatch: expected {args.packet_mode!r}, got {packet_mode!r}")
    if not isinstance(review_base, str) or not review_base:
        errors.append("review_base must be a non-empty string")
    if not isinstance(review_tip, str) or not review_tip:
        errors.append("review_tip must be a non-empty string")
    if args.review_base and review_base != args.review_base:
        errors.append(f"review_base mismatch: expected {args.review_base!r}, got {review_base!r}")
    if args.review_tip and review_tip != args.review_tip:
        errors.append(f"review_tip mismatch: expected {args.review_tip!r}, got {review_tip!r}")

    total = manifest.get("total")
    if not isinstance(total, int) or total <= 0:
        errors.append(f"total must be a positive integer, got {total!r}")
        total = 0
    if args.total is not None and total != args.total:
        errors.append(f"total mismatch: expected {args.total}, got {total}")

    output = manifest.get("output")
    if not isinstance(output, str) or not output:
        errors.append("output must be a non-empty string")

    patches = manifest.get("patches")
    if not isinstance(patches, list):
        errors.append("patches must be a list")
        patches = []
    if total and len(patches) != total:
        errors.append(f"patch count mismatch: total={total}, patches={len(patches)}")

    seen_numbers: set[int] = set()
    group_by_patch: dict[int, int] = {}
    for index, patch in enumerate(patches, start=1):
        if not isinstance(patch, dict):
            errors.append(f"patch {index}: must be an object")
            continue

        n = patch.get("n")
        if n != index:
            errors.append(f"patch {index}: n must be {index}, got {n!r}")
        if isinstance(n, int):
            if n in seen_numbers:
                errors.append(f"patch {index}: duplicate n={n}")
            seen_numbers.add(n)

        if patch.get("total") != total:
            errors.append(f"patch {index}: total must be {total}, got {patch.get('total')!r}")

        commit = patch.get("hash")
        if not isinstance(commit, str) or not commit:
            errors.append(f"patch {index}: hash must be a non-empty string")
        short_hash = patch.get("short_hash")
        if not isinstance(short_hash, str) or not isinstance(commit, str) or short_hash != commit[:12]:
            errors.append(f"patch {index}: short_hash must match hash[:12]")

        subject = patch.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            errors.append(f"patch {index}: subject must be non-empty")

        files = patch.get("files")
        if not isinstance(files, list) or not all(isinstance(path, str) for path in files):
            errors.append(f"patch {index}: files must be a list of strings")
            files = []
        if not files:
            errors.append(f"patch {index}: files must not be empty")
        if len(files) != len(set(files)):
            errors.append(f"patch {index}: files must not contain duplicates")
        for path in files:
            path_error = validate_path(path)
            if path_error:
                errors.append(f"patch {index}: invalid file path {path!r}: {path_error}")

        for key in ("fixes", "dt", "dt_file", "dt_driver", "hardware", "qcom_scm_memory"):
            if not isinstance(patch.get(key), bool):
                errors.append(f"patch {index}: {key} must be boolean")

        # dt is the union flag retained for the dependency graph; it must agree
        # with the split dt_file/dt_driver flags that drive packet card selection.
        if isinstance(patch.get("dt"), bool) and isinstance(patch.get("dt_file"), bool) \
                and isinstance(patch.get("dt_driver"), bool):
            if patch["dt"] != (patch["dt_file"] or patch["dt_driver"]):
                errors.append(
                    f"patch {index}: dt must equal dt_file or dt_driver "
                    f"(dt={patch['dt']}, dt_file={patch['dt_file']}, dt_driver={patch['dt_driver']})"
                )

        if "rule_args" in patch:
            errors.append(f"patch {index}: rule_args is a removed rules-brief field and must be omitted")

        rule_cards = patch.get("rule_cards")
        if not isinstance(rule_cards, list):
            errors.append(f"patch {index}: rule_cards must be a list")
            rule_cards = []
        seen_cards: set[str] = set()
        for card_index, card in enumerate(rule_cards, start=1):
            if not isinstance(card, dict):
                errors.append(f"patch {index}: rule_cards[{card_index}] must be an object")
                continue
            card_id = card.get("id")
            card_path = card.get("card")
            triggers = card.get("triggers")
            if not isinstance(card_id, str) or not card_id:
                errors.append(f"patch {index}: rule_cards[{card_index}].id must be non-empty")
                continue
            if card_id in seen_cards:
                errors.append(f"patch {index}: duplicate rule card {card_id}")
            seen_cards.add(card_id)
            expected_card_path = known_rule_cards.get(card_id)
            if expected_card_path is None:
                errors.append(f"patch {index}: unknown rule card {card_id}")
            elif card_path != expected_card_path:
                errors.append(
                    f"patch {index}: rule card {card_id} path must be "
                    f"{expected_card_path!r}, got {card_path!r}"
                )
            if not isinstance(triggers, list) or not all(isinstance(item, str) and item for item in triggers):
                errors.append(f"patch {index}: rule card {card_id} triggers must be non-empty strings")
        try:
            expected_cards = expected_packet_rule_cards(
                skill_dir=skill_dir,
                project=project,
                patch=patch,
            )
        except (OSError, ValueError, json.JSONDecodeError, re.error) as exc:
            errors.append(f"patch {index}: cannot recompute packet rule cards: {exc}")
            expected_cards = None
        if expected_cards is not None:
            expected_ids = [str(card.get("id")) for card in expected_cards if isinstance(card.get("id"), str)]
            actual_ids = [str(card.get("id")) for card in rule_cards if isinstance(card, dict) and isinstance(card.get("id"), str)]
            if actual_ids != expected_ids:
                errors.append(
                    f"patch {index}: packet rule_cards mismatch: "
                    f"expected selector output {expected_ids!r}, got {actual_ids!r}"
                )

        paths = patch.get("paths")
        if not isinstance(paths, dict):
            errors.append(f"patch {index}: paths must be an object")
            paths = {}
        for key, template in PATH_KEYS.items():
            expected_path = template.format(n=index)
            if paths.get(key) != expected_path:
                errors.append(f"patch {index}: paths.{key} must be {expected_path!r}, got {paths.get(key)!r}")

        dependencies = patch.get("dependencies")
        if not isinstance(dependencies, list):
            errors.append(f"patch {index}: dependencies must be a list")
            dependencies = []
        for dep in dependencies:
            if not isinstance(dep, dict):
                errors.append(f"patch {index}: dependency entries must be objects")
                continue
            dep_n = dep.get("n")
            if not isinstance(dep_n, int) or dep_n < 1 or dep_n >= index:
                errors.append(f"patch {index}: dependency n must refer to an earlier patch, got {dep_n!r}")
            reasons = dep.get("reasons")
            if not isinstance(reasons, list) or not reasons or not all(isinstance(reason, str) and reason for reason in reasons):
                errors.append(f"patch {index}: dependency reasons must be non-empty strings")

        group = patch.get("group")
        if not isinstance(group, int) or group <= 0:
            errors.append(f"patch {index}: group must be a positive integer")
        else:
            group_by_patch[index] = group

    expected_numbers = set(range(1, total + 1)) if total else set()
    if total and seen_numbers != expected_numbers:
        errors.append(f"patch numbers must be exactly 1..{total}, got {sorted(seen_numbers)}")

    validate_groups(manifest.get("groups"), total, group_by_patch, errors)
    if project:
        validate_against_git(project, patches, review_base, review_tip, errors)
    return errors


def validate_groups(groups: Any, total: int, group_by_patch: dict[int, int], errors: list[str]) -> None:
    if not isinstance(groups, list):
        errors.append("groups must be a list")
        return

    covered: list[int] = []
    previous_group = 0
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            errors.append(f"groups[{index}]: must be an object")
            continue
        group_id = group.get("group")
        patches = group.get("patches")
        if not isinstance(group_id, int) or group_id <= 0:
            errors.append(f"groups[{index}]: group must be a positive integer")
            continue
        if group_id <= previous_group:
            errors.append(f"groups[{index}]: groups must be sorted and unique")
        previous_group = group_id
        if not isinstance(patches, list) or not patches or not all(isinstance(n, int) for n in patches):
            errors.append(f"groups[{index}]: patches must be a non-empty list of integers")
            continue
        if patches != sorted(patches):
            errors.append(f"groups[{index}]: patches must be sorted")
        for patch_n in patches:
            covered.append(patch_n)
            if patch_n < 1 or patch_n > total:
                errors.append(f"groups[{index}]: patch {patch_n} outside 1..{total}")
            if group_by_patch.get(patch_n) != group_id:
                errors.append(
                    f"groups[{index}]: patch {patch_n} group mismatch: "
                    f"patch has {group_by_patch.get(patch_n)!r}, group entry has {group_id!r}"
                )

    expected = list(range(1, total + 1)) if total else []
    if sorted(covered) != expected:
        errors.append(f"groups must cover each patch exactly once: expected {expected}, got {sorted(covered)}")
    if len(covered) != len(set(covered)):
        errors.append("groups must not list a patch more than once")


def validate_against_git(
    project: Path,
    patches: list[Any],
    review_base: Any,
    review_tip: Any,
    errors: list[str],
) -> None:
    if not project.is_dir():
        errors.append(f"project path does not exist: {project}")
        return
    try:
        run_git(project, ["rev-parse", "--is-inside-work-tree"])
    except subprocess.CalledProcessError as exc:
        errors.append(f"project is not a git work tree: {exc.stderr.strip() or exc}")
        return

    if isinstance(review_tip, str) and review_tip:
        try:
            run_git(project, ["cat-file", "-e", f"{review_tip}^{{commit}}"])
        except subprocess.CalledProcessError:
            errors.append(f"review_tip is not a commit: {review_tip}")
    if isinstance(review_base, str) and review_base and review_base != "<root>":
        try:
            run_git(project, ["cat-file", "-e", f"{review_base}^{{commit}}"])
        except subprocess.CalledProcessError:
            errors.append(f"review_base is not a commit: {review_base}")

    for index, patch in enumerate(patches, start=1):
        if not isinstance(patch, dict) or not isinstance(patch.get("hash"), str):
            continue
        commit = patch["hash"]
        try:
            run_git(project, ["cat-file", "-e", f"{commit}^{{commit}}"])
            git_subject = run_git(project, ["log", "--format=%s", "-1", commit])
            git_files = split_lines(run_git(project, ["show", "--format=", "--name-only", commit]))
        except subprocess.CalledProcessError as exc:
            errors.append(f"patch {index}: git validation failed for {commit}: {exc.stderr.strip() or exc}")
            continue
        if patch.get("subject") != git_subject:
            errors.append(f"patch {index}: subject differs from git commit subject")
        if patch.get("files") != git_files:
            errors.append(f"patch {index}: files differ from git changed-file list")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a review-commits patch-series manifest")
    parser.add_argument("manifest", type=Path, help="Manifest JSON path")
    parser.add_argument("--project", type=Path, help="Optional git project path for commit cross-checks")
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parents[1], help="review-commits skill directory")
    parser.add_argument("--mode", choices=sorted(MODES), help="Expected review mode")
    parser.add_argument("--slug", help="Expected review slug")
    parser.add_argument("--review-base", help="Expected review base")
    parser.add_argument("--review-tip", help="Expected review tip")
    parser.add_argument("--total", type=int, help="Expected patch count")
    parser.add_argument("--packet-mode", choices=sorted(PACKET_MODES), help="Expected packet-only reviewer artifact mode")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"validate_series_manifest.py: cannot read {args.manifest}: {exc}", file=sys.stderr)
        return 1

    errors = validate_manifest(manifest, args)
    if errors:
        print(f"series manifest invalid: {args.manifest}", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"series manifest valid: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
