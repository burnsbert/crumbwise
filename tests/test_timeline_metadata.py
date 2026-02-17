"""Tests for timeline metadata (blocked_at, history) parsing and saving.

Tests for the new blocked_at and history fields used by the timeline feature.
Verifies that metadata is correctly parsed from markdown and preserved on save.
"""

import pytest
import crumbwise


@pytest.fixture
def app(tmp_path):
    """Create a test app with a temporary tasks file."""
    tasks_file = tmp_path / "tasks.md"
    undo_file = tmp_path / "tasks.md.undo"
    settings_file = tmp_path / "settings.json"
    notes_file = tmp_path / "notes.txt"

    # Point the app at temporary files
    crumbwise.TASKS_FILE = tasks_file
    crumbwise.UNDO_FILE = undo_file
    crumbwise.SETTINGS_FILE = settings_file
    crumbwise.NOTES_FILE = notes_file

    crumbwise.app.config["TESTING"] = True
    yield crumbwise.app

    # No cleanup needed -- tmp_path is auto-cleaned


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


def write_tasks(tasks_file, content):
    """Helper to write task markdown content."""
    tasks_file.write_text(content)


class TestSectionConstants:
    """Test that the new section constants are defined."""

    def test_blocked_sections_exists(self):
        """BLOCKED_SECTIONS constant should be defined."""
        assert hasattr(crumbwise, 'BLOCKED_SECTIONS')
        assert isinstance(crumbwise.BLOCKED_SECTIONS, list)

    def test_blocked_sections_contains_blocked(self):
        """BLOCKED_SECTIONS should contain "BLOCKED"."""
        assert "BLOCKED" in crumbwise.BLOCKED_SECTIONS

    def test_done_sections_exists(self):
        """DONE_SECTIONS constant should be defined."""
        assert hasattr(crumbwise, 'DONE_SECTIONS')
        assert isinstance(crumbwise.DONE_SECTIONS, list)

    def test_done_sections_contains_done_this_week(self):
        """DONE_SECTIONS should contain "DONE THIS WEEK"."""
        assert "DONE THIS WEEK" in crumbwise.DONE_SECTIONS

    def test_research_sections_exists(self):
        """RESEARCH_SECTIONS constant should be defined."""
        assert hasattr(crumbwise, 'RESEARCH_SECTIONS')
        assert isinstance(crumbwise.RESEARCH_SECTIONS, list)

    def test_research_sections_contains_expected(self):
        """RESEARCH_SECTIONS should contain all research tab sections."""
        expected = ["PROBLEMS TO SOLVE", "THINGS TO RESEARCH", "RESEARCH IN PROGRESS", "RESEARCH DONE"]
        for section in expected:
            assert section in crumbwise.RESEARCH_SECTIONS, f"{section} missing from RESEARCH_SECTIONS"


