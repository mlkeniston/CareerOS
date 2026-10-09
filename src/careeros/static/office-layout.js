export const LOGICAL_SIZE = Object.freeze({ width: 600, height: 338 });

export const PALETTE = Object.freeze({
  space: "#070713",
  nebula: "#5539a6",
  frame: "#7654ff",
  steel: "#18162d",
  wall: "#443b70",
  floor: "#11142b",
  grid: "#252448",
  light: "#ededff",
  muted: "#a6a6ca",
  cyan: "#43edff",
  green: "#c3ff63",
  amber: "#ffc95e",
  purple: "#b879ff",
  coral: "#ff55b5",
  red: "#ff5c86",
});

export const ROOMS = Object.freeze([
  { id: "jobs", label: "JOB HUNTERS", x: 16, y: 22, width: 170, height: 116, color: "cyan", station: "jobs" },
  { id: "resume", label: "RESUME TEAM", x: 215, y: 22, width: 170, height: 116, color: "green", station: "resume" },
  { id: "outreach", label: "LINKEDIN OUTREACH", x: 414, y: 22, width: 170, height: 116, color: "coral", station: "outreach" },
  { id: "applications", label: "APPLICATION TEAM", x: 16, y: 194, width: 260, height: 122, color: "amber", station: "applications" },
  { id: "portfolio", label: "ENGINEERING TEAM", x: 324, y: 194, width: 260, height: 122, color: "purple", station: "portfolio" },
  { id: "dispatch", label: "DISPATCH", x: 276, y: 142, width: 48, height: 50, color: "coral", station: "settings" },
]);

export const CORRIDORS = Object.freeze([
  { x: 16, y: 138, width: 568, height: 56 },
  { x: 276, y: 116, width: 48, height: 78 },
]);

export const STATIONS = Object.freeze([
  { id: "jobs", room: "jobs", label: "FEED SCAN", x: 24, y: 73, width: 44, height: 31 },
  { id: "jobs", room: "jobs", label: "ROLE MATCH", x: 71, y: 73, width: 44, height: 31 },
  { id: "jobs", room: "jobs", label: "SOURCE BAY", x: 118, y: 73, width: 44, height: 31 },
  { id: "resume", room: "resume", label: "SKILL MAP", x: 223, y: 73, width: 44, height: 31 },
  { id: "resume", room: "resume", label: "ROLE FIT", x: 270, y: 73, width: 44, height: 31 },
  { id: "resume", room: "resume", label: "STORY DESK", x: 317, y: 73, width: 44, height: 31 },
  { id: "outreach", room: "outreach", label: "ROLE FIT", x: 422, y: 73, width: 44, height: 31 },
  { id: "outreach", room: "outreach", label: "MESSAGE", x: 478, y: 73, width: 44, height: 31 },
  { id: "outreach", room: "outreach", label: "REVIEW", x: 534, y: 73, width: 44, height: 31 },
  { id: "applications", room: "applications", label: "DRAFT BAY", x: 29, y: 238, width: 60, height: 31 },
  { id: "applications", room: "applications", label: "REVIEW DESK", x: 106, y: 238, width: 60, height: 31 },
  { id: "applications", room: "applications", label: "PACKET QA", x: 183, y: 238, width: 60, height: 31 },
  { id: "portfolio", room: "portfolio", label: "BUILD LAB", x: 337, y: 238, width: 60, height: 31 },
  { id: "portfolio", room: "portfolio", label: "TEST BENCH", x: 414, y: 238, width: 60, height: 31 },
  { id: "portfolio", room: "portfolio", label: "STAGING", x: 491, y: 238, width: 60, height: 31 },
  { id: "settings", room: "dispatch", label: "ROUTER", x: 280, y: 152, width: 40, height: 28 },
]);

export const WORKER_APPEARANCE = Object.freeze({
  "job-hunter": { color: "cyan", stationId: "job-hunters-01", wait: { x: 42, y: 126 }, sprite: ["..HHH..", ".HHHHH.", ".HSSSH.", "..SSS..", ".TTTTT.", ".TCTTT.", "..PPP..", ".P...P."] },
  "resume-analyst": { color: "green", stationId: "resume-team-01", wait: { x: 240, y: 126 }, sprite: ["..HHH..", ".HHHHH.", ".HSSSH.", "..SSS..", ".TTTTT.", ".TGTTT.", "..PPP..", ".P...P."] },
  "application-prep": { color: "amber", stationId: "application-team-01", wait: { x: 42, y: 304 }, sprite: ["..HHH..", ".HHHHH.", ".HSSSH.", "..SSS..", ".TTTTT.", ".TATTT.", "..PPP..", ".P...P."] },
  "portfolio-engineer": { color: "purple", stationId: "engineering-team-01", wait: { x: 360, y: 304 }, sprite: ["..HHH..", ".HHHHH.", ".HSSSH.", "..SSS..", ".TTTTT.", ".TPTTT.", "..PPP..", ".P...P."] },
  "linkedin-outreach": { color: "coral", stationId: "outreach-team-01", wait: { x: 450, y: 126 }, sprite: ["..HHH..", ".HHHHH.", ".HSSSH.", "..SSS..", ".TTTTT.", ".TRTTT.", "..PPP..", ".P...P."] },
  director: { color: "coral", stationId: "dispatch-01", wait: { x: 300, y: 187 }, sprite: ["..HHH..", ".HHHHH.", ".HSSSH.", "..SSS..", ".TTTTT.", ".TRTTT.", "..PPP..", ".P...P."] },
});

export const SPRITE_COLORS = Object.freeze({
  H: "#282144",
  S: "#f0bc91",
  T: "#3d3872",
  C: "#43edff",
  G: "#c3ff63",
  A: "#ffc95e",
  P: "#b879ff",
  R: "#ff55b5",
  ".": null,
});

export const WORKER_STATIONS = Object.freeze({
  "job-hunters-01": { x: 93, y: 96 },
  "resume-team-01": { x: 292, y: 96 },
  "application-team-01": { x: 136, y: 260 },
  "engineering-team-01": { x: 444, y: 260 },
  "outreach-team-01": { x: 500, y: 96 },
  "dispatch-01": { x: 300, y: 166 },
});
