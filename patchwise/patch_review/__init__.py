# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import argparse

# Automatically import all patch review modules so all @register_patch_review classes are registered
import importlib
import logging
import pkgutil
from typing import Iterable

from git.objects.commit import Commit

from . import ai_review, static_analysis

# Import all modules in static_analysis subpackage
for _, modname, ispkg in pkgutil.iter_modules(static_analysis.__path__):
    if not ispkg:
        importlib.import_module(f"{__name__}.static_analysis.{modname}")

# Import all modules in ai_review subpackage
for _, modname, ispkg in pkgutil.iter_modules(ai_review.__path__):
    if not ispkg:
        importlib.import_module(f"{__name__}.ai_review.{modname}")

from patchwise.patch_review.decorators import (
    AVAILABLE_PATCH_REVIEWS,
    LLM_REVIEWS,
    LONG_REVIEWS,
    SHORT_REVIEWS,
    STATIC_ANALYSIS_REVIEWS,
)

from .patch_review import PatchReview

logger = logging.getLogger(__name__)


class PatchReviewResults:
    def __init__(self, commit: Commit):
        self.commit = commit
        self.results: dict[str, str] = {}

    def __repr__(self):
        return f"PatchReviewResults(commit={self.commit}, results={self.results})"


def run_patch_review(
    selected_reviews: list[type[PatchReview]], commit: Commit
) -> PatchReviewResults:
    output = PatchReviewResults(commit)

    for selected_review in selected_reviews:
        logger.debug(f"Initializing review: {selected_review.__name__}")
        cur_review = selected_review(commit)

        logger.debug(f"Running review: {selected_review.__name__}")
        result = cur_review.run()
        if result:
            logger.info(f"{selected_review.__name__} result:\n{result}")
        else:
            logger.info(f"{selected_review.__name__} found no issues")

        output.results[selected_review.__name__] = result

    return output


def review_patch(reviews: set[str], commit: Commit) -> PatchReviewResults:
    all_reviews = {cls.__name__: cls for cls in AVAILABLE_PATCH_REVIEWS}
    selected_reviews = [all_reviews[name] for name in reviews if name in all_reviews]

    for review_cls in selected_reviews:
        logger.debug(f"Verifying dependencies for: {review_cls.__name__}")
        review_cls.verify_dependencies()

    results = run_patch_review(selected_reviews, commit)

    return results


def install_missing_dependencies(reviews: set[str]) -> None:
    """
    Install missing dependencies for the specified reviews.
    """
    all_reviews = {cls.__name__: cls for cls in AVAILABLE_PATCH_REVIEWS}
    selected_reviews = [all_reviews[name] for name in reviews if name in all_reviews]

    for review_cls in selected_reviews:
        logger.info(f"Installing dependencies for: {review_cls.__name__}")
        review_cls.verify_dependencies(install=True)

    logger.info("All specified reviews' dependencies are installed.")


def _review_list_str(reviews: Iterable[type[PatchReview]]):
    """Helper to format review names for help messages"""
    return ", ".join(sorted({cls.__name__ for cls in reviews})) or "(none)"


def add_review_arguments(
    parser_or_group: argparse.ArgumentParser | argparse._ArgumentGroup,
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
    group_sets: list[set[str]] = []
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
        return set().union(*group_sets)
    else:
        # Default: all reviews
        return explicit_reviews
