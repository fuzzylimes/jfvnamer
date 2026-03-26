"""Tests for resolver helpers."""

from pathlib import Path

import pytest

from jfvnamer.models import ParsedFile, TVDBEpisode
from jfvnamer.resolver import detect_season_from_path, match_episode


class TestDetectSeasonFromPath:
    def test_season_folder_zero_padded(self, tmp_path):
        season_dir = tmp_path / "Season 02"
        season_dir.mkdir()
        f = season_dir / "episode.mkv"
        assert detect_season_from_path(f) == 2

    def test_season_folder_single_digit(self, tmp_path):
        season_dir = tmp_path / "Season 1"
        season_dir.mkdir()
        f = season_dir / "episode.mkv"
        assert detect_season_from_path(f) == 1

    def test_season_folder_specials(self, tmp_path):
        season_dir = tmp_path / "Season 00"
        season_dir.mkdir()
        f = season_dir / "special.mkv"
        assert detect_season_from_path(f) == 0

    def test_short_form_uppercase(self, tmp_path):
        season_dir = tmp_path / "S03"
        season_dir.mkdir()
        f = season_dir / "episode.mkv"
        assert detect_season_from_path(f) == 3

    def test_short_form_lowercase(self, tmp_path):
        season_dir = tmp_path / "s04"
        season_dir.mkdir()
        f = season_dir / "episode.mkv"
        assert detect_season_from_path(f) == 4

    def test_non_season_folder_returns_none(self, tmp_path):
        other_dir = tmp_path / "Extras"
        other_dir.mkdir()
        f = other_dir / "episode.mkv"
        assert detect_season_from_path(f) is None

    def test_file_at_root_returns_none(self, tmp_path):
        f = tmp_path / "episode.mkv"
        assert detect_season_from_path(f) is None

    def test_case_insensitive(self, tmp_path):
        season_dir = tmp_path / "SEASON 05"
        season_dir.mkdir()
        f = season_dir / "episode.mkv"
        assert detect_season_from_path(f) == 5


def _make_episode(tvdb_id, season, ep, absolute=None, name=None):
    return TVDBEpisode(
        tvdb_id=tvdb_id,
        name=name,
        season_number=season,
        episode_number=ep,
        absolute_number=absolute,
    )


def _parsed(ep_nums, season=None):
    return ParsedFile(
        title="Show",
        season_number=season,
        episode_numbers=ep_nums,
        file_extension=".mkv",
        original_filename="show.mkv",
    )


class TestMatchEpisode:
    def test_season_and_episode_match(self):
        eps = [_make_episode(1, 1, 1), _make_episode(2, 1, 2), _make_episode(3, 2, 1)]
        result = match_episode(_parsed([1], season=2), eps, forced_season=None)
        assert result is not None
        assert result.tvdb_id == 3

    def test_absolute_number_match_no_season(self):
        """File with absolute ep 27 should resolve to S2E1, not S1E27."""
        eps = [
            _make_episode(1, 1, 1, absolute=1),
            _make_episode(2, 1, 2, absolute=2),
            _make_episode(3, 2, 1, absolute=27),
        ]
        result = match_episode(_parsed([27]), eps, forced_season=None)
        assert result is not None
        assert result.tvdb_id == 3
        assert result.season_number == 2
        assert result.episode_number == 1

    def test_absolute_match_takes_priority_over_episode_number(self):
        """When absolute_number matches, prefer it over episode_number."""
        eps = [
            _make_episode(1, 1, 5, absolute=None),   # ep_number=5, no absolute
            _make_episode(2, 2, 1, absolute=5),        # absolute=5
        ]
        result = match_episode(_parsed([5]), eps, forced_season=None)
        assert result is not None
        assert result.tvdb_id == 2  # absolute match wins

    def test_fallback_to_episode_number_when_no_absolute(self):
        """Falls back to episode_number matching when no episode has absolute_number."""
        eps = [
            _make_episode(1, 1, 3, absolute=None),
            _make_episode(2, 1, 5, absolute=None),
        ]
        result = match_episode(_parsed([3]), eps, forced_season=None)
        assert result is not None
        assert result.tvdb_id == 1

    def test_date_match(self):
        ep = TVDBEpisode(
            tvdb_id=99, season_number=1, episode_number=1, aired="2024-01-01"
        )
        parsed = ParsedFile(
            title="Show",
            date=__import__("datetime").date(2024, 1, 1),
            file_extension=".mkv",
            original_filename="show.mkv",
        )
        result = match_episode(parsed, [ep], forced_season=None)
        assert result is not None
        assert result.tvdb_id == 99

    def test_no_match_returns_none(self):
        eps = [_make_episode(1, 1, 1, absolute=1)]
        result = match_episode(_parsed([99]), eps, forced_season=None)
        assert result is None
