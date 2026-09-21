import {
  applyVisual,
  configureVisuals,
  renderCompactTimeline,
  renderDetailedTimeline,
} from "./timeline.js";
import {
  activateMotion,
  controlButton,
  hydrateParticipants,
  node,
  renderGauge,
  renderParticipantRecord,
  renderStatusGroup,
  safeToken,
} from "./ui.js";

const root = document.querySelector("#reportRoot");
const announcer = node("p", "visually-hidden", "");
announcer.setAttribute("aria-live", "polite");
announcer.setAttribute("aria-atomic", "true");
document.body.append(announcer);

const state = {
  report: null,
  segmentIndex: 0,
  mode: "",
  filter: "",
  snapshot: "",
  participantExpanded: false,
  segments: new Map(),
  events: new Map(),
  participants: new Map(),
  transitions: new Map(),
  previewBundle: null,
};

root.addEventListener("click", (event) => {
  void handleControlClick(event);
});
root.addEventListener("change", (event) => {
  void handleControlChange(event);
});

main().catch((error) => {
  renderError(error instanceof Error ? error.message : String(error));
});

async function main() {
  const report = await loadReport();
  if (report.schema !== "game.battle_report.presentation" || report.version !== 6) {
    renderUnsupportedReport(report);
    return;
  }
  state.report = report;
  configureVisuals(report.palette, report.actors);
  state.mode = report.ui.defaults.mode;
  state.filter = report.ui.defaults.filter;
  state.snapshot = report.ui.defaults.snapshot;
  report.detail.segments.forEach((segment) => {
    hydrateParticipants(segment, report.roster);
    state.segments.set(segment.index, segment);
  });
  if (report.detail.segments.length) {
    state.segmentIndex = report.detail.segments[0].index;
  }
  document.title = report.document_title;
  renderReport();
}

async function loadReport() {
  const embedded = document.querySelector("#battleReportPreviewData");
  if (embedded) {
    return JSON.parse(embedded.textContent || "null");
  }
  const localPath = new URLSearchParams(window.location.search).get("report");
  const preview = document.querySelector('meta[name="battle-report-preview-data"]');
  if (localPath || preview) {
    return fetchJson(localPath || preview.content);
  }
  const path = reportBasePath();
  if (!path) {
    throw new Error("分享地址无效。");
  }
  return fetchJson(`${path}/data`);
}

async function handleControlClick(event) {
  const button = event.target.closest("button[data-action]");
  if (!button || !root.contains(button) || !state.report) {
    return;
  }
  const action = button.dataset.action;
  const value = button.dataset.value;
  try {
    if (action === "mode" && optionExists(state.report.ui.modes, value)) {
      if (state.mode === value) {
        return;
      }
      if (value === "detail") {
        announce(state.report.ui.text.loading_events);
        await ensureEvents(state.segmentIndex);
      }
      state.mode = value;
      renderReport();
      focusControl("mode", value);
      return;
    }
    if (action === "segment") {
      await selectSegment(Number(value));
      return;
    }
    if (action === "segment-step") {
      await selectSegment(state.segmentIndex + Number(value));
      return;
    }
    if (action === "snapshot" && optionExists(state.report.ui.snapshots, value)) {
      if (state.snapshot === value) {
        return;
      }
      state.snapshot = value;
      if (state.participantExpanded) {
        announce(state.report.ui.text.loading_participants);
        await ensureParticipants(state.segmentIndex, state.snapshot);
      }
      renderReport();
      focusControl("snapshot", value);
      return;
    }
    if (action === "participant-disclosure") {
      state.participantExpanded = !state.participantExpanded;
      if (state.participantExpanded) {
        renderReport();
        announce(state.report.ui.text.loading_participants);
        await ensureParticipants(state.segmentIndex, state.snapshot);
      }
      renderReport();
      focusControl("participant-disclosure", "");
      return;
    }
    if (action === "filter" && optionExists(state.report.ui.filters, value)) {
      state.filter = value;
      renderReport();
      focusControl("filter", value);
    }
  } catch (error) {
    announce(error instanceof Error ? error.message : String(error));
    renderInlineError(error);
  }
}

