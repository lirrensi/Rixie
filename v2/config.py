# FILE: v2/config.py
# PURPOSE: Load V2 configuration defaults and repository overrides from config.yaml.
# OWNS: V2-specific config defaults for blocking and parallel execution.
# EXPORTS: load_repo_config, load_v2_config.
# DOCS: config.yaml, v2/process.py, v2/pipeline.py

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"

DEFAULT_V2_CONFIG: dict = {
    "v2": {
        "defaults": {
            "base_url": None,
            "api_key": None,
            "model": None,
            "temperature": None,
            "request_timeout_seconds": 300,
            "thinking": True,
        },
        "profiles": {
            "mini_summary": {
                "prompt_file": "prompt_block_mini_summary.md",
                "model": None,
                "temperature": 0.1,
                "request_timeout_seconds": 300,
                "thinking": False,
                # "base_url": None,
                # "api_key": None,
            },
            "cartography": {
                "prompt_file": "prompt_cartographer_map.md",
                "model": None,
                "temperature": 0.1,
                "request_timeout_seconds": 300,
                "thinking": True,
                # "base_url": None,
                # "api_key": None,
            },
            "chapter_short": {
                "prompt_file": "prompt_chapter_short.md",
                "model": None,
                "temperature": 0.2,
                "request_timeout_seconds": 300,
                "thinking": True,
                # "base_url": None,
                # "api_key": None,
            },
            "chapter_long": {
                "prompt_file": "prompt_chapter_detailed.md",
                "model": None,
                "temperature": 0.25,
                "request_timeout_seconds": 300,
                "thinking": True,
                # "base_url": None,
                # "api_key": None,
            },
        },
        "blocking": {
            "encoding_model": "gpt-4o-mini",
            "target_tokens": 1024,
            "min_tokens": 768,
            "max_tokens": 1280,
        },
        "execution": {
            "parallel_calls": 8,
        },
    }
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_repo_config(config_path: Path | None = None) -> dict:
    config_path = config_path or CONFIG_PATH
    if config_path.exists():
        with config_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_v2_config(config_path: Path | None = None) -> dict:
    config_path = config_path or CONFIG_PATH
    loaded = load_repo_config(config_path)
    merged = _deep_merge(DEFAULT_V2_CONFIG, loaded)
    return merged.get("v2", deepcopy(DEFAULT_V2_CONFIG["v2"]))


def resolve_profile(v2_config: dict, profile_name: str) -> dict:
    defaults = deepcopy(v2_config.get("defaults", {}))
    profile = deepcopy(v2_config.get("profiles", {}).get(profile_name, {}))
    return _deep_merge(defaults, profile)
