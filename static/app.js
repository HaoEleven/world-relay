"use strict";

const state = {
  bootstrap: null,
  view: "home",
  inventory: "versions",
  selectedItem: "",
  progressRunning: false,
};

const byId = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const request = {
    method: options.method || "GET",
    headers: { "Content-Type": "application/json" },
  };
  if (options.body !== undefined) request.body = JSON.stringify(options.body);
  const response = await fetch(path, request);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`服务返回了无法读取的响应（${response.status}）`);
  }
  if (!response.ok) throw new Error(payload.error || `请求失败（${response.status}）`);
  return payload;
}

function setOptions(select, items, placeholder, valueKey = "name", labelKey = "name") {
  const previous = select.value;
  select.replaceChildren(new Option(placeholder, ""));
  for (const item of items) {
    select.add(new Option(item[labelKey], item[valueKey]));
  }
  if (items.some((item) => item[valueKey] === previous)) select.value = previous;
}

function syncUrl(mode = "push") {
  const url = new URL(window.location.href);
  url.searchParams.set("view", state.view);
  if (state.view === "manage") url.searchParams.set("list", state.inventory);
  else url.searchParams.delete("list");
  history[`${mode}State`]({ view: state.view, inventory: state.inventory }, "", url);
}

function switchView(view, updateUrl = true) {
  state.view = view;
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    const active = button.dataset.viewTarget === view;
    if (button.classList.contains("nav-item")) {
      button.classList.toggle("is-active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
  });
  document.querySelectorAll(".view").forEach((section) => {
    const active = section.id === `view-${view}`;
    section.classList.toggle("is-active", active);
    section.hidden = !active;
  });
  const heading = view === "home" ? byId("home-title") : byId("manage-title");
  heading.focus?.({ preventScroll: true });
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" });
  if (updateUrl) syncUrl();
}

async function refreshBootstrap({ preserveDetail = true } = {}) {
  const data = await api("/api/bootstrap");
  state.bootstrap = data;
  renderStatus();
  renderHomeSelectors();
  renderSettings();
  renderInventory(preserveDetail);
}

function renderStatus() {
  const ready = state.bootstrap.ready;
  byId("app-display-version").textContent = state.bootstrap.app.displayVersion;
  byId("configuration-notice").hidden = ready;
  byId("sidebar-status-dot").classList.toggle("is-ready", ready);
  byId("sidebar-status-title").textContent = ready ? "目录已连接" : "等待配置";
  byId("sidebar-status-copy").textContent = ready
    ? `${state.bootstrap.versions.length} 个版本 · ${state.bootstrap.saves.length} 个存档`
    : "设置两个工作目录后即可开始";
  byId("add-save").disabled = !ready;
}

function renderHomeSelectors() {
  const versionSelect = byId("home-version");
  const saveSelect = byId("home-save");
  const currentVersion = versionSelect.value;
  const currentSave = saveSelect.value;
  setOptions(versionSelect, state.bootstrap.versions, "请选择版本");
  versionSelect.disabled = !state.bootstrap.ready || state.bootstrap.versions.length === 0;
  if (state.bootstrap.versions.some((item) => item.name === currentVersion)) {
    versionSelect.value = currentVersion;
  }
  setOptions(saveSelect, state.bootstrap.saves, "请选择存档");
  saveSelect.disabled = !versionSelect.value;
  if (state.bootstrap.saves.some((item) => item.name === currentSave)) saveSelect.value = currentSave;
  if (!saveSelect.value) resetPlayerSelect("请先选择存档");
  updateHomeReady();
}

function resetPlayerSelect(message) {
  const playerSelect = byId("home-player");
  playerSelect.replaceChildren(new Option(message, ""));
  playerSelect.disabled = true;
  byId("home-player-note").textContent = "";
  updateHomeReady();
}

async function loadHomePlayers() {
  const version = byId("home-version").value;
  const save = byId("home-save").value;
  if (!version || !save) {
    resetPlayerSelect("请先选择存档");
    return;
  }
  const select = byId("home-player");
  select.replaceChildren(new Option("正在读取玩家…", ""));
  select.disabled = true;
  try {
    const result = await api(`/api/players?save=${encodeURIComponent(save)}&version=${encodeURIComponent(version)}`);
    setOptions(select, result.players, "请选择新服主", "uid", "label");
    select.disabled = result.players.length === 0;
    byId("home-player-note").textContent = result.message || `已识别 ${result.players.length} 名玩家。`;
  } catch (error) {
    resetPlayerSelect("玩家读取失败");
    byId("home-player-note").textContent = error.message;
  }
  updateHomeReady();
}

