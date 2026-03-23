"""Tests for rename/move engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jfvnamer.models import (
    AppConfig,
    MediaType,
    ParsedFile,
    RenameAction,
    RenameResult,
    TVDBEpisode,
    TVDBMovieDetails,
    TVDBSeriesDetails,
    UndoLogEntry,
)
from jfvnamer.renamer import (
    check_conflict,
    execute_action,
    find_subtitle_companions,
    plan_rename,
    process_files,
    scan_video_files,
    subtitle_target_name,
    undo_rename,
    write_undo_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def video_dir(tmp_path: Path) -> Path:
    """Create a temp directory with sample video and subtitle files."""
    (tmp_path / "Breaking Bad - S01E01 - Pilot.mkv").write_text("video")
    (tmp_path / "Breaking Bad - S01E01 - Pilot.srt").write_text("subs")
    (tmp_path / "Breaking Bad - S01E01 - Pilot.en.srt").write_text("subs-en")
    (tmp_path / "Breaking Bad - S01E02 - Cats in the Bag.mkv").write_text("video2")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "Inception (2010).mp4").write_text("movie")
    (tmp_path / "notes.txt").write_text("not a video")
    return tmp_path


@pytest.fixture()
def dryrun_config(tmp_path: Path) -> AppConfig:
    """An AppConfig with action=dryrun and library_root pointing to tmp_path/output."""
    output = tmp_path / "output"
    output.mkdir()
    return AppConfig.model_validate({
        "general": {"library_root": str(output), "action": "dryrun"},
    })


@pytest.fixture()
def move_config(tmp_path: Path) -> AppConfig:
    output = tmp_path / "output"
    output.mkdir()
    return AppConfig.model_validate({
        "general": {"library_root": str(output), "action": "move"},
    })


@pytest.fixture()
def copy_config(tmp_path: Path) -> AppConfig:
    output = tmp_path / "output"
    output.mkdir()
    return AppConfig.model_validate({
        "general": {"library_root": str(output), "action": "copy"},
    })


@pytest.fixture()
def sample_parsed() -> ParsedFile:
    return ParsedFile(
        title="Breaking Bad",
        media_type=MediaType.TV,
        season_number=1,
        episode_numbers=[1],
        file_extension=".mkv",
        original_filename="Breaking Bad - S01E01 - Pilot.mkv",
    )


@pytest.fixture()
def sample_series() -> TVDBSeriesDetails:
    return TVDBSeriesDetails(
        tvdb_id=81189,
        name="Breaking Bad",
        year="2008",
    )


@pytest.fixture()
def sample_episode() -> TVDBEpisode:
    return TVDBEpisode(
        tvdb_id=1,
        name="Pilot",
        season_number=1,
        episode_number=1,
    )


@pytest.fixture()
def sample_movie_parsed() -> ParsedFile:
    return ParsedFile(
        title="Inception",
        media_type=MediaType.MOVIE,
        year=2010,
        file_extension=".mp4",
        original_filename="Inception (2010).mp4",
    )


@pytest.fixture()
def sample_movie() -> TVDBMovieDetails:
    return TVDBMovieDetails(
        tvdb_id=1000,
        name="Inception",
        year="2010",
    )


# ---------------------------------------------------------------------------
# scan_video_files
# ---------------------------------------------------------------------------


class TestScanVideoFiles:
    def test_scan_directory_recursive(self, video_dir: Path) -> None:
        files = scan_video_files(video_dir, recursive=True)
        names = [f.name for f in files]
        assert "Breaking Bad - S01E01 - Pilot.mkv" in names
        assert "Breaking Bad - S01E02 - Cats in the Bag.mkv" in names
        assert "Inception (2010).mp4" in names
        assert "notes.txt" not in names
        assert "Breaking Bad - S01E01 - Pilot.srt" not in names

    def test_scan_directory_non_recursive(self, video_dir: Path) -> None:
        files = scan_video_files(video_dir, recursive=False)
        names = [f.name for f in files]
        assert "Breaking Bad - S01E01 - Pilot.mkv" in names
        assert "Inception (2010).mp4" not in names  # in subdir

    def test_scan_single_file(self, video_dir: Path) -> None:
        video = video_dir / "Breaking Bad - S01E01 - Pilot.mkv"
        files = scan_video_files(video)
        assert files == [video]

    def test_scan_non_video_file(self, video_dir: Path) -> None:
        files = scan_video_files(video_dir / "notes.txt")
        assert files == []

    def test_scan_nonexistent(self, tmp_path: Path) -> None:
        files = scan_video_files(tmp_path / "nope")
        assert files == []


# ---------------------------------------------------------------------------
# find_subtitle_companions
# ---------------------------------------------------------------------------


class TestFindSubtitleCompanions:
    def test_finds_matching_subs(self, video_dir: Path) -> None:
        video = video_dir / "Breaking Bad - S01E01 - Pilot.mkv"
        subs = find_subtitle_companions(video)
        names = [s.name for s in subs]
        assert "Breaking Bad - S01E01 - Pilot.srt" in names
        assert "Breaking Bad - S01E01 - Pilot.en.srt" in names

    def test_no_subs_for_other_video(self, video_dir: Path) -> None:
        video = video_dir / "Breaking Bad - S01E02 - Cats in the Bag.mkv"
        subs = find_subtitle_companions(video)
        assert subs == []

    def test_no_false_positives(self, tmp_path: Path) -> None:
        (tmp_path / "Show.mkv").write_text("vid")
        (tmp_path / "Show2.srt").write_text("sub")  # different stem
        (tmp_path / "ShowExtra.srt").write_text("sub")  # starts with stem but no dot
        subs = find_subtitle_companions(tmp_path / "Show.mkv")
        assert subs == []


# ---------------------------------------------------------------------------
# subtitle_target_name
# ---------------------------------------------------------------------------


class TestSubtitleTargetName:
    def test_simple_srt(self) -> None:
        result = subtitle_target_name(
            Path("Breaking Bad - S01E01 - Pilot.srt"),
            "Breaking Bad - S01E01 - Pilot",
            "Breaking Bad - S01E01 - Pilot",
        )
        assert result == "Breaking Bad - S01E01 - Pilot.srt"

    def test_language_tag(self) -> None:
        result = subtitle_target_name(
            Path("old name.en.srt"),
            "old name",
            "New Name - S01E01 - Title",
        )
        assert result == "New Name - S01E01 - Title.en.srt"

    def test_forced_language_tag(self) -> None:
        result = subtitle_target_name(
            Path("old name.en.forced.srt"),
            "old name",
            "New Name - S01E01",
        )
        assert result == "New Name - S01E01.en.forced.srt"


# ---------------------------------------------------------------------------
# check_conflict
# ---------------------------------------------------------------------------


class TestCheckConflict:
    def test_no_conflict(self, tmp_path: Path) -> None:
        assert check_conflict(tmp_path / "nonexistent.mkv") is False

    def test_conflict_exists(self, tmp_path: Path) -> None:
        target = tmp_path / "exists.mkv"
        target.write_text("data")
        assert check_conflict(target) is True


# ---------------------------------------------------------------------------
# execute_action
# ---------------------------------------------------------------------------


class TestExecuteAction:
    def test_dryrun(self, tmp_path: Path) -> None:
        src = tmp_path / "video.mkv"
        src.write_text("data")
        action = RenameAction(
            source=str(src),
            destination=str(tmp_path / "output" / "video.mkv"),
            action="dryrun",
        )
        result = execute_action(action)
        assert result.success
        assert result.action == "dryrun"
        assert src.exists()  # source untouched
        assert not (tmp_path / "output" / "video.mkv").exists()

    def test_move(self, tmp_path: Path) -> None:
        src = tmp_path / "video.mkv"
        dst = tmp_path / "output" / "video.mkv"
        src.write_text("data")
        action = RenameAction(source=str(src), destination=str(dst), action="move")
        result = execute_action(action)
        assert result.success
        assert not src.exists()
        assert dst.exists()
        assert dst.read_text() == "data"

    def test_copy(self, tmp_path: Path) -> None:
        src = tmp_path / "video.mkv"
        dst = tmp_path / "output" / "video.mkv"
        src.write_text("data")
        action = RenameAction(source=str(src), destination=str(dst), action="copy")
        result = execute_action(action)
        assert result.success
        assert src.exists()  # source still there
        assert dst.exists()
        assert dst.read_text() == "data"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        src = tmp_path / "video.mkv"
        dst = tmp_path / "deep" / "nested" / "dir" / "video.mkv"
        src.write_text("data")
        action = RenameAction(source=str(src), destination=str(dst), action="move")
        result = execute_action(action)
        assert result.success
        assert dst.exists()

    def test_move_nonexistent_source(self, tmp_path: Path) -> None:
        action = RenameAction(
            source=str(tmp_path / "nope.mkv"),
            destination=str(tmp_path / "out.mkv"),
            action="move",
        )
        result = execute_action(action)
        assert not result.success
        assert result.error is not None


# ---------------------------------------------------------------------------
# plan_rename
# ---------------------------------------------------------------------------


class TestPlanRename:
    def test_tv_episode_plan(
        self,
        tmp_path: Path,
        dryrun_config: AppConfig,
        sample_parsed: ParsedFile,
        sample_series: TVDBSeriesDetails,
        sample_episode: TVDBEpisode,
    ) -> None:
        video = tmp_path / "Breaking Bad - S01E01 - Pilot.mkv"
        video.write_text("data")
        actions = plan_rename(
            video,
            sample_parsed,
            Path(dryrun_config.general.library_root),
            dryrun_config,
            series=sample_series,
            episode=sample_episode,
        )
        assert len(actions) == 1
        assert actions[0].action == "dryrun"
        assert "Breaking Bad (2008)" in actions[0].destination
        assert "Season 01" in actions[0].destination
        assert "S01E01" in actions[0].destination
        assert actions[0].destination.endswith(".mkv")

    def test_movie_plan(
        self,
        tmp_path: Path,
        dryrun_config: AppConfig,
        sample_movie_parsed: ParsedFile,
        sample_movie: TVDBMovieDetails,
    ) -> None:
        video = tmp_path / "Inception (2010).mp4"
        video.write_text("data")
        actions = plan_rename(
            video,
            sample_movie_parsed,
            Path(dryrun_config.general.library_root),
            dryrun_config,
            movie=sample_movie,
        )
        assert len(actions) == 1
        assert "Inception (2010)" in actions[0].destination
        assert actions[0].destination.endswith(".mp4")

    def test_includes_subtitle_companions(
        self,
        video_dir: Path,
        dryrun_config: AppConfig,
        sample_parsed: ParsedFile,
        sample_series: TVDBSeriesDetails,
        sample_episode: TVDBEpisode,
    ) -> None:
        video = video_dir / "Breaking Bad - S01E01 - Pilot.mkv"
        actions = plan_rename(
            video,
            sample_parsed,
            Path(dryrun_config.general.library_root),
            dryrun_config,
            series=sample_series,
            episode=sample_episode,
        )
        # video + 2 subtitle files (.srt and .en.srt)
        assert len(actions) == 3
        sub_actions = [a for a in actions if a.is_subtitle]
        assert len(sub_actions) == 2
        sub_names = [Path(a.destination).name for a in sub_actions]
        assert any(n.endswith(".srt") and ".en." not in n for n in sub_names)
        assert any(".en.srt" in n for n in sub_names)


# ---------------------------------------------------------------------------
# write_undo_log / undo_rename
# ---------------------------------------------------------------------------


class TestUndoLog:
    def test_write_and_read_undo_log(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("jfvnamer.renamer.UNDO_DIR", tmp_path / "undo")
        results = [
            RenameResult(
                source="/src/video.mkv",
                destination="/dst/video.mkv",
                action="move",
                success=True,
            ),
        ]
        log_path = write_undo_log(results)
        assert log_path is not None
        assert log_path.exists()

        data = json.loads(log_path.read_text())
        entry = UndoLogEntry.model_validate(data)
        assert len(entry.actions) == 1
        assert entry.actions[0].source == "/src/video.mkv"

    def test_no_log_for_dryrun(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("jfvnamer.renamer.UNDO_DIR", tmp_path / "undo")
        results = [
            RenameResult(
                source="/src/video.mkv",
                destination="/dst/video.mkv",
                action="dryrun",
                success=True,
            ),
        ]
        assert write_undo_log(results) is None

    def test_undo_reverses_move(self, tmp_path: Path) -> None:
        # Set up: file at "destination"
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
                )
            ],
        )
        log_path.write_text(json.dumps(entry.model_dump(mode="json"), indent=2))

        results = undo_rename(log_path)
        assert len(results) == 1
        assert results[0].success
        assert original_src.exists()
        assert not dst.exists()


# ---------------------------------------------------------------------------
# process_files (integration-style test with dryrun)
# ---------------------------------------------------------------------------


class TestProcessFiles:
    def test_dryrun_produces_results(self, video_dir: Path, dryrun_config: AppConfig) -> None:
        def resolver(parsed: ParsedFile):
            if parsed.media_type == MediaType.TV:
                series = TVDBSeriesDetails(tvdb_id=1, name=parsed.title, year="2008")
                episode = TVDBEpisode(
                    tvdb_id=1,
                    name="Pilot",
                    season_number=parsed.season_number or 1,
                    episode_number=(parsed.episode_numbers or [1])[0],
                )
                return ("series", series, episode)
            elif parsed.media_type == MediaType.MOVIE:
                movie = TVDBMovieDetails(
                    tvdb_id=1, name=parsed.title, year=str(parsed.year) if parsed.year else None
                )
                return ("movie", movie, None)
            return None

        results = process_files(video_dir, dryrun_config, resolver)
        # Should have results for all 3 video files (+ 2 subs for S01E01)
        assert len(results) > 0
        assert all(r.action == "dryrun" for r in results)
        assert all(r.success for r in results)

    def test_skip_existing(self, tmp_path: Path, copy_config: AppConfig) -> None:
        video = tmp_path / "Breaking Bad - S01E01 - Pilot.mkv"
        video.write_text("data")

        # Pre-create the target so there's a conflict
        output = Path(copy_config.general.library_root)
        target = output / "Breaking Bad (2008)" / "Season 01" / "Breaking Bad - S01E01 - Pilot.mkv"
        target.parent.mkdir(parents=True)
        target.write_text("existing")

        def resolver(parsed: ParsedFile):
            series = TVDBSeriesDetails(tvdb_id=1, name="Breaking Bad", year="2008")
            episode = TVDBEpisode(tvdb_id=1, name="Pilot", season_number=1, episode_number=1)
            return ("series", series, episode)

        results = process_files(tmp_path, copy_config, resolver, skip_existing=True)
        assert len(results) == 0  # skipped due to conflict
        assert target.read_text() == "existing"  # untouched

    def test_resolver_skip(self, video_dir: Path, dryrun_config: AppConfig) -> None:
        """Resolver returning None means skip the file."""
        results = process_files(video_dir, dryrun_config, lambda _: None)
        assert len(results) == 0

    def test_move_actually_moves(self, tmp_path: Path, move_config: AppConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        # Suppress undo log to a temp location
        monkeypatch.setattr("jfvnamer.renamer.UNDO_DIR", tmp_path / "undo")

        video = tmp_path / "Inception (2010).mp4"
        video.write_text("movie data")

        def resolver(parsed: ParsedFile):
            movie = TVDBMovieDetails(tvdb_id=1, name="Inception", year="2010")
            return ("movie", movie, None)

        results = process_files(tmp_path, move_config, resolver)
        assert len(results) == 1
        assert results[0].success
        assert not video.exists()  # moved away

        output = Path(move_config.general.library_root)
        target = output / "Inception (2010)" / "Inception (2010).mp4"
        assert target.exists()
        assert target.read_text() == "movie data"
