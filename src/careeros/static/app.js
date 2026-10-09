import { OfficeRenderer } from "./office-renderer.js";

const state = { provider: "ollama", cloudConfigured: false, settings: null, selectedJob: null, savedOnly: false, activeProposal: null, office: null, officeSelection: null };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const officeRenderer = new OfficeRenderer($("#office-canvas"), {
  onSelect: selection => selectOffice(selection),
  onHover: (workerId, position) => renderWorkerTooltip(workerId, position),
});
officeRenderer.update({ workers: [], counts: {} });
let officePollTimer = null;
let officeRefreshing = false;
window.addEventListener("pagehide", () => {
  if (officePollTimer) window.clearInterval(officePollTimer);
  officeRenderer.destroy();
}, { once: true });

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

async function api(url, options = {}) {
  const config = { ...options, headers: { ...(options.headers || {}) } };
  if (config.body && typeof config.body !== "string") {
    config.headers["Content-Type"] = "application/json";
    config.body = JSON.stringify(config.body);
  }
  const response = await fetch(url, config);
  const contentType = response.headers.get("content-type") || "";
  const value = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = value && typeof value === "object" ? value.detail : value;
    const message = detail && typeof detail === "object" ? detail.message : detail;
    throw new Error(message || `Request failed (${response.status})`);
  }
  return value;
}

function notify(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => toast.classList.remove("visible"), 2800);
}

function go(station) {
  const home = station === "home" || !$("#" + station + "-screen");
  document.body.classList.toggle("office-active", home);
  document.body.classList.toggle("station-active", !home);
  $("#home-screen").hidden = !home;
  $$(".station-screen").forEach(screen => { screen.hidden = home || screen.id !== station + "-screen"; });
  hideWorkerTooltip();
  closeWorkerRoster();
  if (home) window.requestAnimationFrame(() => officeRenderer.resize());
  if (home) {
    refreshOverview();
  } else if (station === "jobs") {
    searchJobs();
  } else if (station === "resume") {
    loadResumeDesk();
  } else if (station === "portfolio") {
    loadProposals();
  } else if (station === "applications") {
    loadOfficeApplications();
  } else if (station === "settings") {
    loadSettings();
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.addEventListener("click", event => {
  const nav = event.target.closest("[data-station]");
  if (nav) go(nav.dataset.station);
});

function safeJobUrl(value) {
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}

function jobCard(job) {
  const card = element("article", "job-card");
  const top = element("div", "job-card-top");
  const info = element("div");
  info.append(element("h3", "job-title", job.title), element("p", "job-company", `${job.company} · ${job.location || "Location not listed"}`));
  top.append(info);
  const linkUrl = safeJobUrl(job.url);
  if (linkUrl) {
    const link = element("a", "job-link", "View role ↗");
    link.href = linkUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    top.append(link);
  }
  card.append(top);
  const meta = element("div", "job-meta");
  meta.append(element("span", "chip", job.kind || "other"));
  if (job.remote) meta.append(element("span", "chip", "remote"));
  if (job.source) meta.append(element("span", "chip", job.source));
  card.append(meta);
  if (job.description) {
    const description = element("p", "muted", job.description.slice(0, 240));
    card.append(description);
  }
  const actions = element("div", "job-actions");
  const save = element("button", "button button-soft", job.is_saved ? "Saved ✓" : "Save role");
  save.type = "button";
  save.addEventListener("click", async () => {
    try {
      await api(`/api/jobs/${encodeURIComponent(job.id)}/${job.is_saved ? "unsave" : "save"}`, { method: "POST" });
      notify(job.is_saved ? "Removed from saved roles" : "Role saved");
      searchJobs();
      refreshOverview();
    } catch (error) { notify(error.message); }
  });
  actions.append(save);
  if (job.is_saved) {
    const prepare = element("button", "button button-dark", "Prepare application");
    prepare.type = "button";
    prepare.addEventListener("click", () => {
      state.selectedJob = job;
      $("#selected-job-copy").textContent = `${job.title} at ${job.company} is selected. Choose a resume and planner to start a draft.`;
      go("resume");
    });
    actions.append(prepare);
  }
  card.append(actions);
  return card;
}

async function searchJobs() {
  const params = new URLSearchParams();
  params.set("q", $("#job-search").value.trim());
  params.set("location", $("#job-location").value.trim());
  params.set("kind", $("#job-kind").value);
  params.set("remote_only", String($("#remote-only").checked));
  params.set("saved", String(state.savedOnly));
  try {
    const jobs = await api("/api/jobs?" + params.toString());
    const list = $("#job-results");
    list.replaceChildren();
    $("#job-result-label").textContent = state.savedOnly ? "SAVED ROLES" : `${jobs.length} MATCHING ROLES`;
    if (!jobs.length) list.append(element("p", "empty-state", "No roles match yet. Try a broader search or add a listing you found."));
    jobs.forEach(job => list.append(jobCard(job)));
  } catch (error) { notify(error.message); }
}

$("#job-search-form").addEventListener("submit", event => { event.preventDefault(); state.savedOnly = false; searchJobs(); });
$("#show-saved-jobs").addEventListener("click", () => { state.savedOnly = !state.savedOnly; $("#show-saved-jobs").textContent = state.savedOnly ? "Show all" : "Saved only"; searchJobs(); });
$("#job-refresh").addEventListener("click", async event => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "Refreshing…";
  try {
    const result = await api("/api/jobs/refresh", { method: "POST", body: { text: $("#job-search").value, location: $("#job-location").value, kind: $("#job-kind").value, remote_only: $("#remote-only").checked } });
    const errors = result.sources.filter(item => item.error).map(item => `${item.name}: ${item.error}`);
    const warnings = result.sources.flatMap(item => item.warnings || []);
    notify(errors.length ? "Some feeds were unavailable. Cached roles remain." : `${result.saved} listings refreshed${warnings.length ? ` · ${warnings[0]}` : ""}`);
    searchJobs();
  } catch (error) { notify(error.message); }
  finally { button.disabled = false; button.textContent = "Refresh public boards"; }
});

$("#manual-job-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form));
  try {
    const job = await api("/api/jobs/manual", { method: "POST", body: payload });
    notify("Role saved to your board");
    form.reset();
    searchJobs();
    refreshOverview();
  } catch (error) { notify(error.message); }
});

