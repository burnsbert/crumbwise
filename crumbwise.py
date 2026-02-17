#!/usr/bin/env python3
"""Crumbwise - Local task management with a visual board UI."""

import os
import re
import uuid
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, request, redirect

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


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
    "PROJECTS": {"tab": "current", "order": 0, "area": "secondary", "locked": True},
    "FOLLOW UPS": {"tab": "current", "order": 1, "area": "secondary"},
    "BLOCKED": {"tab": "current", "order": 2, "area": "secondary"},
    "PROBLEMS TO SOLVE": {"tab": "research", "order": 1},
    "THINGS TO RESEARCH": {"tab": "research", "order": 2},
    "RESEARCH IN PROGRESS": {"tab": "research", "order": 3},
    "RESEARCH DONE": {"tab": "research", "order": 4},
    "BACKLOG HIGH PRIORITY": {"tab": "backlog", "order": 0},
    "BACKLOG MEDIUM PRIORITY": {"tab": "backlog", "order": 1},
    "BACKLOG LOW PRIORITY": {"tab": "backlog", "order": 2},
    "COMPLETED PROJECTS": {"tab": "history", "order": 99},  # Before yearly done sections
    "DONE 2025": {"tab": "history", "order": 100},  # High order so current quarters come first
}

# Sections that use project metadata (color_index)
PROJECT_SECTIONS = ["PROJECTS", "COMPLETED PROJECTS"]

# Section classifications for timestamp lifecycle
IN_PROGRESS_SECTIONS = ["IN PROGRESS TODAY"]
CLEARS_IN_PROGRESS_SECTIONS = [
    "TODO THIS WEEK",
    "TODO NEXT WEEK",
    "TODO FOLLOWING WEEK",
    "BACKLOG HIGH PRIORITY",
    "BACKLOG MEDIUM PRIORITY",
    "BACKLOG LOW PRIORITY"
]

# Sections for timeline blocked state tracking
BLOCKED_SECTIONS = ["BLOCKED"]

# Sections representing done/completed state
# Note: dynamically includes current quarter (e.g., "DONE Q1 2026") and yearly sections (e.g., "DONE 2025")
DONE_SECTIONS = ["DONE THIS WEEK"]

# Sections in the research tab (excluded from timeline tracking)
RESEARCH_SECTIONS = [
    "PROBLEMS TO SOLVE",
    "THINGS TO RESEARCH",
    "RESEARCH IN PROGRESS",
    "RESEARCH DONE"
]


def now_iso():
    """Return current datetime as ISO string with seconds precision."""
    return datetime.now().isoformat(timespec='seconds')


def set_timestamps(task, skip_updated=False, **kwargs):
    """
    Set timestamp fields on a task dict.

    Args:
        task: Task dictionary to update
        skip_updated: If True, don't set 'updated' timestamp
        **kwargs: Timestamp fields to set (created, updated, in_progress, completed_at)
                 Values should be ISO strings or None

    Always sets 'updated' to current time unless skip_updated=True.
    Use completed_at (not completed) to avoid collision with boolean checkbox state.
    """
    # Set explicitly provided timestamps
    for key, value in kwargs.items():
        task[key] = value

    # Always set updated unless told not to
    if not skip_updated:
        task['updated'] = now_iso()


def get_dynamic_sections():
    """Get SECTIONS dict with current quarter added dynamically."""
    sections = SECTIONS.copy()
    current_q = get_current_quarter()
    if current_q not in sections:
        sections[current_q] = {"tab": "history", "order": 0}
    return sections


def is_done_section(section_name):
    """Check if a section name represents a 'done' state.

    Returns True if the section is a done/completed section:
    - Explicitly listed in DONE_SECTIONS constant, OR
    - Starts with "DONE Q" (quarterly sections like "DONE Q1 2026"), OR
    - Starts with "DONE 20" (yearly sections like "DONE 2025", "DONE 2026")

    Returns False for all other sections, including "RESEARCH DONE".

    Args:
        section_name: Name of the section to check

    Returns:
        bool: True if section represents a done state, False otherwise
    """
    # Check against DONE_SECTIONS list
    if section_name in DONE_SECTIONS:
        return True

    # Check for quarterly done sections (e.g., "DONE Q1 2026")
    if section_name.startswith("DONE Q"):
        return True

    # Check for yearly done sections (e.g., "DONE 2025", "DONE 2026")
    if section_name.startswith("DONE 20"):
        return True

    return False


