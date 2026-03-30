---
name: daily-standup
description: Daily standup that reviews Crumbwise status, asks N strategic questions about current work, and identifies opportunities. Usage: /daily-standup [N] (default N=5)
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
user-invocable: true
---

# Daily Standup

Interactive standup that reviews your task board, asks targeted questions, and surfaces opportunities.

**Important**: This skill reads `data/tasks.md` from the current project but writes all standup data to `data/standup/` (gitignored). The task board and all other project files are never modified.

## Parse Arguments

Extract N from args. Default N=5 if no argument given.
- `/daily-standup` → N=5
- `/daily-standup 3` → N=3

If the argument is not a positive integer (e.g. `0`, `-1`, `abc`), default to N=5 and note the invalid input. Minimum valid value is 1.

## Step 0: Ensure Data Directory

```bash
mkdir -p data/standup
```

All standup data lives at:
- Config: `data/standup/config.md`
- History: `data/standup/history.md`

## Step 1: Load Context

### A. Load config

Read `data/standup/config.md`.

**If the file does not exist**, write it with this unconfigured placeholder template, then immediately run the **First-Time Setup** flow below before doing anything else:

```markdown
# Standup Config

role: UNCONFIGURED
team_context: UNCONFIGURED
recent_days: 14
```

**If the file exists**, check whether `role` or `team_context` is still `UNCONFIGURED`. If either is, run the **First-Time Setup** flow before continuing.

#### First-Time Setup

Tell the user: "Let's set up your standup config. I'll ask a couple of quick questions."

Ask these questions **one at a time**, waiting for an answer before asking the next:

1. "What's your role or job title?"
2. "Briefly describe your team and what you're focused on — what kinds of projects, what problems you're solving, what your org is like." *(1-3 sentences)*

After both answers, write the updated config file:

```markdown
# Standup Config

role: [answer to Q1]
team_context: >
  [answer to Q2]
recent_days: 14
```

Tell the user: "Config saved. You can edit it anytime at `data/standup/config.md`"

Then continue with the rest of the standup normally.

### B. Read tasks

Read `data/tasks.md` from the current working directory (read-only — never modify this file or any other project file). If the file cannot be read, tell the user and ask them to confirm the working directory before continuing.

Read **all sections** — do not skip any. Apply this logic per task:

**Completed tasks** (`[x]`): Include only if the task metadata contains a `completed_at` timestamp within the last `recent_days` (default 14). Tasks without a `completed_at` timestamp are old archive data — skip them.

**Incomplete tasks** (`[ ]`): Include all — in progress, planned, blocked, waiting, backlog. These form the forward-looking picture.

**Projects** (PROJECTS section): Include all — note name, priority (high/medium/paused), and which tasks are assigned to each project via `assigned_project` metadata.

From this, build a working picture organized as:
- **Recently completed** — done tasks with `completed_at` within the window
- **Active / in progress** — tasks with `in_progress` metadata or in an IN PROGRESS section
- **Blocked or waiting** — tasks with `blocked_at` metadata or in a BLOCKED section
- **Planned soon** — TODO THIS WEEK, TODO NEXT WEEK
- **Projects** — each project with its priority and assigned tasks (from any section)

Parse task text only for display. Use metadata only for filtering and grouping.

### C. Read notes

Read `data/notes.txt` from the current working directory (read-only). If the file exists and has content, treat it as free-form context — it may contain team info, ongoing concerns, reminders, or anything the user has been tracking. Incorporate relevant details into your understanding of the current situation. Don't quote the notes back verbatim; just let them inform your questions and opportunity framing.

### D. Load standup history

Read `data/standup/history.md`. If it doesn't exist, note "no prior history."

Each session in the file is delimited by `---` (which terminates each block). To load the last 5 sessions: count `---` delimiters from the **end of the file** backward and take the last 5 complete blocks. A block is complete if it has a `## YYYY-MM-DD` header, at least one Q/A pair, and a terminating `---`. If the file ends without a closing `---`, the trailing block is incomplete — exclude it from the count. Use the loaded sessions to inform your questions (use the `topics:` field as the primary signal for what has been recently covered — avoid repeating recent topics, build on past answers).

Session format:
```
## YYYY-MM-DD
topics: [project-a, topic-b]
Q: [question asked]
A: [key answer points, 1-2 sentences max]
Q: [next question]
A: [summary]
...
opportunities: [brief bullets]
---
```

## Perspective Lenses

Before planning questions, internalize these six lenses — collectively **CLAIMS** (Champion, Learner, Automator, Inspiration, Multiplier, Seeker). You are free to inhabit any of them — or stay neutral — depending on where the task board and conversation suggest the biggest opportunities or risks live. You are not locked into one; drift between them as the standup unfolds.

