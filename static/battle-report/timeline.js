import {
  node,
  renderFacts,
  renderSnapshotParticipant,
  safeToken,
} from "/static/battle-report/ui.js";

// 角色名字与颜色由载荷各发一份（`actors` / `palette`），事件与时间线条上只记「谁」（键）。
// 键查不到就**当场抛错**：宁可在控制台看见一句「战报缺少角色颜色」，也不要页面安静地
// 画成一片空白——这是第 116 轮把每条事件的颜色字典收成一张表时留下的边界。
let visuals = {};
let actors = {};

export function configureVisuals(palette, actorTable) {
  visuals = palette && typeof palette === "object" ? palette : {};
  actors = actorTable && typeof actorTable === "object" ? actorTable : {};
}

export function visualOf(key) {
  const value = visuals[key || "system"];
  if (!value) {
    throw new Error(`战报缺少角色颜色：${key || "system"}`);
  }
  return value;
}

function actorLabel(key) {
  return actors[key] || "";
}

export function renderCompactTimeline(segment, ui, loadComparison) {
  const mode = ui.modes[0];
  const section = node("section", "mode-panel compact-panel");
  section.dataset.mode = mode.id;
  section.append(renderTimelineHeading(mode.label));
  const timeline = node("div", "timeline compact-timeline");
  if (!segment.timeline.length) {
    timeline.append(node("p", "empty-state", ui.text.empty_timeline));
  }
  let previousRound = "";
  segment.timeline.forEach((entry) => {
    if (entry.round_label && entry.round_label !== previousRound) {
      timeline.append(node("div", "round-heading", entry.round_label));
      previousRound = entry.round_label;
    }
    timeline.append(renderCompactEntry(entry, ui, loadComparison));
  });
  // 收束句：这一场怎么结束的（服务端按最后一击 + 结果合成）。
  const 收束 = String(segment.ending_line || "").trim();
  if (收束) {
    timeline.append(node("p", "timeline-ending", 收束));
  }
  section.append(timeline);
  return section;
}

export function renderDetailedTimeline(detail, filter, ui, loadComparison) {
  const mode = ui.modes[1] || ui.modes[0];
  const section = node("section", "mode-panel detail-panel");
  section.dataset.mode = mode.id;
  section.append(renderTimelineHeading(mode.label));
  section.append(
    node(
      "div",
      "event-filters",
      detail.filters.map((option) => {
        const button = node("button", "control-button", `${option.label} ${option.count}`);
        button.type = "button";
        button.dataset.action = "filter";
        button.dataset.value = option.id;
        button.setAttribute("aria-pressed", String(filter === option.id));
        return button;
      }),
    ),
  );
  section.append(renderDetailedTimelineEntries(detail, filter, ui, loadComparison));
  return section;
}

export function renderDetailedTimelineEntries(detail, filter, ui, loadComparison) {
  const timeline = node("div", "timeline detailed-timeline region-update");
  const entries = detail.timeline.filter(
    (entry) => entry.events.some((event) => matchesFilter(event, filter, ui)),
  );
  if (!entries.length) {
    timeline.append(node("p", "empty-state", ui.text.empty_filter));
  }
  entries.forEach((entry) => {
    timeline.append(renderDetailedEntry(entry, filter, ui, loadComparison));
  });
  return timeline;
}

//: 引擎的**记账**事件（冷却推进、状态层数、事件转化、资源恢复、行动条）不进「战斗记录」。
//: 它们是逐格结算的账，一场 16 次行动能撑出三百多行——玩家要的是战斗经过，不是流水账。
//: 明细视图照旧全给，什么都不删。
const 记账标签 = new Set(["冷却变化", "冷却完成", "状态层数", "事件转化", "资源恢复", "行动条"]);

