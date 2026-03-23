"""Typer-based CLI entrypoint for jfvnamer."""

import typer

app = typer.Typer(
    name="jfvnamer",
    help="Rename and organize TV show and movie files for Jellyfin.",
)


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


if __name__ == "__main__":
    app()