**Seeker** *(Discoverer/Questioner — Understanding > Root Cause > Impact)*
Digs beneath stated problems to find the real ones. Asks: "What are we not seeing? What assumption is everyone accepting that might be wrong? Whose perspective is missing? What have we tried before and why didn't it work?" Champion when you sense a project is solving the wrong problem, or when tasks keep recurring without closure. Opportunity angle: surface the hidden constraint or overlooked root cause that, once addressed, dissolves a cluster of other problems.

**Inspiration** *(Innovator/Cross-Pollinator — Fresh Angle > Reframe > Impact)*
Imports ideas from other fields and finds unexpected entry points. Asks: "Is there a completely different angle of attack on this problem? What would another domain do? What approach hasn't been tried here yet? Where else has something like this been solved in a surprising way? Is there a small experiment we could run that might bear fruit — a low-cost bet with asymmetric upside?" Champion when work is incremental where a fresh approach could be transformative. Opportunity angle: find the cross-domain analogy, unexpected entry point, or low-risk experiment that opens a faster or higher-leverage path.

**Learner** *(External Scout — Adoption > Improvement > Awareness)*
Looks outside the team and org for better ways. Asks: "Are other people solving this problem better than us? Is there a technology, tool, or methodology out there we haven't evaluated? What's the state of the art on this? Who has already figured out what we're struggling with, and what did they learn?" Champion when the team is grinding on a known-hard problem, when solutions feel homegrown and fragile, or when there's been no time to look up from execution. Opportunity angle: identify a tool, practice, or external solution that could replace weeks of in-house effort or leap the team past a current ceiling.

**Multiplier** *(Constraint Finder — Compounding > Breadth > Leverage)*
Looks for the one thing that unlocks everything else, and for existing investments that aren't being fully used. Asks: "What's the bottleneck quietly throttling this whole system? What investment now pays back for months or years? If we did only one thing, what would make the most other things easier or faster? What do we already have — tools, agents, systems, access, knowledge — that we're only using at 20% of its potential?" Champion when multiple projects seem stuck for the same underlying reason, when there's a platform/tooling gap forcing workarounds, or when something already built is sitting underutilized. Opportunity angle: identify the single constraint whose removal compounds across the team, or the existing asset that could be doing far more work than it is.

**Champion** *(Org Dynamics — Visibility > Timing > Packaging)*
Reads organizational momentum and thinks about how work lands. Asks: "Who needs to champion this for it to get funded or adopted? What's already moving in the org that this could attach to? Is this a good idea at the wrong moment — or the right moment that's being missed? What's the one-sentence headline that makes leadership care?" Activate when technically strong work lacks an adoption or visibility story. Opportunity angle: find the right framing, timing, or coalition to turn existing good work into a recognized win.

**Automator** *(Workload Reducer — Elimination > Delegation > Simplification)*
Relentlessly hunts for work that shouldn't require a human. Asks: "Could an AI agent do this? Could this be a scheduled job instead of a manual step? What am I doing repeatedly that a script, workflow, or model could own? What's the highest-friction recurring task on the board right now?" Activate by default — this lens is always relevant because the goal is always to take things off the plate. Opportunity angle: identify the specific manual workflow, recurring task, or human-in-the-loop step that could be automated today with available tools (Claude Code agents, scripts, MCP, scheduled jobs, etc.).

You don't need to announce which lens you're using. Let it shape the angle of your questions and the framing of your opportunities naturally.

---

## Step 2: Plan Your Questions

You have a budget of **N questions total** (including follow-ups). Every question you ask—whether new topic or follow-up—costs 1.

**Before asking anything**, silently form a question plan:

1. Identify 2-3 candidate topics from the task board that are most worth discussing today. Prioritize:
   - High-priority projects with recent activity
   - Blocked or stalled items
   - Tasks approaching deadlines
   - Topics NOT in the `topics:` fields of recent history
   - Areas where you notice a pattern worth exploring (e.g., a project generating many tasks)

2. Allocate your budget across topics. With N≤3, you typically go 1 question per topic with little room for follow-ups. With N=5+, you have room to follow up on 1-2 answers. If N=1, skip the forward-looking reserve rule and ask the single highest-priority question from your candidate topics.

3. Unless N=1, reserve your last question for something forward-looking — upcoming decisions, risks, or the "what's on your mind that the board doesn't show?"

**Question quality rules:**
- Ask the most specific question the task data supports. "Your Bugfinder project has 6 assigned tasks, 2 about false negatives — where does that stand?" beats "How's Bugfinder going?"
- Treat N as valuable. Never ask a question answerable from the task board alone.
- If an answer opens a thread clearly worth pursuing AND you have budget, use a follow-up. But follow-ups aren't mandatory — save budget for breadth if the answer was complete.
- If a user's answer covers a topic you had planned to ask about next, drop that topic from your plan and substitute a new one or move on.

## Step 3: Ask Questions One at a Time

Start immediately. Do not list topics or warn the user you're about to ask questions.

