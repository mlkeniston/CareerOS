import {
  CORRIDORS,
  LOGICAL_SIZE,
  PALETTE,
  ROOMS,
  SPRITE_COLORS,
  STATIONS,
  WORKER_APPEARANCE,
  WORKER_STATIONS,
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
    this.drawNebula();
    this.drawStars();
    this.drawCorridors();
    for (const room of ROOMS) this.drawRoom(room);
    this.drawDoorways();
    for (const station of STATIONS) this.drawStation(station, timestamp);
    this.drawRoomCounters();
    for (const actor of this.actors.values()) this.drawActor(actor, timestamp);
    this.drawOuterFrame();
  }

  drawNebula() {
    const gradient = this.ctx.createRadialGradient(86, 51, 8, 86, 51, 126);
    gradient.addColorStop(0, "rgba(112, 68, 221, .19)");
    gradient.addColorStop(0.55, "rgba(67, 48, 155, .12)");
    gradient.addColorStop(1, "rgba(26, 24, 74, 0)");
    this.ctx.fillStyle = gradient;
    this.ctx.fillRect(0, 0, 260, 225);
    const second = this.ctx.createRadialGradient(486, 260, 3, 486, 260, 130);
    second.addColorStop(0, "rgba(45, 151, 207, .14)");
    second.addColorStop(1, "rgba(20, 30, 76, 0)");
    this.ctx.fillStyle = second;
    this.ctx.fillRect(340, 170, 260, 168);
  }

  drawStars() {
    const ctx = this.ctx;
    for (let index = 0; index < 58; index += 1) {
      const x = (index * 83 + 19) % LOGICAL_SIZE.width;
      const y = (index * 47 + 13) % LOGICAL_SIZE.height;
      if (insideAnyRoom(x, y)) continue;
      ctx.fillStyle = index % 9 === 0 ? PALETTE.cyan : index % 7 === 0 ? PALETTE.purple : "#515274";
      ctx.fillRect(x, y, index % 11 === 0 ? 2 : 1, index % 11 === 0 ? 2 : 1);
    }
  }

  drawCorridors() {
    const ctx = this.ctx;
    for (const corridor of CORRIDORS) {
      ctx.fillStyle = "#151d29";
      ctx.fillRect(corridor.x, corridor.y, corridor.width, corridor.height);
      ctx.fillStyle = "#252f3d";
      for (let x = corridor.x; x < corridor.x + corridor.width; x += 8) {
        ctx.fillRect(x, corridor.y + 2, 1, corridor.height - 4);
      }
      ctx.fillStyle = "#0b111a";
      ctx.fillRect(corridor.x, corridor.y, corridor.width, 2);
      ctx.fillRect(corridor.x, corridor.y + corridor.height - 2, corridor.width, 2);
    }
  }

  drawRoom(room) {
    const ctx = this.ctx;
    const color = PALETTE[room.color];
    ctx.fillStyle = "rgba(0,0,0,.68)";
    ctx.fillRect(room.x + 3, room.y + 3, room.width, room.height);
    ctx.fillStyle = PALETTE.wall;
    ctx.fillRect(room.x, room.y, room.width, room.height);
    ctx.fillStyle = PALETTE.steel;
    ctx.fillRect(room.x + 2, room.y + 2, room.width - 4, room.height - 4);
    ctx.fillStyle = PALETTE.floor;
    ctx.fillRect(room.x + 5, room.y + 6, room.width - 10, room.height - 11);
    ctx.save();
    ctx.beginPath();
    ctx.rect(room.x + 5, room.y + 6, room.width - 10, room.height - 11);
    ctx.clip();
    ctx.strokeStyle = PALETTE.grid;
    ctx.lineWidth = 1;
    for (let x = room.x + 8; x < room.x + room.width; x += 8) {
      ctx.beginPath(); ctx.moveTo(x + 0.5, room.y + 6); ctx.lineTo(x + 0.5, room.y + room.height); ctx.stroke();
    }
    for (let y = room.y + 8; y < room.y + room.height; y += 8) {
      ctx.beginPath(); ctx.moveTo(room.x + 5, y + 0.5); ctx.lineTo(room.x + room.width, y + 0.5); ctx.stroke();
    }
    ctx.restore();
    ctx.fillStyle = color;
    ctx.fillRect(room.x + 6, room.y + 6, 3, 3);
    ctx.globalAlpha = 0.42;
    ctx.fillRect(room.x + 5, room.y + 2, room.width - 10, 2);
    ctx.globalAlpha = 1;
    ctx.fillRect(room.x + 5, room.y + 3, room.width - 10, 1);
    ctx.fillStyle = PALETTE.light;
    ctx.font = "bold 5px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textBaseline = "top";
    ctx.fillText(room.label, room.x + 12, room.y + 6);
    ctx.fillStyle = color;
    ctx.fillRect(room.x + room.width - 9, room.y + 7, 3, 3);
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.5;
    ctx.fillRect(room.x + 5, room.y + room.height - 2, room.width - 10, 1);
    ctx.globalAlpha = 1;
    ctx.fillStyle = "#9aa6b4";
    ctx.fillRect(room.x + 4, room.y + room.height - 5, room.width - 8, 1);
    if (room.id === "dispatch") this.drawDispatchConsole(room);
  }

  drawDispatchConsole(room) {
    const ctx = this.ctx;
    const active = (this.snapshot?.workers || []).some(worker => worker.status === "working");
    ctx.fillStyle = "#0b111a";
    ctx.fillRect(room.x + 8, room.y + 24, room.width - 16, 21);
    ctx.fillStyle = "#273545";
    ctx.fillRect(room.x + 11, room.y + 27, room.width - 22, 13);
    ctx.fillStyle = active ? PALETTE.green : PALETTE.amber;
    ctx.fillRect(room.x + 14, room.y + 30, 3, 3);
    ctx.fillStyle = "#d0d9e1";
    ctx.font = "4px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.fillText(active ? "QUEUE ACTIVE" : "QUEUE READY", room.x + 19, room.y + 30);
  }

  drawDoorways() {
    const ctx = this.ctx;
    for (const room of ROOMS) {
      if (room.id === "dispatch") continue;
      const x = Math.floor(room.x + room.width / 2 - 7);
      const y = room.y < LOGICAL_SIZE.height / 2 ? room.y + room.height - 5 : room.y - 1;
      ctx.fillStyle = PALETTE.floor;
      ctx.fillRect(x, y, 14, 7);
      for (let stripe = 0; stripe < 4; stripe += 1) {
        ctx.fillStyle = stripe % 2 === 0 ? "#c68e46" : "#242a34";
        ctx.fillRect(x + stripe * 4, y, 2, 2);
        ctx.fillRect(x + stripe * 4, y + 5, 2, 2);
      }
    }
  }

  drawStation(station, timestamp) {
    const ctx = this.ctx;
    const room = ROOMS.find(item => item.id === station.room);
    const color = PALETTE[room?.color || "coral"];
    const selected = this.selection?.type === "station" && this.selection.id === station.id;
    const worker = (this.snapshot?.workers || []).find(item => item.station_id === stationIdForRoom(station.room));
    const isWorking = worker?.status === "working";
    const blink = isWorking && Math.floor(timestamp / 450) % 2 === 0;
    ctx.fillStyle = selected ? "#30275d" : "#242442";
    ctx.fillRect(station.x, station.y + 17, station.width, 9);
    ctx.fillStyle = "#101720";
    ctx.fillRect(station.x + 3, station.y + 2, Math.min(20, station.width - 7), 14);
    ctx.fillStyle = "#152447";
    ctx.fillRect(station.x + 5, station.y + 4, Math.min(16, station.width - 11), 9);
    ctx.fillStyle = blink ? PALETTE.green : color;
    ctx.fillRect(station.x + station.width - 6, station.y + 3, 2, 2);
    ctx.fillStyle = "#070b11";
    ctx.fillRect(station.x + 8, station.y + 16, 1, 2);
    ctx.fillRect(station.x + station.width - 9, station.y + 16, 1, 2);
    ctx.fillStyle = "#b0bdca";
    ctx.font = "3.7px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.textBaseline = "top";
    ctx.fillText(station.label, station.x + 1, station.y + 27, station.width - 2);
    if (selected) {
      ctx.strokeStyle = PALETTE.light;
      ctx.lineWidth = 1;
      ctx.strokeRect(station.x - 1.5, station.y - 1.5, station.width + 3, station.height + 2);
    }
  }

  drawRoomCounters() {
    const counts = this.snapshot?.counts || {};
    const ctx = this.ctx;
    const counters = {
      jobs: [`ROLES ${formatCount(counts.jobs_found)}`, `MATCH ${formatCount(counts.jobs_matched)}`],
      resume: [`DRAFT ${formatCount(counts.drafts_to_review)}`],
      applications: [`DRAFT ${formatCount(counts.drafts_to_review)}`],
      portfolio: [`REVIEW ${formatCount(counts.proposals_to_review)}`, `DONE ${formatCount(counts.tasks_shipped)}`],
      dispatch: [],
      outreach: [`REVIEW ${formatCount(counts.outreach_to_review)}`],
    };
    for (const room of ROOMS) {
      const entries = counters[room.id] || [];
      ctx.font = "4.5px ui-monospace, SFMono-Regular, Menlo, monospace";
      ctx.textBaseline = "top";
      ctx.textAlign = "right";
      ctx.fillStyle = PALETTE[room.color];
      entries.forEach((value, index) => ctx.fillText(value, room.x + room.width - 7, room.y + 7 + index * 6));
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
    for (let row = 0; row < sprite.length; row += 1) {
      for (let column = 0; column < sprite[row].length; column += 1) {
        const symbol = sprite[row][column];
        if (symbol === ".") continue;
        let color = SPRITE_COLORS[symbol];
        if (symbol === "T") color = actor.color;
        if (moving && row === sprite.length - 1 && (column + Math.floor(timestamp / 150)) % 2 === 0) continue;
        this.ctx.fillStyle = color;
        this.ctx.fillRect(x + column * scale, y + row * scale, scale, scale);
      }
    }
    if (working) {
      const blink = Math.floor(timestamp / 400) % 2 === 0;
      this.ctx.fillStyle = blink ? PALETTE.green : PALETTE.light;
      this.ctx.fillRect(Math.round(actor.x + 5), Math.round(y - 4), 2, 2);
    } else if (actor.status === "needs_review") {
      this.ctx.fillStyle = PALETTE.amber;
      this.ctx.fillRect(Math.round(actor.x + 5), Math.round(y - 4), 2, 2);
    }
    if (this.selection?.type === "worker" && this.selection.id === actor.id) {
      this.ctx.strokeStyle = PALETTE.light;
      this.ctx.lineWidth = 1;
      this.ctx.strokeRect(x - 2.5, y - 2.5, width + 5, height + 5);
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
    const station = STATIONS.find(item => x >= item.x - 2 && x <= item.x + item.width + 2 && y >= item.y - 2 && y <= item.y + item.height + 2);
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

function insideAnyRoom(x, y) {
  return ROOMS.some(room => x >= room.x && x <= room.x + room.width && y >= room.y && y <= room.y + room.height)
    || CORRIDORS.some(corridor => x >= corridor.x && x <= corridor.x + corridor.width && y >= corridor.y && y <= corridor.y + corridor.height);
}

function stationIdForRoom(roomId) {
  return {
    jobs: "job-hunters-01",
    resume: "resume-team-01",
    applications: "application-team-01",
    portfolio: "engineering-team-01",
    dispatch: "dispatch-01",
    outreach: "outreach-team-01",
  }[roomId];
}

function formatCount(value) {
  return Number.isInteger(value) ? String(value).padStart(2, "0") : "—";
}
