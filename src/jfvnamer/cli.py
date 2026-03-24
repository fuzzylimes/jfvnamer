"""Typer-based CLI entrypoint for jfvnamer."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from jfvnamer.models import ParsedFile, TVDBEpisode, TVDBSeriesDetails
from jfvnamer.tvdb import TVDBClient
import typer

app = typer.Typer(
    name="jfvnamer",
    help="Rename and organize TV show and movie files for Jellyfin.",
)

VIDEO_EXTENSIONS = {".mkv", ".avi", ".mp4",
                    ".m4v", ".ts", ".wmv", ".flv", ".mov"}

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


def _print_parsed(parsed: "ParsedFile") -> None:  # noqa: F821
    """Pretty-print a parsed file result."""
    typer.echo(f"  File:     {parsed.original_filename}")
    typer.echo(f"  Title:    {parsed.title}")
    typer.echo(f"  Type:     {parsed.media_type.value}")
    if parsed.season_number is not None:
        typer.echo(f"  Season:   {parsed.season_number}")
    if parsed.episode_numbers:
        eps = ", ".join(str(e) for e in parsed.episode_numbers)
        typer.echo(f"  Episode:  {eps}")
    if parsed.episode_name:
        typer.echo(f"  Ep Name:  {parsed.episode_name}")
    if parsed.year:
        typer.echo(f"  Year:     {parsed.year}")
    if parsed.date:
        typer.echo(f"  Date:     {parsed.date}")
    if parsed.quality:
        typer.echo(f"  Quality:  {parsed.quality}")
    if parsed.source:
        typer.echo(f"  Source:   {parsed.source}")
    typer.echo(f"  Ext:      {parsed.file_extension}")
    typer.echo("")


# ---------------------------------------------------------------------------
# rename command
# ---------------------------------------------------------------------------


@app.command()
def rename(
    path: Path = typer.Argument(..., help="File or directory to rename."),
    order: Optional[str] = typer.Option(
        None, "--order", help="Episode ordering: aired, dvd, or absolute (TV only)."
    ),
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
    from jfvnamer.renamer import process_files
    from jfvnamer.tvdb import TVDBClient

    # Build CLI overrides
    cli_overrides: dict = {}
    if action:
        cli_overrides.setdefault("general", {})["action"] = action
    if series_root:
        cli_overrides.setdefault("general", {})[
            "series_root"] = str(series_root)
    if movies_root:
        cli_overrides.setdefault("general", {})[
            "movies_root"] = str(movies_root)
    if verbose:
        cli_overrides.setdefault("general", {})["verbose"] = True
    if order:
        cli_overrides.setdefault("tvdb", {})["default_order"] = order

    config = load_config(user_config_path=config_file,
                         cli_overrides=cli_overrides or None)

    # Set up logging
    _setup_logging(config.general.verbose)

    # Validate API key
    validate_api_key(config)

    if not path.exists():
        typer.echo(f"Error: {path} does not exist.", err=True)
        raise typer.Exit(1)

    client = TVDBClient(
        api_key=config.tvdb.api_key,
        cache_ttl_days=config.tvdb.cache_ttl_days,
        language=config.tvdb.language,
    )

    # Per-session caches to avoid redundant API calls and repeated prompts
    # when processing multiple files from the same series.
    series_details_cache: dict[int, "TVDBSeriesDetails"] = {}
    ordering_cache: dict[int, str] = {}

    # Build the resolver callback
    def resolver(parsed: ParsedFile):
        return _resolve_tvdb(
            parsed,
            client=client,
            no_prompt=no_prompt,
            forced_series_id=series_id,
            forced_movie_id=movie_id,
            forced_season=season,
            default_order=config.tvdb.default_order,
            order_override=order,
            series_details_cache=series_details_cache,
            ordering_cache=ordering_cache,
        )

    try:
        results = process_files(
            input_path=path,
            config=config,
            resolver=resolver,
            skip_existing=skip_existing,
        )
    finally:
        client.close()

    # Summary
    successes = sum(1 for r in results if r.success)
    failures = sum(1 for r in results if not r.success)
    dry_runs = sum(1 for r in results if r.action == "dryrun")

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
    query: str = typer.Argument(...,
                                help="Search query (series or movie name)."),
    media_type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Filter by type: series or movie."
    ),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to user config file."
    ),
) -> None:
    """Search TVDB interactively."""
    from jfvnamer.config import load_config, validate_api_key
    from jfvnamer.tvdb import TVDBClient

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
        typer.echo(
            f"  {i:>2}. {label:<10} {r.name}{year_str} — TVDB ID: {r.tvdb_id}")


# ---------------------------------------------------------------------------
# cache subcommand group
# ---------------------------------------------------------------------------

cache_app = typer.Typer(help="Manage TVDB cache.")
app.add_typer(cache_app, name="cache")


@cache_app.command("clear")
def cache_clear() -> None:
    """Clear all TVDB cached data (token, searches, episodes)."""
    from jfvnamer.tvdb import TVDBClient

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
        # Find the most recent undo log
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
# Interactive disambiguation helpers
# ---------------------------------------------------------------------------

# Regex for DVD/Blu-ray source keywords in filenames
_DVD_SOURCE_RE = re.compile(
    r"\b(dvd|dvdrip|bd|bdrip|bluray|blu[\-\.]?ray)\b", re.IGNORECASE)


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
        # In non-interactive mode, auto-select the first result
        r = results[0]
        logger.info('Auto-selected first result for "%s": %s (ID: %d)',
                    title, r.name, r.tvdb_id)
        return (r.tvdb_id, r.type)

    typer.echo(f'\nMultiple matches found for "{title}":')
    for i, r in enumerate(results, 1):
        label = f"[{r.type.capitalize()}]"
        year_str = f" ({r.year})" if r.year else ""
        typer.echo(
            f"  {i}. {label:<10} {r.name}{year_str} — TVDB ID: {r.tvdb_id}")
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


def _prompt_ordering(
    series_name: str,
    available_types: list[str],
    episodes_by_type: dict[str, dict],
    *,
    auto_dvd: bool = False,
) -> str:
    """Prompt the user to select an episode ordering for a TV series.

    Parameters
    ----------
    series_name:
        Display name for the series.
    available_types:
        List of TVDB season type strings (e.g. ["default", "dvd", "absolute"]).
    episodes_by_type:
        Dict mapping season type to {"seasons": int, "episodes": int} counts.
    auto_dvd:
        If True, auto-select DVD ordering (based on filename heuristic).

    Returns one of "aired", "dvd", "absolute".
    """
    from jfvnamer.tvdb import ORDER_MAP

    # Build reverse map: tvdb_type -> user_facing_name
    reverse_map = {v: k for k, v in ORDER_MAP.items()}

    # Filter to types that exist for this series
    choices: list[tuple[str, str]] = []  # (season_type, tvdb_type)
    for tvdb_type in available_types:
        season_type = reverse_map.get(tvdb_type)
        if season_type:
            choices.append((season_type, tvdb_type))

    if not choices:
        # Fallback to aired
        return "aired"

    if len(choices) == 1:
        return choices[0][0]

    # Auto-select DVD if filename indicates it
    if auto_dvd:
        for season_type, tvdb_type in choices:
            if season_type == "dvd":
                typer.echo(
                    "Auto-selected DVD ordering based on filename. "
                    "Override with --order aired"
                )
                return "dvd"

    typer.echo(f'\nEpisode ordering for "{series_name}":')
    for i, (season_type, tvdb_type) in enumerate(choices, 1):
        info = episodes_by_type.get(tvdb_type, {})
        seasons = info.get("seasons", "?")
        episodes = info.get("episodes", "?")
        label = season_type.capitalize() + " Order"
        typer.echo(
            f"  {i}. {label} ({seasons} seasons, {episodes} episodes)")

    typer.echo("")
    while True:
        choice = typer.prompt(
            f"Select [1-{len(choices)}, q=quit]",
            default="1",
        )
        choice = choice.strip().lower()
        if choice == "q":
            raise typer.Exit(0)
        try:
            idx = int(choice)
            if 1 <= idx <= len(choices):
                return choices[idx - 1][0]
        except ValueError:
            pass
        typer.echo("Invalid selection, try again.")


def _count_episodes_by_type(
    client: "TVDBClient",
    series_id: int,
    season_types: list[str],
) -> dict[str, dict]:
    """Fetch episode counts per ordering type for display in the ordering prompt."""
    from jfvnamer.tvdb import ORDER_MAP

    reverse_map = {v: k for k, v in ORDER_MAP.items()}
    result: dict[str, dict] = {}

    for tvdb_type in season_types:
        season_type = reverse_map.get(tvdb_type)
        if not season_type:
            continue
        try:
            episodes = client.get_episodes(series_id, order=season_type)
            seasons = set()
            for ep in episodes:
                seasons.add(ep.season_number)
            # Exclude season 0 (specials) from the count
            regular_seasons = {s for s in seasons if s > 0}
            result[tvdb_type] = {
                "seasons": len(regular_seasons),
                "episodes": len([e for e in episodes if e.season_number > 0]),
            }
        except Exception:
            result[tvdb_type] = {"seasons": 0, "episodes": 0}

    return result


# ---------------------------------------------------------------------------
# TVDB resolver (wires disambiguation + ordering into the rename flow)
# ---------------------------------------------------------------------------


def _resolve_tvdb(
    parsed: "ParsedFile",
    *,
    client: "TVDBClient",
    no_prompt: bool,
    forced_series_id: int | None,
    forced_movie_id: int | None,
    forced_season: int | None,
    default_order: str,
    order_override: str | None,
    series_details_cache: dict | None = None,
    ordering_cache: dict | None = None,
) -> tuple | None:
    """Resolve a ParsedFile to TVDB metadata.

    Returns a tuple of (type, metadata, episode_or_none) or None to skip.
    """
    from jfvnamer.models import MediaType

    if series_details_cache is None:
        series_details_cache = {}
    if ordering_cache is None:
        ordering_cache = {}

    def _get_series(sid: int):
        if sid not in series_details_cache:
            series_details_cache[sid] = client.get_series_details(sid)
        return series_details_cache[sid]

    # --- Handle forced IDs ---
    if forced_movie_id is not None:
        movie = client.get_movie_details(forced_movie_id)
        return ("movie", movie, None)

    if forced_series_id is not None:
        series = _get_series(forced_series_id)
        episode = _match_episode(
            parsed, client, forced_series_id,
            order=order_override or default_order,
            forced_season=forced_season,
        )
        return ("series", series, episode)

    # --- Check search cache ---
    cached = client.get_cached_search(parsed.title)
    if cached:
        tvdb_id = cached["tvdb_id"]
        result_type = cached["type"]
        logger.debug(
            "Using cached search result for '%s': %s (ID: %d)",
            parsed.title, cached["name"], tvdb_id,
        )
    else:
        # --- Search TVDB ---
        search_type = None
        if parsed.media_type == MediaType.TV:
            search_type = "series"
        elif parsed.media_type == MediaType.MOVIE:
            search_type = "movie"

        results = client.search(parsed.title, media_type=search_type)
        selection = _prompt_disambiguation(
            parsed.title, results, no_prompt=no_prompt)
        if selection is None:
            return None

        tvdb_id, result_type = selection

        # Find the name to cache
        name = parsed.title
        for r in results:
            if r.tvdb_id == tvdb_id:
                name = r.name
                break

        client.cache_search_result(parsed.title, tvdb_id, result_type, name)

    # --- Fetch details based on type ---
    if result_type == "movie":
        movie = client.get_movie_details(tvdb_id)
        return ("movie", movie, None)

    # It's a series
    series = _get_series(tvdb_id)

    # Determine episode ordering (use cached choice if available)
    if tvdb_id in ordering_cache:
        order = ordering_cache[tvdb_id]
    elif order_override:
        order = order_override
    else:
        order = _select_ordering(
            parsed, client, series,
            default_order=default_order,
            no_prompt=no_prompt,
        )
        ordering_cache[tvdb_id] = order

    episode = _match_episode(
        parsed, client, tvdb_id,
        order=order,
        forced_season=forced_season,
    )
    return ("series", series, episode)


def _select_ordering(
    parsed: "ParsedFile",
    client: "TVDBClient",
    series: "TVDBSeriesDetails",
    *,
    default_order: str,
    no_prompt: bool,
) -> str:
    """Determine the episode ordering to use for a series."""
    # Check for DVD source keywords in the original filename
    auto_dvd = bool(_DVD_SOURCE_RE.search(parsed.original_filename))

    if no_prompt:
        if auto_dvd:
            logger.info("Auto-selected DVD ordering based on filename.")
            return "dvd"
        return default_order

    if not series.season_types or len(series.season_types) <= 1:
        return default_order

    # Fetch episode counts for the ordering prompt
    counts = _count_episodes_by_type(
        client, series.tvdb_id, series.season_types)

    return _prompt_ordering(
        series.name,
        series.season_types,
        counts,
        auto_dvd=auto_dvd,
    )


def _match_episode(
    parsed: "ParsedFile",
    client: "TVDBClient",
    series_id: int,
    *,
    order: str,
    forced_season: int | None,
) -> "TVDBEpisode | None":
    """Find the matching TVDB episode for the parsed file info."""

    episodes = client.get_episodes(series_id, order=order)

    season_num = forced_season if forced_season is not None else parsed.season_number
    ep_nums = parsed.episode_numbers

    # Try to match by season + episode number
    if season_num is not None and ep_nums:
        for ep in episodes:
            if ep.season_number == season_num and ep.episode_number == ep_nums[0]:
                return ep

    # Try to match by date
    if parsed.date is not None:
        date_str = parsed.date.isoformat()
        for ep in episodes:
            if ep.aired == date_str:
                return ep

    # Try to match by absolute number (episode_numbers without season)
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
    """Configure logging based on verbosity."""
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