async function refreshOverview() {
  try {
    const [resumes] = await Promise.all([api("/api/resumes"), refreshOffice()]);
    $("#resume-count").textContent = resumes.length;
  } catch { /* The station still explains what to do when there is no data. */ }
}

async function refreshOffice() {
  if (document.visibilityState !== "visible" || officeRefreshing) return false;
  officeRefreshing = true;
  try {
    const snapshot = await api("/api/workspace");
    state.office = snapshot;
    if (state.officeSelection?.type === "worker" && !(snapshot.workers || []).some(worker => worker.id === state.officeSelection.id)) {
      state.officeSelection = null;
      officeRenderer.setSelection(null);
    }
    officeRenderer.update(snapshot);
    $("#office-connection").textContent = "LIVE";
    $("#office-connection").dataset.state = "live";
    renderWorkerRoster(snapshot.workers || []);
    renderOfficeActivity(snapshot.activity || []);
    renderOfficeCounts(snapshot);
    renderAutopilot(snapshot.autopilot || {});
    renderInspector();
    if (!$("#worker-tooltip").hidden) renderWorkerTooltip(officeRenderer.hoveredWorker, officeRenderer.hoverPosition);
    return true;
  } catch {
    $("#office-connection").textContent = state.office ? "STALE" : "OFFLINE";
    $("#office-connection").dataset.state = "offline";
    $("#autopilot-indicator").textContent = state.office ? "Showing last local update" : "Local queue is unavailable";
    $("#autopilot-schedule").textContent = "CareerOS will reconnect automatically.";
    if (!state.office) {
      $("#autopilot-toggle").textContent = "AUTO —";
      $("#autopilot-toggle").setAttribute("aria-label", "Automatic discovery status unavailable");
    }
    return false;
  } finally {
    officeRefreshing = false;
  }
}

function renderWorkerRoster(workers) {
  const list = $("#worker-roster");
  if (!workers.length) {
    list.replaceChildren(element("p", "roster-empty", "No office workers are available yet."));
    return;
  }
  Array.from(list.children).forEach(child => { if (!child.querySelector("[data-worker-id]")) child.remove(); });
  const existing = new Map(Array.from(list.querySelectorAll("[data-worker-id]"), button => [button.dataset.workerId, button]));
  for (const worker of workers) {
    let button = existing.get(worker.id);
    if (button) existing.delete(worker.id);
    else {
      const slot = element("div", "roster-slot");
      slot.setAttribute("role", "listitem");
      button = element("button", "worker-entry");
      button.type = "button";
      button.dataset.workerId = worker.id;
      button.addEventListener("click", () => selectOffice({ type: "worker", id: button.dataset.workerId }));
      slot.append(button);
      list.append(slot);
    }
    button.setAttribute("aria-pressed", String(state.officeSelection?.type === "worker" && state.officeSelection.id === worker.id));
    const status = ["idle", "waiting", "paused", "working", "needs_review", "failed", "interrupted"].includes(worker.status) ? worker.status : "waiting";
    const copy = element("span", "worker-copy");
    copy.append(element("strong", "", worker.department || worker.id));
    const taskText = worker.task_label || "Waiting for work";
    const duration = status === "working" && worker.since ? ` · ${formatElapsed(worker.since)}` : "";
    copy.append(element("small", "", taskText + duration));
    button.replaceChildren(element("span", "worker-pixel", ""), copy, element("span", `worker-state ${status}`, formatStatus(status)));
  }
  for (const button of existing.values()) button.closest('[role="listitem"]')?.remove();
}

