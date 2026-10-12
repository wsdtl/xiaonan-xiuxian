"use strict";

const PAGE_SIZE = 100;

const el = {
  prefixes: document.getElementById("prefixes"),
  entries: document.getElementById("entries"),
  pager: document.getElementById("pager"),
  detail: document.getElementById("detail"),
  overview: document.getElementById("overview"),
  dialog: document.getElementById("detail-dialog"),
  status: document.getElementById("status"),
  crumb: document.getElementById("crumb"),
  query: document.getElementById("query"),
};

let rows = [];
let page = 1;
let label = "";
let activePrefix = "";
let lastQuery = "";
// 详情走弹窗；顺着「关联」点下去时压栈，好退回上一个词条。
let currentId = "";
const detailStack = [];

async function fetchData(params) {
  const response = await fetch("/baike/data" + (params || ""));
  const body = await response.json();
  if (!response.ok) throw new Error(body["错误"] || "取数失败：" + response.status);
  return body;
}

function show(node, on) {
  node.hidden = !on;
}

function setStatus(text, bad) {
  el.status.textContent = text;
  el.status.classList.toggle("status-error", Boolean(bad));
  show(el.status, Boolean(text));
}

function push(query) {
  history.pushState(null, "", location.pathname + query);
}

function clear(list) {
  while (list.firstChild) list.removeChild(list.firstChild);
}

function renderPrefixes(table) {
  clear(el.prefixes);
  const frag = document.createDocumentFragment();
  let lastGroup = "";
  for (const row of table) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "prefix-button";
    const group = row["主体"];
    if (group && group !== lastGroup) {
      const heading = document.createElement("li");
      heading.className = "group";
      heading.textContent = group;
      frag.append(heading);
      lastGroup = group;
    }
    const code = document.createElement("span");
    code.className = "prefix-code";
    code.textContent = row["前缀"];
    const name = document.createElement("span");
    name.className = "prefix-name";
    name.textContent = row["类别"];
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = row["条数"];
    button.append(code, name, count);
    button.dataset.prefix = row["前缀"];
    if (!Number(row["条数"])) {
      // 号段先登记、实体还没放进来（精英 / 讨伐首领…）：置灰不可点，别让人点进一片空白。
      button.classList.add("is-empty");
      button.disabled = true;
      button.title = "这一类还没有词条";
    } else {
      button.addEventListener("click", () => openPrefix(row["前缀"], row["类别"]));
    }
    item.append(button);
    frag.append(item);
  }
  el.prefixes.append(frag);
}

function mark(node, text, word) {
  if (!word) {
    node.textContent = text;
    return;
  }
  const at = text.indexOf(word);
  if (at < 0) {
    node.textContent = text;
    return;
  }
  node.textContent = "";
  node.append(text.slice(0, at));
  const hit = document.createElement("mark");
  hit.className = "hit";
  hit.textContent = text.slice(at, at + word.length);
  node.append(hit, text.slice(at + word.length));
}

function renderRows() {
  clear(el.entries);
  const start = (page - 1) * PAGE_SIZE;
  const slice = rows.slice(start, start + PAGE_SIZE);
  const frag = document.createDocumentFragment();
  for (const row of slice) {
    const item = document.createElement("li");
    item.className = "entry";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "entry-button";
    const code = document.createElement("span");
    code.className = "code";
    code.textContent = row["编号"];
    const name = document.createElement("span");
    name.className = "name";
    mark(name, row["名称"], lastQuery);
    const source = document.createElement("span");
    source.className = "source";
    source.textContent = row["来源"];
    button.append(code, name, source);
    button.addEventListener("click", () => openDetail(row["编号"]));
    item.append(button);
    frag.append(item);
  }
  el.entries.append(frag);
  renderPager();
}

function renderPager() {
  clear(el.pager);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  if (pages <= 1) return;
  const frag = document.createDocumentFragment();
  const make = (text, target, disabled) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "pager-button";
    button.textContent = text;
    button.disabled = disabled;
    button.addEventListener("click", () => {
      page = target;
      renderRows();
      window.scrollTo({ top: 0 });
    });
    return button;
  };
  const marker = document.createElement("span");
  marker.className = "pager-marker";
  marker.textContent = page + " / " + pages;
  frag.append(make("上一页", Math.max(1, page - 1), page <= 1), marker, make("下一页", Math.min(pages, page + 1), page >= pages));
  el.pager.append(frag);
}

