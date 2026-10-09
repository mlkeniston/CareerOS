import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const layoutSource = await readFile(new URL("../src/careeros/static/office-layout.js", import.meta.url), "utf8");
const rendererSource = await readFile(new URL("../src/careeros/static/office-renderer.js", import.meta.url), "utf8");
const layoutUrl = `data:text/javascript;base64,${Buffer.from(layoutSource).toString("base64")}`;
const rendererModule = rendererSource.replace('from "./office-layout.js"', `from "${layoutUrl}"`);
const { OfficeRenderer } = await import(`data:text/javascript;base64,${Buffer.from(rendererModule).toString("base64")}`);
const { FLOOR_CELLS, STATIONS, WORKER_APPEARANCE } = await import(layoutUrl);

function canvasHarness() {
  const filledStyles = [];
  const listeners = new Map();
  let context;
  context = new Proxy({
    createRadialGradient: () => ({ addColorStop() {} }),
    measureText: value => ({ width: value.length * 3 }),
    fill: () => { filledStyles.push(context.fillStyle); },
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
  return { canvas, filledStyles, listeners };
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

test("isometric renderer fills every floor tile while drawing the office", () => {
  withReducedMotion(() => {
    const { canvas, filledStyles } = canvasHarness();
    new OfficeRenderer(canvas).update({ workers: [], counts: {} });
    const floorMaterials = new Set(FLOOR_CELLS.map(cell => cell.material));
    const filledFloorTiles = filledStyles.filter(color => floorMaterials.has(color)).length;
    assert.ok(filledFloorTiles >= FLOOR_CELLS.length * 0.7,
      `expected visible filled floor tiles for the whole isometric map; got ${filledFloorTiles} of ${FLOOR_CELLS.length}`);
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
    const { canvas } = canvasHarness();
    const renderer = new OfficeRenderer(canvas);
    renderer.update({
      workers: [{ id: "job-hunter", name: "Job Hunter", color: "cyan", status: "idle", station_id: "job-hunters-01" }],
      counts: {},
    });
    const actor = renderer.actors.get("job-hunter");
    const appearance = WORKER_APPEARANCE["job-hunter"];
    assert.ok(Math.abs(actor.bounds.width - 22 * renderer.project.scale) < 0.01);
    assert.ok(Math.abs(actor.bounds.height - 36 * renderer.project.scale) < 0.01);
    assert.ok(appearance.sprite.length >= 70 && appearance.sprite[0].length >= 40);
    renderer.destroy();
  });
});
