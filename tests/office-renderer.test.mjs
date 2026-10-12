import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import test from "node:test";

const layoutSource = await readFile(new URL("../src/careeros/static/office-layout.js", import.meta.url), "utf8");
const rendererSource = await readFile(new URL("../src/careeros/static/office-renderer.js", import.meta.url), "utf8");
const layoutUrl = `data:text/javascript;base64,${Buffer.from(layoutSource).toString("base64")}`;
const rendererModule = rendererSource.replace('from "./office-layout.js"', `from "${layoutUrl}"`);
const { OfficeRenderer, HandoffCursor } = await import(`data:text/javascript;base64,${Buffer.from(rendererModule).toString("base64")}`);
const { CONVEYOR_NETWORK, FLOOR_CELLS, PALETTE, STATIONS, WORKER_APPEARANCE, WORKER_DISPLAY_SCALE } = await import(layoutUrl);

function canvasHarness() {
  const filledStyles = [];
  const rectStyles = [];
  const rectCalls = [];
  const linearGradients = [];
  const listeners = new Map();
  let context;
  context = new Proxy({
    createRadialGradient: () => ({ addColorStop() {} }),
    createLinearGradient: (...args) => {
      const gradient = { args, stops: [], addColorStop(offset, color) { this.stops.push({ offset, color }); } };
      linearGradients.push(gradient);
      return gradient;
    },
    measureText: value => ({ width: value.length * 3 }),
    fill: () => { filledStyles.push(context.fillStyle); },
    fillRect: (...args) => {
      rectStyles.push(context.fillStyle);
      rectCalls.push({ style: context.fillStyle, x: args[0], y: args[1], width: args[2], height: args[3] });
    },
  }, {
    get(target, key) {
      if (key in target) return target[key];
      return () => {};
    },
    set(target, key, value) {
      target[key] = value;
      return true;
    },
  });
  const canvas = {
    width: 0,
    height: 0,
    style: {},
    getContext: () => context,
    getBoundingClientRect: () => ({ width: 600, height: 338, left: 0, top: 0 }),
    addEventListener: (name, handler) => listeners.set(name, handler),
    removeEventListener: name => listeners.delete(name),
    setPointerCapture() {},
    releasePointerCapture() {},
  };
  return { canvas, filledStyles, rectStyles, rectCalls, linearGradients, listeners };
}

function withReducedMotion(callback) {
  const previousWindow = globalThis.window;
  globalThis.window = {
    devicePixelRatio: 1,
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {} }),
    addEventListener() {},
    removeEventListener() {},
  };
  try {
    return callback();
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
}

