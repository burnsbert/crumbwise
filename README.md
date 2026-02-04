# Crumbwise

A local-first task management app with a visual kanban-style board UI. Tasks are stored in a simple Markdown file, making them easy to read, edit, and version control.

## Features

- **Visual Board UI**: Drag-and-drop cards between columns
- **Markdown Storage**: All tasks stored in a single, human-readable Markdown file
- **Tab Organization**:
  - **Current**: Weekly workflow (Following Week → Next Week → This Week → In Progress → Done)
  - **Research/Ops**: Ongoing projects, problems to solve, things to research
  - **Backlog**: High/Medium/Low priority items
  - **History**: Completed tasks organized by quarter
  - **Settings**: Configure integrations and preferences
- **Weekly Workflow**: "New Week" button advances your weekly columns with undo support
- **Notes Area**: Freeform text area on the Current tab for quick notes
- **16 Color Themes**: Dark and light themes including Minecraft, Knight Rider, Portal 2, Fallout, and more
- **Projects**: Color-coded projects with task assignment via drag-and-drop
- **Google Calendar Integration**: See today's meetings in a timeline sidebar
- **Confluence Sync**: Optional integration to sync tasks to a Confluence page
- **No Cloud Required**: Everything runs locally on your machine

## Installation

### Prerequisites

- Python 3.8+
- pip

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/burnsbert/crumbwise.git
   cd crumbwise
   ```

2. Create a virtual environment (recommended):
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up your task file:
   ```bash
   cp data/tasks.example.md data/tasks.md
   ```

5. Run the server:
   ```bash
   python crumbwise.py
   ```

6. Open your browser to [http://localhost:5050](http://localhost:5050)

## Usage

### Managing Tasks

- **Add a task**: Click the "+ Add task" button at the bottom of any column
- **Edit a task**: Click on a task to edit it inline
- **Move a task**: Drag and drop between columns
- **Delete a task**: Hover over a task and click the X button
- **Add links**: Include URLs in task text - they become clickable links
- **Assign to project**: Drag a task onto a project (or vice versa) to assign it, or use the ◐ button

### Weekly Workflow

The "Current" tab is designed around a weekly workflow:

1. Plan tasks in "Following Week" and "Next Week"
2. Move tasks to "This Week" as you plan your week
3. Move active tasks to "In Progress Today"
4. Mark completed tasks in "Done This Week"
5. Click "New Week" to advance everything (done items move to history)

### Themes

Click the **Theme** button in the header to open the theme selector:

| Theme | Type | Description |
|-------|------|-------------|
| Blue Notes | Dark | Navy blue with orange accents (default) |
| Minecraft | Dark | Creeper green with pixelated styling |
| Knight Rider | Dark | Black with red scanner glow effect |
| Amethyst Dusk | Dark | Rich purples |
| Warm Sand | Light | Warm tan with terracotta accents |
| Ember Glow | Dark | Charcoal with red-orange accents |
| SNES Classic | Dark | Retro gaming gray-purple |
| Crystal Fog | Light | Cool blue-gray tones |
| Super Famicom | Light | Blue-gray console colors |
| Snowy Night | Dark | Dark winter night with icy blue accents |
| Portal 2 | Dark | Abandoned Aperture with split blue/orange logo |
| Fallout | Dark | Pip-Boy terminal green with scanlines |
| Emerald City | Dark | Wizard of Oz inspired with emerald green and gold |
| Whiteboard Post-Its | Light | Colorful post-it notes on whiteboard grid |
| Blueprint | Dark | Technical drawing blue with grid lines |
| Coffee Shop | Light | Warm browns and cream, cozy cafe feel |

Your theme preference is saved automatically.

### Google Calendar Integration (Optional)

Display today's meetings in a timeline sidebar on the Current tab.

**One-time setup** (use a personal Gmail account):

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and sign in with a personal Gmail
2. Create a new project named "Crumbwise"
3. Enable the [Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com)
4. Set up [OAuth consent screen](https://console.cloud.google.com/auth/branding) (External, add your work email as a test user)
5. Create [OAuth credentials](https://console.cloud.google.com/auth/clients) (Web application, redirect URI: `http://localhost:5050/api/calendar/callback`)
6. Copy the Client ID and Client Secret

**Connect your calendar:**

1. Go to Settings tab in Crumbwise
2. Paste your Client ID and Client Secret, click "Save Credentials"
3. Click "Connect Google Calendar"
4. Sign in with your **work account** to access your work calendar

The calendar sidebar shows timed events (not all-day events), with indicators for declined (grayed out) and tentative (?) meetings. Use the arrow buttons to view other days.

### Confluence Integration (Optional)

1. Go to the Settings tab
2. Enter your Confluence page URL
3. Add your Atlassian email
4. Generate an API token at [https://id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
5. Click "Save Settings"
6. Use the "Sync" button to update your Confluence page

## Data Format

Tasks are stored in `data/tasks.md` using standard Markdown:

```markdown
## IN PROGRESS TODAY

- [ ] Current task
- [ ] Another task

## TODO THIS WEEK

- [ ] Weekly task

## DONE THIS WEEK

- [x] Completed task
```

You can edit this file directly with any text editor.

## Configuration

Settings are stored in `data/settings.json` (automatically created when you save settings). This file is gitignored to protect your credentials.

## Development

The codebase is intentionally simple:

- `crumbwise.py` - Flask server and API endpoints
- `static/app.js` - Frontend logic and drag-drop handling
- `static/style.css` - Styling
- `templates/index.html` - Main HTML template
- `data/tasks.md` - Your task data (not tracked in git)

## License

MIT License - see [LICENSE](LICENSE) for details.
