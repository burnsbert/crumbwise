// Crumbwise - Frontend Application

// Sections that are locked - can reorder within but not move items to/from other sections
const LOCKED_SECTIONS = ['PROJECTS', 'COMPLETED PROJECTS'];

// Sections that contain projects with color indices
const PROJECT_SECTIONS = ['PROJECTS', 'COMPLETED PROJECTS'];

const SECTION_CONFIG = {
    current: {
        // Flow: Week After Next -> Next Week -> This Week -> In Progress -> Done This Week
        columns: ['TODO FOLLOWING WEEK', 'TODO NEXT WEEK', 'TODO THIS WEEK', 'IN PROGRESS TODAY', 'DONE THIS WEEK'],
        secondary: ['PROJECTS', 'FOLLOW UPS', 'BLOCKED'],
        hasNotes: true
    },
    research: {
        columns: ['PROBLEMS TO SOLVE', 'THINGS TO RESEARCH', 'RESEARCH IN PROGRESS', 'RESEARCH DONE']
    },
    backlog: {
        columns: ['BACKLOG HIGH PRIORITY', 'BACKLOG MEDIUM PRIORITY', 'BACKLOG LOW PRIORITY']
    },
    history: {
        columns: [] // Will be populated dynamically
    },
    settings: {
        isSettings: true
    }
};

let currentQuarter = null;
let weekDates = {};

let currentTab = 'current';
let tasks = {};
let sortableInstances = [];
let notes = '';
let notesSaveTimeout = null;
let calendarEvents = [];
let calendarConnected = false;
let calendarDateOffset = 0; // 0 = today, -1 = yesterday, 1 = tomorrow, etc.
let calendarVisible = true;
let currentTheme = 1;
let currentDraggedTaskId = null;
let currentDraggedFromSection = null;

const THEME_COUNT = 16;
const THEME_NAMES = {
    1: 'Blue Notes',
    2: 'Minecraft',
    3: 'Knight Rider',
    4: 'Amethyst Dusk',
    5: 'Warm Sand',
    6: 'Ember Glow',
    7: 'SNES Classic',
    8: 'Crystal Fog',
    9: 'Super Famicom',
    10: 'Snowy Night',
    11: 'Portal 2',
    12: 'Fallout',
    13: 'Emerald City',
    14: 'Whiteboard Post-Its',
    15: 'Blueprint',
    16: 'Coffee Shop'
};

const THEME_TYPES = {
    1: 'Dark', 2: 'Dark', 3: 'Dark', 4: 'Dark',
    5: 'Light', 6: 'Dark', 7: 'Dark', 8: 'Light',
    9: 'Light', 10: 'Dark', 11: 'Dark', 12: 'Dark',
    13: 'Dark', 14: 'Light', 15: 'Dark', 16: 'Light'
};

// Preview colors for theme selector (bg, surface, accent)
const THEME_COLORS = {
    1: ['#1a1a2e', '#16213e', '#ea580c'],
    2: ['#1a2618', '#2d4a28', '#7cb342'],
    3: ['#0a0a0a', '#1a1a1a', '#ff1a1a'],
    4: ['#1a1625', '#2d2640', '#a78bfa'],
    5: ['#c9c0b0', '#ddd6c6', '#c2410c'],
    6: ['#1c1917', '#292524', '#f97316'],
    7: ['#1a1a24', '#2d2d3d', '#9d8cd6'],
    8: ['#c8d0d8', '#dce4eb', '#4a6fa5'],
    9: ['#a8a8b8', '#c8c8d4', '#6b5b95'],
    10: ['#0a0c10', '#12151a', '#a8d4ff'],
    11: ['#0d0d0d', '#1a1a1a', '#ff6b00'],
    12: ['#0a0a0a', '#0d1a0d', '#14ff00'],
    13: ['#0f2818', '#1a3a24', '#50c878'],
    14: ['#e8e8e8', '#ffffff', '#fff9b0'],
    15: ['#1a3a5c', '#1e4268', '#7ec8e3'],
    16: ['#f5f0e6', '#ebe4d6', '#8b5a2b']
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadTheme(); // Load theme first to avoid flash
    setupTabs();
    setupNewWeek();
    setupSettings();
    loadTasks();
    loadSettings();
    calendarDateOffset = 0; // Always start on today
    loadCalendarEvents();
    checkCalendarConnectionFromUrl();

    // Auto-refresh calendar display every minute to update past/current event styling
    setInterval(() => {
        renderCalendarSidebar();
    }, 60000);
});

// Theme functions
async function loadTheme() {
    try {
        const response = await fetch('/api/theme');
        const data = await response.json();
        currentTheme = data.theme || 1;
        applyTheme(currentTheme);
    } catch (error) {
        console.error('Failed to load theme:', error);
        applyTheme(1);
    }
}

function applyTheme(themeNum) {
    document.body.setAttribute('data-theme', themeNum);
    updateThemeButton();
}

function showThemeModal() {
    const modal = document.getElementById('theme-modal');
    const grid = document.getElementById('theme-grid');

    // Build theme options
    let html = '';
    for (let i = 1; i <= THEME_COUNT; i++) {
        const colors = THEME_COLORS[i];
        const selected = i === currentTheme ? 'selected' : '';
        const gradient = `linear-gradient(135deg, ${colors[0]} 0%, ${colors[1]} 50%, ${colors[2]} 100%)`;

        html += `
            <button class="theme-option ${selected}" onclick="selectTheme(${i})" data-theme-num="${i}">
                <div class="theme-preview" style="background: ${gradient}"></div>
                <div class="theme-info">
                    <div class="theme-name">${THEME_NAMES[i]}</div>
                    <div class="theme-type">${THEME_TYPES[i]}</div>
                </div>
            </button>
        `;
    }

    grid.innerHTML = html;
    modal.classList.remove('hidden');
}

function closeThemeModal() {
    document.getElementById('theme-modal').classList.add('hidden');
}

async function selectTheme(themeNum) {
    currentTheme = themeNum;
    applyTheme(currentTheme);

    // Update selection in modal
    document.querySelectorAll('.theme-option').forEach(opt => {
        opt.classList.toggle('selected', parseInt(opt.dataset.themeNum) === themeNum);
    });

    try {
        await fetch('/api/theme', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme: currentTheme })
        });
    } catch (error) {
        console.error('Failed to save theme:', error);
    }

    closeThemeModal();
}

function updateThemeButton() {
    const btn = document.getElementById('theme-btn');
    if (btn) {
        btn.textContent = THEME_NAMES[currentTheme];
    }
}

function setupTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentTab = tab.dataset.tab;
            renderBoard();
        });
    });
}

async function loadTasks() {
    try {
        // Fetch current quarter, tasks, undo status, week dates, and notes in parallel
        const [tasksResponse, quarterResponse, undoResponse, weekDatesResponse, notesResponse] = await Promise.all([
            fetch('/api/tasks'),
            fetch('/api/current-quarter'),
            fetch('/api/can-undo'),
            fetch('/api/week-dates'),
            fetch('/api/notes')
        ]);
        tasks = await tasksResponse.json();
        const quarterData = await quarterResponse.json();
        const undoData = await undoResponse.json();
        weekDates = await weekDatesResponse.json();
        const notesData = await notesResponse.json();
        currentQuarter = quarterData.quarter;
        notes = notesData.notes || '';

        // Build history columns dynamically from task data
        updateHistoryColumns();

        // Check if any tasks are assigned to projects (for Post-It theme styling)
        updateProjectAssignmentClass();

        renderBoard();
        updateUndoButton(undoData.canUndo);
    } catch (error) {
        console.error('Failed to load tasks:', error);
    }
}

function updateHistoryColumns() {
    // Find all history sections (DONE Q* and DONE 20*)
    const doneColumns = Object.keys(tasks)
        .filter(section => section.startsWith('DONE Q') || section.startsWith('DONE 20'))
        .filter(section => section !== 'DONE THIS WEEK')
        .sort((a, b) => {
            // Current quarter first, then by year/quarter descending
            if (a === currentQuarter) return -1;
            if (b === currentQuarter) return 1;
            // Sort quarters: Q4 > Q3 > Q2 > Q1, newer years first
            return b.localeCompare(a);
        });

    // COMPLETED PROJECTS goes second (after current quarter)
    if (doneColumns.length > 0) {
        SECTION_CONFIG.history.columns = [doneColumns[0], 'COMPLETED PROJECTS', ...doneColumns.slice(1)];
    } else {
        SECTION_CONFIG.history.columns = ['COMPLETED PROJECTS'];
    }
}

function renderBoard() {
    const board = document.getElementById('board');
    const followupsArea = document.getElementById('followups-area');
    const followupsColumns = document.getElementById('followups-columns');
    const config = SECTION_CONFIG[currentTab];

    // Cleanup existing sortables
    sortableInstances.forEach(s => s.destroy());
    sortableInstances = [];

    // Handle settings tab specially
    if (config.isSettings) {
        board.className = 'board settings-view';
        board.innerHTML = renderSettingsPage();
        followupsArea.classList.add('hidden');
        document.getElementById('calendar-sidebar')?.classList.add('hidden');
        loadSettingsIntoForm();
        return;
    }

    // Add class for current tab styling
    board.className = currentTab === 'current' ? 'board current-tab' : 'board';

    // Render main columns
    board.innerHTML = config.columns
        .map(section => renderColumn(section))
        .join('');

    // Render secondary area for Current tab
    if (config.secondary && config.secondary.length > 0) {
        followupsArea.classList.remove('hidden');
        let secondaryHtml = config.secondary
            .map(section => renderColumn(section, true))
            .join('');

        // Add notes area if this tab has it
        if (config.hasNotes) {
            secondaryHtml += renderNotesArea();
        }

        followupsColumns.innerHTML = secondaryHtml;

        // Setup notes auto-save if notes area exists
        const notesTextarea = document.getElementById('notes-textarea');
        if (notesTextarea) {
            notesTextarea.value = notes;
            notesTextarea.addEventListener('input', handleNotesInput);
        }
    } else {
        followupsArea.classList.add('hidden');
        followupsColumns.innerHTML = '';
    }

    // Initialize sortable on all column-tasks
    document.querySelectorAll('.column-tasks').forEach(el => {
        const section = el.closest('.column')?.dataset.section;
        const isLocked = LOCKED_SECTIONS.includes(section);

        const sortable = new Sortable(el, {
            // Locked sections get their own group so items can't move to/from other sections
            group: isLocked ? `locked-${section}` : 'tasks',
            animation: 150,
            ghostClass: 'sortable-ghost',
            chosenClass: 'sortable-chosen',
            dragClass: 'sortable-drag',
            onStart: (evt) => {
                currentDraggedTaskId = evt.item.dataset.id;
                currentDraggedFromSection = evt.from.closest('.column')?.dataset.section;
            },
            onEnd: handleDragEnd
        });
        sortableInstances.push(sortable);
    });

    // Update calendar sidebar visibility
    renderCalendarSidebar();

    // Setup header drop zones - dropping on header adds to end of section
    document.querySelectorAll('.column-header').forEach(header => {
        const column = header.closest('.column');
        header.addEventListener('dragover', (e) => {
            e.preventDefault();
            header.classList.add('header-drop-target');
        });
        header.addEventListener('dragleave', () => {
            header.classList.remove('header-drop-target');
        });
        header.addEventListener('drop', async (e) => {
            e.preventDefault();
            header.classList.remove('header-drop-target');

            // Use the tracked dragged task ID
            if (!currentDraggedTaskId) return;

            const taskId = currentDraggedTaskId;
            const section = header.closest('.column').dataset.section;
            const fromSection = currentDraggedFromSection;

            // Clear BEFORE async work so handleDragEnd sees null and exits early
            currentDraggedTaskId = null;
            currentDraggedFromSection = null;

            // Block cross-section moves involving locked sections
            if (fromSection !== section) {
                if (LOCKED_SECTIONS.includes(fromSection) || LOCKED_SECTIONS.includes(section)) {
                    return;
                }
            }

            // Count tasks excluding the one being moved (in case it's from same section)
            const sectionTasks = (tasks[section] || []).filter(t => t.id !== taskId);

            try {
                await fetch('/api/tasks/reorder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        taskId,
                        section,
                        index: sectionTasks.length + 1  // Put at end
                    })
                });
                await loadTasks();
            } catch (error) {
                console.error('Failed to move to section:', error);
                await loadTasks();
            }
        });
    });

    // Setup project hover highlighting
    setupProjectHoverHighlighting();

    // Setup project drop zones for task assignment
    setupProjectDropZones();
}

