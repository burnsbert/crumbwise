"""Tests for private mode profile switching."""

import shutil
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from crumbwise import (
    app,
    _reset_backup_state,
    daily_backup,
    DEFAULT_DATA_DIR,
    _get_data_dir,
    _tasks_file,
    _settings_file,
    _notes_file,
    _backups_dir,
)
import crumbwise


@pytest.fixture
def profile_env(tmp_path):
    """Set up temp default and private data directories."""
    default_dir = tmp_path / "data"
    private_dir = default_dir / "private"
    default_dir.mkdir()
    private_dir.mkdir()

    # Create sample data in default profile
    (default_dir / "tasks.md").write_text("## TODO THIS WEEK\n\n- [ ] default task <!-- id:abc -->\n")
    (default_dir / "notes.txt").write_text("default notes")
    (default_dir / "settings.json").write_text('{"theme": 1}')

    with patch("crumbwise.DEFAULT_DATA_DIR", default_dir):
        _reset_backup_state()
        yield default_dir, private_dir


class TestProfileEndpoints:
    def test_get_profile_default(self, profile_env):
        with app.test_client() as client:
            resp = client.get("/api/profile")
            assert resp.json["profile"] == "default"

    def test_get_profile_private(self, profile_env):
        with app.test_client() as client:
            client.set_cookie("profile", "private")
            resp = client.get("/api/profile")
            assert resp.json["profile"] == "private"

    def test_toggle_from_default_to_private(self, profile_env):
        with app.test_client() as client:
            resp = client.post("/api/profile/toggle")
            assert resp.json["profile"] == "private"

    def test_toggle_from_private_to_default(self, profile_env):
        with app.test_client() as client:
            client.set_cookie("profile", "private")
            resp = client.post("/api/profile/toggle")
            assert resp.json["profile"] == "default"

    def test_toggle_sets_cookie(self, profile_env):
        with app.test_client() as client:
            resp = client.post("/api/profile/toggle")
            cookie_header = resp.headers.get("Set-Cookie", "")
            assert "profile=private" in cookie_header


class TestProfileActivation:
    def test_default_profile_uses_default_paths(self, profile_env):
        default_dir, _ = profile_env
        with app.test_request_context(headers={"Cookie": "profile=default"}):
            app.preprocess_request()
            assert _get_data_dir() == default_dir
            assert _tasks_file() == default_dir / "tasks.md"

    def test_private_profile_uses_private_paths(self, profile_env):
        _, private_dir = profile_env
        with app.test_request_context(headers={"Cookie": "profile=private"}):
            app.preprocess_request()
            assert _get_data_dir() == private_dir
            assert _tasks_file() == private_dir / "tasks.md"
            assert _settings_file() == private_dir / "settings.json"
            assert _notes_file() == private_dir / "notes.txt"
            assert _backups_dir() == private_dir / ".backups"

    def test_private_dir_created_if_missing(self, profile_env):
        _, private_dir = profile_env
        shutil.rmtree(private_dir)
        assert not private_dir.exists()
        with app.test_request_context(headers={"Cookie": "profile=private"}):
            app.preprocess_request()
            _get_data_dir()  # triggers mkdir
        assert private_dir.exists()


class TestProfileIsolation:
    def test_independent_tasks(self, profile_env):
        default_dir, private_dir = profile_env
        with app.test_client() as client:
            # Default profile has a task
            resp = client.get("/api/tasks")
            tasks = resp.json
            default_task_count = sum(len(v) for v in tasks.values())
            assert default_task_count >= 1

            # Switch to private — should have no tasks
            client.set_cookie("profile", "private")
            resp = client.get("/api/tasks")
            tasks = resp.json
            private_task_count = sum(len(v) for v in tasks.values())
            assert private_task_count == 0

    def test_independent_theme(self, profile_env):
        default_dir, private_dir = profile_env
        with app.test_client() as client:
            # Set theme in default profile
            client.post("/api/theme", json={"theme": 5})
            resp = client.get("/api/theme")
            assert resp.json["theme"] == 5

            # Switch to private — theme should be default (1 or absent)
            client.set_cookie("profile", "private")
            resp = client.get("/api/theme")
            assert resp.json["theme"] != 5

    def test_add_task_in_private_stays_in_private(self, profile_env):
        default_dir, private_dir = profile_env
        with app.test_client() as client:
            client.set_cookie("profile", "private")
            client.post("/api/tasks", json={
                "section": "TODO THIS WEEK",
                "text": "private task"
            })

            # Verify it's in the private tasks file
            private_tasks = (private_dir / "tasks.md").read_text()
            assert "private task" in private_tasks

            # Verify it's NOT in default tasks
            default_tasks = (default_dir / "tasks.md").read_text()
            assert "private task" not in default_tasks


class TestProfileBackupIsolation:
    def test_backup_runs_independently_per_profile(self, profile_env):
        default_dir, private_dir = profile_env
        _reset_backup_state()

        with app.test_client() as client:
            # Trigger backup for default profile
            client.get("/api/tasks")
            default_backup = default_dir / ".backups" / date.today().isoformat()
            assert default_backup.exists()

            # Create a file in private so backup has something to copy
            (private_dir / "tasks.md").write_text("## TODO THIS WEEK\n\n")

            # Trigger backup for private profile
            client.set_cookie("profile", "private")
            client.get("/api/tasks")
            private_backup = private_dir / ".backups" / date.today().isoformat()
            assert private_backup.exists()