def handle_section_transition(task, source_section, target_section):
    """Handle timestamp lifecycle and history tracking for section transitions.

    This is the central function for managing task state changes when moving
    between sections. It handles:
    - Setting/clearing in_progress, blocked_at, completed_at timestamps
    - Appending history entries for status changes
    - Research section exclusion (no tracking for research tasks)

    History format: pipe-delimited entries like "ip@2026-02-10T09:00:00|bl@2026-02-12T14:00:00"
    History prefixes:
    - ip@ = moved to in-progress
    - op@ = moved back to todo/backlog (opened)
    - bl@ = moved to blocked
    - co@ = completed

    Args:
        task: Task dictionary to update (modified in-place)
        source_section: Section the task is moving from
        target_section: Section the task is moving to

    Behavioral changes from previous implementation:
    - Moving to BLOCKED now clears in_progress (previously had no effect)
    - Moving to done sections now sets completed_at (previously only via checkbox)
    - All transitions now append history entries
    """
    # Skip history/blocked_at tracking for research section tasks (user decision #5)
    if source_section in RESEARCH_SECTIONS:
        return

    # Helper to append history entry
    def append_history(prefix):
        timestamp = now_iso()
        entry = f"{prefix}@{timestamp}"
        if task.get("history"):
            task["history"] = f"{task['history']}|{entry}"
        else:
            task["history"] = entry

    # (a) Moving to IN_PROGRESS_SECTIONS
    if target_section in IN_PROGRESS_SECTIONS:
        # Set in_progress if not already set (preserve original start time)
        if not task.get("in_progress"):
            task["in_progress"] = now_iso()
        # Clear blocked_at
        task["blocked_at"] = None
        # Append ip@ to history
        append_history("ip")

    # (b) Moving to CLEARS_IN_PROGRESS_SECTIONS
    elif target_section in CLEARS_IN_PROGRESS_SECTIONS:
        # Clear in_progress
        task["in_progress"] = None
        # Clear blocked_at
        task["blocked_at"] = None
        # Clear completed_at if moving from a done section
        if is_done_section(source_section):
            task["completed_at"] = None
        # Append op@ to history
        append_history("op")

    # (c) Moving to BLOCKED_SECTIONS
    elif target_section in BLOCKED_SECTIONS:
        # Set blocked_at
        task["blocked_at"] = now_iso()
        # Clear in_progress (IMPORTANT behavioral change)
        task["in_progress"] = None
        # Append bl@ to history
        append_history("bl")

    # (d) Moving to done sections
    elif is_done_section(target_section):
        # Set completed_at
        task["completed_at"] = now_iso()
        # Clear in_progress
        task["in_progress"] = None
        # Clear blocked_at
        task["blocked_at"] = None
        # Append co@ to history
        append_history("co")


def migrate_section_renames():
    """Migrate renamed sections in existing tasks file."""
    if not TASKS_FILE.exists():
        return

    renames = {
        "BIG ONGOING PROJECTS": "PROJECTS",
    }

    content = TASKS_FILE.read_text()
    modified = False

    for old_name, new_name in renames.items():
        old_header = f"## {old_name}"
        new_header = f"## {new_name}"
        if old_header in content:
            content = content.replace(old_header, new_header)
            modified = True

    if modified:
        TASKS_FILE.write_text(content)


def ensure_data_file():
    """Create the data file with default sections if it doesn't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not TASKS_FILE.exists():
        content = []
        for section in sorted(SECTIONS.keys(), key=lambda s: (SECTIONS[s]["tab"], SECTIONS[s]["order"])):
            content.append(f"## {section}\n\n")
        TASKS_FILE.write_text("\n".join(content))
    else:
        migrate_section_renames()


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

        # Check for task item - extract metadata if present
        # Format: - [ ] Task text <!-- id:uuid [project:N] [assigned:uuid] -->
        # Legacy format (no id): - [ ] Task text <!-- project:N --> or <!-- assigned:uuid -->
        task_match = re.match(r"^- \[([ xX])\] (.+?)(?:\s*<!--\s*(.+?)\s*-->)?$", line)
        if task_match and current_section:
            completed = task_match.group(1).lower() == "x"
            text = task_match.group(2).strip()
            meta_str = task_match.group(3) or ""

            # Parse metadata key:value pairs
            meta = {}
            for m in re.finditer(r"(\w+):([^\s]+)", meta_str):
                meta[m.group(1)] = m.group(2)

            # Get or generate task ID
            task_id = meta.get("id")
            if not task_id:
                # Generate new ID for legacy tasks without one
                task_id = str(uuid.uuid4())

            task = {
                "id": task_id,
                "text": text,
                "completed": completed,
            }

            # Add color_index for project sections
            if current_section in PROJECT_SECTIONS and "project" in meta:
                task["color_index"] = int(meta["project"])

            # Add assigned_project for tasks linked to a project
            if "assigned" in meta:
                task["assigned_project"] = meta["assigned"]

            # Add timestamp metadata fields
            task["created"] = meta.get("created")
            task["updated"] = meta.get("updated")
            task["in_progress"] = meta.get("in_progress")
            task["completed_at"] = meta.get("completed_at")
            task["blocked_at"] = meta.get("blocked_at")
            task["history"] = meta.get("history")

            # Add order_index field if present (convert to int)
            oi = meta.get("order_index")
            task["order_index"] = int(oi) if oi is not None else None

            current_tasks.append(task)

    # Save last section
    if current_section:
        sections[current_section] = current_tasks

    # Ensure all defined sections exist (including dynamic current quarter)
    for section in get_dynamic_sections():
        if section not in sections:
            sections[section] = []

    # Migrate projects without color_index
    migrate_project_colors(sections)

    # Fix any orphaned project assignments (from uuid5->uuid4 ID change)
    migrate_orphaned_assignments(sections)

    return sections


def get_next_project_color(sections):
    """Get the best available project color using smart assignment.

    Priority:
    1. First unclaimed color (1-10) across all projects
    2. Color not used by any active (non-completed) project
    3. Color with fewest active project claimants
    """
    # Gather all used colors and active project colors
    all_used_colors = set()
    active_color_counts = {}  # color -> count of active projects using it

    for section_name in PROJECT_SECTIONS:
        is_active = section_name == "PROJECTS"
        for task in sections.get(section_name, []):
            color = task.get("color_index")
            if color:
                all_used_colors.add(color)
                if is_active:
                    active_color_counts[color] = active_color_counts.get(color, 0) + 1

    # Priority 1: Find first unclaimed color
    for i in range(1, 17):
        if i not in all_used_colors:
            return i

    # Priority 2: Find color not used by active projects
    for i in range(1, 17):
        if i not in active_color_counts:
            return i

    # Priority 3: Find color with fewest active claimants
    min_count = min(active_color_counts.values())
    for i in range(1, 17):
        if active_color_counts.get(i, 0) == min_count:
            return i

    return 1  # Fallback


def migrate_project_colors(sections):
    """Assign color indices to projects that don't have one."""
    needs_save = False

    for section_name in PROJECT_SECTIONS:
        if section_name not in sections:
            continue

        for task in sections[section_name]:
            if "color_index" not in task:
                task["color_index"] = get_next_project_color(sections)
                needs_save = True

    if needs_save:
        save_tasks(sections)


