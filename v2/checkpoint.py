# FILE: v2/checkpoint.py
# PURPOSE: Periodic checkpoint saves during long-running pipeline stages so
#          progress survives crashes without hammering the disk on every step.
# OWNS: CheckpointTracker for frequency throttling, save_artifact_sync for
#       durable writes.
# EXPORTS: CheckpointTracker, save_artifact_sync.
# DOCS: v2/cartographer.py, v2/summarizer.py, v2/process.py

"""
Checkpoint tracking for the V2 pipeline.

The pipeline has stages with very different granularity:
  - Mini-summaries: hundreds of small LLM calls (one per block)
  - Chapter summaries: tens of LLM calls (two per chapter)

A naive "save after every unit" approach causes hundreds of full-YAML writes
for a typical book, wearing SSDs for no good reason.  A "save only at stage
boundaries" approach loses all progress if the process crashes mid-stage.

CheckpointTracker splits the difference: save every N% of total work,
configurable via config.yaml → v2.execution.checkpoint_pct (default 5 %).
On resume, pending work is detected automatically (fields still None), so
resume-cost is at most one checkpoint interval of redundant LLM calls.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from v2.schema import BookArtifact


# ── Checkpoint throttle ──────────────────────────────────────────────────────

class CheckpointTracker:
    """Decides how often to save so you don't spam the disk.
    
    Usage::
    
        ck = CheckpointTracker(100, every_pct=5.0)  # 5% of 100 = every 5 units
        for i in range(100):
            ... do work ...
            if ck.should_save():
                save_artifact_sync(artifact, yaml_path)
    
    ``should_save()`` increments the counter and returns True when the next
    checkpoint interval is crossed.  Never misses the final unit (always True
    on the very last one).
    
    Args:
        total: Total number of units to process.
        every_pct: Save every N% of progress (default 5%).
        min_interval: Minimum units between saves (default 5). Prevents
            aggressive saving when total is small (e.g. 18 chapters at 5%
            would save every 1 chapter — min_interval=5 makes it every 5).
    
    Edge cases:
      - total <= min_interval → save every unit (you're almost done anyway)
      - every_pct very low → interval still at least min_interval
      - total large → predictable interval (e.g. 5% → every 25 for 500 blocks)
    """

    def __init__(self, total: int, *, every_pct: float = 5.0, min_interval: int = 5):
        self.total = max(total, 1)
        self.processed: int = 0
        # How many units between saves; never less than min_interval (or 1 for tiny totals)
        pct_interval = round(self.total * every_pct / 100.0)
        self._interval: int = max(min_interval, pct_interval) if self.total > min_interval else 1
        self._next_save_at: int = self._interval

    @property
    def interval(self) -> int:
        return self._interval

    def should_save(self) -> bool:
        """Mark one unit processed.  Return True if this hit a checkpoint."""
        self.processed += 1
        # Always save on the very last unit so resume picks up exactly here
        if self.processed >= self.total:
            return True
        if self.processed >= self._next_save_at:
            self._next_save_at = self.processed + self._interval
            return True
        return False

    @property
    def progress_pct(self) -> float:
        """Percentage of total units processed (0–100)."""
        return self.processed / self.total * 100.0


# ── Durable artifact save ────────────────────────────────────────────────────

def save_artifact_sync(artifact: BookArtifact, yaml_path: Path) -> None:
    """Write the full artifact to disk and wait until the OS confirms it.

    Uses fsync (not just flush) for crash-safe durability.  No verify re-read
    — fsync returning without error *is* the durability guarantee.
    """
    yaml_content = yaml.safe_dump(
        artifact.model_dump(mode="json"),
        sort_keys=False,
        allow_unicode=True,
    )
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)
        f.flush()
        os.fsync(f.fileno())
