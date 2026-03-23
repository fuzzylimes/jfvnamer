# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

jfvnamer is a Jellyfin-focused video file renamer that renames and organizes TV show and movie files into Jellyfin's expected directory structure. It uses the TVDB v4 API for metadata lookup.

## Development Setup

- Python 3.14, managed via uv (not pip)
- `uv sync` to install dependencies
- Virtual environment at `.venv/`

## Commands

- **Run tests:** `uv run pytest`
- **Run a single test:** `uv run pytest tests/test_renamer.py::test_name`
- **Run the CLI:** `uv run jfvnamer` (entry point: `jfvnamer.cli:app`)

## Architecture

The project uses a `src/` layout with three core modules:

- **`jellyfin.py`** — Jellyfin naming convention rules (how files/folders should be named)
- **`renamer.py`** — Path construction and rename/move/copy logic (the engine that applies naming rules to actual files)
- **`tvdb.py`** — TVDB v4 API client wrapper (fetches series/episode metadata)

CLI is built with Typer, models use Pydantic, HTTP via httpx.

## Configuration

Default config lives in `config/default.toml` with sections: `[general]`, `[tvdb]`, `[naming]`, `[patterns]`. Users can extend patterns via `patterns_prepend`/`patterns_append` keys without overwriting defaults, or use `patterns_replace` to override all defaults.

## Key Dependencies

- typer (CLI framework)
- pydantic (data models/validation)
- httpx (async-capable HTTP client for TVDB API)
