export const LOGICAL_SIZE = Object.freeze({ width: 600, height: 338 });

export const ISO_VIEW = Object.freeze({
  columns: 18,
  rows: 10,
  tileWidth: 34,
  tileHeight: 17,
  originX: 232,
  originY: 77,
  wallHeight: 18,
  edgeDepth: 10,
});

export function projectIso(col, row) {
  return {
    x: ISO_VIEW.originX + (col - row) * ISO_VIEW.tileWidth / 2,
    y: ISO_VIEW.originY + (col + row) * ISO_VIEW.tileHeight / 2,
  };
}

export function createIsoProjector(rotationDegrees = 0) {
  const radians = (rotationDegrees * Math.PI) / 180;
  const cosine = Math.cos(radians);
  const sine = Math.sin(radians);
  const centerCol = (ISO_VIEW.columns - 1) / 2;
  const centerRow = (ISO_VIEW.rows - 1) / 2;
  const raw = (col, row) => {
    const dx = col - centerCol;
    const dy = row - centerRow;
    const rotatedCol = dx * cosine - dy * sine;
    const rotatedRow = dx * sine + dy * cosine;
    return {
      x: (rotatedCol - rotatedRow) * ISO_VIEW.tileWidth / 2,
      y: (rotatedCol + rotatedRow) * ISO_VIEW.tileHeight / 2,
    };
  };
  const corners = [
    raw(-0.5, -0.5),
    raw(ISO_VIEW.columns - 0.5, -0.5),
    raw(ISO_VIEW.columns - 0.5, ISO_VIEW.rows - 0.5),
    raw(-0.5, ISO_VIEW.rows - 0.5),
  ];
  const minX = Math.min(...corners.map(point => point.x));
  const maxX = Math.max(...corners.map(point => point.x));
  const minY = Math.min(...corners.map(point => point.y));
  const maxY = Math.max(...corners.map(point => point.y));
  const scale = Math.min(
    (LOGICAL_SIZE.width - 42) / (maxX - minX),
    (LOGICAL_SIZE.height - 48) / (maxY - minY + ISO_VIEW.wallHeight + ISO_VIEW.edgeDepth),
  );
  const originX = LOGICAL_SIZE.width / 2 - ((minX + maxX) / 2) * scale;
  const originY = LOGICAL_SIZE.height / 2 - ((minY + maxY) / 2) * scale
    + ((ISO_VIEW.wallHeight - ISO_VIEW.edgeDepth) / 2) * scale;
  const project = (col, row) => {
    const point = raw(col, row);
    return { x: originX + point.x * scale, y: originY + point.y * scale };
  };
  project.scale = scale;
  project.rotation = ((rotationDegrees % 360) + 360) % 360;
  return project;
}

export const PALETTE = Object.freeze({
  space: "#0b0e0d",
  frame: "#7958d8",
  steel: "#29302c",
  wall: "#5b5a4b",
  floor: "#41443a",
  grid: "#555548",
  light: "#e8dfc6",
  muted: "#a99d7d",
  olive: "#72785a",
  rust: "#a5583b",
  cyan: "#43edff",
  green: "#c3ff63",
  amber: "#ffc95e",
  purple: "#b879ff",
  coral: "#ff55b5",
  red: "#ff5c86",
});

export const ROOMS = Object.freeze([
  { id: "jobs", label: "JOB HUNTERS", grid: { col: 0, row: 0, columns: 6, rows: 4 }, color: "cyan", floor: "#4a4a3e", wall: "#65604e" },
  { id: "resume", label: "RESUME TEAM", grid: { col: 6, row: 0, columns: 6, rows: 4 }, color: "green", floor: "#44483d", wall: "#5b614f" },
  { id: "outreach", label: "OUTREACH", grid: { col: 12, row: 0, columns: 6, rows: 4 }, color: "coral", floor: "#4a453c", wall: "#685348" },
  { id: "applications", label: "APPLICATIONS", grid: { col: 0, row: 6, columns: 9, rows: 4 }, color: "amber", floor: "#4b463c", wall: "#655744" },
  { id: "portfolio", label: "ENGINEERING", grid: { col: 9, row: 6, columns: 9, rows: 4 }, color: "purple", floor: "#414741", wall: "#586057" },
  { id: "dispatch", label: "DISPATCH", grid: { col: 7, row: 4, columns: 4, rows: 2 }, color: "coral", floor: "#51463d", wall: "#73503f" },
]);

const roomAtCell = new Map();
for (const room of ROOMS) {
  const { col, row, columns, rows } = room.grid;
  for (let gridRow = row; gridRow < row + rows; gridRow += 1) {
    for (let gridCol = col; gridCol < col + columns; gridCol += 1) {
      roomAtCell.set(`${gridCol},${gridRow}`, room);
    }
  }
}

