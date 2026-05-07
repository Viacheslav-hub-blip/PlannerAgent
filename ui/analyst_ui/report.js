/**
 * Финальный отчёт выбранного run.
 */

const STATUS_ID = "statusBar";
const runId = getQueryParam("run");

function renderMissingRun() {
  $("runChrome").innerHTML = `<p class="muted">Укажите запуск в адресе: <code>?run=…</code> или откройте <a href="./history.html">историю</a>.</p>`;
  $("runHeader").className = "run-header empty";
  $("runHeader").innerHTML = "<h2>Запуск не выбран</h2>";
  $("reportContent").textContent = "";
}

async function loadReport() {
  if (!runId) {
    renderMissingRun();
    return;
  }
  $("runChrome").innerHTML = runNavHtml(runId);
  try {
    setStatus(STATUS_ID, "Загружаю отчёт…", "");
    const result = await apiFetch(`/runs/${encodeURIComponent(runId)}/result`);
    const run = result.run;
    $("runHeader").innerHTML = `
      <h2>${escapeHtml(run.title || run.initial_user_query || run.run_id)}</h2>
      <div>
        <span class="pill">${escapeHtml(run.status)}</span>
        <span class="pill">run: ${escapeHtml(run.run_id)}</span>
      </div>
    `;
    $("runHeader").className = "run-header";
    $("reportContent").textContent = result.final_report || "Финальный отчёт отсутствует.";
    setStatus(STATUS_ID, "Готово.", "success");
  } catch (error) {
    setStatus(STATUS_ID, error.message, "error");
    $("reportContent").textContent = "";
  }
}

loadReport();
