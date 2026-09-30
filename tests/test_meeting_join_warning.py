"""Tests for the Join Meet warning logic in static/app.js (run under Node)."""

import json
import re
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "static" / "app.js"
FUNCTIONS = ["formatMinutesAway", "getMeetingJoinWarning"]

START = "2026-09-30T13:00:00-04:00"
END = "2026-09-30T14:00:00-04:00"


def extract_function(source, name):
    match = re.search(rf"^function {name}\(.*?^}}$", source, re.S | re.M)
    assert match, f"{name} not found in app.js"
    return match.group(0)


def warning_at(now, start=START, end=END):
    source = APP_JS.read_text()
    code = "\n".join(extract_function(source, name) for name in FUNCTIONS)
    code += (
        f"\nconsole.log(JSON.stringify(getMeetingJoinWarning("
        f"new Date({json.dumps(start)}), new Date({json.dumps(end)}), new Date({json.dumps(now)}))));"
    )
    result = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("now, expected", [
    # Future: more than 10 minutes out warns, 10 or fewer does not
    ("2026-09-30T12:59:56-04:00", None),
    ("2026-09-30T12:50:00-04:00", None),
    ("2026-09-30T12:49:00-04:00", "11 minutes in the future"),
    ("2026-09-30T12:00:00-04:00", "1 hour in the future"),
    ("2026-09-30T11:55:00-04:00", "1 hour and 5 minutes in the future"),
    ("2026-09-30T10:58:00-04:00", "2 hours and 2 minutes in the future"),
    # In progress: fine through 75%, warns after
    ("2026-09-30T13:00:00-04:00", None),
    ("2026-09-30T13:45:00-04:00", None),
    ("2026-09-30T13:46:00-04:00", "almost done"),
    # Past: at or after the end
    ("2026-09-30T14:00:00-04:00", "already complete"),
    ("2026-09-30T16:30:00-04:00", "already complete"),
])
def test_meeting_join_warning(now, expected):
    assert warning_at(now) == expected


def test_partial_minutes_round_up():
    assert warning_at("2026-09-30T12:49:30-04:00") == "11 minutes in the future"


def test_singular_minute():
    assert warning_at("2026-09-30T11:59:00-04:00") == "1 hour and 1 minute in the future"
