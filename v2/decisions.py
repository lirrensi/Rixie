# FILE: v2/decisions.py
# PURPOSE: Minimal /v1/systemone client for binary pre-gates (fail-open).
# OWNS: DecisionSettings, batched noul scoring over plain HTTP (stdlib only).
# EXPORTS: DecisionSettings, DecisionError, noul_batch.
# DOCS: v2/cartographer.py, config.yaml
#
# FAIL-OPEN CONTRACT: any transport/shape error raises DecisionError and the
# caller MUST fall back to the generative path. No retries here — the
# generative path is the retry.

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


class DecisionError(RuntimeError):
    """Decision endpoint unusable; caller must fail open to generation."""


@dataclass
class DecisionSettings:
    base_url: str = "http://localhost:58081/v1"
    model: str | None = None  # single-model servers (llama.cpp) ignore this
    timeout: int = 120
    enabled: bool = True

    @classmethod
    def disabled(cls) -> "DecisionSettings":
        """Explicitly-off settings: gate skipped without needing a server."""
        return cls(base_url="", enabled=False)

    @property
    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/systemone"


def noul_batch(
    settings: DecisionSettings,
    state: dict[str, str],
    instructions: str,
    criteria_true: str,
    criteria_false: str,
) -> dict[str, float]:
    """Score one noul question per state field in a single request.

    Returns {state_key: P(yes)}. Raises DecisionError on ANY failure.
    Each question binds to its field explicitly (``Field `key`: ...``)
    so batched questions never answer about the wrong text.
    """
    if not state:
        return {}
    questions = {
        f"q__{key}": {
            "type": "noul",
            "instructions": f"Field `{key}`: {instructions}",
            "criteria": {"true": criteria_true, "false": criteria_false},
        }
        for key in state
    }
    body: dict = {"state": state, "questions": questions}
    if settings.model:
        body["model"] = settings.model
    try:
        req = urllib.request.Request(
            settings.endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=settings.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        answers = payload.get("answers", {})
        out: dict[str, float] = {}
        for key in state:
            ans = answers.get(f"q__{key}", {})
            score = ans.get("noul")
            if not isinstance(score, (int, float)) or not 0.0 <= score <= 1.0:
                raise DecisionError(f"bad noul for {key}: {ans!r}"[:200])
            out[key] = float(score)
        return out
    except DecisionError:
        raise
    except Exception as e:
        raise DecisionError(f"{type(e).__name__}: {e}"[:300]) from e
