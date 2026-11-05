"""LLM provider selection for Care Coordination - Health Insurance."""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from openai import (
    DefaultAsyncHttpxClient,
    DefaultHttpxClient,
)
from langchain_core.language_models import BaseChatModel

MODEL = "gpt-5.4"


def build_llm(temperature: float = 0) -> BaseChatModel:
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is missing; add it to .env or project secrets")

    # Inject secrets at send time so LangChain traces cannot serialize them.
    def inject_headers(request):
        # Grove Legacy API keys authenticate with the api-key header, not Bearer.
        request.headers.pop("authorization", None)
        request.headers["api-key"] = api_key

    async def inject_async_headers(request):
        inject_headers(request)

    http_client = DefaultHttpxClient(event_hooks={"request": [inject_headers]}, follow_redirects=False)
    http_async_client = DefaultAsyncHttpxClient(event_hooks={"request": [inject_async_headers]}, follow_redirects=False)
    return ChatOpenAI(
        model=MODEL,
        api_key=SecretStr("unused"),
        base_url="https://grove-gateway-prod.azure-api.net/grove-foundry-prod/openai/v1",
        use_responses_api=True,
        http_client=http_client,
        http_async_client=http_async_client,
    )
