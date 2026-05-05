# FILE: v1/__init__.py
# PURPOSE: Expose the legacy V1 pipeline as an isolated package behind compatibility wrappers.
# OWNS: V1 package surface and package-level metadata.
# EXPORTS: REPO_ROOT, V1_ROOT - resolved legacy path anchors.
# DOCS: README.md

from pathlib import Path

V1_ROOT = Path(__file__).resolve().parent
REPO_ROOT = V1_ROOT.parent

__all__ = ["REPO_ROOT", "V1_ROOT"]
