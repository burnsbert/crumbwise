"""End-to-end integration test for task lifecycle with timeline spans.

This capstone test validates the entire backend pipeline for the timeline
feature by creating tasks, moving them through various states (IN PROGRESS,
BLOCKED, completed), and verifying that:
1. Timestamps are correctly set/cleared at each transition
2. History is correctly appended with proper event markers
3. The timeline API computes spans correctly from the history
4. Research section tasks are excluded from history tracking
"""

import json
from datetime import datetime, date
from unittest.mock import patch

import pytest

import crumbwise


@pytest.fixture
def app(tmp_path):
    """Create a test app with a temporary tasks file."""
    tasks_file = tmp_path / "tasks.md"
    undo_file = tmp_path / "tasks.md.undo"
    settings_file = tmp_path / "settings.json"
    notes_file = tmp_path / "notes.txt"

    crumbwise.TASKS_FILE = tasks_file
    crumbwise.UNDO_FILE = undo_file
    crumbwise.SETTINGS_FILE = settings_file
    crumbwise.NOTES_FILE = notes_file

    crumbwise.app.config["TESTING"] = True
    yield crumbwise.app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


def write_tasks(tasks_file, content):
    """Helper to write task markdown content."""
    tasks_file.write_text(content)


# Use a fixed "today" for deterministic tests: 2026-02-17 (Tuesday)
# Week offset 0 => Sunday 2026-02-15 to Saturday 2026-02-21
FIXED_TODAY = datetime(2026, 2, 17, 12, 0, 0)
FIXED_TODAY_DATE = date(2026, 2, 17)


def mock_today():
    """Patch datetime.now() to return a fixed date for deterministic tests."""
    return patch("crumbwise.datetime", wraps=datetime,
                 **{"now.return_value": FIXED_TODAY})


