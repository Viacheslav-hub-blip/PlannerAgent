/**
 * Список запусков.
 */

const STATUS_ID = "statusBar";

async function loadRuns() {
  try {
    setStatus(STATUS_ID, "Загружаю запуски…", "");
    const runs = await apiFetch("/runs");
    renderRuns(runs);
    setStatus(STATUS_ID, `Загружено: ${runs.length}`, "success");
  } catch (error) {
    setStatus(STATUS_ID, `Ошибка: ${error.message}`, "error");
  }
}

/**
 * @param {Array<{run: object, node_count: number, artifact_count: number}>} summaries
 */
function renderRuns(summaries) {
  const container = $("runsList");
  container.innerHTML = "";
  if (!summaries.length) {
    container.appendChild(emptyBlock("Запусков пока нет."));
    return;
  }
  summaries.forEach((summary) => {
    const run = summary.run;
    const runId = run.run_id;
    const q = encodeURIComponent(runId);
    const article = document.createElement("article");
    article.className = "history-card";
    article.innerHTML = `
      <h3 class="history-card-title">${escapeHtml(run.title || run.initial_user_query || runId)}</h3>
      <p class="item-meta">${escapeHtml(run.status)} · узлов: ${summary.node_count} · файлов: ${summary.artifact_count}</p>
      <p class="item-meta">${escapeHtml(formatDate(run.created_at))}</p>
      <div class="history-card-actions">
        <a class="button-link primary" href="./report.html?run=${q}">Отчёт</a>
        <a class="button-link" href="./files.html?run=${q}">Файлы</a>
        <a class="button-link" href="./audit.html?run=${q}">Аудит</a>
      </div>
    `;
    container.appendChild(article);
  });
}

function init() {
  $("refreshRunsButton").addEventListener("click", loadRuns);
  loadRuns();
}

init();