def migrate_orphaned_assignments(sections):
    """Fix task assignments that point to old uuid5-based project IDs.

    When task ID generation changed from uuid5 to uuid4, project IDs changed
    but task assignments still pointed to the old IDs. This migration:
    1. Builds a mapping from old uuid5 IDs to current project IDs
    2. Updates any orphaned assignments to use the current project ID
    """
    # Build set of valid (current) project IDs
    valid_project_ids = set()
    # Build mapping from project text to current ID
    project_text_to_id = {}

    for section_name in PROJECT_SECTIONS:
        for project in sections.get(section_name, []):
            valid_project_ids.add(project["id"])
            project_text_to_id[project["text"]] = project["id"]

    # Build mapping from old uuid5 IDs to current project IDs
    old_to_new_id = {}
    for project_text, current_id in project_text_to_id.items():
        # Generate what the old uuid5-based ID would have been
        for section_name in PROJECT_SECTIONS:
            old_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{section_name}:{project_text}"))
            if old_id != current_id:  # Only map if different
                old_to_new_id[old_id] = current_id

    # Find and fix orphaned assignments
    needs_save = False
    for section_name, tasks in sections.items():
        if section_name in PROJECT_SECTIONS:
            continue  # Projects don't have assignments

        for task in tasks:
            assigned = task.get("assigned_project")
            if assigned and assigned not in valid_project_ids:
                # This is an orphaned assignment - try to fix it
                if assigned in old_to_new_id:
                    task["assigned_project"] = old_to_new_id[assigned]
                    needs_save = True

    if needs_save:
        save_tasks(sections)


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
            line = f"- [{checkbox}] {task['text']}"

            # Build metadata comment with id and optional project/assigned
            meta_parts = [f"id:{task['id']}"]
            if section in PROJECT_SECTIONS and task.get("color_index"):
                meta_parts.append(f"project:{task['color_index']}")
            elif task.get("assigned_project"):
                meta_parts.append(f"assigned:{task['assigned_project']}")

            # Add timestamp metadata fields if present
            if task.get("created"):
                meta_parts.append(f"created:{task['created']}")
            if task.get("updated"):
                meta_parts.append(f"updated:{task['updated']}")
            if task.get("in_progress"):
                meta_parts.append(f"in_progress:{task['in_progress']}")
            if task.get("completed_at"):
                meta_parts.append(f"completed_at:{task['completed_at']}")
            if task.get("blocked_at"):
                meta_parts.append(f"blocked_at:{task['blocked_at']}")
            if task.get("history"):
                meta_parts.append(f"history:{task['history']}")

            # Add order_index if present
            if task.get("order_index") is not None:
                meta_parts.append(f"order_index:{task['order_index']}")

            line += f" <!-- {' '.join(meta_parts)} -->"
            lines.append(line)

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

    # Set timestamps for new task
    new_task["created"] = now_iso()
    new_task["updated"] = now_iso()
    new_task["completed_at"] = None

    # Set in_progress if adding to an in-progress section
    if section in IN_PROGRESS_SECTIONS:
        new_task["in_progress"] = now_iso()
    else:
        new_task["in_progress"] = None

    # Assign color_index for project sections using smart assignment
    if section in PROJECT_SECTIONS:
        new_task["color_index"] = get_next_project_color(sections)

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

        # Handle section transition (timestamps and history)
        handle_section_transition(found_task, found_section, new_section)

    # Set updated timestamp for any change (text or section)
    found_task["updated"] = now_iso()

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
    """Toggle task completion status. Projects move between PROJECTS and COMPLETED PROJECTS."""
    sections = parse_tasks()

    for section, tasks in sections.items():
        for task in tasks:
            if task["id"] == task_id:
                task["completed"] = not task["completed"]

                # Set/clear completed_at timestamp
                if task["completed"]:
                    task["completed_at"] = now_iso()
                else:
                    task["completed_at"] = None

                # Handle project completion - move between PROJECTS and COMPLETED PROJECTS
                if section == "PROJECTS" and task["completed"]:
                    # Move to COMPLETED PROJECTS and set completed_at
                    tasks.remove(task)
                    sections["COMPLETED PROJECTS"].append(task)
                    task["completed_at"] = now_iso()
                    # Append co@ history for project completion (unless research section)
                    if section not in RESEARCH_SECTIONS:
                        timestamp = now_iso()
                        entry = f"co@{timestamp}"
                        if task.get("history"):
                            task["history"] = f"{task['history']}|{entry}"
                        else:
                            task["history"] = entry
                elif section == "COMPLETED PROJECTS" and not task["completed"]:
                    # Move back to PROJECTS and clear completed_at
                    tasks.remove(task)
                    sections["PROJECTS"].append(task)
                    task["completed_at"] = None
                    # Append op@ history for project uncompleting (unless research section)
                    if section not in RESEARCH_SECTIONS:
                        timestamp = now_iso()
                        entry = f"op@{timestamp}"
                        if task.get("history"):
                            task["history"] = f"{task['history']}|{entry}"
                        else:
                            task["history"] = entry
                else:
                    # In-place completion (no section move) - append history directly
                    # Skip research section tasks (user decision #5)
                    if section not in RESEARCH_SECTIONS:
                        timestamp = now_iso()
                        if task["completed"]:
                            entry = f"co@{timestamp}"
                        else:
                            entry = f"op@{timestamp}"
                        if task.get("history"):
                            task["history"] = f"{task['history']}|{entry}"
                        else:
                            task["history"] = entry

                # Always set updated timestamp
                task["updated"] = now_iso()

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
    source_section = None
    for section, tasks in sections.items():
        for task in tasks:
            if task["id"] == task_id:
                found_task = task
                source_section = section  # Capture source section before removal
                tasks.remove(task)
                break
        if found_task:
            break

    if not found_task:
        return jsonify({"error": "Task not found"}), 404

    # Insert at new position
    target_index = min(target_index, len(sections[target_section]))
    sections[target_section].insert(target_index, found_task)

    # Only set updated if sections differ (same-section reorder does NOT set updated)
    if source_section != target_section:
        found_task["updated"] = now_iso()

        # Handle section transition (timestamps and history)
        handle_section_transition(found_task, source_section, target_section)

    save_tasks(sections)
    clear_undo()
    return jsonify({"success": True})


