#!/usr/bin/env python3
"""Crumbwise - Local task management with a visual board UI."""

import os
import re
import uuid
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, request


def get_current_quarter():
    """Get the current quarter string like 'DONE Q1 2026'.

    Based on the most recent Friday (including today if it's Friday).
    This ensures weekly tasks are attributed to the correct quarter
    even when clicking New Week on a Monday after quarter end.
    """
    today = datetime.now().date()
    # Friday is weekday 4 (Monday=0, Sunday=6)
    days_since_friday = (today.weekday() - 4) % 7
    most_recent_friday = today - timedelta(days=days_since_friday)
    quarter = (most_recent_friday.month - 1) // 3 + 1
    return f"DONE Q{quarter} {most_recent_friday.year}"


def get_week_dates():
    """Get Monday-Friday date ranges for this week, next week, and following week.

    Returns a dict with formatted date ranges like 'Jan 27 - Jan 31'.
    """
    today = datetime.now().date()
    # Monday is weekday 0
    days_since_monday = today.weekday()
    this_monday = today - timedelta(days=days_since_monday)

    def format_week(monday):
        friday = monday + timedelta(days=4)
        # Format: "Jan 27 - Jan 31" or "Jan 27 - Feb 2" if crossing months
        mon_str = monday.strftime("%b %d").replace(" 0", " ")
        fri_str = friday.strftime("%b %d").replace(" 0", " ")
        # If same month, could shorten, but keeping full format for clarity
        return f"{mon_str} - {fri_str}"

    return {
        "TODO THIS WEEK": format_week(this_monday),
        "TODO NEXT WEEK": format_week(this_monday + timedelta(days=7)),
        "TODO FOLLOWING WEEK": format_week(this_monday + timedelta(days=14)),
    }

app = Flask(__name__)

DATA_DIR = Path(__file__).parent / "data"
TASKS_FILE = DATA_DIR / "tasks.md"
UNDO_FILE = DATA_DIR / "tasks.md.undo"
SETTINGS_FILE = DATA_DIR / "settings.json"
NOTES_FILE = DATA_DIR / "notes.txt"


def load_settings():
    """Load settings from JSON file."""
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text())
    return {}


def save_settings(settings):
    """Save settings to JSON file."""
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))


def clear_undo():
    """Clear undo file after any task modification."""
    if UNDO_FILE.exists():
        UNDO_FILE.unlink()


# Section definitions with display order and tab grouping
# Current tab flow: Week After Next -> Next Week -> This Week -> In Progress -> Done This Week
SECTIONS = {
    "TODO FOLLOWING WEEK": {"tab": "current", "order": 0},
    "TODO NEXT WEEK": {"tab": "current", "order": 1},
    "TODO THIS WEEK": {"tab": "current", "order": 2},
    "IN PROGRESS TODAY": {"tab": "current", "order": 3},
    "DONE THIS WEEK": {"tab": "current", "order": 4},
    "BIG ONGOING PROJECTS": {"tab": "current", "order": 0, "area": "secondary"},
    "FOLLOW UPS": {"tab": "current", "order": 1, "area": "secondary"},
    "BLOCKED": {"tab": "current", "order": 2, "area": "secondary"},
    "PROBLEMS TO SOLVE": {"tab": "research", "order": 1},
    "THINGS TO RESEARCH": {"tab": "research", "order": 2},
    "RESEARCH IN PROGRESS": {"tab": "research", "order": 3},
    "RESEARCH DONE": {"tab": "research", "order": 4},
    "BACKLOG HIGH PRIORITY": {"tab": "backlog", "order": 0},
    "BACKLOG MEDIUM PRIORITY": {"tab": "backlog", "order": 1},
    "BACKLOG LOW PRIORITY": {"tab": "backlog", "order": 2},
    "DONE 2025": {"tab": "history", "order": 100},  # High order so current quarters come first
}