class TestMetadataParsing:
    """Test that blocked_at and history are correctly parsed from markdown."""

    def test_parse_task_with_blocked_at(self, tmp_path):
        """Parsing a task with blocked_at metadata should extract it."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## IN PROGRESS TODAY

- [ ] Task with blocked_at <!-- id:task1 blocked_at:2026-02-14T10:00:00 -->

## BLOCKED

""")
        crumbwise.TASKS_FILE = tasks_file

        sections = crumbwise.parse_tasks()
        task = sections["IN PROGRESS TODAY"][0]

        assert task["id"] == "task1"
        assert task["blocked_at"] == "2026-02-14T10:00:00"

    def test_parse_task_with_history(self, tmp_path):
        """Parsing a task with history metadata should extract it."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## IN PROGRESS TODAY

- [ ] Task with history <!-- id:task1 history:ip@2026-02-10T09:00:00|bl@2026-02-12T14:00:00 -->

""")
        crumbwise.TASKS_FILE = tasks_file

        sections = crumbwise.parse_tasks()
        task = sections["IN PROGRESS TODAY"][0]

        assert task["id"] == "task1"
        assert task["history"] == "ip@2026-02-10T09:00:00|bl@2026-02-12T14:00:00"

    def test_parse_task_with_both_metadata(self, tmp_path):
        """Task can have both blocked_at and history."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## BLOCKED

- [ ] Complex task <!-- id:task1 in_progress:2026-02-10T09:00:00 blocked_at:2026-02-12T14:00:00 history:ip@2026-02-10T09:00:00|bl@2026-02-12T14:00:00 -->

""")
        crumbwise.TASKS_FILE = tasks_file

        sections = crumbwise.parse_tasks()
        task = sections["BLOCKED"][0]

        assert task["in_progress"] == "2026-02-10T09:00:00"
        assert task["blocked_at"] == "2026-02-12T14:00:00"
        assert task["history"] == "ip@2026-02-10T09:00:00|bl@2026-02-12T14:00:00"

    def test_parse_task_without_blocked_at(self, tmp_path):
        """Task without blocked_at should have None for blocked_at."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## IN PROGRESS TODAY

- [ ] Normal task <!-- id:task1 -->

""")
        crumbwise.TASKS_FILE = tasks_file

        sections = crumbwise.parse_tasks()
        task = sections["IN PROGRESS TODAY"][0]

        assert task.get("blocked_at") is None

    def test_parse_task_without_history(self, tmp_path):
        """Task without history should have None for history."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## IN PROGRESS TODAY

- [ ] Normal task <!-- id:task1 -->

""")
        crumbwise.TASKS_FILE = tasks_file

        sections = crumbwise.parse_tasks()
        task = sections["IN PROGRESS TODAY"][0]

        assert task.get("history") is None