@app.route("/api/tasks/<task_id>/assign", methods=["POST"])
def assign_to_project(task_id):
    """Assign a task to a project."""
    data = request.json
    project_id = data.get("projectId")

    if not project_id:
        return jsonify({"error": "projectId required"}), 400

    sections = parse_tasks()

    # Find the task
    found_task = None
    for section, tasks in sections.items():
        for task in tasks:
            if task["id"] == task_id:
                found_task = task
                break
        if found_task:
            break

    if not found_task:
        return jsonify({"error": "Task not found"}), 404

    # Verify the project exists
    project_exists = False
    for section_name in PROJECT_SECTIONS:
        for project in sections.get(section_name, []):
            if project["id"] == project_id:
                project_exists = True
                break
        if project_exists:
            break

    if not project_exists:
        return jsonify({"error": "Project not found"}), 404

    found_task["assigned_project"] = project_id
    found_task["updated"] = now_iso()  # Set updated timestamp
    found_task.pop("order_index", None)  # Clear stale order_index from previous project

    # Check if any tasks assigned to this project have order_index
    # If yes, set order_index = max + 1 for the newly assigned task
    max_order_index = None
    for section, tasks in sections.items():
        for task in tasks:
            if task.get("assigned_project") == project_id and task.get("order_index") is not None:
                if max_order_index is None or task["order_index"] > max_order_index:
                    max_order_index = task["order_index"]

    if max_order_index is not None:
        found_task["order_index"] = max_order_index + 1

    save_tasks(sections)
    clear_undo()
    return jsonify(found_task)


@app.route("/api/tasks/<task_id>/unassign", methods=["POST"])
def unassign_from_project(task_id):
    """Remove a task's project assignment."""
    sections = parse_tasks()

    for section, tasks in sections.items():
        for task in tasks:
            if task["id"] == task_id:
                if "assigned_project" in task:
                    del task["assigned_project"]
                # Clear order_index when unassigning from project
                if "order_index" in task:
                    del task["order_index"]
                task["updated"] = now_iso()  # Set updated timestamp
                save_tasks(sections)
                clear_undo()
                return jsonify(task)

    return jsonify({"error": "Task not found"}), 404


@app.route("/api/tasks/<task_id>/color", methods=["POST"])
def set_project_color(task_id):
    """Set a project's color index."""
    data = request.json
    color_index = data.get("color_index")

    if not color_index or color_index < 1 or color_index > 16:
        return jsonify({"error": "color_index must be 1-16"}), 400

    sections = parse_tasks()

    # Find the project in PROJECT_SECTIONS
    for section_name in PROJECT_SECTIONS:
        for task in sections.get(section_name, []):
            if task["id"] == task_id:
                task["color_index"] = color_index
                task["updated"] = now_iso()  # Set updated timestamp
                save_tasks(sections)
                clear_undo()
                return jsonify(task)

    return jsonify({"error": "Project not found"}), 404


@app.route("/api/projects/reassign-colors", methods=["POST"])
def reassign_project_colors():
    """Reassign all active project colors sequentially (1 through N)."""
    sections = parse_tasks()

    # Reassign active projects to colors 1-N
    active_projects = sections.get("PROJECTS", [])
    for i, project in enumerate(active_projects):
        project["color_index"] = (i % 16) + 1

    save_tasks(sections)
    clear_undo()

    return jsonify({"reassigned": len(active_projects)})


