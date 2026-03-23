"""Filename parsing engine using regex patterns.

Ported from tvnamer's battle-tested filename patterns, extended with
movie detection and quality/source extraction.
"""

from __future__ import annotations

import datetime
import os
import re
from typing import Optional

from jfvnamer.models import MediaType, ParsedFile

# Quality tags recognized in filenames
QUALITY_PATTERNS: list[str] = [
    r"2160p", r"1080p", r"720p", r"480p", r"576p",
    r"4[Kk]", r"UHD",
]

# Source tags recognized in filenames
SOURCE_PATTERNS: list[str] = [
    r"[Bb][Ll][Uu]-?[Rr][Aa][Yy]", r"[Bb][Dd][Rr][Ii][Pp]",
    r"[Dd][Vv][Dd][Rr][Ii][Pp]", r"[Dd][Vv][Dd]",
    r"[Hh][Dd][Tt][Vv]", r"[Ww][Ee][Bb]-?[Dd][Ll]",
    r"[Ww][Ee][Bb][Rr][Ii][Pp]", r"[Ww][Ee][Bb]",
    r"[Hh][Dd][Rr][Ii][Pp]",
    r"[Rr]emastered",
]

QUALITY_RE = re.compile(r"(?:^|[\.\-_ ])(" + "|".join(QUALITY_PATTERNS) + r")(?:[\.\-_ ]|$)", re.IGNORECASE)
SOURCE_RE = re.compile(r"(?:^|[\.\-_ ])(" + "|".join(SOURCE_PATTERNS) + r")(?:[\.\-_ ]|$)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# TV patterns — tried in order, first match wins.
# Ported from tvnamer with adaptations for named groups we use.
# ---------------------------------------------------------------------------

TV_PATTERNS: list[tuple[str, re.Pattern[str]]] = []


def _add_tv(name: str, pattern: str) -> None:
    TV_PATTERNS.append((name, re.compile(pattern, re.VERBOSE | re.IGNORECASE)))


# --- Multi-episode patterns (most specific first) ---

# [group] Show - 01-02 [crc]  (anime fansub multi-ep)
_add_tv(
    "anime_group_multi",
    r"""
    ^\[(?P<group>.+?)\][ ]?
    (?P<seriesname>.*?)[ ]?[-_][ ]?
    (?P<episodenumberstart>\d+)
    [-_](?P<episodenumberend>\d+)
    (?:.*\[(?P<crc>.+?)\])?
    [^/]*$
    """,
)

# foo s01e23 s01e24 s01e25
_add_tv(
    "s_ep_repeated",
    r"""
    ^((?P<seriesname>.+?)[ ._\-])?
    [Ss](?P<seasonnumber>[0-9]+)
    [.\- ]?
    [Ee](?P<episodenumberstart>[0-9]+)
    ([.\- ]+[Ss](?P=seasonnumber)[.\- ]?[Ee][0-9]+)*
    ([.\- ]+[Ss](?P=seasonnumber)[.\- ]?[Ee](?P<episodenumberend>[0-9]+))
    [^/]*$
    """,
)

# foo.s01e23e24
_add_tv(
    "s_ep_multi_e",
    r"""
    ^((?P<seriesname>.+?)[ ._\-])?
    [Ss](?P<seasonnumber>[0-9]+)
    [.\- ]?
    [Ee](?P<episodenumberstart>[0-9]+)
    ([.\- ]?[Ee][0-9]+)*
    [.\- ]?[Ee](?P<episodenumberend>[0-9]+)
    [^/]*$
    """,
)

# foo.1x23 1x24 1x25
_add_tv(
    "nx_multi_space",
    r"""
    ^((?P<seriesname>.+?)[ ._\-])?
    (?P<seasonnumber>[0-9]+)
    [xX](?P<episodenumberstart>[0-9]+)
    ([ ._\-]+(?P=seasonnumber)[xX][0-9]+)*
    ([ ._\-]+(?P=seasonnumber)[xX](?P<episodenumberend>[0-9]+))
    [^/]*$
    """,
)

# foo.1x23x24
_add_tv(
    "nx_multi_x",
    r"""
    ^((?P<seriesname>.+?)[ ._\-])?
    (?P<seasonnumber>[0-9]+)
    [xX](?P<episodenumberstart>[0-9]+)
    ([xX][0-9]+)*
    [xX](?P<episodenumberend>[0-9]+)
    [^/]*$
    """,
)

# foo.s01e23-24
_add_tv(
    "s_ep_dash_range",
    r"""
    ^((?P<seriesname>.+?)[ ._\-])?
    [Ss](?P<seasonnumber>[0-9]+)
    [.\- ]?
    [Ee](?P<episodenumberstart>[0-9]+)
    ([\-][Ee]?[0-9]+)*
    [\-][Ee]?(?P<episodenumberend>[0-9]+)
    [.\- ]
    [^/]*$
    """,
)

# foo.1x23-24
_add_tv(
    "nx_dash_range",
    r"""
    ^((?P<seriesname>.+?)[ ._\-])?
    (?P<seasonnumber>[0-9]+)
    [xX](?P<episodenumberstart>[0-9]+)
    ([\-+][0-9]+)*
    [\-+](?P<episodenumberend>[0-9]+)
    ([.\-+ ].*|$)
    """,
)

# foo.[1x09-11]
_add_tv(
    "nx_bracket_range",
    r"""
    ^(?P<seriesname>.+?)[ ._\-]
    \[
    \s*(?P<seasonnumber>[0-9]+)
    [xX](?P<episodenumberstart>[0-9]+)
    ([\-+]\s*[0-9]+)*
    [\-+]\s*(?P<episodenumberend>[0-9]+)
    \]
    [^/]*$
    """,
)

# Show.Name.Part.1.and.Part.2
_add_tv(
    "part_multi",
    r"""
    ^(?P<seriesname>.+?)
    [ ._\-]
    (?:part|pt)?[._ \-]
    (?P<episodenumberstart>[0-9]+)
    (?:[ ._\-](?:and|&|to)[ ._\-](?:part|pt)?[ ._\-](?:[0-9]+))*
    [ ._\-](?:and|&|to)
    [ ._\-]?(?:part|pt)?
    [ ._\-](?P<episodenumberend>[0-9]+)
    [._ \-][^/]*$
    """,
)

# --- Single-episode patterns ---

# [group] Show - 01 [crc]  (anime fansub)
_add_tv(
    "anime_group_single",
    r"""
    ^\[(?P<group>.+?)\][ ]?
    (?P<seriesname>.*)
    [ ]?[-_][ ]?
    (?P<episodenumber>\d+)
    (?:.*\[(?P<crc>.+?)\])?
    [^/]*$
    """,
)

# Standard SxxExx — the most common TV pattern
# Breaking Bad - S01E01 - Pilot
# breaking.bad.s01e01.pilot.720p.bluray
_add_tv(
    "standard_se",
    r"""
    ^((?P<seriesname>.+?)[ ._\-])?
    [Ss](?P<seasonnumber>[0-9]+)
    [.\- ]?
    [Ee](?P<episodenumber>[0-9]+)
    ([ ._\-]+(?P<episodename>.+))?
    $
    """,
)

# foo.1x09
_add_tv(
    "nx_single",
    r"""
    ^((?P<seriesname>.+?)[ ._\-])?
    \[?
    (?P<seasonnumber>[0-9]+)
    [xX]
    (?P<episodenumber>[0-9]+)
    \]?
    [^/]*$
    """,
)

# date-based: foo.2024.03.15
_add_tv(
    "date_based",
    r"""
    ^((?P<seriesname>.+?)[ ._\-])?
    (?P<year>\d{4})
    [ ._\-]
    (?P<month>\d{2})
    [ ._\-]
    (?P<day>\d{2})
    [^/]*$
    """,
)

# show name Season 01 Episode 20
_add_tv(
    "season_episode_words",
    r"""
    ^(?P<seriesname>.+?)[ ]?[ ._\-][ ]?
    [Ss]eason[ ]?(?P<seasonnumber>[0-9]+)[ ]?
    [Ee]pisode[ ]?(?P<episodenumber>[0-9]+)
    [^/]*$
    """,
)

# Show - Episode 9999 [S 12 - Ep 131]
_add_tv(
    "episode_bracket",
    r"""
    (?P<seriesname>.+)
    [ ]-[ ]
    [Ee]pisode[ ]\d+
    [ ]
    \[
    [sS][ ]?(?P<seasonnumber>\d+)
    (?:[ ]|[ ]-[ ]|-)
    (?:[eE]|[eE]p)[ ]?(?P<episodenumber>\d+)
    \]
    .*$
    """,
)

# foo.s0101 (requires S prefix to avoid false positives on years/absolute numbers)
_add_tv(
    "bare_se_4digit",
    r"""
    ^(?P<seriesname>.+?)[ ._\-]
    [Ss](?P<seasonnumber>[0-9]{2})
    [\.\- ]?
    (?P<episodenumber>[0-9]{2})
    [^0-9]*$
    """,
)

# show name 2 of 6
_add_tv(
    "n_of_m",
    r"""
    ^(?P<seriesname>.+?)
    [ ._\-]
    (?P<episodenumber>[0-9]+)
    \s*of\s*
    \d+
    ([._ \-]|$|[^/]*$)
    """,
)

# Show.Name.Part1
_add_tv(
    "part_single",
    r"""
    ^(?P<seriesname>.+?)
    [ ._\-]
    [Pp]art[ ](?P<episodenumber>[0-9]+)
    [._ \-][^/]*$
    """,
)

# foo - [012]  (episode in brackets)
_add_tv(
    "bracket_episode",
    r"""
    ^((?P<seriesname>.+?)[ ._\-])?
    \[
    (?P<episodenumber>[0-9]+)
    \]
    [^/]*$
    """,
)

# show.name.e123 (no season)
_add_tv(
    "bare_e",
    r"""
    ^(?P<seriesname>.+?)
    [ ._\-]
    [Ee](?P<episodenumber>[0-9]+)
    [._ \-][^/]*$
    """,
)

# foo - [01.09]  (season.episode in brackets)
_add_tv(
    "bracket_season_dot_ep",
    r"""
    ^((?P<seriesname>.+?))
    [ ._\-]?
    \[
    (?P<seasonnumber>[0-9]+?)
    [.]
    (?P<episodenumber>[0-9]+?)
    \]
    [ ._\-]?
    [^/]*$
    """,
)

# Absolute number: Naruto - 001 or Naruto 001
_add_tv(
    "absolute_number",
    r"""
    ^(?P<seriesname>.+?)
    [ ._\-]+
    (?!(?:19|20)\d{2}(?:[._ \-]|$))   # reject year-like 4-digit numbers
    (?P<episodenumber>[0-9]{2,4})
    (?:[._ \-]|$)
    [^/]*$
    """,
)


# ---------------------------------------------------------------------------
# Movie patterns — checked after all TV patterns fail
# ---------------------------------------------------------------------------

# Movie with year in parens: Inception (2010).mkv
MOVIE_YEAR_PAREN = re.compile(
    r"""
    ^(?P<title>.+?)
    \s*\((?P<year>\d{4})\)
    (?P<rest>[^/]*)$
    """,
    re.VERBOSE,
)

# Movie with year separated by dots/dashes: inception.2010.1080p.bluray.mkv
MOVIE_YEAR_DOT = re.compile(
    r"""
    ^(?P<title>.+?)
    [.\-_ ](?P<year>(?:19|20)\d{2})
    [.\-_ ](?P<rest>[^/]*)$
    """,
    re.VERBOSE,
)

# Movie with no year: My Movie.mkv (fallback — only used if nothing else matched)
MOVIE_BARE = re.compile(
    r"""
    ^(?P<title>.+?)
    (?P<rest>)$
    """,
    re.VERBOSE,
)


# ---------------------------------------------------------------------------
# Name cleanup utilities
# ---------------------------------------------------------------------------

def _clean_name(name: str) -> str:
    """Clean a parsed series/movie name: replace dots/underscores with spaces,
    strip trailing dashes and whitespace."""
    if not name:
        return name
    # Replace dots and underscores with spaces
    cleaned = re.sub(r"[._]", " ", name)
    # Collapse multiple spaces
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Strip trailing dashes and whitespace
    cleaned = cleaned.strip(" -")
    return cleaned


def _extract_quality(filename: str) -> Optional[str]:
    m = QUALITY_RE.search(filename)
    return m.group(1) if m else None


def _extract_source(filename: str) -> Optional[str]:
    m = SOURCE_RE.search(filename)
    return m.group(1).lower().replace("-", "") if m else None


def _strip_extension(filename: str) -> tuple[str, str]:
    """Return (name_without_ext, extension_with_dot)."""
    root, ext = os.path.splitext(filename)
    return root, ext.lower()


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_filename(filename: str) -> ParsedFile:
    """Parse a video filename and return structured metadata.

    Tries TV patterns first (most specific to least specific), then falls
    back to movie patterns. If nothing matches, returns media_type=unknown.
    """
    basename = os.path.basename(filename)
    name_no_ext, ext = _strip_extension(basename)

    quality = _extract_quality(name_no_ext)
    source = _extract_source(name_no_ext)

    # --- Try TV patterns ---
    for pattern_name, pattern in TV_PATTERNS:
        m = pattern.match(name_no_ext)
        if not m:
            continue

        groups = m.groupdict()

        # Date-based episode
        if "year" in groups and "month" in groups and "day" in groups and groups.get("month"):
            try:
                air_date = datetime.date(
                    int(groups["year"]),
                    int(groups["month"]),
                    int(groups["day"]),
                )
            except ValueError:
                continue  # Invalid date, try next pattern

            return ParsedFile(
                title=_clean_name(groups.get("seriesname", "") or ""),
                media_type=MediaType.TV,
                season_number=None,
                episode_numbers=None,
                episode_name=None,
                year=int(groups["year"]),
                date=air_date,
                quality=quality,
                source=source,
                file_extension=ext,
                original_filename=basename,
            )

        # Multi-episode
        if groups.get("episodenumberstart") and groups.get("episodenumberend"):
            start = int(groups["episodenumberstart"])
            end = int(groups["episodenumberend"])
            episodes = list(range(start, end + 1))
            season = int(groups["seasonnumber"]) if groups.get("seasonnumber") else None

            return ParsedFile(
                title=_clean_name(groups.get("seriesname", "") or ""),
                media_type=MediaType.TV,
                season_number=season,
                episode_numbers=episodes,
                episode_name=None,
                year=None,
                date=None,
                quality=quality,
                source=source,
                file_extension=ext,
                original_filename=basename,
            )

        # Single episode
        if groups.get("episodenumber") is not None:
            ep_num = int(groups["episodenumber"])
            season = int(groups["seasonnumber"]) if groups.get("seasonnumber") else None
            ep_name_raw = groups.get("episodename")
            ep_name = _clean_episode_name(_clean_name(ep_name_raw)) if ep_name_raw else None

            return ParsedFile(
                title=_clean_name(groups.get("seriesname", "") or ""),
                media_type=MediaType.TV,
                season_number=season,
                episode_numbers=[ep_num],
                episode_name=ep_name,
                year=None,
                date=None,
                quality=quality,
                source=source,
                file_extension=ext,
                original_filename=basename,
            )

    # --- Try movie patterns ---
    # Movie with year in parentheses
    m = MOVIE_YEAR_PAREN.match(name_no_ext)
    if m:
        return ParsedFile(
            title=_clean_name(m.group("title")),
            media_type=MediaType.MOVIE,
            year=int(m.group("year")),
            quality=quality,
            source=source,
            file_extension=ext,
            original_filename=basename,
        )

    # Movie with year in dots/dashes
    m = MOVIE_YEAR_DOT.match(name_no_ext)
    if m:
        return ParsedFile(
            title=_clean_name(m.group("title")),
            media_type=MediaType.MOVIE,
            year=int(m.group("year")),
            quality=quality,
            source=source,
            file_extension=ext,
            original_filename=basename,
        )

    # Bare filename — unknown (could be movie or TV, can't tell without TVDB)
    return ParsedFile(
        title=_clean_name(name_no_ext),
        media_type=MediaType.UNKNOWN,
        quality=quality,
        source=source,
        file_extension=ext,
        original_filename=basename,
    )


def _clean_episode_name(name: str) -> Optional[str]:
    """Strip quality/source tags from an episode name. Return None if nothing remains."""
    stripped = name
    for pat in QUALITY_PATTERNS + SOURCE_PATTERNS:
        stripped = re.sub(pat, "", stripped, flags=re.IGNORECASE)
    # Clean up leftover separators and whitespace
    stripped = re.sub(r"[.\-_ ]+", " ", stripped).strip(" -")
    return stripped if stripped else None
