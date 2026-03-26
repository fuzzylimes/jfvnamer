"""Interactive rename flow: TVDB search, selection, episode matching, and execution."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import typer

from jfvnamer.models import (
    AppConfig,
    ParsedFile,
    RenameAction,
    RenameResult,
    TVDBEpisode,
    TVDBSearchResult,
    TVDBSeriesDetails,
)
from jfvnamer.renamer import check_conflict, execute_action, plan_rename
from jfvnamer.tvdb import TVDBClient

logger = logging.getLogger(__name__)

_SEASON_DIR_RE = re.compile(r'^(?:season|s)\s*0*(\d+)$', re.IGNORECASE)


def detect_season_from_path(path: Path) -> int | None:
    """Return the season number implied by the parent directory name, or None.

    Recognises patterns like ``Season 01``, ``Season 1``, ``S01``, ``S2``.
    """
    m = _SEASON_DIR_RE.match(path.parent.name)
    return int(m.group(1)) if m else None


def run_group_interactive(
    title: str,
    group: list[tuple[Path, ParsedFile]],
    *,
    client: TVDBClient,
    config: AppConfig,
    no_prompt: bool,
    forced_series_id: int | None,
    forced_movie_id: int | None,
    forced_season: int | None,
    skip_existing: bool,
    series_details_cache: dict[int, TVDBSeriesDetails],
) -> list[RenameResult]:
    """Process one group of files with the interactive rename flow.

    ``series_details_cache`` is a shared dict that persists across calls so
    that repeated lookups for the same series ID hit the cache rather than
    the API.
    """
    typer.echo(f"\nSearching: {title}")

    # --- Step 1: Determine TVDB selection ---
    if forced_movie_id is not None:
        tvdb_id, result_type = forced_movie_id, "movie"
    elif forced_series_id is not None:
        tvdb_id, result_type = forced_series_id, "series"
    else:
        selection = search_tvdb_loop(title, client, no_prompt=no_prompt)
        if selection is None:
            typer.echo(f"  Skipping group: {title}")
            return []
        tvdb_id, result_type = selection

    series_root = Path(config.general.series_root)
    movies_root = Path(config.general.movies_root)

    # --- Movie path ---
    if result_type == "movie":
        movie = client.get_movie_details(tvdb_id)
        all_actions = []
        for video_path, parsed in group:
            all_actions.extend(plan_rename(
                video_path, parsed, movies_root, config, movie=movie,
            ))
        display_planned_actions(all_actions)
        if not no_prompt:
            if not typer.confirm("Confirm these renames?", default=True):
                return []
        return execute_with_conflict_check(all_actions, skip_existing=skip_existing)

    # --- Series path ---
    season_type = "default"

    while True:
        if tvdb_id not in series_details_cache:
            series_details_cache[tvdb_id] = client.get_series_details(tvdb_id)
        series = series_details_cache[tvdb_id]

        episodes = client.get_episodes(tvdb_id, season_type=season_type)

        all_actions = []
        for video_path, parsed in group:
            effective_season = forced_season
            if effective_season is None:
                effective_season = detect_season_from_path(video_path)
            ep = match_episode(parsed, episodes, forced_season=effective_season)
            all_actions.extend(plan_rename(
                video_path, parsed, series_root, config,
                series=series, episode=ep,
            ))

        display_planned_actions(all_actions)

        # In non-interactive mode, proceed immediately without confirmation.
        # Use --action dryrun to preview safely in CI/scripting contexts.
        if no_prompt:
            break

        choice = typer.prompt(
            "[c]onfirm, [t]ry different season type, [s]kip group, [q]uit",
            default="c",
        ).strip().lower()

        if choice == "q":
            raise typer.Exit(0)
        if choice == "s":
            return []
        if choice == "c":
            break
        if choice == "t":
            season_type = prompt_season_type(series)
        # any other input: re-display and re-prompt

    return execute_with_conflict_check(all_actions, skip_existing=skip_existing)


def search_tvdb_loop(
    title: str,
    client: TVDBClient,
    *,
    no_prompt: bool,
) -> tuple[int, str] | None:
    """Search TVDB with re-search support. Returns (tvdb_id, type) or None to skip."""
    query = title
    while True:
        results = client.search(query)

        if not results:
            typer.echo(f'  No results found for "{query}".')
        else:
            display_search_results(results)

        if no_prompt:
            if results:
                r = results[0]
                year_str = f" ({r.year})" if r.year else ""
                typer.echo(
                    f"  Auto-selected: [{r.type.capitalize()}] {r.name}{year_str} — TVDB ID: {r.tvdb_id}"
                )
                return (r.tvdb_id, r.type)
            return None

        options = f"[1-{len(results)}, " if results else "["
        options += "s=search again, i=TVDB ID, k=skip, q=quit]"
        choice = typer.prompt(f"  Select {options}").strip().lower()

        if choice == "q":
            raise typer.Exit(0)
        if choice == "k":
            return None
        if choice == "s":
            query = typer.prompt("  Search query").strip()
            continue
        if choice == "i":
            return prompt_manual_tvdb_id()
        try:
            idx = int(choice)
            if results and 1 <= idx <= len(results):
                r = results[idx - 1]
                return (r.tvdb_id, r.type)
        except ValueError:
            pass
        typer.echo("  Invalid selection, try again.")


def display_search_results(results: list[TVDBSearchResult]) -> None:
    for i, r in enumerate(results, 1):
        label = f"[{r.type.capitalize()}]"
        year_str = "" if (
            r.year and r.year in r.name) else f" ({r.year})" if r.year else ""
        genre_str = f"  [{', '.join(r.genres[:3])}]" if r.genres else ""
        typer.echo(
            f"  {i:>2}. {label:<10} {r.name}{year_str}{genre_str} — TVDB ID: {r.tvdb_id}")


def display_planned_actions(actions: list[RenameAction]) -> None:
    """Print planned rename actions grouped by source."""
    typer.echo("")
    for action in actions:
        src = Path(action.source).name
        dst = action.destination
        typer.echo(f"  {src}")
        typer.echo(f"    → {dst}")
    typer.echo("")


def prompt_season_type(series: TVDBSeriesDetails) -> str:
    """Let the user pick a season type from the available types."""
    if not series.season_types:
        typer.echo("  No alternative season types available.")
        return "default"

    typer.echo(f"\n  Available season types for {series.name}:")
    for i, st in enumerate(series.season_types, 1):
        typer.echo(f"    {i}. {st}")

    while True:
        choice = typer.prompt(
            f"  Select [1-{len(series.season_types)}]").strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(series.season_types):
                return series.season_types[idx - 1]
        except ValueError:
            pass
        typer.echo("  Invalid selection, try again.")


def execute_with_conflict_check(
    actions: list[RenameAction],
    *,
    skip_existing: bool,
) -> list[RenameResult]:
    """Check conflicts and execute actions, returning results."""
    results = []
    for action in actions:
        if action.action != "dryrun" and check_conflict(Path(action.destination)):
            if skip_existing:
                logger.debug("Skipping (exists): %s", action.destination)
            else:
                logger.warning(
                    "Target already exists, skipping: %s", action.destination)
            continue

        result = execute_action(action)
        results.append(result)
        if result.success:
            verb = {"move": "Moved", "copy": "Copied",
                    "dryrun": "Would rename"}[result.action]
            logger.info("%s: %s -> %s", verb,
                        result.source, result.destination)
        else:
            logger.error("FAILED: %s -> %s: %s", result.source,
                         result.destination, result.error)

    return results


def match_episode(
    parsed: ParsedFile,
    episodes: list[TVDBEpisode],
    *,
    forced_season: int | None,
) -> TVDBEpisode | None:
    """Find the matching TVDB episode from a pre-fetched episode list."""
    season_num = forced_season if forced_season is not None else parsed.season_number
    ep_nums = parsed.episode_numbers

    if season_num is not None and ep_nums:
        for ep in episodes:
            if ep.season_number == season_num and ep.episode_number == ep_nums[0]:
                return ep

    if parsed.date is not None:
        date_str = parsed.date.isoformat()
        for ep in episodes:
            if ep.aired == date_str:
                return ep

    if ep_nums and season_num is None:
        for ep in episodes:
            if ep.absolute_number is not None and ep.absolute_number == ep_nums[0]:
                return ep
        for ep in episodes:
            if ep.episode_number == ep_nums[0]:
                return ep

    logger.warning(
        "Could not match episode for '%s' (S%s E%s) in TVDB data",
        parsed.title,
        season_num,
        ep_nums,
    )
    return None


def prompt_manual_tvdb_id() -> tuple[int, str] | None:
    """Prompt the user for a manual TVDB ID and type."""
    try:
        raw_id = typer.prompt("Enter TVDB ID")
        tvdb_id = int(raw_id.strip())
    except (ValueError, KeyboardInterrupt):
        typer.echo("Invalid ID.")
        return None

    while True:
        choice = typer.prompt("Is this a [s]eries or [m]ovie?")
        choice = choice.strip().lower()
        if choice in ("s", "series"):
            return (tvdb_id, "series")
        if choice in ("m", "movie"):
            return (tvdb_id, "movie")
        typer.echo("Please enter 's' for series or 'm' for movie.")