@app.route("/api/projects/<project_id>/timeline", methods=["GET"])
def get_project_timeline(project_id):
    """Get project details and all tasks assigned to a project, sorted chronologically."""
    sections = parse_tasks()

    # Find the project in PROJECTS or COMPLETED PROJECTS sections
    project = None
    for section in PROJECT_SECTIONS:
        for task in sections.get(section, []):
            if task["id"] == project_id:
                project = {
                    "id": task["id"],
                    "text": task["text"],
                    "color_index": task.get("color_index"),
                    "completed": task.get("completed", False),
                    "created": task.get("created"),
                    "updated": task.get("updated"),
                    "in_progress": task.get("in_progress"),
                    "completed_at": task.get("completed_at"),
                }
                break
        if project:
            break

    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Collect all tasks assigned to this project across ALL sections
    assigned_tasks = []
    for section_name, tasks in sections.items():
        for task in tasks:
            if task.get("assigned_project") == project_id:
                # Add section name to each task so frontend knows where it lives
                task_with_section = task.copy()
                task_with_section["section"] = section_name
                assigned_tasks.append(task_with_section)

    # Sort tasks: prefer order_index if ANY task has it, otherwise use chronological sort
    # Check if any task has order_index
    has_any_order_index = any(task.get("order_index") is not None for task in assigned_tasks)

    def _section_age_tier(section_name):
        """Map section name to chronological tier (lower = older).

        Used as primary sort factor when tasks lack timestamps.
        Tiers: yearly archives < quarterly archives < completed projects
               < recent done < in progress < todo < backlog/other
        """
        name = section_name.upper()
        if name.startswith("DONE 20"):  # DONE 2025, DONE 2024
            try:
                return (0, int(name.split()[-1]))
            except ValueError:
                return (0, 9999)
        if name.startswith("DONE Q"):  # DONE Q1 2026
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

    def sort_key(task):
        if has_any_order_index:
            # When ANY task has order_index, sort by order_index ascending
            # Tasks with order_index come first (tier 0), tasks without come last (tier 1)
            if task.get("order_index") is not None:
                return (0, task.get("order_index"), (0, 0))
            else:
                return (1, 0, (0, 0))
        else:
            # Fallback: section tier first (oldest sections first), then timestamps
            tier = _section_age_tier(task.get("section", ""))
            in_progress = task.get("in_progress") or "9999"
            created = task.get("created") or "9999"
            return (tier, in_progress, created)

    assigned_tasks.sort(key=sort_key)

    return jsonify({
        "project": project,
        "tasks": assigned_tasks
    })


@app.route("/api/projects/<project_id>/reorder", methods=["POST"])
def reorder_project_tasks(project_id):
    """Reorder tasks within a project by setting order_index values."""
    data = request.json
    task_ids = data.get("taskIds")

    # Validate input
    if not task_ids:
        return jsonify({"error": "taskIds required"}), 400
    if not isinstance(task_ids, list) or len(task_ids) == 0:
        return jsonify({"error": "taskIds must be a non-empty array"}), 400

    sections = parse_tasks()

    # Find all tasks and validate they belong to this project
    tasks_to_update = []
    for task_id in task_ids:
        found_task = None
        for section_name, tasks in sections.items():
            for task in tasks:
                if task["id"] == task_id:
                    found_task = task
                    break
            if found_task:
                break

        if not found_task:
            return jsonify({"error": f"Task not found: {task_id}"}), 404

        if found_task.get("assigned_project") != project_id:
            return jsonify({"error": f"Task {task_id} is not assigned to project {project_id}"}), 400

        tasks_to_update.append(found_task)

    # Set order_index values (0, 1, 2, ...)
    for i, task in enumerate(tasks_to_update):
        task["order_index"] = i

    # Save without setting updated timestamp (explicit AC requirement)
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
    # Don't expose Google client secret
    if settings.get("google_client_secret"):
        settings["google_client_secret"] = ""
    # Don't expose Google credentials
    settings.pop("google_credentials", None)
    settings.pop("google_oauth_state", None)
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

    # Define the order for Confluence export
    # Use None as a marker for horizontal rules
    section_order = [
        ("PROJECTS", "PROJECTS"),
        None,  # HR below projects
        ("DONE THIS WEEK", "DONE THIS WEEK"),
        ("FOLLOW UPS", "FOLLOW UPS"),
        ("BLOCKED", "BLOCKED"),
        ("IN PROGRESS TODAY", "IN PROGRESS TODAY"),
        ("TODO THIS WEEK", "TODO THIS WEEK"),
        ("TODO NEXT WEEK", "TODO NEXT WEEK"),
        ("TODO FOLLOWING WEEK", "TODO FOLLOWING WEEK"),
        None,  # HR before backlog
        ("BACKLOG HIGH PRIORITY", "BACKLOG HIGH PRIORITY"),
        ("BACKLOG MEDIUM PRIORITY", "BACKLOG MEDIUM PRIORITY"),
        ("BACKLOG LOW PRIORITY", "BACKLOG LOW PRIORITY"),
        None,  # HR after backlog
        ("PROBLEMS TO SOLVE", "PROBLEMS TO SOLVE"),
        ("THINGS TO RESEARCH", "THINGS TO RESEARCH"),
        None,  # HR after research
    ]

    # Add current quarter
    current_q = get_current_quarter()
    section_order.append((current_q, current_q))

    # Add DONE 2025 if it exists
    if "DONE 2025" in sections:
        section_order.append(("DONE 2025", "DONE 2025"))

    for item in section_order:
        # Handle horizontal rule markers
        if item is None:
            html_parts.append('<hr/>')
            continue

        section_key, section_title = item
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
    html_parts.append('<hr/>')
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
            headers={"Accept": "application/json"},
            timeout=30
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
            json=update_data,
            timeout=30
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


# Google Calendar Integration (OAuth)
GOOGLE_SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
GOOGLE_REDIRECT_URI = 'http://localhost:5050/api/calendar/callback'


def get_google_client_config():
    """Get Google OAuth client config from settings."""
    settings = load_settings()
    client_id = settings.get('google_client_id')
    client_secret = settings.get('google_client_secret')

    if not client_id or not client_secret:
        return None

    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI]
        }
    }


def get_google_credentials():
    """Get stored Google credentials if available."""
    settings = load_settings()
    creds_data = settings.get('google_credentials')

    if not creds_data:
        return None

    try:
        creds = Credentials(
            token=creds_data.get('token'),
            refresh_token=creds_data.get('refresh_token'),
            token_uri=creds_data.get('token_uri'),
            client_id=creds_data.get('client_id'),
            client_secret=creds_data.get('client_secret'),
            scopes=creds_data.get('scopes')
        )

        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            save_google_credentials(creds)

        return creds
    except Exception:
        return None


