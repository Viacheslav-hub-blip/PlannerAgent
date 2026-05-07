/**
 * Общие утилиты для многостраничного analyst UI: API base, fetch, DOM.
 */

function getApiBase() {
  return localStorage.getItem("researchAgentApiBase") || "/api/v1";
}

function setApiBase(value) {
  localStorage.setItem("researchAgentApiBase", value);
}

/**
 * @param {string} path
 * @param {RequestInit} options
 * @returns {Promise<any>}
 */
async function apiFetch(path, options = {}) {
  const base = getApiBase();
  const response = await fetch(`${base}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" ? payload.detail || JSON.stringify(payload) : payload;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}

/**
 * @param {string} id
 * @returns {HTMLElement}
 */
function $(id) {
  const el = document.getElementById(id);
  if (!el) {
    throw new Error(`Missing element #${id}`);
  }
  return el;
}

/**
 * @param {string} value
 * @returns {string}
 */
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

/**
 * @param {string} value
 * @returns {string}
 */
function formatDate(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

/**
 * @param {string} name
 * @returns {string | null}
 */
function getQueryParam(name) {
  const params = new URLSearchParams(window.location.search);
  const v = params.get(name);
  return v && v.trim() ? v.trim() : null;
}

/**
 * @param {string} runId
 * @returns {string}
 */
function runNavHtml(runId) {
  const q = encodeURIComponent(runId);
  return `
    <nav class="run-nav" aria-label="Текущий запуск">
      <a href="./report.html?run=${q}">Отчёт</a>
      <a href="./files.html?run=${q}">Файлы</a>
      <a href="./followup.html?run=${q}">Уточнение</a>
      <a href="./audit.html?run=${q}">Аудит</a>
    </nav>
  `;
}

/**
 * @param {string} message
 * @param {string} kind
 */
function setStatus(elementId, message, kind = "") {
  const element = document.getElementById(elementId);
  if (!element) {
    return;
  }
  element.textContent = message || "";
  element.className = `status-bar ${kind}`.trim();
}

/**
 * @param {string} text
 * @returns {HTMLElement}
 */
function emptyBlock(text) {
  const element = document.createElement("div");
  element.className = "muted";
  element.textContent = text;
  return element;
}
