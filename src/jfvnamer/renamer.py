"""Path construction and rename/move/copy logic.

Wires together: file scanning -> parsing -> TVDB lookup -> Jellyfin naming
-> filesystem operations. The TVDB lookup step is abstracted via a callback
so the CLI layer can provide interactive disambiguation (Phase 7).
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

from jfvnamer.jellyfin import build_target_path
from jfvnamer.models import (
    SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
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
from jfvnamer.parser import parse_filename

logger = logging.getLogger(__name__)

UNDO_DIR = Path.home() / ".local" / "share" / "jfvnamer" / "undo"

# Type alias for the TVDB resolution callback.
# Given a ParsedFile, the callback returns either:
#   ("series", TVDBSeriesDetails, TVDBEpisode | None)  for TV
#   ("movie", TVDBMovieDetails, None)                   for movies
#   None  if the user chose to skip
TVDBResolveResult = tuple[str, TVDBSeriesDetails | TVDBMovieDetails, TVDBEpisode | None]
TVDBResolver = Callable[[ParsedFile], Optional[TVDBResolveResult]]


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
# Subtitle companion detection
# ---------------------------------------------------------------------------


def find_subtitle_companions(video_path: Path) -> list[Path]:
    """Find subtitle files in the same directory that share the video's stem.

    Matches files like:
      - ``video.srt``
      - ``video.en.srt``  (language tag preserved)
      - ``video.en.forced.srt``
    """
    stem = video_path.stem
    parent = video_path.parent
    companions: list[Path] = []

    for f in parent.iterdir():
        if f == video_path or not f.is_file():
            continue
        # Check if the file starts with the video stem and has a subtitle extension
        fname = f.name
        if not fname.startswith(stem):
            continue
        # The part after the stem should start with a dot (e.g. ".srt", ".en.srt")
        remainder = fname[len(stem):]
        if not remainder.startswith("."):
            continue
        # Check that the final extension is a subtitle extension
        if f.suffix.lower() in SUBTITLE_EXTENSIONS:
            companions.append(f)

    return sorted(companions)


def subtitle_target_name(
    subtitle_path: Path,
    video_stem_old: str,
    video_stem_new: str,
) -> str:
    """Compute the new subtitle filename by replacing the video stem portion.

    Preserves language tags: if the subtitle was ``video.en.srt`` and the
    new video stem is ``New Name - S01E01 - Pilot``, the result is
    ``New Name - S01E01 - Pilot.en.srt``.
    """
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
    """Execute a single rename/move/copy/dryrun action.

    Returns a :class:`RenameResult` with success status.
    """
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
        # Ensure the target directory exists
        dst.parent.mkdir(parents=True, exist_ok=True)

        if action.action == "copy":
            shutil.copy2(str(src), str(dst))
        else:
            # "move" — use shutil.move which handles cross-filesystem moves
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
    """Reverse a previous rename operation using its undo log.

    Moves/copies files back to their original locations.
    """
    data = json.loads(log_path.read_text())
    entry = UndoLogEntry.model_validate(data)
    results: list[RenameResult] = []

    # Process in reverse order so subtitles are undone before videos
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
# Plan + execute: the main rename workflow
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
    """Plan rename actions for a video file and its subtitle companions.

    Returns a list of :class:`RenameAction` objects (video + subtitles).
    """
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

    # Plan subtitle companions
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


def process_files(
    input_path: Path,
    config: AppConfig,
    resolver: TVDBResolver,
    *,
    skip_existing: bool = False,
) -> list[RenameResult]:
    """Main rename workflow: scan, parse, resolve, plan, execute.

    Parameters
    ----------
    input_path:
        File or directory to process.
    config:
        Resolved application configuration.
    resolver:
        Callback that takes a ParsedFile and returns TVDB metadata
        (or None to skip the file). This is where interactive
        disambiguation happens (provided by the CLI layer).
    skip_existing:
        If True, silently skip files whose target already exists.
        If False, log a warning and skip.
    """
    series_root = Path(config.general.series_root)
    movies_root = Path(config.general.movies_root)
    video_files = scan_video_files(input_path, recursive=config.general.recursive)

    if not video_files:
        logger.warning("No video files found in %s", input_path)
        return []

    all_results: list[RenameResult] = []

    for video_path in video_files:
        try:
            parsed = parse_filename(video_path.name)
            logger.debug("Parsed %s -> %s (%s)", video_path.name, parsed.title, parsed.media_type.value)

            # Resolve TVDB metadata via the callback
            resolution = resolver(parsed)
            if resolution is None:
                logger.info("Skipping %s (no TVDB match or user skipped)", video_path.name)
                continue

            result_type, metadata, ep = resolution

            # Build kwargs for plan_rename
            kwargs: dict[str, Any] = {}
            if result_type == "series":
                kwargs["series"] = metadata
                kwargs["episode"] = ep
                library_root = series_root
            else:
                kwargs["movie"] = metadata
                library_root = movies_root

            actions = plan_rename(
                video_path, parsed, library_root, config, **kwargs
            )

            # Check for conflicts
            skip_file = False
            for action in actions:
                if action.action != "dryrun" and check_conflict(Path(action.destination)):
                    if skip_existing:
                        logger.debug("Skipping (exists): %s", action.destination)
                        skip_file = True
                        break
                    else:
                        logger.warning(
                            "Target already exists, skipping: %s", action.destination
                        )
                        skip_file = True
                        break

            if skip_file:
                continue

            # Execute all actions for this file
            for action in actions:
                result = execute_action(action)
                all_results.append(result)
                if result.success:
                    verb = {"move": "Moved", "copy": "Copied", "dryrun": "Would rename"}[result.action]
                    logger.info("%s: %s -> %s", verb, result.source, result.destination)
                else:
                    logger.error("FAILED: %s -> %s: %s", result.source, result.destination, result.error)

        except Exception:
            logger.exception("Error processing %s", video_path.name)
            continue

    # Write undo log
    write_undo_log(all_results)

    return all_results
