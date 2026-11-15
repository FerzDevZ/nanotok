import json
from pathlib import Path

import pytest

from nanotok.config import (
    CONFIG_FILENAME,
    NanotokConfig,
    config_from_mapping,
    discover_config,
    load_config,
)
from nanotok.errors import ConfigError, InputError
from nanotok.models import CompressionTier


def test_load_config_returns_defaults_when_none() -> None:
    config = load_config(None)
    assert config.default_tier is CompressionTier.L1
    assert config.max_checkpoint_tokens == 90


def test_config_from_mapping_accepts_valid_overrides() -> None:
    config = config_from_mapping(
        {
            "default_tier": "L2",
            "max_checkpoint_tokens": 80,
            "auto_escalate_threshold_tokens": 12000,
            "operators": {"because": "bc", "with": "w/"},
        }
    )
    assert config.default_tier is CompressionTier.L2
    assert config.max_checkpoint_tokens == 80
    assert config.operators["because"] == "bc"


def test_config_rejects_unknown_key() -> None:
    with pytest.raises(ConfigError, match="unknown config key"):
        config_from_mapping({"unknown_flag": True})


def test_config_rejects_invalid_tier() -> None:
    with pytest.raises(InputError):
        config_from_mapping({"default_tier": "L9"})


def test_config_rejects_wrong_type() -> None:
    with pytest.raises(ConfigError):
        config_from_mapping({"max_checkpoint_tokens": "ninety"})


def test_discover_config_finds_file_upward(tmp_path: Path) -> None:
    project = tmp_path / "repo" / "src"
    project.mkdir(parents=True)
    config_path = tmp_path / "repo" / CONFIG_FILENAME
    config_path.write_text(json.dumps({"default_tier": "L1"}), encoding="utf-8")
    found = discover_config(project)
    assert found == config_path


def test_load_config_from_file(tmp_path: Path) -> None:
    config_path = tmp_path / CONFIG_FILENAME
    config_path.write_text(
        json.dumps({"default_tier": "L3", "diff_threshold_ratio": 0.6}),
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert isinstance(config, NanotokConfig)
    assert config.default_tier is CompressionTier.L3
    assert config.diff_threshold_ratio == 0.6
