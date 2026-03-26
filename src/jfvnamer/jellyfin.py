"""Jellyfin naming convention rules.

Implements the naming conventions documented at:
- TV Shows: https://jellyfin.org/docs/general/server/media/shows
- Movies: https://jellyfin.org/docs/general/server/media/movies

The main entry point is ``build_target_path()``, which returns a relative
path (from the media library root) for a given parsed file and TVDB metadata.
"""

from __future__ import annotations

import datetime
from pathlib import PurePosixPath

from jfvnamer.models import (
    NamingConfig,
    ParsedFile,
    TVDBEpisode,
    TVDBMovieDetails,
    TVDBSeriesDetails,
)


# ---------------------------------------------------------------------------
# Filename sanitization
# ---------------------------------------------------------------------------

# Characters illegal on Windows/NTFS and generally problematic for media servers.
_DEFAULT_STRIP = frozenset('?*"<>|')


def sanitize_name(
    name: str,
    *,
    replace_colon_with: str = " -",
    replace_slash_with: str = "-",
    strip_characters: frozenset[str] | list[str] = _DEFAULT_STRIP,
) -> str:
    """Remove or replace characters that are invalid on common filesystems.

    - Colons are replaced with *replace_colon_with* (default ``" -"``).
    - Slashes are replaced with *replace_slash_with* (default ``"-"``).
    - Characters in *strip_characters* are removed entirely.
    - Trailing dots and spaces are stripped (Windows compatibility).
    """
    name = name.replace(":", replace_colon_with)
    name = name.replace("/", replace_slash_with)
    for ch in strip_characters:
        if ch == ":":
            continue  # already handled
        name = name.replace(ch, "")
    return name.rstrip(". ")


# ---------------------------------------------------------------------------
# TV show naming helpers
# ---------------------------------------------------------------------------


def build_series_folder_name(
    series_name: str,
    *,
    year: str | int | None = None,
    naming: NamingConfig | None = None,
) -> str:
    """Build the series root folder name, e.g. ``Series Name (2005)``."""
    cfg = naming or NamingConfig()
    clean = sanitize_name(
        series_name,
        replace_colon_with=cfg.replace_colon_with,
        replace_slash_with=cfg.replace_slash_with,
        strip_characters=cfg.strip_characters,
    )
    if year:
        return cfg.series_format.format(series_name=clean, year=year)
    # No year — strip the parenthetical from the format
    return clean


def build_season_folder_name(
    season_number: int | None,
    *,
    naming: NamingConfig | None = None,
) -> str:
    """Build the season folder name, e.g. ``Season 01``.

    If *season_number* is ``None`` (e.g. absolute-numbered anime), defaults
    to ``Season 01``.
    """
    cfg = naming or NamingConfig()
    season = season_number if season_number is not None else 1
    return cfg.season_format.format(season=season)


def build_episode_filename(
    series_name: str,
    season_number: int,
    episode_numbers: list[int],
    file_extension: str,
    *,
    episode_title: str | None = None,
    naming: NamingConfig | None = None,
) -> str:
    """Build the episode filename.

    Handles single episodes, multi-episodes, and episodes without a title.
    """
    cfg = naming or NamingConfig()
    clean = sanitize_name(
        series_name,
        replace_colon_with=cfg.replace_colon_with,
        replace_slash_with=cfg.replace_slash_with,
        strip_characters=cfg.strip_characters,
    )

    if len(episode_numbers) > 1:
        title = (
            sanitize_name(
                episode_title,
                replace_colon_with=cfg.replace_colon_with,
                strip_characters=cfg.strip_characters,
            )
            if episode_title
            else None
        )
        if title:
            filename = cfg.multi_episode_format.format(
                series_name=clean,
                season=season_number,
                episode=episode_numbers[0],
                episode_end=episode_numbers[-1],
                episode_title=title,
            )
        else:
            filename = cfg.multi_episode_format_no_title.format(
                series_name=clean,
                season=season_number,
                episode=episode_numbers[0],
                episode_end=episode_numbers[-1],
            )
    elif episode_title:
        title = sanitize_name(
            episode_title,
            replace_colon_with=cfg.replace_colon_with,
            strip_characters=cfg.strip_characters,
        )
        filename = cfg.episode_format.format(
            series_name=clean,
            season=season_number,
            episode=episode_numbers[0],
            episode_title=title,
        )
    else:
        filename = cfg.episode_format_no_title.format(
            series_name=clean,
            season=season_number,
            episode=episode_numbers[0],
        )

    return filename + file_extension


