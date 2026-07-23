# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from patchwise import SANDBOX_PATH
from patchwise.utils.config import parse_config


@dataclass
class FpToolsConfig:
    model: str | None
    provider: str | None
    embedding_model: str | None
    embedding_provider: str | None
    verify_max_tokens: int
    vector_db_path: Path
    similarity_threshold: float
    default_top_k: int

    @classmethod
    def load(cls) -> "FpToolsConfig":
        cfg = parse_config()
        ai = cfg.get("ai", {})
        fp = ai.get("fp_tools") or {}
        provider = fp.get("provider") or ai.get("provider")

        raw_path = fp.get("vector_db_path")
        vector_db_path = (
            Path(str(raw_path)).expanduser()
            if raw_path and str(raw_path).strip()
            else SANDBOX_PATH / "fp_vector_db"
        )

        return cls(
            model=fp.get("model") or ai.get("model"),
            provider=provider,
            embedding_model=fp.get("embedding_model"),
            embedding_provider=fp.get("embedding_provider") or provider,
            verify_max_tokens=int(fp.get("verify_max_tokens") or 32000),
            vector_db_path=vector_db_path,
            similarity_threshold=float(fp.get("similarity_threshold") or 0.65),
            default_top_k=int(fp.get("default_top_k") or 3),
        )


_cfg = FpToolsConfig.load()

DEFAULT_LLM_MODEL                  = _cfg.model
DEFAULT_LLM_API_BASE               = _cfg.provider
DEFAULT_EMBEDDING_MODEL            = _cfg.embedding_model
DEFAULT_EMBEDDING_API_BASE         = _cfg.embedding_provider
DEFAULT_VERIFY_MAX_TOKENS          = _cfg.verify_max_tokens
DEFAULT_FP_DB_PATH                 = _cfg.vector_db_path
DEFAULT_FP_DB_SIMILARITY_THRESHOLD = _cfg.similarity_threshold
DEFAULT_FP_DB_TOP_K                = _cfg.default_top_k


def configure_litellm_client() -> None:
    import litellm
    litellm.ssl_verify = False


def require_model(model: str | None, *, config_key: str, option: str) -> str:
    if model and model.strip():
        return model.strip()
    raise ValueError(f"Model is required. Set {config_key} or pass {option}.")


def litellm_kwargs(
    *,
    model: str | None,
    api_base: str | None,
    model_config_key: str,
    model_option: str,
    **kwargs: Any,
) -> dict[str, Any]:
    request = {
        "model": require_model(model, config_key=model_config_key, option=model_option),
        **kwargs,
    }
    if api_base:
        request["api_base"] = api_base
    return request