async function handleControlChange(event) {
  const select = event.target.closest('select[data-action="segment-select"]');
  if (!select || !root.contains(select) || !state.report) {
    return;
  }
  try {
    await selectSegment(Number(select.value));
  } catch (error) {
    renderInlineError(error);
  }
}

async function selectSegment(index) {
  const count = state.report.detail.segment_count;
  if (!Number.isInteger(index) || index < 0 || index >= count || index === state.segmentIndex) {
    return;
  }
  announce(fillTemplate(state.report.ui.text.switching_segment, { 当前片段: index + 1 }));
  await ensureSegment(index);
  state.segmentIndex = index;
  state.filter = state.report.ui.defaults.filter;
  state.participantExpanded = false;
  if (state.mode === "detail") {
    await ensureEvents(index);
  }
  renderReport();
  const heading = root.querySelector(".segment-overview");
  heading?.setAttribute("tabindex", "-1");
  heading?.focus({ preventScroll: true });
  heading?.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
  announce(fillTemplate(state.report.ui.text.switched_segment, { 当前片段: index + 1 }));
}

async function ensureSegment(index) {
  if (state.segments.has(index)) {
    return state.segments.get(index);
  }
  const payload = await loadEndpoint("segment", { segmentIndex: index });
  assertProtocol(payload);
  hydrateParticipants(payload.segment, state.report.roster);
  state.segments.set(index, payload.segment);
  return payload.segment;
}

async function ensureEvents(index) {
  if (state.events.has(index)) {
    return state.events.get(index);
  }
  const payload = await loadEndpoint("events", { segmentIndex: index });
  assertProtocol(payload);
  state.events.set(index, payload);
  return payload;
}

async function ensureParticipants(index, snapshot) {
  const key = `${index}:${snapshot}`;
  if (state.participants.has(key)) {
    return state.participants.get(key);
  }
  const payload = await loadEndpoint("participants", { segmentIndex: index, snapshot });
  assertProtocol(payload);
  hydrateParticipants(payload, state.report.roster);
  state.participants.set(key, payload);
  return payload;
}

async function ensureTransition(index, sequence) {
  const key = `${index}:${sequence}`;
  if (state.transitions.has(key)) {
    return state.transitions.get(key);
  }
  const payload = await loadEndpoint("transition", { segmentIndex: index, sequence });
  assertProtocol(payload);
  hydrateParticipants(payload, state.report.roster);
  state.transitions.set(key, payload);
  return payload;
}

async function loadEndpoint(kind, values) {
  const preview = document.querySelector('meta[name="battle-report-preview-data"]');
  if (preview) {
    const bundle = await loadPreviewBundle(preview.content);
    return previewValue(bundle, kind, values);
  }
  const base = reportBasePath();
  const index = values.segmentIndex;
  const paths = {
    segment: `${base}/segments/${index}`,
    events: `${base}/segments/${index}/events`,
    participants: `${base}/segments/${index}/participants/${encodeURIComponent(values.snapshot || "")}`,
    transition: `${base}/segments/${index}/transitions/${values.sequence}`,
  };
  return fetchJson(paths[kind]);
}

async function loadPreviewBundle(url) {
  if (!state.previewBundle) {
    state.previewBundle = fetchJson(url);
  }
  return state.previewBundle;
}

function previewValue(bundle, kind, values) {
  const index = String(values.segmentIndex);
  if (kind === "segment") {
    return bundle.segments[index];
  }
  if (kind === "events") {
    return bundle.events[index];
  }
  if (kind === "participants") {
    return bundle.participants[`${index}:${values.snapshot}`];
  }
  if (kind === "transition") {
    return bundle.transitions[`${index}:${values.sequence}`];
  }
  throw new Error(state.report.ui.text.unsupported_detail);
}