function updateHomeReady() {
  const version = byId("home-version").value;
  const save = byId("home-save").value;
  const uid = byId("home-player").value;
  byId("start-replace").disabled = !(version && save && uid);
  const base = state.bootstrap?.settings.minecraftPath || ".minecraft";
  byId("target-preview").textContent = version && save
    ? `${base}\\versions\\${version}\\saves\\${save}`
    : "选择三个字段后显示";
}

function renderSettings() {
  const settings = state.bootstrap.settings;
  if (document.activeElement !== byId("minecraft-path")) byId("minecraft-path").value = settings.minecraftPath;
  if (document.activeElement !== byId("saves-path")) byId("saves-path").value = settings.savesPath;
}

function switchInventory(type, updateUrl = true) {
  state.inventory = type;
  state.selectedItem = "";
  document.querySelectorAll("[data-inventory-target]").forEach((button) => {
    const active = button.dataset.inventoryTarget === type;
    if (button.classList.contains("segment-button")) {
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    }
  });
  renderInventory(false);
  if (updateUrl) syncUrl();
}

function renderInventory(preserveDetail = true) {
  if (!state.bootstrap) return;
  const items = state.inventory === "versions" ? state.bootstrap.versions : state.bootstrap.saves;
  byId("inventory-list-title").textContent = state.inventory === "versions" ? "版本列表" : "存档列表";
  byId("inventory-count").textContent = `${items.length} 个项目`;
  const list = byId("inventory-list");
  list.replaceChildren();

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "list-empty";
    const text = document.createElement("p");
    text.textContent = state.bootstrap.ready
      ? state.inventory === "versions" ? "versions 中没有可显示的版本。" : "saves 中还没有存档。"
      : "保存有效路径后在这里显示内容。";
    empty.append(text);
    list.append(empty);
    renderEmptyDetail();
    return;
  }

  if (!preserveDetail || !items.some((item) => item.name === state.selectedItem)) {
    state.selectedItem = "";
  }
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "inventory-item";
    button.title = item.name;
    button.classList.toggle("is-selected", item.name === state.selectedItem);

    const marker = document.createElement("span");
    marker.className = "inventory-item-marker";
    marker.setAttribute("aria-hidden", "true");
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = item.name;
    const subtitle = document.createElement("small");
    subtitle.textContent = state.inventory === "versions"
      ? "只读版本目录"
      : item.version || "尚未绑定版本";
    copy.append(title, subtitle);
    const arrow = document.createElement("span");
    arrow.className = "item-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "›";
    button.append(marker, copy, arrow);
    button.addEventListener("click", () => selectInventoryItem(item.name));
    list.append(button);
  }
  if (state.selectedItem) renderDetail(state.selectedItem);
  else renderEmptyDetail();
}

function selectInventoryItem(name) {
  state.selectedItem = name;
  renderInventory(true);
}

function renderEmptyDetail() {
  const panel = byId("detail-panel");
  panel.replaceChildren();
  const empty = document.createElement("div");
  empty.className = "empty-state";
  const heading = document.createElement("h2");
  heading.textContent = "选择一个项目";
  const copy = document.createElement("p");
  copy.textContent = state.inventory === "versions"
    ? "选择版本查看只读路径。"
    : "选择存档以绑定版本、查看玩家或删除。";
  empty.append(heading, copy);
  panel.append(empty);
}

function renderDetail(name) {
  const items = state.inventory === "versions" ? state.bootstrap.versions : state.bootstrap.saves;
  const item = items.find((entry) => entry.name === name);
  if (!item) return renderEmptyDetail();
  if (state.inventory === "versions") renderVersionDetail(item);
  else renderSaveDetail(item);
}

function renderVersionDetail(item) {
  const panel = byId("detail-panel");
  panel.replaceChildren();
  const header = detailHeader(item.name, "Minecraft 版本", "只读");
  const block = document.createElement("div");
  block.className = "detail-block";
  const label = document.createElement("h3");
  label.textContent = "版本路径";
  const path = document.createElement("p");
  path.className = "version-path";
  path.textContent = item.path;
  block.append(label, path);
  const note = document.createElement("p");
  note.textContent = "中继站只读取该目录的 usercache.json，并仅向其 saves 子目录写入目标存档。";
  panel.append(header, block, note);
}

