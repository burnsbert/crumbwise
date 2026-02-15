"""Tests for project timeline sort logic.

These tests verify the sort ordering in /api/projects/<id>/timeline.
Uses a temporary tasks.md file to avoid touching user data.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

# Import the Flask app so we can use its test client
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


# ---------------------------------------------------------------------------
# Section age tier unit tests
# ---------------------------------------------------------------------------

class TestSectionAgeTier:
    """Test the _section_age_tier helper used in chronological sort fallback.

    This is the function that maps section names to chronological tiers.
    Since it's defined inside get_project_timeline(), we test it indirectly
    through the API, and also replicate the logic here for unit-level checks.
    """

    @staticmethod
    def section_age_tier(section_name):
        """Replica of _section_age_tier from crumbwise.py for direct testing."""
        name = section_name.upper()
        if name.startswith("DONE 20"):
            try:
                return (0, int(name.split()[-1]))
            except ValueError:
                return (0, 9999)
        if name.startswith("DONE Q"):
            parts = name.split()
            try:
                return (1, int(parts[2]) * 10 + int(parts[1][1]))
            except (IndexError, ValueError):
                return (1, 99999)
        if name == "COMPLETED PROJECTS":
            return (2, 0)
        if name in ("DONE THIS WEEK", "RESEARCH DONE"):
            return (3, 0)
        if name in ("IN PROGRESS TODAY", "RESEARCH IN PROGRESS"):
            return (4, 0)
        if name == "TODO THIS WEEK":
            return (5, 0)
        if name == "TODO NEXT WEEK":
            return (6, 0)
        if name == "TODO FOLLOWING WEEK":
            return (7, 0)
        return (8, 0)

    def test_yearly_done_is_oldest(self):
        assert self.section_age_tier("DONE 2025") < self.section_age_tier("DONE Q1 2026")

    def test_quarterly_before_weekly_done(self):
        assert self.section_age_tier("DONE Q1 2026") < self.section_age_tier("DONE THIS WEEK")

    def test_weekly_done_before_in_progress(self):
        assert self.section_age_tier("DONE THIS WEEK") < self.section_age_tier("IN PROGRESS TODAY")

    def test_in_progress_before_todo(self):
        assert self.section_age_tier("IN PROGRESS TODAY") < self.section_age_tier("TODO THIS WEEK")

    def test_todo_ordering(self):
        assert self.section_age_tier("TODO THIS WEEK") < self.section_age_tier("TODO NEXT WEEK")
        assert self.section_age_tier("TODO NEXT WEEK") < self.section_age_tier("TODO FOLLOWING WEEK")

    def test_yearly_done_ordering(self):
        assert self.section_age_tier("DONE 2024") < self.section_age_tier("DONE 2025")

    def test_quarterly_ordering(self):
        assert self.section_age_tier("DONE Q1 2026") < self.section_age_tier("DONE Q2 2026")
        assert self.section_age_tier("DONE Q4 2025") < self.section_age_tier("DONE Q1 2026")

    def test_full_chronological_ordering(self):
        """Verify the complete ordering from oldest to newest."""
        sections = [
            "DONE 2025",
            "DONE Q1 2026",
            "DONE Q2 2026",
            "COMPLETED PROJECTS",
            "DONE THIS WEEK",
            "IN PROGRESS TODAY",
            "TODO THIS WEEK",
            "TODO NEXT WEEK",
            "TODO FOLLOWING WEEK",
            "BACKLOG HIGH PRIORITY",
        ]
        tiers = [self.section_age_tier(s) for s in sections]
        assert tiers == sorted(tiers), (
            f"Sections not in chronological order: {list(zip(sections, tiers))}"
        )


# ---------------------------------------------------------------------------
# Timeline API sort tests (integration tests using Flask test client)
# ---------------------------------------------------------------------------

PROJECT_ID = "proj-001"

TASKS_WITH_NO_TIMESTAMPS = f"""\
## PROJECTS

- [ ] Test Project <!-- id:{PROJECT_ID} project:1 -->

## IN PROGRESS TODAY

- [ ] Active task <!-- id:task-active assigned:{PROJECT_ID} -->

## DONE THIS WEEK

- [ ] Recently done task <!-- id:task-recent assigned:{PROJECT_ID} -->

## DONE Q1 2026

- [ ] Old task A <!-- id:task-old-a assigned:{PROJECT_ID} -->
- [ ] Old task B <!-- id:task-old-b assigned:{PROJECT_ID} -->

## TODO THIS WEEK

## DONE 2025

