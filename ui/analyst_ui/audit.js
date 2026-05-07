/**
 * Timeline узлов и node inspector.
 */

const STATUS_ID = "statusBar";
const runId = getQueryParam("run");

let selectedNodeId = "";

async function inspectNode(nodeId) {
  if (!runId) {
    return;
  }
  try {
    selectedNodeId = nodeId;
    renderNodeList(window.__auditNodes || []);
    setStatus(STATUS_ID, "Загружаю inspector…", "");
    const payload = await apiFetch(
      `/runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}/inspector?preview_chars=2000&snapshot_preview_chars=1000`
    );
    $("nodeInspector").textContent = JSON.stringify(payload, null, 2);
    setStatus(STATUS_ID, "Готово.", "success");
  } catch (error) {
    setStatus(STATUS_ID, error.message, "error");
  }
}

function renderNodeList(nodes) {
  const container = $("nodesList");
  container.innerHTML = "";
  $("nodeInspector").textContent = "Выберите узел.";
  if (!nodes.length) {
    container.appendChild(emptyBlock("Граф пуст."));
    return;
  }
  nodes.forEach((node) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `node-item${node.node_id === selectedNodeId ? " active" : ""}`;
    button.innerHTML = `
      <div class="item-title">${escapeHtml(node.title || node.node_type)}</div>
      <div class="item-meta">${escapeHtml(node.node_type)} | ${escapeHtml(node.status)}</div>
      <div class="item-meta">${escapeHtml(node.node_id)}</div>
    `;
    button.addEventListener("click", () => inspectNode(node.node_id));
    container.appendChild(button);
  });
}

async function loadGraph() {
  if (!runId) {
    $("runChrome").innerHTML = `<p class="muted">Укажите <code>?run=…</code> или <a href="./history.html">историю</a>.</p>`;
    return;
  }
  $("runChrome").innerHTML = runNavHtml(runId);
  try {
    setStatus(STATUS_ID, "Загружаю граф…", "");
    const graph = await apiFetch(`/runs/${encodeURIComponent(runId)}/graph`);
    const nodes = graph.nodes || [];
    window.__auditNodes = nodes;
    selectedNodeId = "";
    renderNodeList(nodes);
    setStatus(STATUS_ID, "Готово.", "success");
  } catch (error) {
    setStatus(STATUS_ID, error.message, "error");
  }
}

$("refreshGraphButton").addEventListener("click", loadGraph);
loadGraph();