function renderReport() {
  const report = state.report;
  root.removeAttribute("aria-busy");
  root.replaceChildren();
  root.className = "report-shell report-ready";
  document.body.dataset.mode = state.mode;
  root.append(renderSummaryHeader(report));
  if (!report.detail.available) {
    root.append(
      node("section", "notice", [
        node("p", "section-kicker", report.ui.text.archive_kicker),
        node("h2", "", report.ui.text.archive_title),
        node("p", "", report.detail.retention_notice),
      ]),
    );
    return;
  }
  const segment = currentSegment();
  if (!segment) {
    root.append(node("section", "error-state", report.ui.text.segment_load_failed));
    return;
  }
  if (report.detail.segment_count > 1) {
    root.append(renderSegmentNavigation());
  }
  root.append(renderMatchup(segment));
  root.append(renderViewToolbar());
  root.append(renderReportBody(segment));
  requestAnimationFrame(() => activateMotion(root));
}

function renderSummaryHeader(report) {
  const text = report.ui.text;
  const header = node("header", "report-header");
  header.append(
    node("div", "brand-line", [
      node("span", "brand-name", report.game_name),
      node("span", "brand-divider", text.brand_suffix),
    ]),
  );
  header.append(
    node("div", "title-row", [
      node("div", "title-copy", [
        node("h1", "", report.summary.title),
        node("p", "report-time", report.time_label),
      ]),
      node("div", `result-stamp ${safeToken(report.summary.tone)}`, [
        node("span", "", text.settlement_label),
        node("strong", "", report.summary.outcome),
      ]),
    ]),
  );
  const lines = report.summary.lines || [];
  if (!lines.length) {
    return header;
  }
  header.append(node("ul", "summary-lines", lines.slice(0, 2).map((line) => node("li", "", line))));
  if (lines.length > 2) {
    const more = node("details", "summary-lines-more");
    more.append(node("summary", "", text.more_summary));
    more.append(node("ul", "summary-more-list", lines.slice(2).map((line) => node("li", "", line))));
    header.append(more);
  }
  return header;
}

function renderMatchup(segment) {
  const participants = segment.final_participants.length
    ? segment.final_participants
    : segment.initial_participants;
  const teams = groupByTeam(participants);
  if (!teams.length) {
    return node("div", "matchup segment-overview empty", state.report.ui.text.empty_participants);
  }
  const first = renderTeamSummary(teams[0]);
  if (teams.length === 1) {
    return node("section", "matchup segment-overview single", first);
  }
  const last = renderTeamSummary(teams[teams.length - 1], true);
  const middleTeams = Math.max(0, teams.length - 2);
  return node("section", "matchup segment-overview", [
    first,
    node("div", "versus", [
      node("strong", "", state.report.ui.text.versus_label),
      segment.duration_label ? node("span", "", segment.duration_label) : null,
      middleTeams
        ? node("small", "", fillTemplate(state.report.ui.text.additional_team_template, { 数量: middleTeams }))
        : null,
    ]),
    last,
  ]);
}

function renderTeamSummary(team, reverse = false) {
  const names = team.participants.map((item) => item.label).join("、");
  return node("div", `combat-side${reverse ? " enemy" : ""}`, [
    node("div", "side-name", [node("span", "", team.label), node("strong", "", names)]),
  ]);
}