- [ ] Ancient task <!-- id:task-ancient assigned:{PROJECT_ID} -->
"""


class TestTimelineSortNoTimestamps:
    """Test sort when tasks have NO timestamps (pre-existing tasks).

    THIS TEST WOULD HAVE CAUGHT THE ORIGINAL BUG:
    Tasks without timestamps should still sort oldest-first using
    section membership as a chronological proxy.
    """

    def test_oldest_sections_sort_first(self, client, tmp_path):
        """Tasks in DONE 2025 should appear before DONE Q1 2026
        before DONE THIS WEEK before IN PROGRESS TODAY."""
        write_tasks(crumbwise.TASKS_FILE, TASKS_WITH_NO_TIMESTAMPS)

        resp = client.get(f"/api/projects/{PROJECT_ID}/timeline")
        assert resp.status_code == 200

        data = resp.get_json()
        task_ids = [t["id"] for t in data["tasks"]]

        assert task_ids == [
            "task-ancient",   # DONE 2025 (oldest)
            "task-old-a",     # DONE Q1 2026
            "task-old-b",     # DONE Q1 2026
            "task-recent",    # DONE THIS WEEK
            "task-active",    # IN PROGRESS TODAY (newest)
        ]

    def test_section_names_in_response(self, client, tmp_path):
        """Each task includes its section name."""
        write_tasks(crumbwise.TASKS_FILE, TASKS_WITH_NO_TIMESTAMPS)

        resp = client.get(f"/api/projects/{PROJECT_ID}/timeline")
        data = resp.get_json()
        sections = [t["section"] for t in data["tasks"]]

        assert sections == [
            "DONE 2025",
            "DONE Q1 2026",
            "DONE Q1 2026",
            "DONE THIS WEEK",
            "IN PROGRESS TODAY",
        ]


TASKS_WITH_TIMESTAMPS = f"""\
## PROJECTS

- [ ] Test Project <!-- id:{PROJECT_ID} project:1 -->

## IN PROGRESS TODAY

- [ ] Newest task <!-- id:task-new assigned:{PROJECT_ID} in_progress:2026-02-15T10:00:00 created:2026-02-14T09:00:00 -->
- [ ] Middle task <!-- id:task-mid assigned:{PROJECT_ID} in_progress:2026-02-10T10:00:00 created:2026-02-09T09:00:00 -->

## DONE THIS WEEK

- [ ] Oldest task <!-- id:task-old assigned:{PROJECT_ID} in_progress:2026-02-01T10:00:00 created:2026-01-30T09:00:00 -->

## TODO THIS WEEK

"""


class TestTimelineSortWithTimestamps:
    """Test sort when tasks have timestamps."""

    def test_oldest_timestamp_first(self, client, tmp_path):
        """Tasks with timestamps sort oldest first within same section tier."""
        write_tasks(crumbwise.TASKS_FILE, TASKS_WITH_TIMESTAMPS)

        resp = client.get(f"/api/projects/{PROJECT_ID}/timeline")
        data = resp.get_json()
        task_ids = [t["id"] for t in data["tasks"]]

        # DONE THIS WEEK (tier 3) before IN PROGRESS (tier 4)
        # Within IN PROGRESS, older timestamp first
        assert task_ids == [
            "task-old",   # DONE THIS WEEK, oldest timestamp
            "task-mid",   # IN PROGRESS, older timestamp
            "task-new",   # IN PROGRESS, newest timestamp
        ]


TASKS_MIXED_TIMESTAMPS = f"""\
## PROJECTS

- [ ] Test Project <!-- id:{PROJECT_ID} project:1 -->

## IN PROGRESS TODAY

- [ ] Has timestamp <!-- id:task-ts assigned:{PROJECT_ID} in_progress:2026-02-15T10:00:00 -->
- [ ] No timestamp <!-- id:task-nots assigned:{PROJECT_ID} -->

## TODO THIS WEEK

"""


class TestTimelineSortMixedTimestamps:
    """Test sort with a mix of timestamped and non-timestamped tasks."""

    def test_no_timestamp_sorts_after_timestamped_in_same_tier(self, client, tmp_path):
        """Within the same section tier, tasks with timestamps come before
        tasks without timestamps (which get sentinel "9999")."""
        write_tasks(crumbwise.TASKS_FILE, TASKS_MIXED_TIMESTAMPS)

        resp = client.get(f"/api/projects/{PROJECT_ID}/timeline")
        data = resp.get_json()
        task_ids = [t["id"] for t in data["tasks"]]

        assert task_ids == [
            "task-ts",    # has timestamp (sorts earlier)
            "task-nots",  # no timestamp (sentinel "9999")
        ]


# ---------------------------------------------------------------------------
# order_index sort tests
# ---------------------------------------------------------------------------

TASKS_WITH_ORDER_INDEX = f"""\
## PROJECTS

- [ ] Test Project <!-- id:{PROJECT_ID} project:1 -->

