# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import argparse
import atexit
import logging
import signal
from typing import Any, Iterable

from git.objects.commit import Commit

# Import each review module so its @register_* decorators fire.
from .static_analysis import checkpatch, coccicheck, dt_check, dtbs_check, sparse
from .ai_review import ai_code_review, llm_commit_audit

from patchwise.patch_review.decorators import (
    AVAILABLE_PATCH_REVIEWS,
    LLM_REVIEWS,
    LONG_REVIEWS,
    SHORT_REVIEWS,
    STATIC_ANALYSIS_REVIEWS,
)

from .patch_review import PatchReview
from patchwise.docker import CONTAINERS_BUILT

logger = logging.getLogger(__name__)


class PatchReviewResults:
    def __init__(self, commit: Commit):
        self.commit = commit
        self.results: dict[str, str] = {}

    def __repr__(self):
        return f"PatchReviewResults(commit={self.commit}, results={self.results})"


def prepare_containers_and_build_volume(
    reviews: set[str], commit: Commit, repo_path: str
) -> None:
    """Build all required containers and initialize shared build volume upfront."""
    from patchwise.docker import DockerManager
    from patchwise.patch_review.patch_review import DOCKERFILES_PATH
    from pathlib import Path

    all_reviews = {cls.__name__: cls for cls in AVAILABLE_PATCH_REVIEWS}
    selected_reviews = [all_reviews[name] for name in reviews if name in all_reviews]

    logger.info("Building required Docker containers...")

    # Always ensure base container is built first
    base_dockerfile = DOCKERFILES_PATH / "base.Dockerfile"
    base_image_tag = "patchwise-base:latest"
    base_container_name = f"patchwise-base-latest-{commit.hexsha}"

    base_manager = DockerManager(
        base_image_tag, base_container_name, Path(repo_path), commit.hexsha
    )
    base_manager.build_image(base_dockerfile)

    # Build all other required containers
    built_images = {base_image_tag}
    for review_class in selected_reviews:
        dockerfile_path = DOCKERFILES_PATH / f"{review_class.__name__}.Dockerfile"
        if not dockerfile_path.exists():
            dockerfile_path = base_dockerfile

        if dockerfile_path.name == "base.Dockerfile":
            image_tag = base_image_tag
        else:
            image_tag = f"patchwise-{review_class.__name__.lower()}"

        if image_tag not in built_images:
            container_name = f"{image_tag.replace(':', '-')}-{commit.hexsha}"
            manager = DockerManager(
                image_tag, container_name, Path(repo_path), commit.hexsha
            )
            manager.build_image(dockerfile_path)
            built_images.add(image_tag)

    # Initialize shared build volume using base container
    DockerManager.initialize_shared_build_volume(Path(repo_path), commit.hexsha)

    logger.info("Container preparation complete.")


def _cleanup_all_containers() -> None:
    """Stop all tracked containers and clean up their overlays.

    Ignores SIGINT/SIGTERM so that cleanup subprocess calls are not
    interrupted by additional Ctrl-C presses.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    for container_name, manager in list(CONTAINERS_BUILT.items()):
        logger.debug(f"Cleaning up container: {container_name}")
        try:
            manager.stop_container()
        except Exception:
            logger.warning(f"Failed to clean up docker container {container_name}.")
        CONTAINERS_BUILT.pop(container_name, None)


def register_containers_cleanup() -> None:
    atexit.register(_cleanup_all_containers)

    def signal_handler(*args):
        """Trigger a normal exit so the atexit handler runs.

        Immediately switches to SIG_IGN so that a second Ctrl-C while
        sys.exit() unwinds the stack does not re-enter the handler.
        """
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        import sys

        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def review_commit(
    reviews: set[str], commit: Commit, repo_path: str
) -> PatchReviewResults:
    all_reviews = {cls.__name__: cls for cls in AVAILABLE_PATCH_REVIEWS}
    selected_reviews = [all_reviews[name] for name in reviews if name in all_reviews]

    register_containers_cleanup()

    # Prepare containers and build volume upfront
    prepare_containers_and_build_volume(reviews, commit, repo_path)

    output = PatchReviewResults(commit)

    for selected_review in selected_reviews:
        logger.debug(f"Initializing review: {selected_review.__name__}")
        cur_review = selected_review(repo_path, commit)

        logger.debug(f"Running review: {selected_review.__name__}")
        result = cur_review.run()
        if result:
            logger.info(f"{selected_review.__name__} result:\n{result}")
        else:
            logger.info(f"{selected_review.__name__} found no issues")

        output.results[selected_review.__name__] = result

    return output


def _review_list_str(reviews: Iterable[type[PatchReview]]):
    """Helper to format review names for help messages"""
    return ", ".join(sorted({cls.__name__ for cls in reviews})) or "(none)"


def add_review_arguments(
    parser_or_group: Any,
):
    # Case-insensitive review name handling
    available_review_names = {
        cls.__name__.lower(): cls.__name__ for cls in AVAILABLE_PATCH_REVIEWS
    }
    # For display in help messages
    available_review_choices = sorted([cls.__name__ for cls in AVAILABLE_PATCH_REVIEWS])

    def _case_insensitive_review(review_name: str) -> str:
        lower_name = review_name.lower()
        if lower_name not in available_review_names:
            # This error message is more consistent with argparse's default
            raise argparse.ArgumentTypeError(
                f"invalid choice: '{review_name}' (choose from {', '.join(available_review_choices)})"
            )
        return available_review_names[lower_name]

    parser_or_group.add_argument(
        "--reviews",
        nargs="+",
        type=_case_insensitive_review,
        choices=available_review_choices,
        default=available_review_choices,
        help="Space-separated list of reviews to run. (default: %(default)s)",
    )

    # TODO perhaps add a "fast" mode for reviews that would otherwise take a long time
    parser_or_group.add_argument(
        "--short-reviews",
        action="store_true",
        help=f"Run only short reviews: [`{_review_list_str(SHORT_REVIEWS)}`]. Overrides --reviews.",
    )

    parser_or_group.add_argument(
        "--install",
        action="store_true",
        help="Install missing dependencies for the specified reviews. This will not run any reviews, only install dependencies.",
    )

    return parser_or_group


def get_selected_reviews_from_args(args: argparse.Namespace) -> set[str]:
    """
    Given parsed args, return the set of review class names to run.
    This logic is shared by all entry points.
    """
    group_sets: "list[set[str]]" = []
    if getattr(args, "all_reviews", False):
        group_sets.append(set(cls.__name__ for cls in AVAILABLE_PATCH_REVIEWS))
    if getattr(args, "llm_reviews", False):
        group_sets.append(set(cls.__name__ for cls in LLM_REVIEWS))
    if getattr(args, "static_analysis_reviews", False):
        group_sets.append(set(cls.__name__ for cls in STATIC_ANALYSIS_REVIEWS))
    if getattr(args, "short_reviews", False):
        group_sets.append(set(cls.__name__ for cls in SHORT_REVIEWS))
    if getattr(args, "long_reviews", False):
        group_sets.append(set(cls.__name__ for cls in LONG_REVIEWS))

    explicit_reviews: set[str] = (
        set(args.reviews) if hasattr(args, "reviews") and args.reviews else set()
    )

    if group_sets:
        return {str(item) for group in group_sets for item in group}
    else:
        # Default: all reviews
        return explicit_reviews
