"""Tests for Jellyfin naming conventions."""

import datetime

import pytest

from jfvnamer.jellyfin import (
    build_date_episode_filename,
    build_episode_filename,
    build_movie_filename,
    build_movie_folder_name,
    build_season_folder_name,
    build_series_folder_name,
    build_target_path,
    sanitize_name,
)
from jfvnamer.models import (
    MediaType,
    NamingConfig,
    ParsedFile,
    TVDBEpisode,
    TVDBMovieDetails,
    TVDBSeriesDetails,
)


# ---------------------------------------------------------------------------
# sanitize_name
# ---------------------------------------------------------------------------


class TestSanitizeName:
    def test_colon_replaced(self):
        assert sanitize_name("Title: Subtitle") == "Title - Subtitle"

    def test_strip_characters_removed(self):
        assert sanitize_name('What?') == "What"
        assert sanitize_name('Name*') == "Name"
        assert sanitize_name('A "Quoted" Name') == "A Quoted Name"

    def test_trailing_dots_and_spaces_stripped(self):
        assert sanitize_name("Name...") == "Name"
        assert sanitize_name("Name   ") == "Name"
        assert sanitize_name("Name. . .") == "Name"

    def test_custom_colon_replacement(self):
        assert sanitize_name("A: B", replace_colon_with=" --") == "A -- B"

    def test_preserves_normal_characters(self):
        assert sanitize_name("Normal Title 2024") == "Normal Title 2024"


# ---------------------------------------------------------------------------
# TV show folder/filename builders
# ---------------------------------------------------------------------------


class TestSeriesFolder:
    def test_with_year(self):
        assert build_series_folder_name("Breaking Bad", year=2008) == "Breaking Bad (2008)"

    def test_without_year(self):
        assert build_series_folder_name("Breaking Bad") == "Breaking Bad"

    def test_year_as_string(self):
        assert build_series_folder_name("Lost", year="2004") == "Lost (2004)"

    def test_colon_in_name(self):
        assert build_series_folder_name("Star Trek: Discovery", year=2017) == "Star Trek - Discovery (2017)"


class TestSeasonFolder:
    def test_standard(self):
        assert build_season_folder_name(1) == "Season 01"
        assert build_season_folder_name(3) == "Season 03"
        assert build_season_folder_name(12) == "Season 12"

    def test_specials(self):
        assert build_season_folder_name(0) == "Season 00"

    def test_none_defaults_to_01(self):
        assert build_season_folder_name(None) == "Season 01"


class TestEpisodeFilename:
    def test_standard_episode(self):
        result = build_episode_filename(
            "Breaking Bad", 1, [1], ".mkv", episode_title="Pilot"
        )
        assert result == "Breaking Bad - S01E01 - Pilot.mkv"

    def test_no_title(self):
        result = build_episode_filename("Breaking Bad", 1, [1], ".mkv")
        assert result == "Breaking Bad - S01E01.mkv"

    def test_multi_episode(self):
        result = build_episode_filename(
            "Breaking Bad", 1, [1, 2], ".mkv", episode_title="Pilot"
        )
        assert result == "Breaking Bad - S01E01-E02 - Pilot.mkv"

    def test_multi_episode_no_title(self):
        result = build_episode_filename("Breaking Bad", 1, [1, 2], ".mkv")
        assert result == "Breaking Bad - S01E01-E02.mkv"

    def test_specials(self):
        result = build_episode_filename(
            "Doctor Who", 0, [5], ".mkv", episode_title="The Christmas Invasion"
        )
        assert result == "Doctor Who - S00E05 - The Christmas Invasion.mkv"

    def test_colon_in_episode_title(self):
        result = build_episode_filename(
            "Show", 1, [1], ".mkv", episode_title="Part 1: The Beginning"
        )
        assert result == "Show - S01E01 - Part 1 - The Beginning.mkv"

    def test_colon_in_series_name(self):
        result = build_episode_filename(
            "Star Trek: Discovery", 1, [1], ".mkv", episode_title="Pilot"
        )
        assert result == "Star Trek - Discovery - S01E01 - Pilot.mkv"


class TestDateEpisodeFilename:
    def test_date_fallback(self):
        result = build_date_episode_filename(
            "The Daily Show", datetime.date(2024, 3, 15), ".mkv"
        )
        assert result == "The Daily Show - 2024-03-15.mkv"


# ---------------------------------------------------------------------------
# Movie naming
# ---------------------------------------------------------------------------


class TestMovieFolder:
    def test_with_year(self):
        assert build_movie_folder_name("Inception", year=2010) == "Inception (2010)"

    def test_without_year(self):
        assert build_movie_folder_name("Inception") == "Inception"

    def test_colon_in_name(self):
        assert build_movie_folder_name("Batman: The Movie", year=1966) == "Batman - The Movie (1966)"


class TestMovieFilename:
    def test_with_year(self):
        assert build_movie_filename("Inception", ".mkv", year=2010) == "Inception (2010).mkv"

    def test_without_year(self):
        assert build_movie_filename("Inception", ".mkv") == "Inception.mkv"

    def test_special_characters(self):
        result = build_movie_filename('What If...?', ".mkv", year=2021)
        assert result == "What If (2021).mkv"


# ---------------------------------------------------------------------------
# build_target_path — TV
# ---------------------------------------------------------------------------


