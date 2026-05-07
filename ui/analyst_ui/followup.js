/**
 * Follow-up запуск от выбранного run.
 */

const STATUS_ID = "statusBar";
const runId = getQueryParam("run");

function buildFollowupPayload() {
  const contextRuns = [];
  if ($("includeCurrentRun").checked && runId) {
    contextRuns.push({
      run_id: runId,
      role: "current",
      include_final_report: true,
      include_artifacts: true,
    });
  }
  return {
    user_query: $("followupQuery").value.trim(),
    context_runs: contextRuns,
  };
}

async function previewDialogContext() {
  if (!runId) {
    setStatus(STATUS_ID, "Сначала откройте страницу с параметром run.", "error");
    return;
  }
  try {
    setStatus(STATUS_ID, "Собираю context…", "");
    const payload = await apiFetch("/dialog-context", {
      method: "POST",
      body: JSON.stringify(buildFollowupPayload()),
    });
    $("dialogContextPreview").textContent = payload.context.rendered_context || "Context пуст.";
    setStatus(STATUS_ID, "Context собран.", "success");
  } catch (error) {
    setStatus(STATUS_ID, error.message, "error");
  }
}

async function invokeFollowup(event) {
  event.preventDefault();
  const query = $("followupQuery").value.trim();
  if (!query) {
    setStatus(STATUS_ID, "Введите задачу.", "error");
    return;
  }
  if (!runId) {
    setStatus(STATUS_ID, "Нет run в URL.", "error");
    return;
  }
  try {
    setStatus(STATUS_ID, "Запускаю follow-up…", "");
    let sessionId = "";
    let userId = null;
    try {
      const result = await apiFetch(`/runs/${encodeURIComponent(runId)}/result`);
      sessionId = result.run.session_id || "";
      userId = result.run.user_id || null;
    } catch {
      /* use empty */
    }
    const payload = buildFollowupPayload();
    const response = await apiFetch("/runs/invoke", {
      method: "POST",
      body: JSON.stringify({
        user_query: payload.user_query,
        session_id: sessionId,
        user_id: userId,
        filesystem_context: {},
        context_runs: payload.context_runs,
      }),
    });
    $("followupQuery").value = "";
    const newId = response.run_id;
    setStatus(STATUS_ID, "Follow-up завершён. Переход к отчёту нового запуска…", "success");
    window.location.href = `./report.html?run=${encodeURIComponent(newId)}`;
  } catch (error) {
    setStatus(STATUS_ID, error.message, "error");
  }
}

function init() {
  if (!runId) {
    $("runChrome").innerHTML = `<p class="muted">Укажите <code>?run=…</code> или выберите запуск в <a href="./history.html">истории</a>.</p>`;
  } else {
    $("runChrome").innerHTML = runNavHtml(runId);
  }
  $("previewDialogContextButton").addEventListener("click", previewDialogContext);
  $("followupForm").addEventListener("submit", invokeFollowup);
}

init();