class TestMetadataSerialization:
    """Test that blocked_at and history are correctly written to markdown."""

    def test_save_task_with_blocked_at(self, tmp_path):
        """Saving a task with blocked_at should preserve it in the markdown."""
        tasks_file = tmp_path / "tasks.md"
        crumbwise.TASKS_FILE = tasks_file

        # Create minimal sections to write
        sections = {
            "IN PROGRESS TODAY": [],
            "BLOCKED": [
                {
                    "id": "task1",
                    "text": "Blocked task",
                    "completed": False,
                    "created": "2026-02-10T09:00:00",
                    "updated": "2026-02-12T14:00:00",
                    "in_progress": "2026-02-10T09:00:00",
                    "completed_at": None,
                    "order_index": None,
                    "blocked_at": "2026-02-12T14:00:00",
                    "history": None,
                }
            ],
            "DONE THIS WEEK": [],
        }

        # Add other required sections
        for section_name in crumbwise.SECTIONS.keys():
            if section_name not in sections:
                sections[section_name] = []

        crumbwise.save_tasks(sections)

        # Read back and verify metadata is preserved
        content = tasks_file.read_text()
        assert "blocked_at:2026-02-12T14:00:00" in content
        assert "<!-- id:task1" in content

    def test_save_task_with_history(self, tmp_path):
        """Saving a task with history should preserve it in the markdown."""
        tasks_file = tmp_path / "tasks.md"
        crumbwise.TASKS_FILE = tasks_file

        sections = {
            "IN PROGRESS TODAY": [
                {
                    "id": "task1",
                    "text": "Task with history",
                    "completed": False,
                    "created": "2026-02-10T09:00:00",
                    "updated": "2026-02-12T14:00:00",
                    "in_progress": "2026-02-10T09:00:00",
                    "completed_at": None,
                    "order_index": None,
                    "blocked_at": None,
                    "history": "ip@2026-02-10T09:00:00|bl@2026-02-12T14:00:00|ip@2026-02-13T08:00:00",
                }
            ],
            "BLOCKED": [],
            "DONE THIS WEEK": [],
        }

        # Add other required sections
        for section_name in crumbwise.SECTIONS.keys():
            if section_name not in sections:
                sections[section_name] = []

        crumbwise.save_tasks(sections)

        # Read back and verify metadata is preserved
        content = tasks_file.read_text()
        assert "history:ip@2026-02-10T09:00:00|bl@2026-02-12T14:00:00|ip@2026-02-13T08:00:00" in content

    def test_save_and_parse_roundtrip(self, tmp_path):
        """Save and re-parse should preserve metadata."""
        tasks_file = tmp_path / "tasks.md"
        crumbwise.TASKS_FILE = tasks_file

        original_task = {
            "id": "task1",
            "text": "Task with metadata",
            "completed": False,
            "created": "2026-02-10T09:00:00",
            "updated": "2026-02-12T14:00:00",
            "in_progress": "2026-02-10T09:00:00",
            "completed_at": None,
            "order_index": None,
            "blocked_at": "2026-02-12T14:00:00",
            "history": "ip@2026-02-10T09:00:00|bl@2026-02-12T14:00:00",
        }

        sections = {
            "IN PROGRESS TODAY": [],
            "BLOCKED": [original_task.copy()],
            "DONE THIS WEEK": [],
        }

        # Add other required sections
        for section_name in crumbwise.SECTIONS.keys():
            if section_name not in sections:
                sections[section_name] = []

        # Save
        crumbwise.save_tasks(sections)

        # Parse again
        parsed_sections = crumbwise.parse_tasks()
        parsed_task = parsed_sections["BLOCKED"][0]

        # Verify all metadata is preserved
        assert parsed_task["blocked_at"] == "2026-02-12T14:00:00"
        assert parsed_task["history"] == "ip@2026-02-10T09:00:00|bl@2026-02-12T14:00:00"
        assert parsed_task["in_progress"] == "2026-02-10T09:00:00"

    def test_save_task_without_blocked_at(self, tmp_path):
        """Saving a task without blocked_at should not include it in metadata."""
        tasks_file = tmp_path / "tasks.md"
        crumbwise.TASKS_FILE = tasks_file

        sections = {
            "IN PROGRESS TODAY": [
                {
                    "id": "task1",
                    "text": "Normal task",
                    "completed": False,
                    "created": "2026-02-10T09:00:00",
                    "updated": "2026-02-10T09:00:00",
                    "in_progress": "2026-02-10T09:00:00",
                    "completed_at": None,
                    "order_index": None,
                    "blocked_at": None,
                    "history": None,
                }
            ],
            "BLOCKED": [],
            "DONE THIS WEEK": [],
        }

        # Add other required sections
        for section_name in crumbwise.SECTIONS.keys():
            if section_name not in sections:
                sections[section_name] = []

        crumbwise.save_tasks(sections)

        # Read back - blocked_at should not be in the metadata
        content = tasks_file.read_text()
        lines = content.split("\n")
        task_line = [l for l in lines if "Normal task" in l][0]

        assert "blocked_at:" not in task_line
        assert "history:" not in task_line

    def test_save_task_without_history(self, tmp_path):
        """Saving a task without history should not include it in metadata."""
        tasks_file = tmp_path / "tasks.md"
        crumbwise.TASKS_FILE = tasks_file

        sections = {
            "IN PROGRESS TODAY": [
                {
                    "id": "task1",
                    "text": "Normal task",
                    "completed": False,
                    "created": "2026-02-10T09:00:00",
                    "updated": "2026-02-10T09:00:00",
                    "in_progress": "2026-02-10T09:00:00",
                    "completed_at": None,
                    "order_index": None,
                    "blocked_at": None,
                    "history": None,
                }
            ],
            "BLOCKED": [],
            "DONE THIS WEEK": [],
        }

        # Add other required sections
        for section_name in crumbwise.SECTIONS.keys():
            if section_name not in sections:
                sections[section_name] = []

        crumbwise.save_tasks(sections)

        # Read back - history should not be in the metadata
        content = tasks_file.read_text()
        lines = content.split("\n")
        task_line = [l for l in lines if "Normal task" in l][0]

        assert "history:" not in task_line