def _make_parsed(
    title: str = "Test",
    media_type: MediaType = MediaType.TV,
    ext: str = ".mkv",
    **kwargs,
) -> ParsedFile:
    return ParsedFile(
        title=title,
        media_type=media_type,
        file_extension=ext,
        original_filename=f"{title}{ext}",
        **kwargs,
    )


class TestBuildTargetPathTV:
    def test_standard_episode(self):
        parsed = _make_parsed("Breaking Bad", season_number=1, episode_numbers=[1])
        series = TVDBSeriesDetails(tvdb_id=1, name="Breaking Bad", year="2008")
        episode = TVDBEpisode(
            tvdb_id=100, name="Pilot", season_number=1, episode_number=1
        )
        path = build_target_path(parsed, series=series, episode=episode)
        assert path == "Breaking Bad (2008)/Season 01/Breaking Bad - S01E01 - Pilot.mkv"

    def test_missing_year_uses_parsed(self):
        parsed = _make_parsed("Show", year=2020, season_number=1, episode_numbers=[1])
        series = TVDBSeriesDetails(tvdb_id=1, name="Show", year=None)
        episode = TVDBEpisode(
            tvdb_id=100, name="Ep", season_number=1, episode_number=1
        )
        path = build_target_path(parsed, series=series, episode=episode)
        assert path == "Show (2020)/Season 01/Show - S01E01 - Ep.mkv"

    def test_missing_year_entirely(self):
        parsed = _make_parsed("Show", season_number=1, episode_numbers=[1])
        series = TVDBSeriesDetails(tvdb_id=1, name="Show")
        episode = TVDBEpisode(
            tvdb_id=100, season_number=1, episode_number=1
        )
        path = build_target_path(parsed, series=series, episode=episode)
        assert path == "Show/Season 01/Show - S01E01.mkv"

    def test_no_season_defaults_to_01(self):
        parsed = _make_parsed("Naruto", season_number=None, episode_numbers=[1])
        series = TVDBSeriesDetails(tvdb_id=1, name="Naruto", year="2002")
        # No episode match — falls through to parsed info
        path = build_target_path(parsed, series=series)
        assert path == "Naruto (2002)/Season 01/Naruto - S01E01.mkv"

    def test_specials_season_00(self):
        parsed = _make_parsed("Doctor Who", season_number=0, episode_numbers=[5])
        series = TVDBSeriesDetails(tvdb_id=1, name="Doctor Who", year="2005")
        episode = TVDBEpisode(
            tvdb_id=200,
            name="The Christmas Invasion",
            season_number=0,
            episode_number=5,
        )
        path = build_target_path(parsed, series=series, episode=episode)
        assert path == "Doctor Who (2005)/Season 00/Doctor Who - S00E05 - The Christmas Invasion.mkv"

    def test_date_based_fallback(self):
        parsed = _make_parsed(
            "The Daily Show",
            date=datetime.date(2024, 3, 15),
        )
        series = TVDBSeriesDetails(tvdb_id=1, name="The Daily Show", year="1996")
        # No episode match — date fallback
        path = build_target_path(parsed, series=series)
        assert path == "The Daily Show (1996)/Season 2024/The Daily Show - 2024-03-15.mkv"

    def test_invalid_characters_sanitized(self):
        parsed = _make_parsed("Test", season_number=1, episode_numbers=[1])
        series = TVDBSeriesDetails(tvdb_id=1, name="What If...?", year="2021")
        episode = TVDBEpisode(
            tvdb_id=100,
            name='The "Big" Question?',
            season_number=1,
            episode_number=1,
        )
        path = build_target_path(parsed, series=series, episode=episode)
        assert "?" not in path
        assert '"' not in path
        assert path.startswith("What If (2021)/")


# ---------------------------------------------------------------------------
# build_target_path — Movies
# ---------------------------------------------------------------------------


class TestBuildTargetPathMovie:
    def test_movie_with_year(self):
        parsed = _make_parsed("inception", media_type=MediaType.MOVIE, year=2010)
        movie = TVDBMovieDetails(tvdb_id=1, name="Inception", year="2010")
        path = build_target_path(parsed, movie=movie)
        assert path == "Inception (2010)/Inception (2010).mkv"

    def test_movie_without_year(self):
        parsed = _make_parsed("my movie", media_type=MediaType.MOVIE)
        movie = TVDBMovieDetails(tvdb_id=1, name="My Movie")
        path = build_target_path(parsed, movie=movie)
        assert path == "My Movie/My Movie.mkv"

    def test_movie_colon(self):
        parsed = _make_parsed("batman", media_type=MediaType.MOVIE)
        movie = TVDBMovieDetails(tvdb_id=1, name="Batman: The Movie", year="1966")
        path = build_target_path(parsed, movie=movie)
        assert path == "Batman - The Movie (1966)/Batman - The Movie (1966).mkv"

    def test_movie_year_fallback_to_parsed(self):
        parsed = _make_parsed("inception", media_type=MediaType.MOVIE, year=2010)
        movie = TVDBMovieDetails(tvdb_id=1, name="Inception", year=None)
        path = build_target_path(parsed, movie=movie)
        assert path == "Inception (2010)/Inception (2010).mkv"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestBuildTargetPathErrors:
    def test_no_metadata_raises(self):
        parsed = _make_parsed("Test")
        with pytest.raises(ValueError, match="requires either"):
            build_target_path(parsed)
