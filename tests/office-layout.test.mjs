import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/careeros/static/office-layout.js", import.meta.url), "utf8");
const {
  FLOOR_CELLS,
  ISO_VIEW,
  ROOMS,
  STATIONS,
  WORKER_APPEARANCE,
  WORKER_STATIONS,
  findStationAt,
  projectIso,
} = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

test("LinkedIn outreach has a rendered pixel worker at its own office station", () => {
  const worker = WORKER_APPEARANCE["linkedin-outreach"];
  assert.ok(worker, "the backend worker must have pixel art");
  const room = ROOMS.find(item => item.id === "outreach");
  const desk = STATIONS.find(item => item.workerStationId === "outreach-team-01");
  assert.ok(room, "the office needs an outreach room");
  assert.ok(desk, "the outreach room needs the outreach worker desk");
  assert.equal(worker.stationId, "outreach-team-01");
  assert.deepEqual(room.grid, { col: 12, row: 0, columns: 6, rows: 4 });
  assert.deepEqual(WORKER_STATIONS[worker.stationId], projectIso(desk.workerCell.col, desk.workerCell.row));
  assert.equal(
    FLOOR_CELLS.find(cell => cell.col === worker.waitCell.col && cell.row === worker.waitCell.row)?.zoneId,
    "corridor",
  );
});

test("floor coordinates project along two axes into an isometric diamond grid", () => {
  const origin = projectIso(0, 0);
  const east = projectIso(1, 0);
  const west = projectIso(0, 1);

  assert.ok(east.x > origin.x && east.y > origin.y);
  assert.ok(west.x < origin.x && west.y > origin.y);
  assert.equal(east.x - origin.x, origin.x - west.x);
  assert.equal(east.y - origin.y, west.y - origin.y);
  assert.equal(ISO_VIEW.tileWidth, 2 * (east.x - origin.x));
  assert.equal(ISO_VIEW.tileHeight, 2 * (east.y - origin.y));
});

test("each office department owns a non-overlapping floor footprint", () => {
  const cells = new Set();
  for (const cell of FLOOR_CELLS) {
    const key = `${cell.col},${cell.row}`;
    assert.ok(!cells.has(key), `floor cell ${key} must only belong to one room`);
    cells.add(key);
  }

  for (const room of ROOMS) {
    const roomCells = FLOOR_CELLS.filter(cell => cell.zoneId === room.id);
    assert.equal(roomCells.length, room.grid.columns * room.grid.rows, `${room.id} floor area`);
  }
});

test("worker destinations and clickable desk centers use the isometric map", () => {
  for (const appearance of Object.values(WORKER_APPEARANCE)) {
    const station = STATIONS.find(item => item.workerStationId === appearance.stationId);
    assert.ok(station, `desk for ${appearance.stationId}`);
    assert.deepEqual(WORKER_STATIONS[appearance.stationId], projectIso(station.workerCell.col, station.workerCell.row));
    assert.equal(
      FLOOR_CELLS.find(cell => cell.col === station.workerCell.col && cell.row === station.workerCell.row)?.zoneId,
      station.room,
    );
  }

  for (const station of STATIONS) {
    assert.equal(findStationAt(station.position.x, station.position.y), station);
  }
});

test("worker sprites have room for readable face, clothing, and team accents", () => {
  for (const appearance of Object.values(WORKER_APPEARANCE)) {
    assert.ok(appearance.sprite.length >= 14);
    assert.ok(appearance.sprite.every(row => row.length >= 11));
  }
});

test("idle workers have separate floor positions instead of stacking in the corridor", () => {
  const workers = Object.values(WORKER_APPEARANCE);
  for (let first = 0; first < workers.length; first += 1) {
    for (let second = first + 1; second < workers.length; second += 1) {
      const a = workers[first].wait;
      const b = workers[second].wait;
      const overlaps = Math.abs(a.x - b.x) < 22 && Math.abs(a.y - b.y) < 36;
      assert.ok(!overlaps, `idle workers ${first} and ${second} need distinct sprite footprints`);
    }
  }
});
