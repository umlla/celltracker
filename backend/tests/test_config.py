"""配置加载测试：BOM 兼容、环境变量覆盖。"""

from __future__ import annotations

from backend.config import Config


def test_config_reads_file_with_bom(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"port": 9123, "host": "127.0.0.1"}', encoding="utf-8-sig")
    config = Config.load(path)
    assert config.port == 9123


def test_config_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CELLTRACKER_PORT", "9321")
    monkeypatch.setenv("CELLTRACKER_DB", str(tmp_path / "custom.db"))
    config = Config.load(tmp_path / "missing.json")
    assert config.port == 9321
    assert config.db_path == (tmp_path / "custom.db").resolve()


def test_config_defaults_when_file_missing(tmp_path):
    config = Config.load(tmp_path / "nothing.json")
    assert config.db_path.name == "cell_data.db"
    assert config.auth_enabled is False