def get_dynamic_sections():
    """Get SECTIONS dict with current quarter added dynamically."""
    sections = SECTIONS.copy()
    current_q = get_current_quarter()
    if current_q not in sections:
        sections[current_q] = {"tab": "history", "order": 0}
    return sections


def ensure_data_file():
    """Create the data file with default sections if it doesn't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not TASKS_FILE.exists():
        content = []
        for section in sorted(SECTIONS.keys(), key=lambda s: (SECTIONS[s]["tab"], SECTIONS[s]["order"])):
            content.append(f"## {section}\n\n")
        TASKS_FILE.write_text("\n".join(content))


def parse_tasks():
    """Parse the markdown file into a structured dict."""
    ensure_data_file()
    content = TASKS_FILE.read_text()

    sections = {}
    current_section = None
    current_tasks = []

    for line in content.split("\n"):
        # Check for section header
        header_match = re.match(r"^## (.+)$", line)
        if header_match:
            # Save previous section
            if current_section:
                sections[current_section] = current_tasks
            current_section = header_match.group(1).strip()
            current_tasks = []
            continue

        # Check for task item
        task_match = re.match(r"^- \[([ xX])\] (.+)$", line)
        if task_match and current_section:
            completed = task_match.group(1).lower() == "x"
            text = task_match.group(2).strip()
            # Generate a stable ID from content (or use existing if we add ID support later)
            task_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{current_section}:{text}"))
            current_tasks.append({
                "id": task_id,
                "text": text,
                "completed": completed,
            })

    # Save last section
    if current_section:
        sections[current_section] = current_tasks

    # Ensure all defined sections exist (including dynamic current quarter)
    for section in get_dynamic_sections():
        if section not in sections:
            sections[section] = []

    return sections


def save_tasks(sections):
    """Save the structured dict back to markdown."""
    lines = []

    # Sort sections by tab and order (using dynamic sections)
    dynamic_sections = get_dynamic_sections()

    # Also include any sections in the data that aren't in our config (old quarters)
    all_section_names = set(dynamic_sections.keys()) | set(sections.keys())

    def section_sort_key(s):
        if s in dynamic_sections:
            return (dynamic_sections[s]["tab"], dynamic_sections[s]["order"])
        # Old quarter sections go to history tab, sorted by name (descending for newest first)
        if s.startswith("DONE Q"):
            return ("history", 50, s)
        return ("zzz", 0, s)  # Unknown sections at end

    sorted_sections = sorted(all_section_names, key=section_sort_key)

    for section in sorted_sections:
        lines.append(f"## {section}")
        lines.append("")

        tasks = sections.get(section, [])
        for task in tasks:
            checkbox = "x" if task.get("completed") else " "
            lines.append(f"- [{checkbox}] {task['text']}")

        lines.append("")

    TASKS_FILE.write_text("\n".join(lines))


@app.route("/")
def index():
    """Serve the main UI."""
    return render_template("index.html")


@app.route("/api/sections")
def get_sections():
    """Get section metadata including dynamic current quarter."""
    return jsonify(get_dynamic_sections())


@app.route("/api/current-quarter")
def get_current_quarter_api():
    """Get the current quarter string."""
    return jsonify({"quarter": get_current_quarter()})


@app.route("/api/week-dates")
def get_week_dates_api():
    """Get Monday-Friday date ranges for TODO week sections."""
    return jsonify(get_week_dates())


@app.route("/api/tasks")
def get_tasks():
    """Get all tasks organized by section."""
    sections = parse_tasks()
    return jsonify(sections)


@app.route("/api/tasks", methods=["POST"])
def add_task():
    """Add a new task to a section."""
    data = request.json
    section = data.get("section")
    text = data.get("text", "").strip()

    dynamic_sections = get_dynamic_sections()
    if not section or (section not in dynamic_sections and not section.startswith("DONE Q")):
        return jsonify({"error": "Invalid section"}), 400
    if not text:
        return jsonify({"error": "Task text required"}), 400

    sections = parse_tasks()
    task_id = str(uuid.uuid4())
    new_task = {
        "id": task_id,
        "text": text,
        "completed": False,
    }
    sections[section].append(new_task)
    save_tasks(sections)
    clear_undo()

    return jsonify(new_task), 201


@app.route("/api/tasks/<task_id>", methods=["PUT"])
def update_task(task_id):
    """Update a task's text or move it to a different section."""
    data = request.json
    new_text = data.get("text")
    new_section = data.get("section")

    sections = parse_tasks()

    # Find the task
    found_task = None
    found_section = None
    for section, tasks in sections.items():
        for task in tasks:
            if task["id"] == task_id:
                found_task = task
                found_section = section
                break
        if found_task:
            break

    if not found_task:
        return jsonify({"error": "Task not found"}), 404

    # Update text if provided
    if new_text is not None:
        found_task["text"] = new_text.strip()

    # Move to new section if provided
    if new_section and new_section != found_section:
        dynamic_sections = get_dynamic_sections()
        if new_section not in dynamic_sections and not new_section.startswith("DONE Q"):
            return jsonify({"error": "Invalid section"}), 400
        sections[found_section].remove(found_task)
        sections[new_section].append(found_task)

    save_tasks(sections)
    clear_undo()
    return jsonify(found_task)


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    """Delete a task."""
    sections = parse_tasks()

    for section, tasks in sections.items():
        for task in tasks:
            if task["id"] == task_id:
                tasks.remove(task)
                save_tasks(sections)
                clear_undo()
                return jsonify({"success": True})

    return jsonify({"error": "Task not found"}), 404


