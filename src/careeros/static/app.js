import { HandoffCursor, OfficeRenderer } from "./office-renderer.js?v=project-qa-worker-20261012";

const state = { provider: "ollama", cloudConfigured: false, settings: null, selectedJob: null, savedOnly: false, activeProposal: null, activeOutreach: null, office: null, officeSelection: null, profileEditVersion: 0 };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const officeRenderer = new OfficeRenderer($("#office-canvas"), {
  onSelect: selection => selectOffice(selection),
  onHover: (workerId, position) => renderWorkerTooltip(workerId, position),
  onViewChange: degrees => {
    const angle = $("#office-view-angle");
    if (angle) angle.textContent = `${String(Math.round(degrees) % 360).padStart(3, "0")}°`;
  },
});
const handoffCursor = new HandoffCursor(officeRenderer);
officeRenderer.update({ workers: [], counts: {} });
$("#office-reset-view").addEventListener("click", () => officeRenderer.setRotation(0));
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

function addUsPersonEligibilityField() {
  const sponsorship = $("#profile-form [name='sponsorship']");
  if (!sponsorship || $("#profile-form [name='us_person']")) return;
  const label = element("label", "", "Do you qualify as a U.S. Person?");
  const select = element("select");
  select.name = "us_person";
  [["", "Unknown / not provided"], ["yes", "Yes"], ["no", "No"]].forEach(([value, text]) => {
    const option = element("option", "", text);
    option.value = value;
    select.append(option);
  });
  label.append(select);
  sponsorship.closest("label").insertAdjacentElement("afterend", label);
}