function detailHeader(titleText, subtitleText, badgeText = "") {
  const header = document.createElement("div");
  header.className = "detail-header";
  const copy = document.createElement("div");
  const title = document.createElement("h2");
  title.textContent = titleText;
  const subtitle = document.createElement("p");
  subtitle.textContent = subtitleText;
  copy.append(title, subtitle);
  header.append(copy);
  if (badgeText) {
    const badge = document.createElement("span");
    badge.className = "readonly-badge";
    badge.textContent = badgeText;
    header.append(badge);
  }
  return header;
}

function renderSaveDetail(item) {
  const panel = byId("detail-panel");
  panel.replaceChildren();
  panel.append(detailHeader(item.name, item.path, item.hasLevelDat ? "有效存档" : "缺少 level.dat"));

  const association = document.createElement("div");
  association.className = "detail-block";
  const label = document.createElement("label");
  label.htmlFor = "detail-version";
  label.textContent = "对应 Minecraft 版本";
  const row = document.createElement("div");
  row.className = "association-row";
  const select = document.createElement("select");
  select.id = "detail-version";
  select.name = "associatedVersion";
  select.autocomplete = "off";
  setOptions(select, state.bootstrap.versions, "请选择版本");
  select.value = item.version || "";
  const saveButton = document.createElement("button");
  saveButton.type = "button";
  saveButton.className = "primary-button compact";
  saveButton.textContent = "保存关联";
  saveButton.disabled = !select.value;
  select.addEventListener("change", () => { saveButton.disabled = !select.value; });
  saveButton.addEventListener("click", () => saveAssociation(item.name, select.value, saveButton));
  row.append(select, saveButton);
  const help = document.createElement("p");
  help.textContent = "关联后使用该版本目录中的 usercache.json 识别玩家姓名。";
  association.append(label, row, help);
  panel.append(association);

  const playersBlock = document.createElement("div");
  playersBlock.className = "detail-block";
  const playersTitle = document.createElement("h3");
  playersTitle.textContent = "玩家信息";
  const playersBody = document.createElement("div");
  playersBody.className = "player-results";
  playersBlock.append(playersTitle, playersBody);
  panel.append(playersBlock);
  if (item.version) loadDetailPlayers(item.name, item.version, playersBody);
  else playersBody.textContent = "先为存档选择对应版本。";

  const danger = document.createElement("div");
  danger.className = "detail-danger";
  const warning = document.createElement("p");
  warning.textContent = "删除会移除 saves 管理目录中的整个存档文件夹，目标版本中的副本不会同步删除。";
  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "danger-button";
  deleteButton.textContent = "删除这个存档";
  deleteButton.addEventListener("click", () => requestDelete(item.name));
  danger.append(warning, deleteButton);
  panel.append(danger);
}

async function loadDetailPlayers(save, version, container) {
  container.textContent = "正在读取玩家…";
  try {
    const result = await api(`/api/players?save=${encodeURIComponent(save)}&version=${encodeURIComponent(version)}`);
    container.replaceChildren();
    if (!result.players.length) {
      container.textContent = result.message || "没有可显示的玩家。";
      return;
    }
    const list = document.createElement("ul");
    list.className = "player-list";
    for (const player of result.players) {
      const row = document.createElement("li");
      row.className = "player-row";
      const name = document.createElement("span");
      name.className = "player-name";
      name.textContent = player.name;
      const uid = document.createElement("span");
      uid.className = "player-uid";
      uid.textContent = player.uid;
      row.append(name, uid);
      list.append(row);
    }
    container.append(list);
    if (result.cachePath) {
      const cache = document.createElement("p");
      cache.className = "cache-path";
      cache.textContent = `名称来源：${result.cachePath}`;
      container.append(cache);
    }
  } catch (error) {
    container.textContent = error.message;
  }
}

async function saveAssociation(save, version, button) {
  button.disabled = true;
  button.textContent = "正在保存…";
  try {
    state.bootstrap = await api("/api/association", {
      method: "POST",
      body: { save, version },
    });
    state.selectedItem = save;
    renderStatus();
    renderHomeSelectors();
    renderInventory(true);
  } catch (error) {
    await showNotice("关联保存失败", error.message, "知道了");
    button.disabled = false;
    button.textContent = "保存关联";
  }
}

