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

function renderCompactEntry(entry, ui, loadComparison) {
  const article = node("article", `action-card tone-${safeToken(entry.tone)}`);
  applyVisual(article, visualOf(entry.actor));
  article.append(node("div", "action-head", [node("div", "action-title", entry.title)]));
  if (entry.summary_events.length) {
    const events = node("ol", "event-list compact-event-list");
    entry.summary_events.forEach((event) => events.append(renderEvent(event, false, ui)));
    article.append(events);
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
      node("div", "action-title", entry.title),
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