class TestIsDoneSection:
    """Test the is_done_section() helper function."""

    def test_done_this_week_is_done_section(self):
        """'DONE THIS WEEK' should be recognized as a done section."""
        assert crumbwise.is_done_section("DONE THIS WEEK") is True

    def test_done_q1_2026_is_done_section(self):
        """'DONE Q1 2026' (quarterly) should be recognized as a done section."""
        assert crumbwise.is_done_section("DONE Q1 2026") is True

    def test_done_q4_2025_is_done_section(self):
        """'DONE Q4 2025' should be recognized as a done section."""
        assert crumbwise.is_done_section("DONE Q4 2025") is True

    def test_done_2025_is_done_section(self):
        """'DONE 2025' (yearly) should be recognized as a done section."""
        assert crumbwise.is_done_section("DONE 2025") is True

    def test_done_2026_is_done_section(self):
        """'DONE 2026' should be recognized as a done section."""
        assert crumbwise.is_done_section("DONE 2026") is True

    def test_research_done_is_not_done_section(self):
        """'RESEARCH DONE' should NOT be recognized as a done section."""
        assert crumbwise.is_done_section("RESEARCH DONE") is False

    def test_in_progress_today_is_not_done_section(self):
        """'IN PROGRESS TODAY' should NOT be recognized as a done section."""
        assert crumbwise.is_done_section("IN PROGRESS TODAY") is False

    def test_todo_this_week_is_not_done_section(self):
        """'TODO THIS WEEK' should NOT be recognized as a done section."""
        assert crumbwise.is_done_section("TODO THIS WEEK") is False

    def test_blocked_is_not_done_section(self):
        """'BLOCKED' should NOT be recognized as a done section."""
        assert crumbwise.is_done_section("BLOCKED") is False

    def test_arbitrary_section_is_not_done_section(self):
        """Arbitrary section names should NOT be recognized as done sections."""
        assert crumbwise.is_done_section("SOME RANDOM SECTION") is False

    def test_empty_string_is_not_done_section(self):
        """Empty string should NOT be recognized as a done section."""
        assert crumbwise.is_done_section("") is False

    def test_done_prefix_case_sensitive(self):
        """'Done Q1 2026' (lowercase) should NOT match (case-sensitive)."""
        assert crumbwise.is_done_section("Done Q1 2026") is False

    def test_done_prefix_exact_match_required(self):
        """'UNDONE Q1 2026' should NOT match (must start with DONE, not contain it)."""
        assert crumbwise.is_done_section("UNDONE Q1 2026") is False


