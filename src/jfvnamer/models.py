"""Pydantic models for parsed files, episodes, movies, config, etc."""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class MediaType(str, Enum):
    TV = "tv"
    MOVIE = "movie"
    UNKNOWN = "unknown"


class ParsedFile(BaseModel):
    """Result of parsing a video filename."""

    title: str = Field(description="Cleaned series or movie name")
    media_type: MediaType = Field(description="Detected media type")
    season_number: Optional[int] = Field(default=None, description="Season number if detected")
    episode_numbers: Optional[list[int]] = Field(default=None, description="Episode number(s)")
    episode_name: Optional[str] = Field(default=None, description="Episode title if present")
    year: Optional[int] = Field(default=None, description="Year if detected")
    date: Optional[datetime.date] = Field(default=None, description="Air date for date-based episodes")
    quality: Optional[str] = Field(default=None, description="Quality tag (720p, 1080p, etc.)")
    source: Optional[str] = Field(default=None, description="Source tag (bluray, hdtv, etc.)")
    file_extension: str = Field(description="File extension including dot")
    original_filename: str = Field(description="The original filename before parsing")


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class GeneralConfig(BaseModel):
    library_root: str = "."
    action: Literal["move", "copy", "dryrun"] = "move"
    recursive: bool = True
    verbose: bool = False


class TvdbConfig(BaseModel):
    api_key: str = ""
    default_order: Literal["aired", "dvd", "absolute"] = "aired"
    cache_ttl_days: int = 7
    language: str = "eng"


class NamingConfig(BaseModel):
    series_format: str = "{series_name} ({year})"
    season_format: str = "Season {season:02d}"
    episode_format: str = "{series_name} - S{season:02d}E{episode:02d} - {episode_title}"
    episode_format_no_title: str = "{series_name} - S{season:02d}E{episode:02d}"
    multi_episode_format: str = "{series_name} - S{season:02d}E{episode:02d}-E{episode_end:02d} - {episode_title}"
    date_episode_fallback: str = "{series_name} - {date}"
    movie_folder_format: str = "{title} ({year})"
    movie_file_format: str = "{title} ({year})"
    replace_colon_with: str = " -"
    strip_characters: list[str] = Field(default_factory=lambda: ["?", "*", '"', "<", ">", "|"])


class PatternsConfig(BaseModel):
    patterns_prepend: list[str] = Field(default_factory=list)
    patterns_append: list[str] = Field(default_factory=list)
    patterns_replace: Optional[list[str]] = None


class AppConfig(BaseModel):
    """Full application configuration, assembled from layered TOML sources."""

    general: GeneralConfig = Field(default_factory=GeneralConfig)
    tvdb: TvdbConfig = Field(default_factory=TvdbConfig)
    naming: NamingConfig = Field(default_factory=NamingConfig)
    patterns: PatternsConfig = Field(default_factory=PatternsConfig)

    @model_validator(mode="after")
    def _check_api_key_hint(self) -> AppConfig:
        """Attach a flag indicating whether the API key is missing.

        We don't raise here — the CLI checks this before operations that need TVDB.
        """
        return self
