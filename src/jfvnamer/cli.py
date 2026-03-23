"""Typer-based CLI entrypoint for jfvnamer."""

from __future__ import annotations

import json
from pathlib import Path

import typer

app = typer.Typer(
    name="jfvnamer",
    help="Rename and organize TV show and movie files for Jellyfin.",
)

VIDEO_EXTENSIONS = {".mkv", ".avi", ".mp4", ".m4v", ".ts", ".wmv", ".flv", ".mov"}


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="Show version and exit."),
) -> None:
    if version:
        from jfvnamer import __version__

        typer.echo(f"jfvnamer {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command()
def parse(
    path: Path = typer.Argument(..., help="File or directory to parse."),
    as_json: bool = typer.Option(False, "--json", "-j", help="Output as JSON."),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", "-r/-R", help="Scan subdirectories."),
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
    from jfvnamer.models import MediaType

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


config_app = typer.Typer(help="Manage jfvnamer configuration.")
app.add_typer(config_app, name="config")


@config_app.command("init")
def config_init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config file."),
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
    config_file: Path = typer.Option(None, "--config", "-c", help="Path to user config file."),
) -> None:
    """Print the fully resolved configuration (all layers merged)."""
    from jfvnamer.config import load_config

    cfg = load_config(user_config_path=config_file)
    typer.echo(json.dumps(cfg.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    app()
