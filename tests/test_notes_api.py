"""Tests for the notes JSON API endpoints.

Covers: GET/POST /api/notes, PUT/DELETE /api/notes/<id>, POST /api/notes/reorder,
migration from notes.txt, and project_color resolution.
"""

import json
import pytest
import crumbwise


@pytest.fixture
def app(tmp_path):
    """Test app with isolated data directory."""
    crumbwise.DEFAULT_DATA_DIR = tmp_path
    crumbwise.app.config["TESTING"] = True
    yield crumbwise.app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


def write_tasks(tasks_file, content):
    """Helper to write task markdown content."""
    tasks_file.write_text(content)


# --- GET /api/notes ---


class TestGetNotes:
    def test_get_notes_empty(self, tmp_path, client):
        """Returns empty list when no notes.json exists."""
        resp = client.get("/api/notes")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_get_notes_sorted_by_order_index(self, tmp_path, client):
        """Notes are returned sorted by order_index ascending."""
        notes = [
            {"id": "a", "title": "Z", "content": "", "created_at": "2026-01-01T00:00:00",
             "updated_at": "2026-01-01T00:00:00", "assigned_project": None, "order_index": 2},
            {"id": "b", "title": "A", "content": "", "created_at": "2026-01-01T00:00:00",
             "updated_at": "2026-01-01T00:00:00", "assigned_project": None, "order_index": 0},
            {"id": "c", "title": "M", "content": "", "created_at": "2026-01-01T00:00:00",
             "updated_at": "2026-01-01T00:00:00", "assigned_project": None, "order_index": 1},
        ]
        (tmp_path / "notes.json").write_text(json.dumps(notes))
        resp = client.get("/api/notes")
        data = resp.get_json()
        assert [n["id"] for n in data] == ["b", "c", "a"]

    def test_get_notes_includes_project_color_null(self, tmp_path, client):
        """project_color is null when no project assigned."""
        write_tasks(tmp_path / "tasks.md", "## PROJECTS\n\n")
        notes = [
            {"id": "a", "title": "T", "content": "", "created_at": "2026-01-01T00:00:00",
             "updated_at": "2026-01-01T00:00:00", "assigned_project": None, "order_index": 0},
        ]
        (tmp_path / "notes.json").write_text(json.dumps(notes))
        resp = client.get("/api/notes")
        data = resp.get_json()
        assert data[0]["project_color"] is None

    def test_get_notes_resolves_project_color(self, tmp_path, client):
        """project_color is resolved from PROJECTS section."""
        proj_id = "proj-uuid-123"
        tasks_content = f"## PROJECTS\n\n- [ ] My Project <!-- id:{proj_id} project:5 -->\n"
        write_tasks(tmp_path / "tasks.md", tasks_content)
        notes = [
            {"id": "n1", "title": "Test", "content": "", "created_at": "2026-01-01T00:00:00",
             "updated_at": "2026-01-01T00:00:00", "assigned_project": proj_id, "order_index": 0},
        ]
        (tmp_path / "notes.json").write_text(json.dumps(notes))
        resp = client.get("/api/notes")
        data = resp.get_json()
        assert data[0]["project_color"] == 5


# --- POST /api/notes ---


