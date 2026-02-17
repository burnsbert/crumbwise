"""Tests for GET /api/timeline endpoint with span computation.

Tests the timeline API endpoint that computes weekly task spans from
history entries and timestamp metadata. TDD: tests written first,
then implementation.
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


# Use a fixed "today" for deterministic tests: 2026-02-17 (Tuesday)
# Week offset 0 => Sunday 2026-02-15 to Saturday 2026-02-21
FIXED_TODAY = datetime(2026, 2, 17, 12, 0, 0)
FIXED_TODAY_DATE = date(2026, 2, 17)


def mock_today():
    """Patch datetime.now() to return a fixed date for deterministic tests."""
    return patch("crumbwise.datetime", wraps=datetime,
                 **{"now.return_value": FIXED_TODAY})


class TestTimelineEndpointBasic:
    """Basic endpoint behavior tests."""

    def test_endpoint_exists(self, tmp_path, client):
        """GET /api/timeline should return 200."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

## DONE THIS WEEK

## BLOCKED

""")
        with mock_today():
            resp = client.get("/api/timeline")
        assert resp.status_code == 200

    def test_returns_week_boundaries(self, tmp_path, client):
        """Response should include week_start, week_end, and today."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

## DONE THIS WEEK

## BLOCKED

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert data["week_start"] == "2026-02-15"  # Sunday
        assert data["week_end"] == "2026-02-21"    # Saturday
        assert data["today"] == "2026-02-17"       # Tuesday

    def test_week_offset_default_zero(self, tmp_path, client):
        """Default week_offset should be 0 (current week)."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert data["week_start"] == "2026-02-15"

    def test_week_offset_minus_one(self, tmp_path, client):
        """week_offset=-1 should return previous week."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline?week_offset=-1")
        data = resp.get_json()
        # Previous week: Sun Feb 8 - Sat Feb 14
        assert data["week_start"] == "2026-02-08"
        assert data["week_end"] == "2026-02-14"

    def test_week_offset_plus_one(self, tmp_path, client):
        """week_offset=1 should return next week."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline?week_offset=1")
        data = resp.get_json()
        # Next week: Sun Feb 22 - Sat Feb 28
        assert data["week_start"] == "2026-02-22"
        assert data["week_end"] == "2026-02-28"

    def test_empty_tasks_returns_empty_list(self, tmp_path, client):
        """No qualifying tasks should return empty tasks list."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

## DONE THIS WEEK

## BLOCKED

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert data["tasks"] == []


