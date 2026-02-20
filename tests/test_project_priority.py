"""Tests for project priority buckets (high/medium/paused).

Tests that priority metadata is correctly parsed, saved, migrated,
and accessible via the API.
"""

import json
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


class TestPriorityParsing:
    """Test priority metadata parsing and defaults."""

    def test_priority_default_medium(self, app, tmp_path):
        """Project without priority metadata parses as 'medium'."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, (
            "## PROJECTS\n\n"
            "- [ ] My Project <!-- id:abc123 project:1 -->\n\n"
        ))
        crumbwise.TASKS_FILE = tasks_file
        sections = crumbwise.parse_tasks()
        project = sections["PROJECTS"][0]
        assert project["priority"] == "medium"

    def test_priority_parsed_from_metadata(self, app, tmp_path):
        """priority:high in markdown parses correctly."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, (
            "## PROJECTS\n\n"
            "- [ ] Urgent Project <!-- id:abc123 project:2 priority:high -->\n\n"
        ))
        crumbwise.TASKS_FILE = tasks_file
        sections = crumbwise.parse_tasks()
        project = sections["PROJECTS"][0]
        assert project["priority"] == "high"

    def test_priority_paused_parsed(self, app, tmp_path):
        """priority:paused in markdown parses correctly."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, (
            "## PROJECTS\n\n"
            "- [ ] On Hold <!-- id:abc123 project:3 priority:paused -->\n\n"
        ))
        crumbwise.TASKS_FILE = tasks_file
        sections = crumbwise.parse_tasks()
        project = sections["PROJECTS"][0]
        assert project["priority"] == "paused"

    def test_priority_saved_to_metadata(self, app, tmp_path):
        """save_tasks writes priority to markdown metadata."""
        tasks_file = tmp_path / "tasks.md"
        crumbwise.TASKS_FILE = tasks_file

        sections = {"PROJECTS": [{
            "id": "abc123",
            "text": "Test Project",
            "completed": False,
            "color_index": 1,
            "priority": "high",
            "created": None, "updated": None, "in_progress": None,
            "completed_at": None, "blocked_at": None, "history": None,
            "order_index": None,
        }]}
        crumbwise.save_tasks(sections)

        content = tasks_file.read_text()
        assert "priority:high" in content

    def test_non_project_has_no_priority(self, app, tmp_path):
        """Non-project tasks should not have a priority field."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, (
            "## TODO THIS WEEK\n\n"
            "- [ ] Regular task <!-- id:abc123 -->\n\n"
        ))
        crumbwise.TASKS_FILE = tasks_file
        sections = crumbwise.parse_tasks()
        task = sections["TODO THIS WEEK"][0]
        assert "priority" not in task


