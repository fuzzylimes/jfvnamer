"""Tests for config loading and merging."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jfvnamer.config import (
    _deep_merge,
    generate_user_config_template,
    load_config,
    validate_api_key,
)
from jfvnamer.models import AppConfig


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_scalar_override(self) -> None:
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        assert _deep_merge(base, override) == {"a": 1, "b": 99}

    def test_nested_merge(self) -> None:
        base = {"general": {"verbose": False, "recursive": True}}
        override = {"general": {"verbose": True}}
        result = _deep_merge(base, override)
        assert result == {"general": {"verbose": True, "recursive": True}}

    def test_new_key_added(self) -> None:
        base = {"a": 1}
        override = {"b": 2}
        assert _deep_merge(base, override) == {"a": 1, "b": 2}

    def test_empty_override(self) -> None:
        base = {"a": 1}
        assert _deep_merge(base, {}) == {"a": 1}

    def test_empty_base(self) -> None:
        override = {"a": 1}
        assert _deep_merge({}, override) == {"a": 1}


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_defaults_only(self) -> None:
        cfg = load_config(user_config_path=Path("/nonexistent/config.toml"))
        assert cfg.general.action == "move"
        assert cfg.general.recursive is True
        assert cfg.tvdb.api_key == ""
        assert cfg.naming.replace_colon_with == " -"
        assert "?" in cfg.naming.strip_characters

    def test_user_config_overrides_scalar(self, tmp_path: Path) -> None:
        user_cfg = tmp_path / "config.toml"
        user_cfg.write_text(
            '[general]\naction = "dryrun"\nverbose = true\n'
            '[tvdb]\napi_key = "my-key"\n'
        )
        cfg = load_config(user_config_path=user_cfg)
        assert cfg.general.action == "dryrun"
        assert cfg.general.verbose is True
        assert cfg.general.recursive is True
        assert cfg.tvdb.api_key == "my-key"

    def test_user_config_overrides_naming(self, tmp_path: Path) -> None:
        user_cfg = tmp_path / "config.toml"
        user_cfg.write_text('[naming]\nreplace_colon_with = " — "\n')
        cfg = load_config(user_config_path=user_cfg)
        assert cfg.naming.replace_colon_with == " — "
        assert cfg.naming.season_format == "Season {season:02d}"

    def test_cli_overrides_take_priority(self, tmp_path: Path) -> None:
        user_cfg = tmp_path / "config.toml"
        user_cfg.write_text('[general]\naction = "copy"\n')
        cfg = load_config(
            user_config_path=user_cfg,
            cli_overrides={"general": {"action": "dryrun"}},
        )
        assert cfg.general.action == "dryrun"

    def test_missing_user_config_is_fine(self) -> None:
        cfg = load_config(user_config_path=Path("/does/not/exist.toml"))
        assert isinstance(cfg, AppConfig)

    def test_invalid_action_raises(self, tmp_path: Path) -> None:
        user_cfg = tmp_path / "config.toml"
        user_cfg.write_text('[general]\naction = "invalid_action"\n')
        with pytest.raises(Exception):
            load_config(user_config_path=user_cfg)


# ---------------------------------------------------------------------------
# validate_api_key
# ---------------------------------------------------------------------------


class TestValidateApiKey:
    def test_empty_key_raises(self) -> None:
        cfg = AppConfig()
        with pytest.raises(SystemExit) as exc_info:
            validate_api_key(cfg)
        assert "TVDB API key" in str(exc_info.value)

    def test_valid_key_passes(self) -> None:
        cfg = AppConfig(tvdb={"api_key": "some-key"})  # type: ignore[arg-type]
        validate_api_key(cfg)  # should not raise


# ---------------------------------------------------------------------------
# generate_user_config_template
# ---------------------------------------------------------------------------


class TestGenerateTemplate:
    def test_template_is_valid_content(self) -> None:
        template = generate_user_config_template()
        assert "[general]" in template
        assert "[tvdb]" in template
        assert "[naming]" in template
        assert "api_key" in template

    def test_template_mentions_api_url(self) -> None:
        template = generate_user_config_template()
        assert "thetvdb.com/api-information" in template

    def test_template_has_no_default_order(self) -> None:
        template = generate_user_config_template()
        assert "default_order" not in template

    def test_template_has_no_patterns_section(self) -> None:
        template = generate_user_config_template()
        assert "[patterns]" not in template


# ---------------------------------------------------------------------------
# CLI integration (via typer test runner)
# ---------------------------------------------------------------------------


class TestConfigCLI:
    def test_config_show(self) -> None:
        from typer.testing import CliRunner
        from jfvnamer.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "general" in data
        assert "tvdb" in data
        assert "naming" in data

    def test_config_init_creates_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from typer.testing import CliRunner
        from jfvnamer import config as config_mod
        from jfvnamer.cli import app

        fake_dir = tmp_path / ".config" / "jfvnamer"
        fake_path = fake_dir / "config.toml"
        monkeypatch.setattr(config_mod, "USER_CONFIG_DIR", fake_dir)
        monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", fake_path)

        runner = CliRunner()
        result = runner.invoke(app, ["config", "init"])
        assert result.exit_code == 0
        assert fake_path.exists()
        content = fake_path.read_text()
        assert "[tvdb]" in content

    def test_config_init_refuses_overwrite(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from typer.testing import CliRunner
        from jfvnamer import config as config_mod
        from jfvnamer.cli import app

        fake_dir = tmp_path / ".config" / "jfvnamer"
        fake_dir.mkdir(parents=True)
        fake_path = fake_dir / "config.toml"
        fake_path.write_text("existing content")
        monkeypatch.setattr(config_mod, "USER_CONFIG_DIR", fake_dir)
        monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", fake_path)

        runner = CliRunner()
        result = runner.invoke(app, ["config", "init"])
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_config_init_force_overwrites(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from typer.testing import CliRunner
        from jfvnamer import config as config_mod
        from jfvnamer.cli import app

        fake_dir = tmp_path / ".config" / "jfvnamer"
        fake_dir.mkdir(parents=True)
        fake_path = fake_dir / "config.toml"
        fake_path.write_text("old content")
        monkeypatch.setattr(config_mod, "USER_CONFIG_DIR", fake_dir)
        monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", fake_path)

        runner = CliRunner()
        result = runner.invoke(app, ["config", "init", "--force"])
        assert result.exit_code == 0
        assert "[tvdb]" in fake_path.read_text()