function setupProjectHoverHighlighting() {
    // Find all project cards
    document.querySelectorAll('[data-section="PROJECTS"] .card, [data-section="COMPLETED PROJECTS"] .card').forEach(projectCard => {
        const projectId = projectCard.dataset.id;

        projectCard.addEventListener('mouseenter', () => {
            // Highlight all tasks assigned to this project
            document.querySelectorAll(`.card[data-assigned-project="${projectId}"]`).forEach(taskCard => {
                taskCard.classList.add('project-highlight');
            });
            projectCard.classList.add('project-highlight');
        });

        projectCard.addEventListener('mouseleave', () => {
            // Remove highlight
            document.querySelectorAll('.card.project-highlight').forEach(card => {
                card.classList.remove('project-highlight');
            });
        });
    });
}

function setupProjectDropZones() {
    // Use event delegation on the board for project assignment drops
    // This ensures new cards automatically get the handlers
    const board = document.getElementById('board');
    const followups = document.getElementById('followups-columns');

    // Remove old handlers if any (to prevent duplicates)
    board.removeEventListener('dragover', handleProjectDragOver);
    board.removeEventListener('dragleave', handleProjectDragLeave);
    board.removeEventListener('drop', handleProjectDrop);
    followups?.removeEventListener('dragover', handleProjectDragOver);
    followups?.removeEventListener('dragleave', handleProjectDragLeave);
    followups?.removeEventListener('drop', handleProjectDrop);

    // Add delegated handlers
    board.addEventListener('dragover', handleProjectDragOver);
    board.addEventListener('dragleave', handleProjectDragLeave);
    board.addEventListener('drop', handleProjectDrop);
    followups?.addEventListener('dragover', handleProjectDragOver);
    followups?.addEventListener('dragleave', handleProjectDragLeave);
    followups?.addEventListener('drop', handleProjectDrop);
}

function handleProjectDragOver(e) {
    const card = e.target.closest('.card');
    if (!card) return;

    const cardSection = card.closest('.column')?.dataset.section;
    const cardId = card.dataset.id;

    // Case 1: Dragging a task over a project card
    if (cardSection === 'PROJECTS' && currentDraggedTaskId && !PROJECT_SECTIONS.includes(currentDraggedFromSection)) {
        e.preventDefault();
        card.classList.add('drop-target');
    }

    // Case 2: Dragging a project over a task card
    if (!PROJECT_SECTIONS.includes(cardSection) && currentDraggedTaskId && currentDraggedFromSection === 'PROJECTS') {
        e.preventDefault();
        card.classList.add('drop-target');
    }
}

function handleProjectDragLeave(e) {
    const card = e.target.closest('.card');
    if (card) {
        card.classList.remove('drop-target');
    }
}

async function handleProjectDrop(e) {
    const card = e.target.closest('.card');
    if (!card) return;

    const cardSection = card.closest('.column')?.dataset.section;
    const cardId = card.dataset.id;

    // Case 1: Dropping a task on a project - assign task to project
    if (cardSection === 'PROJECTS' && currentDraggedTaskId && !PROJECT_SECTIONS.includes(currentDraggedFromSection)) {
        e.preventDefault();
        e.stopPropagation();
        card.classList.remove('drop-target');

        const projectId = cardId;
        const taskId = currentDraggedTaskId;

        // Clear BEFORE async operation to prevent race with handleDragEnd
        currentDraggedTaskId = null;
        currentDraggedFromSection = null;

        await assignToProject(taskId, projectId);
    }

    // Case 2: Dropping a project on a task - assign task to project
    if (!PROJECT_SECTIONS.includes(cardSection) && currentDraggedTaskId && currentDraggedFromSection === 'PROJECTS') {
        e.preventDefault();
        e.stopPropagation();
        card.classList.remove('drop-target');

        const projectId = currentDraggedTaskId;
        const taskId = cardId;

        // Clear BEFORE async operation to prevent race with handleDragEnd
        currentDraggedTaskId = null;
        currentDraggedFromSection = null;

        await assignToProject(taskId, projectId);
    }
}

function renderSettingsPage() {
    return `
        <div class="settings-page">
            <div class="settings-card">
                <h2>Google Calendar</h2>
                <div id="google-calendar-status" class="calendar-status">
                    <!-- Status will be populated by JS -->
                </div>
            </div>

            <div class="settings-card" style="margin-top: 16px;">
                <h2>Confluence Integration</h2>
                <p class="settings-help">Sync your tasks to a Confluence page. You'll need an API token from <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank">Atlassian Account Settings</a>.</p>

                <div class="form-group">
                    <label for="confluence-url">Page URL</label>
                    <input type="text" id="confluence-url" placeholder="https://yoursite.atlassian.net/wiki/spaces/.../pages/edit-v2/123456">
                </div>

                <div class="form-group">
                    <label for="confluence-email">Email</label>
                    <input type="email" id="confluence-email" placeholder="your.email@company.com">
                </div>

                <div class="form-group">
                    <label for="confluence-token">API Token</label>
                    <input type="password" id="confluence-token" placeholder="Enter new token to change">
                    <span id="token-status" class="token-status"></span>
                </div>

                <div class="settings-actions">
                    <button id="save-settings-btn" class="action-btn confirm">Save Settings</button>
                </div>
            </div>
        </div>
    `;
}

function renderNotesArea() {
    return `
        <div class="notes-area">
            <div class="column-header">
                <span>NOTES</span>
            </div>
            <textarea id="notes-textarea" class="notes-textarea" placeholder="Add notes here..."></textarea>
        </div>
    `;
}

function handleNotesInput(event) {
    notes = event.target.value;

    // Debounce save - wait 5 seconds after typing stops
    if (notesSaveTimeout) {
        clearTimeout(notesSaveTimeout);
    }
    notesSaveTimeout = setTimeout(saveNotes, 5000);
}

async function saveNotes() {
    try {
        await fetch('/api/notes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ notes })
        });
    } catch (error) {
        console.error('Failed to save notes:', error);
    }
}