function renderSegmentNavigation() {
  const count = state.report.detail.segment_count;
  const text = state.report.ui.text;
  const options = Array.from({ length: count }, (_, index) => {
    const segment = state.segments.get(index);
    const option = node("option", "", `${index + 1} / ${count} · ${segment?.title || ""}`);
    option.value = String(index);
    option.selected = index === state.segmentIndex;
    return option;
  });
  const select = node("select", "segment-select", options);
  select.dataset.action = "segment-select";
  select.setAttribute("aria-label", text.segment_select_label);
  const compactButtons = count <= 6
    ? node(
        "div",
        "segment-scroll",
        Array.from({ length: count }, (_, index) =>
          controlButton(
            state.segments.get(index)?.title || "",
            "segment",
            String(index),
            index === state.segmentIndex,
          ),
        ),
      )
    : null;
  return node("nav", `segment-tabs${count > 6 ? " many-segments" : ""}`, [
    node("span", "segment-label", [
      document.createTextNode(text.segment_label),
      node("small", "segment-count", `${state.segmentIndex + 1} / ${count}`),
    ]),
    node("div", "segment-navigation", [
      segmentStepButton(text.previous_segment_label, -1, state.segmentIndex === 0),
      node("label", "segment-picker", [select]),
      compactButtons,
      segmentStepButton(text.next_segment_label, 1, state.segmentIndex === count - 1),
    ]),
  ]);
}

function segmentStepButton(label, direction, disabled) {
  const button = node("button", "segment-step", direction < 0 ? "‹" : "›");
  button.type = "button";
  button.dataset.action = "segment-step";
  button.dataset.value = String(direction);
  button.disabled = disabled;
  button.setAttribute("aria-label", label);
  button.title = label;
  return button;
}

function renderViewToolbar() {
  return node("section", "view-toolbar", [
    node(
      "div",
      "mode-switch",
      state.report.ui.modes.map((option) =>
        controlButton(option.label, "mode", option.id, state.mode === option.id),
      ),
    ),
  ]);
}

function renderReportBody(segment) {
  return node("section", "report-body view-panel", [
    renderSummaryPanel(segment),
    node("section", "timeline-panel", [renderActiveTimeline(segment)]),
  ]);
}

function renderActiveTimeline(segment) {
  const comparison = (sequence) => ensureTransition(state.segmentIndex, sequence);
  if (state.mode === "detail") {
    const detail = state.events.get(state.segmentIndex);
    return detail
      ? renderDetailedTimeline(detail, state.filter, state.report.ui, comparison)
      : loadingPanel(state.report.ui.text.events_loading);
  }
  return renderCompactTimeline(segment, state.report.ui, comparison);
}

function renderSummaryPanel(segment) {
  const selected = state.report.ui.snapshots.find((item) => item.id === state.snapshot);
  const button = node("button", "participant-disclosure-title", [
    node("strong", "", state.report.ui.text.participant_panel_title),
    node("span", "", selected.label),
  ]);
  button.type = "button";
  button.dataset.action = "participant-disclosure";
  button.setAttribute("aria-controls", "participantDetails");
  button.setAttribute("aria-expanded", String(state.participantExpanded));
  const disclosure = node("section", "participant-disclosure", [
    button,
    renderRoster(segment),
  ]);
  disclosure.dataset.expanded = String(state.participantExpanded);
  if (state.participantExpanded) {
    const key = `${state.segmentIndex}:${state.snapshot}`;
    const loaded = state.participants.get(key);
    const snapshotSwitch = node(
      "div",
      "snapshot-switch",
      state.report.ui.snapshots.map((option) =>
        controlButton(option.label, "snapshot", option.id, state.snapshot === option.id),
      ),
    );
    snapshotSwitch.dataset.snapshot = state.snapshot;
    const body = loaded
      ? node(
          "div",
          "participant-stack",
          loaded.participants.map((participant) => renderParticipantSummary(participant)),
        )
      : loadingPanel(state.report.ui.text.participants_loading);
    const content = node("div", "participant-disclosure-content", [
      node("div", "participant-disclosure-inner", [
        node("div", "panel-heading", [snapshotSwitch]),
        body,
      ]),
    ]);
    content.id = "participantDetails";
    disclosure.append(content);
  }
  return node("aside", "summary-panel", disclosure);
}