@app.route("/api/tasks/<task_id>/complete", methods=["POST"])
def toggle_complete(task_id):
    """Toggle task completion status."""
    sections = parse_tasks()

    for section, tasks in sections.items():
        for task in tasks:
            if task["id"] == task_id:
                task["completed"] = not task["completed"]
                save_tasks(sections)
                clear_undo()
                return jsonify(task)

    return jsonify({"error": "Task not found"}), 404


@app.route("/api/tasks/reorder", methods=["POST"])
def reorder_tasks():
    """Reorder tasks within or between sections."""
    data = request.json
    task_id = data.get("taskId")
    target_section = data.get("section")
    target_index = data.get("index", 0)

    if not task_id or not target_section:
        return jsonify({"error": "taskId and section required"}), 400
    dynamic_sections = get_dynamic_sections()
    if target_section not in dynamic_sections and not target_section.startswith("DONE Q"):
        return jsonify({"error": "Invalid section"}), 400

    sections = parse_tasks()

    # Find and remove the task from its current location
    found_task = None
    for section, tasks in sections.items():
        for task in tasks:
            if task["id"] == task_id:
                found_task = task
                tasks.remove(task)
                break
        if found_task:
            break

    if not found_task:
        return jsonify({"error": "Task not found"}), 404

    # Insert at new position
    target_index = min(target_index, len(sections[target_section]))
    sections[target_section].insert(target_index, found_task)

    save_tasks(sections)
    clear_undo()
    return jsonify({"success": True})


@app.route("/api/new-week", methods=["POST"])
def new_week():
    """Advance to a new week: move done items to history, shift weekly columns."""
    # Save current state for undo
    current_content = TASKS_FILE.read_text()
    UNDO_FILE.write_text(current_content)

    sections = parse_tasks()

    # Move DONE THIS WEEK items to current quarter (e.g., DONE Q1 2026)
    current_quarter = get_current_quarter()
    done_this_week = sections.get("DONE THIS WEEK", [])
    current_quarter_tasks = sections.get(current_quarter, [])
    sections[current_quarter] = current_quarter_tasks + done_this_week
    sections["DONE THIS WEEK"] = []

    # Shift weekly items:
    # TODO NEXT WEEK -> TODO THIS WEEK (preserving existing items)
    # TODO FOLLOWING WEEK -> TODO NEXT WEEK
    this_week = sections.get("TODO THIS WEEK", [])
    next_week = sections.get("TODO NEXT WEEK", [])
    following_week = sections.get("TODO FOLLOWING WEEK", [])

    sections["TODO THIS WEEK"] = this_week + next_week
    sections["TODO NEXT WEEK"] = following_week
    sections["TODO FOLLOWING WEEK"] = []

    save_tasks(sections)
    return jsonify({"success": True, "canUndo": True})