class TestHandleSectionTransition:
    """Test the handle_section_transition() helper function."""

    def test_move_to_in_progress_sets_in_progress_timestamp(self):
        """Moving to IN PROGRESS TODAY should set in_progress timestamp."""
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": None,
            "blocked_at": None,
            "completed_at": None,
            "history": None,
        }

        crumbwise.handle_section_transition(task, "TODO THIS WEEK", "IN PROGRESS TODAY")

        assert task["in_progress"] is not None
        assert task["blocked_at"] is None
        assert task["history"] is not None
        assert "ip@" in task["history"]

    def test_move_to_in_progress_preserves_existing_timestamp(self):
        """Moving to IN PROGRESS TODAY when already in_progress should preserve timestamp."""
        original_timestamp = "2026-02-10T09:00:00"
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": original_timestamp,
            "blocked_at": None,
            "completed_at": None,
            "history": "ip@2026-02-10T09:00:00",
        }

        crumbwise.handle_section_transition(task, "BLOCKED", "IN PROGRESS TODAY")

        assert task["in_progress"] == original_timestamp
        assert task["blocked_at"] is None
        # History should have both ip@ entries
        assert task["history"].startswith("ip@2026-02-10T09:00:00|ip@")

    def test_move_to_blocked_sets_blocked_at(self):
        """Moving to BLOCKED should set blocked_at and clear in_progress."""
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": "2026-02-10T09:00:00",
            "blocked_at": None,
            "completed_at": None,
            "history": "ip@2026-02-10T09:00:00",
        }

        crumbwise.handle_section_transition(task, "IN PROGRESS TODAY", "BLOCKED")

        assert task["blocked_at"] is not None
        assert task["in_progress"] is None
        assert "bl@" in task["history"]

    def test_move_to_todo_clears_in_progress(self):
        """Moving to TODO THIS WEEK should clear in_progress and blocked_at."""
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": "2026-02-10T09:00:00",
            "blocked_at": None,
            "completed_at": None,
            "history": "ip@2026-02-10T09:00:00",
        }

        crumbwise.handle_section_transition(task, "IN PROGRESS TODAY", "TODO THIS WEEK")

        assert task["in_progress"] is None
        assert task["blocked_at"] is None
        assert "op@" in task["history"]

    def test_move_to_done_sets_completed_at(self):
        """Moving to DONE THIS WEEK should set completed_at and clear other timestamps."""
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": "2026-02-10T09:00:00",
            "blocked_at": None,
            "completed_at": None,
            "history": "ip@2026-02-10T09:00:00",
        }

        crumbwise.handle_section_transition(task, "IN PROGRESS TODAY", "DONE THIS WEEK")

        assert task["completed_at"] is not None
        assert task["in_progress"] is None
        assert task["blocked_at"] is None
        assert "co@" in task["history"]

    def test_move_from_done_clears_completed_at(self):
        """Moving from DONE THIS WEEK should clear completed_at."""
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": None,
            "blocked_at": None,
            "completed_at": "2026-02-14T10:00:00",
            "history": "ip@2026-02-10T09:00:00|co@2026-02-14T10:00:00",
        }

        crumbwise.handle_section_transition(task, "DONE THIS WEEK", "TODO THIS WEEK")

        assert task["completed_at"] is None
        assert task["in_progress"] is None
        assert "op@" in task["history"]

    def test_ip_to_blocked_to_ip_cycle(self):
        """Moving IP -> BLOCKED -> IP should track full history."""
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": "2026-02-10T09:00:00",
            "blocked_at": None,
            "completed_at": None,
            "history": "ip@2026-02-10T09:00:00",
        }

        # Move to BLOCKED
        crumbwise.handle_section_transition(task, "IN PROGRESS TODAY", "BLOCKED")
        assert task["blocked_at"] is not None
        assert task["in_progress"] is None
        assert "|bl@" in task["history"]

        # Move back to IP
        crumbwise.handle_section_transition(task, "BLOCKED", "IN PROGRESS TODAY")
        assert task["in_progress"] is not None
        assert task["blocked_at"] is None
        assert task["history"].count("|ip@") == 1
        assert "|bl@" in task["history"]

    def test_move_to_quarterly_done_section(self):
        """Moving to quarterly done section (DONE Q1 2026) should set completed_at."""
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": "2026-02-10T09:00:00",
            "blocked_at": None,
            "completed_at": None,
            "history": "ip@2026-02-10T09:00:00",
        }

        crumbwise.handle_section_transition(task, "IN PROGRESS TODAY", "DONE Q1 2026")

        assert task["completed_at"] is not None
        assert task["in_progress"] is None
        assert "co@" in task["history"]

    def test_research_task_no_tracking(self):
        """Tasks from research sections should not have history/blocked_at tracked."""
        task = {
            "id": "task1",
            "text": "Research task",
            "in_progress": None,
            "blocked_at": None,
            "completed_at": None,
            "history": None,
        }

        # Move from research to blocked -- should NOT track
        crumbwise.handle_section_transition(task, "RESEARCH IN PROGRESS", "BLOCKED")

        assert task["blocked_at"] is None
        assert task["history"] is None

    def test_history_appends_with_pipe_delimiter(self):
        """History entries should be pipe-delimited."""
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": None,
            "blocked_at": None,
            "completed_at": None,
            "history": None,
        }

        # First transition
        crumbwise.handle_section_transition(task, "TODO THIS WEEK", "IN PROGRESS TODAY")
        history_after_first = task["history"]
        assert history_after_first.startswith("ip@")
        assert "|" not in history_after_first  # First entry, no pipe yet

        # Second transition
        crumbwise.handle_section_transition(task, "IN PROGRESS TODAY", "BLOCKED")
        history_after_second = task["history"]
        assert "|bl@" in history_after_second
        assert history_after_second.startswith("ip@")

    def test_move_from_backlog_to_in_progress(self):
        """Moving from BACKLOG HIGH to IN PROGRESS should set in_progress."""
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": None,
            "blocked_at": None,
            "completed_at": None,
            "history": None,
        }

        crumbwise.handle_section_transition(task, "BACKLOG HIGH", "IN PROGRESS TODAY")

        assert task["in_progress"] is not None
        assert "ip@" in task["history"]

    def test_blocked_clears_in_progress(self):
        """IMPORTANT: Moving to BLOCKED should clear in_progress (new behavior)."""
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": "2026-02-10T09:00:00",
            "blocked_at": None,
            "completed_at": None,
            "history": "ip@2026-02-10T09:00:00",
        }

        crumbwise.handle_section_transition(task, "IN PROGRESS TODAY", "BLOCKED")

        # Behavioral change: BLOCKED now clears in_progress
        assert task["in_progress"] is None
        assert task["blocked_at"] is not None

    def test_move_ip_to_done_full_lifecycle(self):
        """Full lifecycle: IP -> DONE should track all timestamps."""
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": "2026-02-10T09:00:00",
            "blocked_at": None,
            "completed_at": None,
            "history": "ip@2026-02-10T09:00:00",
        }

        crumbwise.handle_section_transition(task, "IN PROGRESS TODAY", "DONE THIS WEEK")

        assert task["completed_at"] is not None
        assert task["in_progress"] is None
        assert task["blocked_at"] is None
        assert task["history"].startswith("ip@2026-02-10T09:00:00|co@")

    def test_same_section_no_transition(self):
        """Moving to the same section should not trigger any changes."""
        task = {
            "id": "task1",
            "text": "Test task",
            "in_progress": "2026-02-10T09:00:00",
            "blocked_at": None,
            "completed_at": None,
            "history": "ip@2026-02-10T09:00:00",
        }

        original_history = task["history"]
        crumbwise.handle_section_transition(task, "IN PROGRESS TODAY", "IN PROGRESS TODAY")

        # Should be a no-op or preserve state (depending on implementation)
        # The important thing is in_progress shouldn't be set again since already set
        assert task["in_progress"] == "2026-02-10T09:00:00"