function renderOfficeActivity(activity) {
  const list = $("#office-activity");
  list.replaceChildren();
  if (!activity.length) {
    list.append(element("li", "activity-empty", "No tasks have been recorded yet. The first scheduled scan will appear here."));
    return;
  }
  activity.slice(0, 8).forEach(item => {
    const row = element("li", `activity-item activity-${safeStatus(item.status)}`);
    const copy = element("span", "activity-copy");
    copy.append(element("strong", "", item.label || "Task updated"));
    copy.append(element("small", "", `${formatStatus(item.status)} · ${formatTimestamp(item.updated_at)}`));
    row.append(element("span", "activity-mark", ""), copy);
    list.append(row);
  });
}

function renderOfficeCounts(snapshot) {
  const counts = snapshot.counts || {};
  $("#saved-job-count").textContent = formatCount(counts.jobs_found);
  $("#matched-job-count").textContent = `${formatCount(counts.jobs_matched)} technology matches`;
  $("#application-count").textContent = formatCount(counts.tasks_shipped);
  $("#draft-review-count").textContent = formatCount(counts.drafts_to_review);
  $("#proposal-review-count").textContent = `${formatCount(counts.proposals_to_review)} proposals`;
  const model = snapshot.model || {};
  $("#model-state").textContent = ({ ready: "Ready", offline: "Offline", model_missing: "Model needed" })[model.state] || "Checking";
  $("#model-name").textContent = model.autopilot_provider === "ollama" ? model.name || "Ollama" : "Ollama for auto work";
}

function renderAutopilot(autopilot) {
  const enabled = Boolean(autopilot.enabled);
  const indicator = $("#autopilot-indicator");
  indicator.dataset.enabled = String(enabled);
  indicator.textContent = enabled ? "AUTO" : "PAUSED";
  const toggle = $("#autopilot-toggle");
  toggle.disabled = autopilotUpdating;
  toggle.setAttribute("aria-pressed", String(enabled));
  toggle.textContent = enabled ? "AUTO ON" : "AUTO OFF";
  toggle.setAttribute("aria-label", enabled ? "Pause automatic discovery" : "Resume automatic discovery");
  const schedule = $("#autopilot-schedule");
  if (!enabled) schedule.textContent = "Automatic listing discovery is paused. Existing queued work can finish.";
  else if (autopilot.last_error) schedule.textContent = `The last scan had a problem. CareerOS will retry. ${autopilot.last_error}`;
  else schedule.textContent = autopilot.next_discovery_at ? `Next automatic listing scan · ${formatUntil(autopilot.next_discovery_at)}` : "Automatic listing discovery is enabled.";
}

const OFFICE_STATIONS = {
  jobs: { title: "Job Hunters", target: "jobs", description: "Search technology roles and review the listings CareerOS found." },
  resume: { title: "Resume Team", target: "resume", description: "Keep your profile and resume versions on this Mac." },
  applications: { title: "Application Team", target: "applications", description: "Review application drafts. CareerOS never submits them." },
  portfolio: { title: "Engineering Team", target: "portfolio", description: "Review staged project proposals before applying any files." },
  settings: { title: "Dispatch", target: "settings", description: "Choose the local planner or explicitly configure optional cloud use." },
};
const WORKER_STATIONS = {
  "job-hunter": "jobs",
  "resume-analyst": "resume",
  "application-prep": "applications",
  "portfolio-engineer": "portfolio",
  director: "settings",
};

function selectOffice(selection) {
  if (!selection || !["worker", "station"].includes(selection.type)) return;
  closeWorkerRoster();
  hideWorkerTooltip();
  state.officeSelection = selection;
  officeRenderer.setSelection(selection);
  renderWorkerRoster(state.office?.workers || []);
  renderInspector();
}

function hideWorkerTooltip() {
  $("#worker-tooltip").hidden = true;
}

function renderWorkerTooltip(workerId, position) {
  const tooltip = $("#worker-tooltip");
  const worker = (state.office?.workers || []).find(item => item.id === workerId);
  if (!worker || !position) {
    tooltip.hidden = true;
    return;
  }
  $("#worker-tooltip-name").textContent = worker.department || worker.name || worker.id;
  $("#worker-tooltip-task").textContent = worker.task_label || "Waiting for work";
  const details = [formatStatus(worker.status).toUpperCase()];
  if (worker.since) details.push(`FOR ${formatElapsed(worker.since)}`);
  if (worker.task_id) details.push(`#${worker.task_id}`);
  $("#worker-tooltip-meta").textContent = details.join("  /  ");
  tooltip.className = `worker-tooltip status-${safeStatus(worker.status)}`;
  tooltip.hidden = false;
  const frame = $(".canvas-frame");
  const maxX = Math.max(8, frame.clientWidth - tooltip.offsetWidth - 8);
  const maxY = Math.max(8, frame.clientHeight - tooltip.offsetHeight - 8);
  tooltip.style.left = `${Math.max(8, Math.min(position.x + 15, maxX))}px`;
  tooltip.style.top = `${Math.max(8, Math.min(position.y + 12, maxY))}px`;
}