class TestCreateNote:
    def test_create_note_returns_201(self, tmp_path, client):
        """Creating a note returns 201."""
        resp = client.post("/api/notes", json={"title": "Hello", "content": "World"})
        assert resp.status_code == 201

    def test_create_note_has_required_fields(self, tmp_path, client):
        """Created note has id, created_at, updated_at, order_index."""
        resp = client.post("/api/notes", json={"title": "T", "content": "C"})
        data = resp.get_json()
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data
        assert "order_index" in data
        assert data["title"] == "T"
        assert data["content"] == "C"

    def test_create_note_persisted(self, tmp_path, client):
        """Note is retrievable after creation."""
        client.post("/api/notes", json={"title": "Persist", "content": ""})
        resp = client.get("/api/notes")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["title"] == "Persist"

    def test_create_note_order_index_is_max_plus_one(self, tmp_path, client):
        """First note gets order_index 0; second gets 1."""
        r1 = client.post("/api/notes", json={"title": "First", "content": ""})
        r2 = client.post("/api/notes", json={"title": "Second", "content": ""})
        assert r1.get_json()["order_index"] == 0
        assert r2.get_json()["order_index"] == 1

    def test_create_note_with_project(self, tmp_path, client):
        """assigned_project is stored when provided."""
        resp = client.post("/api/notes", json={
            "title": "Proj Note", "content": "", "assigned_project": "proj-123"
        })
        assert resp.get_json()["assigned_project"] == "proj-123"

    def test_create_note_empty_project_stored_as_none(self, tmp_path, client):
        """Empty string assigned_project is stored as null."""
        resp = client.post("/api/notes", json={
            "title": "Note", "content": "", "assigned_project": ""
        })
        assert resp.get_json()["assigned_project"] is None


# --- PUT /api/notes/<id> ---


class TestUpdateNote:
    def test_update_note_title(self, tmp_path, client):
        """PUT updates title."""
        create_resp = client.post("/api/notes", json={"title": "Old", "content": ""})
        note_id = create_resp.get_json()["id"]
        resp = client.put(f"/api/notes/{note_id}", json={"title": "New"})
        assert resp.status_code == 200
        assert resp.get_json()["title"] == "New"

    def test_update_note_content(self, tmp_path, client):
        """PUT updates content."""
        note_id = client.post("/api/notes", json={"title": "T", "content": "old"}).get_json()["id"]
        resp = client.put(f"/api/notes/{note_id}", json={"content": "new"})
        assert resp.get_json()["content"] == "new"

    def test_update_note_bumps_updated_at(self, tmp_path, client):
        """PUT bumps updated_at."""
        note = client.post("/api/notes", json={"title": "T", "content": ""}).get_json()
        original_updated = note["updated_at"]
        import time; time.sleep(0.01)
        updated = client.put(f"/api/notes/{note['id']}", json={"title": "New"}).get_json()
        assert updated["updated_at"] >= original_updated

    def test_update_note_assign_project(self, tmp_path, client):
        """PUT can assign a project."""
        note_id = client.post("/api/notes", json={"title": "T", "content": ""}).get_json()["id"]
        resp = client.put(f"/api/notes/{note_id}", json={"assigned_project": "proj-abc"})
        assert resp.get_json()["assigned_project"] == "proj-abc"

    def test_update_note_clear_project(self, tmp_path, client):
        """PUT with empty assigned_project clears it."""
        note_id = client.post("/api/notes", json={
            "title": "T", "content": "", "assigned_project": "proj-abc"
        }).get_json()["id"]
        resp = client.put(f"/api/notes/{note_id}", json={"assigned_project": ""})
        assert resp.get_json()["assigned_project"] is None

    def test_update_note_not_found(self, tmp_path, client):
        """PUT on unknown ID returns 404."""
        resp = client.put("/api/notes/nonexistent", json={"title": "X"})
        assert resp.status_code == 404


# --- DELETE /api/notes/<id> ---


class TestDeleteNote:
    def test_delete_note(self, tmp_path, client):
        """DELETE removes the note."""
        note_id = client.post("/api/notes", json={"title": "Gone", "content": ""}).get_json()["id"]
        resp = client.delete(f"/api/notes/{note_id}")
        assert resp.status_code == 200
        notes = client.get("/api/notes").get_json()
        assert all(n["id"] != note_id for n in notes)

    def test_delete_nonexistent_note(self, tmp_path, client):
        """DELETE on unknown ID returns 200 (idempotent)."""
        resp = client.delete("/api/notes/nonexistent-id")
        assert resp.status_code == 200


# --- POST /api/notes/reorder ---


