"""TVDB v4 API client wrapper.

Handles authentication, search, episode fetching, and caching against
the official TVDB v4 API (https://thetvdb.github.io/v4-api/).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from jfvnamer.models import (
    TVDBEpisode,
    TVDBMovieDetails,
    TVDBSearchResult,
    TVDBSeriesDetails,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api4.thetvdb.com/v4"

CACHE_DIR = Path.home() / ".cache" / "jfvnamer"
TOKEN_PATH = CACHE_DIR / "tvdb_token.json"
SEARCH_CACHE_PATH = CACHE_DIR / "search_cache.json"
EPISODE_CACHE_PATH = CACHE_DIR / "episode_cache.json"

# Map user-facing ordering names to TVDB season-type path parameters.
ORDER_MAP: dict[str, str] = {
    "aired": "default",
    "dvd": "dvd",
    "absolute": "absolute",
}


class TVDBAuthError(Exception):
    """Raised when TVDB authentication fails."""


class TVDBApiError(Exception):
    """Raised when a TVDB API call returns an error."""


class TVDBClient:
    """Client for the TVDB v4 API.

    Parameters
    ----------
    api_key:
        TVDB API key (from user config).
    cache_ttl_days:
        How long cached episode/search data is valid.
    language:
        Preferred language code (e.g. ``"eng"``).
    """

    def __init__(
        self,
        api_key: str,
        cache_ttl_days: int = 7,
        language: str = "eng",
    ) -> None:
        self._api_key = api_key
        self._cache_ttl = cache_ttl_days * 86400  # seconds
        self._language = language
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._http = httpx.Client(base_url=BASE_URL, timeout=30.0)

        # Ensure cache directory exists
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Try to load a cached token
        self._load_cached_token()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _load_cached_token(self) -> None:
        """Load a previously cached bearer token if it hasn't expired."""
        if not TOKEN_PATH.exists():
            return
        try:
            data = json.loads(TOKEN_PATH.read_text())
            if data.get("expiry", 0) > time.time():
                self._token = data["token"]
                self._token_expiry = data["expiry"]
                logger.debug(
                    "Loaded cached TVDB token (expires %.0fs from now)", data["expiry"] - time.time())
        except (json.JSONDecodeError, KeyError):
            logger.debug("Ignoring invalid cached token file")

    def _save_token(self) -> None:
        """Persist the current token to disk."""
        TOKEN_PATH.write_text(json.dumps(
            {"token": self._token, "expiry": self._token_expiry}))

    def authenticate(self) -> None:
        """POST to /login to obtain a bearer token."""
        resp = self._http.post("/login", json={"apikey": self._api_key})
        if resp.status_code != 200:
            raise TVDBAuthError(
                f"TVDB login failed (HTTP {resp.status_code}): {resp.text}")

        body = resp.json()
        token = body.get("data", {}).get("token")
        if not token:
            raise TVDBAuthError(f"TVDB login response missing token: {body}")

        self._token = token
        # TVDB v4 tokens are valid for ~30 days; we conservatively set 28 days.
        self._token_expiry = time.time() + 28 * 86400
        self._save_token()
        logger.debug("Authenticated with TVDB successfully")

    def _ensure_auth(self) -> None:
        """Make sure we have a valid token, refreshing if needed."""
        if self._token and self._token_expiry > time.time():
            return
        self.authenticate()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    # ------------------------------------------------------------------
    # Generic request helper
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """Make an authenticated GET request to the TVDB API."""
        self._ensure_auth()
        resp = self._http.get(path, headers=self._headers(), params=params)
        if resp.status_code == 401:
            # Token may have been revoked; re-auth once and retry
            logger.debug("Got 401, re-authenticating")
            self.authenticate()
            resp = self._http.get(path, headers=self._headers(), params=params)
        if resp.status_code != 200:
            raise TVDBApiError(
                f"TVDB API error (HTTP {resp.status_code}) on {path}: {resp.text}")
        return resp.json()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        media_type: str | None = None,
    ) -> list[TVDBSearchResult]:
        """Search TVDB for series and/or movies.

        Parameters
        ----------
        query:
            Search string (e.g. series/movie name).
        media_type:
            Optional filter — ``"series"`` or ``"movie"``. If ``None``,
            searches across both.
        """
        params: dict[str, str] = {"query": query}
        if media_type:
            params["type"] = media_type

        body = self._get("/search", params=params)
        results: list[TVDBSearchResult] = []

        for item in body.get("data", []):
            tvdb_id = item.get("tvdb_id") or item.get("id")
            if tvdb_id is None:
                continue
            language_title = item.get("translations", {}).get(self._language)
            results.append(
                TVDBSearchResult(
                    tvdb_id=int(tvdb_id),
                    name=language_title or item.get("name", "Unknown"),
                    type=item.get("type", "unknown"),
                    year=item.get("year"),
                    overview=item.get("overview"),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Series
    # ------------------------------------------------------------------

    def get_series_details(self, series_id: int) -> TVDBSeriesDetails:
        """Fetch extended details for a series."""
        body = self._get(f"/series/{series_id}/extended?short=true")
        data = body.get("data", {})

        season_types: list[str] = []
        for st in data.get("seasonTypes", []):
            st_type = st.get("type")
            if st_type:
                season_types.append(st_type)

        return TVDBSeriesDetails(
            tvdb_id=series_id,
            name=data.get("name", "Unknown"),
            year=data.get("year"),
            status=data.get("status", {}).get("name") if isinstance(
                data.get("status"), dict) else data.get("status"),
            season_types=season_types,
        )

    def get_episodes(
        self,
        series_id: int,
        order: str = "aired",
    ) -> list[TVDBEpisode]:
        """Fetch all episodes for a series with the given ordering.

        Parameters
        ----------
        series_id:
            TVDB series ID.
        order:
            One of ``"aired"``, ``"dvd"``, ``"absolute"``.  Mapped to the
            TVDB season-type path parameter.
        """
        # Check cache first
        cached = self._load_episode_cache(series_id, order)
        if cached is not None:
            logger.debug(
                "Using cached episodes for series %d (%s)", series_id, order)
            return cached

        season_type = ORDER_MAP.get(order, "default")
        episodes: list[TVDBEpisode] = []
        page = 0

        while True:
            body = self._get(
                f"/series/{series_id}/episodes/{season_type}/{self._language}",
                params={"page": str(page)},
            )
            data = body.get("data", {})

            for ep in data.get("episodes", []):
                episodes.append(
                    TVDBEpisode(
                        tvdb_id=ep.get("id", 0),
                        name=ep.get("name"),
                        season_number=ep.get("seasonNumber", 0),
                        episode_number=ep.get("number", 0),
                        aired=ep.get("aired"),
                        overview=ep.get("overview"),
                    )
                )

            # Handle pagination
            links = body.get("links", {})
            if links.get("next"):
                page += 1
            else:
                break

        self._save_episode_cache(series_id, order, episodes)
        return episodes

    # ------------------------------------------------------------------
    # Movies
    # ------------------------------------------------------------------

    def get_movie_details(self, movie_id: int) -> TVDBMovieDetails:
        """Fetch extended details for a movie."""
        body = self._get(f"/movies/{movie_id}/extended?short=true")
        data = body.get("data", {})
        return TVDBMovieDetails(
            tvdb_id=movie_id,
            name=data.get("name", "Unknown"),
            year=data.get("year"),
            runtime=data.get("runtime"),
        )

    # ------------------------------------------------------------------
    # Caching — search
    # ------------------------------------------------------------------

    def load_search_cache(self) -> dict[str, Any]:
        """Load the search cache from disk."""
        if not SEARCH_CACHE_PATH.exists():
            return {}
        try:
            return json.loads(SEARCH_CACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def save_search_cache(self, cache: dict[str, Any]) -> None:
        """Persist the search cache to disk."""
        SEARCH_CACHE_PATH.write_text(json.dumps(cache, indent=2))

    def get_cached_search(self, query: str) -> dict[str, Any] | None:
        """Look up a cached search-to-ID mapping.

        Returns a dict with ``tvdb_id``, ``type``, and ``name`` if cached
        and not expired, else ``None``.
        """
        cache = self.load_search_cache()
        key = query.lower().strip()
        entry = cache.get(key)
        if entry and entry.get("cached_at", 0) + self._cache_ttl > time.time():
            return entry
        return None

    def cache_search_result(self, query: str, tvdb_id: int, result_type: str, name: str) -> None:
        """Cache a user's search selection for future runs."""
        cache = self.load_search_cache()
        key = query.lower().strip()
        cache[key] = {
            "tvdb_id": tvdb_id,
            "type": result_type,
            "name": name,
            "cached_at": time.time(),
        }
        self.save_search_cache(cache)

    # ------------------------------------------------------------------
    # Caching — episodes
    # ------------------------------------------------------------------

    def _episode_cache_key(self, series_id: int, order: str) -> str:
        return f"{series_id}:{order}"

    def _load_episode_cache(self, series_id: int, order: str) -> list[TVDBEpisode] | None:
        if not EPISODE_CACHE_PATH.exists():
            return None
        try:
            cache = json.loads(EPISODE_CACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        key = self._episode_cache_key(series_id, order)
        entry = cache.get(key)
        if not entry:
            return None
        if entry.get("cached_at", 0) + self._cache_ttl <= time.time():
            return None
        return [TVDBEpisode.model_validate(ep) for ep in entry.get("episodes", [])]

    def _save_episode_cache(self, series_id: int, order: str, episodes: list[TVDBEpisode]) -> None:
        try:
            cache = json.loads(EPISODE_CACHE_PATH.read_text()
                               ) if EPISODE_CACHE_PATH.exists() else {}
        except (json.JSONDecodeError, OSError):
            cache = {}
        key = self._episode_cache_key(series_id, order)
        cache[key] = {
            "episodes": [ep.model_dump() for ep in episodes],
            "cached_at": time.time(),
        }
        EPISODE_CACHE_PATH.write_text(json.dumps(cache, indent=2))

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    @staticmethod
    def clear_cache() -> None:
        """Remove all cached data (token, searches, episodes)."""
        for path in (TOKEN_PATH, SEARCH_CACHE_PATH, EPISODE_CACHE_PATH):
            if path.exists():
                path.unlink()
                logger.info("Removed %s", path)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> TVDBClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
