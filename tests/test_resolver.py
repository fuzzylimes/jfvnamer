"""Tests for resolver helpers."""

from pathlib import Path

import pytest

from jfvnamer.resolver import detect_season_from_path


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
