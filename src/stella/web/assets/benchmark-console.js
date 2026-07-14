const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  bootstrap: null,
  token: "",
  runs: [],
  activeRun: null,
  events: [],
  eventIds: new Set(),
  selectedEvent: null,
  selectedPaper: "",
  payload: null,
  payloadEnvelope: null,
  inspectorTab: "request",
  eventFilter: "all",
  source: null,
  preflight: null,
  startedAt: null,
  runIdTouched: false,
  payloadGeneration: 0,
  statusRefreshInFlight: false,
  terminalCloseTimer: null,
};

const FLOW = {
  B: [
    ["context", "CTX"], ["scaffold", "SCAF"], ["batches", "BATCH"],
    ["validation", "VALID"], ["repair", "REPAIR"], ["review", "REVIEW"], ["final", "FINAL"],
  ],
  C: [
    ["context", "CTX"], ["plan", "PLAN"], ["candidates", "CAND"],
    ["validation", "VALID"], ["repair", "REPAIR"], ["review", "REVIEW"], ["final", "FINAL"],
  ],
};

function node(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function formatNumber(value) {
  const number = Number(value || 0);
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(2)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(1)}K`;
  return number.toLocaleString();
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(2)} MB`;
  if (bytes >= 1_000) return `${(bytes / 1_000).toFixed(1)} KB`;
  return `${bytes} BYTES`;
}

function formatElapsed(seconds) {
  const safe = Math.max(0, Math.floor(seconds || 0));
  const hours = String(Math.floor(safe / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((safe % 3600) / 60)).padStart(2, "0");
  const secs = String(safe % 60).padStart(2, "0");
  return `${hours}:${minutes}:${secs}`;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 3600);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.method && options.method !== "GET") {
    headers["Content-Type"] = "application/json";
    headers["X-Stella-Console-Token"] = state.token;
  }
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `${response.status} ${response.statusText}`);
  return payload;
}

function commaList(selector) {
  return $(selector).value.split(",").map((value) => value.trim()).filter(Boolean);
}

function formPayload() {
  const method = $("input[name=method]:checked")?.value || "";
  const maxTokens = $("#max-tokens").value.trim();
  return {
    method,
    run_id: $("#run-id").value.trim(),
    extractor_model: $("#extractor-model").value.trim(),
    reviewer_model: $("#reviewer-model").value.trim(),
    task_surface: $("#task-surface").value,
    parallel: Number($("#parallel").value),
    max_repair_rounds: Number($("#repair-rounds").value),
    timeout_seconds: Number($("#timeout-seconds").value),
    batch_size: Number($("#batch-size").value),
    max_tokens: maxTokens ? Number(maxTokens) : null,
    provider_pin: $("#provider-pin").checked,
    providers: commaList("#providers"),
    fallback_models: commaList("#fallback-models"),
  };
}

function slug(value) {
  return String(value || "model").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 38) || "model";
}

function suggestRunId() {
  if (state.runIdTouched) return;
  const method = $("input[name=method]:checked")?.value;
  if (!method) return;
  const model = slug($("#extractor-model").value);
  const surface = $("#task-surface").value.replace("core_prov", "core");
  const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 13).replace("T", "-");
  $("#run-id").value = `dev-${method.toLowerCase()}-${stamp}-${model}-${surface}`;
}

function invalidatePreflight() {
  state.preflight = null;
  $("#start-button").disabled = true;
  $("#command-output").textContent = "Configuration changed. Run preflight again.";
  if ($("input[name=method]:checked")) {
    $("#preflight-list").innerHTML = '<p class="empty-note">Configuration changed. Re-run checks.</p>';
  }
}

function renderMethod() {
  const method = $("input[name=method]:checked")?.value || "";
  $("#method-badge").textContent = method ? `METHOD ${method}` : "NO METHOD";
  $("#method-b-options").classList.toggle("hidden", method !== "B");
  renderFlow(method);
  suggestRunId();
}

