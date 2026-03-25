"""Path construction and rename/move/copy logic.

Wires together: file scanning -> parsing -> grouping -> Jellyfin naming
-> filesystem operations. Interactive TVDB resolution lives in the CLI layer.
"""

from __future__ import annotations

import datetime
import json
import logging
import shutil
from pathlib import Path

from jfvnamer.jellyfin import build_target_path
from jfvnamer.models import (
    SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    AppConfig,
    ParsedFile,
    RenameAction,
    RenameResult,
    TVDBEpisode,
    TVDBMovieDetails,
    TVDBSeriesDetails,
    UndoLogEntry,
)
from jfvnamer.parser import parse_filename

logger = logging.getLogger(__name__)

UNDO_DIR = Path.home() / ".local" / "share" / "jfvnamer" / "undo"


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------


def scan_video_files(path: Path, *, recursive: bool = True) -> list[Path]:
    """Find all video files under *path*.

    If *path* is a single file, returns it in a list (if it has a video
    extension). If it's a directory, globs for video files.
    """
    if path.is_file():
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            return [path]
        return []

    if not path.is_dir():
        return []

    pattern = "**/*" if recursive else "*"
    return sorted(
        f for f in path.glob(pattern)
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    )


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def group_files_by_title(
    files: list[Path],
) -> dict[str, list[tuple[Path, ParsedFile]]]:
    """Parse *files* and group them by their parsed title.

    Returns an ordered dict mapping title → list of (path, parsed) pairs,
    preserving the order in which each title is first encountered.
    """
    groups: dict[str, list[tuple[Path, ParsedFile]]] = {}
    for path in files:
        parsed = parse_filename(path.name)
        title = parsed.title
        if title not in groups:
            groups[title] = []
        groups[title].append((path, parsed))
    return groups


# ---------------------------------------------------------------------------
# Subtitle companion detection
# ---------------------------------------------------------------------------


def find_subtitle_companions(video_path: Path) -> list[Path]:
    """Find subtitle files in the same directory that share the video's stem."""
    stem = video_path.stem
    parent = video_path.parent
    companions: list[Path] = []

    for f in parent.iterdir():
        if f == video_path or not f.is_file():
            continue
        fname = f.name
        if not fname.startswith(stem):
            continue
        remainder = fname[len(stem):]
        if not remainder.startswith("."):
            continue
        if f.suffix.lower() in SUBTITLE_EXTENSIONS:
            companions.append(f)

    return sorted(companions)


def subtitle_target_name(
    subtitle_path: Path,
    video_stem_old: str,
    video_stem_new: str,
) -> str:
    """Compute the new subtitle filename by replacing the video stem portion."""
    remainder = subtitle_path.name[len(video_stem_old):]
    return video_stem_new + remainder


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def check_conflict(destination: Path) -> bool:
    """Return True if *destination* already exists."""
    return destination.exists()


# ---------------------------------------------------------------------------
# Filesystem actions
# ---------------------------------------------------------------------------


def execute_action(action: RenameAction) -> RenameResult:
    """Execute a single rename/move/copy/dryrun action."""
    src = Path(action.source)
    dst = Path(action.destination)

    if action.action == "dryrun":
        return RenameResult(
            source=action.source,
            destination=action.destination,
            action="dryrun",
            success=True,
        )

    try:
        dst.parent.mkdir(parents=True, exist_ok=True, mode=0o755)

        if action.action == "copy":
            shutil.copy2(str(src), str(dst))
        else:
            shutil.move(str(src), str(dst))

        return RenameResult(
            source=action.source,
            destination=action.destination,
            action=action.action,
            success=True,
        )
    except OSError as exc:
        logger.error("Failed to %s %s -> %s: %s", action.action, src, dst, exc)
        return RenameResult(
            source=action.source,
            destination=action.destination,
            action=action.action,
            success=False,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Undo log
# ---------------------------------------------------------------------------


def write_undo_log(results: list[RenameResult]) -> Path | None:
    """Write a JSON undo log for the completed actions.

    Only logs successful move/copy actions (not dry-runs).
    Returns the path to the undo log file, or None if there was nothing to log.
    """
    actionable = [r for r in results if r.success and r.action != "dryrun"]
    if not actionable:
        return None

    UNDO_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = UNDO_DIR / f"{timestamp}.json"

    entry = UndoLogEntry(
        timestamp=datetime.datetime.now().isoformat(),
        actions=actionable,
    )
    log_path.write_text(json.dumps(entry.model_dump(mode="json"), indent=2))
    logger.info("Undo log written to %s", log_path)
    return log_path


def undo_rename(log_path: Path) -> list[RenameResult]:
    """Reverse a previous rename operation using its undo log."""
    data = json.loads(log_path.read_text())
    entry = UndoLogEntry.model_validate(data)
    results: list[RenameResult] = []

    for action in reversed(entry.actions):
        reverse_action = RenameAction(
            source=action.destination,
            destination=action.source,
            action=action.action,
        )
        result = execute_action(reverse_action)
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Plan: single file
# ---------------------------------------------------------------------------


def plan_rename(
    video_path: Path,
    parsed: ParsedFile,
    library_root: Path,
    config: AppConfig,
    *,
    series: TVDBSeriesDetails | None = None,
    episode: TVDBEpisode | None = None,
    movie: TVDBMovieDetails | None = None,
) -> list[RenameAction]:
    """Plan rename actions for a video file and its subtitle companions."""
    target_rel = build_target_path(
        parsed,
        series=series,
        episode=episode,
        movie=movie,
        naming=config.naming,
    )

    target_abs = library_root.resolve() / target_rel
    action_type = config.general.action

    actions: list[RenameAction] = [
        RenameAction(
            source=str(video_path.resolve()),
            destination=str(target_abs),
            action=action_type,
        )
    ]

    new_video_stem = Path(target_rel).stem
    for sub_path in find_subtitle_companions(video_path):
        new_sub_name = subtitle_target_name(sub_path, video_path.stem, new_video_stem)
        sub_target = target_abs.parent / new_sub_name
        actions.append(
            RenameAction(
                source=str(sub_path.resolve()),
                destination=str(sub_target),
                action=action_type,
                is_subtitle=True,
            )
        )

    return actions