@app.route("/api/undo-new-week", methods=["POST"])
def undo_new_week():
    """Undo the last new week operation."""
    if not UNDO_FILE.exists():
        return jsonify({"error": "No undo data available"}), 400

    # Restore from undo file
    undo_content = UNDO_FILE.read_text()
    TASKS_FILE.write_text(undo_content)

    # Remove undo file
    UNDO_FILE.unlink()

    return jsonify({"success": True})


@app.route("/api/can-undo")
def can_undo():
    """Check if undo is available."""
    return jsonify({"canUndo": UNDO_FILE.exists()})


@app.route("/api/settings", methods=["GET"])
def get_settings():
    """Get current settings."""
    settings = load_settings()
    # Don't expose the full API token, just indicate if it's set
    if settings.get("confluence_token"):
        settings["confluence_token_set"] = True
        settings["confluence_token"] = ""  # Don't send actual token
    return jsonify(settings)


@app.route("/api/settings", methods=["POST"])
def update_settings():
    """Update settings."""
    data = request.json
    settings = load_settings()

    if "confluence_url" in data:
        settings["confluence_url"] = data["confluence_url"]

    if "confluence_email" in data:
        settings["confluence_email"] = data["confluence_email"]

    # Only update token if a new one is provided
    if data.get("confluence_token"):
        settings["confluence_token"] = data["confluence_token"]

    save_settings(settings)
    return jsonify({"success": True})


@app.route("/api/notes", methods=["GET"])
def get_notes():
    """Get the notes content."""
    if NOTES_FILE.exists():
        return jsonify({"notes": NOTES_FILE.read_text()})
    return jsonify({"notes": ""})


@app.route("/api/notes", methods=["POST"])
def save_notes():
    """Save the notes content."""
    data = request.json
    notes = data.get("notes", "")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_FILE.write_text(notes)
    return jsonify({"success": True})


def extract_confluence_page_id(url):
    """Extract page ID from various Confluence URL formats."""
    import re
    # Try edit-v2 format: /pages/edit-v2/1597734939
    match = re.search(r'/pages/edit-v2/(\d+)', url)
    if match:
        return match.group(1)
    # Try viewpage format: /pages/viewpage.action?pageId=1597734939
    match = re.search(r'pageId=(\d+)', url)
    if match:
        return match.group(1)
    # Try direct page format: /pages/1597734939
    match = re.search(r'/pages/(\d+)', url)
    if match:
        return match.group(1)
    return None


def extract_confluence_base_url(url):
    """Extract base URL from Confluence URL."""
    import re
    match = re.match(r'(https://[^/]+)', url)
    if match:
        return match.group(1)
    return None