class TestPriorityAPI:
    """Test the /api/tasks/<id>/priority endpoint."""

    def test_set_priority_api(self, client, app, tmp_path):
        """POST /api/tasks/<id>/priority with valid value succeeds."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, (
            "## PROJECTS\n\n"
            "- [ ] My Project <!-- id:proj1 project:1 priority:medium -->\n\n"
        ))
        crumbwise.TASKS_FILE = tasks_file

        response = client.post(
            "/api/tasks/proj1/priority",
            data=json.dumps({"priority": "high"}),
            content_type="application/json"
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["priority"] == "high"

        # Verify persistence
        sections = crumbwise.parse_tasks()
        assert sections["PROJECTS"][0]["priority"] == "high"

    def test_set_invalid_priority_api(self, client, app, tmp_path):
        """POST with invalid priority value returns 400."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, (
            "## PROJECTS\n\n"
            "- [ ] My Project <!-- id:proj1 project:1 priority:medium -->\n\n"
        ))
        crumbwise.TASKS_FILE = tasks_file

        response = client.post(
            "/api/tasks/proj1/priority",
            data=json.dumps({"priority": "urgent"}),
            content_type="application/json"
        )
        assert response.status_code == 400

    def test_set_priority_non_project(self, client, app, tmp_path):
        """POST on non-project task returns 404."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, (
            "## TODO THIS WEEK\n\n"
            "- [ ] Regular task <!-- id:task1 -->\n\n"
        ))
        crumbwise.TASKS_FILE = tasks_file

        response = client.post(
            "/api/tasks/task1/priority",
            data=json.dumps({"priority": "high"}),
            content_type="application/json"
        )
        assert response.status_code == 404

    def test_priority_in_get_tasks(self, client, app, tmp_path):
        """GET /api/tasks includes priority on projects."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, (
            "## PROJECTS\n\n"
            "- [ ] My Project <!-- id:proj1 project:1 priority:high -->\n\n"
        ))
        crumbwise.TASKS_FILE = tasks_file

        response = client.get("/api/tasks")
        data = response.get_json()
        project = data["PROJECTS"][0]
        assert project["priority"] == "high"

    def test_new_project_gets_medium(self, client, app, tmp_path):
        """POST to create project gets priority 'medium'."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, "## PROJECTS\n\n")
        crumbwise.TASKS_FILE = tasks_file

        response = client.post(
            "/api/tasks",
            data=json.dumps({"section": "PROJECTS", "text": "New Project"}),
            content_type="application/json"
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["priority"] == "medium"


class TestPriorityMigration:
    """Test that existing projects get migrated to medium priority."""

    def test_migration_adds_medium(self, app, tmp_path):
        """Projects without priority get 'medium' written to disk."""
        tasks_file = tmp_path / "tasks.md"
        write_tasks(tasks_file, (
            "## PROJECTS\n\n"
            "- [ ] Old Project <!-- id:old1 project:1 -->\n\n"
        ))
        crumbwise.TASKS_FILE = tasks_file

        # parse_tasks triggers migration
        sections = crumbwise.parse_tasks()
        assert sections["PROJECTS"][0]["priority"] == "medium"

        # Verify written to disk
        content = tasks_file.read_text()
        assert "priority:medium" in content


class TestConfluencePriorityGrouping:
    """Test that Confluence export groups projects by priority."""

    def test_confluence_priority_grouping(self, app, tmp_path):
        """generate_confluence_content groups projects by priority bucket."""
        tasks_file = tmp_path / "tasks.md"
        crumbwise.TASKS_FILE = tasks_file

        sections = {
            "PROJECTS": [
                {"id": "p1", "text": "High Proj", "completed": False,
                 "color_index": 1, "priority": "high",
                 "created": None, "updated": None, "in_progress": None,
                 "completed_at": None, "blocked_at": None, "history": None,
                 "order_index": None},
                {"id": "p2", "text": "Medium Proj", "completed": False,
                 "color_index": 2, "priority": "medium",
                 "created": None, "updated": None, "in_progress": None,
                 "completed_at": None, "blocked_at": None, "history": None,
                 "order_index": None},
                {"id": "p3", "text": "Paused Proj", "completed": False,
                 "color_index": 3, "priority": "paused",
                 "created": None, "updated": None, "in_progress": None,
                 "completed_at": None, "blocked_at": None, "history": None,
                 "order_index": None},
            ],
            "DONE THIS WEEK": [],
            "FOLLOW UPS": [],
            "BLOCKED": [],
            "IN PROGRESS TODAY": [],
            "TODO THIS WEEK": [],
            "TODO NEXT WEEK": [],
            "TODO FOLLOWING WEEK": [],
            "BACKLOG HIGH PRIORITY": [],
            "BACKLOG MEDIUM PRIORITY": [],
            "BACKLOG LOW PRIORITY": [],
            "PROBLEMS TO SOLVE": [],
            "THINGS TO RESEARCH": [],
        }

        html = crumbwise.generate_confluence_content(sections)

        # Should have three priority headings
        assert "Projects - High Priority" in html
        assert "Projects - Medium Priority" in html
        assert "Projects - Paused" in html

        # High project should be under high heading, not under medium
        high_pos = html.index("Projects - High Priority")
        medium_pos = html.index("Projects - Medium Priority")
        paused_pos = html.index("Projects - Paused")

        high_proj_pos = html.index("High Proj")
        medium_proj_pos = html.index("Medium Proj")
        paused_proj_pos = html.index("Paused Proj")

        assert high_pos < high_proj_pos < medium_pos
        assert medium_pos < medium_proj_pos < paused_pos
        assert paused_pos < paused_proj_pos
