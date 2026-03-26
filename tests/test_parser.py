"""Tests for filename parsing."""

from __future__ import annotations

import datetime

from jfvnamer.parser import parse_filename, _preprocess_fansub


# ---------------------------------------------------------------------------
# Standard TV patterns: SxxExx
# ---------------------------------------------------------------------------

class TestStandardSE:
    def test_standard_dash_separated(self):
        r = parse_filename("Breaking Bad - S01E01 - Pilot.mkv")
        assert r.title == "Breaking Bad"
        assert r.season_number == 1
        assert r.episode_numbers == [1]
        assert r.episode_name == "Pilot"
        assert r.file_extension == ".mkv"

    def test_dotted_lowercase(self):
        r = parse_filename("breaking.bad.s01e01.pilot.720p.bluray.mkv")
        assert r.title == "breaking bad"
        assert r.season_number == 1
        assert r.episode_numbers == [1]
        # episode name may be present or cleaned away; we just check it's not a tag
        if r.episode_name:
            assert "720p" not in r.episode_name
            assert "bluray" not in r.episode_name.lower()

    def test_tags_not_in_episode_name(self):
        r = parse_filename("show.s01e01.720p.hdtv.mkv")
        assert r.episode_name is None

    def test_year_in_show_name(self):
        r = parse_filename("Show Name (2024) - S01E01.mkv")
        assert r.season_number == 1
        assert r.episode_numbers == [1]
        assert "Show Name" in r.title

    def test_dots_in_show_name(self):
        r = parse_filename("A.P. Bio - S01E01.mkv")
        assert r.season_number == 1
        assert r.episode_numbers == [1]

    def test_shield_acronym(self):
        r = parse_filename("Marvel's Agents of S.H.I.E.L.D. - S01E01.mkv")
        assert r.season_number == 1
        assert r.episode_numbers == [1]


# ---------------------------------------------------------------------------
# NxNN format
# ---------------------------------------------------------------------------

class TestNxFormat:
    def test_1x01(self):
        r = parse_filename("Breaking Bad 1x01 Pilot.mkv")
        assert r.title == "Breaking Bad"
        assert r.season_number == 1
        assert r.episode_numbers == [1]


# ---------------------------------------------------------------------------
# Multi-episode
# ---------------------------------------------------------------------------

class TestMultiEpisode:
    def test_se_dash_multi(self):
        r = parse_filename("Breaking Bad - S01E01-E02.mkv")
        assert r.season_number == 1
        assert r.episode_numbers == [1, 2]

    def test_se_multi_no_dash(self):
        r = parse_filename("breaking.bad.s01e01e02.mkv")
        assert r.season_number == 1
        assert r.episode_numbers == [1, 2]

    def test_se_cross_episode_range(self):
        r = parse_filename("Breaking Bad - S01E01-S01E03.mkv")
        assert r.season_number == 1
        assert r.episode_numbers == [1, 2, 3]


# ---------------------------------------------------------------------------
# Date-based episodes
# ---------------------------------------------------------------------------

class TestDateBased:
    def test_dash_date(self):
        r = parse_filename("The Daily Show - 2024-03-15.mkv")
        assert r.date == datetime.date(2024, 3, 15)
        assert "Daily Show" in r.title

    def test_dot_date(self):
        r = parse_filename("The.Daily.Show.2024.03.15.mkv")
        assert r.date == datetime.date(2024, 3, 15)


# ---------------------------------------------------------------------------
# Absolute numbering (anime)
# ---------------------------------------------------------------------------

class TestAbsoluteNumbering:
    def test_absolute_dash(self):
        r = parse_filename("Naruto - 001.mkv")
        assert r.episode_numbers == [1]
        assert r.season_number is None
        assert r.title == "Naruto"

    def test_absolute_space(self):
        r = parse_filename("Naruto 001.mkv")
        assert r.episode_numbers == [1]
        assert r.season_number is None


# ---------------------------------------------------------------------------
# Bare season+episode
# ---------------------------------------------------------------------------

class TestBareSE:
    def test_bare_3digit(self):
        r = parse_filename("Lost - 301.mkv")
        assert r.episode_numbers is not None


# ---------------------------------------------------------------------------
# ep / eps episode prefix
# ---------------------------------------------------------------------------

class TestEpEpsPrefix:
    def test_eps_no_separator(self):
        r = parse_filename("Show.Name.eps01.mkv")
        assert r.title == "Show Name"
        assert r.episode_numbers == [1]

    def test_ep_no_separator(self):
        r = parse_filename("Show.Name.ep01.mkv")
        assert r.title == "Show Name"
        assert r.episode_numbers == [1]

    def test_bare_e_end_of_filename(self):
        r = parse_filename("Show.Name.e01.mkv")
        assert r.title == "Show Name"
        assert r.episode_numbers == [1]

    def test_eps_space_separated(self):
        r = parse_filename("Show Name eps01.mkv")
        assert r.title == "Show Name"
        assert r.episode_numbers == [1]

    def test_eps_uppercase(self):
        r = parse_filename("Show.Name.EPS12.mkv")
        assert r.title == "Show Name"
        assert r.episode_numbers == [12]

    def test_ep_uppercase(self):
        r = parse_filename("Show.Name.EP12.mkv")
        assert r.title == "Show Name"
        assert r.episode_numbers == [12]

    def test_eps_dot_separator(self):
        r = parse_filename("Show.Name.eps.01.mkv")
        assert r.title == "Show Name"
        assert r.episode_numbers == [1]

    def test_e_with_trailing_tags(self):
        r = parse_filename("Show.Name.e01.720p.mkv")
        assert r.title == "Show Name"
        assert r.episode_numbers == [1]


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
        assert r.file_extension == ".mkv"

    def test_unicode_characters(self):
        r = parse_filename("Café Society (2016).mkv")
        assert r.file_extension == ".mkv"

    def test_very_long_filename(self):
        name = "A" * 200 + " - S01E01.mkv"
        r = parse_filename(name)
        assert r.season_number == 1


