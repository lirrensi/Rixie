# FILE: v1/_paths.py
# PURPOSE: Resolve V1 asset and workspace paths after the legacy code moved under v1/.
# OWNS: Shared path discovery for config, prompts, templates, input, and output folders.
# EXPORTS: REPO_ROOT, V1_ROOT, resolve_asset_path, resolve_config_path.
# DOCS: README.md

from pathlib import Path

V1_ROOT = Path(__file__).resolve().parent
REPO_ROOT = V1_ROOT.parent


def resolve_asset_path(filename: str) -> Path:
    """Resolve a V1 asset, preferring the v1 copy and falling back to repo root."""
    candidates = [V1_ROOT / filename, REPO_ROOT / filename]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_config_path() -> Path:
    """Resolve the repository-level config file used by the legacy pipeline."""
    return REPO_ROOT / "config.yaml"
