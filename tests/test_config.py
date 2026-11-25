from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.config import (
    CONTROL_FILES,
    DEFAULT_ARCHIVE_ROUTES,
    TEMP_DIRS,
    load_config,
    normalize_prompt_language,
    resolve_config_path,
)


def test_load_config_from_valid_yaml(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
watch_dir: "./incoming"
sandbox_dir: "./sandbox_box"
processed_dir: "./done_drops"
needs_review_dir: "./manual_review"
default_domain: "SOFTWARE_BACKEND"
prompt_language: "zh-TW"
prefer_google_models: false
extra_tool_dirs:
  - "./custom_tools/bin"
archive_routes:
  HARDWARE_RTL: "./out/hw"
  SOFTWARE_BACKEND: "./out/sw"
""".strip(),
        encoding="utf-8",
    )

    cfg = load_config(cfg_file)

    assert cfg.loaded_from_file is True
    assert cfg.config_path == cfg_file.resolve()
    assert cfg.watch_dir == (tmp_path / "incoming").resolve()
    assert cfg.sandbox_dir == (tmp_path / "sandbox_box").resolve()
    assert cfg.processed_dir == (tmp_path / "done_drops").resolve()
    assert cfg.needs_review_dir == (tmp_path / "manual_review").resolve()
    assert cfg.prompt_language == "zh-TW"
    assert cfg.prefer_google_models is False
    assert cfg.extra_tool_dirs == [(tmp_path / "custom_tools" / "bin").resolve()]
    assert cfg.resolve_archive_dir("HARDWARE_RTL") == (tmp_path / "out" / "hw").resolve()
    assert cfg.resolve_archive_dir("UNKNOWN_DOMAIN") == (tmp_path / "out" / "sw").resolve()


def test_load_config_missing_falls_back_with_hint(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "config.yaml"
    cfg = load_config(missing, warn_missing=True)

    captured = capsys.readouterr().out
    assert "config.example.yaml" in captured
    assert cfg.loaded_from_file is False
    assert cfg.prompt_language == "en"
    assert cfg.watch_dir == (tmp_path / "dropzone").resolve()
    assert cfg.sandbox_dir == (tmp_path / "active_sandbox").resolve()
    assert set(cfg.archive_routes.keys()) == set(DEFAULT_ARCHIVE_ROUTES.keys())


def test_resolve_config_path_uses_env_variable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_cfg = tmp_path / "env_config.yaml"
    monkeypatch.setenv("PIPELINE_CONFIG", str(env_cfg))

    assert resolve_config_path() == env_cfg


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("en", "en"),
        ("EN-US", "en"),
        ("zh-TW", "zh-TW"),
        ("zh_tw", "zh-TW"),
        ("zh", "zh-TW"),
    ],
)
def test_normalize_prompt_language(raw: str, expected: str) -> None:
    assert normalize_prompt_language(raw) == expected


@pytest.mark.parametrize(
    "content",
    [
        "- not-a-mapping",
        "watch_dir: 12345",
        "archive_routes: []",
        "prefer_google_models: 'yes'",
        "extra_tool_dirs: 'not-a-list'",
        "prompt_language: 'fr'",
        "watch_dir: [unclosed",
    ],
)
def test_load_config_rejects_invalid_yaml_or_schema(tmp_path: Path, content: str) -> None:
    bad_cfg = tmp_path / "bad.yaml"
    bad_cfg.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError):
        load_config(bad_cfg, warn_missing=False)


def test_control_files_and_temp_dirs_constants() -> None:
    assert {"_CLEAN_SPEC.md", "_FILE_TREE.txt", "_PLAN.json"}.issubset(CONTROL_FILES)
    assert "_ai_tmp" in TEMP_DIRS
