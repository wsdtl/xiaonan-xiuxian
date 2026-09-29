const $ = (id) => document.getElementById(id);
const sections = ["功法", "真意", "气机", "器律"];
let page = null, allLimits = {}, draft = Object.fromEntries(sections.map(s => [s, []]));
let target = {section: "功法", index: 0}, offset = 0, revision = 0, scopeRequest = 0, codeRequest = 0;
let dictionary = new Map();
const pageSize = 30;
const key = (s, entry) => [s, entry.编号, entry.品级].join(":");
const status = (message, error = false) => { $("status").textContent = message; $("status").className = error ? "error" : ""; };
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function option(value, label) { const node = element("option", label); node.value = value; return node; }
async function request(url, body) {
  const response = await fetch(url, body === undefined ? {cache: "no-store"} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body), cache: "no-store"
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求未完成，请重试");
  return data;
}
function invalidate() {
  revision++;
  $("code-output").value = "";
  $("copy-code").disabled = $("copy-command").disabled = true;
}
function label(section, item) {
  return dictionary.get(key(section, item))?.label || item.编号 + (item.品级 ? " · 品级" + item.品级 : "");
}
function renderSlots() {
  $("slots").replaceChildren();
  for (const section of sections) {
    const group = element("section", undefined, "slot-group");
    group.append(element("h3", section + " " + draft[section].filter(Boolean).length + "/" + allLimits[section]));
    const grid = element("div", undefined, "slot-grid");
    for (let index = 0; index < allLimits[section]; index++) {
      const item = draft[section][index];
      const row = element("div", undefined, "slot-row");
      const select = element("button", (index + 1) + " · " + (item ? label(section, item) : "空槽"), "slot");
      select.type = "button";
      const selected = target.section === section && target.index === index;
      select.setAttribute("aria-pressed", String(selected));
      select.onclick = () => { target = {section, index}; $("section").value = section; offset = 0; renderSlots(); renderCandidates(); };
      const clear = element("button", "清除", "clear");
      clear.type = "button"; clear.disabled = !item;
      clear.setAttribute("aria-label", "清除" + section + (index + 1));
      clear.onclick = () => { draft[section][index] = null; invalidate(); renderSlots(); };
      row.append(select, clear); grid.append(row);
    }
    group.append(grid); $("slots").append(group);
  }
}
function renderCandidates() {
  if (!page) return;
  const section = $("section").value;
  const grade = $("grade").value, query = $("search").value.trim().toLowerCase();
  $("grade").disabled = section === "器律";
  // 器律不分品级：把筛选值清掉并说明，避免下拉里挂着一个不起作用的品级。
  if (section === "器律") { $("grade").value = ""; $("grade").title = "器律不分品级，品级筛选对它无效"; }
  else { $("grade").title = ""; }
  const rows = page.entries.filter(entry => entry.section === section &&
    (section === "器律" || !grade || entry.grade === grade) &&
    (!query || (entry.label + " " + entry.id + " " + entry.description).toLowerCase().includes(query)));
  offset = Math.min(offset, Math.max(0, Math.ceil(rows.length / pageSize) - 1));
  const container = $("candidates"); container.replaceChildren();
  $("target-hint").textContent = "填入位置：" + target.section + "第" + (target.index + 1) + "槽";
  // 非器律按编号查重（与整套校验一致），器律按编号加品级；方案里已有的内容不该再被填入。
  const taken = new Map();
  for (const section of sections) draft[section].forEach((item, index) => {
    if (!item) return;
    taken.set(section + ":" + item.编号 + (section === "器律" ? ":" + item.品级 : ""), index + 1);
  });
  for (const entry of rows.slice(offset * pageSize, (offset + 1) * pageSize)) {
    const card = element("article", undefined, "candidate");
    card.append(element("h3", entry.label));
    let info = entry.id;
    if (entry.quantity !== null) info += " · 库存 " + entry.quantity + (entry.equipped.length ? " · 已装槽 " + entry.equipped.join("、") : "");
    card.append(element("p", info, "meta"));
    const detail = element("details"); detail.append(element("summary", "查看说明"), element("p", entry.description));
    let loaded = false, loading = false;
    detail.ontoggle = async () => {
      if (!detail.open || loaded || loading) return;
      loading = true;
      try {
        const value = await request("/assembly/content?section=" + encodeURIComponent(section) + "&content_id=" + entry.id);
        detail.append(element("p", value.lines.join("\n")));
        loaded = true;
      } catch (error) { status("说明读取失败：" + error.message + "，重新展开可重试。", true); }
      finally { loading = false; }
    };
    const slot = taken.get(section + ":" + entry.id + (section === "器律" ? ":" + entry.grade : ""));
    if (slot) card.classList.add("placed");
    const put = element("button", slot ? "已在第" + slot + "槽" : "填入第" + (target.index + 1) + "槽");
    put.type = "button";
    put.disabled = Boolean(slot);
    put.title = slot ? "同一内容不能在同类里重复装配" : "";
    put.onclick = () => {
      draft[section][target.index] = {编号: entry.id, 品级: entry.grade};
      invalidate(); renderSlots(); renderCandidates(); status("已填入 " + entry.label + "；尚未修改人物装配。");
    };
    card.append(detail, put); container.append(card);
  }
  if (!rows.length) container.append(element("p", "此范围没有符合条件的内容。可调整筛选或选择全池。", "empty"));
  $("count").textContent = rows.length + " 项 · " + (rows.length ? offset + 1 : 0) + "/" + Math.ceil(rows.length / pageSize) + " 页";
  $("prev").disabled = offset === 0;
  $("next").disabled = (offset + 1) * pageSize >= rows.length;
}
async function loadScope(scope = $("scope").value) {
  const sequence = ++scopeRequest;
  page = null;
  $("scope").disabled = true; $("load-current").disabled = true;
  $("candidates").replaceChildren();
  status("正在读取清单…");
  try {
    const data = await request("/assembly/data?scope=" + encodeURIComponent(scope));
    if (sequence !== scopeRequest) return;
    page = data;
    if (!Object.keys(allLimits).length) {
      allLimits = {...data.limits};
      for (const section of sections) draft[section] = Array(allLimits[section]).fill(null);
    }
    for (const entry of data.entries) dictionary.set(key(entry.section, {编号: entry.id, 品级: entry.grade}), entry);
    if (scope === "all") {
      const chosen = $("grade").value, grades = new Map();
      for (const entry of data.entries) if (entry.grade) grades.set(entry.grade, entry.grade_name);
      $("grade").replaceChildren(option("", "全部品级"), ...Array.from(grades, ([id, name]) => option(id, name)));
      $("grade").value = chosen;
    }
    $("scope").replaceChildren(...data.scopes.map(s => option(s.id, s.name)));
    $("scope").value = data.scope;
    $("load-current").disabled = scope === "all";
    $("generate").disabled = false;
    $("intro").textContent = data.ui.说明;
    $("public-help").textContent = data.ui.公开说明;
    $("import-help").textContent = data.ui.导入说明;
    $("cost-help").textContent = data.ui.消耗说明;
    $("scope-info").textContent = scope === "all" ? "全池：完整构筑目录，供研究与配装；不表示任何玩家实际拥有。" :
      "此人的当前槽位：" + sections.map(s => s + " " + data.limits[s]).join(" / ") + "。切换清单不会覆盖右侧方案。";
    offset = 0; renderSlots(); renderCandidates(); status("清单已更新，方案保持不变。");
  } catch (error) {
    if (sequence !== scopeRequest) return;
    page = null;
    $("scope-info").textContent = "";
    $("scope").replaceChildren(option("all", "全池"));
    $("count").textContent = "";
    status(error.message + "；点击刷新清单返回全池。", true);
  } finally {
    if (sequence === scopeRequest) $("scope").disabled = false;
  }
}
async function calculate(body, replace) {
  const sequence = ++codeRequest, before = revision;
  status(replace ? "正在解析装配码…" : "正在生成装配码…");
  try {
    const value = await request("/assembly/scheme", body);
    if (sequence !== codeRequest || before !== revision) return;
    if (replace) {
      draft = Object.fromEntries(sections.map(s => [s, Array.from({length: allLimits[s]}, (_, i) => value.build[s][i] || null)]));
      // 编码接口返回的公开标签不依赖当前候选清单。
      for (const s of sections) value.build[s].forEach((item, index) => {
        if (!item) return;
        const prefix = s + (index + 1) + "：";
        const text = value.lines.find(line => line.startsWith(prefix));
        if (text) dictionary.set(key(s, item), {label: text.slice(prefix.length)});
      });
      invalidate(); renderSlots();
    }
    $("code-output").value = value.code;
    $("copy-code").disabled = $("copy-command").disabled = false;
    status(replace ? "已载入方案；网页未修改人物装配。" : "装配码已生成。聊天导入时再校验执行者的实际拥有清单。");
  } catch (error) {
    if (sequence === codeRequest && before === revision) status(error.message, true);
  }
}
async function copy(command) {
  const code = $("code-output").value.replace(/^导入装配\s+/, "");
  if (!code) return;
  const value = (command ? "导入装配 " : "") + code;
  try { await navigator.clipboard.writeText(value); status("已复制" + (command ? "聊天导入命令" : "装配码")); }
  catch {
    $("code-output").value = value; $("code-output").focus(); $("code-output").select();
    status("浏览器未允许自动复制，文本已选中，请手动复制。");
  }
}
$("section").replaceChildren(...sections.map(s => option(s, s)));
$("scope").onchange = () => loadScope();
$("refresh").onclick = () => loadScope();
$("section").onchange = () => { target = {section: $("section").value, index: 0}; offset = 0; renderSlots(); renderCandidates(); };
$("grade").onchange = $("search").oninput = () => { offset = 0; renderCandidates(); };
$("prev").onclick = () => { offset--; renderCandidates(); };
$("next").onclick = () => { offset++; renderCandidates(); };
$("reset").onclick = () => { for (const s of sections) draft[s] = Array(allLimits[s]).fill(null); invalidate(); renderSlots(); status("方案已清空；人物装配未改变。"); };
$("load-current").onclick = () => {
  if (!page || page.scope === "all") return;
  draft = Object.fromEntries(sections.map(s => [s, Array.from({length: allLimits[s]}, (_, i) => page.current[s][i] || null)]));
  invalidate(); renderSlots(); status("已将此人当前装配填入方案。");
};
$("generate").onclick = () => calculate({build: draft}, false);
$("open-code").onclick = () => {
  if (!Object.keys(allLimits).length) { status("请先成功读取全池。", true); return; }
  calculate({code: $("code-input").value.trim().replace(/^导入装配\s+/, "")}, true);
};
$("copy-code").onclick = () => copy(false);
$("copy-command").onclick = () => copy(true);
await loadScope("all");
