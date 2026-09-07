from __future__ import annotations

from pathlib import Path

from second_brain.core.config import Settings


def test_config_yaml_in_cwd_is_picked_up(tmp_path: Path, monkeypatch) -> None:
    """A config.yaml in the current working directory is found and its LLM
    block applied, even though it isn't the repo-root config.yaml."""
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(
        "llm:\n"
        "  model: test-cwd-model\n"
        "  max_tokens: 12345\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SECOND_BRAIN_CONFIG", raising=False)

    settings = Settings()

    assert settings.llm.model == "test-cwd-model"
    assert settings.llm.max_tokens == 12345


def test_second_brain_config_env_var_takes_priority(tmp_path: Path, monkeypatch) -> None:
    """SECOND_BRAIN_CONFIG, when set, wins over ./config.yaml in the cwd."""
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    (cwd_dir / "config.yaml").write_text("llm:\n  model: cwd-model\n")

    explicit = tmp_path / "explicit-config.yaml"
    explicit.write_text("llm:\n  model: explicit-model\n")

    monkeypatch.chdir(cwd_dir)
    monkeypatch.setenv("SECOND_BRAIN_CONFIG", str(explicit))

    settings = Settings()

    assert settings.llm.model == "explicit-model"


def test_resolve_config_path_returns_none_when_nothing_found(tmp_path: Path, monkeypatch) -> None:
    """With no SECOND_BRAIN_CONFIG, no ./config.yaml, and (for this test only)
    an empty repo root, resolution returns None and Settings falls back to
    LLMConfig defaults instead of raising."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SECOND_BRAIN_CONFIG", raising=False)
    monkeypatch.setattr("second_brain.core.config._PROJECT_ROOT", tmp_path / "nonexistent-root")

    assert Settings._resolve_config_path() is None

    settings = Settings()
    assert settings.llm.model == "deepseek/deepseek-v3.2"  # LLMConfig's own default