class TestUpdateTaskIntegration:
    """Integration tests for update_task() using handle_section_transition()."""

    def test_update_task_ip_to_blocked_via_put(self, tmp_path, client):
        """Moving a task from IN PROGRESS to BLOCKED via PUT should set blocked_at and append bl@ to history."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## IN PROGRESS TODAY

- [ ] Test task <!-- id:task1 in_progress:2026-02-10T09:00:00 history:ip@2026-02-10T09:00:00 -->

## BLOCKED

""")

        # Move task to BLOCKED via PUT
        response = client.put("/api/tasks/task1", json={"section": "BLOCKED"})
        assert response.status_code == 200

        # Parse tasks and verify blocked_at is set
        sections = crumbwise.parse_tasks()
        task = sections["BLOCKED"][0]
        assert task["blocked_at"] is not None
        assert task["in_progress"] is None  # Should be cleared
        assert "bl@" in task["history"]
        # History should have both entries
        history_parts = task["history"].split("|")
        assert len(history_parts) == 2
        assert history_parts[0] == "ip@2026-02-10T09:00:00"
        assert history_parts[1].startswith("bl@")

    def test_update_task_preserves_existing_in_progress_behavior(self, tmp_path, client):
        """Moving a task to IN PROGRESS should preserve existing in_progress behavior."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## TODO THIS WEEK

- [ ] Test task <!-- id:task1 -->

## IN PROGRESS TODAY

""")

        # Move task to IN PROGRESS
        response = client.put("/api/tasks/task1", json={"section": "IN PROGRESS TODAY"})
        assert response.status_code == 200

        # Parse and verify in_progress is set
        sections = crumbwise.parse_tasks()
        task = sections["IN PROGRESS TODAY"][0]
        assert task["in_progress"] is not None
        assert "ip@" in task["history"]


