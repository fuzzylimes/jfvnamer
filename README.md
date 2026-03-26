# jfvnamer

A Jellyfin-focused video file renamer — renames and organizes TV show and movie files into Jellyfin's expected directory structure using [TVDB](https://thetvdb.com/) for metadata lookup.

Heavily inspired by [tvnamer](https://github.com/dbr/tvnamer), which this project's parsing logic is largely based on. Huge thanks to that project for the hard work.

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
  - [parse](#parse)
  - [search](#search)
  - [rename](#rename)
  - [undo](#undo)
  - [cache](#cache)
  - [config](#config)
- [Configuration Reference](#configuration-reference)
  - [\[general\]](#general)
  - [\[tvdb\]](#tvdb)
  - [\[naming\]](#naming)
- [The Rename Workflow](#the-rename-workflow)
- [Output Structure](#output-structure)
- [Supported File Formats](#supported-file-formats)
- [Subtitle Handling](#subtitle-handling)
- [Undo System](#undo-system)

---

## Installation

### Using pipx (recommended)

[pipx](https://pipx.pypa.io/) installs the tool in an isolated environment and adds it to your PATH:

```bash
pipx install git+https://github.com/fuzzylimes/jfvnamer.git
```

### Using uv

[uv](https://docs.astral.sh/uv/) can do the same with `uv tool`:

```bash
uv tool install git+https://github.com/fuzzylimes/jfvnamer.git
```

### From source

```bash
git clone https://github.com/fuzzylimes/jfvnamer.git
cd jfvnamer
uv sync
```

When running from source, prefix all commands with `uv run` (e.g., `uv run jfvnamer rename ...`).

---

## Quick Start

**1. Create a config file and add your TVDB API key** (free at [thetvdb.com/api-information](https://thetvdb.com/api-information)):

```bash
jfvnamer config init
# Edit ~/.config/jfvnamer/config.toml — set api_key, series_root, movies_root
```

**2. Verify filenames parse correctly** (no API key needed):

```bash
jfvnamer parse /path/to/files/
```

**3. Do a dry run to preview what would happen:**

```bash
jfvnamer rename /path/to/files/ --action dryrun
```

**4. Run for real:**

```bash
jfvnamer rename /path/to/files/
```

**5. If something went wrong, undo it:**

```bash
jfvnamer undo
```

---

## CLI Reference

### parse

Parse filenames and display extracted metadata. **No TVDB lookup or API key required.**

```
jfvnamer parse <path> [options]
```

| Argument / Option | Default | Description |
|---|---|---|
| `path` | *(required)* | File or directory to parse |
| `--json` / `-j` | false | Output results as JSON |
| `--recursive` / `--no-recursive` | recursive | Whether to scan subdirectories |

**Examples:**

```bash
# Parse a single file
jfvnamer parse "Breaking.Bad.S01E01.720p.mkv"

# Parse all video files in a directory
jfvnamer parse /path/to/files/

# Parse non-recursively
jfvnamer parse /path/to/files/ --no-recursive

# Output as JSON (useful for scripting)
jfvnamer parse /path/to/files/ --json
```

**Sample output:**

```
  File:     Breaking.Bad.S01E01.720p.mkv
  Title:    Breaking Bad
  Season:   1
  Episode:  1
  Ext:      .mkv
```

---

### search

Search the TVDB for a series or movie by name. Useful for confirming a title exists and finding its TVDB ID before a rename.

```
jfvnamer search <query> [options]
```

| Argument / Option | Default | Description |
|---|---|---|
| `query` | *(required)* | Search query |
| `--type` / `-t` | *(all)* | Filter by type: `series` or `movie` |
| `--config` / `-c` | `~/.config/jfvnamer/config.toml` | Path to a custom config file |

**Examples:**

```bash
jfvnamer search "Breaking Bad"
jfvnamer search "Inception" --type movie
jfvnamer search "Attack on Titan" --type series
```

**Sample output:**

```
Results for "Breaking Bad":
   1. [Series]    Breaking Bad (2008)  [Crime, Drama, Thriller] — TVDB ID: 81189
   2. [Series]    Breaking Bad (2009)  [Animation] — TVDB ID: 392699
```

---

### rename

The main command. Parses files, looks them up on TVDB, and moves/copies them into Jellyfin's directory structure.

```
jfvnamer rename <path> [options]
```

| Argument / Option | Default | Description |
|---|---|---|
| `path` | *(required)* | File or directory to rename |
| `--action` | from config (`move`) | Override the action: `move`, `copy`, or `dryrun` |
| `--series-root` | from config | Override the output root for TV series |
| `--movies-root` | from config | Override the output root for movies |
| `--series-id` | *(none)* | Force a specific TVDB series ID, skipping the search |
| `--movie-id` | *(none)* | Force a specific TVDB movie ID, skipping the search |
| `--season` | *(none)* | Force a season number for all files (TV only) |
| `--no-prompt` | false | Non-interactive mode — auto-selects the first search result |
| `--skip-existing` | false | Silently skip files whose target path already exists |
| `--verbose` / `-v` | false | Print detailed debug output |
| `--config` / `-c` | `~/.config/jfvnamer/config.toml` | Path to a custom config file |

**Examples:**

```bash
# Preview what would happen (no files moved)
jfvnamer rename /downloads/Breaking.Bad/ --action dryrun

# Move files into Jellyfin structure (interactive)
jfvnamer rename /downloads/Breaking.Bad/

# Copy instead of move
jfvnamer rename /downloads/Breaking.Bad/ --action copy

# Force a known TVDB ID to skip the search prompt
jfvnamer rename /downloads/Breaking.Bad/ --series-id 81189

# Force all files to be treated as Season 2
jfvnamer rename /downloads/Breaking.Bad/ --season 2

# Non-interactive: auto-select first result, no confirmation prompts
jfvnamer rename /downloads/ --no-prompt

# Use a different output directory just for this run
jfvnamer rename /downloads/Breaking.Bad/ --series-root /mnt/media/Shows

# Skip files that already exist at the destination
jfvnamer rename /downloads/ --skip-existing
```

**Interactive prompts during rename:**

When running interactively (without `--no-prompt`), the rename flow presents search results and asks you to confirm. At each step you can:

- Enter a result number (e.g. `1`) to select it
- Enter `s` to search again with a different query
- Enter `i` to enter a TVDB ID manually
- Enter `k` to skip this group of files
- Enter `q` to quit

After TVDB metadata is fetched, the planned renames are displayed. You can then:

- Enter `c` (or press Enter) to confirm and execute
- Enter `t` to try a different season ordering type (e.g. DVD order, absolute order)
- Enter `s` to skip this group
- Enter `q` to quit

---

### undo

Reverse a previous rename operation using its automatically-saved undo log.

```
jfvnamer undo [log-file]
```

| Argument | Default | Description |
|---|---|---|
| `log-file` | *(most recent)* | Path to a specific undo log file. If omitted, uses the most recent. |

Undo logs are stored in `~/.local/share/jfvnamer/undo/` as timestamped JSON files.

```bash
# Undo the most recent rename
jfvnamer undo

# Undo a specific session
jfvnamer undo ~/.local/share/jfvnamer/undo/20240315_143022.json
```

> **Note on copy actions:** Undoing a `copy` restores the file to its original location but does **not** delete the copy at the destination. Both files will exist after the undo. Remove the destination manually if needed.

---

### cache

Manage cached TVDB API responses.

```
jfvnamer cache clear
```

TVDB responses (auth tokens, search results, episode lists) are cached locally to reduce API calls. The cache TTL is configurable (default 7 days). Use this command to force fresh data from TVDB.

```bash
jfvnamer cache clear
```

---

### config

Manage the jfvnamer configuration file.

#### config init

Create a template config file at `~/.config/jfvnamer/config.toml`.

```
jfvnamer config init [--force]
```

| Option | Description |
|---|---|
| `--force` / `-f` | Overwrite the config file if it already exists |

```bash
jfvnamer config init
jfvnamer config init --force   # overwrite existing
```

#### config show

Print the fully resolved configuration — defaults merged with your overrides.

```
jfvnamer config show [--config <path>]
```

```bash
jfvnamer config show
jfvnamer config show --config /path/to/other/config.toml
```

---

## Configuration Reference

The config file lives at `~/.config/jfvnamer/config.toml`. Generate a template with `jfvnamer config init`.

Configuration is resolved in layers (highest priority wins):

1. **CLI flags** — e.g. `--action dryrun`, `--series-root /mnt/shows`
2. **User config** — `~/.config/jfvnamer/config.toml`
3. **Built-in defaults** — baked into the package

Only set the values you want to override — everything else inherits its default.

---

### [general]

Controls file scanning and the default action taken on files.

| Key | Default | Description |
|---|---|---|
| `series_root` | `"."` | Root directory where TV series are output. Subdirectories are created automatically. |
| `movies_root` | `"."` | Root directory where movies are output. |
| `action` | `"move"` | What to do with matched files: `"move"`, `"copy"`, or `"dryrun"`. |
| `recursive` | `true` | Whether to scan subdirectories when given a directory path. |
| `verbose` | `false` | Enable debug-level logging output. |

**Example:**

```toml
[general]
series_root = "/mnt/media/Shows"
movies_root = "/mnt/media/Movies"
action = "move"
recursive = true
```

---

### [tvdb]

Controls TVDB API access and caching.

| Key | Default | Description |
|---|---|---|
| `api_key` | `""` | **Required.** Your TVDB v4 API key. Get one free at [thetvdb.com/api-information](https://thetvdb.com/api-information). |
| `cache_ttl_days` | `7` | How many days to cache TVDB responses before they expire. |
| `language` | `"eng"` | Preferred language for metadata (TVDB language code, e.g. `"eng"`, `"jpn"`, `"deu"`). |

**Example:**

```toml
[tvdb]
api_key = "your-key-here"
cache_ttl_days = 14
language = "eng"
```

---

### [naming]

Controls the exact output filenames and folder names. All format strings use Python's `str.format()` syntax.

| Key | Default | Description |
|---|---|---|
| `series_format` | `"{series_name} ({year})"` | Series root folder name. Variables: `series_name`, `year`. |
| `season_format` | `"Season {season:02d}"` | Season subfolder name. Variables: `season`. |
| `episode_format` | `"{series_name} - S{season:02d}E{episode:02d} - {episode_title}"` | Episode filename (when a title is known). Variables: `series_name`, `season`, `episode`, `episode_title`. |
| `episode_format_no_title` | `"{series_name} - S{season:02d}E{episode:02d}"` | Episode filename (when no title is available). Variables: `series_name`, `season`, `episode`. |
| `multi_episode_format` | `"{series_name} - S{season:02d}E{episode:02d}-E{episode_end:02d} - {episode_title}"` | Multi-episode filename with title. Variables: `series_name`, `season`, `episode`, `episode_end`, `episode_title`. |
| `multi_episode_format_no_title` | `"{series_name} - S{season:02d}E{episode:02d}-E{episode_end:02d}"` | Multi-episode filename without title. Variables: `series_name`, `season`, `episode`, `episode_end`. |
| `date_episode_fallback` | `"{series_name} - {date}"` | Filename for date-based episodes when no TVDB match is found. Variables: `series_name`, `date`. |
| `movie_folder_format` | `"{title} ({year})"` | Movie folder name. Variables: `title`, `year`. |
| `movie_file_format` | `"{title} ({year})"` | Movie filename (without extension). Variables: `title`, `year`. |
| `replace_colon_with` | `" -"` | What to substitute for `:` in names (colons are illegal on Windows). |
| `replace_slash_with` | `"-"` | What to substitute for `/` in names. |
| `strip_characters` | `["?", "*", "\"", "<", ">", "\|"]` | Characters to remove entirely from filenames. |

**Example — customizing episode format:**

```toml
[naming]
# Remove episode title from filename
episode_format = "{series_name} - S{season:02d}E{episode:02d}"

# Use single-digit season padding
season_format = "Season {season}"
```

---

## The Rename Workflow

When `jfvnamer rename` is run against a directory, it follows these steps:

1. **Scan** — finds all video files (recursively, unless `--no-recursive` is set).
2. **Parse** — each filename is parsed using a library of regex patterns (ported from tvnamer) to extract the series name, season, and episode numbers. Fansub noise (group tags, CRC hashes, codec tags, resolution) is stripped automatically before matching.
3. **Group** — files are grouped by their parsed title. Each group is processed separately, allowing a mixed directory containing multiple shows to be handled in one run.
4. **TVDB lookup** — for each group, TVDB is searched using the parsed title. Results are shown and you select the correct one. If a match is ambiguous, you can search again, enter an ID manually, or skip the group.
5. **Episode matching** — the tool fetches the full episode list for the selected series and matches each file to its episode by season + episode number, air date, or absolute episode number (for anime).
6. **Preview** — planned renames are displayed before any files are touched.
7. **Confirm** — you confirm or skip. If the episode ordering looks wrong, you can switch to an alternative ordering type (e.g. DVD order, absolute/anime order) and preview again.
8. **Execute** — files are moved, copied, or skipped according to your configuration.
9. **Undo log** — a JSON log of all completed operations is saved so the entire session can be reversed.

**Season detection from directory structure:**

If a file is already inside a folder named `Season 01`, `Season 1`, `S01`, etc., jfvnamer will use that as the season number even if it cannot be parsed from the filename itself. This is useful for files that only have bare episode numbers.

---

## Output Structure

jfvnamer produces the directory structure that Jellyfin expects.

**TV series:**

```
<series_root>/
  Breaking Bad (2008)/
    Season 01/
      Breaking Bad - S01E01 - Pilot.mkv
      Breaking Bad - S01E02 - Cat's in the Bag.mkv
    Season 02/
      Breaking Bad - S02E01 - Seven Thirty-Seven.mkv
```

**Movies:**

```
<movies_root>/
  Inception (2010)/
    Inception (2010).mkv
```

---

## Supported File Formats

**Video:** `.mkv`, `.avi`, `.mp4`, `.m4v`, `.ts`, `.wmv`, `.flv`, `.mov`

**Subtitle (companion files):** `.srt`, `.sub`, `.ass`, `.ssa`, `.idx`

The following filename conventions are recognized:

| Pattern | Example |
|---|---|
| Standard `SxxExx` | `Show.Name.S01E05.mkv` |
| `NxNN` notation | `Show.Name.1x05.mkv` |
| Multi-episode `S01E01E02` | `Show.S01E01E02.mkv` |
| Multi-episode `S01E01-E03` | `Show.S01E01-E03.mkv` |
| Date-based | `Show.Name.2024.03.15.mkv` |
| Absolute number (anime) | `Naruto.001.mkv` |
| Anime fansub `[Group] Show - 01` | `[SubGroup] Show Name - 23 [CRC].mkv` |
| `Season X Episode Y` words | `Show Name Season 1 Episode 5.mkv` |
| Bare episode number | `Show Name - 07.mkv` |

---

## Subtitle Handling

Subtitle files that share a video file's stem are automatically moved/copied alongside it. For example:

```
# Before
Breaking.Bad.S01E01.720p.mkv
Breaking.Bad.S01E01.720p.en.srt

# After
Breaking Bad (2008)/Season 01/Breaking Bad - S01E01 - Pilot.mkv
Breaking Bad (2008)/Season 01/Breaking Bad - S01E01 - Pilot.en.srt
```

The subtitle's language suffix (`.en`, `.fr.sdh`, etc.) is preserved.

---

## Undo System

Every successful rename or copy session writes a timestamped undo log to `~/.local/share/jfvnamer/undo/`. Running `jfvnamer undo` with no arguments reverses the most recent session.

Logs are plain JSON and can be inspected manually. They record the source and destination of every file that was moved or copied. Dry-run sessions do not produce an undo log.