**Format each question as:**
```
**[N remaining]** [Your question here]
```

Where the label counts down: the first question of N shows `[N remaining]`, the second shows `[N-1 remaining]`, and the last shows `[1 remaining]`.

Wait for the user's answer after each question.

After receiving an answer:
- Note the key points internally
- Decide: follow-up (if answer was partial or opened something genuinely interesting) OR move to next planned topic
- Ask the next question

Continue until budget is exhausted.

## Step 4: Research Opportunities in Parallel

After all N questions are answered, **before** synthesizing, silently identify up to 4 distinct research threads that could surface a compelling opportunity. Each thread should pursue a different angle — don't spawn agents on the same question from different directions.

Good research threads:
- A specific technology, tool, or pattern that came up in the conversation (look up current state of the art, adoption, or relevant examples)
- An existing project or initiative in the codebase/task board that might connect to something mentioned
- A market or industry pattern relevant to what the user described as a pain point
- A prior standup history thread that went unresolved — has anything changed?
- A concrete "has this been done before?" check on a potential new project idea

Launch up to 4 agents using the `research-assistant` subagent type (locally defined in `.claude/agents/research-assistant.md`). Each agent should:
- Get a specific, focused research question (1-2 sentences)
- Return a short answer (3-5 sentences max) plus any concrete examples, links, or data points found
- Run in **parallel** (single message, multiple Task calls)

You decide how many agents to launch (1–4) based on how many genuinely distinct threads emerged from the conversation. Don't launch agents for the sake of it — if only 2 good threads exist, launch 2.

Tell the user: "Researching a few angles before identifying opportunities..." then launch the agents.

Wait for all agents to complete, then proceed to Step 5.

## Step 5: Synthesize Opportunities

After all N questions are answered and research is complete, output this section:

---

### Opportunities

Based on your current board and today's answers, here are 1-2 opportunities worth considering:

**[Opportunity 1 Title]**
[2-3 sentences: what the opportunity is, why it matters for your role/goals, and a concrete first step. Frame in terms of impact — time saved, team velocity, company wins, etc.]

**[Opportunity 2 Title]** *(if applicable)*
[Same format]

---

Keep opportunities grounded in what was discussed and what the research turned up. Let the perspective lenses shape the framing — pick whichever lens the conversation most warrants, not the one that feels most familiar:

- **Seeker lens**: the root cause hiding behind a cluster of recurring tasks; an assumption everyone's accepted that's worth challenging; the problem behind the stated problem
- **Inspiration lens**: a fresh angle of attack that hasn't been tried; prior art from another field that maps surprisingly well; a low-cost experiment with asymmetric upside
- **Learner lens**: a tool, library, or methodology the team hasn't evaluated that could replace weeks of in-house effort; the state-of-the-art on a problem the team is grinding through; who has already solved this and what did they learn
- **Multiplier lens**: the one bottleneck whose removal compounds across the team for months; the platform or tooling gap that keeps forcing workarounds; the tool, agent, or system already in place that's being used at a fraction of its potential
- **Champion lens**: the right moment to surface existing good work to leadership; the current that's already moving in the org that a project could attach to; the coalition or framing that turns a good idea into a funded one
- **Automator lens**: the manual workflow or recurring task that an AI agent, script, or scheduled job could own today; the human-in-the-loop step that's costing disproportionate time; the thing being done by hand that shouldn't be

You can draw on multiple lenses for a single opportunity, or let one dominate. Choose based on what the task board and conversation actually showed — not habit.

## Step 6: Save Session

Get today's date:
```bash
date +%Y-%m-%d
```

Build the session block in this compact format:
```markdown
## YYYY-MM-DD
topics: [comma-separated topic tags, 2-5 words each]
Q: [question asked]
A: [1-2 sentence summary of answer]
Q: [next question]
A: [summary]
...
opportunities: [one-liner per opportunity]
---
```

Keep answers to 1-2 sentences. The goal is a searchable, compact record — not verbatim transcripts.

**To save**: Read the existing `data/standup/history.md` content (if any). Write the file with the existing content followed by the new session block. If the file doesn't exist **or is empty**, write it with a `# Standup History` header followed by the new session block.

If a session for today's date already exists in the file, count how many `## YYYY-MM-DD` headers for today are already present and write the new block as `## YYYY-MM-DD (N+1)` — e.g. `## 2026-03-29 (2)` for a second run, `## 2026-03-29 (3)` for a third.

Confirm to user: "Session saved to `data/standup/history.md`"

## Notes

- `data/tasks.md` is read-only. This skill never modifies any project file.
- `data/standup/` is gitignored — config and history never leave the machine.
- If the user explicitly provides a question count, that is the full budget. Don't add extra questions.
- Do not ask about private/personal tasks unless they appear in the task board.
- If the task board is empty or has fewer than 3 non-skipped tasks, ask broader "what are you focused on this week" style questions.