def build_date_episode_filename(
    series_name: str,
    date: datetime.date,
    file_extension: str,
    *,
    naming: NamingConfig | None = None,
) -> str:
    """Build a date-based episode filename (fallback when TVDB lookup fails)."""
    cfg = naming or NamingConfig()
    clean = sanitize_name(
        series_name,
        replace_colon_with=cfg.replace_colon_with,
        replace_slash_with=cfg.replace_slash_with,
        strip_characters=cfg.strip_characters,
    )
    filename = cfg.date_episode_fallback.format(
        series_name=clean, date=date.isoformat()
    )
    return filename + file_extension


# ---------------------------------------------------------------------------
# Movie naming helpers
# ---------------------------------------------------------------------------


def build_movie_folder_name(
    title: str,
    *,
    year: str | int | None = None,
    naming: NamingConfig | None = None,
) -> str:
    """Build the movie folder name, e.g. ``Inception (2010)``."""
    cfg = naming or NamingConfig()
    clean = sanitize_name(
        title,
        replace_colon_with=cfg.replace_colon_with,
        replace_slash_with=cfg.replace_slash_with,
        strip_characters=cfg.strip_characters,
    )
    if year:
        return cfg.movie_folder_format.format(title=clean, year=year)
    return clean


def build_movie_filename(
    title: str,
    file_extension: str,
    *,
    year: str | int | None = None,
    naming: NamingConfig | None = None,
) -> str:
    """Build the movie filename, e.g. ``Inception (2010).mkv``."""
    cfg = naming or NamingConfig()
    clean = sanitize_name(
        title,
        replace_colon_with=cfg.replace_colon_with,
        replace_slash_with=cfg.replace_slash_with,
        strip_characters=cfg.strip_characters,
    )
    if year:
        name = cfg.movie_file_format.format(title=clean, year=year)
    else:
        name = clean
    return name + file_extension


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------


def build_target_path(
    parsed: ParsedFile,
    *,
    series: TVDBSeriesDetails | None = None,
    episode: TVDBEpisode | None = None,
    movie: TVDBMovieDetails | None = None,
    naming: NamingConfig | None = None,
) -> str:
    """Build the full relative target path for a file.

    The caller provides either (*series* + *episode*) for TV, or *movie*
    for movies. The returned path is relative to the library root.

    For TV:
        ``Series Name (Year)/Season XX/Series Name - SXXEXX - Title.ext``

    For movies:
        ``Title (Year)/Title (Year).ext``
    """
    if movie is not None:
        return _build_movie_path(parsed, movie, naming)
    if series is not None:
        return _build_tv_path(parsed, series, episode, naming)

    raise ValueError(
        "build_target_path requires either 'movie' or 'series' metadata"
    )


# ---------------------------------------------------------------------------
# Internal path builders
# ---------------------------------------------------------------------------


def _build_tv_path(
    parsed: ParsedFile,
    series: TVDBSeriesDetails,
    episode: TVDBEpisode | None,
    naming: NamingConfig | None,
) -> str:
    year = series.year
    series_folder = build_series_folder_name(series.name, year=year, naming=naming)

    if episode is not None:
        season = episode.season_number
        season_folder = build_season_folder_name(season, naming=naming)
        filename = build_episode_filename(
            series.name,
            season,
            [episode.episode_number],
            parsed.file_extension,
            episode_title=episode.name,
            naming=naming,
        )
    elif parsed.date is not None:
        # Date-based episode without a TVDB episode match — use date fallback
        year_season = parsed.date.year
        season_folder = build_season_folder_name(year_season, naming=naming)
        filename = build_date_episode_filename(
            series.name, parsed.date, parsed.file_extension, naming=naming
        )
    else:
        # No episode match — use parsed season/episode if available
        season = parsed.season_number if parsed.season_number is not None else 1
        season_folder = build_season_folder_name(season, naming=naming)
        episodes = parsed.episode_numbers or [1]
        filename = build_episode_filename(
            series.name,
            season,
            episodes,
            parsed.file_extension,
            episode_title=parsed.episode_name,
            naming=naming,
        )

    return str(PurePosixPath(series_folder) / season_folder / filename)


def _build_movie_path(
    parsed: ParsedFile,
    movie: TVDBMovieDetails,
    naming: NamingConfig | None,
) -> str:
    year = movie.year
    folder = build_movie_folder_name(movie.name, year=year, naming=naming)
    filename = build_movie_filename(
        movie.name, parsed.file_extension, year=year, naming=naming
    )
    return str(PurePosixPath(folder) / filename)
