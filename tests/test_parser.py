"""Tests for filename parsing."""

from __future__ import annotations

import datetime

import pytest

from jfvnamer.models import MediaType
from jfvnamer.parser import parse_filename


# ---------------------------------------------------------------------------
# Standard TV patterns: SxxExx
# ---------------------------------------------------------------------------

class TestStandardSE:
    def test_standard_dash_separated(self):
        r = parse_filename("Breaking Bad - S01E01 - Pilot.mkv")
        assert r.title == "Breaking Bad"
        assert r.media_type == MediaType.TV
        assert r.season_number == 1
        assert r.episode_numbers == [1]
        assert r.episode_name == "Pilot"
        assert r.file_extension == ".mkv"

    def test_dotted_lowercase(self):
        r = parse_filename("breaking.bad.s01e01.pilot.720p.bluray.mkv")
        assert r.title == "breaking bad"
        assert r.media_type == MediaType.TV
        assert r.season_number == 1
        assert r.episode_numbers == [1]
        assert r.episode_name == "pilot"
        assert r.quality == "720p"

    def test_tags_not_in_episode_name(self):
        r = parse_filename("show.s01e01.720p.hdtv.mkv")
        assert r.episode_name is None

    def test_year_in_show_name(self):
        r = parse_filename("Show Name (2024) - S01E01.mkv")
        assert r.media_type == MediaType.TV
        assert r.season_number == 1
        assert r.episode_numbers == [1]
        assert "Show Name" in r.title

    def test_dots_in_show_name(self):
        r = parse_filename("A.P. Bio - S01E01.mkv")
        assert r.media_type == MediaType.TV
        assert r.season_number == 1
        assert r.episode_numbers == [1]

    def test_shield_acronym(self):
        r = parse_filename("Marvel's Agents of S.H.I.E.L.D. - S01E01.mkv")
        assert r.media_type == MediaType.TV
        assert r.season_number == 1
        assert r.episode_numbers == [1]


# ---------------------------------------------------------------------------
# NxNN format
# ---------------------------------------------------------------------------

class TestNxFormat:
    def test_1x01(self):
        r = parse_filename("Breaking Bad 1x01 Pilot.mkv")
        assert r.title == "Breaking Bad"
        assert r.media_type == MediaType.TV
        assert r.season_number == 1
        assert r.episode_numbers == [1]


# ---------------------------------------------------------------------------
# Multi-episode
# ---------------------------------------------------------------------------

class TestMultiEpisode:
    def test_se_dash_multi(self):
        r = parse_filename("Breaking Bad - S01E01-E02.mkv")
        assert r.media_type == MediaType.TV
        assert r.season_number == 1
        assert r.episode_numbers == [1, 2]

    def test_se_multi_no_dash(self):
        r = parse_filename("breaking.bad.s01e01e02.mkv")
        assert r.media_type == MediaType.TV
        assert r.season_number == 1
        assert r.episode_numbers == [1, 2]

    def test_se_cross_episode_range(self):
        r = parse_filename("Breaking Bad - S01E01-S01E03.mkv")
        assert r.media_type == MediaType.TV
        assert r.season_number == 1
        assert r.episode_numbers == [1, 2, 3]


# ---------------------------------------------------------------------------
# Date-based episodes
# ---------------------------------------------------------------------------

class TestDateBased:
    def test_dash_date(self):
        r = parse_filename("The Daily Show - 2024-03-15.mkv")
        assert r.media_type == MediaType.TV
        assert r.date == datetime.date(2024, 3, 15)
        assert "Daily Show" in r.title

    def test_dot_date(self):
        r = parse_filename("The.Daily.Show.2024.03.15.mkv")
        assert r.media_type == MediaType.TV
        assert r.date == datetime.date(2024, 3, 15)


# ---------------------------------------------------------------------------
# Absolute numbering (anime)
# ---------------------------------------------------------------------------

class TestAbsoluteNumbering:
    def test_absolute_dash(self):
        r = parse_filename("Naruto - 001.mkv")
        assert r.media_type == MediaType.TV
        assert r.episode_numbers == [1]
        assert r.season_number is None
        assert r.title == "Naruto"

    def test_absolute_space(self):
        r = parse_filename("Naruto 001.mkv")
        assert r.media_type == MediaType.TV
        assert r.episode_numbers == [1]
        assert r.season_number is None


# ---------------------------------------------------------------------------
# Bare season+episode (Lost - 301)
# ---------------------------------------------------------------------------

class TestBareSE:
    def test_bare_3digit(self):
        r = parse_filename("Lost - 301.mkv")
        assert r.media_type == MediaType.TV
        # Should parse as season 3, episode 01 or absolute 301
        # The bare_se_4digit pattern treats first digit(s) as season, last 2 as episode
        assert r.episode_numbers is not None


# ---------------------------------------------------------------------------
# Movie patterns
# ---------------------------------------------------------------------------

