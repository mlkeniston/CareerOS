import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/careeros/static/office-layout.js", import.meta.url), "utf8");
const { ROOMS, STATIONS, WORKER_APPEARANCE, WORKER_STATIONS } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

test("LinkedIn outreach has a rendered pixel worker at its own office station", () => {
  const worker = WORKER_APPEARANCE["linkedin-outreach"];
  assert.ok(worker, "the backend worker must have pixel art");
  const room = ROOMS.find(item => item.id === "outreach");
  const desk = STATIONS.find(item => item.id === "outreach" && item.room === "outreach");
  assert.ok(room, "the office needs an outreach room");
  assert.ok(desk, "the outreach room needs a clickable desk");
  assert.equal(worker.stationId, "outreach-team-01");
  assert.equal(room.width, 170);
  assert.equal(room.height, 116);
  assert.deepEqual(WORKER_STATIONS[worker.stationId], { x: 500, y: 96 });
  assert.equal(worker.wait.x, 450);
  assert.ok(worker.wait.y > room.y && worker.wait.y < room.y + room.height);
});