def generate_confluence_content(sections):
    """Generate Confluence storage format HTML from tasks."""
    html_parts = []

    # Define the order matching the user's original Confluence format
    section_order = [
        ("DONE THIS WEEK", "DONE THIS WEEK"),
        ("PROBLEMS TO SOLVE", "PROBLEMS TO SOLVE"),
        ("THINGS TO RESEARCH", "THINGS TO RESEARCH"),
        ("BIG ONGOING PROJECTS", "BIG ONGOING PROJECTS"),
        ("FOLLOW UPS", "FOLLOW UPS"),
        ("BLOCKED", "BLOCKED"),
        ("IN PROGRESS TODAY", "IN PROGRESS TODAY"),
        ("TODO THIS WEEK", "TODO THIS WEEK"),
        ("TODO NEXT WEEK", "TODO NEXT WEEK"),
        ("TODO FOLLOWING WEEK", "TODO FOLLOWING WEEK"),
        ("BACKLOG HIGH PRIORITY", "BACKLOG HIGH PRIORITY"),
        ("BACKLOG MEDIUM PRIORITY", "BACKLOG MEDIUM PRIORITY"),
        ("BACKLOG LOW PRIORITY", "BACKLOG LOW PRIORITY"),
    ]

    # Add current quarter
    current_q = get_current_quarter()
    section_order.append((current_q, current_q))

    # Add DONE 2025 if it exists
    if "DONE 2025" in sections:
        section_order.append(("DONE 2025", "DONE 2025"))

    for section_key, section_title in section_order:
        tasks = sections.get(section_key, [])
        html_parts.append(f'<h2>{section_title}</h2>')

        if tasks:
            html_parts.append('<ul>')
            for task in tasks:
                text = task['text']
                # Convert URLs to links
                text = re.sub(
                    r'(https?://[^\s]+)',
                    r'<a href="\1">\1</a>',
                    text
                )
                html_parts.append(f'<li>{text}</li>')
            html_parts.append('</ul>')
        else:
            html_parts.append('<p><em>(empty)</em></p>')

    # Add notes section at the end
    notes = ""
    if NOTES_FILE.exists():
        notes = NOTES_FILE.read_text().strip()
    html_parts.append('<h2>NOTES</h2>')
    if notes:
        # Convert newlines to <br/> and URLs to links
        notes_html = re.sub(
            r'(https?://[^\s]+)',
            r'<a href="\1">\1</a>',
            notes
        )
        notes_html = notes_html.replace('\n', '<br/>')
        html_parts.append(f'<p>{notes_html}</p>')
    else:
        html_parts.append('<p><em>(empty)</em></p>')

    return '\n'.join(html_parts)


@app.route("/api/sync-confluence", methods=["POST"])
def sync_confluence():
    """Sync current tasks to Confluence page."""
    settings = load_settings()

    confluence_url = settings.get("confluence_url")
    confluence_email = settings.get("confluence_email")
    confluence_token = settings.get("confluence_token")

    if not all([confluence_url, confluence_email, confluence_token]):
        return jsonify({"error": "Confluence settings not configured"}), 400

    page_id = extract_confluence_page_id(confluence_url)
    base_url = extract_confluence_base_url(confluence_url)

    if not page_id or not base_url:
        return jsonify({"error": "Could not parse Confluence URL"}), 400

    # Get current page to get version number
    api_url = f"{base_url}/wiki/api/v2/pages/{page_id}"

    auth = (confluence_email, confluence_token)

    try:
        # Get current page version
        response = requests.get(
            api_url,
            auth=auth,
            headers={"Accept": "application/json"}
        )

        if response.status_code != 200:
            return jsonify({
                "error": f"Failed to get page: {response.status_code}",
                "details": response.text
            }), 400

        page_data = response.json()
        current_version = page_data.get("version", {}).get("number", 1)
        page_title = page_data.get("title", "Crumbwise Export")

        # Generate new content
        sections = parse_tasks()
        new_content = generate_confluence_content(sections)

        # Update the page
        update_data = {
            "id": page_id,
            "status": "current",
            "title": page_title,
            "body": {
                "representation": "storage",
                "value": new_content
            },
            "version": {
                "number": current_version + 1
            }
        }

        response = requests.put(
            api_url,
            auth=auth,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json"
            },
            json=update_data
        )

        if response.status_code == 200:
            return jsonify({"success": True, "message": "Confluence page updated"})
        else:
            return jsonify({
                "error": f"Failed to update page: {response.status_code}",
                "details": response.text
            }), 400

    except requests.RequestException as e:
        return jsonify({"error": f"Request failed: {str(e)}"}), 500


if __name__ == "__main__":
    ensure_data_file()
    print("Starting Crumbwise on http://localhost:5050")
    app.run(debug=True, port=5050)