function 该上屏(event) {
  if (记账标签.has(String(event.label || ""))) {
    return false;
  }
  // 「普攻」单独一行等于没说：标题已经写了这一击用的是什么。
  if (String(event.label || "") === "普攻") {
    return false;
  }
  // 0 伤害不单独占一行：护盾全吸收、免疫这类结果，正文里自会说明。
  // 取值在 `text` 里、且 `text` 自带标签（形如「伤害 · 0」），所以取最后一段数字判。
  if (String(event.label || "") === "伤害") {
    const 数值 = String(event.text || "").split("·").pop().trim();
    if (/^0(?:\.0+)?$/.test(数值)) {
      return false;
    }
  }
  return true;
}

//: 事实的取值：`text` 自带标签（形如「伤害 · 4.52」），取最后一段即数值本身。
function 取值(文本) {
  return String(文本 || "").split("·").pop().trim();
}

//: 把一次行动里的事实收成**读得懂的几行**：连续的同名状态合成一行、
//: 伤害写明打谁、零信息行去掉（第 123 轮：玩家视角的可读性）。
function 上屏分组(事件表) {
  const 出 = [];
  let 状态行 = null;
  (事件表 || []).forEach((event) => {
    if (!该上屏(event)) {
      return;
    }
    const 标 = String(event.label || "");
    if (标 === "获得状态") {
      const 值 = 取值(event.text);
      if (状态行) {
        状态行.text = `${状态行.text} · ${值}`;
        return;
      }
      状态行 = { ...event, text: 值 };
      出.push(状态行);
      return;
    }
    状态行 = null;
    if (标 === "伤害") {
      const 目标 = event.target && event.target !== event.source ? actorLabel(event.target) : "自身";
      出.push({ ...event, text: `→ ${目标}  ${取值(event.text)}` });
      return;
    }
    出.push(event);
  });
  return 出;
}

//: 「A 对 A」读起来像打自己：来源与目标同一个人时，目标写「自身」。
function 行动标题(entry) {
  const 名 = actorLabel(entry.actor);
  const 原 = String(entry.title || "");
  if (名 && 原.startsWith(`${名} 对 ${名} `)) {
    return 原.replace(`${名} 对 ${名} `, `${名} 对 自身 `);
  }
  return 原;
}

function renderCompactEntry(entry, ui, loadComparison) {
  const article = node("article", `action-card tone-${safeToken(entry.tone)}`);
  applyVisual(article, visualOf(entry.actor));
  article.append(node("div", "action-head", [node("div", "action-title", 行动标题(entry))]));
  // 给玩家的是**一句话**（服务端合成）：标题 + 结果 + 副作用。
  const 叙述 = String(entry.narrative || "").trim();
  if (叙述 && 叙述 !== 行动标题(entry)) {
    article.append(node("p", "action-narrative", 叙述.slice(行动标题(entry).length).replace(/^；/, "")));
  }
  if (entry.health_line) {
    article.append(node("p", "action-health", entry.health_line));
  }
  // 原始事件收进折叠：默认不占屏，要点开才看（明细视图「全部事件」照旧全给）。
  const 可读 = 上屏分组(entry.summary_events);
  if (可读.length) {
    const details = node("details", "action-raw");
    details.append(node("summary", "", `原始事件 ${可读.length} 条`));
    const events = node("ol", "event-list compact-event-list");
    可读.forEach((event) => events.append(renderEvent(event, false, ui)));
    details.append(events);
    article.append(details);
  }
  if (entry.comparison_available) {
    article.append(renderComparisonAccess(entry.sequence, ui, loadComparison));
  }
  return article;
}

function renderDetailedEntry(entry, filter, ui, loadComparison) {
  const article = node("article", `action-card detailed-action tone-${safeToken(entry.tone)}`);
  applyVisual(article, visualOf(entry.actor));
  article.append(
    node("div", "action-head", [
      node("div", "action-title", 行动标题(entry)),
      node("div", "action-sequence", entry.sequence_label),
    ]),
  );
  if (entry.facts.length) {
    article.append(renderFacts(entry.facts, "fact-row"));
  }
  const eventList = node("ol", "event-list");
  entry.events
    .filter((event) => matchesFilter(event, filter, ui))
    .forEach((event) => eventList.append(renderEvent(event, true, ui)));
  article.append(eventList);
  if (entry.comparison?.available) {
    article.append(renderComparisonAccess(entry.sequence, ui, loadComparison));
  }
  return article;
}

