import {
  DOORWAY_EDGES,
  FLOOR_CELLS,
  ISO_VIEW,
  LOGICAL_SIZE,
  PALETTE,
  PROPS,
  ROOMS,
  SPRITE_COLORS,
  STATIONS,
  WORKER_APPEARANCE,
  WORKER_STATIONS,
  findStationAt,
  projectIso,
} from "./office-layout.js";

export class OfficeRenderer {
  constructor(canvas, { onSelect = () => {}, onHover = () => {} } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: false });
    if (!this.ctx) throw new Error("The office canvas is not available in this browser.");
    this.onSelect = onSelect;
    this.onHover = onHover;
    this.snapshot = null;
    this.actors = new Map();
    this.selection = null;
    this.hoveredWorker = null;
    this.hoverPosition = null;
    this.destroyed = false;
    this.lastFrameAt = 0;
    this.motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
    this.reducedMotion = this.motionPreference.matches;
    this.handleResize = () => this.resize();
    this.handleClick = event => this.selectAt(event);
    this.handlePointerMove = event => this.hoverAt(event);
    this.handlePointerLeave = () => this.clearHover();
    this.handleMotionChange = event => {
      this.reducedMotion = event.matches;
      this.lastFrameAt = 0;
      if (this.reducedMotion) {
        if (this.frameId) window.cancelAnimationFrame(this.frameId);
        this.frameId = undefined;
        this.snapActorsToTargets();
        this.draw(0);
      } else {
        this.startAnimation();
      }
    };
    window.addEventListener("resize", this.handleResize);
    canvas.addEventListener("click", this.handleClick);
    canvas.addEventListener("pointermove", this.handlePointerMove);
    canvas.addEventListener("pointerleave", this.handlePointerLeave);
    if (this.motionPreference.addEventListener) {
      this.motionPreference.addEventListener("change", this.handleMotionChange);
    } else {
      this.motionPreference.addListener(this.handleMotionChange);
    }
    this.resize();
    this.draw(0);
    if (!this.reducedMotion) this.startAnimation();
  }

  update(snapshot) {
    this.snapshot = snapshot || { workers: [], counts: {} };
    const workers = Array.isArray(this.snapshot.workers) ? this.snapshot.workers : [];
    const liveIds = new Set(workers.map(worker => worker.id));
    for (const id of this.actors.keys()) {
      if (!liveIds.has(id)) this.actors.delete(id);
    }
    for (const worker of workers) this.updateActor(worker);
    if (this.hoveredWorker && this.actors.has(this.hoveredWorker)) {
      this.onHover(this.hoveredWorker, this.hoverPosition);
    } else if (this.hoveredWorker) {
      this.clearHover();
    }
    if (this.reducedMotion) this.snapActorsToTargets();
    this.draw(0);
  }

  setSelection(selection) {
    this.selection = selection && ["worker", "station"].includes(selection.type) ? selection : null;
    this.draw(0);
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    if (this.frameId) window.cancelAnimationFrame(this.frameId);
    window.removeEventListener("resize", this.handleResize);
    this.canvas.removeEventListener("click", this.handleClick);
    this.canvas.removeEventListener("pointermove", this.handlePointerMove);
    this.canvas.removeEventListener("pointerleave", this.handlePointerLeave);
    if (this.motionPreference.removeEventListener) {
      this.motionPreference.removeEventListener("change", this.handleMotionChange);
    } else {
      this.motionPreference.removeListener(this.handleMotionChange);
    }
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    const cssScale = rect.width ? rect.width / LOGICAL_SIZE.width : 1;
    const ratio = Math.max(1, Math.round(cssScale * (window.devicePixelRatio || 1)));
    const width = LOGICAL_SIZE.width * ratio;
    const height = LOGICAL_SIZE.height * ratio;
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.ctx.imageSmoothingEnabled = false;
    this.draw(0);
  }

  updateActor(worker) {
    const appearance = WORKER_APPEARANCE[worker.id];
    if (!appearance) return;
    const station = WORKER_STATIONS[worker.station_id] || WORKER_STATIONS[appearance.stationId];
    const isAtStation = ["working", "needs_review", "failed", "interrupted"].includes(worker.status);
    const target = isAtStation ? station : appearance.wait;
    let actor = this.actors.get(worker.id);
    if (!actor) {
      actor = { id: worker.id, x: appearance.wait.x, y: appearance.wait.y };
      this.actors.set(worker.id, actor);
    }
    actor.name = worker.name || worker.id;
    actor.color = PALETTE[worker.color] || PALETTE[appearance.color];
    actor.status = worker.status;
    actor.taskId = worker.task_id || null;
    actor.stationId = worker.station_id || appearance.stationId;
    actor.targetX = target.x;
    actor.targetY = target.y;
  }

  snapActorsToTargets() {
    for (const actor of this.actors.values()) {
      actor.x = actor.targetX;
      actor.y = actor.targetY;
    }
  }

  startAnimation() {
    if (this.destroyed || this.reducedMotion || this.frameId) return;
    const frame = timestamp => {
      if (this.destroyed || this.reducedMotion) {
        this.frameId = undefined;
        return;
      }
      const elapsed = this.lastFrameAt ? Math.min(48, timestamp - this.lastFrameAt) : 0;
      this.lastFrameAt = timestamp;
      this.advanceActors(elapsed);
      this.draw(timestamp);
      this.frameId = window.requestAnimationFrame(frame);
    };
    this.frameId = window.requestAnimationFrame(frame);
  }

  advanceActors(elapsed) {
    if (!elapsed) return;
    const distance = 56 * (elapsed / 1000);
    for (const actor of this.actors.values()) {
      const dx = actor.targetX - actor.x;
      const dy = actor.targetY - actor.y;
      const remaining = Math.hypot(dx, dy);
      if (remaining <= distance || remaining === 0) {
        actor.x = actor.targetX;
        actor.y = actor.targetY;
      } else {
        actor.x += (dx / remaining) * distance;
        actor.y += (dy / remaining) * distance;
      }
    }
  }

  draw(timestamp) {
    const ctx = this.ctx;
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = PALETTE.space;
    ctx.fillRect(0, 0, LOGICAL_SIZE.width, LOGICAL_SIZE.height);
    this.drawDustHaze();
    this.drawDustMotes();
    this.drawIsoFloor();
    this.drawRoomSigns();
    this.drawDoorwayMarks();
    this.drawRoomCounters();
    this.drawWorldObjects(timestamp);
    this.drawOuterFrame();
  }

  drawDustHaze() {
    const gradient = this.ctx.createRadialGradient(86, 51, 8, 86, 51, 126);
    gradient.addColorStop(0, "rgba(126, 91, 46, .14)");
    gradient.addColorStop(0.58, "rgba(69, 72, 49, .09)");
    gradient.addColorStop(1, "rgba(20, 25, 20, 0)");
    this.ctx.fillStyle = gradient;
    this.ctx.fillRect(0, 0, LOGICAL_SIZE.width, LOGICAL_SIZE.height);
    const second = this.ctx.createRadialGradient(490, 264, 5, 490, 264, 158);
    second.addColorStop(0, "rgba(59, 113, 105, .12)");
    second.addColorStop(1, "rgba(14, 24, 22, 0)");
    this.ctx.fillStyle = second;
    this.ctx.fillRect(332, 150, 268, 188);
  }

  drawDustMotes() {
    const ctx = this.ctx;
    for (let index = 0; index < 76; index += 1) {
      const x = (index * 83 + 19) % LOGICAL_SIZE.width;
      const y = (index * 47 + 13) % LOGICAL_SIZE.height;
      const light = index % 13 === 0 ? PALETTE.amber : index % 9 === 0 ? "#85846b" : "#4a4a3e";
      ctx.globalAlpha = index % 13 === 0 ? 0.72 : 0.5;
      ctx.fillStyle = light;
      ctx.fillRect(x, y, index % 11 === 0 ? 2 : 1, 1);
    }
    ctx.globalAlpha = 1;
  }

  drawIsoFloor() {
    const ctx = this.ctx;
    const cells = [...FLOOR_CELLS].sort((a, b) => (a.col + a.row) - (b.col + b.row) || a.col - b.col);
    const byPosition = new Map(cells.map(cell => [`${cell.col},${cell.row}`, cell]));
    this.floorAt = byPosition;

    const footprint = [
      projectIso(0, 0),
      projectIso(ISO_VIEW.columns - 1, 0),
      projectIso(ISO_VIEW.columns - 1, ISO_VIEW.rows - 1),
      projectIso(0, ISO_VIEW.rows - 1),
    ];
    drawPolygon(ctx, footprint.map(point => ({ x: point.x, y: point.y + 8 })), "rgba(0,0,0,.56)");

    for (const cell of cells) {
      this.drawBackWalls(cell, byPosition);
      this.drawIsoTile(cell);
      this.drawOuterFace(cell, byPosition, cell.col + 1, cell.row, "east");
      this.drawOuterFace(cell, byPosition, cell.col, cell.row + 1, "south");
    }
  }

  drawBackWalls(cell, byPosition) {
    const neighbors = [
      { col: cell.col - 1, row: cell.row, edge: "west" },
      { col: cell.col, row: cell.row - 1, edge: "north" },
    ];
    for (const neighbor of neighbors) {
      const other = byPosition.get(`${neighbor.col},${neighbor.row}`);
      if (other?.zoneId === cell.zoneId || isDoorway(cell, neighbor)) continue;
      drawBackWall(this.ctx, projectIso(cell.col, cell.row), neighbor.edge, cell.wall || PALETTE.wall, ISO_VIEW);
    }
  }

  drawIsoTile(cell) {
    const ctx = this.ctx;
    const center = projectIso(cell.col, cell.row);
    const corners = isoCorners(center, ISO_VIEW.tileWidth, ISO_VIEW.tileHeight);
    const grain = Math.abs((cell.col * 41 + cell.row * 67) % 5);
    ctx.fillStyle = grain === 0 ? lighten(cell.material, 5) : cell.material;
    drawPolygon(ctx, corners.polygon, ctx.fillStyle);
    ctx.strokeStyle = "rgba(16,19,16,.72)";
    ctx.lineWidth = 1;
    tracePolygon(ctx, corners.polygon);
    ctx.stroke();

    ctx.strokeStyle = "rgba(206,193,151,.17)";
    ctx.beginPath();
    ctx.moveTo(corners.west.x + 1, corners.west.y);
    ctx.lineTo(corners.south.x, corners.south.y - 1);
    ctx.stroke();

    const mark = Math.abs(cell.col * 37 + cell.row * 71);
    ctx.fillStyle = mark % 4 === 0 ? "#78684b" : "#292d27";
    ctx.fillRect(center.x + (mark % 9) - 4, center.y + ((mark >> 2) % 5) - 2, 1, 1);
    if (mark % 7 === 0) {
      ctx.fillStyle = "rgba(17,20,16,.55)";
      ctx.fillRect(center.x + (mark % 11) - 5, center.y + ((mark >> 3) % 5) - 2, 4, 1);
      ctx.fillRect(center.x + (mark % 11) - 2, center.y + ((mark >> 3) % 5) - 2, 1, 3);
    }
    if (mark % 3 === 0) {
      ctx.fillStyle = "#8a7958";
      ctx.fillRect(corners.east.x - 3, corners.east.y - 1, 1, 1);
      ctx.fillRect(corners.west.x + 2, corners.west.y - 1, 1, 1);
    }
  }

  drawOuterFace(cell, byPosition, col, row, edge) {
    if (byPosition.has(`${col},${row}`)) return;
    const center = projectIso(cell.col, cell.row);
    drawFrontWall(this.ctx, center, edge, cell.wall || PALETTE.wall, ISO_VIEW);
  }

  drawRoomSigns() {
    const ctx = this.ctx;
    for (const room of ROOMS) {
      const anchor = projectIso(room.grid.col + (room.grid.columns - 1) / 2, room.grid.row + 0.4);
      ctx.font = "bold 5px ui-monospace, SFMono-Regular, Menlo, monospace";
      const width = Math.min(room.grid.columns * ISO_VIEW.tileWidth * 0.62, ctx.measureText(room.label).width + 9);
      const left = Math.round(anchor.x - width / 2);
      const top = Math.round(anchor.y - 17);
      ctx.fillStyle = "rgba(19,22,18,.94)";
      ctx.fillRect(left, top, width, 9);
      ctx.fillStyle = room.wall;
      ctx.fillRect(left, top, width, 1);
      ctx.fillStyle = PALETTE[room.color];
      ctx.fillRect(left + 2, top + 3, 2, 2);
      ctx.fillStyle = PALETTE.light;
      ctx.textBaseline = "top";
      ctx.textAlign = "center";
      ctx.fillText(room.label, anchor.x + 2, top + 2, width - 8);
      ctx.textAlign = "left";
    }
  }

  drawDoorwayMarks() {
    const ctx = this.ctx;
    const doorCells = [
      [2, 3], [8, 3], [14, 3], [4, 6], [13, 6], [8, 4], [8, 5],
    ];
    for (const [col, row] of doorCells) {
      const point = projectIso(col, row);
      ctx.fillStyle = "#272923";
      ctx.fillRect(point.x - 7, point.y - 2, 14, 4);
      ctx.fillStyle = PALETTE.amber;
      for (let stripe = -5; stripe <= 5; stripe += 5) {
        ctx.fillRect(point.x + stripe, point.y - 2, 2, 4);
      }
    }
  }

  drawWorldObjects(timestamp) {
    const objects = [
      ...PROPS.map(prop => ({ type: "prop", value: prop, depth: projectIso(prop.col, prop.row).y })),
      ...STATIONS.map(station => ({ type: "station", value: station, depth: station.position.y + 4 })),
      ...[...this.actors.values()].map(actor => ({ type: "actor", value: actor, depth: actor.y })),
    ].sort((a, b) => a.depth - b.depth);
    for (const item of objects) {
      if (item.type === "prop") this.drawProp(item.value);
      else if (item.type === "station") this.drawStation(item.value, timestamp);
      else this.drawActor(item.value, timestamp);
    }
  }

  drawStation(station, timestamp) {
    const ctx = this.ctx;
    const { x, y } = station.position;
    const room = ROOMS.find(item => item.id === station.room);
    const accent = PALETTE[room?.color || "coral"];
    const worker = station.workerStationId
      ? (this.snapshot?.workers || []).find(item => item.station_id === station.workerStationId)
      : null;
    const working = worker?.status === "working";
    const selected = this.selection?.type === "station" && this.selection.id === station.id;
    const signal = working && Math.floor(timestamp / 450) % 2 === 0 ? PALETTE.green : accent;

    drawPixelShadow(ctx, x, y + 4, 16, 4);
    drawIsoPrism(ctx, x, y + 5, 25, 12, 6, "#817a60", "#4b4a3e", "#383a33");
    ctx.fillStyle = "#262b27";
    ctx.fillRect(x - 6, y - 10, 12, 8);
    ctx.fillStyle = "#8e8767";
    ctx.fillRect(x - 7, y - 11, 14, 2);
    ctx.fillStyle = "#233d39";
    ctx.fillRect(x - 4, y - 8, 8, 4);
    ctx.fillStyle = signal;
    ctx.fillRect(x - 2, y - 7, 4, 1);
    ctx.fillRect(x + 4, y - 9, 2, 2);
    ctx.fillStyle = "#d0bd91";
    ctx.fillRect(x - 10, y + 1, 3, 2);
    if (station.kind === "files") {
      ctx.fillStyle = "#c4b38b";
      ctx.fillRect(x + 7, y - 2, 5, 2);
      ctx.fillStyle = "#87664b";
      ctx.fillRect(x + 8, y - 4, 4, 2);
    } else if (station.kind === "radio") {
      ctx.fillStyle = "#32372f";
      ctx.fillRect(x + 8, y - 6, 5, 6);
      ctx.fillStyle = signal;
      ctx.fillRect(x + 9, y - 5, 1, 1);
      ctx.fillRect(x + 11, y - 3, 1, 1);
    } else if (station.kind === "workbench") {
      ctx.fillStyle = "#343831";
      ctx.fillRect(x + 7, y - 3, 5, 4);
      ctx.fillStyle = PALETTE.amber;
      ctx.fillRect(x + 8, y - 4, 1, 3);
      ctx.fillRect(x + 7, y - 4, 3, 1);
    }
    ctx.fillStyle = selected ? PALETTE.light : "#d2c59f";
    ctx.font = "4px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textBaseline = "top";
    ctx.textAlign = "center";
    ctx.fillText(station.label, x, y + 9, 35);
    ctx.textAlign = "left";
    if (selected) {
      ctx.strokeStyle = PALETTE.light;
      ctx.lineWidth = 1;
      ctx.strokeRect(station.bounds.left, station.bounds.top, station.bounds.width, station.bounds.height);
    }
  }

  drawProp(prop) {
    const ctx = this.ctx;
    const point = projectIso(prop.col, prop.row);
    drawPixelShadow(ctx, point.x, point.y + 2, 10, 3);
    if (prop.kind === "crate" || prop.kind === "toolbox" || prop.kind === "filebox") {
      const toolbox = prop.kind === "toolbox";
      const filebox = prop.kind === "filebox";
      drawIsoPrism(ctx, point.x, point.y + 1, 13, 10, toolbox ? 6 : 8,
        filebox ? "#a58d68" : toolbox ? "#68715b" : "#80543b", "#4b4031", "#35342b");
      ctx.fillStyle = toolbox ? PALETTE.amber : "#bd9863";
      ctx.fillRect(point.x - 2, point.y - 4, 4, 1);
      if (filebox) {
        ctx.fillStyle = "#e0d0a6";
        ctx.fillRect(point.x - 4, point.y - 6, 8, 2);
        ctx.fillStyle = "#8d7855";
        ctx.fillRect(point.x - 2, point.y - 5, 3, 1);
      }
      return;
    }
    if (["locker", "filecabinet", "shelf"].includes(prop.kind)) {
      drawIsoPrism(ctx, point.x, point.y + 2, 13, 10, prop.kind === "shelf" ? 19 : 23,
        prop.kind === "locker" ? "#74725e" : "#82765a", "#514d3d", "#3a3a31");
      ctx.fillStyle = "#a79a75";
      ctx.fillRect(point.x - 3, point.y - 14, 1, 7);
      ctx.fillRect(point.x + 2, point.y - 14, 1, 7);
      ctx.fillStyle = PALETTE.rust;
      ctx.fillRect(point.x + 4, point.y - 11, 1, 1);
      ctx.fillStyle = "#d0bd91";
      ctx.fillRect(point.x - 1, point.y - 8, 2, 1);
      return;
    }
    if (prop.kind === "lamp" || prop.kind === "antenna") {
      drawIsoPrism(ctx, point.x, point.y + 2, 11, 8, 5, "#6b634a", "#403d32", "#30332c");
      ctx.fillStyle = "#4c5147";
      ctx.fillRect(point.x - 1, point.y - 13, 2, 14);
      ctx.fillRect(point.x - 5, point.y - 14, 10, 2);
      ctx.fillStyle = prop.kind === "lamp" ? PALETTE.amber : PALETTE.cyan;
      ctx.fillRect(point.x - 3, point.y - 12, 6, 2);
      ctx.globalAlpha = 0.35;
      ctx.fillRect(point.x - 5, point.y - 10, 10, 3);
      ctx.globalAlpha = 1;
      return;
    }
    if (prop.kind === "radio") {
      drawIsoPrism(ctx, point.x, point.y + 2, 12, 8, 9, "#606650", "#3c4239", "#2d342f");
      ctx.fillStyle = PALETTE.coral;
      ctx.fillRect(point.x - 2, point.y - 5, 2, 2);
      ctx.fillStyle = PALETTE.cyan;
      ctx.fillRect(point.x + 2, point.y - 5, 2, 2);
      return;
    }
    if (prop.kind === "cactus") {
      drawIsoPrism(ctx, point.x, point.y + 2, 9, 7, 5, "#936b4c", "#514234", "#36332a");
      ctx.fillStyle = "#758358";
      ctx.fillRect(point.x - 1, point.y - 9, 3, 9);
      ctx.fillRect(point.x - 4, point.y - 6, 3, 2);
      ctx.fillRect(point.x - 4, point.y - 8, 2, 4);
      ctx.fillRect(point.x + 2, point.y - 5, 3, 2);
      ctx.fillRect(point.x + 3, point.y - 7, 2, 4);
    }
  }

  drawRoomCounters() {
    const counts = this.snapshot?.counts || {};
    const entries = {
      jobs: [`ROLES ${formatCount(counts.jobs_found)}`, `MATCH ${formatCount(counts.jobs_matched)}`],
      resume: [`DRAFTS ${formatCount(counts.drafts_to_review)}`],
      applications: [`DRAFTS ${formatCount(counts.drafts_to_review)}`],
      portfolio: [`REVIEW ${formatCount(counts.proposals_to_review)}`, `DONE ${formatCount(counts.tasks_shipped)}`],
      dispatch: [],
      outreach: [`REVIEW ${formatCount(counts.outreach_to_review)}`],
    };
    const ctx = this.ctx;
    for (const room of ROOMS) {
      const point = projectIso(room.grid.col + room.grid.columns - 0.5, room.grid.row + room.grid.rows - 0.5);
      ctx.font = "4px ui-monospace, SFMono-Regular, Menlo, monospace";
      ctx.textBaseline = "top";
      ctx.textAlign = "center";
      ctx.fillStyle = PALETTE[room.color];
      (entries[room.id] || []).forEach((value, index) => ctx.fillText(value, point.x, point.y + 2 + index * 5, 45));
    }
    ctx.textAlign = "left";
  }

  drawActor(actor, timestamp) {
    const appearance = WORKER_APPEARANCE[actor.id];
    const sprite = appearance.sprite;
    const scale = 2;
    const width = sprite[0].length * scale;
    const height = sprite.length * scale;
    const x = Math.round(actor.x - width / 2);
    const y = Math.round(actor.y - height);
    actor.bounds = { x, y, width, height };
    const moving = Math.hypot(actor.targetX - actor.x, actor.targetY - actor.y) > 0.75;
    const working = actor.status === "working";
    const step = Math.floor(timestamp / 170) % 2;
    drawPixelShadow(this.ctx, actor.x, actor.y + 1, 8, 3);
    for (let row = 0; row < sprite.length; row += 1) {
      for (let column = 0; column < sprite[row].length; column += 1) {
        const symbol = sprite[row][column];
        if (symbol === ".") continue;
        let color = SPRITE_COLORS[symbol];
        if (symbol === "A") color = actor.color;
        if (moving && symbol === "K" && (column + step) % 2 === 0) continue;
        this.ctx.fillStyle = color;
        this.ctx.fillRect(x + column * scale, y + row * scale, scale, scale);
      }
    }
    this.drawWorkerGear(appearance.gear, x, y, width, timestamp);
    if (working) {
      const blink = Math.floor(timestamp / 400) % 2 === 0;
      this.ctx.fillStyle = blink ? PALETTE.green : PALETTE.amber;
      this.ctx.fillRect(Math.round(x + width - 2), Math.round(y + 19 + step), 3, 2);
      this.ctx.fillStyle = blink ? PALETTE.green : PALETTE.light;
      this.ctx.fillRect(Math.round(actor.x + 9), Math.round(y - 4), 3, 3);
    } else if (actor.status === "needs_review") {
      this.ctx.fillStyle = PALETTE.amber;
      this.ctx.fillRect(Math.round(actor.x + 9), Math.round(y - 4), 3, 3);
    }
    if (this.selection?.type === "worker" && this.selection.id === actor.id) {
      this.ctx.strokeStyle = PALETTE.light;
      this.ctx.lineWidth = 1;
      this.ctx.strokeRect(x - 3.5, y - 3.5, width + 7, height + 7);
    }
  }

  drawWorkerGear(gear, x, y, width, timestamp) {
    const ctx = this.ctx;
    if (gear === "visor" || gear === "goggles") {
      ctx.fillStyle = gear === "visor" ? PALETTE.amber : PALETTE.cyan;
      ctx.fillRect(x + 6, y + 9, 10, 2);
      ctx.fillStyle = "#28302c";
      ctx.fillRect(x + 9, y + 9, 2, 2);
    } else if (gear === "glasses") {
      ctx.fillStyle = PALETTE.green;
      ctx.fillRect(x + 7, y + 10, 3, 2);
      ctx.fillRect(x + 13, y + 10, 3, 2);
      ctx.fillStyle = "#43392e";
      ctx.fillRect(x + 10, y + 10, 3, 1);
    } else if (gear === "clipboard") {
      ctx.fillStyle = "#715f43";
      ctx.fillRect(x + width - 1, y + 19, 4, 9);
      ctx.fillStyle = "#d9cda8";
      ctx.fillRect(x + width, y + 20, 2, 6);
      ctx.fillStyle = PALETTE.amber;
      ctx.fillRect(x + width, y + 22, 1, 1);
    } else if (gear === "headset") {
      ctx.fillStyle = PALETTE.coral;
      ctx.fillRect(x + width - 5, y + 5, 2, 8);
      ctx.fillRect(x + width - 5, y + 12, 4, 2);
      ctx.fillStyle = PALETTE.cyan;
      ctx.fillRect(x + width - 3, y + 14, 1, 2);
    } else if (gear === "cap") {
      ctx.fillStyle = PALETTE.amber;
      ctx.fillRect(x + 7, y + 1, 10, 2);
      ctx.fillRect(x + 5, y + 3, 14, 2);
      ctx.fillStyle = Math.floor(timestamp / 600) % 2 ? PALETTE.amber : PALETTE.green;
      ctx.fillRect(x + 10, y + 4, 3, 1);
    }
  }

  drawOuterFrame() {
    const ctx = this.ctx;
    ctx.strokeStyle = PALETTE.frame;
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, LOGICAL_SIZE.width - 2, LOGICAL_SIZE.height - 2);
    ctx.strokeStyle = "#38305e";
    ctx.lineWidth = 1;
    ctx.strokeRect(5.5, 5.5, LOGICAL_SIZE.width - 11, LOGICAL_SIZE.height - 11);
    ctx.fillStyle = PALETTE.frame;
    const right = LOGICAL_SIZE.width - 10;
    const bottom = LOGICAL_SIZE.height - 10;
    for (const [index, [x, y]] of [[6, 6], [right, 6], [6, bottom], [right, bottom]].entries()) {
      ctx.fillStyle = index % 2 === 0 ? PALETTE.cyan : PALETTE.purple;
      ctx.fillRect(x, y, 3, 3);
    }
  }

  selectAt(event) {
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = (event.clientX - rect.left) * LOGICAL_SIZE.width / rect.width;
    const y = (event.clientY - rect.top) * LOGICAL_SIZE.height / rect.height;
    const actor = this.actorAtPoint(x, y);
    if (actor) {
      this.hoveredWorker = null;
      this.onHover(null, null);
      this.selection = { type: "worker", id: actor.id };
      this.onSelect(this.selection);
      this.draw(0);
      return;
    }
    const station = findStationAt(x, y);
    if (station) {
      this.selection = { type: "station", id: station.id };
      this.onSelect(this.selection);
      this.draw(0);
    }
  }

  hoverAt(event) {
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = (event.clientX - rect.left) * LOGICAL_SIZE.width / rect.width;
    const y = (event.clientY - rect.top) * LOGICAL_SIZE.height / rect.height;
    const actor = this.actorAtPoint(x, y);
    this.hoveredWorker = actor?.id || null;
    this.hoverPosition = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    this.canvas.style.cursor = actor ? "pointer" : "crosshair";
    this.onHover(this.hoveredWorker, this.hoverPosition);
  }

  clearHover() {
    this.hoveredWorker = null;
    this.hoverPosition = null;
    this.canvas.style.cursor = "crosshair";
    this.onHover(null, null);
  }

  actorAtPoint(x, y) {
    for (const actor of this.actors.values()) {
      const bounds = actor.bounds;
      if (bounds && x >= bounds.x - 3 && x <= bounds.x + bounds.width + 3 && y >= bounds.y - 3 && y <= bounds.y + bounds.height + 3) {
        return actor;
      }
    }
    return null;
  }
}

