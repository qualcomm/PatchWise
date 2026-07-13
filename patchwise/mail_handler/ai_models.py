# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from patchwise.patch_review.ai_agent.agent import Agent
from patchwise.utils.config import parse_config


def get_model_name():
    model_to_name = parse_config().get("ai", {}).get("models") or {}
    return model_to_name.get(Agent.model, Agent.model)