function renderRoster(segment) {
  // 收起状态下的参战者名录：一栏徽章 + 名字 + 血气/精神条。
  // 面板收起来时只剩下一个标题，左边这一栏会空成一片——名录让它一直有用。
  const participants = state.snapshot === "before"
    ? segment.initial_participants
    : segment.final_participants;
  const list = node("ul", "roster-list");
  participants.forEach((participant) => {
    const badge = node(
      "span",
      "roster-index",
      String(participant.visual?.number || 0).padStart(2, "0"),
    );
    applyVisual(badge, participant.visual);
    const row = node("li", "roster-item", [
      node("div", "roster-head", [badge, node("span", "roster-name", participant.label)]),
      node(
        "div",
        "roster-gauges",
        (participant.gauges || []).map((gauge) => renderGauge(gauge)),
      ),
    ]);
    list.append(row);
  });
  return node("div", "participant-roster", list);
}

function renderParticipantSummary(participant) {
  const number = String(participant.visual?.number || 0).padStart(2, "0");
  const badge = node("span", "participant-index", number);
  applyVisual(badge, participant.visual);
  badge.dataset.actorKey = participant.visual?.key || "system";
  const children = [
    node("div", "participant-heading", [
      badge,
      node("div", "", [node("strong", "", participant.label)]),
    ]),
    ...(participant.gauges || []).map((gauge) => renderGauge(gauge)),
    renderStatusGroup(participant.status_group),
  ];
  if (participant.detail_groups?.length) {
    children.push(renderParticipantRecord(participant));
  }
  return node("article", "participant-summary", children);
}

function currentSegment() {
  return state.segments.get(state.segmentIndex);
}

function groupByTeam(participants) {
  const teams = new Map();
  participants.forEach((participant) => {
    const key = participant.team_id;
    if (!teams.has(key)) {
      teams.set(key, { id: key, label: participant.team_label, participants: [] });
    }
    teams.get(key).participants.push(participant);
  });
  return [...teams.values()];
}

function optionExists(options, value) {
  return options.some((item) => item.id === value);
}

function assertProtocol(value) {
  if (value?.schema !== "game.battle_report.presentation" || value?.version !== 6) {
    throw new Error(state.report.ui.text.unsupported_detail);
  }
}

function reportBasePath() {
  const path = window.location.pathname.replace(/\/$/, "");
  return /^\/battle\/[^/]+$/.test(path) ? path : "";
}

async function fetchJson(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail || "内容读取失败。");
  }
  return response.json();
}

function renderUnsupportedReport(report) {
  root.removeAttribute("aria-busy");
  root.replaceChildren(
    node("section", "error-state", [
      node("h1", "", "内容协议暂不支持"),
      node("p", "", `收到协议版本 ${String(report?.version ?? "-")}。`),
    ]),
  );
}

function renderError(message) {
  root.removeAttribute("aria-busy");
  root.replaceChildren(
    node("section", "error-state", [
      node("h1", "", "内容暂时无法打开"),
      node("p", "", message),
    ]),
  );
}

function renderInlineError(error) {
  const current = root.querySelector(".inline-page-error");
  current?.remove();
  const message = error instanceof Error ? error.message : String(error);
  const notice = node("p", "inline-page-error", message);
  notice.setAttribute("role", "alert");
  root.querySelector(".view-toolbar")?.after(notice);
}

function loadingPanel(message) {
  const status = node("p", "inline-status", message);
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  return status;
}

function announce(message) {
  announcer.textContent = "";
  requestAnimationFrame(() => {
    announcer.textContent = message;
  });
}

function focusControl(action, value) {
  requestAnimationFrame(() => {
    const suffix = value ? `[data-value="${CSS.escape(value)}"]` : "";
    root.querySelector(`[data-action="${CSS.escape(action)}"]${suffix}`)?.focus();
  });
}

function fillTemplate(template, values) {
  return Object.entries(values).reduce(
    (text, [key, value]) => text.replaceAll(`{${key}}`, String(value)),
    String(template || ""),
  );
}

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