function renderEvent(event, includeFacts, ui) {
  const item = node("li", "event");
  item.dataset.tone = event.tone || "neutral";
  item.dataset.category = event.category || "";
  item.append(
    node("div", "event-heading", [
      renderEventMarker(event, ui),
      includeFacts ? node("span", "event-label", event.label) : null,
      node("span", "event-text", event.text),
    ]),
  );
  if (includeFacts && event.facts?.length) {
    item.append(
      node(
        "div",
        "event-facts",
        event.facts.map((fact) => `${fact.label}: ${fact.display}`).join(" · "),
      ),
    );
  }
  return item;
}

function renderEventMarker(event, ui) {
  const marker = node("span", "event-marker", "");
  const visual = visualOf(event.source);
  applyVisual(marker, visual);
  marker.dataset.actorKey = visual.key || "system";
  marker.dataset.eventCategory = event.category || "";
  marker.title = visual.key === "system"
    ? event.label
    : `${actorLabel(event.source) || ui.text.participant_fallback} · ${event.label}`;
  marker.setAttribute("aria-hidden", "true");
  return marker;
}

function renderComparisonAccess(sequence, ui, loadComparison) {
  const details = node("details", "frame-comparison");
  details.dataset.sequence = String(sequence);
  details.append(node("summary", "", ui.text.comparison_title));
  details.addEventListener("toggle", async () => {
    if (!details.open || details.dataset.loaded === "true") {
      return;
    }
    details.dataset.loaded = "loading";
    const status = loadingStatus(ui.text.loading_comparison);
    details.append(status);
    try {
      const value = await loadComparison(sequence);
      status.replaceWith(renderComparison(value.comparison));
      details.dataset.loaded = "true";
    } catch (error) {
      status.replaceWith(loadError(error));
      details.dataset.loaded = "error";
    }
  });
  return details;
}

function renderComparison(comparison) {
  const body = node("div", "comparison-body");
  body.append(renderChanges(comparison));
  const grid = node("div", "frame-grid");
  if (comparison.before) {
    grid.append(renderFrame(comparison.before));
  }
  if (comparison.after) {
    grid.append(renderFrame(comparison.after));
  }
  body.append(grid);
  return body;
}

function renderChanges(comparison) {
  if (!comparison.changes.length) {
    return node("p", "state-diff muted", comparison.empty_text);
  }
  return node(
    "ul",
    "state-diff",
    comparison.changes.map((change) =>
      node("li", `tone-${safeToken(change.tone)}`, change.text),
    ),
  );
}

function renderFrame(frame) {
  const article = node("article", "snapshot");
  article.append(
    node("div", "snapshot-heading", [
      node("strong", "", frame.title),
      node("span", "", frame.round_turn_label),
    ]),
  );
  article.append(renderFacts(frame.facts, "snapshot-facts"));
  article.append(
    node(
      "div",
      "snapshot-participants",
      frame.participants.map((participant) => renderSnapshotParticipant(participant)),
    ),
  );
  return article;
}

function renderTimelineHeading(title) {
  return node("div", "timeline-heading", [node("h2", "", title)]);
}

function matchesFilter(event, filter, ui) {
  return filter === ui.filters[0].id || event.category === filter;
}

function loadingStatus(message) {
  const status = node("p", "inline-status", message);
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  return status;
}

function loadError(error) {
  return node(
    "p",
    "inline-error",
    error instanceof Error ? error.message : String(error),
  );
}

export function applyVisual(element, visual) {
  if (!visual || typeof visual.color !== "string" || typeof visual.foreground !== "string") {
    throw new Error("战报缺少后端角色颜色。");
  }
  element.style.setProperty("--actor-color", visual.color);
  element.style.setProperty("--actor-ink", visual.foreground);
}