function renderFlow(method) {
  const flow = FLOW[method];
  $("#flow-empty").classList.toggle("hidden", Boolean(flow));
  $("#flow-track").classList.toggle("hidden", !flow);
  const container = $("#flow-nodes");
  container.replaceChildren();
  if (!flow) return;
  flow.forEach(([key, label], index) => {
    const item = node("button", "flow-node");
    item.type = "button";
    item.dataset.stage = key;
    item.addEventListener("click", () => {
      state.eventFilter = key === "tools" ? "tool" : key === "validation" ? "validation" : "all";
      $$(".event-filters button").forEach((button) => button.classList.toggle("active", button.dataset.filter === state.eventFilter));
      $("#event-search").value = key === "all" ? "" : key;
      renderEvents();
    });
    const core = node("span", "node-core", String(index + 1).padStart(2, "0"));
    item.append(core, node("span", "", label), node("small", "", "WAITING"));
    container.append(item);
  });
  renderProgress();
}

function eventStage(event) {
  const stage = String(event.stage || "").toLowerCase();
  const type = String(event.type || "").toLowerCase();
  if (type.startsWith("validation.")) return "validation";
  if (type.startsWith("paper.completed") || type.startsWith("run.completed")) return "final";
  if (stage.startsWith("batch") || stage.startsWith("rebatch")) return "batches";
  if (stage.startsWith("cand")) return "candidates";
  if (stage.includes("repair")) return "repair";
  if (stage.includes("review")) return "review";
  if (stage.includes("scaffold")) return "scaffold";
  if (stage.includes("plan")) return "plan";
  if (stage.includes("context")) return "context";
  if (type.startsWith("tool.")) return stage || "context";
  return stage || "context";
}

function renderProgress() {
  const method = state.activeRun?.method || $("input[name=method]:checked")?.value || "";
  const flow = FLOW[method];
  if (!flow) return;
  const relevant = state.selectedPaper ? state.events.filter((event) => event.paper_id === state.selectedPaper) : state.events;
  const latest = relevant[relevant.length - 1];
  const activeStage = latest ? eventStage(latest) : "";
  const foundIndex = flow.findIndex(([key]) => key === activeStage);
  const activeIndex = foundIndex >= 0 ? foundIndex : 0;
  $$(".flow-node").forEach((element, index) => {
    element.classList.toggle("done", index < activeIndex || (latest?.type === "run.completed" && index <= activeIndex));
    element.classList.toggle("active", index === activeIndex && !String(latest?.type || "").endsWith("completed"));
    element.classList.toggle("failed", index === activeIndex && String(latest?.status || "").includes("fail"));
    const count = relevant.filter((event) => eventStage(event) === element.dataset.stage).length;
    $("small", element).textContent = count ? `${count} EVENTS` : "WAITING";
  });
  const progress = flow.length > 1 ? activeIndex / (flow.length - 1) : 0;
  $("#data-pulse").style.setProperty("--progress", String(progress));
  const transmitting = latest?.type === "llm.request.started";
  $("#data-pulse").classList.toggle("transmitting", transmitting);
  $("#live-call").classList.toggle("hidden", !transmitting);
  $("#live-call-label").textContent = transmitting ? `${latest.paper_id || "RUN"} / ${latest.stage || "LLM"}` : "—";
}

function renderPreflight(result) {
  state.preflight = result;
  const list = $("#preflight-list");
  list.replaceChildren();
  result.checks.forEach((check) => {
    const row = node("div", `check-row ${check.ok ? "ok" : "bad"}`);
    row.append(node("i"), node("span", "", check.name), node("small", "", check.detail));
    list.append(row);
  });
  $("#command-output").textContent = result.command.map((part) => /\s/.test(part) ? JSON.stringify(part) : part).join(" ");
  $("#start-button").disabled = !result.ok;
}

async function runPreflight() {
  try {
    const result = await api("/api/preflight", { method: "POST", body: JSON.stringify(formPayload()) });
    renderPreflight(result);
    showToast(result.ok ? "Preflight passed. The dev run is ready." : "Preflight found blocking conditions.");
    return result;
  } catch (error) {
    showToast(error.message);
    return null;
  }
}

