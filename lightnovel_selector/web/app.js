(() => {
  "use strict";

  const mockMode = new URLSearchParams(window.location.search).get("mock") === "1";
  const app = {
    initialized: false,
    snapshot: null,
    plans: [],
    selectedIndex: null,
    selectedDetail: null,
    plansRevision: -1,
    logCursor: 0,
    lastOperationKey: "",
    lastInput: "pointer",
    detailToken: 0,
    pollTimer: null,
    syncInFlight: false,
    toasts: new Map(),
    mock: createMockBackend(),
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const ui = {};

  function cacheElements() {
    const ids = [
      "app-shell", "app-version", "phase-pill", "phase-text", "folder-path", "folder-hint",
      "settings-summary", "report-dot", "stat-total", "stat-ready", "stat-series", "stat-attention",
      "result-count", "search-input", "series-filter", "status-filter", "plan-rows", "empty-state",
      "empty-title", "empty-copy", "empty-action", "detail-empty", "detail-loading", "detail-content",
      "detail-status", "detail-cover", "cover-placeholder", "detail-title", "detail-meta", "detail-summary",
      "detail-file", "detail-target", "detail-note", "edit-button", "reveal-button", "subject-button",
      "operation-label", "operation-message", "progress-bar", "cancel-button", "undo-button", "scan-button",
      "apply-button", "choose-folder-button", "create-folder-button", "settings-button", "log-button",
      "log-drawer", "drawer-scrim", "close-log-button", "log-list", "settings-dialog", "setting-network",
      "setting-recursive", "setting-rename", "rules-list", "add-rule-button", "settings-error",
      "save-settings-button", "edit-dialog", "edit-series-input", "edit-file-hint", "edit-error",
      "save-edit-button", "confirm-dialog", "confirm-title", "confirm-copy", "confirm-facts",
      "confirm-apply-button", "create-dialog", "create-name-input", "create-error", "confirm-create-button",
      "report-dialog", "report-content", "open-report-button", "toast-stack", "step-folder", "step-scan",
      "step-review", "step-apply",
    ];
    for (const id of ids) ui[id] = document.getElementById(id);
    ui.progressTrack = $(".progress-track");
  }

  async function bridgeCall(method, ...args) {
    let response;
    if (mockMode) {
      const handler = app.mock[method];
      if (!handler) throw new Error(`模拟接口缺少 ${method}`);
      response = { ok: true, data: await handler(...args) };
    } else {
      const api = window.pywebview?.api;
      if (!api?.[method]) throw new Error("Python 桌面桥接尚未准备好。请通过 run.bat 或打包版启动。 ");
      response = await api[method](...args);
    }
    if (!response?.ok) throw new Error(response?.error || "操作失败，请查看日志。 ");
    return response.data;
  }

  function createMockBackend() {
    const plans = [
      {
        index: 0, file_name: "刀剑神域 第01卷 艾恩葛朗特.epub", extension: ".epub",
        source_path: "D:\\轻小说\\刀剑神域 第01卷 艾恩葛朗特.epub", series_name: "刀剑神域",
        series_key: "刀剑神域", target_dir: "D:\\轻小说\\刀剑神域",
        target_path: "D:\\轻小说\\刀剑神域\\刀剑神域 第01卷 艾恩葛朗特.epub",
        target_name: "刀剑神域 第01卷 艾恩葛朗特.epub", resolver_source: "Bangumi",
        confidence: 0.97, confidence_label: "97%", status: "ready", status_label: "可执行",
        note: "", duplicate_of: null, rename_to: null, metadata_title: "刀剑神域", metadata_url: "https://bgm.tv",
        has_local_cover: false, will_move: true,
      },
      {
        index: 1, file_name: "无职转生 13.epub", extension: ".epub",
        source_path: "D:\\轻小说\\无职转生 13.epub", series_name: "无职转生 ~到了异世界就拿出真本事~",
        series_key: "无职转生 ~到了异世界就拿出真本事~", target_dir: "D:\\轻小说\\无职转生",
        target_path: "D:\\轻小说\\无职转生\\无职转生 第13卷.epub", target_name: "无职转生 第13卷.epub",
        resolver_source: "自定义规则", confidence: 1, confidence_label: "100%", status: "ready",
        status_label: "可执行", note: "已按用户规则识别。", duplicate_of: null, rename_to: "无职转生 第13卷.epub",
        metadata_title: "无职转生", metadata_url: "https://bgm.tv", has_local_cover: true, will_move: true,
      },
      {
        index: 2, file_name: "SAO-copy.epub", extension: ".epub", source_path: "D:\\轻小说\\SAO-copy.epub",
        series_name: "SAO copy", series_key: "SAO copy", target_dir: "D:\\轻小说\\SAO copy",
        target_path: "D:\\轻小说\\SAO-copy.epub", target_name: "SAO-copy.epub", resolver_source: "重复文件检测",
        confidence: 1, confidence_label: "100%", status: "duplicate", status_label: "重复",
        note: "与 刀剑神域 第01卷 艾恩葛朗特.epub 内容重复，默认跳过。", duplicate_of: "D:\\轻小说\\刀剑神域 第01卷.epub",
        rename_to: null, metadata_title: null, metadata_url: null, has_local_cover: false, will_move: false,
      },
      {
        index: 3, file_name: "86 第01卷.txt", extension: ".txt", source_path: "D:\\轻小说\\86 第01卷.txt",
        series_name: "86", series_key: "86", target_dir: "D:\\轻小说\\86",
        target_path: "D:\\轻小说\\86\\86 第01卷.txt", target_name: "86 第01卷.txt", resolver_source: "本地规则",
        confidence: 0.55, confidence_label: "55%", status: "ready", status_label: "可执行", note: "",
        duplicate_of: null, rename_to: null, metadata_title: "86—不存在的战区—", metadata_url: "https://bgm.tv",
        has_local_cover: false, will_move: true,
      },
    ];
    const state = {
      app: { name: "Light Novel Selector", version: "2.0.0" },
      folder: "D:\\轻小说\\待整理",
      settings: { use_network: true, recursive: false, auto_rename: true, custom_rules: [{ pattern: "*无职转生*", series: "无职转生 ~到了异世界就拿出真本事~" }], last_folder: "D:\\轻小说\\待整理" },
      operation: { id: 1, kind: "scan", state: "success", message: "预览完成，共识别 4 个文件。", done: 4, total: 4, can_cancel: false, error: null },
      counts: { total: 4, ready: 3, duplicate: 1, error: 0, unchanged: 0, moved: 0, series: 4 },
      report_path: "D:\\轻小说\\待整理\\classification_report.json",
      plans_revision: 1,
      plans,
      logs: [
        { id: 1, time: "14:21:03", kind: "info", message: "已选择目录：D:\\轻小说\\待整理" },
        { id: 2, time: "14:21:05", kind: "success", message: "预览完成，共识别 4 个文件。" },
      ],
      log_cursor: 2,
    };
    const clone = (value) => JSON.parse(JSON.stringify(value));
    return {
      bootstrap: async () => clone(state),
      poll: async (cursor, revision) => {
        const result = clone(state);
        if (Number(revision) === state.plans_revision) result.plans = null;
        result.logs = state.logs.filter((item) => item.id > Number(cursor));
        return result;
      },
      choose_folder: async () => ({ cancelled: true }),
      create_folder: async () => ({ cancelled: true }),
      save_settings: async (payload) => {
        state.settings = { ...state.settings, ...clone(payload) };
        return { saved: true, warning: null, state: clone(state) };
      },
      start_scan: async () => clone(state),
      cancel_operation: async () => ({ cancelled: true, state: clone(state) }),
      start_apply: async () => clone(state),
      start_undo: async () => clone(state),
      edit_plan: async (index, seriesName) => {
        state.plans[Number(index)].series_name = seriesName;
        state.plans[Number(index)].series_key = seriesName;
        state.plans[Number(index)].resolver_source = "手动修正";
        state.plans_revision += 1;
        return clone(state);
      },
      get_detail: async (index) => {
        const plan = state.plans[Number(index)];
        return {
          index: Number(index), title: plan.metadata_title || plan.series_name,
          summary: "这是一段用于界面检查的作品简介。正式运行时会优先显示电子书本地封面，并在允许联网时读取在线条目详情。",
          subject_url: plan.metadata_url, cover_data_url: null, cover_source: "无封面", file_name: plan.file_name,
          source_path: plan.source_path, target_path: plan.target_path, series_name: plan.series_name,
          resolver_source: plan.resolver_source, confidence_label: plan.confidence_label, status: plan.status,
          status_label: plan.status_label, note: plan.note, warning: null,
        };
      },
      get_report: async () => ({
        path: state.report_path, created_at: "2026-07-20T14:21:05",
        summary: { total: 4, moved: 3, skipped: 1, duplicates: 1, errors: 0 },
        items: state.plans.map((plan) => ({ source_path: plan.source_path, target_path: plan.target_path, operation: plan.will_move ? "moved" : "skipped" })),
      }),
      open_folder: async () => true,
      open_report: async () => true,
      reveal_plan: async () => true,
      open_subject: async () => true,
    };
  }

  function bindEvents() {
    document.addEventListener("pointerdown", () => {
      app.lastInput = "pointer";
      document.body.classList.remove("keyboard-mode");
    }, true);
    document.addEventListener("keydown", (event) => {
      app.lastInput = "keyboard";
      document.body.classList.add("keyboard-mode");
      handleShortcut(event);
    }, true);

    ui["choose-folder-button"].addEventListener("click", chooseFolder);
    ui["create-folder-button"].addEventListener("click", () => openDialog(ui["create-dialog"], ui["create-name-input"]));
    ui["empty-action"].addEventListener("click", handleEmptyAction);
    ui["scan-button"].addEventListener("click", startScan);
    ui["apply-button"].addEventListener("click", () => openConfirmation("apply"));
    ui["undo-button"].addEventListener("click", () => openConfirmation("undo"));
    ui["cancel-button"].addEventListener("click", cancelOperation);
    ui["settings-button"].addEventListener("click", openSettings);
    ui["log-button"].addEventListener("click", openLogDrawer);
    ui["close-log-button"].addEventListener("click", closeLogDrawer);
    ui["drawer-scrim"].addEventListener("click", closeLogDrawer);
    ui["search-input"].addEventListener("input", renderPlans);
    ui["series-filter"].addEventListener("change", renderPlans);
    ui["status-filter"].addEventListener("change", renderPlans);
    ui["plan-rows"].addEventListener("click", onPlanRowAction);
    ui["plan-rows"].addEventListener("keydown", onPlanRowKeydown);
    ui["edit-button"].addEventListener("click", openEditDialog);
    ui["reveal-button"].addEventListener("click", revealSelectedPlan);
    ui["subject-button"].addEventListener("click", openSelectedSubject);
    ui["add-rule-button"].addEventListener("click", () => addRuleRow());
    ui["rules-list"].addEventListener("click", onRuleAction);
    ui["settings-dialog"].querySelector("form").addEventListener("submit", saveSettings);
    ui["edit-dialog"].querySelector("form").addEventListener("submit", saveEdit);
    ui["confirm-dialog"].querySelector("form").addEventListener("submit", confirmOperation);
    ui["create-dialog"].querySelector("form").addEventListener("submit", createFolder);
    ui["open-report-button"].addEventListener("click", openReportFile);

    for (const button of $$(".dialog-close")) {
      button.addEventListener("click", () => closeDialog(button.closest("dialog")));
    }
    for (const dialog of $$('dialog')) {
      dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        closeDialog(dialog);
      });
      dialog.addEventListener("pointerdown", (event) => {
        if (event.target === dialog) closeDialog(dialog);
      });
    }
    for (const item of $$(".nav-item")) {
      item.addEventListener("click", () => handleNavigation(item.dataset.action));
    }
  }

  async function initialize() {
    if (app.initialized) return;
    app.initialized = true;
    cacheElements();
    bindEvents();
    try {
      const snapshot = await bridgeCall("bootstrap");
      applySnapshot(snapshot, { initial: true });
      ui["app-shell"].setAttribute("aria-busy", "false");
      schedulePoll(350);
      if (mockMode) {
        const panel = new URLSearchParams(window.location.search).get("panel");
        if (panel === "settings") openSettings();
        else if (panel === "confirm") openConfirmation("apply");
        else if (panel === "detail") selectPlan(0);
      }
    } catch (error) {
      ui["app-shell"].setAttribute("aria-busy", "false");
      showToast(error.message, "error", true);
      ui["phase-text"].textContent = "启动失败";
      ui["phase-pill"].className = "phase-pill phase-error";
      ui["operation-message"].textContent = error.message;
    }
  }

  function schedulePoll(delay) {
    window.clearTimeout(app.pollTimer);
    app.pollTimer = window.setTimeout(pollState, delay);
  }

  async function pollState() {
    if (app.syncInFlight) {
      schedulePoll(300);
      return;
    }
    app.syncInFlight = true;
    try {
      const snapshot = await bridgeCall("poll", app.logCursor, app.plansRevision);
      applySnapshot(snapshot);
    } catch (error) {
      if (!document.hidden) showToast(error.message, "error");
    } finally {
      app.syncInFlight = false;
      const running = app.snapshot?.operation?.state === "running";
      schedulePoll(document.hidden ? 1800 : running ? 180 : 900);
    }
  }

  function applySnapshot(snapshot, options = {}) {
    if (!snapshot) return;
    const previousOperationKey = app.lastOperationKey;
    app.snapshot = snapshot;
    app.logCursor = snapshot.log_cursor ?? app.logCursor;
    if (snapshot.plans !== null && snapshot.plans !== undefined) {
      app.plans = snapshot.plans;
      app.plansRevision = snapshot.plans_revision;
      updateFilters();
      if (app.selectedIndex !== null && !app.plans.some((plan) => plan.index === app.selectedIndex)) {
        app.selectedIndex = null;
        app.selectedDetail = null;
      }
      renderPlans();
      if (app.selectedIndex !== null) loadDetail(app.selectedIndex);
    } else {
      app.plansRevision = snapshot.plans_revision;
    }
    appendLogs(snapshot.logs || []);
    renderSnapshot();

    const operation = snapshot.operation || {};
    const operationKey = `${operation.id}:${operation.state}`;
    app.lastOperationKey = operationKey;
    if (!options.initial && operationKey !== previousOperationKey && ["success", "error", "cancelled"].includes(operation.state)) {
      const kind = operation.state === "success" ? "success" : operation.state === "cancelled" ? "warning" : "error";
      showToast(operation.error ? `${operation.message}：${operation.error}` : operation.message, kind, app.lastInput === "keyboard");
    }
  }

  function renderSnapshot() {
    const snapshot = app.snapshot;
    if (!snapshot) return;
    const { counts, operation, settings } = snapshot;
    ui["app-version"].textContent = `v${snapshot.app.version}`;
    ui["folder-path"].textContent = snapshot.folder || "尚未选择目录";
    ui["folder-path"].title = snapshot.folder || "";
    ui["folder-hint"].textContent = snapshot.folder ? "扫描前可在设置中调整识别方式" : "选择存放待整理小说的大文件夹";
    ui["report-dot"].hidden = !snapshot.report_path;
    ui["stat-total"].textContent = counts.total;
    ui["stat-ready"].textContent = counts.ready;
    ui["stat-series"].textContent = counts.series;
    ui["stat-attention"].textContent = counts.duplicate + counts.error;
    renderSettingsSummary(settings);
    renderOperation(operation, counts);
    renderWorkflow(snapshot, counts);
    refreshActionStates();
    renderEmptyState();
  }

  function renderSettingsSummary(settings) {
    ui["settings-summary"].replaceChildren();
    const items = [
      ["联网识别", settings.use_network],
      ["子目录", settings.recursive],
      ["自动重命名", settings.auto_rename],
    ];
    for (const [label, enabled] of items) {
      const chip = document.createElement("span");
      chip.className = `option-chip${enabled ? " is-on" : ""}`;
      chip.textContent = `${enabled ? "✓" : "□"} ${label}`;
      ui["settings-summary"].append(chip);
    }
  }

  function renderOperation(operation, counts) {
    const stateClass = operation.state === "running" ? "running" : operation.state === "success" ? "success" : operation.state === "error" ? "error" : operation.state === "cancelled" ? "warning" : "idle";
    const stateLabel = operation.state === "running" ? "处理中" : operation.state === "success" ? "已完成" : operation.state === "error" ? "需要处理" : operation.state === "cancelled" ? "已停止" : "准备就绪";
    ui["phase-pill"].className = `phase-pill phase-${stateClass}`;
    ui["phase-text"].textContent = stateLabel;
    ui["operation-label"].textContent = operation.state === "running" ? operation.kind === "scan" ? "扫描进度" : operation.kind === "apply" ? "分类进度" : "撤销进度" : counts.ready > 0 ? "等待确认" : "下一步";
    ui["operation-message"].textContent = operation.message || "选择目录后扫描，先核对预览再执行分类。";

    const total = Number(operation.total || 0);
    const done = Number(operation.done || 0);
    const ratio = total > 0 ? Math.max(0, Math.min(1, done / total)) : operation.state === "success" ? 1 : 0;
    ui["progress-bar"].style.transform = `scaleX(${ratio})`;
    ui.progressTrack.classList.toggle("is-indeterminate", operation.state === "running" && total === 0);
    ui.progressTrack.classList.toggle("is-error", operation.state === "error");
    ui.progressTrack.classList.toggle("is-success", operation.state === "success");
    ui.progressTrack.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
    ui["cancel-button"].hidden = !(operation.state === "running" && operation.can_cancel);
  }

  function renderWorkflow(snapshot, counts) {
    const steps = [ui["step-folder"], ui["step-scan"], ui["step-review"], ui["step-apply"]];
    steps.forEach((step) => step.classList.remove("is-current", "is-complete"));
    if (!snapshot.folder) {
      steps[0].classList.add("is-current");
      return;
    }
    steps[0].classList.add("is-complete");
    if (snapshot.operation.state === "running" && snapshot.operation.kind === "scan") {
      steps[1].classList.add("is-current");
      return;
    }
    if (counts.total === 0) {
      steps[1].classList.add("is-current");
      return;
    }
    steps[1].classList.add("is-complete");
    if (counts.moved > 0 || (snapshot.operation.kind === "apply" && snapshot.operation.state === "success")) {
      steps[2].classList.add("is-complete");
      steps[3].classList.add("is-complete");
    } else {
      steps[2].classList.add("is-current");
    }
  }

  function refreshActionStates() {
    const snapshot = app.snapshot;
    if (!snapshot) return;
    const busy = snapshot.operation.state === "running";
    const hasFolder = Boolean(snapshot.folder);
    const hasReady = snapshot.counts.ready > 0;
    const selected = app.plans.find((plan) => plan.index === app.selectedIndex);
    ui["choose-folder-button"].disabled = busy;
    ui["create-folder-button"].disabled = busy;
    ui["settings-button"].disabled = busy;
    ui["scan-button"].disabled = busy || !hasFolder;
    ui["apply-button"].disabled = busy || !hasReady;
    ui["undo-button"].disabled = busy || !snapshot.report_path;
    ui["edit-button"].disabled = busy || !selected || selected.status === "moved";
    ui["reveal-button"].disabled = !selected;
    ui["subject-button"].disabled = !app.selectedDetail?.subject_url;
  }

  function updateFilters() {
    const selected = ui["series-filter"]?.value || "";
    const series = [...new Set(app.plans.map((plan) => plan.series_key || plan.series_name))].sort((a, b) => a.localeCompare(b, "zh-CN"));
    ui["series-filter"].replaceChildren(new Option("全部系列", ""));
    for (const name of series) ui["series-filter"].add(new Option(name, name));
    ui["series-filter"].value = series.includes(selected) ? selected : "";
  }

  function filteredPlans() {
    const query = ui["search-input"].value.trim().toLocaleLowerCase("zh-CN");
    const series = ui["series-filter"].value;
    const status = ui["status-filter"].value;
    return app.plans.filter((plan) => {
      const matchesQuery = !query || `${plan.file_name} ${plan.series_name} ${plan.resolver_source}`.toLocaleLowerCase("zh-CN").includes(query);
      const matchesSeries = !series || (plan.series_key || plan.series_name) === series;
      const matchesStatus = !status || plan.status === status;
      return matchesQuery && matchesSeries && matchesStatus;
    });
  }

  function renderPlans() {
    if (!ui["plan-rows"]) return;
    const plans = filteredPlans();
    const fragment = document.createDocumentFragment();
    for (const plan of plans) {
      const row = document.createElement("tr");
      row.dataset.index = String(plan.index);
      row.tabIndex = 0;
      row.classList.toggle("is-selected", plan.index === app.selectedIndex);
      row.setAttribute("aria-selected", String(plan.index === app.selectedIndex));

      const statusCell = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = `status-badge status-${plan.status}`;
      badge.textContent = plan.status_label;
      statusCell.append(badge);

      const fileCell = document.createElement("td");
      const fileWrap = document.createElement("span");
      fileWrap.className = "file-cell";
      fileWrap.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#icon-file"></use></svg>';
      const fileName = document.createElement("span");
      fileName.textContent = plan.file_name;
      fileName.title = plan.source_path;
      fileWrap.append(fileName);
      fileCell.append(fileWrap);

      const seriesCell = document.createElement("td");
      seriesCell.textContent = plan.series_name;
      seriesCell.title = plan.target_path;
      const confidenceCell = document.createElement("td");
      confidenceCell.className = "confidence-cell";
      confidenceCell.textContent = plan.confidence_label;
      const sourceCell = document.createElement("td");
      sourceCell.textContent = plan.resolver_source;

      row.append(statusCell, fileCell, seriesCell, confidenceCell, sourceCell);
      fragment.append(row);
    }
    ui["plan-rows"].replaceChildren(fragment);
    ui["result-count"].textContent = `${plans.length} 项`;
    renderEmptyState();
  }

  function renderEmptyState() {
    if (!ui["empty-state"] || !app.snapshot) return;
    const filtered = filteredPlans();
    const runningScan = app.snapshot.operation.state === "running" && app.snapshot.operation.kind === "scan";
    ui["empty-state"].hidden = filtered.length > 0;
    if (filtered.length > 0) return;
    if (runningScan) {
      ui["empty-title"].textContent = "正在扫描目录";
      ui["empty-copy"].textContent = "识别结果会在准备好后一次显示，原文件此时不会移动。";
      ui["empty-action"].hidden = true;
    } else if (!app.snapshot.folder) {
      ui["empty-title"].textContent = "从选择目录开始";
      ui["empty-copy"].textContent = "扫描只会生成预览，不会移动任何文件。";
      ui["empty-action"].textContent = "选择目录";
      ui["empty-action"].dataset.action = "choose";
      ui["empty-action"].hidden = false;
    } else if (app.plans.length === 0) {
      ui["empty-title"].textContent = "没有找到可分类文件";
      ui["empty-copy"].textContent = "可检查文件扩展名，或在设置中开启子文件夹扫描。";
      ui["empty-action"].textContent = "重新扫描";
      ui["empty-action"].dataset.action = "scan";
      ui["empty-action"].hidden = false;
    } else {
      ui["empty-title"].textContent = "当前筛选没有结果";
      ui["empty-copy"].textContent = "清除搜索词或切换系列、状态筛选。";
      ui["empty-action"].textContent = "清除筛选";
      ui["empty-action"].dataset.action = "clear";
      ui["empty-action"].hidden = false;
    }
  }

  function onPlanRowAction(event) {
    const row = event.target.closest("tr[data-index]");
    if (row) selectPlan(Number(row.dataset.index));
  }

  function onPlanRowKeydown(event) {
    const row = event.target.closest("tr[data-index]");
    if (!row || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    selectPlan(Number(row.dataset.index));
  }

  function selectPlan(index) {
    app.selectedIndex = index;
    for (const row of $$("tr[data-index]", ui["plan-rows"])) {
      const selected = Number(row.dataset.index) === index;
      row.classList.toggle("is-selected", selected);
      row.setAttribute("aria-selected", String(selected));
    }
    loadDetail(index);
    refreshActionStates();
  }

  async function loadDetail(index) {
    const token = ++app.detailToken;
    ui["detail-empty"].hidden = true;
    ui["detail-content"].hidden = true;
    ui["detail-loading"].hidden = false;
    ui["detail-status"].textContent = "读取中";
    ui["detail-status"].className = "detail-status status-neutral";
    try {
      const detail = await bridgeCall("get_detail", index);
      if (token !== app.detailToken || app.selectedIndex !== index) return;
      app.selectedDetail = detail;
      renderDetail(detail);
    } catch (error) {
      if (token !== app.detailToken) return;
      ui["detail-loading"].hidden = true;
      ui["detail-empty"].hidden = false;
      $("p", ui["detail-empty"]).textContent = error.message;
      ui["detail-status"].textContent = "读取失败";
      ui["detail-status"].className = "detail-status status-error";
    } finally {
      refreshActionStates();
    }
  }

  function renderDetail(detail) {
    ui["detail-loading"].hidden = true;
    ui["detail-empty"].hidden = true;
    ui["detail-content"].hidden = false;
    ui["detail-status"].textContent = detail.status_label;
    ui["detail-status"].className = `detail-status status-${detail.status}`;
    ui["detail-title"].textContent = detail.title;
    ui["detail-meta"].textContent = `${detail.resolver_source} · ${detail.confidence_label} · ${detail.cover_source}`;
    ui["detail-summary"].textContent = detail.summary;
    ui["detail-file"].textContent = detail.file_name;
    ui["detail-file"].title = detail.source_path;
    ui["detail-target"].textContent = detail.target_path;
    ui["detail-target"].title = detail.target_path;
    ui["detail-note"].textContent = detail.warning || detail.note || "无";
    if (detail.cover_data_url) {
      ui["detail-cover"].src = detail.cover_data_url;
      ui["detail-cover"].alt = `${detail.title} 封面`;
      ui["detail-cover"].hidden = false;
      ui["cover-placeholder"].hidden = true;
    } else {
      ui["detail-cover"].removeAttribute("src");
      ui["detail-cover"].hidden = true;
      ui["cover-placeholder"].hidden = false;
    }
    ui["subject-button"].hidden = !detail.subject_url;
  }

  function openSettings() {
    const settings = app.snapshot.settings;
    ui["setting-network"].checked = settings.use_network;
    ui["setting-recursive"].checked = settings.recursive;
    ui["setting-rename"].checked = settings.auto_rename;
    ui["rules-list"].replaceChildren();
    for (const rule of settings.custom_rules || []) addRuleRow(rule);
    if (!(settings.custom_rules || []).length) addRuleRow();
    hideFormError(ui["settings-error"]);
    openDialog(ui["settings-dialog"], ui["setting-network"]);
  }

  function addRuleRow(rule = {}) {
    const row = document.createElement("div");
    row.className = "rule-row";
    const pattern = document.createElement("input");
    pattern.className = "rule-pattern";
    pattern.type = "text";
    pattern.maxLength = 160;
    pattern.placeholder = "例如 *SAO*";
    pattern.value = rule.pattern || "";
    pattern.setAttribute("aria-label", "文件匹配模式");
    const arrow = document.createElement("span");
    arrow.textContent = "→";
    const series = document.createElement("input");
    series.className = "rule-series";
    series.type = "text";
    series.maxLength = 120;
    series.placeholder = "目标系列";
    series.value = rule.series || "";
    series.setAttribute("aria-label", "目标系列名称");
    const remove = document.createElement("button");
    remove.className = "icon-button remove-rule";
    remove.type = "button";
    remove.title = "删除规则";
    remove.setAttribute("aria-label", "删除规则");
    remove.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#icon-trash"></use></svg>';
    row.append(pattern, arrow, series, remove);
    ui["rules-list"].append(row);
  }

  function onRuleAction(event) {
    const remove = event.target.closest(".remove-rule");
    if (!remove) return;
    remove.closest(".rule-row")?.remove();
    if (!ui["rules-list"].children.length) addRuleRow();
  }

  function readRuleRows() {
    const rules = [];
    for (const [index, row] of $$(".rule-row", ui["rules-list"]).entries()) {
      const pattern = $(".rule-pattern", row).value.trim();
      const series = $(".rule-series", row).value.trim();
      if (!pattern && !series) continue;
      if (!pattern || !series) throw new Error(`第 ${index + 1} 条规则需要同时填写匹配模式和系列名。`);
      rules.push({ pattern, series });
    }
    return rules;
  }

  async function saveSettings(event) {
    event.preventDefault();
    hideFormError(ui["settings-error"]);
    try {
      const payload = {
        use_network: ui["setting-network"].checked,
        recursive: ui["setting-recursive"].checked,
        auto_rename: ui["setting-rename"].checked,
        custom_rules: readRuleRows(),
      };
      setButtonBusy(ui["save-settings-button"], true, "保存中…");
      const result = await bridgeCall("save_settings", payload);
      applySnapshot(result.state);
      closeDialog(ui["settings-dialog"]);
      showToast(result.warning || "设置已保存。", result.warning ? "warning" : "success");
    } catch (error) {
      showFormError(ui["settings-error"], error.message);
    } finally {
      setButtonBusy(ui["save-settings-button"], false);
    }
  }

  function openEditDialog() {
    const plan = app.plans.find((item) => item.index === app.selectedIndex);
    if (!plan || plan.status === "moved") return;
    ui["edit-series-input"].value = plan.series_name;
    ui["edit-file-hint"].textContent = `文件：${plan.file_name}`;
    hideFormError(ui["edit-error"]);
    openDialog(ui["edit-dialog"], ui["edit-series-input"]);
  }

  async function saveEdit(event) {
    event.preventDefault();
    const series = ui["edit-series-input"].value.trim();
    if (!series) {
      showFormError(ui["edit-error"], "系列名不能为空。 ");
      return;
    }
    try {
      setButtonBusy(ui["save-edit-button"], true, "修正中…");
      const snapshot = await bridgeCall("edit_plan", app.selectedIndex, series);
      applySnapshot(snapshot);
      closeDialog(ui["edit-dialog"]);
      showToast("分类目标已修正，请重新核对目标路径。", "success");
    } catch (error) {
      showFormError(ui["edit-error"], error.message);
    } finally {
      setButtonBusy(ui["save-edit-button"], false);
    }
  }

  function openConfirmation(mode) {
    const counts = app.snapshot.counts;
    ui["confirm-dialog"].dataset.mode = mode;
    ui["confirm-facts"].replaceChildren();
    if (mode === "undo") {
      ui["confirm-title"].textContent = "确认撤销上次分类";
      ui["confirm-copy"].textContent = "软件会按最近报告恢复已移动文件。若原位置已有同名文件，对应条目将安全跳过。";
      addConfirmFact("报告", app.snapshot.report_path ? "可用" : "缺失");
      addConfirmFact("当前条目", String(counts.total));
      addConfirmFact("行为", "恢复文件");
      setButtonLabel(ui["confirm-apply-button"], "确认撤销");
    } else {
      ui["confirm-title"].textContent = "确认执行分类";
      ui["confirm-copy"].textContent = "执行后会移动文件并立即写入撤销报告。重复项、错误项和无需移动项会跳过。";
      addConfirmFact("将移动", String(counts.ready));
      addConfirmFact("将跳过", String(counts.total - counts.ready));
      addConfirmFact("作品系列", String(counts.series));
      setButtonLabel(ui["confirm-apply-button"], "确认执行");
    }
    openDialog(ui["confirm-dialog"], ui["confirm-apply-button"]);
  }

  function addConfirmFact(label, value) {
    const item = document.createElement("div");
    item.className = "confirm-fact";
    const strong = document.createElement("strong");
    strong.textContent = value;
    const span = document.createElement("span");
    span.textContent = label;
    item.append(strong, span);
    ui["confirm-facts"].append(item);
  }

  async function confirmOperation(event) {
    event.preventDefault();
    const mode = ui["confirm-dialog"].dataset.mode;
    try {
      setButtonBusy(ui["confirm-apply-button"], true, mode === "undo" ? "开始撤销…" : "开始执行…");
      const snapshot = await bridgeCall(mode === "undo" ? "start_undo" : "start_apply");
      applySnapshot(snapshot);
      closeDialog(ui["confirm-dialog"]);
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setButtonBusy(ui["confirm-apply-button"], false);
    }
  }

  async function chooseFolder() {
    try {
      setButtonBusy(ui["choose-folder-button"], true, "选择中…");
      const result = await bridgeCall("choose_folder");
      if (!result.cancelled) {
        applySnapshot(result.state);
        showToast("目录已选择，可以开始扫描。", "success");
      }
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setButtonBusy(ui["choose-folder-button"], false);
    }
  }

  async function createFolder(event) {
    event.preventDefault();
    const name = ui["create-name-input"].value.trim();
    if (!name) {
      showFormError(ui["create-error"], "目录名称不能为空。 ");
      return;
    }
    hideFormError(ui["create-error"]);
    try {
      setButtonBusy(ui["confirm-create-button"], true, "创建中…");
      const result = await bridgeCall("create_folder", name);
      if (!result.cancelled) {
        applySnapshot(result.state);
        closeDialog(ui["create-dialog"]);
        showToast("整理目录已创建并选中。", "success");
      }
    } catch (error) {
      showFormError(ui["create-error"], error.message);
    } finally {
      setButtonBusy(ui["confirm-create-button"], false);
    }
  }

  async function startScan() {
    try {
      const snapshot = await bridgeCall("start_scan");
      app.selectedIndex = null;
      app.selectedDetail = null;
      resetDetail();
      applySnapshot(snapshot);
    } catch (error) {
      showToast(error.message, "error", app.lastInput === "keyboard");
    }
  }

  async function cancelOperation() {
    try {
      const result = await bridgeCall("cancel_operation");
      applySnapshot(result.state);
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  function resetDetail() {
    app.detailToken += 1;
    ui["detail-content"].hidden = true;
    ui["detail-loading"].hidden = true;
    ui["detail-empty"].hidden = false;
    ui["detail-status"].textContent = "未选择";
    ui["detail-status"].className = "detail-status status-neutral";
  }

  function handleEmptyAction() {
    const action = ui["empty-action"].dataset.action;
    if (action === "scan") startScan();
    else if (action === "clear") {
      ui["search-input"].value = "";
      ui["series-filter"].value = "";
      ui["status-filter"].value = "";
      renderPlans();
    } else chooseFolder();
  }

  function openLogDrawer() {
    ui["drawer-scrim"].hidden = false;
    ui["log-drawer"].setAttribute("aria-hidden", "false");
    window.requestAnimationFrame(() => {
      ui["drawer-scrim"].classList.add("is-visible");
      ui["log-drawer"].classList.add("is-open");
    });
    ui["close-log-button"].focus({ preventScroll: true });
  }

  function closeLogDrawer() {
    ui["drawer-scrim"].classList.remove("is-visible");
    ui["log-drawer"].classList.remove("is-open");
    ui["log-drawer"].setAttribute("aria-hidden", "true");
    window.setTimeout(() => { ui["drawer-scrim"].hidden = true; }, 190);
  }

  function appendLogs(logs) {
    if (!ui["log-list"]) return;
    for (const item of logs) {
      if (ui["log-list"].querySelector(`[data-log-id="${item.id}"]`)) continue;
      const entry = document.createElement("li");
      entry.className = `log-entry kind-${item.kind}`;
      entry.dataset.logId = String(item.id);
      const time = document.createElement("time");
      time.textContent = item.time;
      const dot = document.createElement("i");
      dot.setAttribute("aria-hidden", "true");
      const message = document.createElement("span");
      message.textContent = item.message;
      entry.append(time, dot, message);
      ui["log-list"].append(entry);
    }
    while (ui["log-list"].children.length > 300) ui["log-list"].firstElementChild.remove();
    if (logs.length) ui["log-list"].scrollTop = ui["log-list"].scrollHeight;
  }

  async function showReport() {
    try {
      const report = await bridgeCall("get_report");
      renderReport(report);
      openDialog(ui["report-dialog"], ui["open-report-button"]);
    } catch (error) {
      showToast(error.message, "error", app.lastInput === "keyboard");
    }
  }

  function renderReport(report) {
    ui["report-content"].replaceChildren();
    const summary = report.summary || {};
    const grid = document.createElement("div");
    grid.className = "report-summary-grid";
    for (const [label, value] of [["总计", summary.total || 0], ["已移动", summary.moved || 0], ["已跳过", summary.skipped || 0], ["错误", summary.errors || 0]]) {
      const item = document.createElement("div");
      const strong = document.createElement("strong");
      strong.textContent = String(value);
      const span = document.createElement("span");
      span.textContent = label;
      item.append(strong, span);
      grid.append(item);
    }
    const time = document.createElement("p");
    time.className = "report-time";
    time.textContent = `生成时间：${report.created_at || "未知"} · ${report.path}`;
    const items = document.createElement("ol");
    items.className = "report-items";
    for (const record of (report.items || []).slice(0, 12)) {
      const row = document.createElement("li");
      row.className = "report-item";
      const source = document.createElement("span");
      source.textContent = String(record.source_path || "").split(/[\\/]/).pop() || "未知文件";
      const operation = document.createElement("span");
      operation.textContent = record.operation === "moved" ? "已移动" : "已跳过";
      row.append(source, operation);
      items.append(row);
    }
    ui["report-content"].append(grid, time, items);
  }

  async function openReportFile() {
    try {
      await bridgeCall("open_report");
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function revealSelectedPlan() {
    if (app.selectedIndex === null) return;
    try {
      await bridgeCall("reveal_plan", app.selectedIndex);
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function openSelectedSubject() {
    if (!app.selectedDetail?.subject_url) return;
    try {
      await bridgeCall("open_subject", app.selectedDetail.subject_url);
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  function handleNavigation(action) {
    if (action === "settings") openSettings();
    else if (action === "report") showReport();
  }

  function handleShortcut(event) {
    if (!app.initialized || event.defaultPrevented) return;
    const control = event.ctrlKey || event.metaKey;
    const target = event.target;
    const typing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;
    if (event.key === "Escape" && ui["log-drawer"]?.classList.contains("is-open")) {
      event.preventDefault();
      closeLogDrawer();
      return;
    }
    if (typing) return;
    if (control && event.key.toLocaleLowerCase() === "o") {
      event.preventDefault();
      chooseFolder();
    } else if (event.key === "F5") {
      event.preventDefault();
      if (!ui["scan-button"].disabled) startScan();
    } else if (control && event.key === "Enter") {
      event.preventDefault();
      if (!ui["apply-button"].disabled) openConfirmation("apply");
    } else if (control && event.key.toLocaleLowerCase() === "r") {
      event.preventDefault();
      showReport();
    } else if (control && event.key.toLocaleLowerCase() === "z") {
      event.preventDefault();
      if (!ui["undo-button"].disabled) openConfirmation("undo");
    }
  }

  function openDialog(dialog, focusTarget) {
    if (!dialog || dialog.open) return;
    dialog.dataset.instant = String(app.lastInput === "keyboard");
    dialog.showModal();
    window.requestAnimationFrame(() => {
      dialog.dataset.state = "open";
      focusTarget?.focus({ preventScroll: true });
      if (focusTarget instanceof HTMLInputElement && focusTarget.type === "text") focusTarget.select();
    });
  }

  function closeDialog(dialog) {
    if (!dialog?.open) return;
    dialog.dataset.state = "closing";
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const delay = dialog.dataset.instant === "true" ? 0 : reducedMotion ? 125 : 145;
    window.setTimeout(() => {
      dialog.close();
      delete dialog.dataset.state;
      delete dialog.dataset.instant;
    }, delay);
  }

  function showFormError(element, message) {
    element.textContent = message;
    element.hidden = false;
  }

  function hideFormError(element) {
    element.textContent = "";
    element.hidden = true;
  }

  function setButtonLabel(button, label) {
    const span = $("span", button);
    if (span) span.textContent = label;
  }

  function setButtonBusy(button, busy, busyLabel = "处理中…") {
    if (!button) return;
    if (busy) {
      button.dataset.previousLabel = $("span", button)?.textContent || button.textContent;
      button.disabled = true;
      setButtonLabel(button, busyLabel);
    } else {
      button.disabled = false;
      if (button.dataset.previousLabel) setButtonLabel(button, button.dataset.previousLabel);
      delete button.dataset.previousLabel;
      refreshActionStates();
    }
  }

  function showToast(message, kind = "info", instant = false) {
    if (!ui["toast-stack"]) return;
    const toast = document.createElement("div");
    toast.className = `toast kind-${kind}`;
    toast.setAttribute("role", kind === "error" ? "alert" : "status");
    if (instant) toast.style.transitionDuration = "0ms";
    const dot = document.createElement("span");
    dot.className = "toast-dot";
    const copy = document.createElement("p");
    copy.textContent = message;
    toast.append(dot, copy);
    ui["toast-stack"].append(toast);
    window.requestAnimationFrame(() => toast.classList.add("is-visible"));

    const timer = { remaining: kind === "error" ? 5200 : 3800, started: 0, timeout: null };
    const start = () => {
      timer.started = performance.now();
      timer.timeout = window.setTimeout(() => dismissToast(toast), timer.remaining);
    };
    app.toasts.set(toast, timer);
    if (!document.hidden) start();
  }

  function dismissToast(toast) {
    const timer = app.toasts.get(toast);
    if (timer?.timeout) window.clearTimeout(timer.timeout);
    toast.classList.add("is-leaving");
    toast.classList.remove("is-visible");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const delay = toast.style.transitionDuration === "0ms" ? 0 : reducedMotion ? 125 : 160;
    window.setTimeout(() => toast.remove(), delay);
    app.toasts.delete(toast);
  }

  document.addEventListener("visibilitychange", () => {
    for (const [toast, timer] of app.toasts) {
      if (document.hidden && timer.timeout) {
        window.clearTimeout(timer.timeout);
        timer.timeout = null;
        timer.remaining = Math.max(300, timer.remaining - (performance.now() - timer.started));
      } else if (!document.hidden && !timer.timeout) {
        timer.started = performance.now();
        timer.timeout = window.setTimeout(() => dismissToast(toast), timer.remaining);
      }
    }
  });

  window.LightNovelApp = {
    notifyCriticalClose() {
      showToast("正在移动或恢复文件，操作完成前不能关闭窗口。", "warning", true);
    },
  };

  if (mockMode) {
    window.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    window.addEventListener("pywebviewready", initialize, { once: true });
    window.addEventListener("DOMContentLoaded", () => {
      if (window.pywebview?.api) initialize();
      window.setTimeout(() => {
        if (!app.initialized) initialize();
      }, 1600);
    }, { once: true });
  }
})();