def save_google_credentials(creds):
    """Save Google credentials to settings."""
    settings = load_settings()
    settings['google_credentials'] = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': list(creds.scopes) if creds.scopes else GOOGLE_SCOPES
    }
    save_settings(settings)


@app.route("/api/calendar/status")
def calendar_status():
    """Check Google Calendar connection status."""
    settings = load_settings()
    has_config = bool(settings.get('google_client_id') and settings.get('google_client_secret'))
    has_credentials = bool(settings.get('google_credentials'))
    creds = get_google_credentials()

    # If we have stored credentials but get_google_credentials returned None,
    # the token refresh failed — user needs to reconnect
    needs_reconnect = has_credentials and creds is None

    # If creds were returned, verify they actually work with a lightweight API call
    if creds and not needs_reconnect:
        try:
            service = build('calendar', 'v3', credentials=creds)
            service.calendarList().get(calendarId='primary').execute()
        except Exception:
            needs_reconnect = True
            creds = None

    return jsonify({
        "has_config": has_config,
        "connected": creds is not None,
        "needs_reconnect": needs_reconnect
    })


@app.route("/api/calendar/config", methods=["POST"])
def save_calendar_config():
    """Save Google OAuth client credentials."""
    data = request.json
    settings = load_settings()

    if data.get('client_id'):
        settings['google_client_id'] = data['client_id'].strip()
    if data.get('client_secret'):
        settings['google_client_secret'] = data['client_secret'].strip()

    save_settings(settings)
    return jsonify({"success": True})


@app.route("/api/calendar/auth-url")
def calendar_auth_url():
    """Generate Google OAuth URL."""
    client_config = get_google_client_config()
    if not client_config:
        return jsonify({"error": "Client credentials not configured"}), 400

    flow = Flow.from_client_config(
        client_config,
        scopes=GOOGLE_SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI
    )

    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )

    settings = load_settings()
    settings['google_oauth_state'] = state
    save_settings(settings)

    return jsonify({"auth_url": auth_url})


@app.route("/api/calendar/callback")
def calendar_callback():
    """Handle Google OAuth callback."""
    error = request.args.get('error')
    if error:
        return redirect('/?calendar_error=' + error)

    code = request.args.get('code')
    if not code:
        return redirect('/?calendar_error=no_code')

    client_config = get_google_client_config()
    if not client_config:
        return redirect('/?calendar_error=no_config')

    try:
        flow = Flow.from_client_config(
            client_config,
            scopes=GOOGLE_SCOPES,
            redirect_uri=GOOGLE_REDIRECT_URI
        )
        flow.fetch_token(code=code)
        save_google_credentials(flow.credentials)

        settings = load_settings()
        settings.pop('google_oauth_state', None)
        save_settings(settings)

        return redirect('/?calendar_connected=true')
    except Exception as e:
        return redirect('/?calendar_error=' + str(e))


@app.route("/api/calendar/events")
def calendar_events():
    """Get calendar events for a given day (default: today)."""
    creds = get_google_credentials()
    if not creds:
        return jsonify({"connected": False, "events": []})

    try:
        service = build('calendar', 'v3', credentials=creds)

        # Get date offset from query param (0 = today, -1 = yesterday, 1 = tomorrow)
        offset = request.args.get('offset', 0, type=int)
        target_date = datetime.now() + timedelta(days=offset)

        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        time_min = start_of_day.isoformat() + 'Z'
        time_max = end_of_day.isoformat() + 'Z'

        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = []
        for event in events_result.get('items', []):
            start = event.get('start', {})
            end = event.get('end', {})

            # Skip all-day events and events without specific times
            if 'dateTime' not in start or 'dateTime' not in end:
                continue

            # Get current user's response status
            response_status = None
            for attendee in event.get('attendees', []):
                if attendee.get('self'):
                    response_status = attendee.get('responseStatus')
                    break

            events.append({
                'id': event.get('id'),
                'summary': event.get('summary', '(No title)'),
                'start': start.get('dateTime'),
                'end': end.get('dateTime'),
                'hangoutLink': event.get('hangoutLink'),
                'htmlLink': event.get('htmlLink'),
                'isAllDay': False,
                'responseStatus': response_status
            })

        return jsonify({"connected": True, "events": events})

    except HttpError as e:
        if e.resp.status == 401:
            settings = load_settings()
            settings.pop('google_credentials', None)
            save_settings(settings)
            return jsonify({"connected": False, "events": [], "error": "Token expired"})
        return jsonify({"connected": False, "events": [], "error": str(e)})
    except Exception as e:
        return jsonify({"connected": False, "events": [], "error": str(e)})


@app.route("/api/calendar/disconnect", methods=["POST"])
def calendar_disconnect():
    """Disconnect Google Calendar."""
    settings = load_settings()
    settings.pop('google_credentials', None)
    settings.pop('google_oauth_state', None)
    save_settings(settings)
    return jsonify({"success": True})


def get_timeline_week_boundaries(week_offset=0):
    """Compute Sunday-Saturday week boundaries for the given offset.

    Unlike get_week_dates() which uses Monday-Friday, the timeline uses
    Sunday-Saturday to show full weeks including weekends.

    Args:
        week_offset: 0 = current week, -1 = last week, 1 = next week

    Returns:
        tuple: (week_start: date, week_end: date, today: date)
    """
    today = datetime.now().date()
    # Sunday is weekday 6 in Python (Monday=0, Sunday=6)
    # Calculate days since last Sunday
    days_since_sunday = (today.weekday() + 1) % 7
    this_sunday = today - timedelta(days=days_since_sunday)
    # Apply offset
    week_start = this_sunday + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)  # Saturday
    return week_start, week_end, today


