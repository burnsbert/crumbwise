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

        # Handle in_progress timestamp transitions for section moves
        if new_section in IN_PROGRESS_SECTIONS:
            # Set in_progress if not already set (preserve original start time)
            if not found_task.get("in_progress"):
                found_task["in_progress"] = now_iso()
        elif new_section in CLEARS_IN_PROGRESS_SECTIONS:
            # Clear in_progress when moving to TODO or backlog sections
            found_task["in_progress"] = None

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
                elif section == "COMPLETED PROJECTS" and not task["completed"]:
                    # Move back to PROJECTS and clear completed_at
                    tasks.remove(task)
                    sections["PROJECTS"].append(task)
                    task["completed_at"] = None

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

        # Handle in_progress timestamp transitions
        if target_section in IN_PROGRESS_SECTIONS:
            # Set in_progress if not already set (preserve original start time)
            if not found_task.get("in_progress"):
                found_task["in_progress"] = now_iso()
        elif target_section in CLEARS_IN_PROGRESS_SECTIONS:
            # Clear in_progress when moving to TODO or backlog sections
            found_task["in_progress"] = None

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

    def sort_key(task):
        if has_any_order_index:
            # When ANY task has order_index, sort by order_index ascending
            # Tasks with order_index come first (tier 0), tasks without come last (tier 1)
            if task.get("order_index") is not None:
                return (0, task.get("order_index"))
            else:
                return (1, 0)  # tier 1, no specific secondary sort needed
        else:
            # Fallback to chronological sort: primary by in_progress (newest first, nulls last),
            # secondary by created (newest first, nulls last)
            # Use far-past sentinel "0000" for None values so they sort last when reversed
            in_progress = task.get("in_progress") or "0000"
            created = task.get("created") or "0000"
            return (in_progress, created)

    if has_any_order_index:
        assigned_tasks.sort(key=sort_key)  # sort ascending for order_index
    else:
        assigned_tasks.sort(key=sort_key, reverse=True)  # reverse chronological

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
