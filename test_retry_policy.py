"""Test the new infinite-retry policy against the real local LLM server.

Two scenarios:
  1. Happy path: real model, real response. Confirm normal call works.
  2. Forced failure: nonexistent model. Confirm the retry layer keeps
     hammering for as long as we let it, then succeeds (or we'd abort).
     We cap at max_retries=5 for the test so we don't wait forever.
  3. Drop the cap: just verify the function doesn't return on a failure.

Run with:
    uv run python test_retry_policy.py
"""

import sys
import time
from typing import Any
from pydantic import BaseModel

from v2.pipeline import (
    completion_with_retry,
    structured_completion,
    MAX_ATTEMPTS,
    MAX_BACKOFF_SECONDS,
)


class TestSettings:
    """Settings pointing at the local llama.cpp server on :58080."""
    api_base = "http://localhost:58080/v1"
    api_key = "local"
    model = "gemma-4-26B-A4B-it-ultra-uncensored-heretic-Q5_K_S.gguf"
    temperature = 0.2
    thinking = False
    timeout = 60


class EchoResult(BaseModel):
    answer: str


def banner(msg: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {msg}")
    print("=" * 60, flush=True)


def test_happy_path() -> None:
    """1) Real model, real response. Should succeed on attempt 1."""
    banner("TEST 1: Happy path (real model, expect success on attempt 1)")

    msgs = [
        {"role": "system", "content": "You are a helpful assistant. Reply in JSON with a single field 'answer'."},
        {"role": "user", "content": "Reply with JSON: {\"answer\": \"pong\"}"},
    ]
    settings = TestSettings()
    settings.model = "gemma-4-26B-A4B-it-ultra-uncensored-heretic-Q5_K_S.gguf"

    start = time.time()
    result: EchoResult = structured_completion(settings, msgs, EchoResult, max_retries=3)
    elapsed = time.time() - start

    print(f"   ✅ Returned: {result}")
    print(f"   ⏱️  Elapsed:  {elapsed:.2f}s")


def test_forced_failure_with_cap() -> None:
    """2) Nonexistent model, capped at 4 attempts. Should exhaust and raise."""
    banner("TEST 2: Forced failure (nonexistent model, capped at 4 attempts)")

    msgs = [{"role": "user", "content": "hello"}]
    settings = TestSettings()
    settings.model = "this-model-does-not-exist-12345"

    start = time.time()
    try:
        result = structured_completion(settings, msgs, EchoResult, max_retries=4)
        print(f"   ❌ UNEXPECTED success: {result}")
    except RuntimeError as e:
        elapsed = time.time() - start
        print(f"   ✅ Raised RuntimeError after {elapsed:.1f}s (expected behavior at cap)")
        print(f"      Error: {str(e)[:120]}")


def test_recovery_after_failures() -> None:
    """3) Force a couple of failures (bad model first 2 calls), then succeed.

    We do this by monkey-patching the client builder so it swaps to a
    real working model on attempt 3. This proves the retry loop doesn't
    give up when the early attempts fail — it just keeps going.
    """
    banner("TEST 3: Recovery (fail twice, then succeed on attempt 3)")

    from unittest.mock import patch
    from openai import OpenAI
    from v2 import pipeline

    call_count = {"n": 0}
    real_model = "gemma-4-26B-A4B-it-ultra-uncensored-heretic-Q5_K_S.gguf"
    bad_model = "this-model-does-not-exist-12345"

    def switchable_client(settings):
        """Return a real client, but flip the model on first 2 calls."""
        call_count["n"] += 1
        if call_count["n"] <= 2:
            settings.model = bad_model
        else:
            settings.model = real_model
        return OpenAI(
            base_url=settings.api_base,
            api_key=getattr(settings, "api_key", None) or "local",
            timeout=getattr(settings, "timeout", 300),
            max_retries=0,
        )

    msgs = [
        {"role": "system", "content": "Reply in JSON with a single field 'answer'."},
        {"role": "user", "content": "Reply with JSON: {\"answer\": \"recovered\"}"},
    ]
    settings = TestSettings()

    start = time.time()
    with patch.object(pipeline, "_build_client", side_effect=switchable_client):
        result: EchoResult = structured_completion(settings, msgs, EchoResult, max_retries=10)
    elapsed = time.time() - start

    print(f"   ✅ Recovered: {result}")
    print(f"   📞 Total client calls: {call_count['n']}")
    print(f"   ⏱️  Elapsed: {elapsed:.1f}s (includes ~1s + 2s backoff between failures)")


def test_infinite_retry_signature() -> None:
    """4) Confirm the constants are 'effectively infinite'."""
    banner("TEST 4: Confirm infinite-retry policy is in effect")
    print(f"   MAX_ATTEMPTS         = {MAX_ATTEMPTS:,}")
    print(f"   MAX_BACKOFF_SECONDS  = {MAX_BACKOFF_SECONDS}s")
    print(f"   Default base delay   = 1s (doubles each retry up to cap)")
    if MAX_ATTEMPTS >= 100_000:
        print("   ✅ Effectively infinite: 100k+ attempts ceiling is unreachable in practice")
    else:
        print(f"   ❌ MAX_ATTEMPTS too low: {MAX_ATTEMPTS}")


if __name__ == "__main__":
    print("🔬 Testing new infinite-retry policy against local llama.cpp server...")
    print(f"   Server: http://localhost:58080/v1")
    print(f"   Model:  gemma-4-26B-A4B-it-ultra-uncensored-heretic-Q5_K_S.gguf")

    try:
        test_infinite_retry_signature()
        test_happy_path()
        test_recovery_after_failures()
        test_forced_failure_with_cap()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
        sys.exit(130)

    print("\n" + "=" * 60)
    print("  🎉 All tests complete")
    print("=" * 60)