def compute_spans_from_history(history_str, task, today, week_start, week_end):
    """Compute timeline spans from a task's history string.

    Parses the pipe-delimited history entries and creates spans between
    consecutive entries. Each span has a start date, end date, and status.

    The last entry's span extends to:
    - completed_at if the task is completed
    - blocked_at if the task is currently blocked
    - today if the task is in progress

    op@ (opened/backlog) entries end the previous span without starting
    a visible new span -- the task was deactivated.

    Args:
        history_str: Pipe-delimited history like "ip@2026-02-10T09:00:00|bl@2026-02-12T14:00:00"
        task: Full task dict (for completed_at, blocked_at, in_progress fallback)
        today: Today's date (date object)
        week_start: Start of displayed week (date, Sunday)
        week_end: End of displayed week (date, Saturday)

    Returns:
        list: Spans within the week, each as {start: str, end: str, status: str}
              Dates are ISO format (YYYY-MM-DD). Spans outside the week are excluded.
    """
    # Active states create visible spans; terminal events just end the previous span
    ACTIVE_STATUSES = {
        "ip": "in_progress",
        "bl": "blocked",
    }
    # co@ and op@ are terminal -- they mark where the previous span ends
    # co@ = completed, op@ = moved back to todo/backlog

    entries = history_str.split("|")
    parsed = []
    for entry in entries:
        if "@" not in entry:
            continue
        prefix, timestamp_str = entry.split("@", 1)
        try:
            entry_date = datetime.fromisoformat(timestamp_str).date()
        except (ValueError, TypeError):
            continue
        parsed.append((prefix, entry_date))

    if not parsed:
        return []

    raw_spans = []
    for i in range(len(parsed)):
        prefix, start_date = parsed[i]
        status = ACTIVE_STATUSES.get(prefix)

        # co@ and op@ entries don't start visible spans -- they only end
        # the previous span (which is handled by the next-entry lookup below)
        if status is None:
            continue

        # Determine end date for this span
        if i + 1 < len(parsed):
            # End at next entry's date
            end_date = parsed[i + 1][1]
        else:
            # Last entry is an active state (ip@ or bl@) -- task is currently
            # in this state, so the span extends to today
            end_date = today

        raw_spans.append({
            "start": start_date,
            "end": end_date,
            "status": status,
        })

    # Clip spans to week boundaries and filter out those entirely outside
    clipped = []
    for span in raw_spans:
        s = span["start"]
        e = span["end"]

        # Skip spans entirely outside the week
        if e < week_start or s > week_end:
            continue

        # Clip to week boundaries
        clipped_start = max(s, week_start)
        clipped_end = min(e, week_end)

        clipped.append({
            "start": clipped_start.isoformat(),
            "end": clipped_end.isoformat(),
            "status": span["status"],
        })

    return clipped


def compute_simplified_span(task, today, week_start, week_end, section_name):
    """Compute a single simplified span for pre-existing tasks without history.

    For tasks that have timestamps (in_progress, completed_at, blocked_at) but
    no history field, create a single span from in_progress to the appropriate
    end date.

    For tasks in done sections without completed_at, backfill completed_at
    to the in_progress date (per user decision #2).

    Args:
        task: Task dict with timestamp fields
        today: Today's date
        week_start: Start of displayed week (Sunday)
        week_end: End of displayed week (Saturday)
        section_name: Section the task is in (for done-section backfill)

    Returns:
        list: Zero or one span dicts, empty if span is entirely outside week
    """
    ip_str = task.get("in_progress")
    if not ip_str:
        return []

    try:
        start_date = datetime.fromisoformat(ip_str).date()
    except (ValueError, TypeError):
        return []

    # Determine end date
    if task.get("completed_at"):
        try:
            end_date = datetime.fromisoformat(task["completed_at"]).date()
        except (ValueError, TypeError):
            end_date = today
    elif task.get("blocked_at"):
        try:
            end_date = datetime.fromisoformat(task["blocked_at"]).date()
        except (ValueError, TypeError):
            end_date = today
    elif is_done_section(section_name):
        # Backfill: done-section task without completed_at uses in_progress date
        end_date = start_date
    else:
        end_date = today

    # Check if entirely outside week
    if end_date < week_start or start_date > week_end:
        return []

    # Clip to week boundaries
    clipped_start = max(start_date, week_start)
    clipped_end = min(end_date, week_end)

    return [{
        "start": clipped_start.isoformat(),
        "end": clipped_end.isoformat(),
        "status": "in_progress",
    }]


def _spans_from_terminal_history(task, today, week_start, week_end, section_name):
    """Create spans for tasks with history containing only terminal events.

    When a task has history like "co@2026-02-17T10:00:00" (completed via
    checkbox without ever being moved to IP), create a single-day bar on
    the event date. For co@, use the completion date. For bl@, create a
    blocked span from that date to today.
    """
    history_str = task.get("history", "")
    entries = history_str.split("|")

    for entry in reversed(entries):
        if "@" not in entry:
            continue
        prefix, timestamp_str = entry.split("@", 1)
        try:
            entry_date = datetime.fromisoformat(timestamp_str).date()
        except (ValueError, TypeError):
            continue

        if prefix == "co":
            if entry_date < week_start or entry_date > week_end:
                return []
            return [{
                "start": entry_date.isoformat(),
                "end": entry_date.isoformat(),
                "status": "in_progress",
            }]
        elif prefix == "bl":
            end_date = today
            if end_date < week_start or entry_date > week_end:
                return []
            clipped_start = max(entry_date, week_start)
            clipped_end = min(end_date, week_end)
            return [{
                "start": clipped_start.isoformat(),
                "end": clipped_end.isoformat(),
                "status": "blocked",
            }]

    return []