function withAnimationFrames(callback) {
  const previousWindow = globalThis.window;
  let nextFrameId = 0;
  const frames = new Map();
  const cancelled = [];
  globalThis.window = {
    devicePixelRatio: 1,
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    addEventListener() {},
    removeEventListener() {},
    requestAnimationFrame(handler) {
      const id = ++nextFrameId;
      frames.set(id, handler);
      return id;
    },
    cancelAnimationFrame(id) {
      cancelled.push(id);
      frames.delete(id);
    },
  };
  try {
    return callback({ frames, cancelled });
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
}

test("renderer draws the connected conveyor lanes over an atmospheric backdrop", () => {
  withReducedMotion(() => {
    const { canvas, filledStyles, linearGradients } = canvasHarness();
    new OfficeRenderer(canvas).update({ workers: [], counts: {} });
    const floorMaterials = new Set(FLOOR_CELLS.map(cell => cell.material));
    const filledFloorTiles = filledStyles.filter(color => floorMaterials.has(color)).length;
    assert.ok(filledFloorTiles >= FLOOR_CELLS.length * 0.7,
      `expected visible filled floor tiles for the whole isometric map; got ${filledFloorTiles} of ${FLOOR_CELLS.length}`);
    assert.ok(filledStyles.filter(color => color === PALETTE.conveyor).length >= CONVEYOR_NETWORK.length,
      "all conveyor routes should have a rendered top surface");
    assert.ok(linearGradients.length > 0, "the office should sit against a layered colored backdrop");
  });
});

test("an active task cannot manufacture a handoff parcel", () => {
  withReducedMotion(() => {
    const { canvas, rectCalls } = canvasHarness();
    const renderer = new OfficeRenderer(canvas);
    renderer.update({ workers: [{id: "job-hunter", status: "working", station_id: "job-hunters-01", task_id: "task-123"}], counts: {} });
    assert.deepEqual(renderer.activeConveyorParcels(500), []);
    assert.deepEqual(renderer.activeHandoffTokens(500), []);
    assert.equal(rectCalls.filter(call => call.style === PALETTE.parcel).length, 0);
    renderer.destroy();
  });
});

test("dragging orbits the office and Dispatch opens the Planner inspector", () => {
  withReducedMotion(() => {
    const { canvas, listeners } = canvasHarness();
    const selections = [];
    const viewChanges = [];
    const renderer = new OfficeRenderer(canvas, {
      onSelect: selection => selections.push(selection),
      onViewChange: degrees => viewChanges.push(degrees),
    });
    const dispatch = STATIONS.find(item => item.room === "dispatch");
    const point = renderer.project(dispatch.cell.col, dispatch.cell.row);
    renderer.selectAt({ clientX: point.x, clientY: point.y });
    assert.deepEqual(selections.at(-1), { type: "station", id: "settings" });

    renderer.setRotation(73);
    const rotatedPoint = renderer.project(dispatch.cell.col, dispatch.cell.row);
    renderer.selectAt({ clientX: rotatedPoint.x, clientY: rotatedPoint.y });
    assert.deepEqual(selections.at(-1), { type: "station", id: "settings" }, "desk hit areas should follow the orbiting camera");

    listeners.get("pointerdown")({ button: 0, clientX: 180, clientY: 160, pointerId: 1 });
    listeners.get("pointermove")({ clientX: 300, clientY: 162, pointerId: 1 });
    listeners.get("pointerup")({ pointerId: 1 });

    assert.ok(viewChanges.some(degrees => degrees !== 73), "a horizontal drag should change the camera angle");
    assert.equal(renderer.drag, null, "pointer release should finish the orbit gesture");
    const selectionsAfterOrbit = selections.length;
    renderer.selectAt({ clientX: rotatedPoint.x, clientY: rotatedPoint.y });
    assert.equal(selections.length, selectionsAfterOrbit, "the orbit gesture should not accidentally select a room");
    renderer.destroy();
  });
});

test("pointer cancellation preserves the next click and arrow keys orbit the office", () => {
  withReducedMotion(() => {
    const { canvas, listeners } = canvasHarness();
    const selections = [];
    const renderer = new OfficeRenderer(canvas, { onSelect: selection => selections.push(selection) });
    const dispatch = STATIONS.find(item => item.room === "dispatch");
    let prevented = false;

    listeners.get("pointerdown")({ button: 0, clientX: 100, clientY: 150, pointerId: 2 });
    listeners.get("pointermove")({ clientX: 160, clientY: 150, pointerId: 2 });
    listeners.get("pointercancel")({ pointerId: 2 });
    const point = renderer.project(dispatch.cell.col, dispatch.cell.row);
    renderer.selectAt({ clientX: point.x, clientY: point.y });
    assert.deepEqual(selections.at(-1), { type: "station", id: "settings" }, "cancel should not swallow a later click");

    const angleBeforeKey = renderer.rotation;
    listeners.get("keydown")({ key: "ArrowRight", preventDefault: () => { prevented = true; } });
    assert.ok(Math.abs(renderer.rotation - angleBeforeKey - 15) < 0.01, "right arrow should rotate the camera by one step");
    assert.equal(prevented, true, "camera keys should not scroll the page");
    listeners.get("keydown")({ key: "Home", preventDefault() {} });
    assert.equal(renderer.rotation, 0, "Home should restore the starting angle");
    renderer.destroy();
  });
});

test("higher-density worker pixels keep the same clickable sprite footprint", () => {
  withReducedMotion(() => {
    const { canvas, rectStyles } = canvasHarness();
    const renderer = new OfficeRenderer(canvas);
    renderer.update({
      workers: [{ id: "job-hunter", name: "Job Hunter", color: "cyan", status: "idle", station_id: "job-hunters-01" }],
      counts: {},
    });
    const actor = renderer.actors.get("job-hunter");
    const appearance = WORKER_APPEARANCE["job-hunter"];
    assert.ok(Math.abs(actor.bounds.width - 22 * WORKER_DISPLAY_SCALE * renderer.project.scale) < 0.01);
    assert.ok(Math.abs(actor.bounds.height - 36 * WORKER_DISPLAY_SCALE * renderer.project.scale) < 0.01);
    assert.ok(appearance.sprite.length >= 70 && appearance.sprite[0].length >= 40);
    assert.ok(rectStyles.includes("rgb(103, 255, 255)"), "worker silhouette should use a bright department-colored rim");
    renderer.destroy();
  });
});

test("renderer cancels animation while inactive and resumes it on return", () => {
  withAnimationFrames(({ frames, cancelled }) => {
    const { canvas } = canvasHarness();
    const renderer = new OfficeRenderer(canvas);
    assert.equal(frames.size, 1, "visible office should have one pending animation frame");

    renderer.setActive(false);
    assert.equal(frames.size, 0, "hidden office should cancel its pending animation frame");
    assert.equal(cancelled.length, 1);

    renderer.setActive(true);
    assert.equal(frames.size, 1, "returning to the office should resume animation");
    renderer.destroy();
    assert.equal(frames.size, 0, "destroy should cancel the resumed animation frame");
  });
});

const handoff = (id, eventType, fromWorker = "application-prep", toWorker = "resume-analyst") => ({
  id, event_type: eventType, from_worker: fromWorker, to_worker: toWorker,
  from_station_id: "application-team-01", to_station_id: "resume-team-01", item_type: "document",
});

test("renderer queues recognized handoffs and ignores unknown event types", () => {
  withAnimationFrames(() => {
    const { canvas, rectCalls } = canvasHarness();
    const renderer = new OfficeRenderer(canvas, { now: () => 1000 });
    renderer.update({
      workers: [{ id: "application-prep", station_id: "application-team-01", status: "working", color: "amber" }],
      counts: {},
    });
    assert.equal(renderer.handoffs.length, 0, "worker status alone must not create a handoff");
    const greenPixelsBefore = rectCalls.filter(call => call.style === PALETTE.green).length;
    renderer.playHandoffs([
      handoff(1, "draft-submitted"), handoff(2, "critique-returned"),
      handoff(3, "project-submitted"), handoff(4, "project-defect-returned"),
      handoff(5, "project-qa-passed"), handoff(6, "unrecognized"),
    ]);
    assert.deepEqual(renderer.handoffs.map(item => item.kind), ["document", "ticket", "project", "ticket", "green-pass"]);
    renderer.draw(10000);
    assert.ok(rectCalls.filter(call => call.style === PALETTE.green).length > greenPixelsBefore,
      "the green pass should be painted in the office");
    renderer.destroy();
  });
});

test("handoff tokens exchange between workers and settle after 1300 ms and expire after 2 seconds", () => {
  withAnimationFrames(() => {
    const { canvas } = canvasHarness();
    const renderer = new OfficeRenderer(canvas, { now: () => 1000 });
    renderer.playHandoffs([handoff(1, "draft-submitted")]);
    const start = renderer.activeHandoffTokens(1000)[0];
    const middle = renderer.activeHandoffTokens(1250)[0];
    const end = renderer.activeHandoffTokens(2300)[0];
    assert.deepEqual({ col: start.col, row: start.row }, { col: 4, row: 8 });
    assert.deepEqual({ col: end.col, row: end.row }, { col: 9, row: 2 });
    assert.ok(middle.col > Math.min(start.col, end.col) && middle.col < Math.max(start.col, end.col));
    assert.ok(middle.row > Math.min(start.row, end.row) && middle.row < Math.max(start.row, end.row));
    assert.deepEqual(renderer.activeHandoffTokens(3001), []);
    renderer.destroy();
  });
});

test("reduced motion shows the settled handoff without travel", () => {
  withReducedMotion(() => {
    const { canvas } = canvasHarness();
    const renderer = new OfficeRenderer(canvas, { now: () => 1000 });
    renderer.playHandoffs([handoff(1, "project-qa-passed")]);
    const atStart = renderer.activeHandoffTokens(1000)[0];
    const later = renderer.activeHandoffTokens(1500)[0];
    assert.deepEqual({ col: atStart.col, row: atStart.row }, { col: later.col, row: later.row });
    assert.equal(atStart.kind, "green-pass");
    renderer.destroy();
  });
});

test("initial snapshot cursor suppresses old events and consecutive polls do not replay IDs", () => {
  const played = [];
  const cursor = new HandoffCursor({ playHandoffs(events) { played.push(...events); } });
  cursor.initialize({ handoff_cursor: 4 });
  assert.equal(cursor.afterId, 4);
  cursor.receive({ events: [handoff(5, "draft-submitted")], latest_id: 5 });
  cursor.initialize({ handoff_cursor: 99 });
  assert.equal(cursor.afterId, 5, "later snapshots must not skip events between polls");
  cursor.receive({ events: [handoff(5, "draft-submitted"), handoff(6, "critique-returned")], latest_id: 6 });
  assert.deepEqual(played.map(event => event.id), [5, 6]);
  const reloaded = new HandoffCursor({ playHandoffs(events) { played.push(...events); } });
  reloaded.initialize({ handoff_cursor: 6 });
  assert.equal(reloaded.afterId, 6);
  assert.deepEqual(played.map(event => event.id), [5, 6], "reload must not enqueue the earlier events");
});

test("cursor drains a capped handoff page before advancing to the global latest ID", () => {
  const played = [];
  const cursor = new HandoffCursor({ playHandoffs(events) { played.push(...events); } });
  cursor.initialize({ handoff_cursor: 0 });
  cursor.receive({
    events: Array.from({ length: 100 }, (_, index) => handoff(index + 1, "draft-submitted")),
    latest_id: 101,
  });
  assert.equal(cursor.afterId, 100, "the next request must begin after the last delivered event");
  cursor.receive({ events: [handoff(101, "draft-submitted")], latest_id: 101 });
  assert.deepEqual(played.map(event => event.id), Array.from({ length: 101 }, (_, index) => index + 1));
  assert.equal(cursor.afterId, 101);
});

test('Hiring Manager has a distinct male sprite at the persisted review station', () => {
  const manager = WORKER_APPEARANCE['hiring-manager'];
  assert.equal(manager.gender, 'male');
  assert.equal(manager.stationId, 'hiring-manager-01');
  assert.ok(manager.sprite.some(row => row.includes('M')), 'short beard defines the male manager sprite');
  assert.notDeepEqual(manager.sprite, WORKER_APPEARANCE['application-prep'].sprite);
  assert.ok(STATIONS.some(station => station.workerStationId === manager.stationId));
});

test('working status alone cannot create conveyor or worker movement', () => {
  withAnimationFrames(() => {
    const renderer = new OfficeRenderer(canvasHarness().canvas);
    renderer.update({workers: [{id: 'hiring-manager', station_id: 'hiring-manager-01', status: 'working', task_id: 'real-task'}]});
    const actor = renderer.actors.get('hiring-manager');
    const before = {col: actor.col, row: actor.row};
    renderer.advanceActors(1000);
    assert.deepEqual({col: actor.col, row: actor.row}, before);
    assert.deepEqual(renderer.activeConveyorParcels(500), []);
    assert.deepEqual(renderer.activeHandoffTokens(500), []);
    renderer.destroy();
  });
});

test('application review uses current evidence schema and explicit local actions', async () => {
  const app = await readFile(new URL('../src/careeros/static/app.js', import.meta.url), 'utf8');
  const html = await readFile(new URL('../src/careeros/static/index.html', import.meta.url), 'utf8');
  assert.ok(app.includes('Download package'));
  assert.ok(app.includes('Approve for local download'));
  assert.ok(app.includes('Reject and revise locally'));
  assert.ok(app.includes('I confirm this is accurate'));
  assert.ok(app.includes('reviewed_draft'));
  assert.ok(app.includes('hold_reason'));
  assert.ok(!app.includes('resume_alignment'));
  assert.ok(html.indexOf('id="application-review"') < html.indexOf('id="outreach-screen"'));
});

function makeElement(tag = "div", className = "", textContent = "") {
  return {
    tag, className, textContent, children: [], handlers: {}, dataset: {}, value: "", hidden: false,
    append(...children) { this.children.push(...children); },
    prepend(...children) { this.children.unshift(...children); },
    replaceChildren(...children) { this.children = [...children]; },
    setAttribute() {},
    addEventListener(name, handler) { this.handlers[name] = handler; },
    focus() {},
  };
}

function descendants(root) {
  return [root, ...root.children.flatMap(descendants)];
}

async function applicationReviewHarness(api, extra = {}, includeReview = false) {
  const app = await readFile(new URL("../src/careeros/static/app.js", import.meta.url), "utf8");
  const pollStart = app.indexOf("async function pollApplication(");
  const renderStart = app.indexOf("function renderApplicationReview(");
  const portfolioStart = app.indexOf('$("#portfolio-brief").addEventListener', renderStart);
  const pollAndLoadSource = app.slice(pollStart, renderStart);
  const reviewSource = includeReview ? app.slice(renderStart, portfolioStart) : "";
  const rendered = [];
  const notifications = [];
  const panel = makeElement("section");
  const calls = [];
  const context = {
    state: { applicationPollId: 0 },
    document: { body: { dataset: { station: "applications" } }, createElement: tag => makeElement(tag) },
    window: extra.window || { setTimeout: callback => new Promise(resolve => { if (callback) callback(); resolve(); }) },
    $: selector => selector === "#application-review" ? panel : null,
    element: (tag, className = "", text = "") => makeElement(tag, className, text),
    formatStatus: value => value,
    api: async url => { calls.push({url}); return api(url); },
    notify: message => notifications.push(message),
    go() {},
    renderApplicationReview: application => rendered.push(application.id),
    renderApplications() {},
    loadOfficeApplications: async () => {},
    refreshOverview() {},
    saveApplicationDraft: async () => {},
    askCloud: async () => false,
    fetch: async url => { calls.push({url, fetch: true}); return {ok: true, blob: async () => new Blob()}; },
    URL: { createObjectURL: () => "blob:test", revokeObjectURL() {} },
    setTimeout: () => 0,
    ...extra,
  };
  vm.createContext(context);
  vm.runInContext(`${pollAndLoadSource}\n${reviewSource}\nglobalThis.__functions = {pollApplication, loadApplication, renderApplicationReview};`, context);
  return {context, panel, rendered, notifications, calls};
}

const applicationRecord = (id, status, updated_at = "v1") => ({
  id, status, updated_at, job_title: `Job ${id}`, clearance_stale: false, manager_cycle: 1,
  manager_task_status: status === "manager_review" ? "running" : "completed",
  draft: {resume_text: "Original resume", cover_letter: "Original letter", answers: {}, claims: []},
  hiring_reviews: [], snapshot: {evidence: {}},
});

test("selecting a cleared application invalidates an older pending review poll", async () => {
  let resolveA;
  let markAStarted;
  const aStarted = new Promise(resolve => { markAStarted = resolve; });
  const harness = await applicationReviewHarness(url => {
    if (url === "/api/applications") return [];
    const id = decodeURIComponent(url.match(/applications\/([^/]+)/)[1]);
    if (id === "A") {
      markAStarted();
      return new Promise(resolve => { resolveA = resolve; });
    }
    return applicationRecord(id, "needs_review");
  });

  const pollA = harness.context.pollApplication("A");
  await aStarted;
  await harness.context.loadApplication("B");
  resolveA(applicationRecord("A", "needs_review"));
  await pollA;

  assert.deepEqual(harness.rendered, ["B"], "the older poll must not replace the selected application");
});

test("out-of-order application detail GETs only render the latest selection", async () => {
  const pending = new Map();
  const harness = await applicationReviewHarness(url => new Promise(resolve => {
    const id = decodeURIComponent(url.match(/applications\/([^/]+)/)[1]);
    pending.set(id, resolve);
  }));

  const loadA = harness.context.loadApplication("A");
  await new Promise(resolve => setImmediate(resolve));
  const loadB = harness.context.loadApplication("B");
  await new Promise(resolve => setImmediate(resolve));
  pending.get("B")(applicationRecord("B", "needs_review"));
  await loadB;
  pending.get("A")(applicationRecord("A", "needs_review"));
  await loadA;

  assert.deepEqual(harness.rendered, ["B"], "a late response for the previous selection must be ignored");
});

for (const [label, status, actionText] of [
  ["approval", "needs_review", "Approve for local download"],
  ["download", "approved", "Download package"],
]) {
  test(`blocked ${label} retains unsaved application edits`, async () => {
    const record = applicationRecord("A", status);
    const exportCalls = [];
    const harness = await applicationReviewHarness(async url => {
      if (url === "/api/applications/A") return record;
      if (url === "/api/applications") return [record];
      throw new Error(`Unexpected API request: ${url}`);
    }, {fetch: async url => { exportCalls.push(url); return {ok: true, blob: async () => new Blob()}; }}, true);

    harness.context.renderApplicationReview(record);
    const nodes = descendants(harness.panel);
    await nodes.find(node => node.tag === "button" && node.textContent === "Edit").handlers.click();
    const resume = descendants(harness.panel).find(node => node.tag === "textarea" && node.dataset.field === "resume_text");
    resume.value = "My unsaved improvement";
    await descendants(harness.panel).find(node => node.tag === "button" && node.textContent === actionText).handlers.click();

    const retained = descendants(harness.panel).find(node => node.tag === "textarea" && node.dataset.field === "resume_text");
    assert.equal(retained.value, "My unsaved improvement", "a blocked action must not rerender over local text");
    assert.equal(harness.calls.some(call => call.url.endsWith("/approve")), false, "dirty text must not be approved");
    assert.deepEqual(exportCalls, [], "dirty text must not be exported");
    assert.ok(harness.notifications.some(message => message.toLowerCase().includes("save")));
  });
}

test('real persisted application handoffs animate into and out of the Hiring Manager station', async () => {
  const { execFileSync } = await import('node:child_process');
  const { fileURLToPath } = await import('node:url');
  const root = fileURLToPath(new URL('..', import.meta.url));
  const python = process.env.CAREEROS_TEST_PYTHON || `${root}/.venv/bin/python`;
  const events = JSON.parse(execFileSync(python, ['-c', `
import json,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path[:0] = ['src', 'tests']
from careeros.main import create_app
from careeros.config import Settings
from careeros.jobs.verification import VerificationResult
from fastapi.testclient import TestClient
from conftest import FakePlanner, seed_verified_application_job
with tempfile.TemporaryDirectory() as folder:
    app = create_app(Settings(data_dir=Path(folder), worker_enabled=False))
    fake = FakePlanner()
    app.state.gateway.planners['ollama'] = fake
    with TestClient(app) as client:
        resume = client.post('/api/resumes', json={'name':'Base','text':'Built a Python API'}).json()
        job = client.post('/api/jobs/manual', json={'title':'Backend Intern','company':'Acme','url':'https://jobs.example/1'}).json()
        seed_verified_application_job(app, job['id'])
        with app.state.db.connect() as conn:
            row = conn.execute('SELECT * FROM job_verifications WHERE job_id=?',(job['id'],)).fetchone()
        result = VerificationResult(**{key:row[key] for key in ('status','reason','final_url','checked_at','text','fingerprint')})
        app.state.application_service.posting_verifier = SimpleNamespace(verify=lambda *args:result)
        application, _ = app.state.application_service.create(job['id'],resume['id'],'ollama')
        app.state.worker.run_once()
        app.state.worker.run_once()
        print(json.dumps(client.get('/api/workspace/handoffs?after_id=0').json()['events']))
`], { cwd: root, encoding: 'utf8' }));
  assert.deepEqual(events.map(event => event.event_type), ['draft-submitted', 'critique-returned']);
  assert.equal(events[0].to_worker, 'hiring-manager-01');
  withAnimationFrames(() => {
    let now = 1000;
    const renderer = new OfficeRenderer(canvasHarness().canvas, {now: () => now});
    const workers = [
      {id: 'application-prep', station_id: 'application-team-01', status: 'needs_review'},
      {id: 'hiring-manager', station_id: 'hiring-manager-01', status: 'needs_review'},
    ];
    renderer.update({workers});
    const prep = renderer.actors.get('application-prep');
    const manager = renderer.actors.get('hiring-manager');
    const homes = [prep,manager].map(actor => ({col: actor.col,row:actor.row}));
    renderer.draw(1500);
    assert.deepEqual([prep,manager].map(actor => ({col: actor.col,row:actor.row})), homes, 'no event means no character movement');
    const cursor = new HandoffCursor(renderer);
    cursor.initialize({handoff_cursor: 0});
    cursor.receive({events, latest_id: events.at(-1).id});
    assert.equal(renderer.handoffs.length, 2);
    now = 1450;
    renderer.draw(now);
    const meeting = [prep,manager].map(actor => ({col: actor.col,row:actor.row}));
    assert.notDeepEqual(meeting[0], homes[0], 'the sender approaches after a saved event');
    assert.notDeepEqual(meeting[1], homes[1], 'the manager approaches after a saved event');
    assert.equal(prep.facing, 'right');
    assert.equal(manager.facing, 'left');
    renderer.update({workers});
    cursor.receive({events, latest_id: events.at(-1).id});
    renderer.playHandoffs(events);
    assert.deepEqual([prep,manager].map(actor => ({col:actor.col,row:actor.row})), meeting, 'snapshot refresh must preserve the interaction');
    assert.equal(renderer.handoffs.length, 2, 'same saved IDs cannot restart or duplicate interaction');
    const token = renderer.activeHandoffTokens(now)[0];
    assert.ok(token.col > homes[0].col && token.col < homes[1].col, 'the item is exchanged where the characters meet');
    now = 2400;
    renderer.draw(now);
    assert.deepEqual([prep,manager].map(actor => ({col:actor.col,row:actor.row})), homes, 'both workers return to their ordinary positions');
    now = 3450;
    renderer.draw(now);
    assert.notDeepEqual([prep,manager].map(actor => ({col:actor.col,row:actor.row})), homes, 'the persisted critique return triggers its own interaction');
    now = 5001;
    renderer.draw(now);
    assert.deepEqual([prep,manager].map(actor => ({col:actor.col,row:actor.row})), homes);
    assert.deepEqual(renderer.activeHandoffTokens(now), []);
    renderer.destroy();
  });
});
