# jfvnamer

A Jellyfin-focused video file renamer — renames and organizes TV show and movie files into Jellyfin's expected directory structure using [TVDB](https://thetvdb.com/) for metadata lookup.

> **Note:** This project is under active development and not yet stable. Expect breaking changes.

Heavily inspired by [tvnamer](https://github.com/dbr/tvnamer), which this project's parsing logic is largely based on. Huge thanks to that project for the hard work.

## How to Use

### 1. Install

#### Using pipx (recommended)

[pipx](https://pipx.pypa.io/) installs the tool in an isolated environment and adds it to your PATH:

```bash
pipx install git+https://github.com/fuzzylimes/jfvnamer.git
```

#### Using uv

[uv](https://docs.astral.sh/uv/) can do the same thing with `uv tool`:

```bash
uv tool install git+https://github.com/fuzzylimes/jfvnamer.git
```

#### From source

```bash
git clone https://github.com/fuzzylimes/jfvnamer.git
cd jfvnamer
uv sync
```

When running from source, prefix all commands with `uv run` (e.g., `uv run jfvnamer config init`).

### 2. Configure

Generate a config file:

```bash
jfvnamer config init
```

This creates `~/.config/jfvnamer/config.toml` with commented defaults. At minimum, you need to set your TVDB API key (get one free at https://thetvdb.com/api-information):

```toml
[tvdb]
api_key = "your-key-here"
```

You should also set `series_root` and `movies_root` to your Jellyfin media library paths:

```toml
[general]
series_root = "/path/to/jellyfin/Shows"
movies_root = "/path/to/jellyfin/Movies"
```

To view the fully resolved config (defaults + your overrides):

```bash
jfvnamer config show
```

### 3. Test Parsing (No API Key Required)

Before doing any renaming, you can verify that filenames are being parsed correctly:

```bash
# Parse a single file
jfvnamer parse "Breaking.Bad.S01E01.720p.mkv"

# Parse all video files in a directory
jfvnamer parse /path/to/files/

# Output as JSON
jfvnamer parse /path/to/files/ --json
```

### 4. Search TVDB

Look up series or movies to verify they exist and find their TVDB IDs:

```bash
jfvnamer search "Breaking Bad"
jfvnamer search "Inception" --type movie
```

### 5. Rename

```bash
# Dry run first (no files moved, just shows what would happen)
jfvnamer rename /path/to/files/ --action dryrun

# Move files into Jellyfin structure
jfvnamer rename /path/to/files/

# Copy instead of move
jfvnamer rename /path/to/files/ --action copy

# Force a specific TVDB series ID (skip search)
jfvnamer rename /path/to/files/ --series-id 81189

# Non-interactive mode (auto-selects first match, no prompts)
jfvnamer rename /path/to/files/ --no-prompt
```

### 6. Undo

If something went wrong, reverse the last rename operation:

```bash
jfvnamer undo
```

### Cache

TVDB responses are cached locally. To clear the cache:

```bash
jfvnamer cache clear
```