function renderColumn(section, isSecondary = false) {
    const sectionTasks = tasks[section] || [];
    const taskCards = sectionTasks
        .map(task => renderCard(task, section))
        .join('');

    const columnClass = isSecondary ? 'column secondary' : 'column';
    const sectionClass = (isSecondary && !PROJECT_SECTIONS.includes(section)) || section === 'DONE THIS WEEK' || section === 'RESEARCH DONE' || section === currentQuarter || section === 'COMPLETED PROJECTS' ? 'blocked-section' :
                         section === 'IN PROGRESS TODAY' || section === 'RESEARCH IN PROGRESS' || section === 'PROJECTS' ? 'current-period' :
                         (section.startsWith('DONE Q') || section.startsWith('DONE 20')) && section !== currentQuarter && section !== 'DONE THIS WEEK' ? 'past-period' : '';

    // Add date banner for TODO week sections
    const dateBanner = weekDates[section] ? `<div class="week-date-banner">${weekDates[section]}</div>` : '';

    return `
        <div class="${columnClass} ${sectionClass}" data-section="${section}">
            <div class="column-header">
                <span>${section}</span>
                <span class="column-count">${sectionTasks.length}</span>
            </div>
            ${dateBanner}
            <div class="column-tasks" data-section="${section}">
                ${taskCards}
            </div>
            <div class="add-task">
                <button class="add-task-btn" onclick="showAddTask(this, '${section}')">+ Add task</button>
            </div>
        </div>
    `;
}

function renderCard(task, section) {
    const completedClass = task.completed ? 'completed' : '';
    const textWithLinks = linkify(escapeHtml(task.text));

    // Determine which move button to show based on section
    // Only main columns + BLOCKED get move buttons (not PROJECTS or FOLLOW UPS)
    const currentWithMove = [...SECTION_CONFIG.current.columns, 'BLOCKED'];
    const backlogSections = SECTION_CONFIG.backlog.columns;

    let moveButton = '';
    if (currentWithMove.includes(section)) {
        moveButton = `<button class="card-btn move" onclick="event.stopPropagation(); showMoveToBacklog('${task.id}')" title="Move to Backlog">&gt;&gt;</button>`;
    } else if (backlogSections.includes(section)) {
        moveButton = `<button class="card-btn move" onclick="event.stopPropagation(); showMoveToCurrent('${task.id}')" title="Move to Current">&lt;&lt;</button>`;
    } else if (section === 'PROJECTS') {
        moveButton = `<button class="card-btn move complete-project" onclick="event.stopPropagation(); completeProject('${task.id}')" title="Complete Project">&gt;&gt;</button>`;
    } else if (section === 'COMPLETED PROJECTS') {
        moveButton = `<button class="card-btn move uncomplete-project" onclick="event.stopPropagation(); uncompleteProject('${task.id}')" title="Reactivate Project">&lt;&lt;</button>`;
    }

    // Assign project button for non-project tasks
    let assignButton = '';
    if (!PROJECT_SECTIONS.includes(section)) {
        assignButton = `<button class="card-btn assign-project" onclick="event.stopPropagation(); showAssignProjectModal('${task.id}')" title="Assign to project">◐</button>`;
    }

    // Color assignment button for project cards
    let colorButton = '';
    if (section === 'PROJECTS') {
        colorButton = `<button class="card-btn assign-color" onclick="event.stopPropagation(); showAssignColorModal('${task.id}', ${task.color_index || 1})" title="Change color">●</button>`;
    }

    // Add color stripe for project sections OR assigned tasks
    const isProject = PROJECT_SECTIONS.includes(section);
    let colorIndex = null;
    let projectStripe = '';
    let projectClass = '';

    if (isProject) {
        colorIndex = task.color_index || 1;
        projectStripe = `<div class="project-stripe" data-color="${colorIndex}"></div>`;
        projectClass = 'project-card';
    } else if (task.assigned_project) {
        // Look up the project's color
        colorIndex = getProjectColorIndex(task.assigned_project);
        if (colorIndex) {
            projectStripe = `<div class="project-stripe" data-color="${colorIndex}"></div>`;
            projectClass = 'project-card assigned-task';
        }
    }

    // Add data attribute for project color (used by Post-It theme)
    const projectColorAttr = colorIndex ? `data-project-color="${colorIndex}"` : '';

    return `
        <div class="card ${completedClass} ${projectClass}" data-id="${task.id}" data-assigned-project="${task.assigned_project || ''}" ${projectColorAttr} onclick="handleCardClick(event, '${task.id}')">
            ${projectStripe}
            <div class="card-actions">
                ${colorButton}
                ${assignButton}
                ${moveButton}
                <button class="card-btn delete" onclick="event.stopPropagation(); deleteCard('${task.id}')" title="Delete">×</button>
            </div>
            <div class="card-text">${textWithLinks}</div>
        </div>
    `;
}

// Get a project's color index by its ID
function getProjectColorIndex(projectId) {
    for (const sectionName of PROJECT_SECTIONS) {
        const sectionTasks = tasks[sectionName] || [];
        for (const project of sectionTasks) {
            if (project.id === projectId) {
                return project.color_index || 1;
            }
        }
    }
    return null;
}

// Update body class based on whether any tasks are assigned to projects
// Used by Post-It theme to decide between uniform yellow vs rotating colors
function updateProjectAssignmentClass() {
    const hasAssignedTasks = Object.values(tasks).some(sectionTasks =>
        sectionTasks.some(task => task.assigned_project)
    );
    document.body.classList.toggle('has-project-assignments', hasAssignedTasks);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function linkify(text) {
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    return text.replace(urlRegex, '<a href="$1" target="_blank" rel="noopener">$1</a>');
}

// Add task
function showAddTask(btn, section) {
    const container = btn.parentElement;
    container.innerHTML = `
        <input type="text" class="add-task-input" placeholder="Enter task..."
               onkeydown="handleAddTaskKey(event, '${section}')"
               onblur="hideAddTask(this, '${section}')">
    `;
    container.querySelector('input').focus();
}

function hideAddTask(input, section) {
    setTimeout(() => {
        const container = input.parentElement;
        if (container) {
            container.innerHTML = `
                <button class="add-task-btn" onclick="showAddTask(this, '${section}')">+ Add task</button>
            `;
        }
    }, 150);
}

async function handleAddTaskKey(event, section) {
    if (event.key === 'Enter' && event.target.value.trim()) {
        const text = event.target.value.trim();
        event.target.disabled = true;

        try {
            const response = await fetch('/api/tasks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ section, text })
            });

            if (response.ok) {
                await loadTasks();
            }
        } catch (error) {
            console.error('Failed to add task:', error);
        }
    } else if (event.key === 'Escape') {
        hideAddTask(event.target, section);
    }
}

// Handle card click - edit unless clicking link or button
function handleCardClick(event, taskId) {
    // Don't edit if clicking a link or button
    if (event.target.tagName === 'A' || event.target.tagName === 'BUTTON') {
        return;
    }
    // Don't edit if already editing
    const card = document.querySelector(`.card[data-id="${taskId}"]`);
    if (card.classList.contains('editing')) {
        return;
    }
    editCard(taskId);
}