addUsPersonEligibilityField();

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
  const screenStation = station === "qa" ? "portfolio" : station;
  const home = station === "home" || !$("#" + screenStation + "-screen");
  if (station !== "applications") state.applicationPollId = (state.applicationPollId || 0) + 1;
  state.officeSelection = home ? null : { type: "station", id: screenStation };
  document.body.dataset.station = home ? "home" : screenStation;
  officeRenderer.setSelection(state.officeSelection);
  document.body.classList.toggle("office-active", home);
  document.body.classList.toggle("station-active", !home);
  $$(".department-link").forEach(button => {
    if (button.dataset.station === (home ? "home" : station)) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $("#home-screen").hidden = !home;
  $$(".station-screen").forEach(screen => { screen.hidden = home || screen.id !== screenStation + "-screen"; });
  hideWorkerTooltip();
  closeWorkerRoster();
  closeInspectorDrawer();
  renderInspector();
  if (home) window.requestAnimationFrame(() => officeRenderer.resize());
  if (home) {
    startOfficePolling(false);
    refreshOverview();
  } else {
    officeRenderer.setActive(false);
    startOfficePolling(false);
  }
  if (!home && screenStation === "jobs") {
    searchJobs();
  } else if (!home && screenStation === "resume") {
    loadResumeDesk();
  } else if (!home && screenStation === "portfolio") {
    loadProposals();
  } else if (!home && screenStation === "applications") {
    loadOfficeApplications();
  } else if (!home && screenStation === "outreach") {
    loadOutreach();
  } else if (!home && screenStation === "settings") {
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

const VERIFICATION_OUTCOMES = {
  verified: { label: "Employer verified", tone: "verified" },
  access_restricted: { label: "Access restricted", tone: "held" },
  closed: { label: "Posting closed", tone: "held" },
  not_found: { label: "Posting closed", tone: "held" },
  identity_mismatch: { label: "Employer or role mismatch", tone: "held" },
  insufficient_detail: { label: "Posting needs more detail", tone: "held" },
  transient_error: { label: "Temporary check problem", tone: "retry" },
  unsafe_destination: { label: "Unsafe destination blocked", tone: "held" },
};

function verificationPresentation(verification) {
  if (verification?.outcome && VERIFICATION_OUTCOMES[verification.outcome]) {
    return VERIFICATION_OUTCOMES[verification.outcome];
  }
  return verification?.status === "verified"
    ? VERIFICATION_OUTCOMES.verified
    : { label: "Employer check not run", tone: "pending" };
}

function provenanceLink(label, value) {
  const url = safeJobUrl(value);
  if (!url) return null;
  const link = element("a", "job-provenance-link", label);
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
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
  if (job.location_status === "unknown") meta.append(element("span", "chip location-review", "Location needs review"));
  else if (job.location_status === "outside_us") meta.append(element("span", "chip location-review", "Outside U.S."));
  const verification = job.employer_verification || { status: "not_checked", reason: "Employer check has not run yet." };
  const presentation = verificationPresentation(verification);
  const verificationBox = element("div", `verification-info ${presentation.tone}`);
  verificationBox.append(element("strong", "", presentation.label));
  verificationBox.append(element("span", "", verification.reason || "Employer check has not run yet."));
  if (verification.checked_at) {
    verificationBox.append(element("small", "", `Checked ${formatDateTime(verification.checked_at)}`));
  }
  card.append(verificationBox);
  const provenance = element("div", "job-provenance");
  const provenanceLinks = [
    provenanceLink("Source listing", job.source_url),
    provenanceLink("Employer posting", job.employer_url || verification.final_url),
    provenanceLink("Application page", job.application_url),
  ].filter(Boolean);
  if (provenanceLinks.length) {
    provenance.append(...provenanceLinks);
    card.append(provenance);
  }
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
  if (verification.can_recheck && verification.status !== "verified") {
    const checkLabel = verification.retry_eligible ? "Retry employer check" : "Check employer posting";
    const check = element("button", "button button-outline", checkLabel);
    check.type = "button";
    check.addEventListener("click", async () => {
      check.disabled = true;
      check.textContent = "Checking…";
      try {
        const result = await api(`/api/jobs/${encodeURIComponent(job.id)}/verify`, { method: "POST" });
        notify(result.employer_verification.reason);
        searchJobs();
      } catch (error) {
        check.disabled = false;
        check.textContent = checkLabel;
        notify(error.message);
      }
    });
    actions.append(check);
  }
  if (job.is_saved && job.location_status === "us") {
    const prepare = element("button", "button button-dark", "Prepare application");
    prepare.type = "button";
    prepare.addEventListener("click", () => {
      state.selectedJob = job;
      $("#selected-job-copy").textContent = `${job.title} at ${job.company} is selected. Choose a resume and planner to start a draft.`;
      go("resume");
    });
    actions.append(prepare);
  } else if (job.is_saved && job.location_status !== "us") {
    actions.append(element("span", "small-note", "Held from preparation until a U.S. location is confirmed."));
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
  params.set("us_only", String($("#us-only").checked));
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
    const result = await api("/api/jobs/refresh", { method: "POST", body: { text: $("#job-search").value, location: $("#job-location").value, kind: $("#job-kind").value, remote_only: $("#remote-only").checked, us_only: $("#us-only").checked } });
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
    handoffCursor.initialize(snapshot);
    if (handoffCursor.afterId !== null) {
      const handoffs = await api(`/api/workspace/handoffs?after_id=${handoffCursor.afterId}&limit=100`);
      handoffCursor.receive(handoffs);
    }
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
  const workingCount = workers.filter(worker => worker.status === "working").length;
  $("#team-live-count").textContent = `${workingCount}/${workers.length}`;
  $("#team-live-count").setAttribute("aria-label", `${workingCount} active out of ${workers.length} workers`);
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
    button.dataset.workerColor = worker.color || "cyan";
    const status = ["idle", "waiting", "paused", "working", "manager_review", "quality_hold", "approved", "needs_review", "failed", "interrupted"].includes(worker.status) ? worker.status : "waiting";
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
  $("#draft-review-count").textContent = formatCount((counts.drafts_to_review || 0) + (counts.outreach_to_review || 0));
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
  outreach: { title: "LinkedIn Outreach", target: "outreach", description: "Review locally prepared messages for matched roles." },
  portfolio: { title: "Engineering & Project QA", target: "portfolio", description: "Engineering builds from sourced ideas. Project QA independently tests each build and returns defects for repair." },
  settings: { title: "Dispatch", target: "settings", description: "Choose the local planner or explicitly configure optional cloud use." },
};
const WORKER_STATIONS = {
  "job-hunter": "jobs",
  "resume-analyst": "resume",
  "application-prep": "applications",
  "hiring-manager": "applications",
  "portfolio-engineer": "portfolio",
  "project-qa": "portfolio",
  "linkedin-outreach": "outreach",
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
  if (selection.type === "worker" && window.matchMedia("(max-width: 1050px)").matches) openInspectorDrawer();
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
  if (worker.latest_verdict === null && worker.id === "hiring-manager") details.push("Latest verdict: Waiting");
  if (worker.current_item) details.push(worker.current_item);
  if (worker.latest_verdict) details.push(`Latest verdict: ${worker.latest_verdict}`);
  if (worker.qa_status) details.push(`QA cycle: ${worker.qa_status}`);
  if (worker.hold_reason) details.push(worker.hold_reason);
  if (worker.scan_summary) details.push(scanSummaryText(worker.scan_summary));
  $("#worker-tooltip-meta").textContent = details.join("  /  ");
  const modelLine = $("#worker-tooltip-model");
  if (worker.model) {
    const modelState = worker.model_status ? ` · ${formatStatus(worker.model_status)}` : "";
    modelLine.textContent = `${worker.provider || "Ollama"} · ${worker.model}${modelState}`;
    modelLine.hidden = false;
  } else {
    modelLine.textContent = "";
    modelLine.hidden = true;
  }
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
  const context = $("#inspector-context");
  const meta = $("#inspector-meta");
  const open = $("#inspector-open-station");
  const selection = state.officeSelection;
  meta.replaceChildren();
  if (!selection) {
    const workers = state.office?.workers || [];
    const counts = state.office?.counts || {};
    const reviewCount = (counts.drafts_to_review || 0) + (counts.outreach_to_review || 0) + (counts.proposals_to_review || 0);
    context.textContent = "OFFICE STATUS";
    heading.textContent = "Quick status";
    copy.textContent = state.office ? "Your office is up to date." : "Connecting to your office…";
    addInspectorMeta(meta, "Working now", workers.filter(worker => worker.status === "working").length);
    addInspectorMeta(meta, "On shift", workers.length);
    addInspectorMeta(meta, "Needs review", reviewCount);
    open.hidden = true;
    panel.hidden = false;
    return;
  }
  let target;
  if (selection.type === "worker") {
    const worker = (state.office?.workers || []).find(item => item.id === selection.id);
    if (!worker) { state.officeSelection = null; officeRenderer.setSelection(null); renderInspector(); return; }
    context.textContent = "WORKER STATUS";
    heading.textContent = worker.department || worker.id;
    copy.textContent = worker.task_label || "Waiting for work";
    target = OFFICE_STATIONS[WORKER_STATIONS[worker.id]];
    addInspectorMeta(meta, "Status", formatStatus(worker.status));
    if (worker.task_id) addInspectorMeta(meta, "Queue task", worker.task_id);
    if (worker.model) addInspectorMeta(meta, "Model", `${worker.provider || "Ollama"} · ${worker.model}`);
    if (worker.current_item) addInspectorMeta(meta, "Current item", worker.current_item);
    if (worker.latest_verdict) addInspectorMeta(meta, "Latest verdict", worker.latest_verdict);
    if (worker.qa_status) addInspectorMeta(meta, "QA result", worker.qa_status.replaceAll("_", " "));
    if (worker.hold_reason) addInspectorMeta(meta, "Hold reason", worker.hold_reason);
    if (worker.scan_summary) {
      const summary = worker.scan_summary;
      addInspectorMeta(meta, "Latest scan", `${formatCount(summary.jobs_found)} roles`);
      addInspectorMeta(meta, "Verified postings", formatCount(summary.verification_counts?.verified));
      addInspectorMeta(meta, "Source failures", formatCount(summary.failed_sources));
      addInspectorMeta(meta, "Scheduled retries", formatCount(summary.transient_retries));
      const held = Object.entries(summary.verification_counts || {})
        .filter(([outcome]) => outcome !== "verified")
        .map(([outcome, count]) => `${verificationPresentation({outcome}).label}: ${count}`);
      if (held.length) addInspectorMeta(meta, "Held outcomes", held.join(" · "));
    }
    if (worker.since) addInspectorMeta(meta, "Working for", formatElapsed(worker.since));
  } else {
    target = OFFICE_STATIONS[selection.id];
    if (!target) { state.officeSelection = null; officeRenderer.setSelection(null); renderInspector(); return; }
    context.textContent = "DEPARTMENT";
    heading.textContent = target.title;
    copy.textContent = target.description;
    const workers = (state.office?.workers || []).filter(worker => WORKER_STATIONS[worker.id] === selection.id);
    if (workers.length) addInspectorMeta(meta, "Team status", workers.map(worker => `${worker.department}: ${formatStatus(worker.status)}`).join(" · "));
  }
  open.hidden = !target || document.body.dataset.station === target.target;
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

function formatDateTime(value) {
  const timestamp = Date.parse(value || "");
  return Number.isFinite(timestamp)
    ? new Date(timestamp).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
    : "recently";
}

function scanSummaryText(summary) {
  const counts = summary.verification_counts || {};
  const parts = [`${formatCount(summary.jobs_found)} found`, `${formatCount(counts.verified)} verified`];
  if (summary.failed_sources) parts.push(`${summary.failed_sources} source failures`);
  if (summary.transient_retries) parts.push(`${summary.transient_retries} scheduled retries`);
  return parts.join(" · ");
}

function formatCount(value) { return Number.isInteger(value) ? String(value) : "0"; }
function safeStatus(value) { return ["queued", "running", "completed", "needs_review", "manager_review", "quality_hold", "approved", "failed", "interrupted"].includes(value) ? value : "queued"; }
function formatStatus(value) { return ({needs_review: "Needs your review", manager_review: "Hiring Manager review", quality_hold: "Quality hold", approved: "Approved · downloadable"})[value] || String(value || "waiting").replaceAll("_", " "); }

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
  closeInspectorDrawer();
  $("#toggle-inspector").focus();
});

function closeWorkerRoster() {
  document.body.classList.remove("roster-open");
  $("#toggle-roster").setAttribute("aria-expanded", "false");
}

function toggleWorkerRoster() {
  const opening = !document.body.classList.contains("roster-open");
  if (opening) closeInspectorDrawer();
  document.body.classList.toggle("roster-open", opening);
  $("#toggle-roster").setAttribute("aria-expanded", String(opening));
  if (opening) {
    state.officeSelection = null;
    officeRenderer.setSelection(null);
    renderInspector();
    $("#department-nav").querySelector("button")?.focus();
  }
}

function closeInspectorDrawer() {
  document.body.classList.remove("details-open");
  $("#toggle-inspector").setAttribute("aria-expanded", "false");
}

function toggleInspectorDrawer() {
  const opening = !document.body.classList.contains("details-open");
  if (opening) openInspectorDrawer();
  else closeInspectorDrawer();
}

function openInspectorDrawer() {
  closeWorkerRoster();
  document.body.classList.add("details-open");
  $("#toggle-inspector").setAttribute("aria-expanded", "true");
  $("#inspector-heading").focus();
}

$("#toggle-roster").addEventListener("click", toggleWorkerRoster);
$("#close-roster").addEventListener("click", () => {
  closeWorkerRoster();
  $("#toggle-roster").focus();
});
$("#toggle-inspector").addEventListener("click", toggleInspectorDrawer);
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  if (document.body.classList.contains("roster-open")) {
    closeWorkerRoster();
    $("#toggle-roster").focus();
  } else if (document.body.classList.contains("details-open")) {
    closeInspectorDrawer();
    $("#toggle-inspector").focus();
  }
});

$("#refresh-office-applications").addEventListener("click", loadOfficeApplications);

async function loadOfficeApplications() {
  const list = $("#office-application-list");
  try {
    const applications = await api("/api/applications");
    list.replaceChildren();
    if (!applications.length) list.append(element("p", "empty-state", "The application worker will place reviewable drafts here when a saved role and resume match."));
    applications.sort((a, b) => (a.status === "needs_review" ? -1 : 0) - (b.status === "needs_review" ? -1 : 0)).forEach(application => {
      const card = element("button", "application-card", "");
      card.type = "button";
      const row = element("div", "list-card-top");
      row.append(element("p", "list-card-title", application.job_title || "Application draft"), element("span", `state-label ${safeStatus(application.status)}`, formatStatus(application.status)));
      card.append(row, element("p", "list-card-sub", `Updated ${formatTimestamp(application.updated_at)}`));
      card.addEventListener("click", () => { go("applications"); loadApplication(application.id); });
      list.append(card);
    });
  } catch (error) {
    list.replaceChildren(element("p", "empty-state", error.message));
  }
}

$("#refresh-outreach").addEventListener("click", loadOutreach);

async function loadOutreach() {
  const list = $("#outreach-list");
  try {
    const drafts = await api("/api/outreach");
    list.replaceChildren();
    if (!drafts.length) {
      list.append(element("p", "empty-state", "Waiting for a matching role."));
      $("#outreach-review").hidden = true;
      state.activeOutreach = null;
      return;
    }
    drafts.forEach(draft => {
      const card = element("button", "application-card", "");
      card.type = "button";
      const row = element("div", "list-card-top");
      row.append(
        element("p", "list-card-title", `${draft.company} · ${draft.job_title}`),
        element("span", `state-label ${draft.status === "failed" ? "failed" : ""}`, formatStatus(draft.status)),
      );
      card.append(row, element("p", "list-card-sub", `Updated ${formatTimestamp(draft.updated_at)}`));
      card.setAttribute("aria-pressed", String(state.activeOutreach === draft.id));
      card.addEventListener("click", () => loadOutreachDraft(draft.id));
      list.append(card);
    });
    const active = drafts.find(item => item.id === state.activeOutreach) || drafts.find(item => item.status === "needs_review") || drafts[0];
    await loadOutreachDraft(active.id);
  } catch (error) {
    list.replaceChildren(element("p", "empty-state", error.message));
  }
}

async function loadOutreachDraft(id) {
  try {
    const draft = await api(`/api/outreach/${encodeURIComponent(id)}`);
    state.activeOutreach = draft.id;
    renderOutreachDraft(draft);
  } catch (error) { notify(error.message); }
}

function renderOutreachDraft(item) {
  const panel = $("#outreach-review");
  panel.hidden = false;
  panel.replaceChildren();
  const title = element("div", "panel-title");
  const copy = element("div");
  copy.append(element("span", "panel-kicker", item.company), element("h2", "", item.job_title));
  title.append(copy, element("span", `state-label ${item.status === "failed" ? "failed" : ""}`, formatStatus(item.status)));
  panel.append(title);
  const roleUrl = safeJobUrl(item.job_url);
  if (roleUrl) {
    const link = element("a", "job-link outreach-role-link", "View role");
    link.href = roleUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    panel.append(link);
  }
  if (item.status === "preparing") {
    panel.append(element("p", "muted", "Preparing locally…"));
    return;
  }
  if (["failed", "interrupted"].includes(item.status)) {
    panel.append(element("p", "muted", item.task_error || "The local draft could not be prepared. A later role scan can retry."));
    return;
  }
  if (!item.draft) {
    panel.append(element("p", "muted", "No message is available."));
    return;
  }

  const message = item.draft;
  if (item.status === "needs_review") {
    const grid = element("div", "review-grid outreach-editors");
    const note = addOutreachEditor(grid, "Connection note", message.connection_note, 4, 200);
    const followUp = addOutreachEditor(grid, "Follow-up message", message.follow_up_message, 8);
    const evidence = addOutreachEditor(grid, "Resume evidence · one item per line", (message.evidence || []).join("\n"), 4);
    panel.append(grid);
    const actions = element("div", "review-actions");
    const save = element("button", "button button-soft", "Save edits");
    save.type = "button";
    save.addEventListener("click", async () => {
      try {
        await saveOutreachDraft(item.id, note, followUp, evidence);
        notify("Outreach edits saved");
        await loadOutreach();
      } catch (error) { notify(error.message); }
    });
    const approve = element("button", "button button-dark", "Approve for manual use");
    approve.type = "button";
    approve.addEventListener("click", async () => {
      try {
        await saveOutreachDraft(item.id, note, followUp, evidence);
        await api(`/api/outreach/${encodeURIComponent(item.id)}/approve`, { method: "POST" });
        notify("Approved. Choose a contact and send it yourself.");
        await loadOutreach();
        refreshOverview();
      } catch (error) { notify(error.message); }
    });
    actions.append(save, approve);
    panel.append(actions);
    return;
  }

  panel.append(outreachMessage("Connection note", message.connection_note));
  panel.append(outreachMessage("Follow-up message", message.follow_up_message));
  if ((message.evidence || []).length) {
    const evidence = element("ul", "outreach-evidence");
    message.evidence.forEach(item => evidence.append(element("li", "", item)));
    panel.append(evidence);
  }
  const actions = element("div", "review-actions outreach-actions");
  actions.append(
    copyOutreachButton(item.id, "Copy connection note", message.connection_note),
    copyOutreachButton(item.id, "Copy follow-up", message.follow_up_message),
  );
  const exportLink = element("a", "button button-soft", "Export both");
  exportLink.href = `/api/outreach/${encodeURIComponent(item.id)}/export`;
  exportLink.download = `careeros-outreach-${item.id.slice(0, 8)}.txt`;
  actions.append(exportLink);
  panel.append(actions, element("p", "small-note", "Approved for you to copy and send manually."));
}

function addOutreachEditor(root, title, value, rows, maxLength = null) {
  const label = element("label", "full");
  label.append(element("span", "", title));
  const textarea = element("textarea");
  textarea.value = value || "";
  textarea.rows = rows;
  if (maxLength) {
    textarea.maxLength = maxLength;
    const counter = element("small", "outreach-character-count", `${textarea.value.length}/${maxLength}`);
    textarea.addEventListener("input", () => { counter.textContent = `${textarea.value.length}/${maxLength}`; });
    label.append(textarea, counter);
    root.append(label);
    return textarea;
  }
  label.append(textarea);
  root.append(label);
  return textarea;
}

async function saveOutreachDraft(id, note, followUp, evidence) {
  await api(`/api/outreach/${encodeURIComponent(id)}/draft`, {
    method: "PUT",
    body: {
      connection_note: note.value,
      follow_up_message: followUp.value,
      evidence: evidence.value.split("\n").map(value => value.trim()).filter(Boolean),
    },
  });
}

function outreachMessage(title, value) {
  const section = element("section", "outreach-message-section");
  section.append(element("h3", "list-card-title", title), element("p", "outreach-message", value));
  return section;
}

function copyOutreachButton(id, label, value) {
  const button = element("button", "button button-soft", label);
  button.type = "button";
  button.addEventListener("click", async () => {
    if (state.activeOutreach !== id) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard access is unavailable. Select the message to copy it.");
      await navigator.clipboard.writeText(value);
      notify("Copied to clipboard");
    } catch (error) { notify(error.message); }
  });
  return button;
}

