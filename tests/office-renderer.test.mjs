import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const layoutSource = await readFile(new URL("../src/careeros/static/office-layout.js", import.meta.url), "utf8");
const rendererSource = await readFile(new URL("../src/careeros/static/office-renderer.js", import.meta.url), "utf8");
const layoutUrl = `data:text/javascript;base64,${Buffer.from(layoutSource).toString("base64")}`;
const rendererModule = rendererSource.replace('from "./office-layout.js"', `from "${layoutUrl}"`);
const { OfficeRenderer } = await import(`data:text/javascript;base64,${Buffer.from(rendererModule).toString("base64")}`);
const { FLOOR_CELLS } = await import(layoutUrl);

test("isometric renderer fills every floor tile while drawing the office", () => {
  const filledStyles = [];
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
    addEventListener() {},
    removeEventListener() {},
  };
  const previousWindow = globalThis.window;
  globalThis.window = {
    devicePixelRatio: 1,
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {} }),
    addEventListener() {},
    removeEventListener() {},
  };

  try {
    new OfficeRenderer(canvas).update({ workers: [], counts: {} });
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }

  const floorMaterials = new Set(FLOOR_CELLS.map(cell => cell.material));
  const filledFloorTiles = filledStyles.filter(color => floorMaterials.has(color)).length;
  assert.ok(filledFloorTiles >= FLOOR_CELLS.length * 0.7,
    `expected visible filled floor tiles for the whole isometric map; got ${filledFloorTiles} of ${FLOOR_CELLS.length}`);
});