class TestReorderTasksIntegration:
    """Integration tests for reorder_tasks() using handle_section_transition()."""

    def test_reorder_blocked_to_done_sets_completed_at(self, tmp_path, client):
        """Moving a task from BLOCKED to DONE THIS WEEK via reorder should set completed_at and clear blocked_at."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## BLOCKED

- [ ] Test task <!-- id:task1 blocked_at:2026-02-12T14:00:00 history:ip@2026-02-10T09:00:00|bl@2026-02-12T14:00:00 -->

## DONE THIS WEEK

""")

        # Move task to DONE THIS WEEK via reorder
        response = client.post("/api/tasks/reorder", json={
            "taskId": "task1",
            "section": "DONE THIS WEEK",
            "index": 0
        })
        assert response.status_code == 200

        # Parse and verify completed_at is set and blocked_at is cleared
        sections = crumbwise.parse_tasks()
        task = sections["DONE THIS WEEK"][0]
        assert task["completed_at"] is not None  # Bug fix: drag to done now sets completed_at
        assert task["blocked_at"] is None
        assert task["in_progress"] is None
        # History should have all three entries
        history_parts = task["history"].split("|")
        assert len(history_parts) == 3
        assert history_parts[0] == "ip@2026-02-10T09:00:00"
        assert history_parts[1] == "bl@2026-02-12T14:00:00"
        assert history_parts[2].startswith("co@")

    def test_reorder_same_section_no_transition(self, tmp_path, client):
        """Reordering within the same section should not trigger transition logic."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## IN PROGRESS TODAY

- [ ] Task 1 <!-- id:task1 in_progress:2026-02-10T09:00:00 history:ip@2026-02-10T09:00:00 -->
- [ ] Task 2 <!-- id:task2 in_progress:2026-02-11T10:00:00 history:ip@2026-02-11T10:00:00 -->
""")

        # Reorder task1 to position 1 (after task2) in same section
        response = client.post("/api/tasks/reorder", json={
            "taskId": "task1",
            "section": "IN PROGRESS TODAY",
            "index": 1
        })
        assert response.status_code == 200

        # Verify history hasn't changed
        sections = crumbwise.parse_tasks()
        task = next(t for t in sections["IN PROGRESS TODAY"] if t["id"] == "task1")
        assert task["history"] == "ip@2026-02-10T09:00:00"  # No new entry

    def test_reorder_preserves_existing_in_progress_behavior(self, tmp_path, client):
        """Reorder should preserve existing in_progress setting behavior."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## TODO THIS WEEK

- [ ] Test task <!-- id:task1 -->

## IN PROGRESS TODAY

""")

        # Move task to IN PROGRESS via reorder
        response = client.post("/api/tasks/reorder", json={
            "taskId": "task1",
            "section": "IN PROGRESS TODAY",
            "index": 0
        })
        assert response.status_code == 200

        # Verify in_progress is set
        sections = crumbwise.parse_tasks()
        task = sections["IN PROGRESS TODAY"][0]
        assert task["in_progress"] is not None
        assert "ip@" in task["history"]