async function startRun() {
  const preflight = await runPreflight();
  if (!preflight?.ok) return;
  try {
    const processState = await api("/api/runs", { method: "POST", body: JSON.stringify(formPayload()) });
    await refreshRuns();
    const run = state.runs.find((item) => item.run_id === processState.run_id && item.campaign_id === processState.campaign_id) || {
      campaign_id: processState.campaign_id,
      run_id: processState.run_id,
      method: formPayload().method,
      status: "running",
      papers: state.bootstrap.papers,
      trace_precision: "exact",
      read_only: false,
      controllable: true,
      resumable: false,
    };
    selectRun(run);
    showToast("Dev run launched. Live trace connected.");
  } catch (error) {
    showToast(error.message);
  }
}

async function stopRun() {
  if (!state.activeRun) return;
  try {
    await api(`/api/runs/${encodeURIComponent(state.activeRun.run_id)}/stop`, { method: "POST", body: "{}" });
    state.activeRun.status = "stop_requested";
    state.activeRun.controllable = false;
    renderRunState();
    showToast("Stop requested. Completed paper artifacts are preserved.");
  } catch (error) { showToast(error.message); }
}

async function resumeRun() {
  if (!state.activeRun) return;
  try {
    await api(`/api/runs/${encodeURIComponent(state.activeRun.run_id)}/resume`, { method: "POST", body: "{}" });
    state.activeRun.status = "running";
    state.activeRun.controllable = true;
    state.activeRun.resumable = false;
    connectEvents();
    renderRunState();
    showToast("Run resumed with the immutable saved configuration.");
  } catch (error) { showToast(error.message); }
}

function renderRunState() {
  const status = state.activeRun?.status || "standby";
  const normalized = ["running", "stop_requested"].includes(status) ? "running" : status === "completed" || status === "sealed" ? "completed" : ["failed", "partial"].includes(status) ? "failed" : "queued";
  const glyph = $("#run-state-glyph");
  glyph.className = `status-glyph ${normalized}`;
  $("#run-state-label").textContent = status.replaceAll("_", " ").toUpperCase();
  $("#stop-button").classList.toggle("hidden", status !== "running" || !state.activeRun?.controllable);
  $("#resume-button").classList.toggle("hidden", !state.activeRun?.resumable);
  $("#start-button").classList.toggle("hidden", Boolean(state.activeRun && ["running", "stop_requested"].includes(status)));
}

function aggregateUsage() {
  const totals = {};
  state.events.forEach((event) => {
    Object.entries(event.usage_delta || {}).forEach(([key, value]) => {
      totals[key] = (totals[key] || 0) + Number(value || 0);
    });
  });
  if (!Object.values(totals).some((value) => value > 0)) {
    Object.entries(state.activeRun?.usage_totals || {}).forEach(([key, value]) => {
      totals[key] = Number(value || 0);
    });
  }
  return totals;
}

function renderMetrics() {
  const usage = aggregateUsage();
  $("#metric-input").textContent = formatNumber(usage.prompt_tokens);
  $("#metric-output").textContent = formatNumber(usage.completion_tokens);
  $("#metric-reasoning").textContent = formatNumber(usage.reasoning_tokens);
  $("#metric-cache").textContent = formatNumber(usage.prompt_cache_hit_tokens);
}

function renderElapsed() {
  if (!state.startedAt) {
    $("#metric-elapsed").textContent = "00:00:00";
    return;
  }
  const endEvent = [...state.events].reverse().find((event) => event.type === "run.completed");
  const terminalTime = state.activeRun?.finished_at;
  const end = terminalTime ? new Date(terminalTime).getTime() : endEvent ? new Date(endEvent.occurred_at).getTime() : Date.now();
  $("#metric-elapsed").textContent = formatElapsed((end - state.startedAt.getTime()) / 1000);
}

function paperStates() {
  const values = Object.fromEntries((state.activeRun?.papers || state.bootstrap?.papers || []).map((paper) => [paper, { status: "queued", stage: "waiting" }]));
  state.events.forEach((event) => {
    if (!event.paper_id || !values[event.paper_id]) return;
    if (event.type === "paper.started") values[event.paper_id] = { status: "running", stage: event.stage || "context" };
    else if (event.type === "paper.completed") values[event.paper_id] = { status: String(event.status || "completed"), stage: "final" };
    else values[event.paper_id].stage = eventStage(event);
  });
  Object.entries(state.activeRun?.paper_statuses || {}).forEach(([paper, status]) => {
    if (values[paper] && values[paper].status === "queued" && status !== "missing") values[paper] = { status, stage: "final" };
  });
  return values;
}

