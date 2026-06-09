const API_BASE = '';
const REFRESH_INTERVAL = 5000;

let autoRefreshInterval = null;

function showMessage(elementId, text, type = 'success') {
    const el = document.getElementById(elementId);
    el.textContent = text;
    el.className = `message show ${type}`;
    setTimeout(() => {
        el.className = 'message';
    }, 5000);
}

async function apiFetch(path, options = {}) {
    const url = `${API_BASE}${path}`;
    const response = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString();
}

function getStatusBadge(status) {
    return `<span class="status-badge status-${status}">${status}</span>`;
}

function renderCapabilities(caps) {
    if (!caps || caps.length === 0) return '-';
    return caps.map(c => 
        `<span class="capability-tag">${c.name}${c.operator !== 'eq' ? c.operator : ''}=${c.value}</span>`
    ).join('');
}

async function loadDashboard() {
    try {
        const [jobs, workersHealth] = await Promise.all([
            apiFetch('/jobs'),
            apiFetch('/health/workers'),
        ]);

        const counts = {
            total: jobs.length,
            pending: jobs.filter(j => j.status === 'pending').length,
            running: jobs.filter(j => j.status === 'running').length,
            completed: jobs.filter(j => j.status === 'completed').length,
            failed: jobs.filter(j => j.status === 'failed').length,
            cancelled: jobs.filter(j => j.status === 'cancelled').length,
        };

        document.getElementById('total-jobs').textContent = counts.total;
        document.getElementById('pending-jobs').textContent = counts.pending;
        document.getElementById('running-jobs').textContent = counts.running;
        document.getElementById('completed-jobs').textContent = counts.completed;
        document.getElementById('failed-jobs').textContent = counts.failed;
        document.getElementById('total-workers').textContent = workersHealth.total;
        document.getElementById('healthy-workers').textContent = workersHealth.healthy;
        document.getElementById('unhealthy-workers').textContent = workersHealth.unhealthy;
    } catch (err) {
        console.error('Failed to load dashboard:', err);
    }
}

async function loadJobs() {
    try {
        const jobs = await apiFetch('/jobs');
        const filter = document.getElementById('job-filter').value;
        const tbody = document.getElementById('jobs-table-body');

        const filtered = filter === 'all' ? jobs : jobs.filter(j => j.status === filter);

        if (filtered.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="empty-state">No jobs found</td></tr>`;
            return;
        }

        tbody.innerHTML = filtered.map(job => {
            const progressHtml = job.status === 'running' 
                ? `<div class="progress-bar"><div class="progress-bar-fill" style="width: ${job.progress}%"></div></div><div class="progress-text">${job.progress.toFixed(1)}%</div>`
                : '-';

            let actions = '';
            if (job.status === 'pending') {
                actions += `<button class="btn btn-small btn-primary" onclick="dispatchJob('${job.id}')">Dispatch</button> `;
                actions += `<button class="btn btn-small btn-danger" onclick="cancelJob('${job.id}')">Cancel</button>`;
            } else if (job.status === 'running') {
                actions += `<button class="btn btn-small btn-danger" onclick="cancelJob('${job.id}')">Cancel</button>`;
            } else if (job.status === 'failed') {
                actions += `<button class="btn btn-small btn-primary" onclick="retryJob('${job.id}')">Retry</button>`;
            }

            return `
                <tr>
                    <td>${job.id}</td>
                    <td>${job.name}</td>
                    <td>${getStatusBadge(job.status)}</td>
                    <td>${job.priority}</td>
                    <td>${progressHtml}</td>
                    <td>${job.worker_id || '-'}</td>
                    <td>${job.retry_count}/${job.max_retries}</td>
                    <td class="actions-cell">${actions}</td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error('Failed to load jobs:', err);
    }
}

async function loadWorkers() {
    try {
        const workers = await apiFetch('/workers');
        const tbody = document.getElementById('workers-table-body');

        if (workers.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No workers found</td></tr>`;
            return;
        }

        tbody.innerHTML = workers.map(worker => {
            const heartbeatStatus = worker.status === 'offline' ? 'text-danger' : '';
            return `
                <tr>
                    <td>${worker.id}</td>
                    <td>${getStatusBadge(worker.status)}</td>
                    <td>${renderCapabilities(worker.capabilities)}</td>
                    <td>${worker.current_job_id || '-'}</td>
                    <td class="${heartbeatStatus}">${formatDate(worker.last_heartbeat)}</td>
                    <td class="actions-cell">
                        <button class="btn btn-small btn-secondary" onclick="heartbeatWorker('${worker.id}')">Heartbeat</button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error('Failed to load workers:', err);
    }
}

async function dispatchJob(jobId) {
    try {
        await apiFetch(`/jobs/${jobId}/dispatch`, { method: 'POST', body: JSON.stringify({}) });
        showMessage('dashboard-message', `Job ${jobId} dispatched successfully`, 'success');
        refreshAll();
    } catch (err) {
        showMessage('dashboard-message', `Failed to dispatch job: ${err.message}`, 'error');
    }
}

async function cancelJob(jobId) {
    try {
        await apiFetch(`/jobs/${jobId}/cancel`, { method: 'POST' });
        showMessage('dashboard-message', `Job ${jobId} cancelled`, 'success');
        refreshAll();
    } catch (err) {
        showMessage('dashboard-message', `Failed to cancel job: ${err.message}`, 'error');
    }
}

async function retryJob(jobId) {
    try {
        await apiFetch(`/jobs/${jobId}/retry`, { method: 'POST' });
        showMessage('dashboard-message', `Job ${jobId} retried`, 'success');
        refreshAll();
    } catch (err) {
        showMessage('dashboard-message', `Failed to retry job: ${err.message}`, 'error');
    }
}

async function heartbeatWorker(workerId) {
    try {
        await apiFetch(`/workers/${workerId}/heartbeat`, { method: 'POST' });
        showMessage('dashboard-message', `Worker ${workerId} heartbeat sent`, 'success');
        refreshAll();
    } catch (err) {
        showMessage('dashboard-message', `Failed to send heartbeat: ${err.message}`, 'error');
    }
}

async function autoDispatch() {
    try {
        const result = await apiFetch('/dispatch/auto', { method: 'POST' });
        showMessage('dashboard-message', `Auto-dispatched ${result.job_id} to ${result.worker_id}`, 'success');
        refreshAll();
    } catch (err) {
        showMessage('dashboard-message', `Auto-dispatch failed: ${err.message}`, 'error');
    }
}

async function runHealthCheck() {
    try {
        const result = await apiFetch('/health/check', { method: 'POST' });
        showMessage('dashboard-message', `Health check complete. Marked ${result.count} workers offline.`, 'success');
        refreshAll();
    } catch (err) {
        showMessage('dashboard-message', `Health check failed: ${err.message}`, 'error');
    }
}

function refreshAll() {
    loadDashboard();
    loadJobs();
    loadWorkers();
}

function setupTabs() {
    const tabs = document.querySelectorAll('.tab-btn');
    const contents = document.querySelectorAll('.tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.dataset.tab;
            tabs.forEach(t => t.classList.remove('active'));
            contents.forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(target).classList.add('active');
        });
    });
}

