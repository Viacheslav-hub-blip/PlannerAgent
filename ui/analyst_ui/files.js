/**
 * Artifacts и preview.
 */

const STATUS_ID = "statusBar";
const runId = getQueryParam("run");

async function previewArtifact(artifactId) {
  if (!runId) {
    return;
  }
  try {
    setStatus(STATUS_ID, "Загружаю preview…", "");
    const payload = await apiFetch(
      `/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}/preview?preview_chars=12000`
    );
    $("artifactPreview").textContent = JSON.stringify(payload, null, 2);
    setStatus(STATUS_ID, "Preview загружен.", "success");
  } catch (error) {
    setStatus(STATUS_ID, error.message, "error");
  }
}

function renderArtifacts(artifacts) {
  const container = $("artifactsList");
  container.innerHTML = "";
  $("artifactPreview").textContent = "Выберите файл.";
  if (!artifacts.length) {
    container.appendChild(emptyBlock("Artifacts отсутствуют."));
    return;
  }
  artifacts.forEach((artifact) => {
    const item = document.createElement("div");
    item.className = "artifact-item";
    item.innerHTML = `
      <div class="item-title">${escapeHtml(artifact.summary || artifact.kind || artifact.artifact_id)}</div>
      <div class="item-meta">${escapeHtml(artifact.kind)} | ${escapeHtml(artifact.mime_type || "")}</div>
      <div class="item-meta">${escapeHtml(artifact.artifact_id)}</div>
      <button type="button">Preview</button>
    `;
    item.querySelector("button").addEventListener("click", () => previewArtifact(artifact.artifact_id));
    container.appendChild(item);
  });
}

async function loadArtifacts() {
  if (!runId) {
    $("runChrome").innerHTML = `<p class="muted">Укажите <code>?run=…</code> или <a href="./history.html">историю</a>.</p>`;
    return;
  }
  $("runChrome").innerHTML = runNavHtml(runId);
  try {
    setStatus(STATUS_ID, "Загружаю файлы…", "");
    const artifacts = await apiFetch(`/runs/${encodeURIComponent(runId)}/artifacts`);
    renderArtifacts(artifacts);
    setStatus(STATUS_ID, "Готово.", "success");
  } catch (error) {
    setStatus(STATUS_ID, error.message, "error");
  }
}

$("refreshArtifactsButton").addEventListener("click", loadArtifacts);
loadArtifacts();
