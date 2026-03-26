"""Pydantic models for parsed files, episodes, movies, config, etc."""

from __future__ import annotations

import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ParsedFile(BaseModel):
    """Result of parsing a video filename."""

    title: str = Field(description="Cleaned series or movie name")
    season_number: Optional[int] = Field(
        default=None, description="Season number if detected")
    episode_numbers: Optional[list[int]] = Field(
        default=None, description="Episode number(s)")
    episode_name: Optional[str] = Field(
        default=None, description="Episode title if present")
    date: Optional[datetime.date] = Field(
        default=None, description="Air date for date-based episodes")
    file_extension: str = Field(description="File extension including dot")
    original_filename: str = Field(
        description="The original filename before parsing")


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class GeneralConfig(BaseModel):
    series_root: str = "."
    movies_root: str = "."
    action: Literal["move", "copy", "dryrun"] = "move"
    recursive: bool = True
    verbose: bool = False


class TvdbConfig(BaseModel):
    api_key: str = ""
    cache_ttl_days: int = 7
    language: str = "eng"


class NamingConfig(BaseModel):
    series_format: str = "{series_name} ({year})"
    season_format: str = "Season {season:02d}"
    episode_format: str = "{series_name} - S{season:02d}E{episode:02d} - {episode_title}"
    episode_format_no_title: str = "{series_name} - S{season:02d}E{episode:02d}"
    multi_episode_format: str = "{series_name} - S{season:02d}E{episode:02d}-E{episode_end:02d} - {episode_title}"
    multi_episode_format_no_title: str = "{series_name} - S{season:02d}E{episode:02d}-E{episode_end:02d}"
    date_episode_fallback: str = "{series_name} - {date}"
    movie_folder_format: str = "{title} ({year})"
    movie_file_format: str = "{title} ({year})"
    replace_colon_with: str = " -"
    replace_slash_with: str = "-"
    strip_characters: list[str] = Field(
        default_factory=lambda: ["?", "*", '"', "<", ">", "|"])


class AppConfig(BaseModel):
    """Full application configuration, assembled from layered TOML sources."""

    general: GeneralConfig = Field(default_factory=GeneralConfig)
    tvdb: TvdbConfig = Field(default_factory=TvdbConfig)
    naming: NamingConfig = Field(default_factory=NamingConfig)


# ---------------------------------------------------------------------------
# TVDB API models
# ---------------------------------------------------------------------------


class TVDBSearchResult(BaseModel):
    """A single result from the TVDB /search endpoint."""

    tvdb_id: int = Field(description="TVDB entity ID")
    name: str = Field(description="Title of the series or movie")
    type: str = Field(description="'series' or 'movie'")
    year: Optional[str] = Field(
        default=None, description="Year of release/premiere")
    overview: Optional[str] = Field(default=None, description="Short synopsis")
    genres: list[str] = Field(
        default_factory=list, description="Genre tags")


class TVDBSeriesDetails(BaseModel):
    """Details from /series/{id}/extended."""

    tvdb_id: int
    name: str
    year: Optional[str] = None
    status: Optional[str] = None
    season_types: list[str] = Field(
        default_factory=list, description="Available ordering types")


class TVDBEpisode(BaseModel):
    """A single episode from TVDB."""

    tvdb_id: int
    name: Optional[str] = None
    season_number: int
    episode_number: int
    aired: Optional[str] = None
    overview: Optional[str] = None


class TVDBMovieDetails(BaseModel):
    """Details from /movies/{id}/extended."""

    tvdb_id: int
    name: str
    year: Optional[str] = None
    runtime: Optional[int] = None


class TVDBNameTranslation(BaseModel):
    """nameTranslation inside of translations in series/{id}/extended?meta=translations&short=true response"""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    language: str
    is_primary: Optional[bool] = Field(default=None, alias="isPrimary")

# ---------------------------------------------------------------------------
# Rename engine models
# ---------------------------------------------------------------------------


VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mkv", ".avi", ".mp4", ".m4v", ".ts", ".wmv", ".flv", ".mov"}
)

SUBTITLE_EXTENSIONS: frozenset[str] = frozenset(
    {".srt", ".sub", ".ass", ".ssa", ".idx"}
)


class RenameAction(BaseModel):
    """A single planned rename/move/copy operation."""

    source: str = Field(description="Absolute path to the source file")
    destination: str = Field(description="Absolute path to the target file")
    action: Literal["move", "copy", "dryrun"] = Field(
        description="Action to perform")
    is_subtitle: bool = Field(
        default=False, description="Whether this is a companion subtitle file")


class RenameResult(BaseModel):
    """Outcome of executing a single rename action."""

    source: str
    destination: str
    action: Literal["move", "copy", "dryrun"]
    success: bool = True
    error: Optional[str] = None


class UndoLogEntry(BaseModel):
    """A log of rename operations that can be reversed."""

    timestamp: datetime.datetime = Field(description="Timestamp of the operation")
    actions: list[RenameResult] = Field(default_factory=list)
