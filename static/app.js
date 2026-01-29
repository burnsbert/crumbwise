// Crumbwise - Frontend Application

const SECTION_CONFIG = {
    current: {
        // Flow: Week After Next -> Next Week -> This Week -> In Progress -> Done This Week
        columns: ['TODO FOLLOWING WEEK', 'TODO NEXT WEEK', 'TODO THIS WEEK', 'IN PROGRESS TODAY', 'DONE THIS WEEK'],
        secondary: ['BIG ONGOING PROJECTS', 'FOLLOW UPS', 'BLOCKED'],
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

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
    setupNewWeek();
    setupSettings();
    loadTasks();
    loadSettings();
    loadCalendarEvents();
    checkCalendarConnectionFromUrl();
});

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

        renderBoard();
        updateUndoButton(undoData.canUndo);
    } catch (error) {
        console.error('Failed to load tasks:', error);
    }
}

function updateHistoryColumns() {
    // Find all history sections (DONE Q* and DONE 20*)
    const historyColumns = Object.keys(tasks)
        .filter(section => section.startsWith('DONE Q') || section.startsWith('DONE 20'))
        .filter(section => section !== 'DONE THIS WEEK')
        .sort((a, b) => {
            // Current quarter first, then by year/quarter descending
            if (a === currentQuarter) return -1;
            if (b === currentQuarter) return 1;
            // Sort quarters: Q4 > Q3 > Q2 > Q1, newer years first
            return b.localeCompare(a);
        });

    SECTION_CONFIG.history.columns = historyColumns;
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
        const sortable = new Sortable(el, {
            group: 'tasks',
            animation: 150,
            ghostClass: 'sortable-ghost',
            chosenClass: 'sortable-chosen',
            dragClass: 'sortable-drag',
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
            column.classList.add('drag-over');
        });
        header.addEventListener('dragleave', () => {
            column.classList.remove('drag-over');
        });
        header.addEventListener('drop', async (e) => {
            e.preventDefault();
            column.classList.remove('drag-over');

            // Find the dragged task card
            const draggedCard = document.querySelector('.sortable-drag, .sortable-chosen');
            if (!draggedCard) return;

            const taskId = draggedCard.dataset.id;
            const section = header.closest('.column').dataset.section;
            const sectionTasks = tasks[section] || [];

            try {
                await fetch('/api/tasks/reorder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        taskId,
                        section,
                        index: sectionTasks.length
                    })
                });
                await loadTasks();
            } catch (error) {
                console.error('Failed to move to section:', error);
                await loadTasks();
            }
        });
    });
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
    const sectionClass = isSecondary || section === 'DONE THIS WEEK' || section === 'RESEARCH DONE' || section === currentQuarter ? 'blocked-section' :
                         section === 'IN PROGRESS TODAY' || section === 'RESEARCH IN PROGRESS' ? 'current-period' :
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
    // Only main columns + BLOCKED get move buttons (not BIG ONGOING PROJECTS or FOLLOW UPS)
    const currentWithMove = [...SECTION_CONFIG.current.columns, 'BLOCKED'];
    const backlogSections = SECTION_CONFIG.backlog.columns;

    let moveButton = '';
    if (currentWithMove.includes(section)) {
        moveButton = `<button class="card-btn move" onclick="event.stopPropagation(); showMoveToBacklog('${task.id}')" title="Move to Backlog">&gt;&gt;</button>`;
    } else if (backlogSections.includes(section)) {
        moveButton = `<button class="card-btn move" onclick="event.stopPropagation(); showMoveToCurrent('${task.id}')" title="Move to Current">&lt;&lt;</button>`;
    }

    return `
        <div class="card ${completedClass}" data-id="${task.id}" onclick="handleCardClick(event, '${task.id}')">
            <div class="card-actions">
                ${moveButton}
                <button class="card-btn delete" onclick="event.stopPropagation(); deleteCard('${task.id}')" title="Delete">×</button>
            </div>
            <div class="card-text">${textWithLinks}</div>
        </div>
    `;
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

// Drag and drop
async function handleDragEnd(event) {
    const taskId = event.item.dataset.id;
    const newSection = event.to.dataset.section;
    const newIndex = event.newIndex;

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

        if (data.connected) {
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
});
