"""Pydantic models for parsed files, episodes, movies, config, etc."""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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
