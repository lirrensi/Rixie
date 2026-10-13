"""Force a real, hard network failure to prove the infinite-retry policy works.

The previous test couldn't trigger failures because llama.cpp fell back to
a default model. This time we point at a port nothing is listening on,
which gives us a real connection refused error every time. We cap the
test at 5 attempts so we don't wait forever, but we time it to prove
the backoff schedule is working (1s, 2s, 4s, 8s ...).

Expected output:
  - 5 attempts
  - Each fails with APIConnectionError (connection refused)
  - Total time ~ 1+2+4+8 = 15s of backoff plus 5 quick connect attempts
  - Final outcome: RuntimeError raised (because we hit the cap)
"""

import time
from pydantic import BaseModel
from v2.pipeline import structured_completion


class FakeResult(BaseModel):
    answer: str


class DeadSettings:
    """Point at a port nothing is listening on."""
    api_base = "http://localhost:9/v1"  # port 9 = discard, usually nothing there
    api_key = "local"
    model = "anything"
    temperature = 0.2
    thinking = False
    timeout = 3  # short timeout so each attempt fails fast


def main() -> None:
    print("🔌 TEST: Hard network failure (port 9, nothing listening)")
    print("   Expected: 5 attempts, each fails fast, total ~15s of backoff")
    print("   Capped at max_retries=5 so we don't actually wait forever\n")

    msgs = [{"role": "user", "content": "hi"}]

    start = time.time()
    try:
        result = structured_completion(DeadSettings(), msgs, FakeResult, max_retries=5)
        print(f"   ❌ UNEXPECTED success: {result}")
    except RuntimeError as e:
        elapsed = time.time() - start
        print(f"\n   ✅ RuntimeError raised after {elapsed:.1f}s")
        print(f"      {str(e)[:200]}")

        # Sanity check the elapsed time proves backoff was honored
        if 10.0 <= elapsed <= 60.0:
            print(f"   ✅ Elapsed time is in expected backoff range — retry loop is working")
        else:
            print(f"   ⚠️  Elapsed time unexpected — check backoff schedule")


if __name__ == "__main__":
    main()