## IN PROGRESS TODAY

- [ ] Third <!-- id:task-c assigned:{PROJECT_ID} order_index:2 -->
- [ ] First <!-- id:task-a assigned:{PROJECT_ID} order_index:0 -->

## DONE THIS WEEK

- [ ] Second <!-- id:task-b assigned:{PROJECT_ID} order_index:1 -->

## TODO THIS WEEK

"""


class TestTimelineSortWithOrderIndex:
    """Test that order_index takes priority over section-based sort."""

    def test_order_index_overrides_section_sort(self, client, tmp_path):
        """When tasks have order_index, sort by order_index regardless of section."""
        write_tasks(crumbwise.TASKS_FILE, TASKS_WITH_ORDER_INDEX)

        resp = client.get(f"/api/projects/{PROJECT_ID}/timeline")
        data = resp.get_json()
        task_ids = [t["id"] for t in data["tasks"]]

        assert task_ids == ["task-a", "task-b", "task-c"]

    def test_order_index_zero_is_valid(self, client, tmp_path):
        """order_index=0 is a valid position (not treated as falsy/None)."""
        write_tasks(crumbwise.TASKS_FILE, TASKS_WITH_ORDER_INDEX)

        resp = client.get(f"/api/projects/{PROJECT_ID}/timeline")
        data = resp.get_json()

        first_task = data["tasks"][0]
        assert first_task["id"] == "task-a"
        assert first_task["order_index"] == 0


TASKS_PARTIAL_ORDER_INDEX = f"""\
## PROJECTS

- [ ] Test Project <!-- id:{PROJECT_ID} project:1 -->

## IN PROGRESS TODAY

- [ ] Ordered first <!-- id:task-ordered assigned:{PROJECT_ID} order_index:0 -->
- [ ] Not ordered <!-- id:task-unordered assigned:{PROJECT_ID} -->

## TODO THIS WEEK

"""


class TestTimelineSortPartialOrderIndex:
    """Test when some tasks have order_index and others don't."""

    def test_unordered_tasks_sort_after_ordered(self, client, tmp_path):
        """Tasks without order_index go to the end when other tasks have it."""
        write_tasks(crumbwise.TASKS_FILE, TASKS_PARTIAL_ORDER_INDEX)

        resp = client.get(f"/api/projects/{PROJECT_ID}/timeline")
        data = resp.get_json()
        task_ids = [t["id"] for t in data["tasks"]]

        assert task_ids == ["task-ordered", "task-unordered"]


# ---------------------------------------------------------------------------
# order_index parsing tests
# ---------------------------------------------------------------------------

class TestOrderIndexParsing:
    """Test that order_index is correctly parsed from and saved to markdown."""

    def test_order_index_parsed_as_integer(self, client, tmp_path):
        write_tasks(crumbwise.TASKS_FILE, TASKS_WITH_ORDER_INDEX)

        resp = client.get(f"/api/projects/{PROJECT_ID}/timeline")
        data = resp.get_json()

        for task in data["tasks"]:
            assert isinstance(task["order_index"], int)

    def test_missing_order_index_is_none(self, client, tmp_path):
        write_tasks(crumbwise.TASKS_FILE, TASKS_WITH_NO_TIMESTAMPS)

        resp = client.get(f"/api/projects/{PROJECT_ID}/timeline")
        data = resp.get_json()

        for task in data["tasks"]:
            assert task["order_index"] is None

    def test_order_index_roundtrips_through_save(self, tmp_path):
        """order_index survives parse -> save -> parse cycle."""
        content = f"""\
## PROJECTS

- [ ] Test Project <!-- id:{PROJECT_ID} project:1 -->

## IN PROGRESS TODAY

- [ ] Task <!-- id:task-1 assigned:{PROJECT_ID} order_index:5 -->

## TODO THIS WEEK

"""
        write_tasks(crumbwise.TASKS_FILE, content)

        # Parse, save, parse again
        sections = crumbwise.parse_tasks()
        crumbwise.save_tasks(sections)
        sections2 = crumbwise.parse_tasks()

        task = None
        for tasks in sections2.values():
            for t in tasks:
                if t["id"] == "task-1":
                    task = t
                    break

        assert task is not None
        assert task["order_index"] == 5


# ---------------------------------------------------------------------------
# Reorder endpoint tests
# ---------------------------------------------------------------------------