function startOfficePolling(refreshNow = true) {
  if (document.visibilityState !== "visible") {
    officeRenderer.setActive(false);
    stopOfficePolling();
    return;
  }
  officeRenderer.setActive(!$("#home-screen").hidden);
  if (officePollTimer) return;
  if (refreshNow) refreshOffice();
  officePollTimer = window.setInterval(refreshOffice, 2000);
}

function stopOfficePolling() {
  if (!officePollTimer) return;
  window.clearInterval(officePollTimer);
  officePollTimer = null;
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") startOfficePolling();
  else {
    officeRenderer.setActive(false);
    stopOfficePolling();
  }
});

$("#close-inspector").setAttribute("aria-label", "Close selected details");

function splitList(text) { return text.split(",").map(value => value.trim()).filter(Boolean).slice(0, 20); }

async function loadResumeDesk() {
  try {
    const [profile, resumes, applications] = await Promise.all([api("/api/profile"), api("/api/resumes"), api("/api/applications")]);
    const form = $("#profile-form");
    if (state.profileEditVersion === 0) {
      form.elements.name.value = profile.name || "";
      form.elements.summary.value = profile.summary || "";
      form.elements.target_roles.value = (profile.target_roles || []).join(", ");
      form.elements.preferred_locations.value = (profile.preferred_locations || []).join(", ");
      form.elements.skills.value = (profile.skills || []).join(", ");
      const facts = profile.eligibility_facts || {};
      const eligibilityFields = ["work_authorization", "citizenship", "enrollment", "graduation", "sponsorship", "us_person", "experience_years"];
      eligibilityFields.forEach(key => { form.elements[key].value = facts[key] || ""; });
      form.elements.other_eligibility.value = Object.entries(facts).filter(([key]) => !eligibilityFields.includes(key)).map(([key, value]) => `${key} = ${value}`).join("\n");
    }
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

$("#profile-form").addEventListener("input", () => { state.profileEditVersion += 1; });

$("#profile-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const eligibilityFacts = Object.create(null);
    ["work_authorization", "citizenship", "enrollment", "graduation", "sponsorship", "us_person", "experience_years"].forEach(key => {
      const value = form.elements[key].value.trim();
      if (value) eligibilityFacts[key] = value;
    });
    for (const line of form.elements.other_eligibility.value.split("\n").filter(value => value.trim())) {
      const separator = line.indexOf("=");
      if (separator < 1 || !line.slice(separator + 1).trim()) throw new Error("Use fact = value for each other eligibility fact");
      const key = line.slice(0, separator).trim();
      if (Object.hasOwn(eligibilityFacts, key)) throw new Error(`Eligibility fact already provided: ${key}`);
      eligibilityFacts[key] = line.slice(separator + 1).trim();
    }
    const submittedEditVersion = state.profileEditVersion;
    await api("/api/profile", { method: "PUT", body: { name: form.elements.name.value, summary: form.elements.summary.value, target_roles: splitList(form.elements.target_roles.value), preferred_locations: splitList(form.elements.preferred_locations.value), skills: splitList(form.elements.skills.value), eligibility_facts: eligibilityFacts } });
    if (state.profileEditVersion === submittedEditVersion) state.profileEditVersion = 0;
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
    row.append(element("p", "list-card-title", item.job_title || "Application"), element("span", `state-label ${item.status === "failed" ? "failed" : ""}`, formatStatus(item.status)));
    card.append(row, element("p", "list-card-sub", `Updated ${new Date(item.updated_at).toLocaleDateString()}`));
    card.addEventListener("click", () => { go("applications"); loadApplication(item.id); });
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
    go("applications");
    await pollApplication(created.id);
  } catch (error) { notify(error.message); }
});

