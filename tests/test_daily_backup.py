"""Tests for daily backup feature."""

import shutil
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from crumbwise import app, daily_backup, _reset_backup_state
import crumbwise


@pytest.fixture
def backup_env(tmp_path):
    """Set up a temporary data directory for backup testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    backups_dir = data_dir / ".backups"

    # Create sample data files
    (data_dir / "tasks.md").write_text("## TODO\n- [ ] test task")
    (data_dir / "notes.txt").write_text("some notes")
    (data_dir / "settings.json").write_text('{"theme": 1}')

    with patch("crumbwise.DEFAULT_DATA_DIR", data_dir):
        _reset_backup_state()
        yield data_dir, backups_dir


class TestDailyBackup:
    def test_creates_dated_directory_with_files(self, backup_env):
        data_dir, backups_dir = backup_env
        today = date.today().isoformat()

        daily_backup()

        backup_dir = backups_dir / today
        assert backup_dir.exists()
        assert (backup_dir / "tasks.md").read_text() == "## TODO\n- [ ] test task"
        assert (backup_dir / "notes.txt").read_text() == "some notes"
        assert (backup_dir / "settings.json").read_text() == '{"theme": 1}'

    def test_no_duplicate_backup_same_day(self, backup_env):
        data_dir, backups_dir = backup_env

        daily_backup()
        # Modify a file after first backup
        (data_dir / "tasks.md").write_text("## TODO\n- [ ] modified")
        daily_backup()

        # Should still have original content (no re-backup)
        today = date.today().isoformat()
        assert (backups_dir / today / "tasks.md").read_text() == "## TODO\n- [ ] test task"

    def test_retains_only_three_most_recent(self, backup_env):
        data_dir, backups_dir = backup_env
        backups_dir.mkdir(parents=True, exist_ok=True)

        # Create 3 old backup dirs
        for d in ["2026-01-01", "2026-01-02", "2026-01-03"]:
            (backups_dir / d).mkdir()
            (backups_dir / d / "tasks.md").write_text("old")

        daily_backup()

        dirs = sorted(d.name for d in backups_dir.iterdir() if d.is_dir())
        assert len(dirs) == 3
        # Oldest should be pruned
        assert "2026-01-01" not in dirs
        assert date.today().isoformat() in dirs

    def test_skips_missing_files(self, backup_env):
        data_dir, backups_dir = backup_env
        # Remove notes and settings
        (data_dir / "notes.txt").unlink()
        (data_dir / "settings.json").unlink()

        daily_backup()

        today = date.today().isoformat()
        backup_dir = backups_dir / today
        assert (backup_dir / "tasks.md").exists()
        assert not (backup_dir / "notes.txt").exists()
        assert not (backup_dir / "settings.json").exists()

    def test_before_request_triggers_backup(self, backup_env):
        data_dir, backups_dir = backup_env
        _reset_backup_state()

        with app.test_client() as client:
            client.get("/api/tasks")

        today = date.today().isoformat()
        assert (backups_dir / today).exists()
