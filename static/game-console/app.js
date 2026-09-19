(function () {
  const MAX_DOM_RECORDS = 300;
  const state = {
    csrf: "",
    records: new Map(),
    order: [],
    source: null,
    filter: "all",
    loadingHistory: false,
    hasMore: true,
    userLockedScroll: false,
    unread: 0,
    streamGeneration: 0,
    sessionCheckTimer: null,
  };

  const nodes = {
    consoleShell: document.getElementById("consoleShell"),
    loginShell: document.getElementById("loginShell"),
    loginForm: document.getElementById("loginForm"),
    loginButton: document.getElementById("loginButton"),
    loginStatus: document.getElementById("loginStatus"),
    username: document.getElementById("username"),
    password: document.getElementById("password"),
    logoutButton: document.getElementById("logoutButton"),
    connectionStatus: document.getElementById("connectionStatus"),
    messageList: document.getElementById("messageList"),
    historySentinel: document.getElementById("historySentinel"),
    jumpLatest: document.getElementById("jumpLatest"),
    unreadCount: document.getElementById("unreadCount"),
    commandForm: document.getElementById("commandForm"),
    commandInput: document.getElementById("commandInput"),
    sendButton: document.getElementById("sendButton"),
    filters: Array.from(document.querySelectorAll("[data-filter]")),
  };

  function init() {
    bindViewport();
    bindLogin();
    bindConsole();
    bindConnectionLifecycle();
    restoreSession();
  }

  function bindViewport() {
    const resize = () => {
      const height = Math.max(320, Math.round(window.visualViewport?.height || window.innerHeight));
      document.documentElement.style.setProperty("--app-height", `${height}px`);
    };
    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("orientationchange", resize);
    window.visualViewport?.addEventListener("resize", resize);
    window.visualViewport?.addEventListener("scroll", resize);
  }

  function bindLogin() {
    nodes.loginForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      nodes.loginButton.disabled = true;
      nodes.loginStatus.textContent = "正在登录";
      try {
        const data = await requestJson("/game-console/login", {
          method: "POST",
          body: JSON.stringify({ username: nodes.username.value, password: nodes.password.value }),
        }, false);
        await enterConsole(data);
      } catch (error) {
        nodes.loginStatus.textContent = error.message || "登录失败";
      } finally {
        nodes.loginButton.disabled = false;
      }
    });
  }

  function bindConsole() {
    nodes.commandForm.addEventListener("submit", (event) => {
      event.preventDefault();
      sendCommand();
    });
    nodes.commandInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendCommand();
      }
    });
    nodes.commandInput.addEventListener("input", resizeComposer);
    nodes.messageList.addEventListener("scroll", syncScrollState, { passive: true });
    nodes.messageList.addEventListener("click", handleMessageClick);
    nodes.jumpLatest.addEventListener("click", scrollToLatest);
    nodes.logoutButton.addEventListener("click", logout);
    nodes.filters.forEach((button) => button.addEventListener("click", () => setFilter(button.dataset.filter)));
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) loadOlder();
    }, { root: nodes.messageList, rootMargin: "120px 0px 0px" });
    observer.observe(nodes.historySentinel);
  }

  function bindConnectionLifecycle() {
    window.addEventListener("online", () => {
      if (nodes.consoleShell.hidden) return;
      setConnection("重连中", "is-waiting");
      if (!state.source) connectStream();
    });
    window.addEventListener("offline", () => {
      if (!nodes.consoleShell.hidden) setConnection("网络断开", "is-error");
    });
    window.addEventListener("beforeunload", closeStream);
  }

  async function restoreSession() {
    try {
      await enterConsole(await requestJson("/game-console/api/session", {}, false));
    } catch (_error) {
      showLogin();
    }
  }

  async function enterConsole(session) {
    state.csrf = session.csrf_token || "";
    nodes.loginStatus.textContent = "";
    nodes.loginShell.hidden = true;
    nodes.consoleShell.hidden = false;
    await loadRecent();
    connectStream();
    nodes.commandInput.focus();
  }

  function showLogin(status = "") {
    closeStream();
    nodes.consoleShell.hidden = true;
    nodes.loginShell.hidden = false;
    nodes.loginStatus.textContent = status;
    nodes.password.value = "";
    nodes.password.focus();
  }

  async function loadRecent() {
    setConnection("读取中", "is-waiting");
    const data = await requestJson("/game-console/api/messages?limit=50");
    resetMessages();
    (data.records || []).forEach((record) => appendRecord(record, false));
    state.hasMore = Boolean(data.has_more);
    nodes.historySentinel.textContent = state.hasMore ? "读取更早消息" : "已到达当前保留范围起点";
    requestAnimationFrame(scrollToLatest);
  }

  async function loadOlder() {
    if (state.loadingHistory || !state.hasMore || !state.order.length) return;
    state.loadingHistory = true;
    nodes.historySentinel.textContent = "读取中";
    const beforeId = state.order[0];
    const oldHeight = nodes.messageList.scrollHeight;
    const oldTop = nodes.messageList.scrollTop;
    try {
      const data = await requestJson(`/game-console/api/messages?limit=50&before_id=${beforeId}`);
      const records = data.records || [];
      for (let index = records.length - 1; index >= 0; index -= 1) prependRecord(records[index]);
      state.hasMore = Boolean(data.has_more) && records.length > 0;
      const newHeight = nodes.messageList.scrollHeight;
      nodes.messageList.scrollTop = oldTop + (newHeight - oldHeight);
    } catch (_error) {
      state.hasMore = true;
    } finally {
      state.loadingHistory = false;
      nodes.historySentinel.textContent = state.hasMore ? "读取更早消息" : "已到达当前保留范围起点";
    }
  }

  function connectStream() {
    closeStream();
    const afterId = state.order.length ? state.order[state.order.length - 1] : 0;
    const generation = state.streamGeneration;
    const source = new EventSource(`/game-console/api/stream?after_id=${afterId}`);
    state.source = source;
    source.onopen = () => {
      if (!isCurrentStream(source, generation)) return;
      if (state.sessionCheckTimer !== null) {
        window.clearTimeout(state.sessionCheckTimer);
        state.sessionCheckTimer = null;
      }
      setConnection("实时连接", "is-live");
    };
    source.onerror = () => {
      if (!isCurrentStream(source, generation)) return;
      setConnection(navigator.onLine ? "重连中" : "网络断开", navigator.onLine ? "is-waiting" : "is-error");
      scheduleSessionCheck(source, generation);
    };
    source.onmessage = (event) => {
      if (!isCurrentStream(source, generation)) return;
      try {
        const nearBottom = isNearBottom();
        appendRecord(JSON.parse(event.data), true);
        if (nearBottom && !state.userLockedScroll) {
          scrollToLatest(false);
        } else {
          state.unread += 1;
          updateUnread();
        }
      } catch (_error) {
        setConnection("消息解析失败", "is-error");
      }
    };
    if (!navigator.onLine) setConnection("网络断开", "is-error");
  }

  function closeStream() {
    state.streamGeneration += 1;
    if (state.sessionCheckTimer !== null) {
      window.clearTimeout(state.sessionCheckTimer);
      state.sessionCheckTimer = null;
    }
    const source = state.source;
    state.source = null;
    if (!source) return;
    source.onopen = null;
    source.onerror = null;
    source.onmessage = null;
    source.close();
  }

  function isCurrentStream(source, generation) {
    return state.source === source && state.streamGeneration === generation;
  }

  function scheduleSessionCheck(source, generation) {
    if (state.sessionCheckTimer !== null) return;
    state.sessionCheckTimer = window.setTimeout(async () => {
      state.sessionCheckTimer = null;
      if (!isCurrentStream(source, generation)) return;
      try {
        await requestJson("/game-console/api/session", {}, false);
      } catch (error) {
        if (!isCurrentStream(source, generation)) return;
        if (error.status === 401) {
          showLogin("会话已过期，请重新登录");
          return;
        }
        setConnection(navigator.onLine ? "重连中" : "网络断开", navigator.onLine ? "is-waiting" : "is-error");
      }
    }, 1200);
  }

  function resetMessages() {
    nodes.messageList.querySelectorAll(".flow-row").forEach((row) => row.remove());
    state.records.clear();
    state.order = [];
    state.unread = 0;
    updateUnread();
  }

  function appendRecord(record, trim) {
    const id = Number(record?.flow_id || 0);
    if (!id || state.records.has(id)) return;
    const row = createRow(record);
    nodes.messageList.appendChild(row);
    state.records.set(id, { record, row });
    state.order.push(id);
    if (trim) trimFromStart();
    applyFilter(row, record);
    refreshRequestGroups();
  }

  function prependRecord(record) {
    const id = Number(record?.flow_id || 0);
    if (!id || state.records.has(id)) return;
    const row = createRow(record);
    nodes.messageList.insertBefore(row, nodes.historySentinel.nextSibling);
    state.records.set(id, { record, row });
    state.order.unshift(id);
    trimFromEnd();
    applyFilter(row, record);
    refreshRequestGroups();
  }

  function createRow(record) {
    const row = document.createElement("article");
    row.className = `flow-row ${record.direction === "incoming" ? "incoming" : "outgoing"}`;
    row.dataset.flowId = String(record.flow_id);
    row.dataset.adapter = record.adapter || "unknown";
    row.dataset.requestId = record.request_id || "";

    const stack = document.createElement("div");
    stack.className = "message-stack";
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const sender = document.createElement("span");
    sender.textContent = record.sender_name || record.user_id || "未知";
    const adapter = document.createElement("span");
    adapter.className = `adapter-tag ${record.adapter === "local" ? "local" : "qq"}`;
    adapter.textContent = record.adapter === "local" ? "本地" : record.adapter === "qq" ? "QQ" : record.adapter;
    const time = document.createElement("time");
    time.textContent = formatTime(record.created_at);
    meta.append(sender, adapter, time);

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    const content = document.createElement("div");
    content.className = "message-content";
    // content_html 由后台投影（presentation.py）转义后给出：它只认自己拼的标签，
    // 文本一律过 html.escape，链接另过 _safe_url。所以这里用 innerHTML 是安全的；
    // 回退分支只能拿 content 原文自己转义。
    content.innerHTML = record.content_html || escapeHtml(record.content || "");
    renderFormulas(content);
    bubble.appendChild(content);
    if (record.image && !content.querySelector("img") && isSafeUrl(record.image)) {
      const image = document.createElement("img");
      image.className = "separate-image";
      image.src = record.image;
      image.alt = "消息图片";
      bubble.appendChild(image);
    }
    const actions = createActions(record);
    if (actions.childElementCount) bubble.appendChild(actions);
    if (record.content_truncated) {
      const note = document.createElement("div");
      note.className = "truncated-note";
      note.textContent = "异常超长消息仅保留可见前段";
      bubble.appendChild(note);
    }
    stack.append(meta, bubble);
    row.appendChild(stack);
    return row;
  }

  function renderFormulas(root) {
    root.querySelectorAll(".message-formula").forEach((node) => {
      const source = node.dataset.latex || "";
      if (!source) return;
      if (!window.katex) {
        node.textContent = source;
        return;
      }
      try {
        window.katex.render(source, node, {
          displayMode: node.dataset.display === "true",
          throwOnError: false,
          strict: "ignore",
          trust: false,
        });
      } catch (_) {
        node.textContent = source;
      }
    });
  }

  function createActions(record) {
    const container = document.createElement("div");
    container.className = "message-actions";
    (record.interactions || []).forEach((interaction) => {
      if (interaction.kind === "command_link") return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = `action-button ${interaction.style || "primary"}`;
      button.textContent = interaction.label || "执行";
      button.dataset.flowId = String(record.flow_id);
      button.dataset.actionId = interaction.action_id;
      button.dataset.behavior = interaction.behavior || "callback";
      button.dataset.value = interaction.data || "";
      container.appendChild(button);
    });
    return container;
  }

  async function handleMessageClick(event) {
    const target = event.target.closest("[data-action-id]");
    if (!target) return;
    const behavior = target.dataset.behavior;
    if (behavior === "fill") {
      prefill(target.dataset.value || "");
      return;
    }
    if (behavior === "link") {
      if (isSafeUrl(target.dataset.value)) window.open(target.dataset.value, "_blank", "noopener,noreferrer");
      return;
    }
    target.disabled = true;
    try {
      const data = await requestJson("/game-console/api/action", {
        method: "POST",
        body: JSON.stringify({
          flow_id: Number(target.dataset.flowId),
          action_id: target.dataset.actionId,
        }),
      });
      if (data.kind === "fill") prefill(data.value || "");
      if (data.kind === "link" && isSafeUrl(data.value)) window.open(data.value, "_blank", "noopener,noreferrer");
    } catch (error) {
      setConnection(error.message || "交互失败", "is-error");
    } finally {
      target.disabled = false;
    }
  }

  async function sendCommand() {
    const command = nodes.commandInput.value.trim();
    if (!command || nodes.sendButton.disabled) return;
    nodes.sendButton.disabled = true;
    try {
      await requestJson("/game-console/api/command", {
        method: "POST",
        body: JSON.stringify({ command }),
      });
      nodes.commandInput.value = "";
      resizeComposer();
      nodes.commandInput.focus();
    } catch (error) {
      setConnection(error.message || "发送失败", "is-error");
    } finally {
      nodes.sendButton.disabled = false;
    }
  }

  function prefill(value) {
    nodes.commandInput.value = value;
    resizeComposer();
    nodes.commandInput.focus();
    nodes.commandInput.setSelectionRange(value.length, value.length);
  }

  async function logout() {
    try {
      await requestJson("/game-console/api/logout", { method: "POST", body: "{}" });
    } catch (_error) {
      // 本地状态仍然清理，过期会话无需再次请求。
    }
    state.csrf = "";
    showLogin();
  }

  function resizeComposer() {
    nodes.commandInput.style.height = "auto";
    nodes.commandInput.style.height = `${Math.min(nodes.commandInput.scrollHeight, 132)}px`;
  }

  function syncScrollState() {
    state.userLockedScroll = !isNearBottom();
    if (!state.userLockedScroll) {
      state.unread = 0;
      updateUnread();
    }
  }

  function isNearBottom() {
    const el = nodes.messageList;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 90;
  }

  function scrollToLatest() {
    requestAnimationFrame(() => {
      nodes.messageList.scrollTop = nodes.messageList.scrollHeight;
      state.userLockedScroll = false;
      state.unread = 0;
      updateUnread();
    });
  }

  function updateUnread() {
    nodes.jumpLatest.hidden = state.unread < 1;
    nodes.unreadCount.textContent = state.unread ? `(${state.unread})` : "";
  }

  function trimFromStart() {
    while (state.order.length > MAX_DOM_RECORDS) removeRecord(state.order[0]);
  }

  function trimFromEnd() {
    while (state.order.length > MAX_DOM_RECORDS) removeRecord(state.order[state.order.length - 1]);
  }

  function removeRecord(id) {
    const entry = state.records.get(id);
    entry?.row.remove();
    state.records.delete(id);
    state.order = state.order.filter((value) => value !== id);
  }

  function setFilter(filter) {
    state.filter = filter || "all";
    nodes.filters.forEach((button) => button.classList.toggle("is-active", button.dataset.filter === state.filter));
    state.records.forEach(({ record, row }) => applyFilter(row, record));
    refreshRequestGroups();
  }

  function applyFilter(row, record) {
    row.classList.toggle("is-filtered", state.filter !== "all" && record.adapter !== state.filter);
  }

  function refreshRequestGroups() {
    const rows = state.order
      .map((id) => state.records.get(id)?.row)
      .filter((row) => row && !row.classList.contains("is-filtered"));
    rows.forEach((row) => row.classList.remove("request-with-prev", "request-with-next"));
    rows.forEach((row, index) => {
      const requestId = row.dataset.requestId;
      if (!requestId) return;
      const previous = rows[index - 1];
      const next = rows[index + 1];
      if (previous?.dataset.requestId === requestId) row.classList.add("request-with-prev");
      if (next?.dataset.requestId === requestId) row.classList.add("request-with-next");
    });
  }

  function setConnection(text, className) {
    nodes.connectionStatus.textContent = text;
    nodes.connectionStatus.className = `connection-status ${className}`;
  }

  async function requestJson(url, options = {}, authenticated = true) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (authenticated && state.csrf && (options.method || "GET") !== "GET") headers["X-CSRF-Token"] = state.csrf;
    const response = await fetch(url, { credentials: "same-origin", ...options, headers });
    let data = {};
    try { data = await response.json(); } catch (_error) { data = {}; }
    if (!response.ok) {
      if (response.status === 401 && authenticated) showLogin();
      const error = new Error(data.detail || `请求失败 (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function formatTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function isSafeUrl(value) {
    const text = String(value || "").trim();
    if (text.startsWith("/") && !text.startsWith("//")) return true;
    try {
      const url = new URL(text, window.location.href);
      return url.protocol === "http:" || url.protocol === "https:";
    } catch (_error) {
      return false;
    }
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>\"]/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;",
    })[character]);
  }

  init();
}());