async function pollApplication(id, renderedAt = null, generation = null) {
  const pollId = generation ?? (state.applicationPollId = (state.applicationPollId || 0) + 1);
  for (let attempt = 0; attempt < 180; attempt++) {
    if (pollId !== state.applicationPollId || document.body.dataset.station !== "applications") return;
    const application = await api(`/api/applications/${encodeURIComponent(id)}`);
    if (pollId !== state.applicationPollId) return;
    const renderKey = `${application.updated_at}:${application.manager_task_status}`;
    if (renderedAt !== renderKey) {
      renderApplicationReview(application);
      renderedAt = renderKey;
    }
    if (!["preparing", "manager_review"].includes(application.status) || ["failed", "interrupted"].includes(application.manager_task_status)) {
      const applications = await api("/api/applications");
      if (pollId !== state.applicationPollId) return;
      renderApplications(applications);
      await loadOfficeApplications();
      if (pollId !== state.applicationPollId) return;
      refreshOverview();
      return;
    }
    await new Promise(resolve => window.setTimeout(resolve, 1000));
  }
}

async function loadApplication(id) {
  const generation = state.applicationPollId = (state.applicationPollId || 0) + 1;
  if (document.body.dataset.station !== "applications") go("applications");
  try {
    const application = await api(`/api/applications/${encodeURIComponent(id)}`);
    if (generation !== state.applicationPollId) return;
    renderApplicationReview(application, true);
    if (["preparing", "manager_review"].includes(application.status)) {
      pollApplication(id, `${application.updated_at}:${application.manager_task_status}`, generation)
        .catch(error => { if (generation === state.applicationPollId) notify(error.message); });
    }
  }
  catch (error) { if (generation === state.applicationPollId) notify(error.message); }
}

