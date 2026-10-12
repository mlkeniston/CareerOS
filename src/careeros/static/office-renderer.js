import {
  DOORWAYS,
  DOORWAY_EDGES,
  CONVEYOR_NETWORK,
  FLOOR_CELLS,
  ISO_VIEW,
  LOGICAL_SIZE,
  PALETTE,
  PROPS,
  ROOMS,
  SPRITE_COLORS,
  STATIONS,
  WORKER_APPEARANCE,
  WORKER_DISPLAY_SCALE,
  createIsoProjector,
  findStationAt,
} from "./office-layout.js";

const HANDOFF_KINDS = Object.freeze({
  "draft-submitted": "document",
  "critique-returned": "document",
  "project-submitted": "project",
  "project-defect-returned": "ticket",
  "project-qa-passed": "green-pass",
});

export class HandoffCursor {
  constructor(renderer) {
    this.renderer = renderer;
    this.afterId = null;
  }

  initialize(snapshot) {
    if (this.afterId === null && Number.isSafeInteger(snapshot?.handoff_cursor) && snapshot.handoff_cursor >= 0) {
      this.afterId = snapshot.handoff_cursor;
    }
  }

  receive(batch) {
    if (this.afterId === null) return;
    const returned = Array.isArray(batch?.events) ? batch.events : [];
    const events = returned.filter(event => Number.isSafeInteger(event.id) && event.id > this.afterId);
    if (events.length) this.renderer.playHandoffs(events);
    if (returned.length) {
      if (events.length) this.afterId = Math.max(this.afterId, ...events.map(event => event.id));
    } else if (Number.isSafeInteger(batch?.latest_id)) {
      this.afterId = Math.max(this.afterId, batch.latest_id);
    }
  }
}

