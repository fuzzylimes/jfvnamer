# Project: `jfvnamer` — A Jellyfin-Focused Video File Renamer

## Goal

Build a Python CLI tool called `jfvnamer` that renames and organizes TV show and movie files into the exact directory structure and naming conventions that Jellyfin expects. This is a spiritual successor to the abandoned `tvnamer` project (https://github.com/dbr/tvnamer), built from scratch but borrowing its battle-tested filename parsing regexes. While the original tvnamer was TV-only, this project also handles movies since TVDB indexes both, and Jellyfin has well-defined naming conventions for each.

---

## Phase 1: Project Scaffolding

Create a Python project with the following structure:

```
jfvnamer/
├── pyproject.toml
├── README.md
├── src/
│   └── jfvnamer/
│       ├── __init__.py
│       ├── cli.py              # Typer-based CLI entrypoint
│       ├── config.py           # TOML config loading with layered merge logic
│       ├── parser.py           # Filename parsing (regex engine)
│       ├── tvdb.py             # TVDB v4 API client wrapper
│       ├── renamer.py          # Path construction + rename/move/copy logic
│       ├── jellyfin.py         # Jellyfin naming convention rules
│       └── models.py           # Pydantic models for parsed files, episodes, movies, config, etc.
├── tests/
│   ├── test_parser.py
│   ├── test_jellyfin.py
│   ├── test_config.py
│   └── test_renamer.py
└── config/
    └── default.toml            # Ships with sane defaults
```

Use `pyproject.toml` with a `[project.scripts]` entry so the tool installs as `jfvnamer` on the command line. Use `typer` for CLI, `pydantic` for data models, `tomli`/`tomllib` for config parsing, and `httpx` for API calls.

---

## Phase 2: Filename Parsing (`parser.py`)

This is the most critical module. Port the filename parsing regexes from tvnamer as a starting point. The original patterns live here:
- https://github.com/dbr/tvnamer/blob/master/tvnamer/config_defaults.py (look for `filename_patterns`)

Also reference these tvnamer source files for context on how parsing was originally handled:
- Main runner / orchestration: https://github.com/dbr/tvnamer/blob/master/tvnamer/main.py
- Filename processing utilities: https://github.com/dbr/tvnamer/blob/master/tvnamer/utils.py (contains `FileParser` class and name cleanup logic)
- Data structures: https://github.com/dbr/tvnamer/blob/master/tvnamer/tvnamer_exceptions.py (the exception types reveal edge cases the original handled)

These regexes handle an enormous variety of real-world filename formats. Examples of what must parse correctly:

```
# Standard TV patterns
"Breaking Bad - S01E01 - Pilot.mkv"
"breaking.bad.s01e01.pilot.720p.bluray.mkv"
"Breaking Bad 1x01 Pilot.mkv"

# Multi-episode
"Breaking Bad - S01E01-E02.mkv"
"breaking.bad.s01e01e02.mkv"
"Breaking Bad - S01E01-S01E03.mkv"

# Date-based episodes (talk shows, daily shows)
"The Daily Show - 2024-03-15.mkv"
"The.Daily.Show.2024.03.15.mkv"

# Absolute numbering (anime)
"Naruto - 001.mkv"
"Naruto 001.mkv"

# Season packs / bare season+episode
"Lost - 301.mkv"  (season 3, episode 01)

# Edge cases
"Show Name (2024) - S01E01.mkv"  (year in show name)
"A.P. Bio - S01E01.mkv"  (dots in show name)
"Marvel's Agents of S.H.I.E.L.D. - S01E01.mkv"  (possessives and acronyms)

# Movies (no season/episode info — just a title and optionally a year)
"Inception (2010).mkv"
"inception.2010.1080p.bluray.mkv"
"The.Matrix.1999.Remastered.2160p.UHD.mkv"
"My Movie.mkv"
```

### Requirements for the parser:

1. Return a Pydantic model (`ParsedFile`) with fields: `title` (cleaned name — could be series or movie), `media_type` (`"tv"`, `"movie"`, or `"unknown"`), `season_number` (nullable), `episode_numbers` (list, nullable), `episode_name` (nullable), `year` (nullable), `date` (nullable, for date-based TV), `quality` (nullable), `source` (nullable), `file_extension`.

2. **Media type detection heuristic**: If the parser finds season/episode markers (S01E01, 1x01, date-based, absolute numbering), it's `"tv"`. If it finds only a title and optionally a year with no episode indicators, it's `"movie"`. If ambiguous (e.g., just a title, no year, no episode info), mark it `"unknown"` — the TVDB lookup will resolve it later via the disambiguation prompt.

3. Patterns should be tried in order from most specific to least specific. First match wins. TV patterns should be checked before the movie fallback pattern, since a file with episode info is definitively TV.

4. The parser should clean up names: replace dots/underscores with spaces, strip trailing dashes/whitespace, and preserve years in parentheses.

5. Include a `--parse-only` CLI flag that just shows what the parser extracted without doing any lookups or renaming. This is essential for debugging.

---

## Phase 3: TVDB v4 API Client (`tvdb.py`)

Use the **official TVDB v4 API** (https://thetvdb.github.io/v4-api/). Do NOT use dbr's `tvdb_api` library.

Reference the official Python client for API structure: https://github.com/thetvdb/tvdb-v4-python

For context on how the original tvnamer handled TVDB lookups (useful to understand the search/disambiguation problem, not the API itself):
- https://github.com/dbr/tvnamer/blob/master/tvnamer/utils.py (search for `tvdb_instance` and the series lookup flow)
- The legacy API wrapper it depended on: https://github.com/dbr/tvdb_api/blob/master/tvdb_api.py (shows what data fields were used)

### Auth flow:
- User provides their TVDB API key in config (`tvdb.api_key`)
- On first call, POST to `/login` with the API key to get a bearer token
- Cache the token in `~/.cache/jfvnamer/tvdb_token.json` with expiry
- Auto-refresh when expired

### Required API operations:

1. **Search**: `GET /search?query={name}`
   - Do NOT pass `&type=series` by default — search across both series and movies so results include everything. The TVDB API returns a `type` field on each result (`"series"` or `"movie"`) which is used to label results in the disambiguation prompt and to branch the downstream logic.
   - If the parser already determined `media_type="tv"`, you MAY add `&type=series` to narrow results. Likewise `&type=movie` if the parser said `"movie"`. If `"unknown"`, search without a type filter.
   - Present results to user interactively for disambiguation (see Phase 7 for the UX)
   - Cache ID mappings in `~/.cache/jfvnamer/search_cache.json` so repeated runs don't re-prompt

2. **Get episodes** (TV only): `GET /series/{id}/episodes/{season-type}`
   - This is where the **ordering type** matters. The `{season-type}` path parameter controls what numbering you get back. The common values are:
     - `default` — aired order
     - `dvd` — DVD order
     - `absolute` — absolute numbering (anime)
   - Expose this as a CLI flag: `--order aired|dvd|absolute` (default: `aired`)
   - This directly solves pain point #1 from the original requirements
   - Skip this entirely for movies — they have no episodes

3. **Get series details**: `GET /series/{id}/extended` for year, status, aliases

4. **Get movie details**: `GET /movies/{id}/extended` for year, runtime, aliases. The movie ID comes from the search results (different ID namespace from series).

### Caching strategy:
- Cache episode lists per series+order combo
- Default TTL: 7 days (configurable)
- `jfvnamer cache clear` command to wipe it

---

## Phase 4: Jellyfin Naming Convention (`jellyfin.py`)

Jellyfin's expected structures are documented here:
- TV Shows: https://jellyfin.org/docs/general/server/media/shows
- Movies: https://jellyfin.org/docs/general/server/media/movies

### TV show target structure:

```
{library_root}/
  {Series Name} ({Year})/
    Season {XX}/
      {Series Name} - S{XX}E{XX} - {Episode Title}.{ext}
```

### Movie target structure:

```
{library_root}/
  {Movie Title} ({Year})/
    {Movie Title} ({Year}).{ext}
```

Movies are simpler: one folder, one file, both with the same `Title (Year)` name. If the year is unavailable from TVDB, fall back to any year parsed from the filename, or omit the parenthetical entirely (same logic as TV series folders).

### TV rules to implement:

1. **Series folder**: Always `Series Name (Year)`. The year comes from TVDB. If TVDB doesn't have a year, fall back to any year parsed from the filename, or omit the parenthetical entirely.

2. **Season folder**: Always `Season XX` with zero-padded two digits. **Critical**: If the parsed episode has no season number (e.g., absolute-numbered anime), default to `Season 01`. If the TVDB lookup returns a season number, use that instead. This directly solves pain point #2.

3. **Episode file**: `Series Name - S01E01 - Episode Title.ext`
   - Multi-episode: `Series Name - S01E01-E02 - Episode Title.ext`
   - No episode title from TVDB: `Series Name - S01E01.ext` (omit the trailing dash-space)
   - Specials: `Season 00/Series Name - S00E{XX} - Special Title.ext`

4. **Date-based episodes**: Convert to the season+episode from TVDB lookup. If lookup fails, use `Season {year}/Series Name - {date}.ext` as fallback.

5. **Sanitize filenames**: Remove characters invalid on common filesystems (`:`, `?`, `*`, `"`, `<`, `>`, `|`). Replace `:` with ` -`. Trim trailing dots and spaces (Windows issue).

### Movie rules to implement:

1. **Movie folder**: `Movie Title (Year)`. Year from TVDB, with the same fallback chain as TV series (parsed year → omit).

2. **Movie file**: `Movie Title (Year).ext` — same name as the folder.

3. **Extras / bonus features**: Out of scope for now. If a file is identified as a movie, just handle the main feature. This can be extended later.

4. **Sanitization**: Same rules as TV — invalid characters stripped, colons replaced.

### Shared logic:

The `jellyfin.py` module should expose a single entry point like `build_target_path(parsed_file, tvdb_metadata)` that branches internally based on whether the TVDB result is a series or movie. The renamer shouldn't need to care about the distinction — it just gets a complete target path back.

---

## Phase 5: Config System (`config.py`)

Use TOML. This directly addresses pain point #4.

For context on the config system being replaced (and its shortcomings to avoid repeating):
- https://github.com/dbr/tvnamer/blob/master/tvnamer/config_defaults.py (the monolithic defaults blob)
- https://github.com/dbr/tvnamer/blob/master/tvnamer/config.py (the loading/merge logic — note how user values wholesale-replace defaults)

### Layered config resolution (highest priority wins):
1. CLI flags
2. User config at `~/.config/jfvnamer/config.toml`
3. Built-in defaults from `config/default.toml`

### Merge semantics (this is critical):

For **scalar values** (strings, numbers, bools): higher priority wins (simple override).

For **list values** (like filename patterns): use explicit merge directives. The user config should be able to:
- **Prepend** patterns (checked first): `patterns_prepend = [...]`
- **Append** patterns (checked after defaults): `patterns_append = [...]`
- **Replace entirely** (opt-in, not the default): `patterns_replace = [...]`

This way, adding one custom pattern doesn't nuke the 50+ defaults.

### Default config file (`config/default.toml`):

```toml
[general]
library_root = "."          # where to output renamed files
action = "move"             # "move", "copy", or "dryrun"
recursive = true            # scan subdirectories
verbose = false

[tvdb]
api_key = ""                # user must provide
default_order = "aired"     # "aired", "dvd", "absolute"
cache_ttl_days = 7
language = "eng"

[naming]
series_format = "{series_name} ({year})"
season_format = "Season {season:02d}"
episode_format = "{series_name} - S{season:02d}E{episode:02d} - {episode_title}"
episode_format_no_title = "{series_name} - S{season:02d}E{episode:02d}"
multi_episode_format = "{series_name} - S{season:02d}E{episode:02d}-E{episode_end:02d} - {episode_title}"
date_episode_fallback = "{series_name} - {date}"
movie_folder_format = "{title} ({year})"
movie_file_format = "{title} ({year})"
replace_colon_with = " -"
strip_characters = ['?', '*', '"', '<', '>', '|']

[patterns]
# Users use patterns_prepend / patterns_append in their config
# to add patterns without overwriting defaults.
# patterns_replace will replace ALL defaults if set.
```

### Config validation:
- On load, validate with Pydantic
- If `tvdb.api_key` is empty and the user isn't running `--parse-only`, error with a helpful message explaining how to get one from https://thetvdb.com/api-information
- If the user config file doesn't exist, `jfvnamer config init` should generate a commented template

---

## Phase 6: Rename/Move Engine (`renamer.py`)

For context on how the original tvnamer handled the rename workflow:
- https://github.com/dbr/tvnamer/blob/master/tvnamer/utils.py (search for `FileFinder` and the move/copy logic)
- https://github.com/dbr/tvnamer/blob/master/tvnamer/main.py (the main loop that ties parsing → lookup → rename together)

### Core workflow:
1. Scan the input path for video files (`.mkv`, `.avi`, `.mp4`, `.m4v`, `.ts`, `.wmv`, `.flv`, `.mov`)
2. For each file, run the parser
3. Look up the title from TVDB (with interactive disambiguation on first encounter). The search may return series or movie results — the user's selection determines the downstream path.
4. If the result is a **TV series**: fetch episodes with the selected ordering, match the parsed season/episode, and build the Jellyfin TV path
5. If the result is a **movie**: fetch movie details (year, official title) and build the Jellyfin movie path
6. Execute the action: move, copy, symlink, hardlink, or dry-run

### Safety features:
- **Dry-run by default for first-time users**: If no config file exists, default to `dryrun` and print what would happen
- **Conflict detection**: If target file already exists, prompt (or skip with `--skip-existing`)
- **Undo log**: Write a JSON log of all moves to `~/.local/share/jfvnamer/undo/{timestamp}.json` so renames can be reversed with `jfvnamer undo`
- **Atomic moves**: Use `shutil.move` for same-filesystem, copy-then-delete for cross-filesystem
- **Subtitle handling**: When renaming a video file, also rename any matching subtitle files (`.srt`, `.sub`, `.ass`, `.ssa`, `.idx`) with the same base name. Preserve language tags like `.en.srt`.

---

## Phase 7: CLI Interface (`cli.py`)

Use `typer` with the following command structure:

```
jfvnamer rename <path> [options]      # Main rename workflow
jfvnamer parse <path>                 # Parse-only mode, no TVDB lookup
jfvnamer search <query>               # Search TVDB interactively
jfvnamer config init                  # Create template config file
jfvnamer config show                  # Print resolved config (all layers merged)
jfvnamer cache clear                  # Clear TVDB cache
jfvnamer undo [log_file]              # Reverse a rename operation
```

### Key CLI flags for `rename`:
```
--order aired|dvd|absolute     Override episode ordering (TV only, ignored for movies)
--action move|copy|dryrun      Override action
--library-root PATH            Override output root
--no-prompt                    Non-interactive mode (skip ambiguous, log warnings)
--series-id ID                 Force a specific TVDB series ID (skip search)
--movie-id ID                  Force a specific TVDB movie ID (skip search)
--season NUMBER                Force season number for all files (TV only)
-v / --verbose                 Detailed output
```

### Interactive disambiguation UX:
When a title matches multiple TVDB results, present a numbered list with type labels and a manual ID override option:

```
Multiple matches found for "The Batman":
  1. [Series] The Batman (2004) — TVDB ID: 77551
  2. [Movie]  The Batman (2022) — TVDB ID: 331482
  3. [Series] Batman (1966) — TVDB ID: 77871

Select [1-3, i=enter TVDB ID manually, s=skip, q=quit]:
```

The `[Series]`/`[Movie]` label comes from the `type` field in the TVDB search response. This is how the user knows whether they're picking a TV show or a film — the downstream logic (episode lookup vs movie path) branches automatically based on this.

If the user selects `i`, prompt them for a TVDB ID directly, then ask whether it's a series or movie ID (since TVDB uses separate ID namespaces):

```
Enter TVDB ID: 331482
Is this a [s]eries or [m]ovie? m
```

The `--series-id` CLI flag should still exist for scripted/non-interactive use. Consider also adding a `--movie-id` flag to match, or a single `--tvdb-id` flag with a `--type series|movie` companion.

### Episode ordering selection (TV series only):

If the selected TVDB result is a movie, skip this step entirely — movies have no episode ordering.

If the selected result is a TV series and `--order` was NOT passed on the command line, prompt the user to select an ordering. Query the TVDB API for available season types for that series (the `/series/{id}/extended` endpoint returns this) and present only the ones that actually exist:

```
Episode ordering for "The Office (US)":
  1. Aired Order (8 seasons, 188 episodes)
  2. DVD Order (8 seasons, 188 episodes)
  3. Absolute Order (188 episodes)

Select [1-3]:
```

Show the season/episode counts for each ordering so the user can see at a glance whether they differ (which is the whole reason this choice matters). If only one ordering type exists, auto-select it silently.

**Auto-detection heuristic**: If the parsed filename contains keywords like `dvd`, `dvdrip`, `bd`, `bdrip`, `bluray`, or `blu-ray` (case-insensitive), automatically pre-select `dvd` ordering and note it in the output: `Auto-selected DVD ordering based on filename. Override with --order aired`. The user can still override via the prompt or CLI flag.

Cache the ordering selection alongside the series selection so repeated runs don't re-prompt.

---

## Phase 8: Tests

Write tests for the following areas:

### Parser tests (`test_parser.py`):
- All the example filenames from Phase 2 (both TV and movie patterns)
- Edge cases: unicode characters, extremely long names, names with only numbers
- Verify parsed fields are correct (not just that it doesn't crash)
- Media type detection: files with S01E01 → `"tv"`, files with just title+year → `"movie"`, ambiguous files → `"unknown"`

### Jellyfin path tests (`test_jellyfin.py`):
- Standard TV episode → correct path
- Missing year → path without parenthetical
- Missing season → defaults to Season 01
- Multi-episode → correct hyphenated format
- Specials → Season 00
- Invalid filesystem characters → sanitized
- Date-based episodes → both resolved and fallback formats
- Movie with year → `Title (Year)/Title (Year).ext`
- Movie without year → `Title/Title.ext`
- Movie with colons/special chars → sanitized correctly

### Config tests (`test_config.py`):
- Default config loads cleanly
- User config overrides scalars correctly
- `patterns_prepend` adds to front of list
- `patterns_append` adds to end of list
- `patterns_replace` fully replaces
- Missing user config → defaults only
- Invalid config → helpful error message

### Renamer tests (`test_renamer.py`):
- Dry-run produces correct output without touching filesystem
- Subtitle files are renamed alongside video files
- Conflict detection works
- Undo log is written correctly

---

## Implementation Notes

- **Python version**: Target 3.10+ (Ubuntu 24.04 ships 3.12)
- **No external dependency on tvnamer or tvdb_api**: This is a clean project. Only reference those repos for the regex patterns and to understand the problem domain.
- **Type hints everywhere**: Use modern Python typing. All functions should have full type annotations.
- **Logging**: Use Python's `logging` module. `--verbose` sets DEBUG, default is INFO.
- **Progress output**: For large batches, show a progress summary. Consider `rich` for pretty terminal output if you want, but it's not required. Keep `typer` + `rich` usage lightweight.
- **Error handling**: Never crash on a single bad file. Log the error, skip the file, continue. Summarize failures at the end.

---

## What to Build First

Work through the phases in this order. Each phase should be functional and testable before moving on:

1. **Phase 1 — Scaffolding**: Set up the project structure, `pyproject.toml`, and install dependencies
2. **Phase 2 — Models + Parser**: Define all Pydantic models, port the regexes, write parser tests, get `jfvnamer parse` working as a standalone command
3. **Phase 3 — Config**: Layered TOML loading with merge logic and validation
4. **Phase 4 — TVDB client**: Auth, search, episode fetching, and caching
5. **Phase 5 — Jellyfin naming**: Path construction logic and filename sanitization
6. **Phase 6 — Rename engine**: Wire parser → TVDB → Jellyfin naming → filesystem operations together
7. **Phase 7 — CLI**: Full command structure, interactive prompts, ordering selection flow
8. **Phase 8 — Tests**: Fill in any remaining test coverage across all modules

Note that models (listed separately in the directory structure as `models.py`) should be built as part of Phase 2 since the parser is their first consumer. Similarly, tests should be written alongside each phase, not only at the end — Phase 8 is for filling gaps, not writing everything from scratch.

This order lets you validate each piece independently. The parser alone is useful even without TVDB.
