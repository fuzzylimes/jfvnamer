"""Tests for the CLI interface (Phase 7 commands and helpers)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from jfvnamer.cli import (
    _DVD_SOURCE_RE,
    _match_episode,
    _prompt_disambiguation,
    _prompt_ordering,
    _select_ordering,
    app,
)
from jfvnamer.models import (
    AppConfig,
    MediaType,
    ParsedFile,
    RenameResult,
    TVDBEpisode,
    TVDBMovieDetails,
    TVDBSearchResult,
    TVDBSeriesDetails,
    UndoLogEntry,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def parsed_tv() -> ParsedFile:
    return ParsedFile(
        title="Breaking Bad",
        media_type=MediaType.TV,
        season_number=1,
        episode_numbers=[1],
        file_extension=".mkv",
        original_filename="Breaking Bad - S01E01 - Pilot.mkv",
    )


@pytest.fixture()
def parsed_movie() -> ParsedFile:
    return ParsedFile(
        title="Inception",
        media_type=MediaType.MOVIE,
        year=2010,
        file_extension=".mkv",
        original_filename="Inception (2010).mkv",
    )


@pytest.fixture()
def search_results() -> list[TVDBSearchResult]:
    return [
        TVDBSearchResult(tvdb_id=77551, name="The Batman", type="series", year="2004"),
        TVDBSearchResult(tvdb_id=331482, name="The Batman", type="movie", year="2022"),
        TVDBSearchResult(tvdb_id=77871, name="Batman", type="series", year="1966"),
    ]


@pytest.fixture()
def sample_episodes() -> list[TVDBEpisode]:
    return [
        TVDBEpisode(tvdb_id=1, name="Pilot", season_number=1, episode_number=1, aired="2008-01-20"),
        TVDBEpisode(tvdb_id=2, name="Cat's in the Bag...", season_number=1, episode_number=2, aired="2008-01-27"),
        TVDBEpisode(tvdb_id=3, name="...And the Bag's in the River", season_number=1, episode_number=3),
        TVDBEpisode(tvdb_id=4, name="Special", season_number=0, episode_number=1),
    ]


# ---------------------------------------------------------------------------
# parse command
# ---------------------------------------------------------------------------


class TestParseCommand:
    def test_parse_file(self, tmp_path: Path) -> None:
        video = tmp_path / "Breaking Bad - S01E01 - Pilot.mkv"
        video.write_text("data")
        result = runner.invoke(app, ["parse", str(video)])
        assert result.exit_code == 0
        assert "Breaking Bad" in result.output
        assert "tv" in result.output

    def test_parse_json(self, tmp_path: Path) -> None:
        video = tmp_path / "Inception (2010).mkv"
        video.write_text("data")
        result = runner.invoke(app, ["parse", str(video), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["title"] == "Inception"

    def test_parse_nonexistent(self) -> None:
        result = runner.invoke(app, ["parse", "/does/not/exist"])
        assert result.exit_code == 1

    def test_parse_no_video_files(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("not a video")
        result = runner.invoke(app, ["parse", str(tmp_path)])
        assert result.exit_code == 1
        assert "No video files" in result.output


# ---------------------------------------------------------------------------
# search command
# ---------------------------------------------------------------------------


class TestSearchCommand:
    def test_search_no_api_key(self) -> None:
        result = runner.invoke(app, ["search", "Breaking Bad"])
        assert result.exit_code != 0

    @patch("jfvnamer.tvdb.TVDBClient")
    @patch("jfvnamer.config.validate_api_key")
    @patch("jfvnamer.config.load_config")
    def test_search_shows_results(self, mock_load, mock_validate, mock_client_cls) -> None:
        cfg = AppConfig(tvdb={"api_key": "key"})
        mock_load.return_value = cfg

        mock_client = MagicMock()
        mock_client.search.return_value = [
            TVDBSearchResult(tvdb_id=81189, name="Breaking Bad", type="series", year="2008"),
        ]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["search", "Breaking Bad"])
        assert result.exit_code == 0
        assert "Breaking Bad" in result.output
        assert "81189" in result.output
        assert "[Series]" in result.output

    @patch("jfvnamer.tvdb.TVDBClient")
    @patch("jfvnamer.config.validate_api_key")
    @patch("jfvnamer.config.load_config")
    def test_search_no_results(self, mock_load, mock_validate, mock_client_cls) -> None:
        cfg = AppConfig(tvdb={"api_key": "key"})
        mock_load.return_value = cfg

        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["search", "Nonexistent Show XYZ"])
        assert result.exit_code == 1
        assert "No results" in result.output


# ---------------------------------------------------------------------------
# cache clear command
# ---------------------------------------------------------------------------


class TestCacheClearCommand:
    @patch("jfvnamer.tvdb.TVDBClient.clear_cache")
    def test_cache_clear(self, mock_clear) -> None:
        result = runner.invoke(app, ["cache", "clear"])
        assert result.exit_code == 0
        assert "Cache cleared" in result.output
        mock_clear.assert_called_once()


# ---------------------------------------------------------------------------
# undo command
# ---------------------------------------------------------------------------


class TestUndoCommand:
    def test_undo_no_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("jfvnamer.renamer.UNDO_DIR", tmp_path / "undo")
        result = runner.invoke(app, ["undo"])
        assert result.exit_code == 1
        assert "No undo logs" in result.output

    def test_undo_nonexistent_file(self) -> None:
        result = runner.invoke(app, ["undo", "/does/not/exist.json"])
        assert result.exit_code == 1

    def test_undo_with_log(self, tmp_path: Path) -> None:
        # Create source file at "destination" for undo to move back
        dst = tmp_path / "dst" / "video.mkv"
        dst.parent.mkdir(parents=True)
        dst.write_text("video data")
        original_src = tmp_path / "src" / "video.mkv"
        original_src.parent.mkdir(parents=True)

        log_path = tmp_path / "undo.json"
        entry = UndoLogEntry(
            timestamp="2026-01-01T00:00:00",
            actions=[
                RenameResult(
                    source=str(original_src),
                    destination=str(dst),
                    action="move",
                    success=True,
                ),
            ],
        )
        log_path.write_text(json.dumps(entry.model_dump(mode="json"), indent=2))

        result = runner.invoke(app, ["undo", str(log_path)])
        assert result.exit_code == 0
        assert "1 reversed" in result.output
        assert original_src.exists()

    def test_undo_picks_most_recent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        undo_dir = tmp_path / "undo"
        undo_dir.mkdir()
        monkeypatch.setattr("jfvnamer.renamer.UNDO_DIR", undo_dir)

        # Create a dummy undo log
        log = undo_dir / "20260101_000000.json"
        entry = UndoLogEntry(timestamp="2026-01-01T00:00:00", actions=[])
        log.write_text(json.dumps(entry.model_dump(mode="json"), indent=2))

        with patch("jfvnamer.renamer.undo_rename", return_value=[]):
            result = runner.invoke(app, ["undo"])
        assert result.exit_code == 0
        assert "20260101_000000.json" in result.output


# ---------------------------------------------------------------------------
# Interactive disambiguation: _prompt_disambiguation
# ---------------------------------------------------------------------------


class TestPromptDisambiguation:
    def test_single_result_auto_selects(self, search_results: list[TVDBSearchResult]) -> None:
        single = [search_results[0]]
        result = _prompt_disambiguation("The Batman", single)
        assert result == (77551, "series")

    def test_no_results(self) -> None:
        result = _prompt_disambiguation("Nothing", [])
        assert result is None

    def test_no_prompt_picks_first(self, search_results: list[TVDBSearchResult]) -> None:
        result = _prompt_disambiguation("The Batman", search_results, no_prompt=True)
        assert result == (77551, "series")

    def test_user_selects_number(self, search_results: list[TVDBSearchResult]) -> None:
        with patch("jfvnamer.cli.typer.prompt", return_value="2"):
            result = _prompt_disambiguation("The Batman", search_results)
        assert result == (331482, "movie")

    def test_user_selects_skip(self, search_results: list[TVDBSearchResult]) -> None:
        with patch("jfvnamer.cli.typer.prompt", return_value="s"):
            result = _prompt_disambiguation("The Batman", search_results)
        assert result is None

    def test_user_selects_quit(self, search_results: list[TVDBSearchResult]) -> None:
        from click.exceptions import Exit as ClickExit

        with patch("jfvnamer.cli.typer.prompt", return_value="q"):
            with pytest.raises(ClickExit):
                _prompt_disambiguation("The Batman", search_results)

    def test_user_selects_manual_id(self, search_results: list[TVDBSearchResult]) -> None:
        with patch("jfvnamer.cli.typer.prompt", side_effect=["i", "99999", "s"]):
            result = _prompt_disambiguation("The Batman", search_results)
        assert result == (99999, "series")

    def test_user_selects_manual_movie_id(self, search_results: list[TVDBSearchResult]) -> None:
        with patch("jfvnamer.cli.typer.prompt", side_effect=["i", "55555", "m"]):
            result = _prompt_disambiguation("The Batman", search_results)
        assert result == (55555, "movie")

    def test_invalid_selection_retries(self, search_results: list[TVDBSearchResult]) -> None:
        with patch("jfvnamer.cli.typer.prompt", side_effect=["invalid", "0", "99", "1"]):
            result = _prompt_disambiguation("The Batman", search_results)
        assert result == (77551, "series")


# ---------------------------------------------------------------------------
# Episode ordering: _prompt_ordering
# ---------------------------------------------------------------------------


class TestPromptOrdering:
    def test_single_choice_auto_selects(self) -> None:
        result = _prompt_ordering(
            "Show",
            ["default"],
            {"default": {"seasons": 5, "episodes": 50}},
        )
        assert result == "aired"

    def test_no_choices_defaults_aired(self) -> None:
        result = _prompt_ordering("Show", [], {})
        assert result == "aired"

    def test_auto_dvd(self) -> None:
        result = _prompt_ordering(
            "Show",
            ["default", "dvd"],
            {"default": {"seasons": 5, "episodes": 50}, "dvd": {"seasons": 5, "episodes": 50}},
            auto_dvd=True,
        )
        assert result == "dvd"

    def test_user_selects_ordering(self) -> None:
        with patch("jfvnamer.cli.typer.prompt", return_value="2"):
            result = _prompt_ordering(
                "Show",
                ["default", "dvd", "absolute"],
                {
                    "default": {"seasons": 5, "episodes": 50},
                    "dvd": {"seasons": 5, "episodes": 48},
                    "absolute": {"seasons": 0, "episodes": 50},
                },
            )
        assert result == "dvd"

    def test_user_selects_absolute(self) -> None:
        with patch("jfvnamer.cli.typer.prompt", return_value="3"):
            result = _prompt_ordering(
                "Show",
                ["default", "dvd", "absolute"],
                {
                    "default": {"seasons": 5, "episodes": 50},
                    "dvd": {"seasons": 5, "episodes": 48},
                    "absolute": {"seasons": 0, "episodes": 50},
                },
            )
        assert result == "absolute"


# ---------------------------------------------------------------------------
# Episode matching: _match_episode
# ---------------------------------------------------------------------------


class TestMatchEpisode:
    def test_match_by_season_episode(self, parsed_tv: ParsedFile, sample_episodes: list[TVDBEpisode]) -> None:
        client = MagicMock()
        client.get_episodes.return_value = sample_episodes
        ep = _match_episode(parsed_tv, client, 81189, order="aired", forced_season=None)
        assert ep is not None
        assert ep.name == "Pilot"
        assert ep.season_number == 1
        assert ep.episode_number == 1

    def test_match_by_date(self, sample_episodes: list[TVDBEpisode]) -> None:
        import datetime

        parsed = ParsedFile(
            title="Breaking Bad",
            media_type=MediaType.TV,
            date=datetime.date(2008, 1, 20),
            file_extension=".mkv",
            original_filename="Breaking.Bad.2008.01.20.mkv",
        )
        client = MagicMock()
        client.get_episodes.return_value = sample_episodes
        ep = _match_episode(parsed, client, 81189, order="aired", forced_season=None)
        assert ep is not None
        assert ep.name == "Pilot"

    def test_no_match(self, sample_episodes: list[TVDBEpisode]) -> None:
        parsed = ParsedFile(
            title="Breaking Bad",
            media_type=MediaType.TV,
            season_number=9,
            episode_numbers=[99],
            file_extension=".mkv",
            original_filename="Breaking Bad - S09E99.mkv",
        )
        client = MagicMock()
        client.get_episodes.return_value = sample_episodes
        ep = _match_episode(parsed, client, 81189, order="aired", forced_season=None)
        assert ep is None

    def test_forced_season_overrides(self, sample_episodes: list[TVDBEpisode]) -> None:
        parsed = ParsedFile(
            title="Breaking Bad",
            media_type=MediaType.TV,
            season_number=5,
            episode_numbers=[1],
            file_extension=".mkv",
            original_filename="Breaking Bad - S05E01.mkv",
        )
        client = MagicMock()
        client.get_episodes.return_value = sample_episodes
        ep = _match_episode(parsed, client, 81189, order="aired", forced_season=1)
        assert ep is not None
        assert ep.name == "Pilot"

    def test_absolute_match_no_season(self, sample_episodes: list[TVDBEpisode]) -> None:
        parsed = ParsedFile(
            title="Show",
            media_type=MediaType.TV,
            season_number=None,
            episode_numbers=[1],
            file_extension=".mkv",
            original_filename="Show - 001.mkv",
        )
        client = MagicMock()
        client.get_episodes.return_value = sample_episodes
        ep = _match_episode(parsed, client, 1, order="absolute", forced_season=None)
        assert ep is not None
        assert ep.episode_number == 1


# ---------------------------------------------------------------------------
# DVD auto-detection regex
# ---------------------------------------------------------------------------


class TestDVDAutoDetection:
    @pytest.mark.parametrize(
        "filename",
        [
            "show.s01e01.dvdrip.mkv",
            "show.s01e01.DVDRip.mkv",
            "show.s01e01.bluray.mkv",
            "show.s01e01.blu-ray.mkv",
            "show.s01e01.Blu-Ray.mkv",
            "show.s01e01.bdrip.mkv",
            "show.s01e01.dvd.mkv",
        ],
    )
    def test_matches_dvd_source(self, filename: str) -> None:
        assert _DVD_SOURCE_RE.search(filename) is not None

    @pytest.mark.parametrize(
        "filename",
        [
            "show.s01e01.hdtv.mkv",
            "show.s01e01.web-dl.mkv",
            "show.s01e01.720p.mkv",
        ],
    )
    def test_no_match_non_dvd(self, filename: str) -> None:
        assert _DVD_SOURCE_RE.search(filename) is None


# ---------------------------------------------------------------------------
# Select ordering logic
# ---------------------------------------------------------------------------


class TestSelectOrdering:
    def test_no_prompt_uses_default(self, parsed_tv: ParsedFile) -> None:
        series = TVDBSeriesDetails(
            tvdb_id=1, name="Show", season_types=["default", "dvd"]
        )
        client = MagicMock()
        result = _select_ordering(
            parsed_tv, client, series,
            default_order="aired", no_prompt=True,
        )
        assert result == "aired"

    def test_no_prompt_auto_dvd_from_filename(self) -> None:
        parsed = ParsedFile(
            title="Show",
            media_type=MediaType.TV,
            season_number=1,
            episode_numbers=[1],
            file_extension=".mkv",
            original_filename="show.s01e01.dvdrip.mkv",
        )
        series = TVDBSeriesDetails(
            tvdb_id=1, name="Show", season_types=["default", "dvd"]
        )
        client = MagicMock()
        result = _select_ordering(
            parsed, client, series,
            default_order="aired", no_prompt=True,
        )
        assert result == "dvd"

    def test_single_season_type_returns_default(self, parsed_tv: ParsedFile) -> None:
        series = TVDBSeriesDetails(
            tvdb_id=1, name="Show", season_types=["default"]
        )
        client = MagicMock()
        result = _select_ordering(
            parsed_tv, client, series,
            default_order="aired", no_prompt=False,
        )
        assert result == "aired"


# ---------------------------------------------------------------------------
# rename command (integration-level)
# ---------------------------------------------------------------------------


class TestRenameCommand:
    def test_rename_nonexistent_path(self) -> None:
        with patch("jfvnamer.config.load_config") as mock_config, \
             patch("jfvnamer.config.validate_api_key"):
            mock_config.return_value = AppConfig(tvdb={"api_key": "key"})
            result = runner.invoke(app, ["rename", "/does/not/exist"])
        assert result.exit_code == 1

    def test_rename_dryrun(self, tmp_path: Path) -> None:
        video = tmp_path / "Breaking Bad - S01E01 - Pilot.mkv"
        video.write_text("data")
        output = tmp_path / "output"
        output.mkdir()

        with patch("jfvnamer.config.load_config") as mock_config, \
             patch("jfvnamer.config.validate_api_key"), \
             patch("jfvnamer.tvdb.TVDBClient") as mock_client_cls:

            mock_config.return_value = AppConfig.model_validate({
                "general": {"series_root": str(output), "movies_root": str(output), "action": "dryrun"},
                "tvdb": {"api_key": "key"},
            })

            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_cached_search.return_value = {
                "tvdb_id": 81189, "type": "series", "name": "Breaking Bad",
            }
            mock_client.get_series_details.return_value = TVDBSeriesDetails(
                tvdb_id=81189, name="Breaking Bad", year="2008", season_types=["default"],
            )
            mock_client.get_episodes.return_value = [
                TVDBEpisode(tvdb_id=1, name="Pilot", season_number=1, episode_number=1),
            ]

            result = runner.invoke(app, ["rename", str(video)])

        assert result.exit_code == 0
        assert "Dry run" in result.output or "would be renamed" in result.output

    def test_rename_with_movie_id(self, tmp_path: Path) -> None:
        video = tmp_path / "Inception (2010).mkv"
        video.write_text("data")
        output = tmp_path / "output"
        output.mkdir()

        with patch("jfvnamer.config.load_config") as mock_config, \
             patch("jfvnamer.config.validate_api_key"), \
             patch("jfvnamer.tvdb.TVDBClient") as mock_client_cls:

            mock_config.return_value = AppConfig.model_validate({
                "general": {"series_root": str(output), "movies_root": str(output), "action": "dryrun"},
                "tvdb": {"api_key": "key"},
            })

            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_movie_details.return_value = TVDBMovieDetails(
                tvdb_id=1000, name="Inception", year="2010",
            )

            result = runner.invoke(app, ["rename", str(video), "--movie-id", "1000"])

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# version flag
# ---------------------------------------------------------------------------


class TestVersionFlag:
    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "jfvnamer" in result.output


# ---------------------------------------------------------------------------
# help output
# ---------------------------------------------------------------------------


class TestHelpOutput:
    def test_main_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "rename" in result.output
        assert "parse" in result.output
        assert "search" in result.output
        assert "undo" in result.output
        assert "cache" in result.output
        assert "config" in result.output

    def test_rename_help(self) -> None:
        result = runner.invoke(app, ["rename", "--help"])
        assert result.exit_code == 0
        assert "--order" in result.output
        assert "--action" in result.output
        assert "--series-root" in result.output
        assert "--movies-root" in result.output
        assert "--no-prompt" in result.output
        assert "--series-id" in result.output
        assert "--movie-id" in result.output
        assert "--season" in result.output
        assert "--skip-existing" in result.output
        assert "--verbose" in result.output