class TestReorderNotes:
    def test_reorder_updates_order_index(self, tmp_path, client):
        """Reorder assigns order_index based on position in supplied list."""
        r1 = client.post("/api/notes", json={"title": "A", "content": ""}).get_json()
        r2 = client.post("/api/notes", json={"title": "B", "content": ""}).get_json()
        r3 = client.post("/api/notes", json={"title": "C", "content": ""}).get_json()

        # Reverse the order
        client.post("/api/notes/reorder", json={"order": [r3["id"], r2["id"], r1["id"]]})

        notes = {n["id"]: n for n in client.get("/api/notes").get_json()}
        assert notes[r3["id"]]["order_index"] == 0
        assert notes[r2["id"]]["order_index"] == 1
        assert notes[r1["id"]]["order_index"] == 2

    def test_reorder_get_returns_new_order(self, tmp_path, client):
        """GET returns notes in the new order after reorder."""
        r1 = client.post("/api/notes", json={"title": "First", "content": ""}).get_json()
        r2 = client.post("/api/notes", json={"title": "Second", "content": ""}).get_json()

        client.post("/api/notes/reorder", json={"order": [r2["id"], r1["id"]]})

        notes = client.get("/api/notes").get_json()
        assert notes[0]["title"] == "Second"
        assert notes[1]["title"] == "First"


# --- Migration from notes.txt ---


class TestMigration:
    def test_migration_from_notes_txt(self, tmp_path, client):
        """If notes.txt exists and notes.json doesn't, creates 'Old Notes' card."""
        (tmp_path / "notes.txt").write_text("Old notes content here")
        resp = client.get("/api/notes")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["title"] == "Old Notes"
        assert data[0]["content"] == "Old notes content here"
        assert (tmp_path / "notes.json").exists()

    def test_no_migration_if_notes_json_exists(self, tmp_path, client):
        """Existing notes.json is not overwritten by migration."""
        existing = [{"id": "existing", "title": "Keep me", "content": "",
                     "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
                     "assigned_project": None, "order_index": 0}]
        (tmp_path / "notes.json").write_text(json.dumps(existing))
        (tmp_path / "notes.txt").write_text("Should be ignored")
        resp = client.get("/api/notes")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["title"] == "Keep me"

    def test_no_migration_if_notes_txt_empty(self, tmp_path, client):
        """Empty notes.txt does not trigger migration."""
        (tmp_path / "notes.txt").write_text("   \n  ")
        resp = client.get("/api/notes")
        assert resp.get_json() == []
        assert not (tmp_path / "notes.json").exists()

    def test_no_migration_if_no_notes_txt(self, tmp_path, client):
        """No notes.txt and no notes.json returns empty list."""
        resp = client.get("/api/notes")
        assert resp.get_json() == []


# --- Confluence sync: notes rendering ---