function renderApplicationReview(application, focus = false) {
  const panel = $("#application-review");
  panel.hidden = false;
  panel.replaceChildren();
  const heading = element("h2", "", application.job_title || "Application review");
  const status = element("p", `review-status ${application.status === "quality_hold" ? "held" : !application.clearance_stale ? "cleared" : ""}`, formatStatus(application.status));
  status.setAttribute("role", "status");
  panel.append(heading, status, element("p", "muted", "Approval enables a local download. CareerOS never submits an application."));
  const job = application.snapshot?.job;
  if (job) {
    panel.append(element("p", "", `${job.company} · ${job.title} · ${job.location || "Location not listed"}`));
    const link = element("a", "text-button", "View verified employer posting");
    if (/^https?:\/\//.test(job.verification?.final_url || "")) link.href = job.verification.final_url;
    link.target = "_blank"; link.rel = "noopener noreferrer";
    panel.append(link);
    const gates = element("details");
    gates.append(element("summary", "", "Employer checks and eligibility"));
    (job.gates || []).forEach(gate => gates.append(element("p", "", `${gate.name}: ${gate.passed ? "Passed" : "Held"} — ${gate.reason}`)));
    gates.append(element("p", "muted", "Approval and download recheck the employer posting and your current eligibility."));
    panel.append(gates);
  }
  panel.append(element("p", "review-status", `Draft: ${application.provider || "local"} · ${application.model || "Unknown model"}. Hiring Manager: Ollama · ${application.manager_task_status || "Waiting"}. Review ${application.manager_cycle || 0} of 3.`));
  if (application.hold_reason) panel.append(element("p", "review-status held", application.hold_reason));
  if (application.manager_task_error) panel.append(element("p", "review-status held", application.manager_task_error));
  if (application.review_task_error && application.review_task_error !== application.manager_task_error) panel.append(element("p", "review-status held", application.review_task_error));
  if (application.rejection_reason) panel.append(element("p", "", `Your revision request: ${application.rejection_reason}`));
  if (["failed", "interrupted"].includes(application.status)) {
    panel.append(element("p", "muted", application.task_error || "Draft preparation stopped."));
    const retry = element("button", "button button-soft", "Prepare a new application");
    retry.type = "button"; retry.addEventListener("click", () => retryApplication(application)); panel.append(retry);
  }
  const history = element("details");
  history.append(element("summary", "", "All critiques and fixes"));
  (application.hiring_reviews || []).forEach((review, index, reviews) => {
    history.append(element("h3", "", `Review ${review.cycle}: ${review.verdict}`));
    history.append(element("p", "muted", `${review.provider} · ${review.model} · Draft ${review.draft_version}`));
    review.findings.forEach(finding => history.append(element("p", "", `${finding.severity}: ${finding.issue}. ${finding.revision_instruction} Evidence: ${finding.evidence_ids.join(", ") || "Deterministic check"}`)));
    const nextDraft = reviews[index + 1]?.reviewed_draft || application.draft;
    if (review.reviewed_draft) {
      const original = element("details"); original.append(element("summary", "", "Draft reviewed in this cycle"), element("pre", "", JSON.stringify(review.reviewed_draft, null, 2))); history.append(original);
      if (nextDraft && JSON.stringify(nextDraft) !== JSON.stringify(review.reviewed_draft)) {
        const fixes = element("details"); fixes.append(element("summary", "", "Revised draft after this critique"), element("pre", "", JSON.stringify(nextDraft, null, 2))); history.append(fixes);
      } else history.append(element("p", "muted", "No later draft changes recorded."));
    }
  });
  panel.append(history);
  if (!application.draft) { panel.append(element("p", "muted", "Waiting for a complete draft.")); return; }
  const draft = application.draft;
  const canEdit = ["needs_review", "approved"].includes(application.status) && application.manager_cycle < 3;
  const grid = element("div", "review-grid");
  const resume = addEditor(grid, "Tailored resume", "resume_text", draft.resume_text, "full");
  const cover = addEditor(grid, "Cover letter", "cover_letter", draft.cover_letter, "full");
  const answers = addEditor(grid, "Application answers (question and answer JSON)", "answers", JSON.stringify(draft.answers || {}, null, 2), "full");
  const evidence = element("details", "full");
  evidence.append(element("summary", "", "Claims and fixed evidence"));
  const claims = addEditor(evidence, "Evidence links (JSON)", "claims", JSON.stringify(draft.claims || [], null, 2));
  evidence.append(element("pre", "", JSON.stringify(application.snapshot?.evidence || {}, null, 2)));
  grid.append(evidence);
  [resume, cover, answers, claims].forEach(editor => { editor.readOnly = true; });
  panel.append(grid);
  const actions = element("div", "review-actions");
  const refresh = async () => { await loadApplication(application.id); await loadOfficeApplications(); };
  if (application.can_retry_review) {
    const retry = element("button", "button button-soft", "Retry local review");
    retry.type = "button";
    retry.addEventListener("click", async () => { try { await api(`/api/applications/${encodeURIComponent(application.id)}/retry-review`, {method: "POST"}); notify("Local review queued again"); await refresh(); } catch (error) { notify(error.message); } });
    actions.append(retry);
  }
  const changed = () => resume.value !== draft.resume_text || cover.value !== draft.cover_letter || answers.value !== JSON.stringify(draft.answers || {}, null, 2) || claims.value !== JSON.stringify(draft.claims || [], null, 2);
  if (canEdit) {
    const edit = element("button", "button button-soft", "Edit"); edit.type = "button";
    edit.addEventListener("click", () => { [resume, cover, answers, claims].forEach(editor => { editor.readOnly = false; }); save.hidden = false; resume.focus(); });
    const save = element("button", "button button-soft", "Save edits and request manager review"); save.type = "button"; save.hidden = true;
    save.addEventListener("click", async () => { try { await saveApplicationDraft(application.id, draft, resume, cover, answers, claims); notify("Edits saved. Hiring Manager review queued locally."); await refresh(); } catch (error) { notify(error.message); } });
    actions.append(edit, save);
  } else if (application.manager_cycle >= 3) panel.append(element("p", "muted", "The three-review limit is reached. Prepare a new application for further changes."));
  if (["needs_review", "approved"].includes(application.status) && application.manager_cycle < 3) {
    const reason = element("label", "full"); reason.append(element("span", "", "Reason for revision (optional)")); const input = element("textarea"); input.maxLength = 2000; input.rows = 2; reason.append(input); panel.append(reason);
    const reject = element("button", "button button-soft", "Reject and revise locally"); reject.type = "button";
    reject.addEventListener("click", async () => { try { await api(`/api/applications/${encodeURIComponent(application.id)}/reject`, {method: "POST", body: {reason: input.value}}); notify("Revision queued with Ollama."); await refresh(); } catch (error) { notify(error.message); } }); actions.append(reject);
  }
  if (application.status === "needs_review" && !application.clearance_stale) {
    const approve = element("button", "button button-dark", "Approve for local download"); approve.type = "button";
    approve.setAttribute("aria-label", "Approve for local download. Nothing will be submitted.");
    approve.addEventListener("click", async () => {
      if (changed()) { notify("Save your edits and wait for Hiring Manager clearance before approving."); return; }
      try {
      await api(`/api/applications/${encodeURIComponent(application.id)}/approve`, {method: "POST"}); notify("Approved for local download. Nothing was submitted."); await refresh();
    } catch (error) { notify(error.message); await refresh(); } }); actions.prepend(approve);
  } else if (application.status === "approved") {
    const download = element("button", "button button-dark", "Download package"); download.type = "button";
    download.addEventListener("click", async () => {
      if (changed()) { notify("Save edits for another review before downloading changed materials."); return; }
      try {
      const response = await fetch(`/api/applications/${encodeURIComponent(application.id)}/export`);
      if (!response.ok) { const error = await response.json(); throw new Error(error.detail || "Package download failed"); }
      const url = URL.createObjectURL(await response.blob()); const link = element("a"); link.href = url; link.download = `application-${application.id}.zip`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); notify("Local package downloaded. Nothing was submitted.");
    } catch (error) { notify(error.message); await refresh(); } }); actions.prepend(download);
  }
  panel.append(actions);
  const fact = element("details"); fact.append(element("summary", "", "Add an accurate new fact"), element("p", "muted", "Save a new fact locally, then prepare a new application. This draft keeps its original evidence snapshot."));
  const nameLabel = element("label"); nameLabel.append(element("span", "", "Fact name")); const name = element("input"); name.maxLength = 120; nameLabel.append(name);
  const valueLabel = element("label"); valueLabel.append(element("span", "", "Accurate fact")); const value = element("textarea"); value.maxLength = 500; valueLabel.append(value);
  const confirmation = element("label"); const checkbox = element("input"); checkbox.type = "checkbox"; confirmation.append(checkbox, element("span", "", "I confirm this is accurate"));
  const attest = element("button", "button button-soft", "Save confirmed fact locally"); attest.type = "button";
  attest.addEventListener("click", async () => { try { if (!checkbox.checked) throw new Error("Confirm that this fact is accurate first."); const result = await api(`/api/applications/${encodeURIComponent(application.id)}/evidence`, {method: "POST", body: {name: name.value, value: value.value, confirm_accurate: checkbox.checked}}); notify(result.message); checkbox.checked = false; } catch(error) { notify(error.message); } });
  fact.append(nameLabel, valueLabel, confirmation, attest); panel.append(fact);
  if (focus) panel.focus({preventScroll: true});
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

async function saveApplicationDraft(id, original, resume, cover, answers, claims) {
  let answerValue, claimValue;
  try { answerValue = JSON.parse(answers.value || "{}"); claimValue = JSON.parse(claims.value || "[]"); }
  catch { throw new Error("Answers and evidence links must be valid JSON."); }
  await api(`/api/applications/${encodeURIComponent(id)}/draft`, {method: "PUT", body: {...original, resume_text: resume.value, cover_letter: cover.value, answers: answerValue, claims: claimValue}});
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
  if (proposal.source_urls?.length) {
    const sources = element("div", "qa-sources");
    sources.append(element("strong", "", "Idea sources"));
    proposal.source_urls.forEach(value => {
      const url = safeJobUrl(value);
      if (!url) return;
      const link = element("a", "job-link", new URL(url).hostname);
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      sources.append(link);
    });
    panel.append(sources);
  }
  const qa = proposal.latest_qa;
  if (qa) {
    const review = element("section", `qa-review qa-${qa.status}`);
    review.append(element("h3", "", `Independent Project QA · ${qa.status.replaceAll("_", " ")}`));
    review.append(element("p", "muted", `Cycle ${qa.cycle} of 3 · ${qa.model || "Ollama"} · sandbox ${qa.deterministic_report?.available ? (qa.deterministic_report.exit_code === 0 ? "passed" : "failed") : "unavailable"}`));
    (qa.critique?.findings || []).forEach(finding => {
      const item = element("article", "qa-finding");
      item.append(element("strong", "", finding.issue || "QA finding"));
      if (finding.file) item.append(element("small", "", finding.file));
      if (finding.evidence) item.append(element("pre", "", finding.evidence));
      review.append(item);
    });
    if (proposal.hold_reason) review.append(element("p", "review-status held", proposal.hold_reason));
    panel.append(review);
  }
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