async function pickFolder(input, title) {
  const button = document.activeElement;
  if (button instanceof HTMLButtonElement) button.disabled = true;
  try {
    const result = await api("/api/pick-folder", {
      method: "POST",
      body: { initial: input.value, title },
    });
    if (result.path) input.value = result.path;
  } catch (error) {
    byId("settings-message").textContent = error.message;
  } finally {
    if (button instanceof HTMLButtonElement) button.disabled = false;
  }
}

function askConfirmation({ title, message, acceptText = "继续", danger = true, context = "确认操作", showCancel = true }) {
  const dialog = byId("confirm-dialog");
  byId("confirm-title").textContent = title;
  byId("confirm-message").textContent = message;
  byId("confirm-context").textContent = context;
  const accept = byId("confirm-accept");
  const cancel = byId("confirm-cancel");
  accept.textContent = acceptText;
  accept.className = danger ? "danger-button" : "primary-button compact";
  cancel.hidden = !showCancel;
  dialog.showModal();
  return new Promise((resolve) => {
    const finish = (value) => {
      accept.removeEventListener("click", onAccept);
      cancel.removeEventListener("click", onCancel);
      dialog.removeEventListener("cancel", onCancel);
      dialog.close();
      resolve(value);
    };
    const onAccept = () => finish(true);
    const onCancel = (event) => { event?.preventDefault(); finish(false); };
    accept.addEventListener("click", onAccept);
    cancel.addEventListener("click", onCancel);
    dialog.addEventListener("cancel", onCancel);
  });
}

async function showNotice(title, message, acceptText = "确定") {
  return askConfirmation({ title, message, acceptText, danger: false, context: "执行信息", showCancel: false });
}

async function showJob(jobId) {
  const dialog = byId("progress-dialog");
  state.progressRunning = true;
  dialog.querySelector(".modal-body").setAttribute("aria-busy", "true");
  byId("progress-confirm").disabled = true;
  byId("progress-error").hidden = true;
  byId("progress-warning").hidden = true;
  byId("progress-log").replaceChildren();
  byId("progress-bar").value = 0;
  byId("progress-bar").textContent = "0%";
  byId("progress-percent").textContent = "0%";
  byId("progress-state").textContent = "进行中";
  byId("progress-icon").className = "modal-icon";
  if (!dialog.open) dialog.showModal();

  let knownSteps = 0;
  while (true) {
    let job;
    try {
      job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    } catch (error) {
      job = { status: "error", progress: 0, title: "任务状态读取失败", message: "操作未完成", error: error.message, steps: [] };
    }
    byId("progress-title").textContent = job.title;
    byId("progress-message").textContent = job.message;
    byId("progress-bar").value = job.progress;
    byId("progress-bar").textContent = `${job.progress}%`;
    byId("progress-percent").textContent = `${job.progress}%`;
    for (const step of job.steps.slice(knownSteps)) {
      const item = document.createElement("li");
      item.textContent = step.message;
      byId("progress-log").append(item);
    }
    knownSteps = job.steps.length;
    if (job.status === "running") {
      await new Promise((resolve) => window.setTimeout(resolve, 350));
      continue;
    }
    state.progressRunning = false;
    dialog.querySelector(".modal-body").setAttribute("aria-busy", "false");
    byId("progress-confirm").disabled = false;
    if (job.status === "success") {
      byId("progress-state").textContent = job.warning ? "完成，有提示" : "已完成";
      byId("progress-icon").classList.add("is-done");
      if (job.warning) {
        byId("progress-warning").textContent = job.warning;
        byId("progress-warning").hidden = false;
      }
      await refreshBootstrap({ preserveDetail: false });
    } else {
      byId("progress-state").textContent = "失败";
      byId("progress-icon").classList.add("is-error");
      byId("progress-error").textContent = job.error || "操作失败，未提供详细原因。";
      byId("progress-error").hidden = false;
    }
    byId("progress-confirm").focus();
    break;
  }
}

async function startJob(endpoint, body) {
  try {
    const result = await api(endpoint, { method: "POST", body });
    await showJob(result.jobId);
  } catch (error) {
    await showNotice("无法启动操作", error.message, "知道了");
  }
}

