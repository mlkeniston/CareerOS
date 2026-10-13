import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/careeros/static/office-layout.js", import.meta.url), "utf8");
const {
  FLOOR_CELLS,
  ISO_VIEW,
  DOORWAYS,
  ROOMS,
  STATIONS,
  CONVEYOR_NETWORK,
  WORKER_APPEARANCE,
  WORKER_STATIONS,
  SPRITE_COLORS,
  PALETTE,
  createIsoProjector,
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

test("the office camera can orbit while keeping the whole map in view", () => {
  const front = createIsoProjector(0);
  const side = createIsoProjector(90);
  const fullTurn = createIsoProjector(360);
  const origin = front(0, 0);
  const turned = side(0, 0);
  const reset = fullTurn(0, 0);

  assert.ok(Math.hypot(origin.x - turned.x, origin.y - turned.y) > 8);
  assert.ok(Math.abs(origin.x - reset.x) < 0.01);
  assert.ok(Math.abs(origin.y - reset.y) < 0.01);
  assert.ok(Number.isFinite(front.scale) && front.scale > 0);
  for (const project of [front, side, createIsoProjector(35), createIsoProjector(180), createIsoProjector(270)]) {
    const corners = [
      project(-0.5, -0.5),
      project(ISO_VIEW.columns - 0.5, -0.5),
      project(ISO_VIEW.columns - 0.5, ISO_VIEW.rows - 0.5),
      project(-0.5, ISO_VIEW.rows - 0.5),
    ];
    assert.ok(Math.min(...corners.map(point => point.x)) > 8);
    assert.ok(Math.max(...corners.map(point => point.x)) < 592);
    assert.ok(Math.min(...corners.map(point => point.y)) > 12);
    assert.ok(Math.max(...corners.map(point => point.y)) < 326);
  }
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

test("hazard bands have grid-edge endpoints that follow each camera angle", () => {
  assert.ok(DOORWAYS.length > 0);
  const first = DOORWAYS[0];
  const front = createIsoProjector(0);
  const orbit = createIsoProjector(61);
  const frontStart = front(first.start.col, first.start.row);
  const frontEnd = front(first.end.col, first.end.row);
  const orbitStart = orbit(first.start.col, first.start.row);
  const orbitEnd = orbit(first.end.col, first.end.row);
  assert.ok(Math.hypot(frontStart.x - frontEnd.x, frontStart.y - frontEnd.y) > 4);
  assert.ok(Math.abs(orbitStart.x - orbitEnd.x) > 1 || Math.abs(orbitStart.y - orbitEnd.y) > 1);
  assert.notDeepEqual(orbitStart, frontStart);
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
  assert.equal(STATIONS.find(item => item.room === "dispatch").selectionId, "settings");
});

test('Project QA has a distinct male sprite at its own test bench', () => {
  const qa = WORKER_APPEARANCE['project-qa'];
  assert.equal(qa.gender, 'male');
  assert.equal(qa.stationId, 'project-qa-01');
  assert.ok(qa.sprite.some(row => row.includes('M')));
  assert.notDeepEqual(qa.sprite, WORKER_APPEARANCE['portfolio-engineer'].sprite);
  assert.ok(STATIONS.some(station => station.workerStationId === qa.stationId && station.label === 'PROJECT QA'));
});

test("the connected conveyor network reaches every station and joins through Dispatch", () => {
  const stationIds = CONVEYOR_NETWORK.flatMap(lane => lane.stationIds);
  assert.equal(new Set(stationIds).size, stationIds.length, "each station should appear once in the network");
  assert.deepEqual(new Set(stationIds), new Set(STATIONS.map(item => item.trackId)));
  const liesOnSegment = (point, start, end) => {
    const epsilon = 1e-8;
    const between = (value, a, b) => value >= Math.min(a, b) - epsilon && value <= Math.max(a, b) + epsilon;
    const horizontal = Math.abs(start.row - end.row) < epsilon
      && Math.abs(point.row - start.row) < epsilon && between(point.col, start.col, end.col);
    const vertical = Math.abs(start.col - end.col) < epsilon
      && Math.abs(point.col - start.col) < epsilon && between(point.row, start.row, end.row);
    return horizontal || vertical;
  };
  for (const station of STATIONS) {
    const center = { col: station.cell.col, row: station.cell.row + 0.78 };
    const connected = CONVEYOR_NETWORK.some(lane => lane.waypoints.slice(1).some((end, index) => (
      liesOnSegment(center, lane.waypoints[index], end)
    )));
    assert.ok(connected, `${station.label} should sit directly on a conveyor route`);
  }

  const upper = CONVEYOR_NETWORK.find(lane => lane.id === "upper-run");
  const lower = CONVEYOR_NETWORK.find(lane => lane.id === "lower-run");
  const spine = CONVEYOR_NETWORK.find(lane => lane.id === "dispatch-spine");
  const samePoint = (a, b) => a.col === b.col && a.row === b.row;
  assert.ok(upper.waypoints.some(point => samePoint(point, spine.waypoints[0])));
  assert.ok(lower.waypoints.some(point => samePoint(point, spine.waypoints.at(-1))));
  assert.ok(spine.stationIds.some(id => STATIONS.find(item => item.trackId === id)?.room === "dispatch"));
});

test("worker sprites use a dense pixel grid with extra shade and highlight colors", () => {
  for (const appearance of Object.values(WORKER_APPEARANCE)) {
    assert.ok(appearance.sprite.length >= 70);
    assert.ok(appearance.sprite.every(row => row.length >= 40));
    const pixels = new Set(appearance.sprite.join(""));
    assert.ok(pixels.has("u") && pixels.has("v") && pixels.has("w"));
    assert.ok(appearance.outline.length > 0, "each worker needs an exposed-pixel outline for floor contrast");
  }
  assert.ok(SPRITE_COLORS.u && SPRITE_COLORS.v && SPRITE_COLORS.w);
  assert.ok(PALETTE.conveyor, "the office needs a dedicated belt surface color");
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