function renderInspector() {
  const panel = $("#task-inspector");
  const heading = $("#inspector-heading");
  const copy = $("#inspector-copy");
  const meta = $("#inspector-meta");
  const open = $("#inspector-open-station");
  const selection = state.officeSelection;
  if (!selection) {
    panel.hidden = true;
    return;
  }
  let target;
  meta.replaceChildren();
  if (selection.type === "worker") {
    const worker = (state.office?.workers || []).find(item => item.id === selection.id);
    if (!worker) { panel.hidden = true; return; }
    heading.textContent = worker.department || worker.id;
    copy.textContent = worker.task_label || "Waiting for work";
    target = OFFICE_STATIONS[WORKER_STATIONS[worker.id]];
    addInspectorMeta(meta, "Status", formatStatus(worker.status));
    if (worker.task_id) addInspectorMeta(meta, "Queue task", worker.task_id);
    if (worker.since) addInspectorMeta(meta, "Working for", formatElapsed(worker.since));
  } else {
    target = OFFICE_STATIONS[selection.id];
    if (!target) { panel.hidden = true; return; }
    heading.textContent = target.title;
    copy.textContent = target.description;
    const workers = (state.office?.workers || []).filter(worker => WORKER_STATIONS[worker.id] === selection.id);
    if (workers.length) addInspectorMeta(meta, "Team status", workers.map(worker => `${worker.department}: ${formatStatus(worker.status)}`).join(" · "));
  }
  open.hidden = !target;
  if (target) {
    open.textContent = `Open ${target.title}`;
    open.dataset.station = target.target;
  } else {
    delete open.dataset.station;
  }
  panel.hidden = false;
}

function addInspectorMeta(root, label, value) {
  const row = element("div");
  row.append(element("span", "", label), element("strong", "", value));
  root.append(row);
}