def _empty_sections():
    """Minimal sections dict for generate_confluence_content calls."""
    return {
        "PROJECTS": [],
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


class TestConfluenceNotesRendering:
    """Test that generate_confluence_content renders notes from notes.json."""

    def test_notes_rendered_as_h3_and_p(self, app, tmp_path):
        """Notes with title and content produce <h3> and <p> elements."""
        notes = [
            {"id": "n1", "title": "Meeting Notes", "content": "Discussed roadmap",
             "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
             "assigned_project": None, "order_index": 0},
            {"id": "n2", "title": "Ideas", "content": "Build a widget",
             "created_at": "2026-01-02T00:00:00", "updated_at": "2026-01-02T00:00:00",
             "assigned_project": None, "order_index": 1},
        ]
        (tmp_path / "notes.json").write_text(json.dumps(notes))

        html = crumbwise.generate_confluence_content(_empty_sections())

        assert "<h2>NOTES</h2>" in html
        assert "<h3>Meeting Notes</h3>" in html
        assert "<p>Discussed roadmap</p>" in html
        assert "<h3>Ideas</h3>" in html
        assert "<p>Build a widget</p>" in html

    def test_empty_notes_renders_no_notes_placeholder(self, app, tmp_path):
        """When notes.json is empty list, renders '(no notes)' placeholder."""
        (tmp_path / "notes.json").write_text(json.dumps([]))

        html = crumbwise.generate_confluence_content(_empty_sections())

        assert "<h2>NOTES</h2>" in html
        assert "(no notes)" in html

    def test_no_notes_file_renders_no_notes_placeholder(self, app, tmp_path):
        """When notes.json does not exist, renders '(no notes)' placeholder."""
        # Ensure no notes.json or notes.txt exist
        assert not (tmp_path / "notes.json").exists()

        html = crumbwise.generate_confluence_content(_empty_sections())

        assert "<h2>NOTES</h2>" in html
        assert "(no notes)" in html

    def test_urls_in_note_title_are_linkified(self, app, tmp_path):
        """URLs in note titles are converted to anchor tags."""
        notes = [
            {"id": "n1", "title": "See https://example.com/page for details",
             "content": "", "created_at": "2026-01-01T00:00:00",
             "updated_at": "2026-01-01T00:00:00",
             "assigned_project": None, "order_index": 0},
        ]
        (tmp_path / "notes.json").write_text(json.dumps(notes))

        html = crumbwise.generate_confluence_content(_empty_sections())

        assert '<a href="https://example.com/page">https://example.com/page</a>' in html
        # The linkified URL should be inside an h3
        assert "<h3>See " in html

    def test_urls_in_note_content_are_linkified(self, app, tmp_path):
        """URLs in note content are converted to anchor tags."""
        notes = [
            {"id": "n1", "title": "Links", "content": "Check https://docs.example.com/api",
             "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
             "assigned_project": None, "order_index": 0},
        ]
        (tmp_path / "notes.json").write_text(json.dumps(notes))

        html = crumbwise.generate_confluence_content(_empty_sections())

        assert '<a href="https://docs.example.com/api">https://docs.example.com/api</a>' in html

    def test_note_content_newlines_become_br(self, app, tmp_path):
        """Newlines in note content are converted to <br/> tags."""
        notes = [
            {"id": "n1", "title": "Multi-line", "content": "Line one\nLine two\nLine three",
             "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
             "assigned_project": None, "order_index": 0},
        ]
        (tmp_path / "notes.json").write_text(json.dumps(notes))

        html = crumbwise.generate_confluence_content(_empty_sections())

        assert "Line one<br/>Line two<br/>Line three" in html

    def test_notes_ordered_by_order_index(self, app, tmp_path):
        """Notes in Confluence output respect order_index sorting."""
        notes = [
            {"id": "n2", "title": "Second", "content": "",
             "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
             "assigned_project": None, "order_index": 1},
            {"id": "n1", "title": "First", "content": "",
             "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
             "assigned_project": None, "order_index": 0},
        ]
        (tmp_path / "notes.json").write_text(json.dumps(notes))

        html = crumbwise.generate_confluence_content(_empty_sections())

        first_pos = html.index("<h3>First</h3>")
        second_pos = html.index("<h3>Second</h3>")
        assert first_pos < second_pos

    def test_note_without_content_omits_p_tag(self, app, tmp_path):
        """A note with empty content does not produce a <p> tag."""
        notes = [
            {"id": "n1", "title": "Title Only", "content": "",
             "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
             "assigned_project": None, "order_index": 0},
        ]
        (tmp_path / "notes.json").write_text(json.dumps(notes))

        html = crumbwise.generate_confluence_content(_empty_sections())

        assert "<h3>Title Only</h3>" in html
        # There should be no <p> immediately after this note's h3
        # (the next element should be another h3, h2, hr, or end of string)
        notes_section = html[html.index("<h2>NOTES</h2>"):]
        h3_end = notes_section.index("</h3>") + len("</h3>")
        after_h3 = notes_section[h3_end:].strip()
        assert not after_h3.startswith("<p>")
