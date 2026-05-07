/**
 * Главная: только ввод задачи, затем canvas с появлением узлов графа.
 */

const STATUS_ID = "statusBar";
const LIVE_POLL_INTERVAL_MS = 900;

let livePollTimer = null;
let currentRunId = "";
let renderedNodeIds = new Set();

function sanitizeTypeClass(nodeType) {
  const raw = String(nodeType ?? "node")
    .toLowerCase()
    .replace(/_/g, "-")
    .replace(/[^a-z0-9-]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  return raw.slice(0, 64) || "node";
}

function clearCanvas() {
  const host = $("agentCanvasNodes");
  host.innerHTML = "";
}

function showCanvasPlaceholder(text) {
  clearCanvas();
  const host = $("agentCanvasNodes");
  const el = document.createElement("div");
  el.className = "canvas-placeholder";
  el.setAttribute("role", "status");
  el.textContent = text;
  host.appendChild(el);
}

function removeCanvasPlaceholder() {
  document.querySelectorAll(".canvas-placeholder").forEach((element) => element.remove());
}

function stopLivePolling() {
  if (livePollTimer) {
    window.clearTimeout(livePollTimer);
    livePollTimer = null;
  }
}

/**
 * @param {Array<{node_id: string, node_type: string, title?: string, status?: string}>} nodes
 */
function animateNodesOntoCanvas(nodes) {
  clearCanvas();
  const host = $("agentCanvasNodes");
  if (!nodes.length) {
    host.appendChild(emptyBlock("Узлы графа не найдены."));
    return;
  }
  nodes.forEach((node, index) => {
    appendNodeToCanvas(node, index);
  });
}

/**
 * @param {{node_id: string, node_type: string, title?: string, status?: string, summary?: string}} node
 * @param {number} index
 */
function appendNodeToCanvas(node, index) {
    const card = document.createElement("div");
    card.className = `node-bubble node-bubble--${sanitizeTypeClass(node.node_type)}`;
    card.style.setProperty("--stagger", String(Math.min(index, 50)));
    card.dataset.nodeId = node.node_id;
    card.innerHTML = `
      <div class="node-bubble-type">${escapeHtml(node.node_type)}</div>
      <div class="node-bubble-title">${escapeHtml(node.title || node.node_id)}</div>
      <div class="node-bubble-meta">${escapeHtml(node.status || "")}</div>
      <div class="node-bubble-summary">${escapeHtml(node.summary || "")}</div>
    `;
    $("agentCanvasNodes").appendChild(card);
}

/**
 * @param {Array<{node_id: string, node_type: string, title?: string, status?: string, summary?: string}>} nodes
 */
function renderLiveNodes(nodes) {
  if (!nodes.length) {
    return;
  }
  removeCanvasPlaceholder();
  nodes.forEach((node) => {
    if (renderedNodeIds.has(node.node_id)) {
      const existing = document.querySelector(`[data-node-id="${CSS.escape(node.node_id)}"] .node-bubble-meta`);
      if (existing) {
        existing.textContent = node.status || "";
      }
      return;
    }
    renderedNodeIds.add(node.node_id);
    appendNodeToCanvas(node, renderedNodeIds.size - 1);
  });
}

/**
 * @param {string} runId
 */
function setRunDeepLinks(runId) {
  const q = encodeURIComponent(runId);
  $("linkReport").href = `./report.html?run=${q}`;
  $("linkFiles").href = `./files.html?run=${q}`;
  $("linkFollowup").href = `./followup.html?run=${q}`;
  $("linkAudit").href = `./audit.html?run=${q}`;
  $("linkHistoryHint").href = `./history.html`;
}

function showLanding() {
  stopLivePolling();
  $("homeLanding").hidden = false;
  $("runSessionView").hidden = true;
}

function showRunSession() {
  $("homeLanding").hidden = true;
  $("runSessionView").hidden = false;
}

async function invokeNewRunFallback(query) {
  const response = await apiFetch("/runs/invoke", {
    method: "POST",
    body: JSON.stringify({
      user_query: query,
      session_id: $("sessionIdInput").value.trim(),
      user_id: $("userIdInput").value.trim() || null,
      filesystem_context: {},
      context_runs: [],
    }),
  });
  let nodes = response.result && response.result.nodes ? response.result.nodes : [];
  if (!nodes.length && response.run_id) {
    const graph = await apiFetch(`/runs/${encodeURIComponent(response.run_id)}/graph`);
    nodes = graph.nodes || [];
  }
  animateNodesOntoCanvas(nodes);
  setRunDeepLinks(response.run_id);
  setStatus(STATUS_ID, "Готово. Сервер не отдал live-start, поэтому граф показан после завершения.", "success");
}

async function pollLiveRun(runId) {
  if (currentRunId !== runId) {
    return;
  }
  try {
    const graph = await apiFetch(`/runs/${encodeURIComponent(runId)}/graph`);
    renderLiveNodes(graph.nodes || []);
    const status = graph.run ? graph.run.status : "running";
    if (status === "succeeded") {
      stopLivePolling();
      setStatus(STATUS_ID, "Готово. Узлы построены по мере выполнения агента.", "success");
      return;
    }
    if (status === "failed" || status === "cancelled") {
      stopLivePolling();
      setStatus(STATUS_ID, `Запуск завершился со статусом: ${status}.`, "error");
      return;
    }
    setStatus(STATUS_ID, `Агент работает. Узлов на canvas: ${renderedNodeIds.size}`, "");
  } catch (error) {
    setStatus(STATUS_ID, `Жду граф запуска: ${error.message}`, "");
  }
  livePollTimer = window.setTimeout(() => pollLiveRun(runId), LIVE_POLL_INTERVAL_MS);
}

async function invokeNewRun(event) {
  event.preventDefault();
  const query = $("newRunQuery").value.trim();
  if (!query) {
    setStatus(STATUS_ID, "Введите задачу для анализа.", "error");
    return;
  }
  showRunSession();
  stopLivePolling();
  currentRunId = "";
  renderedNodeIds = new Set();
  clearCanvas();
  showCanvasPlaceholder("Создаю live-запуск и готовлю граф…");
  setStatus(STATUS_ID, "Запускаю анализ в live-режиме…", "");

  try {
    const response = await apiFetch("/runs/live", {
      method: "POST",
      body: JSON.stringify({
        user_query: query,
        session_id: $("sessionIdInput").value.trim(),
        user_id: $("userIdInput").value.trim() || null,
        filesystem_context: {},
        context_runs: [],
      }),
    });
    $("newRunQuery").value = "";
    currentRunId = response.run_id;
    setRunDeepLinks(response.run_id);
    setStatus(STATUS_ID, "Run создан. Слушаю появление узлов…", "");
    pollLiveRun(response.run_id);
  } catch (error) {
    try {
      setStatus(STATUS_ID, "Live endpoint недоступен, запускаю совместимый режим…", "");
      await invokeNewRunFallback(query);
      $("newRunQuery").value = "";
    } catch (fallbackError) {
      setStatus(STATUS_ID, `Не удалось запустить анализ: ${fallbackError.message || error.message}`, "error");
      showCanvasPlaceholder("Ошибка запуска. Попробуйте снова или проверьте настройки API.");
    }
  }
}

function bindEvents() {
  $("newRunForm").addEventListener("submit", invokeNewRun);
  $("newAnalysisButton").addEventListener("click", () => {
    showLanding();
    clearCanvas();
    setStatus(STATUS_ID, "", "");
  });
}

function init() {
  bindEvents();
  showLanding();
}

init();