def _spans_from_timestamp_only(task, today, week_start, week_end, section_name):
    """Create spans for tasks with only completed_at or blocked_at, no in_progress.

    For completed_at-only tasks: single-day bar on completion date.
    For blocked_at-only tasks: bar from blocked_at to today.
    """
    if task.get("completed_at"):
        try:
            comp_date = datetime.fromisoformat(task["completed_at"]).date()
        except (ValueError, TypeError):
            return []
        if comp_date < week_start or comp_date > week_end:
            return []
        return [{
            "start": comp_date.isoformat(),
            "end": comp_date.isoformat(),
            "status": "in_progress",
        }]

    if task.get("blocked_at"):
        try:
            bl_date = datetime.fromisoformat(task["blocked_at"]).date()
        except (ValueError, TypeError):
            return []
        end_date = today
        if end_date < week_start or bl_date > week_end:
            return []
        clipped_start = max(bl_date, week_start)
        clipped_end = min(end_date, week_end)
        return [{
            "start": clipped_start.isoformat(),
            "end": clipped_end.isoformat(),
            "status": "blocked",
        }]

    return []


@app.route("/api/timeline")
def get_timeline():
    """Get timeline data for a given week.

    Query params:
        week_offset: int (default 0). 0 = current week, -1 = last week, etc.

    Returns JSON:
        {
            week_start: "YYYY-MM-DD" (Sunday),
            week_end: "YYYY-MM-DD" (Saturday),
            today: "YYYY-MM-DD",
            tasks: [{
                id, text, section,
                spans: [{start, end, status}],
                assigned_project, project_color
            }]
        }
    """
    week_offset = request.args.get("week_offset", 0, type=int)
    week_start, week_end, today = get_timeline_week_boundaries(week_offset)

    sections = parse_tasks()

    # Build project color lookup: project_id -> color_index
    project_colors = {}
    for section_name in PROJECT_SECTIONS:
        for task in sections.get(section_name, []):
            if task.get("color_index"):
                project_colors[task["id"]] = task.get("color_index")

    # Collect qualifying tasks from all sections
    timeline_tasks = []
    for section_name, tasks in sections.items():
        # Exclude research sections
        if section_name in RESEARCH_SECTIONS:
            continue

        for task in tasks:
            # A task qualifies for the timeline if it has ANY timestamp,
            # history, or is currently in an active section (IP/BLOCKED).
            has_in_progress = task.get("in_progress")
            has_completed_at = task.get("completed_at")
            has_blocked_at = task.get("blocked_at")
            has_history = bool(task.get("history"))
            is_in_active_section = (
                section_name in IN_PROGRESS_SECTIONS
                or section_name in BLOCKED_SECTIONS
            )

            if not any([has_in_progress, has_completed_at, has_blocked_at,
                        has_history, is_in_active_section]):
                continue

            # Compute spans
            if has_history:
                spans = compute_spans_from_history(
                    task["history"], task, today, week_start, week_end
                )
                # If history has only terminal events (co@/op@) with no
                # preceding active span, create a single-day bar on the
                # terminal event date
                if not spans and not has_in_progress:
                    spans = _spans_from_terminal_history(
                        task, today, week_start, week_end, section_name
                    )
            elif has_in_progress:
                spans = compute_simplified_span(
                    task, today, week_start, week_end, section_name
                )
            elif has_completed_at or has_blocked_at:
                # Task with only completed_at or blocked_at, no in_progress
                spans = _spans_from_timestamp_only(
                    task, today, week_start, week_end, section_name
                )
            elif is_in_active_section:
                # Pre-existing task in active section with no timestamps —
                # show as single-day bar on today
                if week_start <= today <= week_end:
                    status = ("blocked" if section_name in BLOCKED_SECTIONS
                              else "in_progress")
                    spans = [{
                        "start": today.isoformat(),
                        "end": today.isoformat(),
                        "status": status,
                    }]
                else:
                    spans = []
            else:
                spans = []

            # Skip tasks with no spans in this week
            if not spans:
                continue

            # Build response entry
            assigned_project = task.get("assigned_project")
            project_color = project_colors.get(assigned_project) if assigned_project else None

            timeline_tasks.append({
                "id": task["id"],
                "text": task["text"],
                "section": section_name,
                "spans": spans,
                "assigned_project": assigned_project,
                "project_color": project_color,
            })

    return jsonify({
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "today": today.isoformat(),
        "tasks": timeline_tasks,
    })


@app.route("/api/theme", methods=["GET"])
def get_theme():
    """Get current theme number."""
    settings = load_settings()
    theme = settings.get('theme', 1)
    return jsonify({"theme": theme})


@app.route("/api/theme", methods=["POST"])
def set_theme():
    """Set theme number."""
    data = request.json
    theme = data.get('theme', 1)
    # Validate theme is between 1 and 16
    theme = max(1, min(16, int(theme)))
    settings = load_settings()
    settings['theme'] = theme
    save_settings(settings)
    return jsonify({"success": True, "theme": theme})


if __name__ == "__main__":
    ensure_data_file()
    print("Starting Crumbwise on http://localhost:5050")
    app.run(debug=True, port=5050)