class TestTimelineTaskFiltering:
    """Tests for which tasks are included/excluded."""

    def test_excludes_tasks_without_in_progress(self, tmp_path, client):
        """Tasks without in_progress timestamp should be excluded."""
        write_tasks(tmp_path / "tasks.md", """## TODO THIS WEEK

- [ ] No timestamp task <!-- id:task1 -->

## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 0

    def test_excludes_research_section_tasks(self, tmp_path, client):
        """Tasks in RESEARCH_SECTIONS should be excluded."""
        write_tasks(tmp_path / "tasks.md", """## RESEARCH IN PROGRESS

- [ ] Research task <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@2026-02-16T09:00:00 -->

## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 0

    def test_includes_ip_task_with_in_progress(self, tmp_path, client):
        """In-progress task with timestamp should be included."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Active task <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@2026-02-16T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["id"] == "task1"

    def test_includes_done_task_with_in_progress(self, tmp_path, client):
        """Done task with in_progress should appear on timeline."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

## DONE THIS WEEK

- [x] Completed task <!-- id:task1 in_progress:2026-02-16T09:00:00 completed_at:2026-02-17T10:00:00 history:ip@2026-02-16T09:00:00|co@2026-02-17T10:00:00 -->

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 1

    def test_includes_blocked_task(self, tmp_path, client):
        """Blocked task with in_progress in its history should appear."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

## BLOCKED

- [ ] Blocked task <!-- id:task1 blocked_at:2026-02-17T14:00:00 history:ip@2026-02-16T09:00:00|bl@2026-02-17T14:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 1

    def test_excludes_task_entirely_outside_week(self, tmp_path, client):
        """Task whose entire span is before the displayed week should be excluded."""
        # Task completed Feb 10 (previous week), current week is Feb 15-21
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

## DONE THIS WEEK

- [x] Old task <!-- id:task1 in_progress:2026-02-09T09:00:00 completed_at:2026-02-10T16:00:00 history:ip@2026-02-09T09:00:00|co@2026-02-10T16:00:00 -->

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 0

    def test_excludes_task_entirely_in_future_week(self, tmp_path, client):
        """Task starting next week should not appear in current week view."""
        # Looking at last week (offset=-1), task started this week
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Future task <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@2026-02-16T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline?week_offset=-1")
        data = resp.get_json()
        assert len(data["tasks"]) == 0


class TestTimelineSpanComputation:
    """Tests for span computation from history entries."""

    def test_simple_in_progress_task_spans_to_today(self, tmp_path, client):
        """IP task started Mon, still open => span Mon to today (Tue)."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Active task <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@2026-02-16T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        assert len(task["spans"]) == 1
        span = task["spans"][0]
        assert span["start"] == "2026-02-16"  # Monday
        assert span["end"] == "2026-02-17"    # Today (Tuesday)
        assert span["status"] == "in_progress"

    def test_completed_task_spans_ip_to_completed(self, tmp_path, client):
        """Task IP Mon, completed Tue => single span Mon-Tue."""
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] Done task <!-- id:task1 in_progress:2026-02-16T09:00:00 completed_at:2026-02-17T10:00:00 history:ip@2026-02-16T09:00:00|co@2026-02-17T10:00:00 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        assert len(task["spans"]) == 1
        span = task["spans"][0]
        assert span["start"] == "2026-02-16"
        assert span["end"] == "2026-02-17"
        assert span["status"] == "in_progress"

    def test_ip_blocked_ip_done_history(self, tmp_path, client):
        """Complex lifecycle: IP->BLOCKED->IP->DONE produces multiple spans."""
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] Complex task <!-- id:task1 completed_at:2026-02-20T17:00:00 history:ip@2026-02-15T09:00:00|bl@2026-02-16T14:00:00|ip@2026-02-18T09:00:00|co@2026-02-20T17:00:00 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        # Should produce 3 visible spans:
        # 1. ip@Sun -> bl@Mon: in_progress
        # 2. bl@Mon -> ip@Wed: blocked
        # 3. ip@Wed -> co@Fri: in_progress
        assert len(task["spans"]) == 3

        assert task["spans"][0]["start"] == "2026-02-15"
        assert task["spans"][0]["end"] == "2026-02-16"
        assert task["spans"][0]["status"] == "in_progress"

        assert task["spans"][1]["start"] == "2026-02-16"
        assert task["spans"][1]["end"] == "2026-02-18"
        assert task["spans"][1]["status"] == "blocked"

        assert task["spans"][2]["start"] == "2026-02-18"
        assert task["spans"][2]["end"] == "2026-02-20"
        assert task["spans"][2]["status"] == "in_progress"

    def test_blocked_task_span_extends_to_today(self, tmp_path, client):
        """Currently blocked task => blocked span extends to today."""
        write_tasks(tmp_path / "tasks.md", """## BLOCKED

- [ ] Blocked task <!-- id:task1 blocked_at:2026-02-16T14:00:00 history:ip@2026-02-15T09:00:00|bl@2026-02-16T14:00:00 -->

## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        assert len(task["spans"]) == 2

        # First span: in_progress from Sun to Mon
        assert task["spans"][0]["start"] == "2026-02-15"
        assert task["spans"][0]["end"] == "2026-02-16"
        assert task["spans"][0]["status"] == "in_progress"

        # Second span: blocked from Mon to today
        assert task["spans"][1]["start"] == "2026-02-16"
        assert task["spans"][1]["end"] == "2026-02-17"
        assert task["spans"][1]["status"] == "blocked"

    def test_same_day_task(self, tmp_path, client):
        """Task started and completed same day => single span with start == end."""
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] Quick task <!-- id:task1 in_progress:2026-02-17T09:00:00 completed_at:2026-02-17T17:00:00 history:ip@2026-02-17T09:00:00|co@2026-02-17T17:00:00 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        assert len(task["spans"]) == 1
        span = task["spans"][0]
        assert span["start"] == "2026-02-17"
        assert span["end"] == "2026-02-17"
        assert span["status"] == "in_progress"

    def test_task_started_before_week_clipped_to_sunday(self, tmp_path, client):
        """Task started before displayed week => span starts at Sunday."""
        # Task started Feb 10 (prev week), still in progress
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Long running task <!-- id:task1 in_progress:2026-02-10T09:00:00 history:ip@2026-02-10T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        assert len(task["spans"]) == 1
        span = task["spans"][0]
        assert span["start"] == "2026-02-15"  # Clipped to Sunday
        assert span["end"] == "2026-02-17"    # Today
        assert span["status"] == "in_progress"

    def test_open_task_clipped_to_today_not_saturday(self, tmp_path, client):
        """Open task should extend to today, NOT to end of week."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Active task <!-- id:task1 in_progress:2026-02-15T09:00:00 history:ip@2026-02-15T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        span = task["spans"][0]
        assert span["end"] == "2026-02-17"  # Today (Tue), not Saturday

    def test_op_entry_ends_previous_span(self, tmp_path, client):
        """op@ (opened/backlog) should end the previous span without starting a new one."""
        # Task went IP Sun -> backlog Mon -> IP Mon afternoon, still open
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Reopened task <!-- id:task1 in_progress:2026-02-16T14:00:00 history:ip@2026-02-15T09:00:00|op@2026-02-16T10:00:00|ip@2026-02-16T14:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        # Two visible spans: ip Sun-Mon, then ip Mon-today(Tue)
        # The op@ on Monday morning ended the first span but created no visible span
        assert len(task["spans"]) == 2
        assert task["spans"][0]["status"] == "in_progress"
        assert task["spans"][0]["start"] == "2026-02-15"
        assert task["spans"][0]["end"] == "2026-02-16"

        assert task["spans"][1]["status"] == "in_progress"
        assert task["spans"][1]["start"] == "2026-02-16"
        assert task["spans"][1]["end"] == "2026-02-17"  # Today (Tue)

    def test_op_entry_task_all_spans_outside_week(self, tmp_path, client):
        """Task that was opened (op@) before current week and re-IPed after should work."""
        # ip@Feb 8, op@Feb 10, ip@Feb 16 -- looking at current week
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Reopened task <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@2026-02-08T09:00:00|op@2026-02-10T17:00:00|ip@2026-02-16T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        # First span (Feb 8-10) is entirely outside current week, should be excluded
        # Second span (Feb 16-today) is within current week
        assert len(task["spans"]) == 1
        assert task["spans"][0]["start"] == "2026-02-16"
        assert task["spans"][0]["end"] == "2026-02-17"
        assert task["spans"][0]["status"] == "in_progress"


class TestTimelinePreExistingTasks:
    """Tests for tasks with timestamps but no history (pre-existing per decision #1)."""

    def test_pre_existing_ip_task_no_history(self, tmp_path, client):
        """Task with in_progress but no history => simplified single span."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Old task <!-- id:task1 in_progress:2026-02-16T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 1
        task = data["tasks"][0]
        assert len(task["spans"]) == 1
        span = task["spans"][0]
        assert span["start"] == "2026-02-16"
        assert span["end"] == "2026-02-17"  # Today
        assert span["status"] == "in_progress"

    def test_pre_existing_completed_task_no_history(self, tmp_path, client):
        """Task with in_progress + completed_at but no history => single span."""
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] Old done task <!-- id:task1 in_progress:2026-02-16T09:00:00 completed_at:2026-02-17T10:00:00 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 1
        task = data["tasks"][0]
        assert len(task["spans"]) == 1
        span = task["spans"][0]
        assert span["start"] == "2026-02-16"
        assert span["end"] == "2026-02-17"
        assert span["status"] == "in_progress"

    def test_pre_existing_blocked_task_no_history(self, tmp_path, client):
        """Task with in_progress + blocked_at but no history => single span to blocked_at."""
        write_tasks(tmp_path / "tasks.md", """## BLOCKED

- [ ] Blocked old task <!-- id:task1 in_progress:2026-02-15T09:00:00 blocked_at:2026-02-17T14:00:00 -->

## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 1
        task = data["tasks"][0]
        assert len(task["spans"]) == 1
        span = task["spans"][0]
        assert span["start"] == "2026-02-15"
        assert span["end"] == "2026-02-17"
        assert span["status"] == "in_progress"


class TestTimelineBackfill:
    """Tests for done-section tasks without completed_at (backfill per decision #2)."""

    def test_done_task_without_completed_at_uses_in_progress(self, tmp_path, client):
        """Done task with in_progress but no completed_at => backfill completed_at to in_progress date."""
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] Old done task <!-- id:task1 in_progress:2026-02-17T09:00:00 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 1
        task = data["tasks"][0]
        # Backfill: completed_at = in_progress date => same-day span
        assert len(task["spans"]) == 1
        span = task["spans"][0]
        assert span["start"] == "2026-02-17"
        assert span["end"] == "2026-02-17"

    def test_quarterly_done_task_without_completed_at(self, tmp_path, client):
        """Task in quarterly done section without completed_at => backfill."""
        write_tasks(tmp_path / "tasks.md", """## DONE Q1 2026

- [x] Quarterly task <!-- id:task1 in_progress:2026-02-16T09:00:00 -->

## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 1
        task = data["tasks"][0]
        assert len(task["spans"]) == 1
        span = task["spans"][0]
        assert span["start"] == "2026-02-16"
        assert span["end"] == "2026-02-16"  # Backfilled to in_progress date


class TestTimelineWeekClipping:
    """Tests for span clipping to week boundaries."""

    def test_span_starting_before_week_clipped_to_sunday(self, tmp_path, client):
        """Span starting before displayed week should be clipped to Sunday."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Long task <!-- id:task1 in_progress:2026-02-10T09:00:00 history:ip@2026-02-10T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        assert task["spans"][0]["start"] == "2026-02-15"  # Clipped to Sunday

    def test_span_ending_after_week_clipped_to_saturday(self, tmp_path, client):
        """Looking at past week, a completed span ending this week should clip to Saturday."""
        # Task started Feb 10, completed Feb 17 (this week Tue)
        # Looking at last week (Feb 8-14): span should clip to Feb 14 (Saturday)
        write_tasks(tmp_path / "tasks.md", """## DONE THIS WEEK

- [x] Cross-week task <!-- id:task1 in_progress:2026-02-10T09:00:00 completed_at:2026-02-17T10:00:00 history:ip@2026-02-10T09:00:00|co@2026-02-17T10:00:00 -->

## IN PROGRESS TODAY

""")
        with mock_today():
            resp = client.get("/api/timeline?week_offset=-1")
        data = resp.get_json()
        task = data["tasks"][0]
        assert task["spans"][0]["start"] == "2026-02-10"
        assert task["spans"][0]["end"] == "2026-02-14"  # Clipped to Saturday


class TestTimelineResponseFormat:
    """Tests for response JSON format and fields."""

    def test_task_includes_required_fields(self, tmp_path, client):
        """Each task in response should have id, text, section, spans."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Test task <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@2026-02-16T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        assert "id" in task
        assert "text" in task
        assert "section" in task
        assert "spans" in task
        assert task["text"] == "Test task"
        assert task["section"] == "IN PROGRESS TODAY"

    def test_task_includes_project_info(self, tmp_path, client):
        """Tasks should include assigned_project and project_color."""
        write_tasks(tmp_path / "tasks.md", """## PROJECTS

- [ ] Test project <!-- id:proj1 project:3 -->

## IN PROGRESS TODAY

- [ ] Task with project <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@2026-02-16T09:00:00 assigned:proj1 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        assert task["assigned_project"] == "proj1"
        assert task["project_color"] == 3

    def test_task_without_project(self, tmp_path, client):
        """Tasks without project should have null project fields."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] No project task <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@2026-02-16T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        task = data["tasks"][0]
        assert task["assigned_project"] is None
        assert task["project_color"] is None

    def test_span_has_start_end_status(self, tmp_path, client):
        """Each span should have start, end, and status fields."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Test task <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@2026-02-16T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        span = data["tasks"][0]["spans"][0]
        assert "start" in span
        assert "end" in span
        assert "status" in span


class TestTimelineMultipleTasks:
    """Tests with multiple tasks in various states."""

    def test_multiple_tasks_all_included(self, tmp_path, client):
        """Multiple qualifying tasks should all appear."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Task A <!-- id:taskA in_progress:2026-02-15T09:00:00 history:ip@2026-02-15T09:00:00 -->
- [ ] Task B <!-- id:taskB in_progress:2026-02-16T09:00:00 history:ip@2026-02-16T09:00:00 -->

## DONE THIS WEEK

- [x] Task C <!-- id:taskC in_progress:2026-02-15T09:00:00 completed_at:2026-02-17T10:00:00 history:ip@2026-02-15T09:00:00|co@2026-02-17T10:00:00 -->

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 3

    def test_mixed_tasks_filtered_correctly(self, tmp_path, client):
        """Mix of qualifying and non-qualifying tasks should filter correctly."""
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

- [ ] Qualifying task <!-- id:task1 in_progress:2026-02-16T09:00:00 history:ip@2026-02-16T09:00:00 -->

## TODO THIS WEEK

- [ ] No timestamp <!-- id:task2 -->

## RESEARCH IN PROGRESS

- [ ] Research task <!-- id:task3 in_progress:2026-02-16T09:00:00 -->

## DONE THIS WEEK

""")
        with mock_today():
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["id"] == "task1"