function setupForms() {
    document.getElementById('create-job-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            const payload = document.getElementById('job-payload').value;
            const capabilities = document.getElementById('job-capabilities').value;
            
            const body = {
                name: document.getElementById('job-name').value,
                priority: parseInt(document.getElementById('job-priority').value),
                max_retries: parseInt(document.getElementById('job-max-retries').value),
                payload: payload ? JSON.parse(payload) : {},
                required_capabilities: capabilities ? JSON.parse(capabilities) : [],
            };

            await apiFetch('/jobs', { method: 'POST', body: JSON.stringify(body) });
            showMessage('create-job-message', 'Job created successfully', 'success');
            document.getElementById('create-job-form').reset();
            refreshAll();
        } catch (err) {
            showMessage('create-job-message', `Failed to create job: ${err.message}`, 'error');
        }
    });

    document.getElementById('create-worker-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            const capabilities = document.getElementById('worker-capabilities').value;
            
            const body = {
                id: document.getElementById('worker-id').value,
                capabilities: capabilities ? JSON.parse(capabilities) : [],
            };

            await apiFetch('/workers', { method: 'POST', body: JSON.stringify(body) });
            showMessage('create-worker-message', 'Worker created successfully', 'success');
            document.getElementById('create-worker-form').reset();
            refreshAll();
        } catch (err) {
            showMessage('create-worker-message', `Failed to create worker: ${err.message}`, 'error');
        }
    });
}

function setupEventListeners() {
    document.getElementById('auto-dispatch-btn').addEventListener('click', autoDispatch);
    document.getElementById('health-check-btn').addEventListener('click', runHealthCheck);
    document.getElementById('refresh-btn').addEventListener('click', refreshAll);
    document.getElementById('job-filter').addEventListener('change', loadJobs);
}

function startAutoRefresh() {
    if (autoRefreshInterval) clearInterval(autoRefreshInterval);
    autoRefreshInterval = setInterval(refreshAll, REFRESH_INTERVAL);
}

document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
    setupForms();
    setupEventListeners();
    refreshAll();
    startAutoRefresh();
});
