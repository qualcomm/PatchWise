# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from patchwise.patch_review.ai_agent.agent import Agent

_MODEL_TO_NAME = {}


def get_model_name():
    if Agent.model in _MODEL_TO_NAME:
        return _MODEL_TO_NAME[Agent.model]
    return Agent.model