# ---------------------------------------------------------------------------
# Anime fansub patterns
# ---------------------------------------------------------------------------

class TestAnimeFansub:
    def test_group_bracket_single(self):
        r = parse_filename("[SubGroup] Naruto - 05 [720p].mkv")
        assert r.episode_numbers == [5]

    def test_group_bracket_multi(self):
        r = parse_filename("[SubGroup] Naruto - 01-03 [CRC123].mkv")
        assert r.episode_numbers == [1, 2, 3]


# ---------------------------------------------------------------------------
# Season word patterns
# ---------------------------------------------------------------------------

class TestSeasonWordPatterns:
    def test_season_episode_words(self):
        r = parse_filename("Show Name Season 01 Episode 20.mkv")
        assert r.season_number == 1
        assert r.episode_numbers == [20]


# ---------------------------------------------------------------------------
# Fansub preprocessing — the 7 required test cases
# ---------------------------------------------------------------------------

class TestFansubPreprocessing:
    def test_single_leading_group(self):
        r = parse_filename("[Nyoro~n Subs] Gurren Lagann 02.mkv")
        assert r.title == "Gurren Lagann"
        assert r.episode_numbers == [2]

    def test_group_with_tech_paren(self):
        r = parse_filename("[SS-anon] Tengen Toppa Gurren-Lagann 14 (720p x264 AAC).mkv")
        assert r.title == "Tengen Toppa Gurren-Lagann"
        assert r.episode_numbers == [14]

    def test_double_leading_group_and_crc(self):
        r = parse_filename("[ANIME-PLUS.COM]_[B2E].One_Outs.01.H264.[CD4A62E4].mkv")
        assert r.title == "One Outs"
        assert r.episode_numbers == [1]

    def test_short_group_and_codec_tag(self):
        r = parse_filename("[B2E].One_Outs.14.x264.[AE2C2B0F].mkv")
        assert r.title == "One Outs"
        assert r.episode_numbers == [14]

    def test_tech_bracket_with_resolution(self):
        r = parse_filename(
            "[Nightspeed]_Code_Geass_-_Lelouch_of_the_Rebellion_R2_-_20"
            "_[H.264_1280x720_AAC][7D56A41E].mkv"
        )
        assert r.title == "Code Geass - Lelouch of the Rebellion R2"
        assert r.episode_numbers == [20]

    def test_no_episode_movie_like(self):
        r = parse_filename("Mind.Game.DVD(H264.AC3)[KAA][10954326].mkv")
        assert r.title == "Mind Game"
        assert r.episode_numbers is None
        assert r.season_number is None

    def test_special_episode_name(self):
        r = parse_filename("[Mazui]_Angel_Beats_-_Special_[XviD][E49CD336].avi")
        assert r.title == "Angel Beats"
        assert r.episode_name == "Special"
        assert r.episode_numbers is None


# ---------------------------------------------------------------------------
# _preprocess_fansub unit tests
# ---------------------------------------------------------------------------

class TestPreprocessFansub:
    def test_strips_leading_group(self):
        assert _preprocess_fansub("[SubGroup] Show Name") == "Show Name"

    def test_strips_multiple_leading_groups(self):
        result = _preprocess_fansub("[ANIME-PLUS.COM]_[B2E].One_Outs.01")
        assert result == "One_Outs.01"

    def test_strips_crc_hash(self):
        assert _preprocess_fansub("Show - 01 [7D56A41E]") == "Show - 01"

    def test_strips_xvid_bracket(self):
        assert _preprocess_fansub("Show [XviD]") == "Show"

    def test_strips_tech_paren(self):
        assert _preprocess_fansub("Show 14 (720p x264 AAC)") == "Show 14"

    def test_strips_trailing_dvd(self):
        assert _preprocess_fansub("Mind.Game.DVD") == "Mind.Game"

    def test_preserves_episode_number_bracket(self):
        # [01] should NOT be stripped — it's an episode reference
        result = _preprocess_fansub("Show - [01]")
        assert "[01]" in result


# ---------------------------------------------------------------------------
# Version suffix stripping (e.g. "3v2" treated as episode 3)
# ---------------------------------------------------------------------------

class TestVersionSuffix:
    def test_bare_absolute_v2(self):
        r = parse_filename("Some_Show_-_3v2.mkv")
        assert r.title == "Some Show"
        assert r.episode_numbers == [3]

    def test_bare_absolute_v3_end_of_name(self):
        r = parse_filename("Naruto_-_123v3.mkv")
        assert r.episode_numbers == [123]

    def test_standard_se_with_version(self):
        r = parse_filename("Show.S01E05v2.mkv")
        assert r.season_number == 1
        assert r.episode_numbers == [5]

    def test_version_with_trailing_title(self):
        r = parse_filename("Some_Show_-_3v2_-_Episode_Title.mkv")
        assert r.episode_numbers == [3]
        assert r.title == "Some Show"
