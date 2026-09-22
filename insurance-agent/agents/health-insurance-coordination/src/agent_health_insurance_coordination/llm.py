"""Provider selection for the health-insurance-coordination agent.

Reads the hints from `agent.yaml` (`config.provider`, `config.model`) and builds
the matching chat model, validating that the corresponding key is present. When
no provider is configured, falls back to the first provider with a key in the
environment. Temperature is 0 — the same case must decide the same way twice.
"""

from __future__ import annotations

import os
from typing import Any, Optional, cast

from langchain_core.language_models import BaseChatModel


def build_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0,
) -> BaseChatModel:
    """Build the runtime chat model.

    Args:
        provider: anthropic, openai or gemini. Falls back to whichever key exists.
        model: Model name override. Each builder has its own default.
        temperature: Sampling temperature; keep at 0 for deterministic decisions.
    """
    configured_provider = os.environ.get("PROVIDER", "").strip().lower()
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    anthropic_base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    openai_base_url = os.environ.get("OPENAI_BASE_URL", "")

    def _build_gemini() -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return cast(Any, ChatGoogleGenerativeAI)(
            api_key=gemini_key,
            model= os.environ.get("MODEL", ""),
            temperature=temperature,
        )

    def _build_openai() -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "api_key": openai_key,
            "model": os.environ.get("MODEL", ""),
            "temperature": temperature,
        }
        if openai_base_url:
            if "grove-foundry" in openai_base_url:
                kwargs["base_url"] = openai_base_url.split("/v1")[0] + "/v1"
                kwargs["default_headers"] = {"api-key": openai_key}
            else:
                kwargs["base_url"] = openai_base_url.rstrip("/")
        return cast(Any, ChatOpenAI)(**kwargs)

    def _build_anthropic() -> BaseChatModel:
        from langchain_anthropic import ChatAnthropic

        kwargs: dict[str, Any] = {
            "api_key": anthropic_key,
            "model_name": os.environ.get("MODEL", ""),
            "temperature": temperature,
        }
        if anthropic_base_url:
            if "grove-foundry" in anthropic_base_url:
                kwargs["base_url"] = anthropic_base_url.split("/v1")[0].rstrip("/")
                kwargs["default_headers"] = {"api-key": anthropic_key}
            else:
                kwargs["base_url"] = anthropic_base_url.rstrip("/")
        return cast(Any, ChatAnthropic)(**kwargs)

    builders = {
        "gemini": (gemini_key, _build_gemini),
        "openai": (openai_key, _build_openai),
        "anthropic": (anthropic_key, _build_anthropic),
    }

    if configured_provider:
        if configured_provider not in builders:
            raise RuntimeError(
                "Unsupported config.provider in agent.yaml. Use one of: anthropic, gemini, openai."
            )
        provider_key, provider_builder = builders[configured_provider]
        if provider_key:
            return provider_builder()
        raise RuntimeError(
            f"agent.yaml config.provider is set to {configured_provider!r}, "
            "but the matching API key is missing from .env."
        )

    for provider_key, provider_builder in builders.values():
        if provider_key:
            return provider_builder()

    raise RuntimeError(
        "No LLM API key found. Set ANTHROPIC_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY."
    )