function renderPapers() {
  const container = $("#paper-grid");
  container.replaceChildren();
  const values = paperStates();
  let completed = 0;
  Object.entries(values).forEach(([paper, info]) => {
    const success = ["ok", "ok_with_cjk_warnings", "completed", "already_successful"].includes(info.status);
    if (success) completed += 1;
    const visual = success ? "completed" : info.status === "running" ? "running" : ["queued", "missing"].includes(info.status) ? "queued" : "failed";
    const card = node("button", `paper-card ${visual}${state.selectedPaper === paper ? " selected" : ""}`);
    card.type = "button";
    card.append(node("b", "", paper), node("span", "", `${info.stage} · ${info.status}`), node("i"));
    card.addEventListener("click", () => {
      state.selectedPaper = state.selectedPaper === paper ? "" : paper;
      renderPapers(); renderEvents(); renderProgress();
    });
    container.append(card);
  });
  $("#paper-summary").textContent = `${completed} / ${Object.keys(values).length} complete`;
}

function eventMatches(event) {
  if (state.selectedPaper && event.paper_id !== state.selectedPaper) return false;
  const type = String(event.type || "").toLowerCase();
  if (state.eventFilter === "llm" && !type.includes("llm")) return false;
  if (state.eventFilter === "tool" && !type.includes("tool")) return false;
  if (state.eventFilter === "validation" && !type.includes("validation")) return false;
  if (state.eventFilter === "error" && !type.includes("fail") && !String(event.status || "").includes("fail") && !String(event.status || "").includes("repair")) return false;
  const query = $("#event-search").value.trim().toLowerCase();
  if (query && !JSON.stringify(event).toLowerCase().includes(query)) return false;
  return true;
}

function renderEvents() {
  const list = $("#event-list");
  list.replaceChildren();
  const events = state.events.filter(eventMatches);
  if (!events.length) {
    list.append(node("p", "empty-note", "No events match the current filter."));
    return;
  }
  events.slice().reverse().forEach((event) => {
    const row = node("button", `event-row${state.selectedEvent?.seq === event.seq ? " selected" : ""}`);
    row.type = "button";
    const time = node("time", "", new Date(event.occurred_at).toLocaleTimeString([], { hour12: false }));
    const paper = node("span", "paper", event.paper_id || "RUN");
    const title = node("span", "event-type", `${event.type}${event.summary ? ` · ${event.summary}` : ""}`);
    const usage = event.usage_delta ? `+${formatNumber(event.usage_delta.total_tokens || 0)} TOK` : event.duration_ms != null ? `${(event.duration_ms / 1000).toFixed(1)}s` : `#${event.seq}`;
    row.append(time, paper, title, node("span", "event-usage", usage));
    row.addEventListener("click", () => selectEvent(event));
    list.append(row);
  });
}

async function selectEvent(event) {
  const generation = ++state.payloadGeneration;
  state.selectedEvent = event;
  state.payload = null;
  state.payloadEnvelope = null;
  if (event.type.includes("request")) state.inspectorTab = "request";
  else if (event.type.includes("response")) state.inspectorTab = "response";
  else if (event.type.includes("tool")) state.inspectorTab = "tool";
  else if (event.type.includes("validation")) state.inspectorTab = "validation";
  else state.inspectorTab = "artifact";
  renderEvents(); renderInspector();
  $(".inspector").classList.add("open");
  try {
    if (event.payload_ref?.sha256) {
      const envelope = await api(`/api/runs/${encodeURIComponent(event.campaign_id)}/${encodeURIComponent(event.run_id)}/blobs/${event.payload_ref.sha256}`);
      if (generation !== state.payloadGeneration) return;
      state.payloadEnvelope = envelope;
      state.payload = envelope.payload;
    } else if (event.data?.legacy_artifact && event.paper_id) {
      const params = new URLSearchParams({ paper: event.paper_id, name: event.data.legacy_artifact });
      const payload = await api(`/api/runs/${encodeURIComponent(event.campaign_id)}/${encodeURIComponent(event.run_id)}/artifact?${params}`);
      if (generation !== state.payloadGeneration) return;
      state.payload = payload;
    } else {
      state.payload = event;
    }
  } catch (error) {
    if (generation !== state.payloadGeneration) return;
    state.payload = { error: error.message, event };
  }
  if (generation !== state.payloadGeneration) return;
  renderInspector();
}

