# FILE: v2/pipeline.py
# PURPOSE: Hold minimal V2 pipeline wiring and LiteLLM request configuration helpers.
# OWNS: V2 stage orchestration skeleton and shared completion kwargs builder.
# EXPORTS: V2Pipeline, build_completion_kwargs, completion_with_retry.
# DOCS: README.md, v2/process.py, v2/schema.py

from __future__ import annotations

import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass

# Shut up EVERY LiteLLM log at every level before import
os.environ["LITELLM_LOG"] = "ERROR"
os.environ["LITELLM_SUPPRESS_DEBUG_INFO"] = "true"

import litellm
from litellm import completion

from v2.schema import BookArtifact, StageState

# Nuke all LiteLLM loggers
litellm.suppress_debug_info = True
for name in ("LiteLLM", "litellm", "LiteLLM.Info"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.ERROR)
    logger.handlers.clear()
    logger.propagate = False


_THINK_PATTERN = re.compile(r"^.*?\\s*", re.DOTALL)
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def strip_think_tags(text: str) -> str:
    """Strip  tags from model responses."""
    if not text:
        return text
    return _THINK_PATTERN.sub("", text).strip()


def completion_with_retry(
    kwargs: dict,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> str:
    """
    Call completion with exponential backoff retry - SYNCHRONOUS.

    Strategy:
    1. First attempt uses kwargs as-is (including reasoning_effort if present).
    2. If UnsupportedParamsError (model doesn't support reasoning_effort),
       silently drop it and retry immediately — no noise.
    3. Other exceptions: retry with exponential backoff + jitter, print message.
    """
    import traceback

    print(f"      🔄 completion_with_retry ENTER (max_retries={max_retries})", flush=True)
    print(f"      📦 kwargs model: {kwargs.get('model')}", flush=True)
    print(f"      📦 kwargs messages count: {len(kwargs.get('messages', []))}", flush=True)
    print(f"      📦 kwargs has response_format: {'response_format' in kwargs}", flush=True)

    last_exc = None
    reasoning_dropped = False

    for attempt in range(max_retries + 1):
        print(f"      📍 Attempt {attempt + 1}/{max_retries + 1}", flush=True)
        current_kwargs = kwargs

        # If reasoning_effort already rejected, drop it silently
        if reasoning_dropped:
            current_kwargs = kwargs.copy()
            current_kwargs.pop("reasoning_effort", None)
            kwargs = current_kwargs  # Use this going forward

        try:
            print(f"      🔗 Calling litellm.completion() (SYNC)...", flush=True)
            response = completion(**current_kwargs)
            print(f"      ✅ Got response from completion()", flush=True)
            print(f"      📊 Response choices count: {len(response.choices)}", flush=True)
            content = (response.choices[0].message.content or "").strip()
            print(f"      📝 Content length: {len(content)} chars", flush=True)

            if content:
                print(f"      ✅ Returning content (stripped think tags)", flush=True)
                return strip_think_tags(content)

            # Empty response - treat as retryable
            last_exc = RuntimeError(f"Empty response (attempt {attempt + 1})")
            print(f"      ⚠️ Empty response", flush=True)

        except litellm.UnsupportedParamsError as e:
            # Model doesn't support reasoning_effort — drop it silently, retry immediately
            print(f"      🚫 UnsupportedParamsError: {e}", flush=True)
            if not reasoning_dropped:
                reasoning_dropped = True
                print(f"      ✂️ Dropping reasoning_effort, retrying immediately", flush=True)
                continue  # Retry immediately, no backoff, no print
            last_exc = e  # Shouldn't reach here, but safety
        except Exception as e:
            print(f"      ❌ Exception type: {type(e).__name__}", flush=True)
            print(f"      ❌ Exception msg: {e}", flush=True)
            print(f"      ❌ TRACEBACK:", flush=True)
            print(traceback.format_exc(), flush=True)
            last_exc = e

        # If this was the last attempt, raise
        if attempt == max_retries:
            print(f"      💥 Max retries reached, raising: {type(last_exc).__name__}", flush=True)
            raise last_exc

        # Exponential backoff with jitter (only for non-unsupported-param errors)
        delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
        print(f"      ⏳ Retry {attempt + 2}/{max_retries + 1} after {delay:.1f}s: {type(last_exc).__name__}", flush=True)
        print(f"      😴 Sleeping for {delay:.1f}s...", flush=True)
        time.sleep(delay)
        print(f"      ☀️ Woke up!", flush=True)


def build_completion_kwargs(
    model: str,
    messages: list[dict],
    temperature: float = 0.2,
    thinking: bool = True,
    response_format: dict | None = None,
) -> dict:
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "drop_params": True,  # Allow local servers to ignore unsupported params
    }
    if thinking:
        kwargs["reasoning_effort"] = "high"
        kwargs["allowed_openai_params"] = ["reasoning_effort"]
    if response_format:
        kwargs["response_format"] = response_format
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


__all__ = ["V2Pipeline", "build_completion_kwargs", "completion_with_retry"]