function isDoorway(first, second) {
  const cells = [`${first.col},${first.row}`, `${second.col},${second.row}`].sort();
  return DOORWAY_EDGES.has(cells.join("|"));
}

function isoCorners(center, width, height) {
  const north = { x: center.x, y: center.y - height / 2 };
  const east = { x: center.x + width / 2, y: center.y };
  const south = { x: center.x, y: center.y + height / 2 };
  const west = { x: center.x - width / 2, y: center.y };
  return { north, east, south, west, polygon: [north, east, south, west] };
}

function drawPolygon(ctx, points, color) {
  if (!points?.length) return;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let index = 1; index < points.length; index += 1) ctx.lineTo(points[index].x, points[index].y);
  ctx.closePath();
  if (color) {
    ctx.fillStyle = color;
    ctx.fill();
  }
}

function tracePolygon(ctx, points) {
  if (!points?.length) return;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let index = 1; index < points.length; index += 1) ctx.lineTo(points[index].x, points[index].y);
  ctx.closePath();
}

function drawBackWall(ctx, center, edge, color, view) {
  const corners = isoCorners(center, view.tileWidth, view.tileHeight);
  const [start, end] = edge === "west"
    ? [corners.west, corners.north]
    : [corners.north, corners.east];
  const upperStart = { x: start.x, y: start.y - view.wallHeight };
  const upperEnd = { x: end.x, y: end.y - view.wallHeight };
  drawPolygon(ctx, [start, end, upperEnd, upperStart], color);
  ctx.strokeStyle = "rgba(20,22,18,.82)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(upperStart.x, upperStart.y);
  ctx.lineTo(upperEnd.x, upperEnd.y);
  ctx.lineTo(end.x, end.y);
  ctx.stroke();
  ctx.fillStyle = "rgba(207,193,151,.25)";
  ctx.fillRect(Math.round((upperStart.x + upperEnd.x) / 2), Math.round((upperStart.y + upperEnd.y) / 2), 2, 1);
  ctx.fillStyle = "rgba(21,24,20,.55)";
  ctx.fillRect(Math.round((start.x + end.x) / 2), Math.round((start.y + end.y) / 2 - 5), 1, 3);
}