function reasoningView(payload) {
  const message = payload?.choices?.[0]?.message || {};
  const reasoning = message.reasoning_content ?? message.reasoning;
  if (typeof reasoning === "string" && reasoning) return { provider_exposed_reasoning: reasoning };
  const tokens = payload?.usage?.completion_tokens_details?.reasoning_tokens;
  return { provider_exposed_reasoning: null, reasoning_tokens: tokens ?? null, note: "This provider did not return reasoning text. Stella does not reconstruct hidden reasoning." };
}

function inspectorProjection() {
  const payload = state.payload;
  if (state.inspectorTab === "reasoning") return reasoningView(payload);
  if (state.inspectorTab === "request" && state.payloadEnvelope?.kind !== "llm.request") return { note: "Select an LLM request event to inspect the exact request envelope.", selected_event: state.selectedEvent };
  if (state.inspectorTab === "response" && state.payloadEnvelope?.kind !== "llm.response") return { note: "Select an LLM response event to inspect the raw provider response.", selected_event: state.selectedEvent };
  if (state.inspectorTab === "tool" && !String(state.payloadEnvelope?.kind || "").startsWith("tool.")) return { note: "Select a tool call or result event.", selected_event: state.selectedEvent };
  if (state.inspectorTab === "validation" && state.payloadEnvelope?.kind !== "validation.result") return { note: "Select a validation event.", selected_event: state.selectedEvent };
  return payload ?? { note: "Payload is loading." };
}

function renderInspector() {
  $$(".inspector-tabs button").forEach((button) => button.classList.toggle("active", button.dataset.tab === state.inspectorTab));
  const event = state.selectedEvent;
  $("#inspector-seq").textContent = event ? `EVENT ${String(event.seq).padStart(4, "0")}` : "NO EVENT";
  const meta = $("#inspector-meta");
  meta.replaceChildren();
  if (!event) {
    meta.append(node("p", "", "Select an event to inspect its exact payload."));
  } else {
    const grid = node("div", "meta-grid");
    [["TYPE", event.type], ["PAPER", event.paper_id || "RUN"], ["STAGE", event.stage || "—"], ["TIME", event.occurred_at], ["TRACE", event.synthetic ? "SYNTHESIZED" : "EXACT"]].forEach(([label, value]) => grid.append(node("span", "", label), node("b", "", String(value))));
    meta.append(grid);
  }
  const text = JSON.stringify(inspectorProjection(), null, 2);
  $("#payload-output").textContent = text;
  $("#payload-size").textContent = formatBytes(new TextEncoder().encode(text).length);
  highlightPayloadSearch();
}

function highlightPayloadSearch() {
  const output = $("#payload-output");
  const query = $("#payload-search").value;
  const text = output.textContent;
  if (!query) return;
  const index = text.toLowerCase().indexOf(query.toLowerCase());
  if (index < 0) return;
  const before = document.createTextNode(text.slice(0, index));
  const mark = node("mark", "", text.slice(index, index + query.length));
  const after = document.createTextNode(text.slice(index + query.length));
  output.replaceChildren(before, mark, after);
  mark.scrollIntoView({ block: "center" });
}

function addEvent(event) {
  const key = `${event.session_id || "legacy"}:${event.seq}`;
  if (state.eventIds.has(key)) return;
  state.eventIds.add(key);
  state.events.push(event);
  state.events.sort((a, b) => new Date(a.occurred_at) - new Date(b.occurred_at) || a.seq - b.seq);
  if (["run.started", "run.resumed"].includes(event.type) && !state.startedAt) state.startedAt = new Date(event.occurred_at);
  if (event.type === "run.completed" && state.activeRun) state.activeRun.status = event.status || "completed";
}

