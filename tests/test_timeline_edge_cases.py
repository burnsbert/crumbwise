"""Additional edge case tests for timeline span computation.

These tests cover edge cases that are harder to hit in the main endpoint tests,
focusing on boundary conditions and unusual history patterns.
"""

import json
from datetime import datetime, date, timedelta
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


# Fixed "today" for deterministic tests: 2026-02-17 (Tuesday)
# Week offset 0 => Sunday 2026-02-15 to Saturday 2026-02-21
FIXED_TODAY = datetime(2026, 2, 17, 12, 0, 0)


def mock_today():
    """Patch datetime.now() to return a fixed date for deterministic tests."""
    return patch("crumbwise.datetime", wraps=datetime,
                 **{"now.return_value": FIXED_TODAY})


class TestTimelineExactBoundaries:
    """Test tasks that start/end exactly on week boundaries."""

    def test_task_starts_exactly_on_sunday(self, tmp_path, client):
        """Task starting exactly on Sunday (week start) should not be clipped."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Sunday start <!-- id:task1 in_progress:2026-02-15T09:00:00 history:ip@2026-02-15T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        span = task["spans"][0]
        assert span["start"] == "2026-02-15"  # Sunday, not clipped
        assert span["end"] == "2026-02-17"    # Today

    def test_task_ends_exactly_on_saturday(self, tmp_path, client):
        """Task ending exactly on Saturday (week end) should not be clipped."""
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] Saturday end <!-- id:task1 in_progress:2026-02-15T09:00:00 completed_at:2026-02-21T17:00:00 history:ip@2026-02-15T09:00:00|co@2026-02-21T17:00:00 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        span = task["spans"][0]
        assert span["start"] == "2026-02-15"  # Sunday
        assert span["end"] == "2026-02-21"    # Saturday, not clipped

    def test_task_entire_week_sunday_to_saturday(self, tmp_path, client):
        """Task spanning exactly Sunday to Saturday should cover entire week."""
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] Entire week <!-- id:task1 in_progress:2026-02-15T00:00:00 completed_at:2026-02-21T23:59:59 history:ip@2026-02-15T00:00:00|co@2026-02-21T23:59:59 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        span = task["spans"][0]
        assert span["start"] == "2026-02-15"
        assert span["end"] == "2026-02-21"


class TestTimelineHistoryTerminalEvents:
    """Test edge cases with history entries that are terminal events (co@, op@)."""

    def test_history_ending_with_terminal_event(self, tmp_path, client):
        """Task history ending with co@ should produce no open span."""
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] Completed task <!-- id:task1 in_progress:2026-02-16T09:00:00 completed_at:2026-02-17T17:00:00 history:ip@2026-02-16T09:00:00|co@2026-02-17T17:00:00 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        # Should produce one span: ip@Mon to co@Tue
        # No open span extending to "today" since task is completed
        assert len(task["spans"]) == 1
        assert task["spans"][0]["start"] == "2026-02-16"
        assert task["spans"][0]["end"] == "2026-02-17"
        assert task["spans"][0]["status"] == "in_progress"

    def test_history_with_only_terminal_event_no_active_state(self, tmp_path, client):
        """Task history containing only op@ (no preceding ip@ or bl@) should produce no spans."""
        write_tasks(tmp_path / "tasks.md", """## TODO THIS WEEK

- [ ] Deactivated task <!-- id:task1 history:op@2026-02-16T09:00:00 -->

## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        # Task has no in_progress timestamp, should be excluded entirely
        assert len(data["tasks"]) == 0

    def test_history_consecutive_terminal_events(self, tmp_path, client):
        """Multiple consecutive terminal events should not create spans."""
        # Scenario: task went ip@Mon, co@Tue, then someone unchecked it (op@Tue)
        write_tasks(tmp_path / "tasks.md", """## TODO THIS WEEK

- [ ] Uncompleted after done <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@2026-02-16T09:00:00|co@2026-02-17T10:00:00|op@2026-02-17T11:00:00 -->

## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        # Should have one span: ip@Mon to co@Tue
        # The op@ after co@ is just another terminal event that doesn't create a span
        assert len(data["tasks"]) == 1
        task = data["tasks"][0]
        assert len(task["spans"]) == 1
        assert task["spans"][0]["start"] == "2026-02-16"
        assert task["spans"][0]["end"] == "2026-02-17"


class TestTimelineMultipleSpanTypes:
    """Test tasks with multiple spans of different types in a single week."""

    def test_ip_bl_ip_all_in_same_week(self, tmp_path, client):
        """Task with ip->blocked->ip cycle all within the displayed week."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Blocked and resumed <!-- id:task1 in_progress:2026-02-18T09:00:00 history:ip@2026-02-16T09:00:00|bl@2026-02-17T14:00:00|ip@2026-02-18T09:00:00 -->

## BLOCKED

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        # Should produce 3 spans:
        # 1. ip Mon-Tue (in_progress)
        # 2. bl Tue-Wed (blocked)
        # 3. ip Wed-today (in_progress, extends to today)
        assert len(task["spans"]) == 3

        assert task["spans"][0]["status"] == "in_progress"
        assert task["spans"][0]["start"] == "2026-02-16"
        assert task["spans"][0]["end"] == "2026-02-17"

        assert task["spans"][1]["status"] == "blocked"
        assert task["spans"][1]["start"] == "2026-02-17"
        assert task["spans"][1]["end"] == "2026-02-18"

        assert task["spans"][2]["status"] == "in_progress"
        assert task["spans"][2]["start"] == "2026-02-18"
        assert task["spans"][2]["end"] == "2026-02-17"  # Today (current in_progress)

    def test_blocked_task_currently_blocked_extends_to_today(self, tmp_path, client):
        """Blocked task (last history entry is bl@) should extend to today."""
        write_tasks(tmp_path / "tasks.md", """## BLOCKED

- [ ] Currently blocked <!-- id:task1 blocked_at:2026-02-17T10:00:00 history:ip@2026-02-16T09:00:00|bl@2026-02-17T10:00:00 -->

## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        # Two spans: ip Mon-Tue, bl Tue-today
        assert len(task["spans"]) == 2

        assert task["spans"][0]["status"] == "in_progress"
        assert task["spans"][0]["start"] == "2026-02-16"
        assert task["spans"][0]["end"] == "2026-02-17"

        assert task["spans"][1]["status"] == "blocked"
        assert task["spans"][1]["start"] == "2026-02-17"
        assert task["spans"][1]["end"] == "2026-02-17"  # Today


class TestTimelineBackfillEdgeCases:
    """Test backfill behavior for done-section tasks without completed_at."""

    def test_done_task_no_completed_at_same_day_span(self, tmp_path, client):
        """Done task without completed_at gets backfilled to in_progress date (same-day span)."""
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] Backfilled done <!-- id:task1 in_progress:2026-02-16T09:00:00 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        # Backfill logic: completed_at = in_progress date => single-day span
        assert len(task["spans"]) == 1
        span = task["spans"][0]
        assert span["start"] == "2026-02-16"
        assert span["end"] == "2026-02-16"  # Same day (backfilled)
        assert span["status"] == "in_progress"

    def test_done_task_no_completed_at_with_history(self, tmp_path, client):
        """Done task with history but no completed_at should still use history for spans."""
        # This is a weird edge case: task has history (so it's tracking properly)
        # but doesn't have completed_at set. Should use history span computation,
        # not backfill logic.
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] History no completed_at <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@2026-02-16T09:00:00 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        # Has history, so compute_spans_from_history is used
        # Last entry is ip@, so span extends to "today"
        assert len(task["spans"]) == 1
        span = task["spans"][0]
        assert span["start"] == "2026-02-16"
        assert span["end"] == "2026-02-17"  # Today (from history logic)
        assert span["status"] == "in_progress"


class TestTimelineWeekOffsetEdgeCases:
    """Test edge cases with different week offsets."""

    def test_task_visible_in_multiple_weeks(self, tmp_path, client):
        """Task spanning multiple weeks should appear in each week view it touches."""
        # Task from Feb 10 (prev week) to Feb 20 (this week Thu)
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] Multi-week task <!-- id:task1 in_progress:2026-02-10T09:00:00 completed_at:2026-02-20T17:00:00 history:ip@2026-02-10T09:00:00|co@2026-02-20T17:00:00 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            # Last week view (Feb 8-14)
            resp_last = client.get("/api/timeline?week_offset=-1")
            data_last = resp_last.get_json()
            assert len(data_last["tasks"]) == 1
            # Span clipped to last week: Feb 10 (Tue) to Feb 14 (Sat)
            span_last = data_last["tasks"][0]["spans"][0]
            assert span_last["start"] == "2026-02-10"
            assert span_last["end"] == "2026-02-14"

            # This week view (Feb 15-21)
            resp_this = client.get("/api/timeline?week_offset=0")
            data_this = resp_this.get_json()
            assert len(data_this["tasks"]) == 1
            # Span clipped to this week: Feb 15 (Sun) to Feb 20 (Thu)
            span_this = data_this["tasks"][0]["spans"][0]
            assert span_this["start"] == "2026-02-15"
            assert span_this["end"] == "2026-02-20"

    def test_task_only_in_current_week(self, tmp_path, client):
        """Task entirely within current week should NOT appear in adjacent weeks."""
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] Current week only <!-- id:task1 in_progress:2026-02-16T09:00:00 completed_at:2026-02-19T17:00:00 history:ip@2026-02-16T09:00:00|co@2026-02-19T17:00:00 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            # Last week: should be excluded
            resp_last = client.get("/api/timeline?week_offset=-1")
            data_last = resp_last.get_json()
            assert len(data_last["tasks"]) == 0

            # This week: should appear
            resp_this = client.get("/api/timeline?week_offset=0")
            data_this = resp_this.get_json()
            assert len(data_this["tasks"]) == 1

            # Next week: should be excluded
            resp_next = client.get("/api/timeline?week_offset=1")
            data_next = resp_next.get_json()
            assert len(data_next["tasks"]) == 0


class TestTimelineMalformedHistory:
    """Test handling of malformed or unusual history strings."""

    def test_history_with_missing_timestamp(self, tmp_path, client):
        """History entry without timestamp should be skipped."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Malformed history <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@|ip@2026-02-17T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        # First entry (ip@ with no timestamp) should be skipped
        # Second entry should create a span
        task = data["tasks"][0]
        assert len(task["spans"]) == 1
        assert task["spans"][0]["start"] == "2026-02-17"

    def test_history_with_invalid_timestamp_format(self, tmp_path, client):
        """History entry with invalid ISO timestamp should be skipped."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Invalid timestamp <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@not-a-date|ip@2026-02-17T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        # First entry (invalid timestamp) should be skipped
        task = data["tasks"][0]
        assert len(task["spans"]) == 1
        assert task["spans"][0]["start"] == "2026-02-17"

    def test_history_with_no_at_symbol(self, tmp_path, client):
        """History entry without '@' separator should be skipped."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Bad entry <!-- id:task1 in_progress:2026-02-16T09:00:00 history:malformed|ip@2026-02-17T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        assert len(task["spans"]) == 1
        assert task["spans"][0]["start"] == "2026-02-17"
