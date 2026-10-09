export const LOGICAL_SIZE = Object.freeze({ width: 480, height: 270 });

export const PALETTE = Object.freeze({
  space: "#070a12",
  nebula: "#58386f",
  frame: "#b84853",
  steel: "#1a202c",
  wall: "#667181",
  floor: "#111925",
  grid: "#202a37",
  light: "#e5edf4",
  muted: "#8997a8",
  cyan: "#5ad4e5",
  green: "#83d69a",
  amber: "#eab563",
  purple: "#bf9ae8",
  coral: "#ef7476",
  red: "#ed6269",
});

export const ROOMS = Object.freeze([
  { id: "jobs", label: "JOB HUNTERS", x: 16, y: 22, width: 196, height: 100, color: "cyan", station: "jobs" },
  { id: "resume", label: "RESUME TEAM", x: 268, y: 22, width: 196, height: 100, color: "green", station: "resume" },
  { id: "applications", label: "APPLICATION TEAM", x: 16, y: 148, width: 196, height: 100, color: "amber", station: "applications" },
  { id: "portfolio", label: "ENGINEERING TEAM", x: 268, y: 148, width: 196, height: 100, color: "purple", station: "portfolio" },
  { id: "dispatch", label: "DISPATCH", x: 216, y: 102, width: 48, height: 66, color: "coral", station: "settings" },
]);

export const CORRIDORS = Object.freeze([
  { x: 16, y: 122, width: 448, height: 26 },
  { x: 216, y: 94, width: 48, height: 80 },
]);

export const STATIONS = Object.freeze([
  { id: "jobs", room: "jobs", label: "FEED SCAN", x: 30, y: 61, width: 52, height: 31 },
  { id: "jobs", room: "jobs", label: "ROLE MATCH", x: 93, y: 61, width: 52, height: 31 },
  { id: "jobs", room: "jobs", label: "SOURCE BAY", x: 156, y: 61, width: 43, height: 31 },
  { id: "resume", room: "resume", label: "SKILL MAP", x: 282, y: 61, width: 52, height: 31 },
  { id: "resume", room: "resume", label: "ROLE FIT", x: 345, y: 61, width: 52, height: 31 },
  { id: "resume", room: "resume", label: "STORY DESK", x: 408, y: 61, width: 43, height: 31 },
  { id: "applications", room: "applications", label: "DRAFT BAY", x: 30, y: 187, width: 52, height: 31 },
  { id: "applications", room: "applications", label: "REVIEW DESK", x: 93, y: 187, width: 52, height: 31 },
  { id: "applications", room: "applications", label: "PACKET QA", x: 156, y: 187, width: 43, height: 31 },
  { id: "portfolio", room: "portfolio", label: "BUILD LAB", x: 282, y: 187, width: 52, height: 31 },
  { id: "portfolio", room: "portfolio", label: "TEST BENCH", x: 345, y: 187, width: 52, height: 31 },
  { id: "portfolio", room: "portfolio", label: "STAGING", x: 408, y: 187, width: 43, height: 31 },
  { id: "settings", room: "dispatch", label: "ROUTER", x: 220, y: 121, width: 40, height: 28 },
]);

export const WORKER_APPEARANCE = Object.freeze({
  "job-hunter": { color: "cyan", stationId: "job-hunters-01", wait: { x: 42, y: 106 }, sprite: ["..HHH..", ".HHHHH.", ".HSSSH.", "..SSS..", ".TTTTT.", ".TCTTT.", "..PPP..", ".P...P."] },
  "resume-analyst": { color: "green", stationId: "resume-team-01", wait: { x: 290, y: 106 }, sprite: ["..HHH..", ".HHHHH.", ".HSSSH.", "..SSS..", ".TTTTT.", ".TGTTT.", "..PPP..", ".P...P."] },
  "application-prep": { color: "amber", stationId: "application-team-01", wait: { x: 42, y: 232 }, sprite: ["..HHH..", ".HHHHH.", ".HSSSH.", "..SSS..", ".TTTTT.", ".TATTT.", "..PPP..", ".P...P."] },
  "portfolio-engineer": { color: "purple", stationId: "engineering-team-01", wait: { x: 290, y: 232 }, sprite: ["..HHH..", ".HHHHH.", ".HSSSH.", "..SSS..", ".TTTTT.", ".TPTTT.", "..PPP..", ".P...P."] },
  director: { color: "coral", stationId: "dispatch-01", wait: { x: 240, y: 161 }, sprite: ["..HHH..", ".HHHHH.", ".HSSSH.", "..SSS..", ".TTTTT.", ".TRTTT.", "..PPP..", ".P...P."] },
});

export const SPRITE_COLORS = Object.freeze({
  H: "#352d43",
  S: "#f0bc91",
  T: "#347b89",
  C: "#65dfeb",
  G: "#79d895",
  A: "#efb355",
  P: "#b995e0",
  R: "#ee777a",
  ".": null,
});

export const WORKER_STATIONS = Object.freeze({
  "job-hunters-01": { x: 105, y: 73 },
  "resume-team-01": { x: 357, y: 73 },
  "application-team-01": { x: 105, y: 199 },
  "engineering-team-01": { x: 357, y: 199 },
  "dispatch-01": { x: 240, y: 133 },
});