function connectEvents() {
  clearTimeout(state.terminalCloseTimer);
  state.terminalCloseTimer = null;
  state.source?.close();
  if (!state.activeRun) return;
  const url = `/api/runs/${encodeURIComponent(state.activeRun.campaign_id)}/${encodeURIComponent(state.activeRun.run_id)}/events`;
  const source = new EventSource(url);
  state.source = source;
  source.addEventListener("trace", (message) => {
    try { addEvent(JSON.parse(message.data)); } catch { return; }
    renderMetrics(); renderEvents(); renderPapers(); renderProgress(); renderRunState();
  });
  source.onopen = () => { $("#connection-dot").classList.remove("disconnected"); $("#connection-label").textContent = "LIVE"; };
  source.onerror = () => { $("#connection-dot").classList.add("disconnected"); $("#connection-label").textContent = "RECONNECT"; };
}

async function selectRun(run) {
  state.payloadGeneration += 1;
  state.activeRun = run;
  state.events = [];
  state.eventIds.clear();
  state.selectedEvent = null;
  state.selectedPaper = "";
  state.payload = null;
  state.payloadEnvelope = null;
  state.startedAt = run.created_at ? new Date(run.created_at) : null;
  $("#method-badge").textContent = `METHOD ${run.method}`;
  renderFlow(run.method);
  renderRunState(); renderPapers(); renderEvents(); renderInspector(); renderMetrics();
  $("#history-dialog").close();
  connectEvents();
}

async function refreshRuns() {
  const payload = await api("/api/runs");
  state.runs = payload.runs;
  renderHistory();
}

async function refreshActiveStatus() {
  if (!state.activeRun || state.statusRefreshInFlight) return;
  const campaignId = state.activeRun.campaign_id;
  const runId = state.activeRun.run_id;
  state.statusRefreshInFlight = true;
  try {
    const latest = await api(`/api/runs/${encodeURIComponent(campaignId)}/${encodeURIComponent(runId)}/status`);
    if (state.activeRun?.campaign_id !== campaignId || state.activeRun?.run_id !== runId) return;
    Object.assign(state.activeRun, latest);
    if (!state.startedAt && latest.created_at) state.startedAt = new Date(latest.created_at);
    const index = state.runs.findIndex((run) => run.campaign_id === campaignId && run.run_id === runId);
    if (index >= 0) state.runs[index] = { ...state.runs[index], ...latest };
    if (!["running", "stop_requested"].includes(latest.status) && !state.terminalCloseTimer) {
      state.terminalCloseTimer = setTimeout(() => {
        if (state.activeRun?.campaign_id === campaignId && state.activeRun?.run_id === runId && !["running", "stop_requested"].includes(state.activeRun.status)) {
          state.source?.close();
        }
        state.terminalCloseTimer = null;
      }, 2000);
    }
    renderRunState(); renderPapers(); renderMetrics(); renderElapsed();
  } catch (error) {
    if (!String(error.message).includes("does not exist")) {
      $("#connection-dot").classList.add("disconnected");
      $("#connection-label").textContent = "RECONNECT";
    }
  } finally {
    state.statusRefreshInFlight = false;
  }
}

function renderHistory() {
  const list = $("#history-list");
  list.replaceChildren();
  const query = $("#history-search").value.trim().toLowerCase();
  const runs = state.runs.filter((run) => !query || JSON.stringify(run).toLowerCase().includes(query));
  $("#history-count").textContent = `${runs.length} RUNS`;
  if (!runs.length) { list.append(node("p", "empty-note", "No local runs match this filter.")); return; }
  runs.forEach((run) => {
    const row = node("button", "history-row");
    row.type = "button";
    const method = node("span", "history-method", run.method || "?");
    const identity = node("div"); identity.append(node("b", "", run.run_id), node("small", "", `${run.campaign_id} · ${run.trace_precision.replaceAll("_", " ")}`));
    const model = node("div"); model.append(node("b", "", run.extractor_model || "UNKNOWN MODEL"), node("small", "", run.reviewer_model ? `review: ${run.reviewer_model}` : "no reviewer metadata"));
    const papers = node("div"); papers.append(node("b", "", `${Object.values(run.paper_statuses || {}).filter((value) => ["ok", "ok_with_cjk_warnings"].includes(value)).length} / ${run.papers.length}`), node("small", "", "PAPERS DELIVERED"));
    const created = node("div"); created.append(node("b", "", run.created_at ? new Date(run.created_at).toLocaleDateString() : "—"), node("small", "", run.task_surface));
    row.append(method, identity, model, papers, created, node("span", "history-status", run.status));
    row.addEventListener("click", () => selectRun(run));
    list.append(row);
  });
}