class TestToggleCompleteIntegration:
    """Integration tests for toggle_complete() with history tracking."""

    def test_toggle_complete_in_place_appends_co(self, tmp_path, client):
        """Completing a task via checkbox (in-place) should append co@ to history."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## IN PROGRESS TODAY

- [ ] Test task <!-- id:task1 in_progress:2026-02-10T09:00:00 history:ip@2026-02-10T09:00:00 -->
""")

        # Toggle complete
        response = client.post("/api/tasks/task1/complete")
        assert response.status_code == 200

        # Verify history has co@ appended
        sections = crumbwise.parse_tasks()
        task = sections["IN PROGRESS TODAY"][0]
        assert task["completed"] is True
        assert task["completed_at"] is not None
        # History should have ip@ and co@
        history_parts = task["history"].split("|")
        assert len(history_parts) == 2
        assert history_parts[0] == "ip@2026-02-10T09:00:00"
        assert history_parts[1].startswith("co@")

    def test_toggle_uncomplete_appends_op(self, tmp_path, client):
        """Uncompleting a task via checkbox should append op@ to history."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## IN PROGRESS TODAY

- [x] Test task <!-- id:task1 in_progress:2026-02-10T09:00:00 completed_at:2026-02-14T16:00:00 history:ip@2026-02-10T09:00:00|co@2026-02-14T16:00:00 -->
""")

        # Toggle uncomplete
        response = client.post("/api/tasks/task1/complete")
        assert response.status_code == 200

        # Verify history has op@ appended
        sections = crumbwise.parse_tasks()
        task = sections["IN PROGRESS TODAY"][0]
        assert task["completed"] is False
        assert task["completed_at"] is None
        # History should have ip@, co@, and op@
        history_parts = task["history"].split("|")
        assert len(history_parts) == 3
        assert history_parts[0] == "ip@2026-02-10T09:00:00"
        assert history_parts[1] == "co@2026-02-14T16:00:00"
        assert history_parts[2].startswith("op@")

    def test_toggle_complete_research_task_no_history(self, tmp_path, client):
        """Completing a research section task should not append history."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## RESEARCH IN PROGRESS

- [ ] Research task <!-- id:task1 -->
""")

        # Toggle complete
        response = client.post("/api/tasks/task1/complete")
        assert response.status_code == 200

        # Verify no history was added
        sections = crumbwise.parse_tasks()
        task = sections["RESEARCH IN PROGRESS"][0]
        assert task["completed"] is True
        assert task["completed_at"] is not None
        assert task.get("history") is None  # No history for research tasks

    def test_toggle_complete_project_moves_to_completed(self, tmp_path, client):
        """Completing a project should move to COMPLETED PROJECTS and append co@."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## PROJECTS

- [ ] Project task <!-- id:task1 history:ip@2026-02-10T09:00:00 -->

## COMPLETED PROJECTS

""")

        # Toggle complete
        response = client.post("/api/tasks/task1/complete")
        assert response.status_code == 200

        # Verify task moved to COMPLETED PROJECTS with co@ history
        sections = crumbwise.parse_tasks()
        assert len(sections["PROJECTS"]) == 0
        assert len(sections["COMPLETED PROJECTS"]) == 1
        task = sections["COMPLETED PROJECTS"][0]
        assert task["completed"] is True
        assert task["completed_at"] is not None
        # History should have co@ appended
        history_parts = task["history"].split("|")
        assert len(history_parts) == 2
        assert history_parts[0] == "ip@2026-02-10T09:00:00"
        assert history_parts[1].startswith("co@")

    def test_toggle_uncomplete_project_moves_to_projects(self, tmp_path, client):
        """Uncompleting a completed project should move back to PROJECTS and append op@."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## PROJECTS

## COMPLETED PROJECTS

- [x] Project task <!-- id:task1 completed_at:2026-02-14T16:00:00 history:ip@2026-02-10T09:00:00|co@2026-02-14T16:00:00 -->
""")

        # Toggle uncomplete
        response = client.post("/api/tasks/task1/complete")
        assert response.status_code == 200

        # Verify task moved back to PROJECTS with op@ history
        sections = crumbwise.parse_tasks()
        assert len(sections["COMPLETED PROJECTS"]) == 0
        assert len(sections["PROJECTS"]) == 1
        task = sections["PROJECTS"][0]
        assert task["completed"] is False
        assert task["completed_at"] is None
        # History should have op@ appended
        history_parts = task["history"].split("|")
        assert len(history_parts) == 3
        assert history_parts[0] == "ip@2026-02-10T09:00:00"
        assert history_parts[1] == "co@2026-02-14T16:00:00"
        assert history_parts[2].startswith("op@")

    def test_toggle_complete_in_done_section_appends_history(self, tmp_path, client):
        """Completing a task that's already in DONE THIS WEEK should still append co@."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, """## DONE THIS WEEK

- [ ] Test task <!-- id:task1 in_progress:2026-02-10T09:00:00 history:ip@2026-02-10T09:00:00 -->
""")

        # Toggle complete
        response = client.post("/api/tasks/task1/complete")
        assert response.status_code == 200

        # Verify history has co@ appended
        sections = crumbwise.parse_tasks()
        task = sections["DONE THIS WEEK"][0]
        assert task["completed"] is True
        assert task["completed_at"] is not None
        # History should have co@ appended
        history_parts = task["history"].split("|")
        assert len(history_parts) == 2
        assert history_parts[0] == "ip@2026-02-10T09:00:00"
        assert history_parts[1].startswith("co@")
