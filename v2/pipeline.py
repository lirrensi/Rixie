# FILE: v2/pipeline.py
# PURPOSE: OpenAI SDK completion helpers for V2 pipeline stages.
# OWNS: Shared text and structured completion functions with retry logic.
# EXPORTS: V2Pipeline, completion_with_retry, structured_completion.
# DOCS: README.md, v2/process.py, v2/schema.py
#
# NO LITELLM. Direct OpenAI SDK calls only.
# Text: client.chat.completions.create()
# Structured: client.beta.chat.completions.parse() -> message.parsed

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from openai import APIError, APIConnectionError, OpenAI, RateLimitError
from pydantic import BaseModel

from v2.schema import BookArtifact, StageState


def _build_client(settings: Any) -> OpenAI:
    """Create an OpenAI client from a settings object."""
    return OpenAI(
        base_url=settings.api_base,
        api_key=getattr(settings, "api_key", None) or "local",
        timeout=getattr(settings, "timeout", 300),
        max_retries=0,  # We handle retries ourselves
    )


def completion_with_retry(
    settings: Any,
    messages: list[dict],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> str:
    """
    Text completion via OpenAI SDK - returns content string.

    No LiteLLM. No schema conversion. No bullshit.

    If the server rejects reasoning_effort, it is silently dropped
    and the call is retried immediately.
    """
    client = _build_client(settings)
    last_exc: Exception | None = None
    reasoning_dropped = False

    extra: dict[str, Any] = {}
    if getattr(settings, "thinking", False):
        extra["reasoning_effort"] = "high"

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=settings.model,
                messages=messages,
                temperature=getattr(settings, "temperature", 0.2),
                **extra,
            )
            content = (response.choices[0].message.content or "").strip()
            if content:
                return content
            last_exc = RuntimeError(f"Empty response (attempt {attempt + 1})")

        except Exception as e:
            # If reasoning_effort was rejected, drop it and retry immediately
            if not reasoning_dropped and "reasoning_effort" in extra:
                reasoning_dropped = True
                extra.pop("reasoning_effort")
                continue
            last_exc = e

        if attempt < max_retries:
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            print(f"      Retry {attempt + 2}/{max_retries + 1} "
                  f"after {delay:.1f}s: {type(last_exc).__name__}", flush=True)
            time.sleep(delay)

    raise RuntimeError(
        f"All {max_retries + 1} attempts failed. "
        f"Last error: {type(last_exc).__name__}: {last_exc}"
    ) from last_exc


def structured_completion(
    settings: Any,
    messages: list[dict],
    response_model: type[BaseModel],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> BaseModel:
    """
    Structured completion returning ALREADY PARSED Pydantic model.

    Uses openai.OpenAI().beta.chat.completions.parse().
    Returns message.parsed - no manual validation needed.
    No LiteLLM. No schema conversion. No markdown stripping.
    """
    client = _build_client(settings)
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = client.beta.chat.completions.parse(
                model=settings.model,
                messages=messages,
                response_format=response_model,
                temperature=getattr(settings, "temperature", 0.2),
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise RuntimeError("LLM returned None (refusal or empty)")
            return parsed

        except Exception as e:
            last_exc = e

        if attempt < max_retries:
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            print(f"      Retry {attempt + 2}/{max_retries + 1} "
                  f"after {delay:.1f}s: {type(last_exc).__name__}", flush=True)
            time.sleep(delay)

    raise RuntimeError(
        f"All {max_retries + 1} attempts failed. "
        f"Last error: {type(last_exc).__name__}: {last_exc}"
    ) from last_exc


@dataclass
class V2Pipeline:
    """Minimal V2 stage orchestration skeleton."""
    model: str = "gpt-4o-mini"
    temperature: float = 0.2

    def run_stage(self, artifact: BookArtifact, stage_name: str) -> BookArtifact:
        artifact.stages.setdefault(stage_name, StageState(name=stage_name, status="pending"))
        artifact.notes.append(
            f"TODO: stage '{stage_name}' not implemented yet."
        )
        return artifact.touch()


__all__ = ["V2Pipeline", "completion_with_retry", "structured_completion"]