function renderOverview(table) {
  clear(el.overview);
  const head = document.createElement("header");
  head.className = "overview-head";
  const title = document.createElement("h2");
  title.className = "overview-title";
  title.textContent = "全部词条";
  const meta = document.createElement("p");
  meta.className = "overview-meta";
  meta.textContent = table["总数"] + " 条 · " + table["前缀数"] + " 个前缀";
  head.append(title, meta);
  const cards = document.createElement("ul");
  cards.className = "cards";
  for (const row of table["主体表"] || []) {
    const item = document.createElement("li");
    item.className = "card";
    const name = document.createElement("span");
    name.className = "card-name";
    name.textContent = row["主体"];
    const count = document.createElement("span");
    count.className = "card-count";
    if (!Number(row["条数"])) {
      // 号段登记了、实体还没放进来（精英 / 讨伐首领…）：说「未开放」，不摆一个 0 条让人点。
      item.classList.add("is-empty");
      count.textContent = "未开放";
    } else {
      count.textContent = row["条数"] + " 条";
    }
    const sub = document.createElement("span");
    sub.className = "card-sub";
    sub.textContent = row["前缀数"] + " 个前缀";
    item.append(name, count, sub);
    cards.append(item);
  }
  // 只靠十来张卡片，主区下半截会空着；把前缀按条数排个序配上占比条，
  // 空白就变成有用的信息（数据全来自同一份总表，不额外取数）。
  const total = Number(table["总数"]) || 1;
  const ranked = [...(table["前缀表"] || [])]
    .sort((a, b) => Number(b["条数"]) - Number(a["条数"]))
    .slice(0, 12);
  const rankTitle = document.createElement("h3");
  rankTitle.className = "refs-title";
  rankTitle.textContent = "条数最多的前缀";
  const rank = document.createElement("ul");
  rank.className = "rank";
  for (const row of ranked) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "rank-row";
    const code = document.createElement("span");
    code.className = "rank-code";
    code.textContent = row["前缀"];
    const name = document.createElement("span");
    name.className = "rank-name";
    name.textContent = row["类别"];
    const bar = document.createElement("progress");
    bar.className = "rank-bar";
    bar.max = total;
    bar.value = Number(row["条数"]) || 0;
    const count = document.createElement("span");
    count.className = "rank-count";
    count.textContent = row["条数"] + " 条";
    button.append(code, name, bar, count);
    button.addEventListener("click", () => openPrefix(row["前缀"], row["类别"]));
    item.append(button);
    rank.append(item);
  }
  el.overview.append(head, cards, rankTitle, rank);
  show(el.overview, true);
}

// 字段值可能是对象或数组，直接 JSON.stringify 会甩出一堆引号花括号；
// 一律展开成「键：值」多行，读起来才像册子。
function formatValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value !== "object") return String(value);
  if (Array.isArray(value)) return value.map(formatValue).join("、");
  return Object.entries(value)
    .map(([key, inner]) => key + "：" + formatValue(inner))
    .join("\n");
}

// 嵌套对象（敌人的属性覆盖、掉落、交锋所得…）拍平成一行就读不出结构，拆成「子键 + 值」逐行列。
function fieldValue(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const wrap = document.createElement("ul");
    wrap.className = "field-object";
    for (const [key, inner] of Object.entries(value)) {
      const item = document.createElement("li");
      const sub = document.createElement("span");
      sub.className = "field-sub-key";
      sub.textContent = key;
      const text = document.createElement("span");
      text.className = "field-sub-value";
      text.textContent = formatValue(inner);
      item.append(sub, text);
      wrap.append(item);
    }
    return wrap;
  }
  const span = document.createElement("span");
  span.textContent = formatValue(value);
  return span;
}

function openSheet() {
  if (el.dialog && !el.dialog.open) el.dialog.showModal();
}

function closeSheet() {
  if (el.dialog && el.dialog.open) el.dialog.close();
}

function renderDetail(body) {
  clear(el.detail);
  const head = document.createElement("header");
  head.className = "detail-head";
  const title = document.createElement("h2");
  title.className = "detail-title";
  title.textContent = body["名称"];
  const meta = document.createElement("p");
  meta.className = "detail-meta";
  const kind = body["编号类别"] && body["编号类别"] !== body["来源"] ? " · " + body["编号类别"] : "";
  meta.textContent = body["来源"] + " · " + body["编号"] + kind;
  const back = document.createElement("button");
  back.type = "button";
  back.className = "back";
  back.textContent = "返回列表";
  back.addEventListener("click", () => showList());
  head.append(title, meta, back);
  if (detailStack.length) {
    const prev = document.createElement("button");
    prev.type = "button";
    prev.className = "back";
    prev.textContent = "← 返回上一词条";
    prev.addEventListener("click", () => {
      const last = detailStack.pop() || "";
      currentId = "";
      if (last) openDetail(last, true);
    });
    head.append(prev);
  }
  const list = document.createElement("dl");
  list.className = "fields";
  const pairs = Object.entries(body["字段"] || {});
  const first = ["编号", "名称", "说明"];
  pairs.sort((a, b) => (first.indexOf(a[0]) + 1 || 99) - (first.indexOf(b[0]) + 1 || 99));
  for (const [key, value] of pairs) {
    const term = document.createElement("dt");
    term.className = "field-key";
    term.textContent = key;
    const desc = document.createElement("dd");
    desc.className = "field-value";
    desc.append(fieldValue(value));
    list.append(term, desc);
  }
  el.detail.append(head, list);
  const refs = body["引用"] || [];
  if (refs.length) {
    const title = document.createElement("h3");
    title.className = "refs-title";
    title.textContent = "关联";
    const wrap = document.createElement("ul");
    wrap.className = "refs";
    for (const ref of refs) {
      const item = document.createElement("li");
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = ref["名称"];
      const where = document.createElement("span");
      where.className = "chip-field";
      where.textContent = ref["字段"];
      chip.append(where);
      chip.addEventListener("click", () => openDetail(ref["编号"]));
      item.append(chip);
      wrap.append(item);
    }
    el.detail.append(title, wrap);
  }
  show(el.detail, true);
}

