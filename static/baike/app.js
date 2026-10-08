"use strict";

const PAGE_SIZE = 100;

const el = {
  prefixes: document.getElementById("prefixes"),
  entries: document.getElementById("entries"),
  pager: document.getElementById("pager"),
  detail: document.getElementById("detail"),
  status: document.getElementById("status"),
  crumb: document.getElementById("crumb"),
  query: document.getElementById("query"),
};

let rows = [];
let page = 1;
let label = "";
let activePrefix = "";

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
    button.addEventListener("click", () => openPrefix(row["前缀"], row["类别"]));
    item.append(button);
    frag.append(item);
  }
  el.prefixes.append(frag);
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
    name.textContent = row["名称"];
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

function renderDetail(body) {
  clear(el.detail);
  const head = document.createElement("header");
  head.className = "detail-head";
  const title = document.createElement("h2");
  title.className = "detail-title";
  title.textContent = body["名称"];
  const meta = document.createElement("p");
  meta.className = "detail-meta";
  meta.textContent = body["来源"] + " · " + body["编号"] + (body["编号类别"] ? " · " + body["编号类别"] : "");
  const back = document.createElement("button");
  back.type = "button";
  back.className = "back";
  back.textContent = "返回列表";
  back.addEventListener("click", () => showList());
  head.append(title, meta, back);
  const list = document.createElement("dl");
  list.className = "fields";
  for (const [key, value] of Object.entries(body["字段"] || {})) {
    const term = document.createElement("dt");
    term.className = "field-key";
    term.textContent = key;
    const desc = document.createElement("dd");
    desc.className = "field-value";
    desc.textContent = typeof value === "string" ? value : JSON.stringify(value);
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
  show(el.detail, false);
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
  show(el.detail, false);
  try {
    const body = await fetchData("?prefix=" + encodeURIComponent(prefix));
    rows = body["条目"] || [];
    page = 1;
    label = prefix + " " + category + " · 共 " + rows.length + " 条";
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
  show(el.detail, false);
  try {
    const body = await fetchData("?q=" + encodeURIComponent(word));
    rows = body["条目"] || [];
    page = 1;
    label = "检索「" + word + "」 · 共 " + rows.length + " 条";
    el.crumb.textContent = "检索 " + word;
    renderRows();
    setStatus(rows.length ? label : "没有匹配的条目", !rows.length);
  } catch (error) {
    setStatus(String(error.message || error), true);
  }
}

async function openDetail(id) {
  markActive("");
  setStatus("正在载入…", false);
  try {
    const body = await fetchData("?id=" + encodeURIComponent(id));
    show(el.entries, false);
    show(el.pager, false);
    setStatus("", false);
    renderDetail(body);
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
    setStatus("选一个前缀，或直接检索编号与名称", false);
  } catch (error) {
    setStatus(String(error.message || error), true);
  }
}

el.query.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const word = el.query.value.trim();
  if (word) search(word);
});

boot();