export class OfficeRenderer {
  constructor(canvas, { onSelect = () => {}, onHover = () => {}, onViewChange = () => {}, now = () => performance.now() } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: false });
    if (!this.ctx) throw new Error("The office canvas is not available in this browser.");
    this.onSelect = onSelect;
    this.onHover = onHover;
    this.onViewChange = onViewChange;
    this.rotation = 0;
    this.project = createIsoProjector(this.rotation);
    this.drag = null;
    this.suppressClick = false;
    this.snapshot = null;
    this.actors = new Map();
    this.selection = null;
    this.hoveredWorker = null;
    this.hoverPosition = null;
    this.active = true;
    this.destroyed = false;
    this.lastFrameAt = 0;
    this.now = now;
    this.handoffs = [];
    this.motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
    this.reducedMotion = this.motionPreference.matches;
    this.handleResize = () => this.resize();
    this.handleClick = event => this.selectAt(event);
    this.handlePointerDown = event => this.beginOrbit(event);
    this.handlePointerMove = event => this.drag ? this.orbitTo(event) : this.hoverAt(event);
    this.handlePointerUp = event => this.endOrbit(event);
    this.handlePointerCancel = event => this.endOrbit(event, true);
    this.handleKeyDown = event => this.handleOfficeKey(event);
    this.handlePointerLeave = () => { if (!this.drag) this.clearHover(); };
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
    canvas.addEventListener("pointerdown", this.handlePointerDown);
    canvas.addEventListener("pointermove", this.handlePointerMove);
    canvas.addEventListener("pointerup", this.handlePointerUp);
    canvas.addEventListener("pointercancel", this.handlePointerCancel);
    canvas.addEventListener("pointerleave", this.handlePointerLeave);
    canvas.addEventListener("keydown", this.handleKeyDown);
    if (this.motionPreference.addEventListener) {
      this.motionPreference.addEventListener("change", this.handleMotionChange);
    } else {
      this.motionPreference.addListener(this.handleMotionChange);
    }
    this.resize();
    this.onViewChange(this.rotation);
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

  playHandoffs(events) {
    if (!Array.isArray(events) || this.destroyed) return;
    const startedAt = this.now();
    for (const event of events) {
      const kind = HANDOFF_KINDS[event?.event_type];
      if (!kind) continue;
      const from = this.handoffPosition(event.from_worker, event.from_station_id);
      const to = this.handoffPosition(event.to_worker, event.to_station_id);
      if (!from || !to) continue;
      this.handoffs.push({ id: event.id, kind, from, to, startedAt });
    }
    this.draw(startedAt);
  }

  handoffPosition(workerId, stationId) {
    const station = STATIONS.find(item => item.workerStationId === stationId)
      || STATIONS.find(item => item.workerStationId === WORKER_APPEARANCE[workerId]?.stationId);
    return station?.workerCell || this.actors.get(workerId) || WORKER_APPEARANCE[workerId]?.waitCell || null;
  }

  activeHandoffTokens(timestamp) {
    const now = timestamp || this.now();
    this.handoffs = this.handoffs.filter(item => now - item.startedAt < 2000);
    return this.handoffs.map(item => {
      const phase = this.reducedMotion ? 1 : Math.max(0, Math.min(1, (now - item.startedAt) / 700));
      return {
        id: item.id,
        kind: item.kind,
        col: item.from.col + (item.to.col - item.from.col) * phase,
        row: item.from.row + (item.to.row - item.from.row) * phase,
      };
    });
  }

  setSelection(selection) {
    this.selection = selection && ["worker", "station"].includes(selection.type) ? selection : null;
    this.draw(0);
  }

  setActive(active) {
    const next = Boolean(active);
    if (this.destroyed || this.active === next) return;
    this.active = next;
    this.lastFrameAt = 0;
    if (!this.active) {
      if (this.frameId) window.cancelAnimationFrame(this.frameId);
      this.frameId = undefined;
      return;
    }
    this.draw(0);
    if (!this.reducedMotion) this.startAnimation();
  }

  setRotation(degrees) {
    this.rotation = ((degrees % 360) + 360) % 360;
    this.project = createIsoProjector(this.rotation);
    this.onViewChange(this.rotation);
    this.draw(0);
  }

  beginOrbit(event) {
    if (event.button !== undefined && event.button !== 0) return;
    this.drag = { startX: event.clientX, startRotation: this.rotation, moved: false, pointerId: event.pointerId };
    this.canvas.style.cursor = "grabbing";
    this.hoveredWorker = null;
    this.onHover(null, null);
    this.canvas.setPointerCapture?.(event.pointerId);
  }

  orbitTo(event) {
    if (!this.drag) return;
    const distance = Math.abs(event.clientX - this.drag.startX);
    if (distance > 3) this.drag.moved = true;
    if (this.drag.moved) this.setRotation(this.drag.startRotation + (event.clientX - this.drag.startX) * 0.6);
  }

  endOrbit(event, cancelled = false) {
    if (!this.drag) return;
    const drag = this.drag;
    this.drag = null;
    this.suppressClick = drag.moved && !cancelled;
    this.canvas.style.cursor = "grab";
    this.canvas.releasePointerCapture?.(event.pointerId ?? drag.pointerId);
  }

  handleOfficeKey(event) {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      this.setRotation(this.rotation + (event.key === "ArrowRight" ? 15 : -15));
    } else if (event.key === "Home") {
      event.preventDefault();
      this.setRotation(0);
    }
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    if (this.frameId) window.cancelAnimationFrame(this.frameId);
    window.removeEventListener("resize", this.handleResize);
    this.canvas.removeEventListener("click", this.handleClick);
    this.canvas.removeEventListener("pointerdown", this.handlePointerDown);
    this.canvas.removeEventListener("pointermove", this.handlePointerMove);
    this.canvas.removeEventListener("pointerup", this.handlePointerUp);
    this.canvas.removeEventListener("pointercancel", this.handlePointerCancel);
    this.canvas.removeEventListener("pointerleave", this.handlePointerLeave);
    this.canvas.removeEventListener("keydown", this.handleKeyDown);
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
    const station = STATIONS.find(item => item.workerStationId === worker.station_id)
      || STATIONS.find(item => item.workerStationId === appearance.stationId);
    const isAtStation = ["working", "needs_review", "failed", "interrupted"].includes(worker.status);
    const targetCell = isAtStation ? station?.workerCell : appearance.waitCell;
    let actor = this.actors.get(worker.id);
    if (!actor) {
      actor = { id: worker.id, col: appearance.waitCell.col, row: appearance.waitCell.row };
      this.actors.set(worker.id, actor);
    }
    actor.name = worker.name || worker.id;
    actor.color = PALETTE[worker.color] || PALETTE[appearance.color];
    actor.status = worker.status;
    actor.taskId = worker.task_id || null;
    actor.stationId = worker.station_id || appearance.stationId;
    actor.targetCol = targetCell?.col ?? appearance.waitCell.col;
    actor.targetRow = targetCell?.row ?? appearance.waitCell.row;
  }

  snapActorsToTargets() {
    for (const actor of this.actors.values()) {
      actor.col = actor.targetCol;
      actor.row = actor.targetRow;
    }
  }

  startAnimation() {
    if (this.destroyed || !this.active || this.reducedMotion || this.frameId) return;
    const frame = timestamp => {
      if (this.destroyed || !this.active || this.reducedMotion) {
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
    const distance = 3.2 * (elapsed / 1000);
    for (const actor of this.actors.values()) {
      const dx = actor.targetCol - actor.col;
      const dy = actor.targetRow - actor.row;
      const remaining = Math.hypot(dx, dy);
      if (remaining <= distance || remaining === 0) {
        actor.col = actor.targetCol;
        actor.row = actor.targetRow;
      } else {
        actor.col += (dx / remaining) * distance;
        actor.row += (dy / remaining) * distance;
      }
    }
  }

  draw(timestamp) {
    const ctx = this.ctx;
    ctx.imageSmoothingEnabled = false;
    this.drawAtmosphericBackdrop();
    this.drawDustHaze();
    this.drawDustMotes();
    this.drawIsoFloor();
    this.drawRoomSigns();
    this.drawDoorwayMarks();
    this.drawRoomCounters();
    this.drawConveyorNetwork(timestamp);
    this.drawWorldObjects(timestamp);
    this.drawOuterFrame();
  }

  drawAtmosphericBackdrop() {
    const ctx = this.ctx;
    const sky = ctx.createLinearGradient(0, 0, 0, LOGICAL_SIZE.height);
    sky.addColorStop(0, PALETTE.space);
    sky.addColorStop(0.42, "#172728");
    sky.addColorStop(0.78, "#131b1d");
    sky.addColorStop(1, "#110f19");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, LOGICAL_SIZE.width, LOGICAL_SIZE.height);
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
    const cells = [...FLOOR_CELLS].sort((a, b) => this.project(a.col, a.row).y - this.project(b.col, b.row).y);
    const byPosition = new Map(cells.map(cell => [`${cell.col},${cell.row}`, cell]));
    this.floorAt = byPosition;

    const footprint = [
      this.project(-0.5, -0.5),
      this.project(ISO_VIEW.columns - 0.5, -0.5),
      this.project(ISO_VIEW.columns - 0.5, ISO_VIEW.rows - 0.5),
      this.project(-0.5, ISO_VIEW.rows - 0.5),
    ];
    drawPolygon(ctx, footprint.map(point => ({ x: point.x, y: point.y + ISO_VIEW.edgeDepth * this.project.scale })), "rgba(0,0,0,.56)");

    const backWalls = [];
    const frontWalls = [];
    const seenEdges = new Set();
    const viewX = Math.cos(this.rotation * Math.PI / 180) + Math.sin(this.rotation * Math.PI / 180);
    const viewY = Math.cos(this.rotation * Math.PI / 180) - Math.sin(this.rotation * Math.PI / 180);
    for (const cell of cells) {
      for (const edge of cellEdges(cell)) {
        const neighbor = byPosition.get(`${cell.col + edge.neighbor.col},${cell.row + edge.neighbor.row}`);
        if (neighbor?.zoneId === cell.zoneId || (neighbor && isDoorway(cell, {
          col: cell.col + edge.neighbor.col,
          row: cell.row + edge.neighbor.row,
        }))) continue;
        const endpoints = [edge.start, edge.end]
          .map(point => `${point.col.toFixed(2)},${point.row.toFixed(2)}`).sort();
        const key = endpoints.join("|");
        if (seenEdges.has(key)) continue;
        seenEdges.add(key);
        const front = edge.normal.col * viewX + edge.normal.row * viewY > 0;
        const wall = { ...edge, front, color: cell.wall || PALETTE.wall };
        (front ? frontWalls : backWalls).push(wall);
      }
    }
    for (const wall of backWalls) this.drawWallSegment(wall);
    for (const cell of cells) this.drawIsoTile(cell);
    for (const wall of frontWalls) this.drawWallSegment(wall);
  }

  drawWallSegment(wall) {
    const ctx = this.ctx;
    const start = this.project(wall.start.col, wall.start.row);
    const end = this.project(wall.end.col, wall.end.row);
    const wallHeight = ISO_VIEW.wallHeight * this.project.scale;
    const edgeDepth = ISO_VIEW.edgeDepth * this.project.scale;
    const topStart = { x: start.x, y: start.y - wallHeight };
    const topEnd = { x: end.x, y: end.y - wallHeight };
    drawPolygon(ctx, [start, end, topEnd, topStart], wall.front ? lighten(wall.color, -11) : wall.color);
    ctx.strokeStyle = wall.color;
    ctx.lineWidth = Math.max(1, this.project.scale);
    ctx.beginPath();
    ctx.moveTo(topStart.x, topStart.y);
    ctx.lineTo(topEnd.x, topEnd.y);
    ctx.stroke();
    const fasteners = [0.18, 0.82];
    for (const fraction of fasteners) {
      const x = Math.round(start.x + (end.x - start.x) * fraction);
      const y = Math.round(start.y + (end.y - start.y) * fraction - wallHeight * 0.68);
      ctx.fillStyle = "rgba(26,29,25,.8)";
      ctx.fillRect(x, y, 2, 2);
      ctx.fillStyle = "rgba(204,190,150,.48)";
      ctx.fillRect(x, y, 1, 1);
    }
    if (wall.front) {
      const lowerStart = { x: start.x, y: start.y + edgeDepth };
      const lowerEnd = { x: end.x, y: end.y + edgeDepth };
      drawPolygon(ctx, [start, end, lowerEnd, lowerStart], "#292c27");
      ctx.fillStyle = "rgba(183,157,109,.5)";
      ctx.fillRect(Math.round((start.x + end.x) / 2), Math.round((start.y + end.y) / 2 + 3), 2, 1);
      return;
    }
    ctx.strokeStyle = "rgba(20,22,18,.82)";
    ctx.lineWidth = Math.max(1, this.project.scale);
    ctx.beginPath();
    ctx.moveTo(topStart.x, topStart.y);
    ctx.lineTo(topEnd.x, topEnd.y);
    ctx.lineTo(end.x, end.y);
    ctx.stroke();
    ctx.fillStyle = "rgba(207,193,151,.25)";
    ctx.fillRect(Math.round((topStart.x + topEnd.x) / 2), Math.round((topStart.y + topEnd.y) / 2), 2, 1);
  }

  drawIsoTile(cell) {
    const ctx = this.ctx;
    const center = this.project(cell.col, cell.row);
    const corners = {
      north: this.project(cell.col - 0.5, cell.row - 0.5),
      east: this.project(cell.col + 0.5, cell.row - 0.5),
      south: this.project(cell.col + 0.5, cell.row + 0.5),
      west: this.project(cell.col - 0.5, cell.row + 0.5),
    };
    corners.polygon = [corners.north, corners.east, corners.south, corners.west];
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
    if (mark % 4 === 1) {
      this.drawGroundPatch(cell.col - 0.16, cell.row + 0.11, 0.2, 0.12, "#69634d");
      this.drawGroundPatch(cell.col - 0.04, cell.row + 0.16, 0.08, 0.07, "#393b33");
    }
    if (mark % 6 === 2) {
      const start = this.project(cell.col - 0.28, cell.row + 0.13);
      const end = this.project(cell.col - 0.09, cell.row + 0.26);
      drawPolygon(ctx, segmentBand(start, end, 0, 1, 0.45 * this.project.scale), "rgba(20,23,19,.64)");
    }
    if (mark % 9 === 0) {
      this.drawGroundPatch(cell.col + 0.24, cell.row - 0.19, 0.075, 0.075, "#99906d");
    }
  }

  drawGroundPatch(col, row, width, depth, color) {
    const halfCol = width / 2;
    const halfRow = depth / 2;
    drawPolygon(this.ctx, [
      this.project(col - halfCol, row - halfRow),
      this.project(col + halfCol, row - halfRow),
      this.project(col + halfCol, row + halfRow),
      this.project(col - halfCol, row + halfRow),
    ], color);
  }

  drawRoomSigns() {
    const ctx = this.ctx;
    for (const room of ROOMS) {
      const anchor = this.project(room.grid.col + (room.grid.columns - 1) / 2, room.grid.row + 0.4);
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

  drawGroundPrism(col, row, width, depth, height, topColor, eastColor, westColor) {
    const halfCol = width / ISO_VIEW.tileWidth / 2;
    const halfRow = depth / ISO_VIEW.tileHeight / 2;
    const corners = [
      { col: col - halfCol, row: row - halfRow },
      { col: col + halfCol, row: row - halfRow },
      { col: col + halfCol, row: row + halfRow },
      { col: col - halfCol, row: row + halfRow },
    ];
    const base = corners.map(point => this.project(point.col, point.row));
    const top = base.map(point => ({ x: point.x, y: point.y - height * this.project.scale }));
    const angle = this.rotation * Math.PI / 180;
    const viewCol = Math.cos(angle) + Math.sin(angle);
    const viewRow = Math.cos(angle) - Math.sin(angle);
    const faces = [
      { from: 0, to: 1, normal: { col: 0, row: -1 }, color: westColor },
      { from: 1, to: 2, normal: { col: 1, row: 0 }, color: eastColor },
      { from: 2, to: 3, normal: { col: 0, row: 1 }, color: eastColor },
      { from: 3, to: 0, normal: { col: -1, row: 0 }, color: westColor },
    ];
    for (const face of faces) {
      if (face.normal.col * viewCol + face.normal.row * viewRow <= 0) continue;
      drawPolygon(this.ctx, [top[face.from], top[face.to], base[face.to], base[face.from]], face.color);
    }
    drawPolygon(this.ctx, top, topColor);
    this.ctx.strokeStyle = "rgba(20,21,17,.9)";
    this.ctx.lineWidth = Math.max(1, this.project.scale);
    tracePolygon(this.ctx, top);
    this.ctx.stroke();
    this.ctx.strokeStyle = "rgba(216,199,155,.35)";
    this.ctx.beginPath();
    this.ctx.moveTo(top[0].x, top[0].y);
    this.ctx.lineTo(top[1].x, top[1].y);
    this.ctx.stroke();
  }

  drawDoorwayMarks() {
    const ctx = this.ctx;
    const width = 2.8 * this.project.scale;
    for (const doorway of DOORWAYS) {
      const start = this.project(doorway.start.col, doorway.start.row);
      const end = this.project(doorway.end.col, doorway.end.row);
      drawPolygon(ctx, segmentBand(start, end, 0, 1, width), "#272923");
      for (const stripe of [0.12, 0.47, 0.82]) {
        drawPolygon(ctx, segmentBand(start, end, stripe, Math.min(1, stripe + 0.12), width * 0.72), PALETTE.amber);
      }
    }
  }

  drawWorldObjects(timestamp) {
    const objects = [
      ...PROPS.map(prop => ({ type: "prop", value: prop, depth: this.project(prop.col, prop.row).y })),
      ...STATIONS.map(station => ({ type: "station", value: station, depth: this.project(station.cell.col, station.cell.row).y + 4 })),
      ...[...this.actors.values()].map(actor => ({ type: "actor", value: actor, depth: this.project(actor.col, actor.row).y })),
      ...this.activeConveyorParcels(timestamp).map(parcel => ({
        type: "parcel",
        value: parcel,
        depth: this.project(parcel.col, parcel.row).y + 1,
      })),
      ...this.activeHandoffTokens(timestamp).map(token => ({
        type: "handoff",
        value: token,
        depth: this.project(token.col, token.row).y + 2,
      })),
    ].sort((a, b) => a.depth - b.depth);
    for (const item of objects) {
      if (item.type === "prop") this.drawProp(item.value);
      else if (item.type === "station") this.drawStation(item.value, timestamp);
      else if (item.type === "parcel") this.drawParcel(item.value);
      else if (item.type === "handoff") this.drawHandoffToken(item.value);
      else this.drawActor(item.value, timestamp);
    }
  }

  activeConveyorParcels(timestamp) {
    return (this.snapshot?.workers || []).flatMap(worker => {
      if (worker.status !== "working" || !worker.task_id) return [];
      const source = STATIONS.find(item => item.workerStationId === worker.station_id);
      if (!source) return [];
      const lane = CONVEYOR_NETWORK.find(item => item.stationIds.includes(source.trackId));
      if (!lane) return [];
      const sourceIndex = lane.stationIds.indexOf(source.trackId);
      const destination = STATIONS.find(item => item.trackId === lane.stationIds[sourceIndex + 1]);
      if (!destination) return [];

      const phase = taskPhase(worker.task_id, timestamp, 3200);
      const rowOffset = 0.78;
      return [{
        col: source.cell.col + (destination.cell.col - source.cell.col) * phase,
        row: source.cell.row + rowOffset
          + ((destination.cell.row + rowOffset) - (source.cell.row + rowOffset)) * phase,
        color: PALETTE[worker.color] || PALETTE[WORKER_APPEARANCE[worker.id]?.color] || PALETTE.cyan,
      }];
    });
  }

  drawConveyorNetwork(timestamp) {
    const ctx = this.ctx;
    const scale = this.project.scale;
    const rollerPhase = this.reducedMotion ? 0 : (timestamp * 0.003) % (7 * scale);
    for (const lane of CONVEYOR_NETWORK) {
      for (let index = 0; index < lane.waypoints.length - 1; index += 1) {
        const start = this.project(lane.waypoints[index].col, lane.waypoints[index].row);
        const end = this.project(lane.waypoints[index + 1].col, lane.waypoints[index + 1].row);
        const length = Math.hypot(end.x - start.x, end.y - start.y);
        if (!length) continue;
        drawPolygon(ctx, segmentBand(start, end, 0, 1, 6 * scale), "#1d2422");
        drawPolygon(ctx, segmentBand(start, end, 0, 1, 4.7 * scale), "#8a7450");
        drawPolygon(ctx, segmentBand(start, end, 0, 1, 4 * scale), PALETTE.conveyor);
        drawPolygon(ctx, segmentBand(start, end, 0, 1, 2.9 * scale), "#25302e");

        const spacing = 8 * scale;
        for (let distance = rollerPhase; distance < length; distance += spacing) {
          const position = distance / length;
          const slatLength = Math.min(2.2 * scale / length, 1 - position);
          if (slatLength <= 0) continue;
          const slatColor = Math.round(distance / spacing) % 2 === 0 ? "#a59b79" : "#687469";
          drawPolygon(ctx, segmentBand(start, end, position, position + slatLength, 2.55 * scale), slatColor);
        }
      }
    }

    for (const junction of [{ col: 8, row: 1.78 }, { col: 8, row: 7.78 }]) {
      this.drawGroundPatch(junction.col, junction.row, 0.48, 0.48, "#8a7450");
      this.drawGroundPatch(junction.col, junction.row, 0.38, 0.38, PALETTE.conveyor);
    }
  }

  drawParcel(parcel) {
    const point = this.project(parcel.col, parcel.row);
    const scale = this.project.scale;
    const x = Math.round(point.x);
    const y = Math.round(point.y - 2.5 * scale);
    drawPixelShadow(this.ctx, x, y + 5 * scale, 8 * scale, 2 * scale);
    this.ctx.fillStyle = "#171e1c";
    this.ctx.fillRect(x - 3 * scale, y, 6 * scale, 5 * scale);
    this.ctx.fillStyle = PALETTE.parcel;
    this.ctx.fillRect(x - 3 * scale, y, 6 * scale, 1.2 * scale);
    this.ctx.fillStyle = parcel.color;
    this.ctx.fillRect(x - 2 * scale, y + 2 * scale, 4 * scale, 2 * scale);
  }

  drawHandoffToken(token) {
    const point = this.project(token.col, token.row);
    const scale = this.project.scale;
    const x = Math.round(point.x);
    const y = Math.round(point.y - 8 * scale);
    const color = {
      document: PALETTE.cyan,
      project: PALETTE.purple,
      ticket: PALETTE.amber,
      "green-pass": PALETTE.green,
    }[token.kind];
    drawPixelShadow(this.ctx, x, y + 9 * scale, 10 * scale, 2 * scale);
    this.ctx.fillStyle = "#101a1d";
    this.ctx.fillRect(x - 4 * scale, y - 2 * scale, 8 * scale, 8 * scale);
    this.ctx.fillStyle = color;
    this.ctx.fillRect(x - 3 * scale, y - 1 * scale, 6 * scale, 6 * scale);
    this.ctx.fillStyle = "#f2fbeb";
    if (token.kind === "document" || token.kind === "ticket") {
      this.ctx.fillRect(x - 2 * scale, y + 1 * scale, 4 * scale, scale);
      this.ctx.fillRect(x - 2 * scale, y + 3 * scale, 3 * scale, scale);
    } else if (token.kind === "project") {
      this.ctx.fillRect(x - 2 * scale, y + 1 * scale, 4 * scale, 3 * scale);
    } else {
      this.ctx.fillRect(x - 2 * scale, y + 2 * scale, 2 * scale, scale);
      this.ctx.fillRect(x, y + scale, 2 * scale, scale);
    }
  }

  drawStation(station, timestamp) {
    const ctx = this.ctx;
    const { x, y } = this.project(station.cell.col, station.cell.row);
    const room = ROOMS.find(item => item.id === station.room);
    const accent = PALETTE[room?.color || "coral"];
    const worker = station.workerStationId
      ? (this.snapshot?.workers || []).find(item => item.station_id === station.workerStationId)
      : null;
    const working = worker?.status === "working";
    const selected = this.selection?.type === "station" && this.selection.id === station.selectionId;
    const signal = working && Math.floor(timestamp / 450) % 2 === 0 ? PALETTE.green : accent;

    drawPixelShadow(ctx, x, y + 4, 16, 4);
    this.drawGroundPrism(station.cell.col, station.cell.row + 0.28, 25, 12, 6, "#817a60", "#4b4a3e", "#383a33");
    ctx.fillStyle = "#262b27";
    ctx.fillRect(x - 6, y - 10, 12, 8);
    ctx.fillStyle = "#8e8767";
    ctx.fillRect(x - 7, y - 11, 14, 2);
    ctx.fillStyle = "#233d39";
    ctx.fillRect(x - 4, y - 8, 8, 4);
    ctx.fillStyle = "#477d6d";
    ctx.fillRect(x - 3, y - 7, 4, 1);
    ctx.fillRect(x - 3, y - 5, 2, 1);
    ctx.fillStyle = "#172722";
    ctx.fillRect(x + 1, y - 6, 2, 2);
    ctx.fillStyle = "#b6a780";
    ctx.fillRect(x - 6, y - 9, 1, 1);
    ctx.fillRect(x + 5, y - 9, 1, 1);
    ctx.fillStyle = signal;
    ctx.fillRect(x - 2, y - 7, 4, 1);
    ctx.fillRect(x + 4, y - 9, 2, 2);
    ctx.fillStyle = "#d0bd91";
    ctx.fillRect(x - 10, y + 1, 3, 2);
    ctx.fillStyle = "#5b604d";
    ctx.fillRect(x - 6, y + 4, 12, 2);
    ctx.fillStyle = "#20251f";
    for (let key = 0; key < 5; key += 1) ctx.fillRect(x - 5 + key * 2, y + 4, 1, 1);
    ctx.fillStyle = "#383d32";
    ctx.fillRect(x + 12, y + 1, 1, 4);
    ctx.fillRect(x + 12, y + 4, 3, 1);
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
    ctx.fillText(station.label, x, y + 15, 35);
    ctx.textAlign = "left";
    if (selected) {
      ctx.strokeStyle = PALETTE.light;
      ctx.lineWidth = 1;
      const size = 13 * this.project.scale;
      ctx.strokeRect(x - size, y - 15 * this.project.scale, size * 2, size * 2);
    }
  }

  drawProp(prop) {
    const ctx = this.ctx;
    const point = this.project(prop.col, prop.row);
    drawPixelShadow(ctx, point.x, point.y + 2, 10, 3);
    if (prop.kind === "crate" || prop.kind === "toolbox" || prop.kind === "filebox") {
      const toolbox = prop.kind === "toolbox";
      const filebox = prop.kind === "filebox";
      this.drawGroundPrism(prop.col, prop.row + 0.12, 13, 10, toolbox ? 6 : 8,
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
      this.drawGroundPrism(prop.col, prop.row + 0.12, 13, 10, prop.kind === "shelf" ? 19 : 23,
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
      this.drawGroundPrism(prop.col, prop.row + 0.12, 11, 8, 5, "#6b634a", "#403d32", "#30332c");
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
      this.drawGroundPrism(prop.col, prop.row + 0.12, 12, 8, 9, "#606650", "#3c4239", "#2d342f");
      ctx.fillStyle = PALETTE.coral;
      ctx.fillRect(point.x - 2, point.y - 5, 2, 2);
      ctx.fillStyle = PALETTE.cyan;
      ctx.fillRect(point.x + 2, point.y - 5, 2, 2);
      return;
    }
    if (prop.kind === "cactus") {
      this.drawGroundPrism(prop.col, prop.row + 0.12, 9, 7, 5, "#936b4c", "#514234", "#36332a");
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
      const point = this.project(room.grid.col + room.grid.columns - 0.5, room.grid.row + room.grid.rows - 0.5);
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
    const pixelScale = this.project.scale * WORKER_DISPLAY_SCALE / 2;
    const width = sprite[0].length;
    const height = sprite.length;
    const point = this.project(actor.col, actor.row);
    const x = Math.round(point.x - width * pixelScale / 2);
    const y = Math.round(point.y - height * pixelScale);
    const screenWidth = width * pixelScale;
    const screenHeight = height * pixelScale;
    const designWidth = width / 2;
    actor.bounds = { x, y, width: screenWidth, height: screenHeight };
    const moving = Math.hypot(actor.targetCol - actor.col, actor.targetRow - actor.row) > 0.03;
    const working = actor.status === "working";
    const step = Math.floor(timestamp / 170) % 2;
    drawPixelShadow(this.ctx, point.x, point.y + 1, 12 * pixelScale, 3 * pixelScale);
    this.ctx.save();
    this.ctx.translate(x, y);
    this.ctx.scale(pixelScale, pixelScale);
    this.ctx.fillStyle = lighten(actor.color, 36);
    for (const [row, column] of appearance.outline) this.ctx.fillRect(column, row, 1, 1);
    for (let row = 0; row < sprite.length; row += 1) {
      for (let column = 0; column < sprite[row].length; column += 1) {
        const symbol = sprite[row][column];
        if (symbol === ".") continue;
        let color = SPRITE_COLORS[symbol];
        if (symbol === "A") color = actor.color;
        if (symbol === "a") color = lighten(actor.color, 26);
        if (moving && symbol === "K" && (column + step) % 2 === 0) continue;
        this.ctx.fillStyle = color;
        this.ctx.fillRect(column, row, 1, 1);
      }
    }
    this.ctx.scale(2, 2);
    this.drawWorkerGear(appearance.gear, 0, 0, designWidth, timestamp);
    if (working) {
      const blink = Math.floor(timestamp / 400) % 2 === 0;
      this.ctx.fillStyle = blink ? PALETTE.green : PALETTE.amber;
      this.ctx.fillRect(designWidth - 3, 21 + step, 3, 2);
      this.ctx.fillStyle = blink ? PALETTE.green : PALETTE.light;
      this.ctx.fillRect(designWidth / 2 + 8, -4, 3, 3);
    } else if (actor.status === "needs_review") {
      this.ctx.fillStyle = PALETTE.amber;
      this.ctx.fillRect(designWidth / 2 + 8, -4, 3, 3);
    }
    this.ctx.restore();
    if (this.selection?.type === "worker" && this.selection.id === actor.id) {
      this.ctx.strokeStyle = PALETTE.light;
      this.ctx.lineWidth = 1;
      this.ctx.strokeRect(x - 3.5, y - 3.5, screenWidth + 7, screenHeight + 7);
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
    if (this.suppressClick) {
      this.suppressClick = false;
      return;
    }
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
    const station = findStationAt(x, y, this.project);
    if (station) {
      this.selection = { type: "station", id: station.selectionId };
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
    this.canvas.style.cursor = actor ? "pointer" : "grab";
    this.onHover(this.hoveredWorker, this.hoverPosition);
  }

  clearHover() {
    this.hoveredWorker = null;
    this.hoverPosition = null;
    this.canvas.style.cursor = "grab";
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

function cellEdges(cell) {
  const { col, row } = cell;
  return [
    { start: { col: col - 0.5, row: row - 0.5 }, end: { col: col + 0.5, row: row - 0.5 }, neighbor: { col: 0, row: -1 }, normal: { col: 0, row: -1 } },
    { start: { col: col + 0.5, row: row - 0.5 }, end: { col: col + 0.5, row: row + 0.5 }, neighbor: { col: 1, row: 0 }, normal: { col: 1, row: 0 } },
    { start: { col: col + 0.5, row: row + 0.5 }, end: { col: col - 0.5, row: row + 0.5 }, neighbor: { col: 0, row: 1 }, normal: { col: 0, row: 1 } },
    { start: { col: col - 0.5, row: row + 0.5 }, end: { col: col - 0.5, row: row - 0.5 }, neighbor: { col: -1, row: 0 }, normal: { col: -1, row: 0 } },
  ];
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

function segmentBand(start, end, from, to, halfWidth) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const length = Math.hypot(dx, dy);
  if (!length) return [];
  const nx = -dy / length * halfWidth;
  const ny = dx / length * halfWidth;
  const first = { x: start.x + dx * from, y: start.y + dy * from };
  const second = { x: start.x + dx * to, y: start.y + dy * to };
  return [
    { x: first.x + nx, y: first.y + ny },
    { x: second.x + nx, y: second.y + ny },
    { x: second.x - nx, y: second.y - ny },
    { x: first.x - nx, y: first.y - ny },
  ];
}

function tracePolygon(ctx, points) {
  if (!points?.length) return;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let index = 1; index < points.length; index += 1) ctx.lineTo(points[index].x, points[index].y);
  ctx.closePath();
}

function drawPixelShadow(ctx, x, y, width, depth) {
  ctx.fillStyle = "rgba(0,0,0,.34)";
  for (let row = 0; row < depth; row += 1) {
    const inset = Math.abs(row - Math.floor(depth / 2));
    ctx.fillRect(Math.round(x - width / 2 + inset), Math.round(y + row), Math.max(1, width - inset * 2), 1);
  }
}

function taskPhase(taskId, timestamp, duration) {
  let hash = 0;
  for (const character of String(taskId)) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return ((Math.max(0, timestamp) + hash % duration) % duration) / duration;
}

function lighten(hex, amount) {
  const value = Number.parseInt(hex.slice(1), 16);
  const red = Math.max(0, Math.min(255, ((value >> 16) & 255) + amount));
  const green = Math.max(0, Math.min(255, ((value >> 8) & 255) + amount));
  const blue = Math.max(0, Math.min(255, (value & 255) + amount));
  return `rgb(${red}, ${green}, ${blue})`;
}

function formatCount(value) {
  return Number.isInteger(value) ? String(value).padStart(2, "0") : "—";
}
