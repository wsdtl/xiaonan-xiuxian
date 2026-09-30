export function replaceRegion(root, selector, replacement) {
  const current = root.querySelector(selector);
  if (current) {
    current.replaceWith(replacement);
  }
}

export function animateRegion(element) {
  if (!element) {
    return;
  }
  element.classList.remove("region-update");
  void element.offsetWidth;
  element.classList.add("region-update");
}

export function activateMotion(root) {
  root.querySelectorAll(".vital-fill").forEach((fill) => fill.classList.add("is-filled"));
}

export function node(tag, className = "", content = null) {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  if (Array.isArray(content)) {
    content.forEach((item) => item != null && element.append(item));
  } else if (content instanceof Node) {
    element.append(content);
  } else if (content != null) {
    element.textContent = String(content);
  }
  return element;
}

export function controlButton(label, action, value, active) {
  const button = node("button", "control-button", label);
  button.type = "button";
  button.dataset.action = action;
  button.dataset.value = value;
  button.setAttribute("aria-pressed", String(active));
  return button;
}

export function renderFacts(facts, className) {
  return node(
    "div",
    className,
    facts.map((fact) => node("span", "", `${fact.label}: ${fact.display}`)),
  );
}

export function detailLine(label, value) {
  return node("p", "", [node("strong", "", label), document.createTextNode(value)]);
}

export function renderGauge(gauge, reverse = false) {
  const values = node("span", "bar-value", gauge.display);
  const title = node("span", "bar-label", gauge.label);
  if (gauge.presentation === "value") {
    return node(
      "div",
      `bar-row metric-row tone-${safeToken(gauge.tone)}${reverse ? " reverse" : ""}`,
      reverse ? [values, title] : [title, values],
    );
  }
  const bar = node("div", `vital-bar tone-${safeToken(gauge.tone)}`);
  const fill = node("span", "vital-fill");
  fill.style.setProperty("--fill", `${gauge.fill_percent}%`);
  bar.append(fill);
  return node(
    "div",
    `bar-row${reverse ? " reverse" : ""}`,
    reverse ? [values, bar, title] : [title, bar, values],
  );
}

export function renderStatusGroup(group) {
  const items = group.items || [];
  const content = items.length
    ? node(
        "div",
        "effect-chips",
        items.map((item) =>
          node(
            "span",
            `effect-chip tone-${safeToken(item.tone)}`,
            item.display ? `${item.label} · ${item.display}` : item.label,
          ),
        ),
      )
    : node("p", "effect-empty", group.empty_text || "");
  return node("section", "participant-effect-group", [
    node("h3", "participant-group-label", group.label),
    content,
  ]);
}

export function renderDetailGroups(groups) {
  return node(
    "div",
    "detail-grid",
    groups.map((group) => detailLine(group.label, groupText(group))),
  );
}

export function renderParticipantRecord(participant) {
  const details = node("details", "participant-record");
  details.append(node("summary", "", participant.detail_label));
  details.append(renderDetailGroups(participant.detail_groups || []));
  return details;
}

// 快照里的参战者记录只带**会变**的那一半（血气 / 状态），不变的那一半（名字、阵营、
// 颜色、功法能力列表）在载荷的花名册里各有一份——同一个人的功法列表原先被每条行动抄两遍。
// 加载后先把两份合起来，渲染函数照旧只读合成后的记录。**合不起来就抛错**：宁可在控制台
// 看见一句「战报缺少角色档案」，也不要页面安静地画成空白（第 117 轮）。
export function hydrateParticipants(payload, roster) {
  if (!payload || typeof payload !== "object" || !roster) {
    return payload;
  }
  const fill = (record) => {
    if (!record || typeof record !== "object" || !record.key) {
      return record;
    }
    const profile = roster[record.key];
    if (!profile) {
      throw new Error(`战报缺少角色档案：${record.key}`);
    }
    const merged = { ...profile, ...record };
    // 快照记录只带「会变的那一半」，它**不许**把档案里的名字与颜色覆盖成空：
    // 覆盖掉的话下游 applyVisual 就会抛「战报缺少后端角色颜色。」，而真实原因在档案里。
    if (!isVisual(merged.visual)) {
      merged.visual = profile.visual;
    }
    if (!isVisual(merged.visual)) {
      throw new Error(`战报缺少后端角色颜色：${record.key}`);
    }
    if (!merged.label) {
      merged.label = profile.label;
    }
    return merged;
  };
  if (Array.isArray(payload.participants)) {
    payload.participants = payload.participants.map(fill);
  }
  // 片段载荷里的两份参战者名单（行动前 / 行动后）同样是「只带会变的那一半」。
  // 漏掉它们，收起面板里的名录就会拿没有颜色的记录去渲染 —— `renderRoster` 直接抛
  // 「战报缺少后端角色颜色。」（第 122 轮靠真浏览器堆栈定位到这一处）。
  ["initial_participants", "final_participants"].forEach((field) => {
    if (Array.isArray(payload[field])) {
      payload[field] = payload[field].map(fill);
    }
  });
  if (payload.segment) {
    hydrateParticipants(payload.segment, roster);
  }
  const comparison = payload.comparison;
  if (comparison) {
    ["before", "after"].forEach((side) => {
      const frame = comparison[side];
      if (frame && Array.isArray(frame.participants)) {
        frame.participants = frame.participants.map(fill);
      }
    });
  }
  return payload;
}

export function renderSnapshotParticipant(participant) {  const details = node("details", "participant-details");
  details.append(
    node("summary", "", [
      node("strong", "", participant.label),
      node(
        "span",
        "",
        (participant.gauges || []).map((gauge) => `${gauge.label} ${gauge.display}`).join(" · "),
      ),
    ]),
  );
  const body = node("div", "snapshot-participant-body");
  (participant.gauges || []).forEach((gauge) => body.append(renderGauge(gauge)));
  body.append(renderStatusGroup(participant.status_group));
  body.append(renderDetailGroups(participant.detail_groups || []));
  details.append(body);
  return details;
}

export function safeToken(value) {
  const token = String(value || "neutral").toLowerCase().replace(/[^a-z0-9_-]/g, "");
  return token || "neutral";
}

function groupText(group) {
  const items = group.items || [];
  if (!items.length) {
    return group.empty_text || "";
  }
  return items
    .map((item) => (item.display ? `${item.label} ${item.display}` : item.label))
    .join("、");
}

//: 一份能用的角色视觉：必须同时有颜色与字色——`applyVisual` 就按这两项判。
function isVisual(value) {
  return Boolean(value) && typeof value.color === "string" && typeof value.foreground === "string";
}
