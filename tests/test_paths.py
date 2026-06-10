"""Per-user path resolution: defaults live under one root and honour the override."""

from __future__ import annotations

from reactions import paths


def test_override_groups_everything_under_one_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MAKNASSA_DATA_DIR", str(tmp_path))
    assert paths.app_data_dir() == tmp_path
    assert paths.default_db_path() == tmp_path / "data" / "reactions.db"
    assert paths.default_profile_dir() == tmp_path / "profiles" / "facebook"
    assert paths.default_profile_dir("work") == tmp_path / "profiles" / "work"


def test_app_data_dir_is_created(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "root"
    monkeypatch.setenv("MAKNASSA_DATA_DIR", str(target))
    assert paths.app_data_dir().is_dir()
