# FILE: v2/pipeline.py
# PURPOSE: Hold minimal V2 pipeline wiring and LiteLLM request configuration helpers.
# OWNS: V2 stage orchestration skeleton and shared completion kwargs builder.
# EXPORTS: V2Pipeline, build_completion_kwargs, strip_think_tags, acompletion_with_retry.
# DOCS: README.md, v2/process.py, v2/schema.py

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import sys
from dataclasses import dataclass

# Shut up EVERY LiteLLM log at every level before import
os.environ["LITELLM_LOG"] = "ERROR"
os.environ["LITELLM_SUPPRESS_DEBUG_INFO"] = "true"

import litellm
from litellm import acompletion, completion

from v2.schema import BookArtifact, StageState

# Nuke all LiteLLM loggers
litellm.suppress_debug_info = True
for name in ("LiteLLM", "litellm", "LiteLLM.Info"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.ERROR)
    logger.handlers.clear()
    logger.propagate = False


_THINK_PATTERN = re.compile(r"^.*?</think>\s*", re.DOTALL)
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def strip_think_tags(text: str) -> str:
    """Strip <think>...</think> blocks from model responses."""
    if not text:
        return text
    return _THINK_PATTERN.sub("", text).strip()


async def acompletion_with_retry(
    kwargs: dict,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> str:
    """
    Call acompletion with exponential backoff retry.

    Strategy:
    1. First attempt uses kwargs as-is (including reasoning_effort if present).
    2. If UnsupportedParamsError (model doesn't support reasoning_effort),
       silently drop it and retry immediately — no noise.
    3. Other exceptions: retry with exponential backoff + jitter, print message.
    """
    last_exc = None
    reasoning_dropped = False

    for attempt in range(max_retries + 1):
        current_kwargs = kwargs

        # If reasoning_effort already rejected, drop it silently
        if reasoning_dropped:
            current_kwargs = kwargs.copy()
            current_kwargs.pop("reasoning_effort", None)
            kwargs = current_kwargs  # Use this going forward

        try:
            response = await acompletion(**current_kwargs)
            content = (response.choices[0].message.content or "").strip()
            if content:
                return strip_think_tags(content)
            # Empty response - treat as retryable
            last_exc = RuntimeError(f"Empty response (attempt {attempt + 1})")
        except litellm.UnsupportedParamsError as e:
            # Model doesn't support reasoning_effort — drop it silently, retry immediately
            if not reasoning_dropped:
                reasoning_dropped = True
                continue  # Retry immediately, no backoff, no print
            last_exc = e  # Shouldn't reach here, but safety
        except Exception as e:
            last_exc = e

        # If this was the last attempt, raise
        if attempt == max_retries:
            raise last_exc

        # Exponential backoff with jitter (only for non-unsupported-param errors)
        delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
        print(f"   \u23f3 Retry {attempt + 2}/{max_retries + 1} after {delay:.1f}s: {type(last_exc).__name__}: {last_exc}")
        sys.stdout.flush()
        await asyncio.sleep(delay)


def build_completion_kwargs(
    model: str,
    messages: list[dict],
    temperature: float = 0.2,
    thinking: bool = True,
) -> dict:
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if thinking:
        kwargs["reasoning_effort"] = "high"
        kwargs["allowed_openai_params"] = ["reasoning_effort"]
    return kwargs


@dataclass
class V2Pipeline:
    model: str = "gpt-4o-mini"
    temperature: float = 0.2

    def preview_request(self, artifact: BookArtifact, stage_name: str) -> dict:
        return build_completion_kwargs(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": f"Prepare V2 stage {stage_name}."},
                {"role": "user", "content": f"Book: {artifact.metadata.title}"},
            ],
        )

    def run_stage(self, artifact: BookArtifact, stage_name: str) -> BookArtifact:
        artifact.stages.setdefault(stage_name, StageState(name=stage_name, status="pending"))
        artifact.notes.append(
            f"TODO: stage '{stage_name}' not implemented yet; LiteLLM hook available via v2.pipeline."
        )
        return artifact.touch()


__all__ = ["V2Pipeline", "build_completion_kwargs", "completion"]
