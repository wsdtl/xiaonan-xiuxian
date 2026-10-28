const root = document.getElementById("reportRoot");
const initialMode = new URLSearchParams(location.search).get("mode") === "animation" ? "animation" : "text";
const state = { mode: initialMode, payload: null, playing: false, speed: 1, t: 0, duration: 1, frame: 0, last: 0, cursor: 0, units: new Map(), formations: new Map(), env: null, floatStacks: new Map() };
const RESULT = { left: "左方胜", right: "右方胜", draw: "未分胜负" };
const RES_LABEL = { health: "血气", soul: "神魂", spirit: "精神", shield: "护盾" };
const TYPE_LABEL = { attack: "单体", aoe: "群攻", combo: "连击", drain: "吸取", heal: "治疗", shield: "护盾", buff: "增益", debuff: "减益", control: "控制", item: "丹药", other: "其他" };

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function num(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "0";
  const rounded = Math.round(n * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}
function sec(value) { return (Number(value || 0) / 1000).toFixed(1) + "s"; }
function ratio(value) {
  const n = Number(value) || 0;
  return Math.max(0, Math.min(100, n <= 1 ? n * 100 : n));
}
function unitById(id) { return state.payload.units.find(function (u) { return u.id === id; }); }
function formationById(id) { return state.payload.formations.find(function (f) { return f.id === id; }); }
function unitName(id) {
  const u = unitById(id);
  return u ? u.name : id;
}
function formationName(id) {
  const f = formationById(id);
  return f ? f.name : id;
}
function targetName(id) {
  if (id === "environment") return "环境";
  if (id && id.indexOf("formation:") === 0) return formationName(id);
  return unitName(id);
}
function resourceLabel(key) { return RES_LABEL[key] || key; }

function showLoadError(error) {
  root.textContent = "";
  const box = el("section", "error-state");
  box.appendChild(el("p", "", "战报读取失败：" + error.message));
  box.appendChild(el("p", "", "请返回上一页重试。"));
  root.appendChild(box);
}

function mountPayload(payload) {
  if (!payload || payload.schema !== "game.battle_animation" || payload.version !== 1) {
    throw new Error("战报数据版本不匹配");
  }
  state.payload = payload;
  state.duration = Math.max(1000, Number(payload.battle.duration) || 1000);
  renderShell();
  if (new URLSearchParams(location.search).get("play") === "1") {
    setTimeout(function () { if (!state.playing) playLoop(); }, 120);
  }
  const seekValue = Number(new URLSearchParams(location.search).get("seek"));
  if (Number.isFinite(seekValue) && seekValue > 0) {
    setTimeout(function () { seek(seekValue); }, 180);
  }
}

async function boot() {
  if (window.__BATTLE_ANIMATION__) {
    try { mountPayload(window.__BATTLE_ANIMATION__); } catch (error) { showLoadError(error); }
    return;
  }
  try {
    const base = location.pathname.replace(/\/+$/, "");
    const response = await fetch(base + "/data?view=animation", { cache: "no-store", headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("HTTP " + response.status);
    mountPayload(await response.json());
  } catch (error) {
    showLoadError(error);
  }
}

function renderShell() {
  root.textContent = "";
  root.setAttribute("aria-busy", "false");
  const header = el("header", "report-header");
  const title = el("div", "report-title");
  title.appendChild(el("h1", "", state.payload.battle.title || "战斗记录"));
  const sub = el("p", "report-sub");
  sub.appendChild(el("span", "", "场景 "));
  sub.lastChild.appendChild(el("b", "", state.payload.battle.scene || "未知"));
  sub.appendChild(el("span", "", "结果 "));
  sub.lastChild.appendChild(el("b", "", RESULT[state.payload.battle.result] || "未分胜负"));
  sub.appendChild(el("span", "", "行动 "));
  sub.lastChild.appendChild(el("b", "", String(state.payload.battle.actions || 0)));
  title.appendChild(sub);
  header.appendChild(title);
  const modes = el("div", "mode-switch");
  [["text", "文本"], ["animation", "动画"]].forEach(function (row) {
    const button = el("button", "", row[1]);
    button.type = "button";
    button.setAttribute("aria-pressed", String(state.mode === row[0]));
    button.addEventListener("click", function () { setMode(row[0]); });
    modes.appendChild(button);
  });
  header.appendChild(modes);
  root.appendChild(header);
  const main = el("main", "report-main");
  main.id = "reportMain";
  root.appendChild(main);
  renderMode();
}

function setMode(mode) {
  if (state.mode === mode) return;
  state.mode = mode;
  const buttons = root.querySelectorAll(".mode-switch button");
  buttons.forEach(function (button, index) {
    button.setAttribute("aria-pressed", String((index === 0 ? "text" : "animation") === mode));
  });
  renderMode();
}

function renderMode() {
  const main = document.getElementById("reportMain");
  if (!main) return;
  main.textContent = "";
  if (state.mode === "text") {
    state.playing = false;
    main.appendChild(renderText());
  } else {
    main.appendChild(renderAnimation());
  }
}

function renderText() {
  const wrap = el("section", "text-report");
  if (!state.payload.events.length) {
    wrap.appendChild(el("p", "text-empty", "这场战斗没有留下可读事件。"));
    return wrap;
  }
  let lastTurn = null;
  state.payload.events.forEach(function (event) {
    if (event.turn !== lastTurn) {
      lastTurn = event.turn;
      wrap.appendChild(el("h2", "text-turn", event.turn ? "第 " + event.turn + " 回合" : "开场"));
    }
    const line = el("div", "text-line");
    line.appendChild(el("span", "text-time", sec(event.t)));
    const body = el("div", "text-body");
    body.appendChild(formatText(event));
    line.appendChild(body);
    wrap.appendChild(line);
  });
  return wrap;
}

function formatText(event) {
  const frag = document.createDocumentFragment();
  function add(text, cls) {
    const span = el("span", cls || "", text);
    frag.appendChild(span);
  }
  function bold(text) { add(text, "gold"); }
  if (event.type === "battle_start") { bold("战斗开始"); return frag; }
  if (event.type === "battle_end") { bold("战斗结束 · " + (RESULT[event.winner] || "未分胜负")); return frag; }
  if (event.type === "action") {
    bold(unitName(event.actor));
    add(" 施放 ");
    bold(event.skill || "普通攻击");
    add("（" + (TYPE_LABEL[event.animation] || "其他") + "）");
    if (event.targets && event.targets.length) add(" → " + event.targets.map(targetName).join("、"), "muted");
    return frag;
  }
  if (event.type === "damage") {
    bold(unitName(event.source));
    add(" 对 ");
    bold(targetName(event.target));
    add(" 造成 ");
    add(num(event.value) + " 点" + resourceLabel(event.resource) + "伤害", event.resource === "soul" ? "soul" : "dmg");
    if (event.shield_absorbed) add("（护盾吸收 " + num(event.shield_absorbed) + "）", "muted");
    if (event.crit) add(" 暴击", "dmg");
    if (event.blocked) add(" 格挡", "muted");
    return frag;
  }
  if (event.type === "heal") {
    bold(targetName(event.target));
    add(" 恢复 " + num(event.value) + " 点" + resourceLabel(event.resource), "heal");
    return frag;
  }
  if (event.type === "shield") {
    bold(targetName(event.target));
    add(" 获得 " + num(event.value) + " 点护盾", "heal");
    return frag;
  }
  if (event.type === "resource") {
    bold(targetName(event.target));
    add(" " + resourceLabel(event.resource) + " 变化 " + num(event.delta), "muted");
    return frag;
  }
  if (event.type === "status_add") {
    bold(targetName(event.target));
    add(" 获得状态 ");
    bold(event.name);
    add(" ×" + event.stacks, "muted");
    return frag;
  }
  if (event.type === "status_remove") {
    bold(targetName(event.target));
    add(" 失去状态 ");
    bold(event.name);
    return frag;
  }
  if (event.type === "status_stack") {
    bold(targetName(event.target));
    add(" 状态 ");
    bold(event.name);
    add(" 变为 " + event.stacks + " 层", "muted");
    return frag;
  }
  if (event.type === "miss") {
    bold(unitName(event.source));
    add(" 的攻击被 ");
    bold(targetName(event.target));
    add(" 闪避", "muted");
    return frag;
  }
  if (event.type === "unit_down") {
    bold(targetName(event.target));
    add(" 倒下", "dmg");
    return frag;
  }
  if (event.type === "revive") {
    bold(targetName(event.target));
    add(" 复苏", "heal");
    return frag;
  }
  if (event.type === "formation_cast") { bold("阵法「" + formationName(event.formation) + "」展开"); return frag; }
  if (event.type === "formation_turn") { bold("阵法「" + formationName(event.formation) + "」轮转"); return frag; }
  if (event.type === "formation_impact") {
    bold("阵法「" + formationName(event.source) + "」冲击 ");
    bold(targetName(event.target));
    add("，承载/伤害 " + num(event.value), "dmg");
    return frag;
  }
  if (event.type === "formation_break") { bold("阵法「" + formationName(event.formation) + "」崩解", "dmg"); return frag; }
  if (event.type === "environment_charge") {
    bold("环境承伤 " + num(event.value));
    add("，累计 " + num(event.accumulated) + "（" + num(ratio(event.ratio)) + "%）", "muted");
    return frag;
  }
  if (event.type === "environment_stage") {
    bold("环境变化 " + (event.from || "?") + " → " + (event.to || "?"));
    add("，承伤 " + num(event.damage_ratio) + "%", "muted");
    return frag;
  }
  add(event.type, "muted");
  return frag;
}

function renderAnimation() {
  const wrap = el("section", "animation");
  const stage = el("div", "battle-stage");
  stage.id = "battleStage";
  const env = el("div", "env-layer");
  env.id = "envLayer";
  const envLine = el("div", "env-line");
  envLine.appendChild(el("span", "env-name", state.payload.environment ? state.payload.environment.name : "无环境"));
  const envBar = el("div", "env-bar");
  envBar.appendChild(el("i"));
  envLine.appendChild(envBar);
  envLine.appendChild(el("span", "env-stage", state.payload.environment ? state.payload.environment.stage : ""));
  env.appendChild(envLine);
  stage.appendChild(env);

  const grid = el("div", "battle-grid");
  const left = el("div", "side-column left");
  const right = el("div", "side-column right");
  left.appendChild(el("div", "side-title", "左方"));
  right.appendChild(el("div", "side-title", "右方"));
  const center = el("div", "center-column");
  center.appendChild(el("div", "turn-badge", "0"));
  center.appendChild(el("div", "center-hint", "回合"));
  grid.appendChild(left);
  grid.appendChild(center);
  grid.appendChild(right);
  stage.appendChild(grid);

  const rays = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  rays.setAttribute("class", "ray-layer");
  rays.setAttribute("id", "rayLayer");
  rays.setAttribute("aria-hidden", "true");
  stage.appendChild(rays);
  const fx = el("div", "fx-layer");
  fx.id = "fxLayer";
  stage.appendChild(fx);
  const banners = el("div", "banner-layer");
  banners.id = "bannerLayer";
  stage.appendChild(banners);
  wrap.appendChild(stage);

  const controls = el("div", "control-bar");
  const play = el("button", "", "播放");
  play.id = "playButton";
  play.type = "button";
  const reset = el("button", "", "重播");
  reset.type = "button";
  const speedGroup = el("div", "speed-group");
  [1, 2, 3, 4, 16].forEach(function (value) {
    const button = el("button", "", value + "x");
    button.type = "button";
    button.setAttribute("aria-pressed", String(state.speed === value));
    button.addEventListener("click", function () {
      state.speed = value;
      speedGroup.querySelectorAll("button").forEach(function (item) { item.setAttribute("aria-pressed", String(item.textContent === value + "x")); });
    });
    speedGroup.appendChild(button);
  });
  const progress = el("div", "progress");
  progress.id = "progress";
  const fill = el("i");
  progress.appendChild(fill);
  const clock = el("span", "control-time", "0.0 / " + sec(state.duration));
  controls.appendChild(play);
  controls.appendChild(reset);
  controls.appendChild(el("div", "spacer"));
  controls.appendChild(speedGroup);
  controls.appendChild(progress);
  controls.appendChild(clock);
  wrap.appendChild(controls);

  state.ui = { stage: stage, left: left, right: right, centerBadge: center.querySelector(".turn-badge"), envBar: envBar.querySelector("i"), envStage: envLine.querySelector(".env-stage"), fill: fill, clock: clock, play: play, rayLayer: rays };
  buildUnits();
  resetVisual();
  updateControls();
  play.addEventListener("click", function () { state.playing ? pause() : playLoop(); });
  reset.addEventListener("click", function () { resetVisual(); state.t = 0; state.cursor = 0; updateControls(); });
  progress.addEventListener("click", function (event) {
    const rect = progress.getBoundingClientRect();
    const ratioValue = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    seek(ratioValue * state.duration);
  });
  return wrap;
}

function buildUnits() {
  if (!state.ui) return;
  state.ui.left.querySelectorAll(".unit-card, .formation-card, .unit-grid").forEach(function (n) { n.remove(); });
  state.ui.right.querySelectorAll(".unit-card, .formation-card, .unit-grid").forEach(function (n) { n.remove(); });
  const ownedFormations = new Map();
  state.payload.formations.forEach(function (formation) {
    if (formation.owner_group) ownedFormations.set(formation.owner_group, formation);
  });
  state.payload.formations.forEach(function (formation) {
    if (formation.owner_group) return;
    const card = el("div", "formation-card");
    card.dataset.formation = formation.id;
    const head = el("div", "formation-head");
    head.appendChild(el("span", "formation-name", formation.name));
    head.appendChild(el("span", "", num(formation.start_capacity)));
    card.appendChild(head);
    const bar = el("div", "formation-bar");
    bar.appendChild(el("i"));
    card.appendChild(bar);
    const column = formation.side === "left" ? state.ui.left : state.ui.right;
    column.appendChild(card);
  });
  const grids = { left: el("div", "unit-grid"), right: el("div", "unit-grid") };
  state.ui.left.appendChild(grids.left);
  state.ui.right.appendChild(grids.right);
  const groups = [];
  const groupMap = new Map();
  state.payload.units.forEach(function (unit) {
    const key = unit.qq || unit.id;
    let group = groupMap.get(key);
    if (!group) {
      group = { side: unit.side, units: [] };
      groupMap.set(key, group);
      groups.push(group);
    }
    group.units.push(unit);
  });
  ["left", "right"].forEach(function (side) {
    const sideGroups = groups.filter(function (group) { return group.side === side; });
    let counts = splitRows(sideGroups.length);
    if (side === "right") counts = counts.slice().reverse();
    let cursor = 0;
    counts.forEach(function (count) {
      const row = el("div", "unit-row " + side);
      sideGroups.slice(cursor, cursor + count).forEach(function (group) {
        const slot = el("div", "unit-slot");
        const pair = el("div", "unit-pair");
        group.units.sort(function (a, b) {
          return (a.kind === "player" ? 0 : 1) - (b.kind === "player" ? 0 : 1);
        });
        group.units.forEach(function (unit) { pair.appendChild(makeUnitCard(unit)); });
        slot.appendChild(pair);
        const formation = ownedFormations.get(group.units[0].group);
        if (formation) slot.appendChild(makeFormationNode(formation));
        row.appendChild(slot);
      });
      cursor += count;
      grids[side].appendChild(row);
    });
  });
}

function splitRows(count) {
  if (count <= 0) return [];
  if (count <= 6) return [count];
  if (count <= 10) return [Math.ceil(count / 2), Math.floor(count / 2)];
  const base = Math.floor(count / 4);
  const remainder = count % 4;
  return [base + (remainder > 0 ? 1 : 0), base + (remainder > 1 ? 1 : 0), base + (remainder > 2 ? 1 : 0), base];
}

function makeFormationNode(formation) {
  const formationNode = el("div", "unit-formation");
  formationNode.dataset.formation = formation.id;
  formationNode.appendChild(el("span", "unit-formation-name", formation.name));
  const formationBar = el("div", "formation-bar");
  formationBar.appendChild(el("i"));
  formationNode.appendChild(formationBar);
  return formationNode;
}

function makeUnitCard(unit) {
  const card = el("div", "unit-card " + unit.side);
  card.dataset.unit = unit.id;
  const bars = el("div", "unit-bars");
  ["health", "soul", "spirit", "shield"].forEach(function (resource) {
    const bar = el("div", "bar " + resource);
    bar.dataset.resource = resource;
    bar.appendChild(el("i"));
    bars.appendChild(bar);
  });
  card.appendChild(bars);
  const avatar = el("div", "avatar " + (unit.kind || "other"));
  avatar.appendChild(el("span", "avatar-fallback", unit.avatar_text || "?"));
  if (unit.kind === "player" && unit.qq) {
    const image = document.createElement("img");
    image.className = "avatar-image";
    image.alt = "";
    image.loading = "lazy";
    image.decoding = "async";
    image.referrerPolicy = "no-referrer";
    image.addEventListener("load", function () { avatar.classList.add("has-image"); });
    image.addEventListener("error", function () { image.remove(); avatar.classList.remove("has-image"); });
    image.src = "https://q.qlogo.cn/g?b=qq&nk=" + encodeURIComponent(unit.qq) + "&s=100";
    avatar.appendChild(image);
  }
  card.appendChild(avatar);
  card.appendChild(el("div", "unit-name", unit.name));
  card.appendChild(el("div", "unit-cast", ""));
  const statuses = el("div", "unit-statuses");
  card.appendChild(statuses);
  return card;
}

function resetVisual() {
  if (!state.ui) return;
  state.floatStacks.clear();
  const fx = state.ui.stage.querySelector(".fx-layer");
  if (fx) fx.textContent = "";
  state.units.clear();
  state.formations.clear();
  state.payload.units.forEach(function (unit) {
    state.units.set(unit.id, { health: unit.start.health, soul: unit.start.soul, spirit: unit.start.spirit, shield: unit.start.shield, statuses: (unit.statuses || []).map(function (s) { return Object.assign({}, s); }), dead: false });
  });
  state.payload.formations.forEach(function (formation) {
    state.formations.set(formation.id, { capacity: formation.start_capacity, start: formation.start_capacity, broken: false });
    const card = state.ui.stage.querySelector('[data-formation="' + formation.id + '"]');
    if (card) {
      card.classList.remove("broken");
      const fill = card.querySelector(".formation-bar i");
      if (fill) fill.style.width = (formation.start_capacity > 0 ? 100 : 0) + "%";
      const value = card.querySelector(".formation-head span:last-child");
      if (value) value.textContent = num(formation.start_capacity);
    }
  });
  state.units.forEach(function (value, id) { paintUnit(id); });
  const env = state.payload.environment;
  if (state.ui.envBar) state.ui.envBar.style.width = env ? ratio(env.initial_damage_ratio || 0) + "%" : "0%";
  if (state.ui.envStage) state.ui.envStage.textContent = env ? (env.initial_stage || env.stage) : "";
  if (state.ui.centerBadge) state.ui.centerBadge.textContent = "0";
}

function paintUnit(id) {
  const unit = unitById(id);
  const value = state.units.get(id);
  const card = state.ui.stage.querySelector('[data-unit="' + id + '"]');
  if (!unit || !value || !card) return;
  card.classList.toggle("dead", value.dead);
  ["health", "soul", "spirit", "shield"].forEach(function (resource) {
    const row = card.querySelector(".bar." + resource);
    if (!row) return;
    const maximum = Math.max(0, Number(unit.max[resource]) || 0);
    const current = Math.max(0, Number(value[resource]) || 0);
    row.querySelector("i").style.width = (maximum > 0 ? Math.min(100, current / maximum * 100) : 0) + "%";
    row.title = RES_LABEL[resource] + " " + num(current) + "/" + num(maximum);
  });
  const holder = card.querySelector(".unit-statuses");
  if (holder) {
    holder.textContent = "";
    value.statuses.slice(0, 4).forEach(function (status) {
      holder.appendChild(el("span", "status-chip " + status.category, status.name + (status.stacks > 1 ? "×" + status.stacks : "")));
    });
    if (value.statuses.length > 4) holder.appendChild(el("span", "status-chip", "+" + (value.statuses.length - 4)));
  }
}

function setResource(id, resource, value) {
  const unit = state.units.get(id);
  if (!unit) return;
  unit[resource] = Math.max(0, Number(value) || 0);
  if (resource === "health" && unit.health <= 0) unit.dead = true;
  paintUnit(id);
}

function floatOn(target, text, kind) {
  if (!state.ui || !target) return;
  const stageRect = state.ui.stage.getBoundingClientRect();
  const rect = target.getBoundingClientRect();
  const key = target.dataset.unit || target.dataset.formation || "environment";
  const active = state.floatStacks.get(key) || [];
  const lane = active.length % 8;
  const node = el("div", "float-text " + (kind || ""));
  node.textContent = text;
  node.style.left = (rect.left - stageRect.left + rect.width / 2 + (lane % 2 ? 14 : -14)) + "px";
  node.style.top = (rect.top - stageRect.top + 18 - lane * 19) + "px";
  state.ui.stage.querySelector(".fx-layer").appendChild(node);
  active.push(node);
  state.floatStacks.set(key, active);
  setTimeout(function () {
    node.remove();
    state.floatStacks.set(key, (state.floatStacks.get(key) || []).filter(function (item) { return item !== node; }));
  }, 1500);
}

function rayElement(id) {
  if (!id || id === "system") return null;
  if (id === "environment") return state.ui.stage.querySelector(".env-layer");
  if (id.indexOf("formation:") === 0) return state.ui.stage.querySelector('[data-formation="' + id + '"]');
  return state.ui.stage.querySelector('[data-unit="' + id + '"]');
}

function showCast(id, text) {
  if (!state.ui) return;
  state.ui.stage.querySelectorAll(".unit-cast").forEach(function (node) { node.textContent = ""; node.parentElement.classList.remove("casting"); });
  const card = state.ui.stage.querySelector('[data-unit="' + id + '"]');
  if (!card) return;
  const label = card.querySelector(".unit-cast");
  if (!label) return;
  label.textContent = text;
  card.classList.add("casting");
  setTimeout(function () { label.textContent = ""; card.classList.remove("casting"); }, 2400);
}

function flashTarget(id, kind) {
  const node = rayElement(id);
  if (!node) return;
  const cls = "effect-" + (kind || "other");
  node.classList.remove(cls);
  void node.offsetWidth;
  node.classList.add(cls);
  setTimeout(function () { node.classList.remove(cls); }, 620);
}

function drawRay(source, target, kind) {
  if (!state.ui || !state.ui.rayLayer) return;
  const from = rayElement(source);
  const to = rayElement(target);
  if (!from || !to || from === to) return;
  const stageRect = state.ui.stage.getBoundingClientRect();
  const a = from.getBoundingClientRect();
  const b = to.getBoundingClientRect();
  state.ui.rayLayer.setAttribute("viewBox", "0 0 " + stageRect.width + " " + stageRect.height);
  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.setAttribute("x1", String(a.left - stageRect.left + a.width / 2));
  line.setAttribute("y1", String(a.top - stageRect.top + a.height / 2));
  line.setAttribute("x2", String(b.left - stageRect.left + b.width / 2));
  line.setAttribute("y2", String(b.top - stageRect.top + b.height / 2));
  line.setAttribute("class", "ray " + (kind || "damage"));
  state.ui.rayLayer.appendChild(line);
  setTimeout(function () { line.remove(); }, 720);
}

function showBanner(text, kind) {
  if (!state.ui) return;
  const layer = state.ui.stage.querySelector(".banner-layer");
  const node = el("div", "banner " + (kind || ""));
  node.textContent = text;
  layer.appendChild(node);
  setTimeout(function () { node.remove(); }, 1400);
}

function applyEvent(event, silent) {
  if (!state.ui) return;
  if (event.type === "action") {
    const card = state.ui.stage.querySelector('[data-unit="' + event.actor + '"]');
    state.ui.stage.querySelectorAll(".unit-card").forEach(function (n) { n.classList.remove("active"); });
    if (card) card.classList.add("active");
    if (!silent) {
      (event.targets || []).forEach(function (target) { flashTarget(target, event.animation); });
      showCast(event.actor, event.skill || "行动");
    }
    if (state.ui.centerBadge) state.ui.centerBadge.textContent = String(event.turn || 0);
    return;
  }
  if (event.type === "damage") {
    const target = event.target;
    drawRay(event.source, event.target, event.resource === "soul" ? "soul" : "damage");
    if (event.shield_absorbed) {
      const unit = state.units.get(target);
      if (unit) setResource(target, "shield", unit.shield - Number(event.shield_absorbed || 0));
    }
    const unit = state.units.get(target);
    if (!unit) return;
    const after = Number.isFinite(Number(event.after)) ? Number(event.after) : unit[event.resource] - Number(event.value || 0);
    setResource(target, event.resource || "health", after);
    const card = state.ui.stage.querySelector('[data-unit="' + target + '"]');
    if (card) {
      card.classList.remove("hurt");
      void card.offsetWidth;
      card.classList.add("hurt");
    }
    if (!silent) floatOn(card, "-" + num(event.value), event.crit ? "crit" : (event.resource === "soul" ? "soul" : "dmg"));
    return;
  }
  if (event.type === "heal" || event.type === "shield" || event.type === "revive") {
    drawRay(event.source, event.target, event.type === "shield" ? "shield" : "heal");
    const unit = state.units.get(event.target);
    if (!unit) return;
    const resource = event.type === "shield" ? "shield" : (event.resource || "health");
    const after = Number.isFinite(Number(event.after)) ? Number(event.after) : unit[resource] + Number(event.value || 0);
    setResource(event.target, resource, after);
    if (event.type === "revive") {
      unit.dead = false;
      if (state.ui) {
        const card = state.ui.stage.querySelector('[data-unit="' + event.target + '"]');
        if (card) card.classList.remove("dead");
      }
    }
    const card = state.ui.stage.querySelector('[data-unit="' + event.target + '"]');
    if (!silent) floatOn(card, "+" + num(event.value), resource === "shield" ? "shield" : "heal");
    return;
  }
  if (event.type === "status_add" || event.type === "status_remove" || event.type === "status_stack") {
    if (event.type === "status_add") drawRay(event.source, event.target, "status");
    const unit = state.units.get(event.target);
    if (!unit) return;
    if (event.type === "status_add") {
      const existing = unit.statuses.find(function (s) { return s.name === event.name; });
      if (existing) existing.stacks = event.stacks;
      else unit.statuses.push({ name: event.name, category: event.category, stacks: event.stacks, duration: event.duration });
    } else if (event.type === "status_remove") {
      unit.statuses = unit.statuses.filter(function (s) { return s.name !== event.name; });
    } else {
      const existing = unit.statuses.find(function (s) { return s.name === event.name; });
      if (existing) existing.stacks = event.stacks;
    }
    paintUnit(event.target);
    if (!silent) {
      const card = state.ui.stage.querySelector('[data-unit="' + event.target + '"]');
      floatOn(card, event.name + (event.type === "status_remove" ? " 消散" : ""), "status");
    }
    return;
  }
  if (event.type === "unit_down") {
    const unit = state.units.get(event.target);
    if (unit) unit.dead = true;
    paintUnit(event.target);
    const card = state.ui.stage.querySelector('[data-unit="' + event.target + '"]');
    if (!silent) floatOn(card, "倒下", "down");
    return;
  }
  if (event.type === "formation_cast" || event.type === "formation_turn" || event.type === "formation_break") {
    const card = state.ui.stage.querySelector('[data-formation="' + event.formation + '"]');
    if (event.type === "formation_break") {
      const value = state.formations.get(event.formation);
      if (value) { value.capacity = 0; value.broken = true; }
      if (card) {
        card.classList.add("broken");
        const fill = card.querySelector(".formation-bar i");
        if (fill) fill.style.width = "0%";
        const valueNode = card.querySelector(".formation-head span:last-child");
        if (valueNode) valueNode.textContent = "0";
      }
    } else if (event.type === "formation_cast") {
      if (card) card.classList.remove("broken");
    }
    if (!silent) {
      const label = event.type === "formation_break" ? "阵破" : (event.type === "formation_turn" ? "阵转" : "阵起");
      floatOn(card, label, event.type === "formation_break" ? "dmg" : "shield");
    }
    return;
  }
  if (event.type === "formation_impact") {
    drawRay(event.source, event.target, "formation");
    const value = state.formations.get(event.target);
    if (value) {
      value.capacity = Math.max(0, Number(event.after) || value.capacity - Number(event.value || 0));
      if (value.capacity <= 0) value.broken = true;
      const card = state.ui.stage.querySelector('[data-formation="' + event.target + '"]');
      if (card) {
        const fill = card.querySelector(".formation-bar i");
        if (fill) fill.style.width = (Math.max(0, value.capacity) / Math.max(1, Number(value.start) || 1) * 100) + "%";
        const valueNode = card.querySelector(".formation-head span:last-child");
        if (valueNode) valueNode.textContent = num(value.capacity);
        if (!silent) floatOn(card, "-" + num(event.value), "dmg");
      }
    } else if (event.target) {
      applyEvent({ type: "damage", target: event.target, resource: event.resource || "health", value: event.value, before: event.before, after: event.after, shield_absorbed: 0 }, silent);
    }
    return;
  }
  if (event.type === "environment_charge" || event.type === "environment_stage") {
    const env = state.payload.environment;
    if (!env) return;
    if (event.type === "environment_stage") {
      if (state.ui.envStage) state.ui.envStage.textContent = event.to || env.stage;
      if (!silent) showBanner("地势 " + (event.to || "变化"), "round");
    }
    const current = event.type === "environment_charge" ? Number(event.ratio) : Number(event.damage_ratio);
    if (state.ui.envBar) state.ui.envBar.style.width = ratio(current) + "%";
    return;
  }
  if (event.type === "battle_end") {
    if (!silent) showBanner("战斗结束 · " + (RESULT[event.winner] || "未分胜负"), "end");
    pause();
    return;
  }
}

function processDue() {
  while (state.cursor < state.payload.events.length) {
    const event = state.payload.events[state.cursor];
    if (Number(event.t) > state.t) break;
    applyEvent(event, false);
    state.cursor += 1;
  }
}

function playLoop() {
  if (state.playing) return;
  state.playing = true;
  state.ui.play.textContent = "暂停";
  state.last = performance.now();
  state.frame = requestAnimationFrame(tick);
}
function pause() {
  state.playing = false;
  if (state.frame) cancelAnimationFrame(state.frame);
  state.frame = 0;
  if (state.ui && state.ui.play) state.ui.play.textContent = "播放";
}
function tick(now) {
  if (!state.playing) return;
  const delta = Math.max(0, now - state.last);
  state.last = now;
  state.t += delta * state.speed;
  if (state.t >= state.duration) state.t = state.duration;
  processDue();
  updateControls();
  if (state.t >= state.duration) {
    pause();
    return;
  }
  state.frame = requestAnimationFrame(tick);
}
function seek(t) {
  pause();
  state.t = Math.max(0, Math.min(state.duration, t));
  resetVisual();
  state.cursor = 0;
  const target = state.t;
  state.t = 0;
  while (state.cursor < state.payload.events.length && Number(state.payload.events[state.cursor].t) <= target) {
    applyEvent(state.payload.events[state.cursor], true);
    state.cursor += 1;
  }
  state.t = target;
  updateControls();
}
function updateControls() {
  if (!state.ui) return;
  const percent = state.duration > 0 ? state.t / state.duration * 100 : 0;
  state.ui.fill.style.width = Math.max(0, Math.min(100, percent)) + "%";
  state.ui.clock.textContent = sec(state.t) + " / " + sec(state.duration);
}

boot();
