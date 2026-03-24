"""Tests for the TVDB v4 API client."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jfvnamer.tvdb import (
    BASE_URL,
    ORDER_MAP,
    TVDBApiError,
    TVDBAuthError,
    TVDBClient,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int = 200, json_data: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


@pytest.fixture()
def tmp_cache(tmp_path, monkeypatch):
    """Redirect all cache paths to a temp directory."""
    monkeypatch.setattr("jfvnamer.tvdb.CACHE_DIR", tmp_path)
    monkeypatch.setattr("jfvnamer.tvdb.TOKEN_PATH",
                        tmp_path / "tvdb_token.json")
    monkeypatch.setattr("jfvnamer.tvdb.SEARCH_CACHE_PATH",
                        tmp_path / "search_cache.json")
    monkeypatch.setattr("jfvnamer.tvdb.EPISODE_CACHE_PATH",
                        tmp_path / "episode_cache.json")
    return tmp_path


@pytest.fixture()
def client(tmp_cache):
    """Create a TVDBClient with a fake API key and pre-set token."""
    c = TVDBClient(api_key="fake-key", cache_ttl_days=7)
    # Pre-populate a valid token so tests don't need to mock /login
    c._token = "fake-token"
    c._token_expiry = time.time() + 3600
    return c


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuth:
    def test_authenticate_success(self, tmp_cache):
        c = TVDBClient(api_key="test-key")
        mock_resp = _mock_response(200, {"data": {"token": "new-token"}})
        with patch.object(c._http, "post", return_value=mock_resp):
            c.authenticate()
        assert c._token == "new-token"
        assert c._token_expiry > time.time()
        # Token should be cached on disk
        token_path = tmp_cache / "tvdb_token.json"
        assert token_path.exists()
        cached = json.loads(token_path.read_text())
        assert cached["token"] == "new-token"

    def test_authenticate_failure(self, tmp_cache):
        c = TVDBClient(api_key="bad-key")
        mock_resp = _mock_response(401, text="Unauthorized")
        with patch.object(c._http, "post", return_value=mock_resp):
            with pytest.raises(TVDBAuthError, match="login failed"):
                c.authenticate()

    def test_authenticate_missing_token(self, tmp_cache):
        c = TVDBClient(api_key="test-key")
        mock_resp = _mock_response(200, {"data": {}})
        with patch.object(c._http, "post", return_value=mock_resp):
            with pytest.raises(TVDBAuthError, match="missing token"):
                c.authenticate()

    def test_load_cached_token(self, tmp_cache):
        token_path = tmp_cache / "tvdb_token.json"
        token_path.write_text(json.dumps(
            {"token": "cached-tok", "expiry": time.time() + 9999}))
        c = TVDBClient(api_key="key")
        assert c._token == "cached-tok"

    def test_expired_cached_token_ignored(self, tmp_cache):
        token_path = tmp_cache / "tvdb_token.json"
        token_path.write_text(json.dumps(
            {"token": "old-tok", "expiry": time.time() - 1}))
        c = TVDBClient(api_key="key")
        assert c._token is None

    def test_auto_reauth_on_401(self, client):
        """If a GET returns 401, the client should re-authenticate and retry."""
        first_resp = _mock_response(401, text="Expired")
        second_resp = _mock_response(200, {"data": []})
        auth_resp = _mock_response(200, {"data": {"token": "refreshed"}})

        with patch.object(client._http, "get", side_effect=[first_resp, second_resp]):
            with patch.object(client._http, "post", return_value=auth_resp):
                result = client._get("/some/path")
        assert result == {"data": []}
        assert client._token == "refreshed"


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_returns_results(self, client):
        api_data = {
            "data": [
                {
                    "tvdb_id": "77551",
                    "name": "The Batman",
                    "type": "series",
                    "year": "2004",
                    "overview": "Animated series",
                },
                {
                    "id": "331482",
                    "name": "The Batman",
                    "type": "movie",
                    "year": "2022",
                    "overview": "A film",
                },
            ]
        }
        mock_resp = _mock_response(200, api_data)
        with patch.object(client._http, "get", return_value=mock_resp):
            results = client.search("The Batman")

        assert len(results) == 2
        assert results[0].tvdb_id == 77551
        assert results[0].type == "series"
        assert results[1].tvdb_id == 331482
        assert results[1].type == "movie"

    def test_search_with_type_filter(self, client):
        mock_resp = _mock_response(200, {"data": []})
        with patch.object(client._http, "get", return_value=mock_resp) as mock_get:
            client.search("Breaking Bad", media_type="series")
        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["params"]["type"] == "series"

    def test_search_without_type_filter(self, client):
        mock_resp = _mock_response(200, {"data": []})
        with patch.object(client._http, "get", return_value=mock_resp) as mock_get:
            client.search("Inception")
        call_kwargs = mock_get.call_args
        assert "type" not in call_kwargs.kwargs["params"]

    def test_search_skips_items_without_id(self, client):
        api_data = {"data": [{"name": "No ID", "type": "series"}]}
        mock_resp = _mock_response(200, api_data)
        with patch.object(client._http, "get", return_value=mock_resp):
            results = client.search("No ID")
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Series / episodes tests
# ---------------------------------------------------------------------------


class TestSeries:
    def test_get_series_details(self, client):
        api_data = {
            "data": {
                "name": "Breaking Bad",
                "year": "2008",
                "status": {"name": "Ended"},
                "seasonTypes": [
                    {"type": "default"},
                    {"type": "dvd"},
                    {"type": "absolute"},
                ],
            }
        }
        mock_resp = _mock_response(200, api_data)
        with patch.object(client._http, "get", return_value=mock_resp):
            details = client.get_series_details(81189)

        assert details.tvdb_id == 81189
        assert details.name == "Breaking Bad"
        assert details.year == "2008"
        assert details.status == "Ended"
        assert "default" in details.season_types
        assert "dvd" in details.season_types
        assert "absolute" in details.season_types

    def test_get_episodes_single_page(self, client):
        api_data = {
            "data": {
                "episodes": [
                    {"id": 1, "name": "Pilot", "seasonNumber": 1,
                        "number": 1, "aired": "2008-01-20"},
                    {"id": 2, "name": "Cat's in the Bag...",
                        "seasonNumber": 1, "number": 2, "aired": "2008-01-27"},
                ]
            },
            "links": {"next": None},
        }
        mock_resp = _mock_response(200, api_data)
        with patch.object(client._http, "get", return_value=mock_resp):
            episodes = client.get_episodes(81189, order="aired")

        assert len(episodes) == 2
        assert episodes[0].name == "Pilot"
        assert episodes[0].season_number == 1
        assert episodes[0].episode_number == 1
        assert episodes[1].episode_number == 2

    def test_get_episodes_paginated(self, client):
        page0 = {
            "data": {
                "episodes": [{"id": 1, "name": "Ep1", "seasonNumber": 1, "number": 1}]
            },
            "links": {"next": "some-url"},
        }
        page1 = {
            "data": {
                "episodes": [{"id": 2, "name": "Ep2", "seasonNumber": 1, "number": 2}]
            },
            "links": {"next": None},
        }
        resp0 = _mock_response(200, page0)
        resp1 = _mock_response(200, page1)
        with patch.object(client._http, "get", side_effect=[resp0, resp1]):
            episodes = client.get_episodes(81189, order="aired")

        assert len(episodes) == 2
        assert episodes[0].name == "Ep1"
        assert episodes[1].name == "Ep2"

    def test_get_episodes_uses_cache(self, client, tmp_cache):
        """Second call should return cached data without hitting the API."""
        api_data = {
            "data": {
                "episodes": [{"id": 1, "name": "Pilot", "seasonNumber": 1, "number": 1}]
            },
            "links": {"next": None},
        }
        mock_resp = _mock_response(200, api_data)
        with patch.object(client._http, "get", return_value=mock_resp) as mock_get:
            first = client.get_episodes(12345, order="aired")
            second = client.get_episodes(12345, order="aired")

        # HTTP should only be called once (for page 0 of the first call)
        assert mock_get.call_count == 1
        assert len(first) == 1
        assert len(second) == 1
        assert first[0].name == second[0].name


# ---------------------------------------------------------------------------
# Movie tests
# ---------------------------------------------------------------------------


class TestMovie:
    def test_get_movie_details(self, client):
        api_data = {
            "data": {
                "name": "Inception",
                "year": "2010",
                "runtime": 148,
            }
        }
        mock_resp = _mock_response(200, api_data)
        with patch.object(client._http, "get", return_value=mock_resp):
            movie = client.get_movie_details(24680)

        assert movie.tvdb_id == 24680
        assert movie.name == "Inception"
        assert movie.year == "2010"
        assert movie.runtime == 148


# ---------------------------------------------------------------------------
# Search cache tests
# ---------------------------------------------------------------------------


class TestSearchCache:
    def test_cache_and_retrieve(self, client):
        client.cache_search_result(
            "breaking bad", tvdb_id=81189, result_type="series", name="Breaking Bad")
        cached = client.get_cached_search("Breaking Bad")
        assert cached is not None
        assert cached["tvdb_id"] == 81189
        assert cached["type"] == "series"

    def test_cache_miss(self, client):
        assert client.get_cached_search("nonexistent") is None

    def test_cache_expired(self, client):
        client.cache_search_result(
            "old show", tvdb_id=1, result_type="series", name="Old Show")
        # Manually expire the entry
        cache = client.load_search_cache()
        cache["old show"]["cached_at"] = time.time() - client._cache_ttl - 1
        client.save_search_cache(cache)
        assert client.get_cached_search("old show") is None


# ---------------------------------------------------------------------------
# Cache management tests
# ---------------------------------------------------------------------------


class TestCacheManagement:
    def test_clear_cache(self, tmp_cache):
        # Create some cache files
        for name in ("tvdb_token.json", "search_cache.json", "episode_cache.json"):
            (tmp_cache / name).write_text("{}")

        TVDBClient.clear_cache()

        for name in ("tvdb_token.json", "search_cache.json", "episode_cache.json"):
            assert not (tmp_cache / name).exists()

    def test_clear_cache_missing_files(self, tmp_cache):
        """Should not raise if files don't exist."""
        TVDBClient.clear_cache()


# ---------------------------------------------------------------------------
# Order map tests
# ---------------------------------------------------------------------------


class TestOrderMap:
    def test_aired_maps_to_default(self):
        assert ORDER_MAP["aired"] == "default"

    def test_dvd_maps_to_dvd(self):
        assert ORDER_MAP["dvd"] == "dvd"

    def test_absolute_maps_to_absolute(self):
        assert ORDER_MAP["absolute"] == "absolute"


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_context_manager(self, tmp_cache):
        with TVDBClient(api_key="key") as c:
            assert c._api_key == "key"
        # After exit, the http client should be closed
        assert c._http.is_closed


# ---------------------------------------------------------------------------
# API error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_api_error_on_non_200(self, client):
        mock_resp = _mock_response(500, text="Internal Server Error")
        with patch.object(client._http, "get", return_value=mock_resp):
            with pytest.raises(TVDBApiError, match="500"):
                client._get("/bad/path")
