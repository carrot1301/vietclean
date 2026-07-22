from pathlib import Path

import pytest

from vietclean.cli import main
from vietclean.config import ConfigError, load_config, starter_toml
from vietclean.pipeline import DataCleaner
from vietclean.profiles import list_profiles


def test_toml_config_is_non_executable_and_selects_profile(tmp_path: Path) -> None:
    path = tmp_path / "rules.toml"
    path.write_text(starter_toml("finance"), encoding="utf-8")

    loaded = load_config(path)
    cleaner = DataCleaner(config=path)

    assert loaded["version"] == 1
    assert loaded["profile"] == "finance"
    assert cleaner.profile == "finance"
    assert cleaner.config["columns"]["doanh thu"]["type"] == "currency"


def test_preset_alias_and_strict_unknown_key_validation() -> None:
    assert DataCleaner(config={"preset": "mkt"}).profile == "marketing"
    with pytest.raises(ConfigError, match="không xác định"):
        DataCleaner(config={"version": 1, "strict": True, "surprise": "value"})
    with pytest.raises(ConfigError, match="version"):
        DataCleaner(config={"version": 99})
    with pytest.raises(ConfigError, match="Key rule"):
        DataCleaner(
            config={
                "strict": True,
                "columns": {"amount": {"type": "currency", "typo_rule": True}},
            }
        )
    with pytest.raises(ConfigError, match="không được hỗ trợ"):
        DataCleaner(config={"columns": {"amount": {"type": "magical_number"}}})
    with pytest.raises(ConfigError, match="currency"):
        DataCleaner(config={"type_conversion": {"currency": "BTC"}})


@pytest.mark.parametrize(
    "config",
    [
        {"auto_types": "false"},
        {"duplicates": {"enabled": "false"}},
        {"drop": {"empty_rows": "false"}},
        {"column_names": {"deduplicate": 0}},
        {"text": {"repair_mojibake": None}},
        {"columns": {"x": {"excel_serial": "true"}}},
    ],
)
def test_boolean_config_never_uses_string_or_integer_truthiness(config: dict) -> None:
    with pytest.raises(ConfigError, match="true hoặc false|boolean"):
        DataCleaner(config=config)


@pytest.mark.parametrize(
    "config",
    [
        {"text": {"mojibake_confidence_threshold": 1.1}},
        {"missing": {"default_strategy": "guess"}},
        {"duplicates": {"action": "merge"}},
        {"outliers": {"methods": ["magic"]}},
        {"outliers": {"action": "drop"}},
        {"domain_rules": {"mode": "rewrite"}},
        {"domain_rules": {"kpi_scale": "auto"}},
        {"quality": {"threshold": 101}},
        {"quality": {"weights": {"unknown": 1}}},
    ],
)
def test_new_conservative_functional_options_fail_closed(config: dict) -> None:
    with pytest.raises(ConfigError):
        DataCleaner(config=config)


def test_cli_config_init_and_validate_toml(tmp_path: Path) -> None:
    path = tmp_path / "vietclean.toml"

    assert main(["config", "init", str(path), "--profile", "fnb"]) == 0
    assert main(["config", "validate", str(path)]) == 0
    assert DataCleaner(config=path).profile == "fnb"


@pytest.mark.parametrize("profile", list_profiles())
def test_generated_toml_round_trips_for_every_profile(tmp_path: Path, profile: str) -> None:
    path = tmp_path / f"{profile}.toml"

    assert main(["config", "init", str(path), "--profile", profile]) == 0
    assert main(["config", "validate", str(path)]) == 0
    assert DataCleaner(config=path).profile == profile


def test_invalid_toml_has_friendly_configuration_exit_code(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("version = [", encoding="utf-8")

    assert main(["config", "validate", str(path)]) == 2