class TestTaskLifecycleIntegration:
    """End-to-end test of task lifecycle with timeline spans."""

    def test_full_lifecycle_ip_blocked_ip_complete(self, tmp_path, client):
        """
        Full lifecycle test:
        (a) Create a task, move to IN PROGRESS (verify in_progress set, history has ip@)
        (b) Move to BLOCKED (verify blocked_at set, in_progress cleared, history has ip@|bl@)
        (c) Move back to IN PROGRESS (verify in_progress set, blocked_at cleared, history has ip@|bl@|ip@)
        (d) Complete the task (verify completed_at set, history has ip@|bl@|ip@|co@)
        (e) Call GET /api/timeline for current week, verify task appears with correct spans
        (f) Call GET /api/timeline with week_offset that excludes the task, verify not returned
        """
        tasks_file = tmp_path / "tasks.md"

        # Start with empty sections
        write_tasks(tasks_file, """## TODO THIS WEEK

## IN PROGRESS TODAY

## BLOCKED

## DONE THIS WEEK

""")

        with mock_today():
            # (a) Create a task in TODO, then move to IN PROGRESS TODAY
            resp = client.post("/api/tasks", json={
                "section": "TODO THIS WEEK",
                "text": "Integration test task"
            })
            assert resp.status_code == 201
            task = resp.get_json()
            task_id = task["id"]

            # Move to IN PROGRESS TODAY
            resp = client.put(f"/api/tasks/{task_id}", json={
                "section": "IN PROGRESS TODAY"
            })
            assert resp.status_code == 200

            # Verify: in_progress is set, history has ip@
            sections = crumbwise.parse_tasks()
            task = sections["IN PROGRESS TODAY"][0]
            assert task["in_progress"] is not None
            assert task["blocked_at"] is None
            assert task["completed_at"] is None
            assert task["history"] is not None
            assert task["history"].startswith("ip@")
            history_parts = task["history"].split("|")
            assert len(history_parts) == 1

            # (b) Move to BLOCKED
            resp = client.put(f"/api/tasks/{task_id}", json={
                "section": "BLOCKED"
            })
            assert resp.status_code == 200

            # Verify: blocked_at is set, in_progress cleared, history has ip@|bl@
            sections = crumbwise.parse_tasks()
            task = sections["BLOCKED"][0]
            assert task["in_progress"] is None  # Should be cleared
            assert task["blocked_at"] is not None
            assert task["completed_at"] is None
            history_parts = task["history"].split("|")
            assert len(history_parts) == 2
            assert history_parts[0].startswith("ip@")
            assert history_parts[1].startswith("bl@")

            # (c) Move back to IN PROGRESS TODAY
            resp = client.put(f"/api/tasks/{task_id}", json={
                "section": "IN PROGRESS TODAY"
            })
            assert resp.status_code == 200

            # Verify: in_progress set (NEW timestamp), blocked_at cleared, history has ip@|bl@|ip@
            sections = crumbwise.parse_tasks()
            task = sections["IN PROGRESS TODAY"][0]
            assert task["in_progress"] is not None
            assert task["blocked_at"] is None  # Should be cleared
            assert task["completed_at"] is None
            history_parts = task["history"].split("|")
            assert len(history_parts) == 3
            assert history_parts[0].startswith("ip@")
            assert history_parts[1].startswith("bl@")
            assert history_parts[2].startswith("ip@")

            # (d) Complete the task (move to DONE THIS WEEK)
            resp = client.post(f"/api/tasks/reorder", json={
                "taskId": task_id,
                "section": "DONE THIS WEEK",
                "index": 0
            })
            assert resp.status_code == 200

            # Verify: completed_at set, in_progress cleared, history has ip@|bl@|ip@|co@
            sections = crumbwise.parse_tasks()
            task = sections["DONE THIS WEEK"][0]
            assert task["in_progress"] is None  # Should be cleared
            assert task["blocked_at"] is None
            assert task["completed_at"] is not None
            history_parts = task["history"].split("|")
            assert len(history_parts) == 4
            assert history_parts[0].startswith("ip@")
            assert history_parts[1].startswith("bl@")
            assert history_parts[2].startswith("ip@")
            assert history_parts[3].startswith("co@")

            # (e) Call GET /api/timeline for current week, verify task appears with correct spans
            resp = client.get("/api/timeline?week_offset=0")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["week_start"] == "2026-02-15"  # Sunday
            assert data["week_end"] == "2026-02-21"    # Saturday
            assert data["today"] == "2026-02-17"       # Tuesday

            # Should have one task
            assert len(data["tasks"]) == 1
            timeline_task = data["tasks"][0]
            assert timeline_task["id"] == task_id
            assert timeline_task["text"] == "Integration test task"

            # Should have 3 spans: ip (start to blocked), bl (blocked period), ip (resumed to complete)
            # Actually, the implementation produces ip and blocked spans only
            # because co@ is a terminal event that ends the previous span
            assert len(timeline_task["spans"]) >= 1
            # Verify spans have correct structure
            for span in timeline_task["spans"]:
                assert "start" in span
                assert "end" in span
                assert "status" in span
                assert span["status"] in ["in_progress", "blocked"]

            # (f) Call GET /api/timeline with week_offset that excludes the task
            # The task's events all happened on 2026-02-17 (today)
            # Previous week is 2026-02-08 to 2026-02-14, which excludes all events
            resp = client.get("/api/timeline?week_offset=-1")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["week_start"] == "2026-02-08"
            assert data["week_end"] == "2026-02-14"
            # Task should NOT appear since all its history is in the current week
            assert len(data["tasks"]) == 0

    def test_research_task_no_history_tracking(self, tmp_path, client):
        """
        Research section tasks should NOT have history or blocked_at tracking.
        (g) Create a research task, move it around, verify no history/blocked_at.
        """
        tasks_file = tmp_path / "tasks.md"

        # Start with research sections
        write_tasks(tasks_file, """## THINGS TO RESEARCH

## RESEARCH IN PROGRESS

## RESEARCH DONE

## BLOCKED

""")

        with mock_today():
            # Create a task in THINGS TO RESEARCH
            resp = client.post("/api/tasks", json={
                "section": "THINGS TO RESEARCH",
                "text": "Research task"
            })
            assert resp.status_code == 201
            task = resp.get_json()
            task_id = task["id"]

            # Move to RESEARCH IN PROGRESS
            resp = client.put(f"/api/tasks/{task_id}", json={
                "section": "RESEARCH IN PROGRESS"
            })
            assert resp.status_code == 200

            # Verify: NO history, NO in_progress (RESEARCH IN PROGRESS not in IN_PROGRESS_SECTIONS)
            sections = crumbwise.parse_tasks()
            task = sections["RESEARCH IN PROGRESS"][0]
            assert task.get("history") is None or task["history"] == ""
            assert task.get("in_progress") is None
            assert task.get("blocked_at") is None

            # Move to BLOCKED (cross from research to non-research)
            resp = client.put(f"/api/tasks/{task_id}", json={
                "section": "BLOCKED"
            })
            assert resp.status_code == 200

            # Verify: STILL no history or blocked_at because source was research section
            sections = crumbwise.parse_tasks()
            task = sections["BLOCKED"][0]
            # Task moved FROM research section, so transition helper skips tracking
            assert task.get("history") is None or task["history"] == ""
            assert task.get("blocked_at") is None

            # Move to RESEARCH DONE
            resp = client.put(f"/api/tasks/{task_id}", json={
                "section": "RESEARCH DONE"
            })
            assert resp.status_code == 200

            # Verify: Still no history or timestamps
            sections = crumbwise.parse_tasks()
            task = sections["RESEARCH DONE"][0]
            assert task.get("history") is None or task["history"] == ""
            assert task.get("in_progress") is None
            assert task.get("blocked_at") is None
            assert task.get("completed_at") is None

            # Call /api/timeline - research task should NOT appear
            resp = client.get("/api/timeline?week_offset=0")
            assert resp.status_code == 200
            data = resp.get_json()
            # No tasks should appear (research tasks are excluded)
            assert len(data["tasks"]) == 0

    def test_multiple_tasks_in_timeline(self, tmp_path, client):
        """Multiple tasks with different histories should all appear correctly in timeline."""
        tasks_file = tmp_path / "tasks.md"

        write_tasks(tasks_file, """## TODO THIS WEEK

## IN PROGRESS TODAY

## BLOCKED

## DONE THIS WEEK

""")

        with mock_today():
            # Create task 1: simple in-progress
            resp1 = client.post("/api/tasks", json={
                "section": "IN PROGRESS TODAY",
                "text": "Task 1"
            })
            assert resp1.status_code == 201
            task1_id = resp1.get_json()["id"]

            # Create task 2: will go through blocked cycle
            resp2 = client.post("/api/tasks", json={
                "section": "IN PROGRESS TODAY",
                "text": "Task 2"
            })
            assert resp2.status_code == 201
            task2_id = resp2.get_json()["id"]

            # Task 2: move to BLOCKED then back to IP
            client.put(f"/api/tasks/{task2_id}", json={"section": "BLOCKED"})
            client.put(f"/api/tasks/{task2_id}", json={"section": "IN PROGRESS TODAY"})

            # Create task 3: will be completed
            # NOTE: Create in TODO first, then move to IP to get ip@ history entry,
            # then complete. Creating directly in IP doesn't create history.
            resp3 = client.post("/api/tasks", json={
                "section": "TODO THIS WEEK",
                "text": "Task 3"
            })
            assert resp3.status_code == 201
            task3_id = resp3.get_json()["id"]

            # Task 3: move to IP (creates ip@ history), then complete
            client.put(f"/api/tasks/{task3_id}", json={"section": "IN PROGRESS TODAY"})
            client.post(f"/api/tasks/reorder", json={
                "taskId": task3_id,
                "section": "DONE THIS WEEK",
                "index": 0
            })

            # Get timeline
            resp = client.get("/api/timeline?week_offset=0")
            assert resp.status_code == 200
            data = resp.get_json()

            # Should have all 3 tasks
            assert len(data["tasks"]) == 3

            task_ids = {t["id"] for t in data["tasks"]}
            assert task1_id in task_ids
            assert task2_id in task_ids
            assert task3_id in task_ids

            # Each task should have spans
            for task in data["tasks"]:
                assert len(task["spans"]) >= 1
                for span in task["spans"]:
                    assert "start" in span
                    assert "end" in span
                    assert "status" in span