function showList() {
  closeSheet();
  detailStack.length = 0;
  currentId = "";
  show(el.overview, false);
  show(el.entries, true);
  show(el.pager, true);
  setStatus(label, false);
}

function markActive(prefix) {
  activePrefix = prefix;
  for (const button of el.prefixes.querySelectorAll(".prefix-button")) {
    button.classList.toggle("is-active", button.dataset.prefix === prefix);
  }
}

async function openPrefix(prefix, category) {
  markActive(prefix);
  setStatus("正在载入…", false);
  show(el.overview, false);
  try {
    const body = await fetchData("?prefix=" + encodeURIComponent(prefix));
    rows = body["条目"] || [];
    page = 1;
    label = prefix + " " + category + " · 共 " + rows.length + " 条";
    lastQuery = "";
    push("?prefix=" + prefix);
    el.crumb.textContent = prefix + " " + category;
    renderRows();
    setStatus(label, false);
  } catch (error) {
    setStatus(String(error.message || error), true);
  }
}

async function search(word) {
  markActive("");
  setStatus("正在载入…", false);
  show(el.overview, false);
  try {
    const body = await fetchData("?q=" + encodeURIComponent(word));
    rows = body["条目"] || [];
    page = 1;
    label = "检索「" + word + "」 · 共 " + rows.length + " 条";
    lastQuery = word;
    push("?q=" + encodeURIComponent(word));
    el.crumb.textContent = "检索 " + word;
    renderRows();
    setStatus(rows.length ? label : "没有匹配的条目", !rows.length);
  } catch (error) {
    setStatus(String(error.message || error), true);
  }
}

async function openDetail(id, keepStack) {
  markActive("");
  setStatus("正在载入…", false);
  try {
    const body = await fetchData("?id=" + encodeURIComponent(id));
    if (!keepStack && currentId && currentId !== id) detailStack.push(currentId);
    currentId = id;
    show(el.entries, false);
    show(el.pager, false);
    setStatus("", false);
    renderDetail(body);
    openSheet();
    push("?id=" + id);
  } catch (error) {
    setStatus(String(error.message || error), true);
  }
}

async function boot() {
  try {
    const table = await fetchData();
    renderPrefixes(table["前缀表"] || []);
    const params = new URLSearchParams(location.search);
    const id = (params.get("id") || "").trim();
    const word = (params.get("q") || "").trim();
    const prefix = (params.get("prefix") || "").trim();
    if (id) {
      await openDetail(id);
      return;
    }
    if (word) {
      el.query.value = word;
      await search(word);
      return;
    }
    if (prefix) {
      const hit = (table["前缀表"] || []).find((row) => row["前缀"] === prefix);
      await openPrefix(prefix, hit ? hit["类别"] : "");
      return;
    }
    show(el.entries, false);
    show(el.pager, false);
    setStatus("", false);
    renderOverview(table);
  } catch (error) {
    setStatus(String(error.message || error), true);
  }
}

el.query.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const word = el.query.value.trim();
  if (word) search(word);
});

// 弹窗用原生关闭（✕、Esc、点遮罩）：关掉就把列表视图还回来。
el.dialog.addEventListener("close", () => {
  detailStack.length = 0;
  currentId = "";
  show(el.entries, true);
  show(el.pager, true);
  setStatus(label, false);
});

window.addEventListener("popstate", () => boot());
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !el.dialog.open) showList();
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  const buttons = [...el.entries.querySelectorAll(".entry-button")];
  if (!buttons.length) return;
  const at = buttons.indexOf(document.activeElement);
  const next = event.key === "ArrowDown" ? Math.min(buttons.length - 1, at + 1) : Math.max(0, at - 1);
  event.preventDefault();
  buttons[next].focus();
});

boot();
