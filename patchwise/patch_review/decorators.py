# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from typing import Any, Dict, List, Type

from .ai_fix import AiFix
from .ai_review.ai_review import AiReview
from .patch_review import PatchReview
from .static_analysis.static_analysis import StaticAnalysis

# Registries for different review types
AVAILABLE_PATCH_REVIEWS: List[Type[PatchReview]] = []
LLM_REVIEWS: List[Type[AiReview]] = []
STATIC_ANALYSIS_REVIEWS: List[Type[StaticAnalysis]] = []
SHORT_REVIEWS: List[Type[PatchReview]] = []
LONG_REVIEWS: List[Type[PatchReview]] = []
DEEP_REVIEWS: List[Type[PatchReview]] = []

# Registries for different fixes
REGISTERED_FIXES: Dict[Type[PatchReview], Type[AiFix]] = {}


# Decorators for each review type
def register_patch_review(cls: Type[Any]) -> Type[Any]:
    if cls not in AVAILABLE_PATCH_REVIEWS:
        AVAILABLE_PATCH_REVIEWS.append(cls)
    return cls


def register_llm_review(cls: Type[Any]) -> Type[Any]:
    if cls not in LLM_REVIEWS:
        LLM_REVIEWS.append(cls)
    register_patch_review(cls)
    return cls


def register_static_analysis_review(cls: Type[Any]) -> Type[Any]:
    if cls not in STATIC_ANALYSIS_REVIEWS:
        STATIC_ANALYSIS_REVIEWS.append(cls)
    register_patch_review(cls)
    return cls


def register_short_review(cls: Type[Any]) -> Type[Any]:
    if cls not in SHORT_REVIEWS:
        SHORT_REVIEWS.append(cls)
    register_patch_review(cls)
    return cls


def register_long_review(cls: Type[Any]) -> Type[Any]:
    if cls not in LONG_REVIEWS:
        LONG_REVIEWS.append(cls)
    register_patch_review(cls)
    return cls


def register_deep_review(cls: Type[Any]) -> Type[Any]:
    if cls not in DEEP_REVIEWS:
        DEEP_REVIEWS.append(cls)
    # Deep review is a heavyweight, opt-in flow that requires a full Linux
    # kernel tree.  Register it as an available patch review (so it can be
    # selected explicitly via --reviews / --deep-review) but deliberately keep
    # it out of the broad LLM_REVIEWS group, so selectors like --llm-reviews
    # and --all-reviews do not silently pull in the deep-review flow.
    register_patch_review(cls)
    return cls


def register_fix(review: Type[Any]) -> Type[Any]:
    def wrapper(cls: Type[Any]):
        if review in REGISTERED_FIXES:
            raise RuntimeError(
                f"{review.__name__} already has a registered fix {REGISTERED_FIXES[review].__name__}"
            )
        REGISTERED_FIXES[review] = cls
        return cls

    return wrapper