function drawFrontWall(ctx, center, edge, color, view) {
  const corners = isoCorners(center, view.tileWidth, view.tileHeight);
  const [start, end] = edge === "east"
    ? [corners.east, corners.south]
    : [corners.west, corners.south];
  const lowerStart = { x: start.x, y: start.y + view.edgeDepth };
  const lowerEnd = { x: end.x, y: end.y + view.edgeDepth };
  drawPolygon(ctx, [start, end, lowerEnd, lowerStart], "#292c27");
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(start.x, start.y + 1);
  ctx.lineTo(end.x, end.y + 1);
  ctx.stroke();
  ctx.fillStyle = "rgba(183,157,109,.42)";
  ctx.fillRect(Math.round((start.x + end.x) / 2), Math.round((start.y + end.y) / 2 + 3), 2, 1);
}

function drawIsoPrism(ctx, x, baseY, width, depth, height, topColor, eastColor, westColor) {
  const top = isoCorners({ x, y: baseY - height }, width, depth);
  const base = isoCorners({ x, y: baseY }, width, depth);
  drawPolygon(ctx, [top.east, top.south, base.south, base.east], eastColor);
  drawPolygon(ctx, [top.west, top.south, base.south, base.west], westColor);
  drawPolygon(ctx, top.polygon, topColor);
  ctx.strokeStyle = "rgba(20,21,17,.9)";
  ctx.lineWidth = 1;
  tracePolygon(ctx, top.polygon);
  ctx.stroke();
  ctx.strokeStyle = "rgba(216,199,155,.35)";
  ctx.beginPath();
  ctx.moveTo(top.north.x, top.north.y);
  ctx.lineTo(top.east.x, top.east.y);
  ctx.stroke();
}

function drawPixelShadow(ctx, x, y, width, depth) {
  ctx.fillStyle = "rgba(0,0,0,.34)";
  for (let row = 0; row < depth; row += 1) {
    const inset = Math.abs(row - Math.floor(depth / 2));
    ctx.fillRect(Math.round(x - width / 2 + inset), Math.round(y + row), Math.max(1, width - inset * 2), 1);
  }
}

function lighten(hex, amount) {
  const value = Number.parseInt(hex.slice(1), 16);
  const red = Math.min(255, ((value >> 16) & 255) + amount);
  const green = Math.min(255, ((value >> 8) & 255) + amount);
  const blue = Math.min(255, (value & 255) + amount);
  return `rgb(${red}, ${green}, ${blue})`;
}

function formatCount(value) {
  return Number.isInteger(value) ? String(value).padStart(2, "0") : "—";
}