class TestMovies:
    def test_movie_year_parens(self):
        r = parse_filename("Inception (2010).mkv")
        assert r.title == "Inception"
        assert r.media_type == MediaType.MOVIE
        assert r.year == 2010
        assert r.file_extension == ".mkv"

    def test_movie_dotted_with_quality(self):
        r = parse_filename("inception.2010.1080p.bluray.mkv")
        assert r.title == "inception"
        assert r.media_type == MediaType.MOVIE
        assert r.year == 2010
        assert r.quality == "1080p"

    def test_movie_remastered(self):
        r = parse_filename("The.Matrix.1999.Remastered.2160p.UHD.mkv")
        assert r.media_type == MediaType.MOVIE
        assert r.year == 1999
        assert r.quality == "2160p"

    def test_movie_bare_no_year(self):
        r = parse_filename("My Movie.mkv")
        assert r.title == "My Movie"
        assert r.media_type == MediaType.UNKNOWN
        assert r.year is None


# ---------------------------------------------------------------------------
# Media type detection
# ---------------------------------------------------------------------------

class TestMediaTypeDetection:
    def test_se_is_tv(self):
        r = parse_filename("Show - S01E01.mkv")
        assert r.media_type == MediaType.TV

    def test_title_year_is_movie(self):
        r = parse_filename("Movie (2020).mkv")
        assert r.media_type == MediaType.MOVIE

    def test_bare_title_is_unknown(self):
        r = parse_filename("SomeFile.mkv")
        assert r.media_type == MediaType.UNKNOWN

    def test_date_is_tv(self):
        r = parse_filename("Show.2024.01.15.mkv")
        assert r.media_type == MediaType.TV


# ---------------------------------------------------------------------------
# Quality and source extraction
# ---------------------------------------------------------------------------

class TestQualitySource:
    def test_720p(self):
        r = parse_filename("show.s01e01.720p.hdtv.mkv")
        assert r.quality == "720p"

    def test_1080p_bluray(self):
        r = parse_filename("show.s01e01.1080p.bluray.mkv")
        assert r.quality == "1080p"
        assert r.source is not None
        assert "bluray" in r.source

    def test_2160p(self):
        r = parse_filename("show.s01e01.2160p.web-dl.mkv")
        assert r.quality == "2160p"

    def test_no_quality(self):
        r = parse_filename("Show - S01E01 - Pilot.mkv")
        assert r.quality is None


# ---------------------------------------------------------------------------
# File extension handling
# ---------------------------------------------------------------------------

class TestExtensions:
    def test_mkv(self):
        assert parse_filename("foo.s01e01.mkv").file_extension == ".mkv"

    def test_mp4(self):
        assert parse_filename("foo.s01e01.mp4").file_extension == ".mp4"

    def test_avi(self):
        assert parse_filename("foo.s01e01.avi").file_extension == ".avi"

    def test_uppercase_ext(self):
        assert parse_filename("foo.s01e01.MKV").file_extension == ".mkv"


# ---------------------------------------------------------------------------
# Name cleanup
# ---------------------------------------------------------------------------

class TestNameCleanup:
    def test_dots_replaced(self):
        r = parse_filename("some.show.name.s01e01.mkv")
        assert "." not in r.title
        assert "some show name" == r.title

    def test_underscores_replaced(self):
        r = parse_filename("some_show_name_s01e01.mkv")
        assert "_" not in r.title

    def test_trailing_dash_stripped(self):
        r = parse_filename("Show Name - S01E01.mkv")
        assert not r.title.endswith("-")
        assert not r.title.endswith(" ")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_original_filename_preserved(self):
        r = parse_filename("Breaking Bad - S01E01 - Pilot.mkv")
        assert r.original_filename == "Breaking Bad - S01E01 - Pilot.mkv"

    def test_path_with_directory(self):
        r = parse_filename("/some/path/Breaking Bad - S01E01.mkv")
        assert r.original_filename == "Breaking Bad - S01E01.mkv"
        assert r.title == "Breaking Bad"

    def test_empty_extension_handled(self):
        r = parse_filename("noext")
        assert r.file_extension == ""

    def test_numbers_only_filename(self):
        r = parse_filename("12345.mkv")
        # Should not crash
        assert r.file_extension == ".mkv"

    def test_unicode_characters(self):
        r = parse_filename("Café Society (2016).mkv")
        assert r.media_type == MediaType.MOVIE
        assert r.year == 2016

    def test_very_long_filename(self):
        name = "A" * 200 + " - S01E01.mkv"
        r = parse_filename(name)
        assert r.media_type == MediaType.TV
        assert r.season_number == 1


# ---------------------------------------------------------------------------
# Anime fansub patterns
# ---------------------------------------------------------------------------

class TestAnimeFansub:
    def test_group_bracket_single(self):
        r = parse_filename("[SubGroup] Naruto - 05 [720p].mkv")
        assert r.media_type == MediaType.TV
        assert r.episode_numbers == [5]

    def test_group_bracket_multi(self):
        r = parse_filename("[SubGroup] Naruto - 01-03 [CRC123].mkv")
        assert r.media_type == MediaType.TV
        assert r.episode_numbers == [1, 2, 3]


# ---------------------------------------------------------------------------
# Season word patterns
# ---------------------------------------------------------------------------

class TestSeasonWordPatterns:
    def test_season_episode_words(self):
        r = parse_filename("Show Name Season 01 Episode 20.mkv")
        assert r.media_type == MediaType.TV
        assert r.season_number == 1
        assert r.episode_numbers == [20]