async function addSave() {
  try {
    const picked = await api("/api/pick-folder", {
      method: "POST",
      body: { initial: "", title: "选择要添加的 Minecraft 存档文件夹" },
    });
    if (!picked.path) return;
    const check = await api("/api/import/check", {
      method: "POST",
      body: { sourcePath: picked.path },
    });
    let overwrite = false;
    if (check.conflict) {
      overwrite = await askConfirmation({
        title: `替换同名存档“${check.name}”？`,
        message: "管理目录中已经有同名存档。继续会完整替换旧存档，而不是合并文件。",
        acceptText: "替换存档",
      });
      if (!overwrite) return;
    }
    await startJob("/api/jobs/import", { sourcePath: picked.path, overwrite });
  } catch (error) {
    await showNotice("无法添加存档", error.message, "知道了");
  }
}

async function requestDelete(save) {
  const confirmed = await askConfirmation({
    title: `删除“${save}”？`,
    message: "这会删除 saves 管理目录中的整个存档。此操作无法通过中继站撤销。",
    acceptText: "删除存档",
  });
  if (confirmed) await startJob("/api/jobs/delete", { save });
}

function bindEvents() {
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.addEventListener("click", (event) => {
      if (
        button instanceof HTMLAnchorElement
        && (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)
      ) return;
      if (button instanceof HTMLAnchorElement) event.preventDefault();
      switchView(button.dataset.viewTarget);
    });
  });
  document.querySelectorAll("[data-inventory-target]").forEach((button) => {
    button.addEventListener("click", () => switchInventory(button.dataset.inventoryTarget));
  });

  byId("home-version").addEventListener("change", () => {
    const selected = Boolean(byId("home-version").value);
    byId("home-save").disabled = !selected;
    byId("home-save").value = "";
    resetPlayerSelect("请先选择存档");
    updateHomeReady();
  });
  byId("home-save").addEventListener("change", loadHomePlayers);
  byId("home-player").addEventListener("change", updateHomeReady);
  byId("relay-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (byId("start-replace").disabled) return;
    await startJob("/api/jobs/replace", {
      version: byId("home-version").value,
      save: byId("home-save").value,
      uid: byId("home-player").value,
    });
  });

  byId("pick-minecraft").addEventListener("click", () => pickFolder(byId("minecraft-path"), "选择 .minecraft 文件夹"));
  byId("pick-saves").addEventListener("click", () => pickFolder(byId("saves-path"), "选择联机存档 saves 文件夹"));
  byId("settings-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = byId("settings-message");
    const submit = byId("settings-submit");
    submit.disabled = true;
    submit.textContent = "正在保存…";
    message.textContent = "正在验证路径…";
    try {
      state.bootstrap = await api("/api/settings", {
        method: "POST",
        body: {
          minecraftPath: byId("minecraft-path").value,
          savesPath: byId("saves-path").value,
        },
      });
      message.textContent = "路径已保存。";
      renderStatus();
      renderHomeSelectors();
      renderInventory(false);
    } catch (error) {
      message.textContent = error.message;
    } finally {
      submit.disabled = false;
      submit.textContent = "保存路径";
    }
  });

  byId("refresh-inventory").addEventListener("click", async () => {
    try {
      await refreshBootstrap({ preserveDetail: true });
    } catch (error) {
      await showNotice("刷新失败", error.message, "知道了");
    }
  });
  byId("add-save").addEventListener("click", addSave);
  byId("progress-confirm").addEventListener("click", () => byId("progress-dialog").close());
  byId("progress-dialog").addEventListener("cancel", (event) => {
    if (state.progressRunning) event.preventDefault();
  });
}

async function init() {
  bindEvents();
  const params = new URLSearchParams(window.location.search);
  const initialView = params.get("view") === "manage" ? "manage" : "home";
  const initialInventory = params.get("list") === "saves" ? "saves" : "versions";
  switchInventory(initialInventory, false);
  switchView(initialView, false);
  syncUrl("replace");
  window.addEventListener("popstate", () => {
    const current = new URLSearchParams(window.location.search);
    switchInventory(current.get("list") === "saves" ? "saves" : "versions", false);
    switchView(current.get("view") === "manage" ? "manage" : "home", false);
  });
  try {
    await refreshBootstrap({ preserveDetail: false });
  } catch (error) {
    byId("configuration-notice").hidden = false;
    byId("settings-message").textContent = error.message;
  }
}

document.addEventListener("DOMContentLoaded", init);
