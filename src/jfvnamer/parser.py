"""Filename parsing engine using regex patterns.

Ported from tvnamer's battle-tested filename patterns, extended with
fansub tag preprocessing for anime files.
"""

from __future__ import annotations

import datetime
import os
import re
from typing import Optional

from jfvnamer.models import ParsedFile


# ---------------------------------------------------------------------------
# Fansub tag preprocessing
# ---------------------------------------------------------------------------

# Technical bracket tags that should be stripped
_TECH_BRACKET_RE = re.compile(
    r"\[(?:"
    r"[Hh]\.?2(?:64|65)|HEVC|AVC"
    r"|[Xx]vi[Dd]|[Xx]2(?:64|65)"
    r"|[Aa][Aa][Cc]2?|[Aa][Cc]3|[Mm][Pp]3|[Ff][Ll][Aa][Cc]|[Dd][Tt][Ss]"
    r"|\d{3,4}[xX]\d{3,4}"
    r"|[0-9]{3,4}[pP]"
    r")[^\]]*\]"
)

# Technical paren tags that should be stripped: (720p x264 AAC), (H264.AC3)
_TECH_PAREN_RE = re.compile(
    r"\((?:[0-9]+[pP]|[Hh]\.?2(?:64|65)|[Xx]vi[Dd]|[Xx]2(?:64|65)|HEVC|AVC)[^)]*\)",
    re.IGNORECASE,
)

# Trailing format-only tokens after separators
_TRAILING_FORMAT_RE = re.compile(
    r"(?:[._\- ]+(?:"
    r"DVD|BDRip|BluRay|Blu[\-.]Ray|HDTV|WEB[\-.]DL|WEBRip"
    r"|[Hh]\.?2(?:64|65)|HEVC|AVC|[Xx]2(?:64|65)|[Xx]vi[Dd]"
    r"|[Aa][Aa][Cc]2?|[Aa][Cc]3|[Mm][Pp]3|[Ff][Ll][Aa][Cc]|[Dd][Tt][Ss]"
    r"|[0-9]+[pP]|UHD|HDR"
    r"))+[._\- ]*$",
    re.IGNORECASE,
)

# Episode special names
_SPECIAL_EPISODE_NAMES = ("special", "ova", "oav")


def _preprocess_fansub(name: str) -> str:
    """Strip fansub noise from a filename stem before pattern matching.

    Strips in order:
    1. All leading [group] tags (e.g. [ANIME-PLUS.COM]_[B2E])
    2. 8-character hex CRC hashes (e.g. [7D56A41E])
    3. Technical bracket tags ([H.264], [XviD], [720p], [1280x720])
    4. Technical paren tags ((720p x264 AAC), (H264.AC3))
    5. Remaining non-numeric bracket tags ([KAA], etc.)
    6. Trailing format-only tokens (DVD, BDRip, x264, etc.)
    """
    s = name

    # Step 1: Strip all leading [group] tags, optionally separated by _, ., or space
    s = re.sub(r"^(?:\[[^\]]*\][_. ]?)+", "", s).lstrip("._- ")

    # Step 2: Strip 8-character hex/alphanumeric CRC hashes anywhere
    s = re.sub(r"\[[0-9A-Fa-f]{8}\]", "", s)

    # Step 3: Strip known technical bracket tags
    s = _TECH_BRACKET_RE.sub("", s)

    # Step 4: Strip technical paren tags
    s = _TECH_PAREN_RE.sub("", s)

    # Step 5: Strip remaining non-numeric bracket tags
    # Keep [01], [01.09], [123] (pure digit or digit.digit) — these are episode refs
    s = re.sub(r"\[(?!\d+(?:\.\d+)?\])[^\]]*\]", "", s)

    # Step 6: Strip trailing format-only tokens (apply repeatedly until stable)
    prev = None
    while prev != s:
        prev = s
        s = _TRAILING_FORMAT_RE.sub("", s)

    return s.strip("._- ")


# ---------------------------------------------------------------------------
# TV patterns — tried in order, first match wins.
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

# Standard SxxExx
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

# foo.s0101
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

# foo - [012]
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

# show.name.e123
_add_tv(
    "bare_e",
    r"""
    ^(?P<seriesname>.+?)
    [ ._\-]
    [Ee](?P<episodenumber>[0-9]+)
    [._ \-][^/]*$
    """,
)

# foo - [01.09]
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

# Bare dash range: Show - 01-03 (fansub multi-ep after preprocessing strips group/crc tags)
_add_tv(
    "bare_dash_range",
    r"""
    ^(?P<seriesname>.+?)
    [ ._\-]+
    (?!(?:19|20)\d{2}(?:[._ \-]|$))   # reject year-like 4-digit numbers
    (?P<episodenumberstart>[0-9]{1,4})
    [-]
    (?P<episodenumberend>[0-9]{1,4})
    (?:[._ \-]|$)
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
# Name cleanup utilities
# ---------------------------------------------------------------------------

def _clean_name(name: str) -> str:
    """Clean a parsed series/movie name: replace dots/underscores with spaces,
    strip trailing dashes and whitespace."""
    if not name:
        return name
    cleaned = re.sub(r"[._]", " ", name)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" -")
    return cleaned


def _strip_extension(filename: str) -> tuple[str, str]:
    """Return (name_without_ext, extension_with_dot)."""
    root, ext = os.path.splitext(filename)
    return root, ext.lower()


def _clean_episode_name(name: str) -> Optional[str]:
    """Strip leftover technical tokens from a captured episode name."""
    stripped = _TRAILING_FORMAT_RE.sub("", name)
    stripped = re.sub(r"[.\-_ ]+", " ", stripped).strip(" -")
    return stripped if stripped else None


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_filename(filename: str) -> ParsedFile:
    """Parse a video filename and return structured metadata.

    Applies fansub preprocessing first, then tries TV episode patterns.
    If no pattern matches, returns a ParsedFile with just the cleaned title.
    """
    basename = os.path.basename(filename)
    name_no_ext, ext = _strip_extension(basename)

    # Preprocess: strip fansub noise before pattern matching
    preprocessed = _preprocess_fansub(name_no_ext)

    # --- Try TV patterns ---
    for _, pattern in TV_PATTERNS:
        m = pattern.match(preprocessed)
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
                continue

            return ParsedFile(
                title=_clean_name(groups.get("seriesname", "") or ""),
                season_number=None,
                episode_numbers=None,
                episode_name=None,
                date=air_date,
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
                season_number=season,
                episode_numbers=episodes,
                episode_name=None,
                date=None,
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
                season_number=season,
                episode_numbers=[ep_num],
                episode_name=ep_name,
                date=None,
                file_extension=ext,
                original_filename=basename,
            )

    # --- No TV pattern matched — check for Special/OVA/OAV ---
    cleaned = _clean_name(preprocessed)
    cleaned_lower = cleaned.lower()
    for special in _SPECIAL_EPISODE_NAMES:
        if cleaned_lower == special or cleaned_lower.endswith(" " + special):
            title_part = cleaned[: -len(special)].strip(" -")
            return ParsedFile(
                title=title_part or cleaned,
                episode_name=cleaned[-len(special):].capitalize(),
                file_extension=ext,
                original_filename=basename,
            )

    # --- Fallback: return cleaned title with no episode info ---
    return ParsedFile(
        title=cleaned,
        file_extension=ext,
        original_filename=basename,
    )
