"""Typer-based CLI entrypoint for jfvnamer."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer

from jfvnamer.renamer import (
    group_files_by_title,
    scan_video_files,
    write_undo_log,
)
from jfvnamer.models import (
    ParsedFile,
    TVDBSeriesDetails,
    VIDEO_EXTENSIONS,
)
from jfvnamer.resolver import display_search_results, run_group_interactive

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
    from jfvnamer.config import MissingApiKeyError, load_config, validate_api_key
    from jfvnamer.tvdb import TVDBClient

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

    config = load_config(user_config_path=config_file,
                         cli_overrides=cli_overrides or None)
    _setup_logging(config.general.verbose)
    try:
        validate_api_key(config)
    except MissingApiKeyError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    if not path.exists():
        typer.echo(f"Error: {path} does not exist.", err=True)
        raise typer.Exit(1)

    client = TVDBClient(
        api_key=config.tvdb.api_key,
        cache_ttl_days=config.tvdb.cache_ttl_days,
        language=config.tvdb.language,
    )

    try:
        video_files = scan_video_files(
            path, recursive=config.general.recursive)
        if not video_files:
            typer.echo("No video files found.")
            return

        groups = group_files_by_title(video_files)
        series_details_cache: dict[int, TVDBSeriesDetails] = {}
        all_results = []

        for title, file_group in groups.items():
            results = run_group_interactive(
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
    from jfvnamer.config import MissingApiKeyError, load_config, validate_api_key
    from jfvnamer.tvdb import TVDBClient

    config = load_config(user_config_path=config_file)
    try:
        validate_api_key(config)
    except MissingApiKeyError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

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
    display_search_results(results=results)


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