const floorCells = [];
for (let row = 0; row < ISO_VIEW.rows; row += 1) {
  for (let col = 0; col < ISO_VIEW.columns; col += 1) {
    const room = roomAtCell.get(`${col},${row}`);
    if (room) {
      floorCells.push({ col, row, zoneId: room.id, material: room.floor, wall: room.wall });
    } else if (row === 4 || row === 5) {
      floorCells.push({ col, row, zoneId: "corridor", material: "#353931", wall: "#4c4e43" });
    }
  }
}
export const FLOOR_CELLS = Object.freeze(floorCells);

function cellKey(cell) {
  return `${cell.col},${cell.row}`;
}

function edgeKey(first, second) {
  return [cellKey(first), cellKey(second)].sort().join("|");
}

const doorwayPairs = [
  [{ col: 2, row: 3 }, { col: 2, row: 4 }],
  [{ col: 8, row: 3 }, { col: 8, row: 4 }],
  [{ col: 14, row: 3 }, { col: 14, row: 4 }],
  [{ col: 4, row: 5 }, { col: 4, row: 6 }],
  [{ col: 13, row: 5 }, { col: 13, row: 6 }],
  [{ col: 8, row: 5 }, { col: 8, row: 6 }],
  [{ col: 6, row: 4 }, { col: 7, row: 4 }],
  [{ col: 10, row: 4 }, { col: 11, row: 4 }],
  [{ col: 6, row: 5 }, { col: 7, row: 5 }],
  [{ col: 10, row: 5 }, { col: 11, row: 5 }],
];
export const DOORWAY_EDGES = new Set(doorwayPairs.map(([first, second]) => edgeKey(first, second)));
export const DOORWAYS = Object.freeze(doorwayPairs.map(([first, second]) => {
  if (first.col !== second.col) {
    const col = (first.col + second.col) / 2;
    const row = (first.row + second.row) / 2;
    return { start: { col, row: row - 0.5 }, end: { col, row: row + 0.5 } };
  }
  const col = (first.col + second.col) / 2;
  const row = (first.row + second.row) / 2;
  return { start: { col: col - 0.5, row }, end: { col: col + 0.5, row } };
}));

function station(room, col, row, label, workerStationId = null, workerCell = null, kind = "terminal") {
  const position = projectIso(col, row);
  return {
    id: room,
    room,
    selectionId: room === "dispatch" ? "settings" : room,
    label,
    kind,
    cell: { col, row },
    position,
    bounds: { left: position.x - 13, top: position.y - 15, width: 26, height: 26 },
    workerStationId,
    workerCell,
  };
}

export const STATIONS = Object.freeze([
  station("jobs", 1, 1, "FEED SCAN", null, null, "scanner"),
  station("jobs", 3, 1, "ROLE MATCH", "job-hunters-01", { col: 3, row: 2 }, "terminal"),
  station("jobs", 5, 1, "SOURCE BAY", null, null, "terminal"),
  station("resume", 7, 1, "SKILL MAP", null, null, "files"),
  station("resume", 9, 1, "ROLE FIT", "resume-team-01", { col: 9, row: 2 }, "terminal"),
  station("resume", 11, 1, "STORY DESK", null, null, "files"),
  station("outreach", 13, 1, "ROLE FIT", null, null, "terminal"),
  station("outreach", 15, 1, "MESSAGE", "outreach-team-01", { col: 15, row: 2 }, "radio"),
  station("outreach", 17, 1, "REVIEW", null, null, "terminal"),
  station("applications", 1, 7, "DRAFT BAY", null, null, "files"),
  station("applications", 4, 7, "REVIEW DESK", "application-team-01", { col: 4, row: 8 }, "files"),
  station("applications", 7, 7, "PACKET QA", null, null, "terminal"),
  station("portfolio", 10, 7, "BUILD LAB", null, null, "workbench"),
  station("portfolio", 13, 7, "TEST BENCH", "engineering-team-01", { col: 13, row: 8 }, "workbench"),
  station("portfolio", 16, 7, "STAGING", null, null, "workbench"),
  station("dispatch", 8, 4, "QUEUE ROUTER", "dispatch-01", { col: 8, row: 5 }, "console"),
]);

export function findStationAt(x, y, project = projectIso) {
  return [...STATIONS].reverse().find(item => {
    const position = project(item.cell.col, item.cell.row);
    const radius = 13 * (project.scale || 1);
    return x >= position.x - radius && x <= position.x + radius
      && y >= position.y - 15 * (project.scale || 1) && y <= position.y + 11 * (project.scale || 1);
  }) || null;
}