function installInteractions() {
  $("#run-form").addEventListener("input", (event) => {
    if (event.target.id === "run-id" && event.isTrusted) state.runIdTouched = true;
    if (["extractor-model", "task-surface"].includes(event.target.id)) suggestRunId();
    invalidatePreflight();
  });
  $$("input[name=method]").forEach((input) => input.addEventListener("change", () => { state.runIdTouched = false; renderMethod(); invalidatePreflight(); }));
  $("#preflight-button").addEventListener("click", runPreflight);
  $("#start-button").addEventListener("click", startRun);
  $("#stop-button").addEventListener("click", stopRun);
  $("#resume-button").addEventListener("click", resumeRun);
  $("#history-open").addEventListener("click", async () => { await refreshRuns(); $("#history-dialog").showModal(); });
  $("#history-close").addEventListener("click", () => $("#history-dialog").close());
  $("#history-search").addEventListener("input", renderHistory);
  $("#event-search").addEventListener("input", renderEvents);
  $$(".event-filters button").forEach((button) => button.addEventListener("click", () => {
    state.eventFilter = button.dataset.filter;
    $$(".event-filters button").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
    renderEvents();
  }));
  $$(".inspector-tabs button").forEach((button) => button.addEventListener("click", () => { state.inspectorTab = button.dataset.tab; renderInspector(); }));
  $("#payload-search").addEventListener("input", renderInspector);
  $("#wrap-toggle").addEventListener("click", () => $("#payload-output").classList.toggle("wrap"));
  $("#copy-payload").addEventListener("click", async () => { await navigator.clipboard.writeText($("#payload-output").textContent); showToast("Payload copied."); });
  $("#clear-selection").addEventListener("click", () => { state.payloadGeneration += 1; state.selectedEvent = null; state.payload = null; state.payloadEnvelope = null; renderEvents(); renderInspector(); });
  $("#config-collapse").addEventListener("click", () => {
    if (window.innerWidth <= 960) $(".config-rail").classList.toggle("open");
    else document.body.classList.toggle("config-collapsed");
  });
  $("#method-badge").addEventListener("click", () => {
    if (window.innerWidth <= 960) $(".config-rail").classList.add("open");
    else document.body.classList.remove("config-collapsed");
  });
  const handle = $("#rail-handle");
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const startY = event.clientY;
    const start = $("#event-rail").getBoundingClientRect().height;
    const move = (moveEvent) => document.documentElement.style.setProperty("--event-height", `${Math.max(150, Math.min(520, start + startY - moveEvent.clientY))}px`);
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { $(".inspector").classList.remove("open"); $(".config-rail").classList.remove("open"); }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#history-dialog").showModal(); $("#history-search").focus(); }
  });
}

async function init() {
  installInteractions();
  try {
    state.bootstrap = await api("/api/bootstrap");
    state.token = state.bootstrap.session_token;
    $("#campaign-label").textContent = state.bootstrap.campaign_id;
    const options = $("#model-options");
    state.bootstrap.models.forEach((model) => { const option = node("option"); option.value = model; options.append(option); });
    $("#extractor-model").value = state.bootstrap.models.find((model) => model !== "glm-5.2") || "";
    renderPapers();
    await refreshRuns();
  } catch (error) {
    $("#connection-dot").classList.add("disconnected");
    $("#connection-label").textContent = "OFFLINE";
    showToast(error.message);
  }
  setInterval(renderElapsed, 1000);
  setInterval(refreshActiveStatus, 1000);
}

init();
