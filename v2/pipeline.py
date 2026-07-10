# FILE: v2/pipeline.py
# PURPOSE: OpenAI SDK completion helpers for V2 pipeline stages.
# OWNS: Shared text and structured completion functions with retry logic.
# EXPORTS: V2Pipeline, completion_with_retry, structured_completion.
# DOCS: README.md, v2/process.py, v2/schema.py
#
# NO LITELLM. Direct OpenAI SDK calls only.
# Text: client.chat.completions.create()
# Structured: client.beta.chat.completions.parse() -> message.parsed
#
# RETRY POLICY (HARD REQUIREMENT — DO NOT WEAKEN):
#   The pipeline MUST never advance to a downstream stage with a missing
#   or partial result from a previous stage. If the LLM call fails for ANY
#   reason — 503 "Loading model", connection drop, rate limit, parse
#   error, refusal, schema mismatch, anything — we retry. There is no
#   error classification, no fast-fail, no "this is a 4xx so give up"
#   branch. We do not move on. We do not skip. We do not write empty
#   results to disk. We wait and try again.
#
#   The only ways out of the retry loop are:
#     1. The call succeeds and returns a valid result.
#     2. The user hits Ctrl-C (KeyboardInterrupt / SystemExit).
#
#   "Effective infinity" is implemented as MAX_ATTEMPTS = 1,000,000
#   attempts with backoff capped at 120s per attempt. That ceiling is
#   unreachable in practice (~3.3 years of continuous retrying) — it's
#   there only as a theoretical guard against an unbounded counter, not
#   a real "give up" point.

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from v2.schema import BookArtifact, StageState


# Effectively infinite. Do not lower this without owner approval.
MAX_ATTEMPTS = 1_000_000

# Per-attempt backoff cap. 120s = 2 minutes between attempts on a
# stubborn outage. Combined with exponential growth this means we
# settle into a slow steady retry rhythm without hammering the API.
MAX_BACKOFF_SECONDS = 120.0

# Base delay for the exponential schedule: 1, 2, 4, 8, 16, 32, 64, 120, 120, ...
BASE_BACKOFF_SECONDS = 1.0


def _build_client(settings: Any) -> OpenAI:
    """Create an OpenAI client from a settings object."""
    return OpenAI(
        base_url=settings.api_base,
        api_key=getattr(settings, "api_key", None) or "local",
        timeout=getattr(settings, "timeout", 300),
        max_retries=0,  # We handle retries ourselves — at the call level
    )


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter, capped at MAX_BACKOFF_SECONDS.

    `attempt` is 0-indexed: 0 → ~1s, 1 → ~2s, 2 → ~4s, ... up to 120s.
    After the cap kicks in, jitter still adds ±1s variation so we don't
    sync up with other retrying clients.
    """
    delay = BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 1.0)
    return min(delay, MAX_BACKOFF_SECONDS)


def _sleep(seconds: float) -> None:
    """Interruptible sleep. KeyboardInterrupt propagates immediately."""
    time.sleep(seconds)


def completion_with_retry(
    settings: Any,
    messages: list[dict],
    *,
    max_retries: int = MAX_ATTEMPTS,
    base_delay: float = BASE_BACKOFF_SECONDS,
) -> str:
    """
    Text completion via OpenAI SDK - returns content string.

    No LiteLLM. No schema conversion. No bullshit.

    If the server rejects reasoning_effort, it is silently dropped
    and the call is retried immediately on the next attempt.

    Retries on ANY error (no classification). The function only returns
    when the model produces a non-empty content string. KeyboardInterrupt
    is the only way out of the loop other than success.
    """
    client = _build_client(settings)
    reasoning_dropped = False

    extra: dict[str, Any] = {}
    if getattr(settings, "thinking", False):
        extra["reasoning_effort"] = "high"

    for attempt in range(1, max_retries + 1):
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
            # Empty response — treat as a transient failure and retry.
            # Do NOT return. Do NOT raise. Just try again.
            print(
                f"      ⚠️  Attempt {attempt}: empty response — retrying",
                flush=True,
            )

        except (KeyboardInterrupt, SystemExit):
            # User wants out. Propagate immediately.
            raise

        except Exception as e:
            # reasoning_effort sometimes gets rejected on cold-start models.
            # Drop it and retry immediately on the same attempt, no sleep.
            if (
                not reasoning_dropped
                and "reasoning_effort" in extra
                and "reasoning_effort" in str(e).lower()
            ):
                reasoning_dropped = True
                extra.pop("reasoning_effort")
                print(
                    f"      ⚠️  Attempt {attempt}: reasoning_effort rejected — "
                    f"dropping and retrying immediately: {type(e).__name__}",
                    flush=True,
                )
                continue

            # ANY other error: log, back off, retry. No classification.
            # No fast-fail. No "this looks permanent" branch.
            delay = _backoff_delay(attempt - 1)
            print(
                f"      ⚠️  Attempt {attempt} failed: {type(e).__name__}: {e}. "
                f"Retrying in {delay:.1f}s (will keep going until success)...",
                flush=True,
            )
            _sleep(delay)
            continue

        # We got an empty response — back off and retry.
        delay = _backoff_delay(attempt - 1)
        print(
            f"      ⚠️  Attempt {attempt}: empty response, retrying in {delay:.1f}s",
            flush=True,
        )
        _sleep(delay)

    # Unreachable in practice. MAX_ATTEMPTS is 1M. If we ever get here,
    # something has gone catastrophically wrong with the counter itself.
    raise RuntimeError(
        f"completion_with_retry exhausted MAX_ATTEMPTS={max_retries}. "
        f"This should be unreachable — file a bug."
    )


def structured_completion(
    settings: Any,
    messages: list[dict],
    response_model: type[BaseModel],
    *,
    max_retries: int = MAX_ATTEMPTS,
    base_delay: float = BASE_BACKOFF_SECONDS,
) -> BaseModel:
    """
    Structured completion returning ALREADY PARSED Pydantic model.

    Uses openai.OpenAI().beta.chat.completions.parse().
    Returns message.parsed - no manual validation needed.
    No LiteLLM. No markdown stripping.

    Retries on ANY error (no classification). The function only returns
    when the model produces a parsed Pydantic object. KeyboardInterrupt
    is the only way out of the loop other than success.
    """
    client = _build_client(settings)

    for attempt in range(1, max_retries + 1):
        try:
            response = client.beta.chat.completions.parse(
                model=settings.model,
                messages=messages,
                response_format=response_model,
                temperature=getattr(settings, "temperature", 0.2),
            )
            parsed = response.choices[0].message.parsed
            if parsed is not None:
                return parsed
            # parsed=None means refusal or empty — treat as transient.
            print(
                f"      ⚠️  Attempt {attempt}: parsed=None (refusal or empty) — retrying",
                flush=True,
            )

        except (KeyboardInterrupt, SystemExit):
            raise

        except Exception as e:
            # ANY error: log, back off, retry. No classification.
            delay = _backoff_delay(attempt - 1)
            print(
                f"      ⚠️  Attempt {attempt} failed: {type(e).__name__}: {e}. "
                f"Retrying in {delay:.1f}s (will keep going until success)...",
                flush=True,
            )
            _sleep(delay)
            continue

        # Empty parsed response — back off and retry.
        delay = _backoff_delay(attempt - 1)
        print(
            f"      ⚠️  Attempt {attempt}: parsed=None, retrying in {delay:.1f}s",
            flush=True,
        )
        _sleep(delay)

    raise RuntimeError(
        f"structured_completion exhausted MAX_ATTEMPTS={max_retries}. "
        f"This should be unreachable — file a bug."
    )


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