export const WORKER_STATIONS = Object.freeze(Object.fromEntries(
  STATIONS.filter(item => item.workerStationId).map(item => [
    item.workerStationId,
    projectIso(item.workerCell.col, item.workerCell.row),
  ]),
));

const BODY_SPRITE = Object.freeze([
  "...HHHHH...",
  "..HHHHHHH..",
  ".HHHHHHHHH.",
  ".HSSSSSSSH.",
  ".HSESSSESH.",
  "..SSSSSSS..",
  "...SSSSS...",
  "...CCCCC...",
  "..JJJJJJJ..",
  ".JTTAAATTJ.",
  ".JJTTTTTJJ.",
  "..JTTTTTJ..",
  "...JBBJ....",
  "...PPPP....",
  "..PP...PP..",
  ".PP.....PP.",
  ".KK.....KK.",
  "KK.......KK",
]);

function addFinePixels(sprite) {
  return Object.freeze(sprite.flatMap((row, rowIndex) => [0, 1].map(yPart => (
    [...row].flatMap((symbol, columnIndex) => [0, 1].map(xPart => {
      if (symbol === ".") return ".";
      if (symbol === "T" && yPart === 0 && xPart === 1 && (rowIndex + columnIndex) % 3 === 0) return "t";
      if (symbol === "J" && yPart === 1 && xPart === 0 && columnIndex % 3 === 0) return "j";
      if (symbol === "S" && yPart === 0 && xPart === 1 && columnIndex % 2 === 0) return "s";
      if (symbol === "H" && yPart === 0 && xPart === 1 && (rowIndex + columnIndex) % 4 === 0) return "h";
      if (symbol === "C" && yPart === 1 && xPart === 1 && columnIndex % 3 === 0) return "c";
      if (symbol === "A" && yPart === 0 && xPart === 1 && (rowIndex + columnIndex) % 2 === 0) return "a";
      if (symbol === "t" && yPart === 1 && xPart === 1) return "u";
      if (symbol === "j" && yPart === 0 && xPart === 1 && columnIndex % 2 === 0) return "v";
      if (symbol === "s" && yPart === 1 && xPart === 0) return "w";
      return symbol;
    })).join("")
  ))));
}
const DETAILED_BODY_SPRITE = addFinePixels(addFinePixels(BODY_SPRITE));

function workerAppearance(color, stationId, waitCell, gear) {
  const wait = projectIso(waitCell.col, waitCell.row);
  return { color, stationId, wait: { x: wait.x, y: wait.y + 2 }, waitCell, gear, sprite: DETAILED_BODY_SPRITE };
}

export const WORKER_APPEARANCE = Object.freeze({
  "job-hunter": workerAppearance("cyan", "job-hunters-01", { col: 0, row: 5 }, "visor"),
  "resume-analyst": workerAppearance("green", "resume-team-01", { col: 3, row: 5 }, "glasses"),
  "application-prep": workerAppearance("amber", "application-team-01", { col: 6, row: 5 }, "clipboard"),
  "portfolio-engineer": workerAppearance("purple", "engineering-team-01", { col: 15, row: 5 }, "goggles"),
  "linkedin-outreach": workerAppearance("coral", "outreach-team-01", { col: 12, row: 5 }, "headset"),
  director: workerAppearance("coral", "dispatch-01", { col: 9, row: 5 }, "cap"),
});

export const SPRITE_COLORS = Object.freeze({
  H: "#43392e",
  S: "#d5a17d",
  E: "#2b2923",
  C: "#778676",
  J: "#626b53",
  T: "#77795d",
  A: "#ffffff",
  B: "#534333",
  P: "#414846",
  K: "#272a27",
  t: "#929274",
  j: "#4d5947",
  s: "#e3b18b",
  h: "#625140",
  c: "#90a08e",
  a: "#ffffff",
  u: "#b0ac87",
  v: "#414b3c",
  w: "#f2c29e",
  ".": null,
});

export const PROPS = Object.freeze([
  { kind: "locker", col: 0, row: 1 },
  { kind: "crate", col: 5, row: 0 },
  { kind: "lamp", col: 0, row: 3 },
  { kind: "filecabinet", col: 6, row: 0 },
  { kind: "shelf", col: 11, row: 3 },
  { kind: "antenna", col: 12, row: 0 },
  { kind: "crate", col: 17, row: 3 },
  { kind: "radio", col: 12, row: 3 },
  { kind: "filebox", col: 0, row: 9 },
  { kind: "lamp", col: 8, row: 9 },
  { kind: "toolbox", col: 9, row: 9 },
  { kind: "cactus", col: 17, row: 9 },
]);
