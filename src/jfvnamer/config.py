"""TOML config loading with layered merge logic.

Resolution order (highest priority wins):
1. CLI flags (applied by the caller after loading)
2. User config at ~/.config/jfvnamer/config.toml
3. Built-in defaults from config/default.toml
"""

from __future__ import annotations

import sys
from importlib.resources import files

try:
    from importlib.resources.abc import Traversable  # Python 3.11+
except ImportError:
    # type: ignore[no-redef]  # Python 3.10–3.11
    from importlib.abc import Traversable
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[import-untyped,no-redef]

from jfvnamer.models import AppConfig

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: Traversable = files(
    "jfvnamer").joinpath("config/default.toml")
USER_CONFIG_DIR = Path.home() / ".config" / "jfvnamer"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.toml"


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------


def _load_toml(path: Path | Traversable) -> dict[str, Any]:
    """Load a TOML file and return its contents as a dict."""
    with path.open("rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*.

    Scalar values in *override* replace those in *base*.
    Nested dicts are merged recursively.
    """
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(
    user_config_path: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> AppConfig:
    """Load and merge the full application config.

    Parameters
    ----------
    user_config_path:
        Path to the user config file.  ``None`` means use the default
        location (``~/.config/jfvnamer/config.toml``).  If the file does
        not exist, only built-in defaults are used.
    cli_overrides:
        A nested dict of overrides from CLI flags (e.g.
        ``{"general": {"verbose": True}}``).  Applied last (highest priority).
    """
    # 1. Built-in defaults
    if _DEFAULT_CONFIG.is_file():
        defaults = _load_toml(_DEFAULT_CONFIG)
    else:
        defaults = {}

    # 2. User config
    user_path = user_config_path if user_config_path is not None else USER_CONFIG_PATH
    if user_path.exists():
        user = _load_toml(user_path)
    else:
        user = {}

    # 3. Merge defaults ← user
    merged = _deep_merge(defaults, user)

    # 4. Apply CLI overrides
    if cli_overrides:
        merged = _deep_merge(merged, cli_overrides)

    # 5. Validate with Pydantic
    return AppConfig.model_validate(merged)


def generate_user_config_template() -> str:
    """Return a commented TOML template suitable for a new user config file."""
    return """\
# jfvnamer configuration
# Place this file at ~/.config/jfvnamer/config.toml
#
# Values shown below are the built-in defaults.
# Uncomment and modify only what you need to change.

[general]
# series_root = "."           # Where to output renamed TV series files
# movies_root = "."           # Where to output renamed movie files
# action = "move"             # "move", "copy", or "dryrun"
# recursive = true            # Scan subdirectories
# verbose = false

[tvdb]
api_key = ""                  # Required — get yours at https://thetvdb.com/api-information
# cache_ttl_days = 7
# language = "eng"

[naming]
# series_format = "{series_name} ({year})"
# season_format = "Season {season:02d}"
# episode_format = "{series_name} - S{season:02d}E{episode:02d} - {episode_title}"
# episode_format_no_title = "{series_name} - S{season:02d}E{episode:02d}"
# multi_episode_format = "{series_name} - S{season:02d}E{episode:02d}-E{episode_end:02d} - {episode_title}"
# multi_episode_format_no_title = "{series_name} - S{season:02d}E{episode:02d}-E{episode_end:02d}"
# date_episode_fallback = "{series_name} - {date}"
# movie_folder_format = "{title} ({year})"
# movie_file_format = "{title} ({year})"
# replace_colon_with = " -"
# strip_characters = ["?", "*", "\\"", "<", ">", "|"]
"""


class MissingApiKeyError(Exception):
    """Raised when the TVDB API key is not configured."""


def validate_api_key(config: AppConfig) -> None:
    """Raise MissingApiKeyError if the TVDB API key is not configured."""
    if not config.tvdb.api_key:
        raise MissingApiKeyError(
            "TVDB API key is not configured.\n"
            "\n"
            "To use TVDB lookups, set your API key in one of these ways:\n"
            "  1. Add it to ~/.config/jfvnamer/config.toml:\n"
            '     [tvdb]\n'
            '     api_key = "your-key-here"\n'
            "\n"
            "  2. Create a config file with: jfvnamer config init\n"
            "\n"
            "Get a free API key at https://thetvdb.com/api-information\n"
            "\n"
            "If you only want to test filename parsing, use: jfvnamer parse <path>"
        )
