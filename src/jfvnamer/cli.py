"""Typer-based CLI entrypoint for jfvnamer."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer

from jfvnamer.renamer import (
    check_conflict,
    execute_action,
    group_files_by_title,
    plan_rename,
    scan_video_files,
    write_undo_log,
)
from jfvnamer.models import (
    ParsedFile,
    TVDBEpisode,
    TVDBSearchResult,
    TVDBSeriesDetails,
    VIDEO_EXTENSIONS,
)
from jfvnamer.tvdb import TVDBClient

app = typer.Typer(
    name="jfvnamer",
    help="Rename and organize TV show and movie files for Jellyfin.",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Top-level callback
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", help="Show version and exit."),
) -> None:
    if version:
        from jfvnamer import __version__

        typer.echo(f"jfvnamer {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# parse command
# ---------------------------------------------------------------------------


@app.command()
def parse(
    path: Path = typer.Argument(..., help="File or directory to parse."),
    as_json: bool = typer.Option(
        False, "--json", "-j", help="Output as JSON."),
    recursive: bool = typer.Option(
        True, "--recursive/--no-recursive", "-r/-R", help="Scan subdirectories."),
) -> None:
    """Parse filenames and show extracted metadata (no TVDB lookup)."""
    from jfvnamer.parser import parse_filename

    files: list[Path] = []
    if path.is_file():
        files.append(path)
    elif path.is_dir():
        pattern = "**/*" if recursive else "*"
        files = sorted(
            f for f in path.glob(pattern) if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        )
    else:
        typer.echo(f"Error: {path} does not exist.", err=True)
        raise typer.Exit(1)

    if not files:
        typer.echo("No video files found.", err=True)
        raise typer.Exit(1)

    results = []
    for f in files:
        parsed = parse_filename(f.name)
        if as_json:
            results.append(parsed.model_dump(mode="json"))
        else:
            _print_parsed(parsed)

    if as_json:
        typer.echo(json.dumps(results, indent=2, default=str))


def _print_parsed(parsed: ParsedFile) -> None:
    """Pretty-print a parsed file result."""
    typer.echo(f"  File:     {parsed.original_filename}")
    typer.echo(f"  Title:    {parsed.title}")
    if parsed.season_number is not None:
        typer.echo(f"  Season:   {parsed.season_number}")
    if parsed.episode_numbers:
        eps = ", ".join(str(e) for e in parsed.episode_numbers)
        typer.echo(f"  Episode:  {eps}")
    if parsed.episode_name:
        typer.echo(f"  Ep Name:  {parsed.episode_name}")
    if parsed.date:
        typer.echo(f"  Date:     {parsed.date}")
    typer.echo(f"  Ext:      {parsed.file_extension}")
    typer.echo("")


# ---------------------------------------------------------------------------
# rename command
# ---------------------------------------------------------------------------


@app.command()
def rename(
    path: Path = typer.Argument(..., help="File or directory to rename."),
    action: Optional[str] = typer.Option(
        None, "--action", help="Override action: move, copy, or dryrun."
    ),
    series_root: Optional[Path] = typer.Option(
        None, "--series-root", help="Override output root directory for TV series."
    ),
    movies_root: Optional[Path] = typer.Option(
        None, "--movies-root", help="Override output root directory for movies."
    ),
    no_prompt: bool = typer.Option(
        False, "--no-prompt", help="Non-interactive mode (skip ambiguous, log warnings)."
    ),
    series_id: Optional[int] = typer.Option(
        None, "--series-id", help="Force a specific TVDB series ID (skip search)."
    ),
    movie_id: Optional[int] = typer.Option(
        None, "--movie-id", help="Force a specific TVDB movie ID (skip search)."
    ),
    season: Optional[int] = typer.Option(
        None, "--season", help="Force season number for all files (TV only)."
    ),
    skip_existing: bool = typer.Option(
        False, "--skip-existing", help="Silently skip files whose target already exists."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Detailed output."),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to user config file."
    ),
) -> None:
    """Main rename workflow: parse, look up TVDB, and rename/move/copy files."""
    from jfvnamer.config import load_config, validate_api_key

    cli_overrides: dict = {}
    if action:
        cli_overrides.setdefault("general", {})["action"] = action
    if series_root:
        cli_overrides.setdefault("general", {})["series_root"] = str(series_root)
    if movies_root:
        cli_overrides.setdefault("general", {})["movies_root"] = str(movies_root)
    if verbose:
        cli_overrides.setdefault("general", {})["verbose"] = True

    config = load_config(user_config_path=config_file,
                         cli_overrides=cli_overrides or None)
    _setup_logging(config.general.verbose)
    validate_api_key(config)

    if not path.exists():
        typer.echo(f"Error: {path} does not exist.", err=True)
        raise typer.Exit(1)

    client = TVDBClient(
        api_key=config.tvdb.api_key,
        cache_ttl_days=config.tvdb.cache_ttl_days,
        language=config.tvdb.language,
    )

    try:
        video_files = scan_video_files(path, recursive=config.general.recursive)
        if not video_files:
            typer.echo("No video files found.")
            return

        groups = group_files_by_title(video_files)
        series_details_cache: dict[int, TVDBSeriesDetails] = {}
        all_results = []

        for title, file_group in groups.items():
            results = _run_group_interactive(
                title=title,
                group=file_group,
                client=client,
                config=config,
                no_prompt=no_prompt,
                forced_series_id=series_id,
                forced_movie_id=movie_id,
                forced_season=season,
                skip_existing=skip_existing,
                series_details_cache=series_details_cache,
            )
            all_results.extend(results)

        write_undo_log(all_results)

    finally:
        client.close()

    successes = sum(1 for r in all_results if r.success)
    failures = sum(1 for r in all_results if not r.success)
    dry_runs = sum(1 for r in all_results if r.action == "dryrun")

    if dry_runs:
        typer.echo(f"\nDry run: {dry_runs} file(s) would be renamed.")
    elif successes or failures:
        typer.echo(f"\nDone: {successes} succeeded, {failures} failed.")
    else:
        typer.echo("\nNo files processed.")


# ---------------------------------------------------------------------------
# search command
# ---------------------------------------------------------------------------


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query (series or movie name)."),
    media_type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Filter by type: series or movie."
    ),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to user config file."
    ),
) -> None:
    """Search TVDB interactively."""
    from jfvnamer.config import load_config, validate_api_key

    config = load_config(user_config_path=config_file)
    validate_api_key(config)

    client = TVDBClient(
        api_key=config.tvdb.api_key,
        cache_ttl_days=config.tvdb.cache_ttl_days,
        language=config.tvdb.language,
    )

    try:
        results = client.search(query, media_type=media_type)
    finally:
        client.close()

    if not results:
        typer.echo(f'No results found for "{query}".')
        raise typer.Exit(1)

    typer.echo(f'Results for "{query}":')
    for i, r in enumerate(results, 1):
        label = f"[{r.type.capitalize()}]"
        year_str = f" ({r.year})" if r.year else ""
        genre_str = f"  [{', '.join(r.genres[:3])}]" if r.genres else ""
        typer.echo(
            f"  {i:>2}. {label:<10} {r.name}{year_str}{genre_str} — TVDB ID: {r.tvdb_id}")


# ---------------------------------------------------------------------------
# cache subcommand group
# ---------------------------------------------------------------------------

cache_app = typer.Typer(help="Manage TVDB cache.")
app.add_typer(cache_app, name="cache")


@cache_app.command("clear")
def cache_clear() -> None:
    """Clear all TVDB cached data (token, searches, episodes)."""
    TVDBClient.clear_cache()
    typer.echo("Cache cleared.")


# ---------------------------------------------------------------------------
# undo command
# ---------------------------------------------------------------------------


@app.command()
def undo(
    log_file: Optional[Path] = typer.Argument(
        None, help="Path to a specific undo log file. If omitted, uses the most recent."
    ),
) -> None:
    """Reverse a previous rename operation using its undo log."""
    from jfvnamer.renamer import UNDO_DIR, undo_rename

    if log_file is None:
        if not UNDO_DIR.exists():
            typer.echo("No undo logs found.", err=True)
            raise typer.Exit(1)
        logs = sorted(UNDO_DIR.glob("*.json"), reverse=True)
        if not logs:
            typer.echo("No undo logs found.", err=True)
            raise typer.Exit(1)
        log_file = logs[0]
        typer.echo(f"Using most recent undo log: {log_file.name}")

    if not log_file.exists():
        typer.echo(f"Error: {log_file} does not exist.", err=True)
        raise typer.Exit(1)

    results = undo_rename(log_file)
    successes = sum(1 for r in results if r.success)
    failures = sum(1 for r in results if not r.success)
    typer.echo(f"Undo complete: {successes} reversed, {failures} failed.")


# ---------------------------------------------------------------------------
# config subcommand group
# ---------------------------------------------------------------------------

config_app = typer.Typer(help="Manage jfvnamer configuration.")
app.add_typer(config_app, name="config")


@config_app.command("init")
def config_init(
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite existing config file."),
) -> None:
    """Create a template config file at ~/.config/jfvnamer/config.toml."""
    from jfvnamer.config import USER_CONFIG_DIR, USER_CONFIG_PATH, generate_user_config_template

    if USER_CONFIG_PATH.exists() and not force:
        typer.echo(f"Config file already exists: {USER_CONFIG_PATH}")
        typer.echo("Use --force to overwrite.")
        raise typer.Exit(1)

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_PATH.write_text(generate_user_config_template())
    typer.echo(f"Config template written to {USER_CONFIG_PATH}")


@config_app.command("show")
def config_show(
    config_file: Path = typer.Option(
        None, "--config", "-c", help="Path to user config file."),
) -> None:
    """Print the fully resolved configuration (all layers merged)."""
    from jfvnamer.config import load_config

    cfg = load_config(user_config_path=config_file)
    typer.echo(json.dumps(cfg.model_dump(mode="json"), indent=2))


# ---------------------------------------------------------------------------
# Grouped interactive rename flow
# ---------------------------------------------------------------------------


def _run_group_interactive(
    title: str,
    group: list[tuple[Path, ParsedFile]],
    *,
    client: TVDBClient,
    config,
    no_prompt: bool,
    forced_series_id: int | None,
    forced_movie_id: int | None,
    forced_season: int | None,
    skip_existing: bool,
    series_details_cache: dict,
) -> list:
    """Process one group of files with the interactive rename flow."""
    typer.echo(f"\nSearching: {title}")

    # --- Step 1: Determine TVDB selection ---
    if forced_movie_id is not None:
        tvdb_id, result_type = forced_movie_id, "movie"
    elif forced_series_id is not None:
        tvdb_id, result_type = forced_series_id, "series"
    else:
        selection = _search_tvdb_loop(title, client, no_prompt=no_prompt)
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
        _display_planned_actions(all_actions)
        if not no_prompt:
            if not typer.confirm("Confirm these renames?", default=True):
                return []
        return _execute_with_conflict_check(all_actions, skip_existing=skip_existing)

    # --- Series path ---
    season_type = "default"

    while True:
        if tvdb_id not in series_details_cache:
            series_details_cache[tvdb_id] = client.get_series_details(tvdb_id)
        series = series_details_cache[tvdb_id]

        episodes = client.get_episodes(tvdb_id, season_type=season_type)

        all_actions = []
        for video_path, parsed in group:
            ep = _match_episode(parsed, episodes, forced_season=forced_season)
            all_actions.extend(plan_rename(
                video_path, parsed, series_root, config,
                series=series, episode=ep,
            ))

        # --- Step 2: Show planned renames ---
        _display_planned_actions(all_actions)

        # --- Step 3: Confirm or switch season type ---
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
            season_type = _prompt_season_type(series)
        # any other input: re-display and re-prompt

    return _execute_with_conflict_check(all_actions, skip_existing=skip_existing)


def _search_tvdb_loop(
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
            _display_search_results(results)

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
            return _prompt_manual_tvdb_id()
        try:
            idx = int(choice)
            if results and 1 <= idx <= len(results):
                r = results[idx - 1]
                return (r.tvdb_id, r.type)
        except ValueError:
            pass
        typer.echo("  Invalid selection, try again.")


def _display_search_results(results: list[TVDBSearchResult]) -> None:
    for i, r in enumerate(results, 1):
        label = f"[{r.type.capitalize()}]"
        year_str = f" ({r.year})" if r.year else ""
        genre_str = f"  [{', '.join(r.genres[:3])}]" if r.genres else ""
        typer.echo(f"  {i:>2}. {label:<10} {r.name}{year_str}{genre_str} — TVDB ID: {r.tvdb_id}")


def _display_planned_actions(actions: list) -> None:
    """Print planned rename actions grouped by source."""
    typer.echo("")
    for action in actions:
        src = Path(action.source).name
        dst = action.destination
        typer.echo(f"  {src}")
        typer.echo(f"    → {dst}")
    typer.echo("")


def _prompt_season_type(series: TVDBSeriesDetails) -> str:
    """Let the user pick a season type from the available types."""
    if not series.season_types:
        typer.echo("  No alternative season types available.")
        return "default"

    typer.echo(f"\n  Available season types for {series.name}:")
    for i, st in enumerate(series.season_types, 1):
        typer.echo(f"    {i}. {st}")

    while True:
        choice = typer.prompt(f"  Select [1-{len(series.season_types)}]").strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(series.season_types):
                return series.season_types[idx - 1]
        except ValueError:
            pass
        typer.echo("  Invalid selection, try again.")


def _execute_with_conflict_check(
    actions: list,
    *,
    skip_existing: bool,
) -> list:
    """Check conflicts and execute actions, returning results."""
    results = []
    for action in actions:
        if action.action != "dryrun" and check_conflict(Path(action.destination)):
            if skip_existing:
                logger.debug("Skipping (exists): %s", action.destination)
                continue
            else:
                logger.warning("Target already exists, skipping: %s", action.destination)
                continue

        result = execute_action(action)
        results.append(result)
        if result.success:
            verb = {"move": "Moved", "copy": "Copied", "dryrun": "Would rename"}[result.action]
            logger.info("%s: %s -> %s", verb, result.source, result.destination)
        else:
            logger.error("FAILED: %s -> %s: %s", result.source, result.destination, result.error)

    return results


# ---------------------------------------------------------------------------
# Interactive disambiguation (shared, also used by legacy-style callers)
# ---------------------------------------------------------------------------


def _prompt_disambiguation(
    title: str,
    results: list,
    *,
    no_prompt: bool = False,
) -> tuple[int, str] | None:
    """Present TVDB search results and let the user pick one.

    Returns (tvdb_id, type) or None if the user chose to skip.
    """
    if not results:
        typer.echo(f'No matches found for "{title}".')
        return None

    if len(results) == 1 and not no_prompt:
        r = results[0]
        year_str = f" ({r.year})" if r.year else ""
        typer.echo(
            f'Auto-selected: [{r.type.capitalize()}] {r.name}{year_str} — TVDB ID: {r.tvdb_id}')
        return (r.tvdb_id, r.type)

    if no_prompt:
        r = results[0]
        logger.info('Auto-selected first result for "%s": %s (ID: %d)',
                    title, r.name, r.tvdb_id)
        return (r.tvdb_id, r.type)

    typer.echo(f'\nMultiple matches found for "{title}":')
    for i, r in enumerate(results, 1):
        label = f"[{r.type.capitalize()}]"
        year_str = f" ({r.year})" if r.year else ""
        genre_str = f"  [{', '.join(r.genres[:3])}]" if r.genres else ""
        typer.echo(
            f"  {i}. {label:<10} {r.name}{year_str}{genre_str} — TVDB ID: {r.tvdb_id}")
    typer.echo("")

    while True:
        choice = typer.prompt(
            f"Select [1-{len(results)}, i=enter TVDB ID manually, s=skip, q=quit]"
        )
        choice = choice.strip().lower()

        if choice == "q":
            raise typer.Exit(0)
        if choice == "s":
            return None
        if choice == "i":
            return _prompt_manual_tvdb_id()
        try:
            idx = int(choice)
            if 1 <= idx <= len(results):
                r = results[idx - 1]
                return (r.tvdb_id, r.type)
        except ValueError:
            pass
        typer.echo("Invalid selection, try again.")


def _prompt_manual_tvdb_id() -> tuple[int, str] | None:
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


# ---------------------------------------------------------------------------
# Episode matching
# ---------------------------------------------------------------------------


def _match_episode(
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
            if ep.episode_number == ep_nums[0]:
                return ep

    logger.warning(
        "Could not match episode for '%s' (S%s E%s) in TVDB data",
        parsed.title,
        season_num,
        ep_nums,
    )
    return None


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )


# ---------------------------------------------------------------------------
# __main__ support
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