function formatElapsed(value) {
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 1000));
  if (!Number.isFinite(seconds)) return "just now";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`;
}

function formatUntil(value) {
  const seconds = Math.max(0, Math.floor((Date.parse(value) - Date.now()) / 1000));
  if (!Number.isFinite(seconds)) return "scheduled";
  if (seconds < 60) return "in less than a minute";
  if (seconds < 3600) return `in ${Math.floor(seconds / 60)}m`;
  return `in ${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`;
}

function formatTimestamp(value) {
  const timestamp = Date.parse(value || "");
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "recently";
}

function formatCount(value) { return Number.isInteger(value) ? String(value) : "0"; }
function safeStatus(value) { return ["queued", "running", "completed", "needs_review", "failed", "interrupted"].includes(value) ? value : "queued"; }
function formatStatus(value) { return String(value || "waiting").replaceAll("_", " "); }

let autopilotUpdating = false;
$("#autopilot-toggle").addEventListener("click", async () => {
  if (!state.office || autopilotUpdating) return;
  const enabled = !state.office.autopilot.enabled;
  autopilotUpdating = true;
  $("#autopilot-toggle").disabled = true;
  try {
    await api("/api/autopilot", { method: "PUT", body: { enabled } });
    await refreshOffice();
    notify(enabled ? "Automatic listing discovery resumed" : "Automatic listing discovery paused");
  } catch (error) {
    notify(error.message);
  } finally {
    autopilotUpdating = false;
    if (state.office) renderAutopilot(state.office.autopilot || {});
  }
});

$("#close-inspector").addEventListener("click", () => {
  state.officeSelection = null;
  officeRenderer.setSelection(null);
  renderInspector();
  renderWorkerRoster(state.office?.workers || []);
});

function closeWorkerRoster() {
  const panel = $("#worker-roster-panel");
  if (!panel) return;
  panel.hidden = true;
  $("#toggle-roster").setAttribute("aria-expanded", "false");
}

function toggleWorkerRoster() {
  const panel = $("#worker-roster-panel");
  const opening = panel.hidden;
  panel.hidden = !opening;
  $("#toggle-roster").setAttribute("aria-expanded", String(opening));
  if (opening) {
    state.officeSelection = null;
    officeRenderer.setSelection(null);
    renderInspector();
    $("#worker-roster").querySelector("button")?.focus();
  }
}

$("#toggle-roster").addEventListener("click", toggleWorkerRoster);
$("#close-roster").addEventListener("click", () => {
  closeWorkerRoster();
  $("#toggle-roster").focus();
});

$("#refresh-office-applications").addEventListener("click", loadOfficeApplications);

async function loadOfficeApplications() {
  const list = $("#office-application-list");
  try {
    const applications = await api("/api/applications");
    list.replaceChildren();
    if (!applications.length) list.append(element("p", "empty-state", "The application worker will place reviewable drafts here when a saved role and resume match."));
    applications.forEach(application => {
      const card = element("button", "application-card", "");
      card.type = "button";
      const row = element("div", "list-card-top");
      row.append(element("p", "list-card-title", application.job_title || "Application draft"), element("span", `state-label ${application.status === "failed" ? "failed" : ""}`, formatStatus(application.status)));
      card.append(row, element("p", "list-card-sub", `Updated ${formatTimestamp(application.updated_at)}`));
      card.addEventListener("click", () => { go("resume"); loadApplication(application.id); });
      list.append(card);
    });
  } catch (error) {
    list.replaceChildren(element("p", "empty-state", error.message));
  }
}

function startOfficePolling() {
  if (document.visibilityState !== "visible") return;
  if (officePollTimer) window.clearInterval(officePollTimer);
  refreshOffice();
  officePollTimer = window.setInterval(refreshOffice, 2000);
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") startOfficePolling();
  else if (officePollTimer) { window.clearInterval(officePollTimer); officePollTimer = null; }
});

$("#close-inspector").setAttribute("aria-label", "Close selected details");

function splitList(text) { return text.split(",").map(value => value.trim()).filter(Boolean).slice(0, 20); }

async function loadResumeDesk() {
  try {
    const [profile, resumes, applications] = await Promise.all([api("/api/profile"), api("/api/resumes"), api("/api/applications")]);
    const form = $("#profile-form");
    form.elements.name.value = profile.name || "";
    form.elements.summary.value = profile.summary || "";
    form.elements.target_roles.value = (profile.target_roles || []).join(", ");
    form.elements.preferred_locations.value = (profile.preferred_locations || []).join(", ");
    form.elements.skills.value = (profile.skills || []).join(", ");
    renderResumes(resumes);
    renderApplications(applications);
    const selector = $("#prepare-form").elements.resume_id;
    const previous = selector.value;
    selector.replaceChildren(element("option", "", "Choose a resume"));
    selector.options[0].value = "";
    resumes.forEach(resume => { const option = element("option", "", resume.name); option.value = resume.id; selector.append(option); });
    if (resumes.some(item => item.id === previous)) selector.value = previous;
    if (!state.selectedJob) $("#selected-job-copy").textContent = "Choose a saved listing from the Job Board first.";
  } catch (error) { notify(error.message); }
}

$("#profile-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("/api/profile", { method: "PUT", body: { name: form.elements.name.value, summary: form.elements.summary.value, target_roles: splitList(form.elements.target_roles.value), preferred_locations: splitList(form.elements.preferred_locations.value), skills: splitList(form.elements.skills.value) } });
    notify("Profile saved on this Mac");
  } catch (error) { notify(error.message); }
});

$("#resume-file").addEventListener("change", async event => {
  const file = event.currentTarget.files[0];
  if (!file) return;
  if (file.size > 200000) { notify("Choose a text file smaller than 200 KB"); event.currentTarget.value = ""; return; }
  try {
    $("#resume-form").elements.text.value = await file.text();
    if (!$("#resume-form").elements.name.value) $("#resume-form").elements.name.value = file.name.replace(/\.(txt|md)$/i, "");
  } catch { notify("That file could not be read as text"); }
});

$("#resume-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.elements.id.value;
  try {
    await api(id ? `/api/resumes/${encodeURIComponent(id)}` : "/api/resumes", { method: id ? "PUT" : "POST", body: { name: form.elements.name.value, text: form.elements.text.value } });
    form.reset();
    form.elements.id.value = "";
    $("#resume-file").value = "";
    notify("Resume version saved");
    loadResumeDesk();
    refreshOverview();
  } catch (error) { notify(error.message); }
});

$("#new-resume").addEventListener("click", () => { $("#resume-form").reset(); $("#resume-form").elements.id.value = ""; });

function renderResumes(resumes) {
  const list = $("#resume-list");
  list.replaceChildren();
  if (!resumes.length) list.append(element("p", "empty-state", "Save a text resume version to use it in an application draft."));
  resumes.forEach(resume => {
    const button = element("button", "application-card", "");
    button.type = "button";
    button.append(element("p", "list-card-title", resume.name), element("p", "list-card-sub", "Select to edit this local version"));
    button.addEventListener("click", async () => {
      try {
        const saved = await api(`/api/resumes/${encodeURIComponent(resume.id)}`);
        const form = $("#resume-form");
        form.elements.id.value = saved.id;
        form.elements.name.value = saved.name;
        form.elements.text.value = saved.text;
        form.scrollIntoView({ behavior: "smooth", block: "center" });
      } catch (error) { notify(error.message); }
    });
    list.append(button);
  });
}

function renderApplications(applications) {
  const list = $("#application-list");
  list.replaceChildren();
  if (!applications.length) list.append(element("p", "empty-state", "Your prepared drafts will appear here."));
  applications.forEach(item => {
    const card = element("button", "application-card", "");
    card.type = "button";
    const row = element("div", "list-card-top");
    row.append(element("p", "list-card-title", item.job_title || "Application"), element("span", `state-label ${item.status === "failed" ? "failed" : ""}`, item.status.replaceAll("_", " ")));
    card.append(row, element("p", "list-card-sub", `Updated ${new Date(item.updated_at).toLocaleDateString()}`));
    card.addEventListener("click", () => loadApplication(item.id));
    list.append(card);
  });
}

async function askCloud(details) {
  if (!state.settings) await loadSettings();
  if (!state.cloudConfigured) { notify("OpenAI is unavailable. Add OPENAI_API_KEY in .env first."); return false; }
  $("#cloud-consent-copy").textContent = "This sends the data below to OpenAI using GPT-6 Luna (gpt-6-luna). API usage may incur charges. CareerOS will use these reviewed details for this task only and will not switch models automatically.";
  $("#cloud-consent-details").textContent = JSON.stringify(details, null, 2);
  $("#cloud-consent-cost").textContent = `Standard rates checked ${state.settings.openai.rates_checked}: $0.10 per million input tokens and $0.50 per million output tokens.`;
  const dialog = $("#cloud-consent");
  if (typeof dialog.showModal !== "function") {
    return window.confirm(`Send these details to OpenAI using GPT-6 Luna?\n\nStandard rates checked ${state.settings.openai.rates_checked}: $0.10 per million input tokens and $0.50 per million output tokens. API usage may incur charges.\n\n${JSON.stringify(details, null, 2)}`);
  }
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise(resolve => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true }));
}

$("#prepare-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!state.selectedJob) { notify("Choose a saved job first"); go("jobs"); return; }
  const form = event.currentTarget;
  const resumeId = form.elements.resume_id.value;
  if (!resumeId) { notify("Choose a resume version first"); return; }
  const provider = form.elements.provider.value;
  try {
    let confirmCloud = false;
    let previewToken = null;
    if (provider === "openai") {
      const preview = await api("/api/applications/preview", { method: "POST", body: { job_id: state.selectedJob.id, resume_id: resumeId } });
      confirmCloud = await askCloud(preview.sent_data);
      if (!confirmCloud) return;
      previewToken = preview.preview_token;
    }
    const created = await api("/api/applications", { method: "POST", body: { job_id: state.selectedJob.id, resume_id: resumeId, provider, confirm_cloud: confirmCloud, preview_token: previewToken } });
    notify("Application draft queued");
    go("resume");
    await pollApplication(created.id);
  } catch (error) { notify(error.message); }
});

async function pollApplication(id) {
  for (let attempt = 0; attempt < 180; attempt++) {
    const application = await api(`/api/applications/${encodeURIComponent(id)}`);
    if (application.status !== "preparing") {
      renderApplicationReview(application);
      renderApplications(await api("/api/applications"));
      refreshOverview();
      return;
    }
    await new Promise(resolve => window.setTimeout(resolve, 1000));
  }
}

async function loadApplication(id) {
  try { renderApplicationReview(await api(`/api/applications/${encodeURIComponent(id)}`)); }
  catch (error) { notify(error.message); }
}

function renderApplicationReview(application) {
  const panel = $("#application-review");
  panel.hidden = false;
  panel.replaceChildren();
  const title = element("div", "panel-title");
  const titleBlock = element("div");
  titleBlock.append(element("span", "panel-kicker", "APPLICATION PACKET"), element("h2", "", application.job_title || "Review your draft"));
  title.append(titleBlock, element("span", `state-label ${application.status === "failed" ? "failed" : ""}`, application.status.replaceAll("_", " ")));
  panel.append(title);
  if (application.status === "preparing") { panel.append(element("p", "muted", "Your planner is working. This screen will update when the draft is ready.")); return; }
  if (["failed", "interrupted"].includes(application.status)) {
    panel.append(element("p", "muted", application.task_error || "The planner could not prepare this draft."));
    const retry = element("button", "button button-soft", application.task_provider === "openai" ? "Start a new cloud task" : "Try again locally");
    retry.type = "button";
    retry.addEventListener("click", () => retryApplication(application));
    panel.append(retry);
    return;
  }
  if (!application.draft) { panel.append(element("p", "muted", "No draft is available.")); return; }
  const draft = application.draft;
  const grid = element("div", "review-grid");
  const cover = addEditor(grid, "Cover letter", "cover_letter", draft.cover_letter, "full");
  const alignment = addEditor(grid, "Resume alignment · one item per line", "resume_alignment", (draft.resume_alignment || []).join("\n"));
  const nextSteps = addEditor(grid, "Next steps · one item per line", "next_steps", (draft.next_steps || []).join("\n"));
  const answers = addEditor(grid, "Answers · JSON object", "answers", JSON.stringify(draft.answers || {}, null, 2), "full");
  panel.append(grid);
  const actions = element("div", "review-actions");
  const save = element("button", "button button-soft", "Save edits");
  save.type = "button";
  save.addEventListener("click", async () => { try { await saveApplicationDraft(application.id, cover, alignment, answers, nextSteps); notify("Draft edits saved"); } catch (error) { notify(error.message); } });
  actions.append(save);
  if (application.status === "needs_review") {
    const approve = element("button", "button button-dark", "Approve draft");
    approve.type = "button";
    approve.addEventListener("click", async () => {
      try {
        await saveApplicationDraft(application.id, cover, alignment, answers, nextSteps);
        await api(`/api/applications/${encodeURIComponent(application.id)}/approve`, { method: "POST" });
        notify("Draft approved for local export");
        await loadApplication(application.id);
        renderApplications(await api("/api/applications"));
      } catch (error) { notify(error.message); }
    });
    actions.append(approve);
  } else if (application.status === "approved") {
    const exportLink = element("a", "button button-dark", "Export approved draft");
    exportLink.href = `/api/applications/${encodeURIComponent(application.id)}/export`;
    exportLink.download = `careeros-${application.id.slice(0, 8)}.md`;
    actions.append(exportLink);
  }
  panel.append(actions);
}

function addEditor(root, title, field, value, extraClass = "") {
  const label = element("label", extraClass);
  label.append(element("span", "", title));
  const textarea = element("textarea");
  textarea.dataset.field = field;
  textarea.value = value || "";
  textarea.rows = field === "cover_letter" ? 9 : field === "answers" ? 8 : 5;
  label.append(textarea);
  root.append(label);
  return textarea;
}

async function saveApplicationDraft(id, cover, alignment, answers, nextSteps) {
  let answerValue;
  try { answerValue = JSON.parse(answers.value || "{}"); }
  catch { throw new Error("Answers must be valid JSON, such as {\"question\": \"answer\"}"); }
  await api(`/api/applications/${encodeURIComponent(id)}/draft`, { method: "PUT", body: { cover_letter: cover.value, resume_alignment: alignment.value.split("\n").map(value => value.trim()).filter(Boolean), answers: answerValue, next_steps: nextSteps.value.split("\n").map(value => value.trim()).filter(Boolean) } });
}

async function retryApplication(application) {
  try {
    const task = application.task_id ? await api(`/api/tasks/${encodeURIComponent(application.task_id)}`) : { provider: "ollama" };
    let confirmCloud = false;
    let previewToken = null;
    if (task.provider === "openai") {
      const preview = await api("/api/applications/preview", { method: "POST", body: { job_id: application.job_id, resume_id: application.resume_id } });
      confirmCloud = await askCloud(preview.sent_data);
      previewToken = preview.preview_token;
    }
    if (task.provider === "openai" && !confirmCloud) return;
    const created = await api("/api/applications", { method: "POST", body: { job_id: application.job_id, resume_id: application.resume_id, provider: task.provider, confirm_cloud: confirmCloud, preview_token: previewToken } });
    await pollApplication(created.id);
  } catch (error) { notify(error.message); }
}

$("#portfolio-brief").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const provider = form.elements.provider.value;
  let confirmCloud = false;
  try {
    const brief = { project_id: form.elements.project_id.value, title: form.elements.title.value, description: form.elements.description.value };
    let previewToken = null;
    if (provider === "openai") {
      const preview = await api("/api/portfolio/preview", { method: "POST", body: brief });
      confirmCloud = await askCloud(preview.sent_data);
      if (!confirmCloud) return;
      previewToken = preview.preview_token;
    }
    const created = await api("/api/portfolio/proposals", { method: "POST", body: { ...brief, provider, confirm_cloud: confirmCloud, preview_token: previewToken } });
    notify("Proposal queued for review");
    await pollProposal(created.proposal_id);
    await loadProposals();
  } catch (error) { notify(error.message); }
});

$("#reload-proposals").addEventListener("click", loadProposals);

async function loadProposals() {
  try {
    const proposals = await api("/api/portfolio/proposals");
    const list = $("#proposal-list");
    list.replaceChildren();
    if (!proposals.length) list.append(element("p", "empty-state", "Your project proposals will show up here."));
    proposals.forEach(proposal => {
      const card = element("button", "proposal-card", "");
      card.type = "button";
      const row = element("div", "list-card-top");
      row.append(element("p", "list-card-title", proposal.title), element("span", `state-label ${proposal.status === "failed" ? "failed" : ""}`, proposal.status.replaceAll("_", " ")));
      card.append(row, element("p", "list-card-sub", proposal.project_id));
      card.addEventListener("click", () => loadProposal(proposal.id));
      list.append(card);
    });
  } catch (error) { notify(error.message); }
}

async function pollProposal(id) {
  for (let attempt = 0; attempt < 180; attempt++) {
    const proposal = await api(`/api/portfolio/proposals/${encodeURIComponent(id)}`);
    if (proposal.status !== "preparing") { renderProposal(proposal); return; }
    await new Promise(resolve => window.setTimeout(resolve, 1000));
  }
}

async function loadProposal(id) {
  try { renderProposal(await api(`/api/portfolio/proposals/${encodeURIComponent(id)}`)); }
  catch (error) { notify(error.message); }
}

function renderProposal(proposal) {
  state.activeProposal = proposal;
  const panel = $("#portfolio-proposal-preview");
  panel.hidden = false;
  panel.replaceChildren();
  const title = element("div", "panel-title");
  const titleCopy = element("div");
  titleCopy.append(element("span", "panel-kicker", `REVIEW · ${proposal.project_id}`), element("h2", "", proposal.title));
  title.append(titleCopy, element("span", `state-label ${proposal.status === "failed" ? "failed" : ""}`, proposal.status.replaceAll("_", " ")));
  panel.append(title);
  if (proposal.task_error) panel.append(element("p", "muted", proposal.task_error));
  if (proposal.summary) panel.append(element("p", "review-summary", proposal.summary));
  (proposal.files || []).forEach(file => {
    const box = element("article", "file-preview");
    const head = element("header");
    const fileName = element("span", "", file.path);
    head.append(fileName);
    if (file.exists && proposal.status === "approved" && file.safe_to_replace !== false) {
      const label = element("label", "replace-choice");
      const check = document.createElement("input");
      check.type = "checkbox";
      check.value = file.path;
      check.dataset.replacePath = "true";
      label.append(check, document.createTextNode(" Replace existing file"));
      head.append(label);
    } else if (file.exists) head.append(element("span", "", "Existing file · review diff"));
    box.append(head);
    const content = element("pre");
    content.textContent = file.content;
    box.append(content);
    if (file.diff) {
      const diff = element("pre", "diff");
      diff.textContent = file.diff;
      box.append(diff);
    }
    panel.append(box);
  });
  const actions = element("div", "review-actions");
  if (proposal.status === "needs_review") {
    const approve = element("button", "button button-dark", "Approve proposal");
    approve.type = "button";
    approve.addEventListener("click", async () => {
      try { await api(`/api/portfolio/proposals/${encodeURIComponent(proposal.id)}/approve`, { method: "POST" }); await loadProposal(proposal.id); await loadProposals(); notify("Proposal approved"); }
      catch (error) { notify(error.message); }
    });
    actions.append(approve);
  } else if (proposal.status === "approved") {
    const apply = element("button", "button button-dark", "Apply files to workspace");
    apply.type = "button";
    apply.addEventListener("click", async () => {
      const replace = $$('[data-replace-path="true"]:checked', panel).map(input => input.value);
      if (replace.length && !window.confirm(`Replace these existing project files?\n\n${replace.join("\n")}`)) return;
      try {
        await api(`/api/portfolio/proposals/${encodeURIComponent(proposal.id)}/apply`, { method: "POST", body: { replace_existing: replace } });
        notify("Approved files applied to the managed project folder");
        await loadProposal(proposal.id);
        await loadProposals();
      } catch (error) { notify(error.message); }
    });
    actions.append(apply);
  } else if (["failed", "interrupted"].includes(proposal.status)) {
    const retry = element("button", "button button-dark", proposal.task_provider === "openai" ? "Start a new cloud task" : "Try again locally");
    retry.type = "button";
    retry.addEventListener("click", () => retryProposal(proposal));
    actions.append(retry);
  }
  if (actions.childElementCount) panel.append(actions);
}

async function retryProposal(proposal) {
  const brief = proposal.retry_brief;
  const provider = proposal.task_provider || "ollama";
  if (!brief) { notify("The original project brief is unavailable. Start a new proposal instead."); return; }
  try {
    let confirmCloud = false;
    let previewToken = null;
    if (provider === "openai") {
      const preview = await api("/api/portfolio/preview", { method: "POST", body: brief });
      confirmCloud = await askCloud(preview.sent_data);
      if (!confirmCloud) return;
      previewToken = preview.preview_token;
    }
    const created = await api("/api/portfolio/proposals", { method: "POST", body: { ...brief, provider, confirm_cloud: confirmCloud, preview_token: previewToken } });
    notify("A new project proposal task was queued");
    await pollProposal(created.proposal_id);
    await loadProposals();
  } catch (error) { notify(error.message); }
}

async function loadSettings() {
  try {
    state.settings = await api("/api/settings");
    state.cloudConfigured = state.settings.openai.configured;
    state.provider = state.settings.provider;
    if (state.provider === "openai" && !state.cloudConfigured) state.provider = "ollama";
    $$("input[name='default-provider']").forEach(input => { input.checked = input.value === state.provider; });
    $("#local-model-label").textContent = state.settings.ollama.model;
    $("#cloud-availability").textContent = state.cloudConfigured ? "API key found locally. Each task still requires approval." : "Not set up · add OPENAI_API_KEY to .env to enable.";
    $("#model-cost").textContent = `GPT-6 Luna standard published rates, checked ${state.settings.openai.rates_checked}: $0.10 / million input tokens · $0.50 / million output tokens. ${state.cloudConfigured ? "Each task shows what it will send." : "OpenAI stays unavailable until you configure an API key."}`;
    $$('option[value="openai"]').forEach(option => { option.disabled = !state.cloudConfigured; });
    const cloudRadio = $("input[name='default-provider'][value='openai']");
    cloudRadio.disabled = !state.cloudConfigured;
    $$("select[name='provider']").forEach(select => { select.value = state.provider; });
  } catch (error) { notify(error.message); }
}

$("#save-provider").addEventListener("click", async () => {
  const selected = $("input[name='default-provider']:checked");
  if (!selected) return;
  try {
    await api("/api/settings", { method: "PUT", body: { provider: selected.value } });
    state.provider = selected.value;
    $$("select[name='provider']").forEach(select => { select.value = state.provider; });
    notify("Default planner saved. Each cloud task still needs your confirmation.");
  } catch (error) { notify(error.message); loadSettings(); }
});

loadSettings();
refreshOverview();
startOfficePolling();
