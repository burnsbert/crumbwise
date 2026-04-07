---
name: sharable-weekly-update
description: Generate a boss-friendly weekly status update from Crumbwise task board and standup history. Summarizes last week's accomplishments and this week's priorities in professional, sharable language.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
user-invocable: true
---

# Sharable Weekly Update

Generates a professional weekly status update suitable for sharing with leadership. Reads the Crumbwise task board and standup history to produce a concise summary of accomplishments and priorities.

## Important: Audience Awareness

This update is shared with the user's manager. Apply these filters:

**Include:**
- Completed work (shipped features, resolved blockers, meetings/alignment achieved)
- Current priorities and planned work
- Blockers that leadership can help with
- Cross-team collaboration and support activities

**Exclude:**
- Internal frustrations, political dynamics, or interpersonal tensions
- Specific tool names or implementation details that aren't meaningful to leadership (abstract to outcomes)
- Personal opinions about others' proposals or decisions
- Anything from standup history marked as coaching or corrections
- Raw task IDs, metadata, or technical jargon

**Tone:** Professional, concise, outcome-oriented. Frame work in terms of impact and progress, not effort. No em dashes anywhere. Use normal dashes sparingly. Avoid AI-sounding phrasing.

## Step 1: Determine Week Boundaries

```bash
date +%Y-%m-%d
```

"Last week" = the most recent full Mon-Fri work week before today.
"This week" = the current Mon-Fri work week.

If today is Monday, last week is the previous Mon-Fri. If today is mid-week, last week is still the previous Mon-Fri.

## Step 2: Load Data

### A. Read task board
Read `data/tasks.md`. Identify:
- Tasks completed last week (check `completed_at` timestamps in metadata)
- Tasks currently in progress or planned for this week (TODO THIS WEEK, IN PROGRESS TODAY)
- Blocked items (BLOCKED OR WAITING)
- Active projects and their priorities

### B. Read standup history
Read `data/standup/history.md`. Load sessions from last week to extract:
- Key discussion topics and decisions
- Opportunities identified
- Context that helps frame the work

### C. Read notes
Read `data/notes.txt` for any additional context.

## Step 3: Generate Update

Output format:

```
## Weekly Update — [date range]

### Last Week
- [Bullet points: completed work grouped by theme/project, outcome-focused]

### Current Tasks
- [Bullet points: planned work, priorities, key meetings]

### Blockers / Needs
- [Only if there are genuine blockers leadership should know about]
```

Guidelines:
- **3-7 bullets per section** — enough to show breadth, not so many it's a task dump
- **Group related items** — "Completed 3 Tech Prepare code reviews" not three separate bullets
- **Lead with the outcome** — "Launched First Responder Slack integration" not "Finished the Slack permission work and got Brian's approval and deployed"
- **Use project names** people recognize — if the user's projects have names their boss knows, use those names
- **Skip trivial items** — minor bug fixes or internal tooling tweaks don't need to be in a leadership update unless they're part of a larger story

## Step 4: Present for Review

Show the draft and ask: "Want me to adjust anything before you share this?"

Do NOT save to a file unless the user asks.