class TestReorderEndpoint:
    """Test POST /api/projects/<id>/reorder."""

    def test_reorder_sets_order_index(self, client, tmp_path):
        content = f"""\
## PROJECTS

- [ ] Test Project <!-- id:{PROJECT_ID} project:1 -->

## IN PROGRESS TODAY

- [ ] A <!-- id:task-a assigned:{PROJECT_ID} -->
- [ ] B <!-- id:task-b assigned:{PROJECT_ID} -->
- [ ] C <!-- id:task-c assigned:{PROJECT_ID} -->

## TODO THIS WEEK

"""
        write_tasks(crumbwise.TASKS_FILE, content)

        # Reorder: C, A, B
        resp = client.post(
            f"/api/projects/{PROJECT_ID}/reorder",
            json={"taskIds": ["task-c", "task-a", "task-b"]},
        )
        assert resp.status_code == 200

        # Verify order persisted
        resp = client.get(f"/api/projects/{PROJECT_ID}/timeline")
        data = resp.get_json()
        task_ids = [t["id"] for t in data["tasks"]]
        assert task_ids == ["task-c", "task-a", "task-b"]

    def test_reorder_does_not_set_updated_timestamp(self, client, tmp_path):
        content = f"""\
## PROJECTS

- [ ] Test Project <!-- id:{PROJECT_ID} project:1 -->

## IN PROGRESS TODAY

- [ ] A <!-- id:task-a assigned:{PROJECT_ID} -->
- [ ] B <!-- id:task-b assigned:{PROJECT_ID} -->

## TODO THIS WEEK

"""
        write_tasks(crumbwise.TASKS_FILE, content)

        resp = client.post(
            f"/api/projects/{PROJECT_ID}/reorder",
            json={"taskIds": ["task-b", "task-a"]},
        )
        assert resp.status_code == 200

        # Verify no updated timestamp was set
        sections = crumbwise.parse_tasks()
        for tasks in sections.values():
            for t in tasks:
                if t["id"] in ("task-a", "task-b"):
                    assert t["updated"] is None


# ---------------------------------------------------------------------------
# Assign/unassign order_index lifecycle
# ---------------------------------------------------------------------------

class TestAssignOrderIndexLifecycle:
    """Test that order_index is set on assign and cleared on unassign."""

    def test_assign_to_ordered_project_gets_max_plus_one(self, client, tmp_path):
        content = f"""\
## PROJECTS

- [ ] Test Project <!-- id:{PROJECT_ID} project:1 -->

## IN PROGRESS TODAY

- [ ] Existing <!-- id:task-existing assigned:{PROJECT_ID} order_index:3 -->
- [ ] New task <!-- id:task-new -->

## TODO THIS WEEK

"""
        write_tasks(crumbwise.TASKS_FILE, content)

        resp = client.post(
            f"/api/tasks/task-new/assign",
            json={"projectId": PROJECT_ID},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["order_index"] == 4  # max(3) + 1

    def test_assign_to_unordered_project_no_order_index(self, client, tmp_path):
        content = f"""\
## PROJECTS

- [ ] Test Project <!-- id:{PROJECT_ID} project:1 -->

## IN PROGRESS TODAY

- [ ] Existing <!-- id:task-existing assigned:{PROJECT_ID} -->
- [ ] New task <!-- id:task-new -->

## TODO THIS WEEK

"""
        write_tasks(crumbwise.TASKS_FILE, content)

        resp = client.post(
            f"/api/tasks/task-new/assign",
            json={"projectId": PROJECT_ID},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # No ordered tasks in project, so order_index should not be set
        assert data.get("order_index") is None

    def test_unassign_clears_order_index(self, client, tmp_path):
        content = f"""\
## PROJECTS

- [ ] Test Project <!-- id:{PROJECT_ID} project:1 -->

## IN PROGRESS TODAY

- [ ] Task <!-- id:task-1 assigned:{PROJECT_ID} order_index:2 -->

## TODO THIS WEEK

"""
        write_tasks(crumbwise.TASKS_FILE, content)

        resp = client.post("/api/tasks/task-1/unassign")
        assert resp.status_code == 200

        # Verify order_index was cleared
        sections = crumbwise.parse_tasks()
        for tasks in sections.values():
            for t in tasks:
                if t["id"] == "task-1":
                    assert t["order_index"] is None

    def test_reassign_clears_stale_order_index(self, client, tmp_path):
        """Assigning to a new project clears stale order_index from old project."""
        content = f"""\
## PROJECTS

- [ ] Old Project <!-- id:old-proj project:1 -->
- [ ] New Project <!-- id:new-proj project:2 -->

## IN PROGRESS TODAY

- [ ] Task with stale index <!-- id:task-1 assigned:old-proj order_index:99 -->

## TODO THIS WEEK

"""
        write_tasks(crumbwise.TASKS_FILE, content)

        resp = client.post(
            "/api/tasks/task-1/assign",
            json={"projectId": "new-proj"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # New project has no ordered tasks, so order_index should not be set
        # (stale value 99 from old project was cleared by pop())
        assert data.get("order_index") is None