// Edit card
function editCard(taskId) {
    const card = document.querySelector(`.card[data-id="${taskId}"]`);
    const textDiv = card.querySelector('.card-text');
    const currentText = findTaskById(taskId)?.text || '';

    card.classList.add('editing');
    textDiv.innerHTML = `
        <textarea class="card-edit-input" onkeydown="handleEditKey(event, '${taskId}')"
                  onblur="saveEdit('${taskId}')">${escapeHtml(currentText)}</textarea>
    `;

    const textarea = card.querySelector('textarea');
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);

    // Auto-resize
    textarea.style.height = 'auto';
    textarea.style.height = textarea.scrollHeight + 'px';
    textarea.addEventListener('input', () => {
        textarea.style.height = 'auto';
        textarea.style.height = textarea.scrollHeight + 'px';
    });
}

function handleEditKey(event, taskId) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        saveEdit(taskId);
    } else if (event.key === 'Escape') {
        loadTasks(); // Reload to cancel edit
    }
}

async function saveEdit(taskId) {
    const card = document.querySelector(`.card[data-id="${taskId}"]`);
    if (!card || !card.classList.contains('editing')) return;

    const textarea = card.querySelector('textarea');
    const newText = textarea.value.trim();

    if (!newText) {
        await deleteCard(taskId);
        return;
    }

    try {
        await fetch(`/api/tasks/${taskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: newText })
        });
        await loadTasks();
    } catch (error) {
        console.error('Failed to save edit:', error);
    }
}

// Delete card
async function deleteCard(taskId) {
    if (!confirm('Delete this task?')) return;

    try {
        await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
        await loadTasks();
    } catch (error) {
        console.error('Failed to delete task:', error);
    }
}

// Project completion (moves between PROJECTS and COMPLETED PROJECTS)
async function completeProject(taskId) {
    try {
        await fetch(`/api/tasks/${taskId}/complete`, { method: 'POST' });
        await loadTasks();
    } catch (error) {
        console.error('Failed to complete project:', error);
    }
}

async function uncompleteProject(taskId) {
    try {
        await fetch(`/api/tasks/${taskId}/complete`, { method: 'POST' });
        await loadTasks();
    } catch (error) {
        console.error('Failed to uncomplete project:', error);
    }
}

// Project assignment
async function assignToProject(taskId, projectId) {
    try {
        // Save scroll positions before reload
        const scrollPositions = saveScrollPositions();

        await fetch(`/api/tasks/${taskId}/assign`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ projectId })
        });
        await loadTasks();

        // Restore scroll positions after reload
        restoreScrollPositions(scrollPositions);
    } catch (error) {
        console.error('Failed to assign to project:', error);
    }
}

// Save scroll positions of all scrollable column containers
function saveScrollPositions() {
    const positions = {};
    document.querySelectorAll('.column-tasks').forEach(el => {
        const section = el.dataset.section;
        if (section && el.scrollTop > 0) {
            positions[section] = el.scrollTop;
        }
    });
    // Also save the main board scroll
    const board = document.getElementById('board');
    if (board && board.scrollLeft > 0) {
        positions['__board__'] = board.scrollLeft;
    }
    return positions;
}

// Restore scroll positions after re-render
function restoreScrollPositions(positions) {
    requestAnimationFrame(() => {
        document.querySelectorAll('.column-tasks').forEach(el => {
            const section = el.dataset.section;
            if (section && positions[section]) {
                el.scrollTop = positions[section];
            }
        });
        const board = document.getElementById('board');
        if (board && positions['__board__']) {
            board.scrollLeft = positions['__board__'];
        }
    });
}

async function unassignFromProject(taskId) {
    try {
        const scrollPositions = saveScrollPositions();
        await fetch(`/api/tasks/${taskId}/unassign`, { method: 'POST' });
        await loadTasks();
        restoreScrollPositions(scrollPositions);
    } catch (error) {
        console.error('Failed to unassign from project:', error);
    }
}

// Show modal to assign task to a project
function showAssignProjectModal(taskId) {
    // Get all active projects
    const projects = tasks['PROJECTS'] || [];

    // Find current assignment
    let currentAssignment = null;
    for (const section of Object.values(tasks)) {
        const task = section.find(t => t.id === taskId);
        if (task) {
            currentAssignment = task.assigned_project;
            break;
        }
    }

    // Build project options
    const projectOptions = projects.map(p => {
        const isSelected = currentAssignment === p.id ? 'selected' : '';
        return `
            <div class="project-option ${isSelected}" data-project-id="${p.id}" onclick="selectProjectOption(this, '${taskId}', '${p.id}')">
                <div class="project-stripe" data-color="${p.color_index || 1}"></div>
                <span>${escapeHtml(p.text)}</span>
            </div>
        `;
    }).join('');

    const noProjectSelected = !currentAssignment ? 'selected' : '';

    const modalHtml = `
        <div id="assign-project-modal" class="modal">
            <div class="modal-content assign-project-modal-content">
                <h3>Assign to Project</h3>
                <div class="project-options">
                    <div class="project-option ${noProjectSelected}" data-project-id="" onclick="selectProjectOption(this, '${taskId}', '')">
                        <div class="no-project-indicator">○</div>
                        <span>No Project</span>
                    </div>
                    ${projectOptions}
                </div>
                <div class="modal-actions">
                    <button class="action-btn" onclick="closeAssignProjectModal()">Cancel</button>
                </div>
            </div>
        </div>
    `;

    // Remove existing modal if any
    document.getElementById('assign-project-modal')?.remove();

    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

async function selectProjectOption(element, taskId, projectId) {
    // Update selection visually
    document.querySelectorAll('.project-option').forEach(el => el.classList.remove('selected'));
    element.classList.add('selected');

    // Save scroll positions before any changes
    const scrollPositions = saveScrollPositions();

    // Assign or unassign (these functions handle their own scroll preservation,
    // but we close modal first to avoid issues)
    closeAssignProjectModal();

    if (projectId) {
        await fetch(`/api/tasks/${taskId}/assign`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ projectId })
        });
    } else {
        await fetch(`/api/tasks/${taskId}/unassign`, { method: 'POST' });
    }

    await loadTasks();
    restoreScrollPositions(scrollPositions);
}

function closeAssignProjectModal() {
    document.getElementById('assign-project-modal')?.remove();
}

// Show modal to assign color to a project
function showAssignColorModal(projectId, currentColor) {
    // Build color options (1-10)
    const colorOptions = [];
    for (let i = 1; i <= 10; i++) {
        const isSelected = currentColor === i ? 'selected' : '';
        colorOptions.push(`
            <div class="color-option ${isSelected}" data-color="${i}" onclick="selectColorOption('${projectId}', ${i})">
                <div class="color-swatch" data-color="${i}"></div>
            </div>
        `);
    }

    const modalHtml = `
        <div id="assign-color-modal" class="modal">
            <div class="modal-content assign-color-modal-content">
                <h3>Assign Color</h3>
                <div class="color-options">
                    ${colorOptions.join('')}
                </div>
                <div class="modal-actions">
                    <button class="action-btn" onclick="closeAssignColorModal()">Cancel</button>
                </div>
            </div>
        </div>
    `;

    // Remove existing modal if any
    document.getElementById('assign-color-modal')?.remove();

    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

async function selectColorOption(projectId, colorIndex) {
    const scrollPositions = saveScrollPositions();
    closeAssignColorModal();

    try {
        await fetch(`/api/tasks/${projectId}/color`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ color_index: colorIndex })
        });
        await loadTasks();
        restoreScrollPositions(scrollPositions);
    } catch (error) {
        console.error('Failed to change color:', error);
    }
}

function closeAssignColorModal() {
    document.getElementById('assign-color-modal')?.remove();
}

// Drag and drop
async function handleDragEnd(event) {
    // Skip if already handled by header drop
    if (!currentDraggedTaskId) return;

    const taskId = event.item.dataset.id;
    const fromSection = event.from.dataset.section;
    const newSection = event.to.dataset.section;
    const newIndex = event.newIndex;

    currentDraggedTaskId = null;  // Clear after handling
    currentDraggedFromSection = null;

    // Block cross-section moves involving locked sections (extra safety)
    if (fromSection !== newSection) {
        if (LOCKED_SECTIONS.includes(fromSection) || LOCKED_SECTIONS.includes(newSection)) {
            await loadTasks(); // Reload to reset state
            return;
        }
    }

    try {
        await fetch('/api/tasks/reorder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                taskId,
                section: newSection,
                index: newIndex
            })
        });
        // Update local state
        await loadTasks();
    } catch (error) {
        console.error('Failed to reorder:', error);
        await loadTasks(); // Reload to fix state
    }
}

// Helper
function findTaskById(taskId) {
    for (const section of Object.values(tasks)) {
        const task = section.find(t => t.id === taskId);
        if (task) return task;
    }
    return null;
}

// New Week functionality
function setupNewWeek() {
    const newWeekBtn = document.getElementById('new-week-btn');
    const undoBtn = document.getElementById('undo-btn');
    const modal = document.getElementById('new-week-modal');
    const confirmBtn = document.getElementById('confirm-new-week');
    const cancelBtn = document.getElementById('cancel-new-week');

    newWeekBtn.addEventListener('click', () => {
        modal.classList.remove('hidden');
    });

    cancelBtn.addEventListener('click', () => {
        modal.classList.add('hidden');
    });

    confirmBtn.addEventListener('click', async () => {
        modal.classList.add('hidden');
        await executeNewWeek();
    });

    undoBtn.addEventListener('click', async () => {
        if (!undoBtn.classList.contains('disabled')) {
            await undoNewWeek();
        }
    });

    // Close modal on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.add('hidden');
        }
    });
}

async function executeNewWeek() {
    try {
        const response = await fetch('/api/new-week', { method: 'POST' });
        const data = await response.json();

        if (data.success) {
            await loadTasks();
            updateUndoButton(true);
        }
    } catch (error) {
        console.error('Failed to execute new week:', error);
    }
}

async function undoNewWeek() {
    try {
        const response = await fetch('/api/undo-new-week', { method: 'POST' });
        const data = await response.json();

        if (data.success) {
            await loadTasks();
            updateUndoButton(false);
        }
    } catch (error) {
        console.error('Failed to undo:', error);
    }
}

async function checkUndoAvailable() {
    try {
        const response = await fetch('/api/can-undo');
        const data = await response.json();
        updateUndoButton(data.canUndo);
    } catch (error) {
        console.error('Failed to check undo status:', error);
    }
}

function updateUndoButton(canUndo) {
    const undoBtn = document.getElementById('undo-btn');
    if (canUndo) {
        undoBtn.classList.remove('disabled');
    } else {
        undoBtn.classList.add('disabled');
    }
}

// Settings functionality
function setupSettings() {
    const syncBtn = document.getElementById('sync-btn');

    // Use event delegation for settings buttons since they're dynamically rendered
    document.addEventListener('click', async (e) => {
        if (e.target.id === 'save-settings-btn') {
            await saveSettings();
        }
        if (e.target.id === 'save-google-config-btn') {
            await saveGoogleConfig();
        }
        if (e.target.id === 'connect-google-btn') {
            await connectGoogleCalendar();
        }
        if (e.target.id === 'disconnect-google-btn') {
            await disconnectGoogleCalendar();
        }
    });

    syncBtn.addEventListener('click', async () => {
        if (!syncBtn.classList.contains('disabled')) {
            await syncToConfluence();
        }
    });
}

async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const settings = await response.json();
        updateSyncButton(settings);
    } catch (error) {
        console.error('Failed to load settings:', error);
    }
}

function loadSettingsIntoForm() {
    fetch('/api/settings')
        .then(res => res.json())
        .then(settings => {
            document.getElementById('confluence-url').value = settings.confluence_url || '';
            document.getElementById('confluence-email').value = settings.confluence_email || '';
            document.getElementById('confluence-token').value = '';

            const tokenStatus = document.getElementById('token-status');
            if (settings.confluence_token_set) {
                tokenStatus.textContent = 'Token is configured';
            } else {
                tokenStatus.textContent = '';
            }

            // Load calendar status (shows appropriate UI based on state)
            loadGoogleCalendarStatus();
        });
}

async function saveSettings() {
    const url = document.getElementById('confluence-url').value.trim();
    const email = document.getElementById('confluence-email').value.trim();
    const token = document.getElementById('confluence-token').value;

    const data = {
        confluence_url: url,
        confluence_email: email
    };

    if (token) {
        data.confluence_token = token;
    }

    try {
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (response.ok) {
            await loadSettings();
        }
    } catch (error) {
        console.error('Failed to save settings:', error);
    }
}

function updateSyncButton(settings) {
    const syncBtn = document.getElementById('sync-btn');
    const isConfigured = settings.confluence_url &&
                         settings.confluence_email &&
                         settings.confluence_token_set;

    if (isConfigured) {
        syncBtn.classList.remove('disabled');
    } else {
        syncBtn.classList.add('disabled');
    }
}

// Google Calendar functions
async function loadGoogleCalendarStatus() {
    const statusDiv = document.getElementById('google-calendar-status');
    if (!statusDiv) return;

    try {
        const response = await fetch('/api/calendar/status');
        const data = await response.json();

        if (data.needs_reconnect) {
            statusDiv.innerHTML = `
                <div class="calendar-connected">
                    <span class="status-indicator disconnected"></span>
                    <span>Calendar session expired</span>
                    <button id="connect-google-btn" class="action-btn confirm" style="margin-left: 12px;">Reconnect</button>
                    <button id="disconnect-google-btn" class="action-btn cancel" style="margin-left: 8px;">Disconnect</button>
                </div>
            `;
        } else if (data.connected) {
            statusDiv.innerHTML = `
                <div class="calendar-connected">
                    <span class="status-indicator connected"></span>
                    <span>Calendar connected</span>
                    <button id="disconnect-google-btn" class="action-btn cancel" style="margin-left: 12px;">Disconnect</button>
                </div>
            `;
        } else if (data.has_config) {
            statusDiv.innerHTML = `
                <p class="settings-help">Credentials saved. Click below to connect, then sign in with your <strong>work account</strong> to see your work calendar.</p>
                <div class="settings-actions">
                    <button id="connect-google-btn" class="action-btn confirm">Connect Google Calendar</button>
                </div>
            `;
        } else {
            statusDiv.innerHTML = `
                <p class="settings-help">Display today's meetings in a timeline on the Current tab.</p>
                <details class="setup-instructions">
                    <summary>Setup Instructions (one-time, use a personal Gmail)</summary>
                    <p class="setup-note">Use a <strong>personal Gmail account</strong> (not your work account) to create the app. You'll sign in with your work account later to access your work calendar.</p>
                    <ol>
                        <li>Sign into <a href="https://console.cloud.google.com/" target="_blank">Google Cloud Console</a> with a personal Gmail</li>
                        <li>Click the project dropdown at the top → "New Project" → name it "Crumbwise" → Create</li>
                        <li>Go to <a href="https://console.cloud.google.com/apis/library/calendar-json.googleapis.com" target="_blank">Calendar API</a> → click "Enable"</li>
                        <li>Go to <a href="https://console.cloud.google.com/auth/branding" target="_blank">OAuth consent screen</a> → Branding → click "Get Started"</li>
                        <li>Enter App name "Crumbwise", your email → Next → select "External" → Next → your email again → Next → agree to policy → Create</li>
                        <li>Go to <a href="https://console.cloud.google.com/auth/audience" target="_blank">OAuth Audience</a> → under "Test users" click "Add users" → add your <strong>work email</strong> → Save</li>
                        <li>Go to <a href="https://console.cloud.google.com/auth/clients" target="_blank">OAuth Clients</a> → "Create Client" → select "Web application"</li>
                        <li>Under "Authorized redirect URIs" → Add URI → <code>http://localhost:5050/api/calendar/callback</code> → Create</li>
                        <li>Copy the Client ID and Client Secret below (secret only shown once!)</li>
                    </ol>
                </details>

                <div class="form-group">
                    <label for="google-client-id">Client ID</label>
                    <input type="text" id="google-client-id" placeholder="xxxxx.apps.googleusercontent.com">
                </div>

                <div class="form-group">
                    <label for="google-client-secret">Client Secret</label>
                    <input type="password" id="google-client-secret" placeholder="Enter client secret">
                </div>

                <div class="settings-actions">
                    <button id="save-google-config-btn" class="action-btn confirm">Save Credentials</button>
                </div>
            `;
        }
    } catch (error) {
        console.error('Failed to load calendar status:', error);
        statusDiv.innerHTML = `<span class="text-muted">Failed to check calendar status</span>`;
    }
}

async function saveGoogleConfig() {
    const clientId = document.getElementById('google-client-id').value.trim();
    const clientSecret = document.getElementById('google-client-secret').value.trim();

    if (!clientId || !clientSecret) {
        alert('Please enter both Client ID and Client Secret');
        return;
    }

    try {
        const response = await fetch('/api/calendar/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_id: clientId, client_secret: clientSecret })
        });

        if (response.ok) {
            await loadGoogleCalendarStatus();
        }
    } catch (error) {
        console.error('Failed to save config:', error);
    }
}

async function connectGoogleCalendar() {
    try {
        const response = await fetch('/api/calendar/auth-url');
        const data = await response.json();

        if (data.auth_url) {
            window.location.href = data.auth_url;
        } else if (data.error) {
            alert('Error: ' + data.error);
        }
    } catch (error) {
        console.error('Failed to get auth URL:', error);
    }
}

async function disconnectGoogleCalendar() {
    if (!confirm('Disconnect Google Calendar?')) return;

    try {
        await fetch('/api/calendar/disconnect', { method: 'POST' });
        await loadGoogleCalendarStatus();
        await loadCalendarEvents();
    } catch (error) {
        console.error('Failed to disconnect:', error);
    }
}

function checkCalendarConnectionFromUrl() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('calendar_connected') === 'true') {
        window.history.replaceState({}, '', '/');
        loadCalendarEvents();
    }
    if (params.get('calendar_error')) {
        alert('Calendar connection failed: ' + params.get('calendar_error'));
        window.history.replaceState({}, '', '/');
    }
}

// Calendar Timeline functions
async function loadCalendarEvents() {
    try {
        const url = calendarDateOffset === 0
            ? '/api/calendar/events'
            : `/api/calendar/events?offset=${calendarDateOffset}`;
        const response = await fetch(url);
        const data = await response.json();

        calendarConnected = data.connected;
        calendarEvents = data.events || [];

        updateCalendarToggleButton();
        renderCalendarSidebar();
    } catch (error) {
        console.error('Failed to load calendar events:', error);
        calendarConnected = false;
        calendarEvents = [];
        updateCalendarToggleButton();
        renderCalendarSidebar();
    }
}

function changeCalendarDay(delta) {
    calendarDateOffset += delta;
    loadCalendarEvents();
}

function goToCalendarToday() {
    calendarDateOffset = 0;
    loadCalendarEvents();
}

function toggleCalendarSidebar() {
    calendarVisible = !calendarVisible;
    renderCalendarSidebar();
    updateCalendarToggleButton();
}

function updateCalendarToggleButton() {
    const btn = document.getElementById('calendar-toggle-btn');
    if (btn) {
        // Only show button when calendar is connected
        if (calendarConnected) {
            btn.classList.remove('hidden');
        } else {
            btn.classList.add('hidden');
        }
        btn.textContent = calendarVisible ? 'Hide Cal' : 'Show Cal';
    }
}

function renderCalendarSidebar() {
    const sidebar = document.getElementById('calendar-sidebar');
    const timeline = document.getElementById('calendar-timeline');
    const dateHeader = document.getElementById('calendar-date');

    if (!sidebar || !timeline) return;

    // Only show on Current tab when connected and visible
    if (currentTab !== 'current' || !calendarConnected || !calendarVisible) {
        sidebar.classList.add('hidden');
        return;
    }

    sidebar.classList.remove('hidden');

    // Set date header with navigation
    const displayDate = new Date();
    displayDate.setDate(displayDate.getDate() + calendarDateOffset);
    const options = { weekday: 'short', month: 'short', day: 'numeric' };
    const dateStr = displayDate.toLocaleDateString('en-US', options);
    const isToday = calendarDateOffset === 0;

    dateHeader.innerHTML = `
        <button class="calendar-nav-btn" onclick="changeCalendarDay(-1)" title="Previous day">‹</button>
        <span class="calendar-date-text ${isToday ? '' : 'not-today'}" onclick="goToCalendarToday()" title="${isToday ? '' : 'Click to go to today'}">${isToday ? 'Today' : dateStr}</span>
        <button class="calendar-nav-btn" onclick="changeCalendarDay(1)" title="Next day">›</button>
    `;

    if (calendarEvents.length === 0) {
        timeline.innerHTML = '<div class="calendar-empty">No events today</div>';
        return;
    }

    // Sort events by start time
    const sortedEvents = [...calendarEvents].sort((a, b) => {
        if (a.isAllDay && !b.isAllDay) return -1;
        if (!a.isAllDay && b.isAllDay) return 1;
        return new Date(a.start) - new Date(b.start);
    });

    const now = new Date();
    const viewingToday = calendarDateOffset === 0;
    let html = '';

    for (const event of sortedEvents) {
        const startTime = new Date(event.start);
        const endTime = new Date(event.end);

        // Determine event state (only mark past/current if viewing today)
        let eventClass = 'calendar-event';
        if (event.isAllDay) {
            eventClass += ' all-day';
        } else if (viewingToday && now >= startTime && now <= endTime) {
            eventClass += ' current';
        } else if (viewingToday && now > endTime) {
            eventClass += ' past';
        }

        html += renderCalendarEvent(event, eventClass);
    }

    timeline.innerHTML = html;
}

function renderCalendarEvent(event, className) {
    let timeStr = '';
    if (event.isAllDay) {
        timeStr = 'All day';
    } else {
        const startTime = new Date(event.start);
        const endTime = new Date(event.end);
        const formatTime = (d) => d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
        timeStr = `${formatTime(startTime)} - ${formatTime(endTime)}`;
    }

    let meetLink = '';
    if (event.hangoutLink) {
        meetLink = `<a href="${event.hangoutLink}" target="_blank" class="calendar-meet-link">Join Meet</a>`;
    }

    // Add response status class
    if (event.responseStatus === 'declined') {
        className += ' declined';
    } else if (event.responseStatus === 'tentative') {
        className += ' tentative';
    }

    const title = event.htmlLink
        ? `<a href="${event.htmlLink}" target="_blank">${escapeHtml(event.summary)}</a>`
        : escapeHtml(event.summary);

    const tentativeIndicator = event.responseStatus === 'tentative' ? '<span class="tentative-indicator">?</span>' : '';

    return `
        <div class="${className}">
            <div class="calendar-event-time">${timeStr}${tentativeIndicator}</div>
            <div class="calendar-event-title">${title}</div>
            ${meetLink}
        </div>
    `;
}

async function syncToConfluence() {
    const syncBtn = document.getElementById('sync-btn');
    const originalText = syncBtn.textContent;
    syncBtn.textContent = 'Syncing...';
    syncBtn.classList.add('disabled');

    try {
        // Save notes first in case there are pending changes
        if (notesSaveTimeout) {
            clearTimeout(notesSaveTimeout);
            notesSaveTimeout = null;
        }
        await saveNotes();

        const response = await fetch('/api/sync-confluence', { method: 'POST' });
        const data = await response.json();

        if (data.success) {
            syncBtn.textContent = 'Synced!';
            setTimeout(() => {
                syncBtn.textContent = originalText;
                syncBtn.classList.remove('disabled');
            }, 2000);
        } else {
            alert('Sync failed: ' + (data.error || 'Unknown error'));
            syncBtn.textContent = originalText;
            syncBtn.classList.remove('disabled');
        }
    } catch (error) {
        console.error('Sync failed:', error);
        alert('Sync failed: ' + error.message);
        syncBtn.textContent = originalText;
        syncBtn.classList.remove('disabled');
    }
}

// Move to Backlog modal
let moveTaskId = null;

function showMoveToBacklog(taskId) {
    moveTaskId = taskId;
    const modal = document.getElementById('move-to-backlog-modal');
    modal.classList.remove('hidden');
}

function showMoveToCurrent(taskId) {
    moveTaskId = taskId;
    const modal = document.getElementById('move-to-current-modal');
    modal.classList.remove('hidden');
}

async function moveToSection(targetSection) {
    if (!moveTaskId) return;

    try {
        await fetch(`/api/tasks/${moveTaskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ section: targetSection })
        });
        await loadTasks();
    } catch (error) {
        console.error('Failed to move task:', error);
    }

    closeMoveModals();
}

function closeMoveModals() {
    moveTaskId = null;
    document.getElementById('move-to-backlog-modal').classList.add('hidden');
    document.getElementById('move-to-current-modal').classList.add('hidden');
}

// Setup move modals on page load
document.addEventListener('DOMContentLoaded', () => {
    // Close modals on backdrop click
    ['move-to-backlog-modal', 'move-to-current-modal'].forEach(modalId => {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    closeMoveModals();
                }
            });
        }
    });

    // Theme modal backdrop click
    const themeModal = document.getElementById('theme-modal');
    if (themeModal) {
        themeModal.addEventListener('click', (e) => {
            if (e.target === themeModal) {
                closeThemeModal();
            }
        });
    }
});