class TestTimelineWeekBoundarySunday:
    """Verify Sunday-Saturday week boundaries specifically."""

    def test_today_is_sunday_week_start(self, tmp_path, client):
        """When today is Sunday, week_start should be today."""
        sunday = datetime(2026, 2, 15, 12, 0, 0)  # Sunday
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with patch("crumbwise.datetime", wraps=datetime,
                   **{"now.return_value": sunday}):
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert data["week_start"] == "2026-02-15"
        assert data["week_end"] == "2026-02-21"

    def test_today_is_saturday_week_end(self, tmp_path, client):
        """When today is Saturday, week_end should be today."""
        saturday = datetime(2026, 2, 21, 12, 0, 0)  # Saturday
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with patch("crumbwise.datetime", wraps=datetime,
                   **{"now.return_value": saturday}):
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert data["week_start"] == "2026-02-15"
        assert data["week_end"] == "2026-02-21"

    def test_today_is_monday(self, tmp_path, client):
        """When today is Monday, week_start should be the previous day (Sunday)."""
        monday = datetime(2026, 2, 16, 12, 0, 0)  # Monday
        write_tasks(tmp_path / "tasks.md", """## IN PROGRESS TODAY

## DONE THIS WEEK

""")
        with patch("crumbwise.datetime", wraps=datetime,
                   **{"now.return_value": monday}):
            resp = client.get("/api/timeline")
        data = resp.get_json()
        assert data["week_start"] == "2026-02-15"  # Sunday
        assert data["week_end"] == "2026-02-21"    # Saturday
