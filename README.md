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
- **Weekly Workflow**: "New Week" button advances your weekly columns with undo support
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

### Weekly Workflow

The "Current" tab is designed around a weekly workflow:

1. Plan tasks in "Following Week" and "Next Week"
2. Move tasks to "This Week" as you plan your week
3. Move active tasks to "In Progress Today"
4. Mark completed tasks in "Done This Week"
5. Click "New Week" to advance everything (done items move to history)

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
