const API_BASE_STORAGE_KEY = "researchAgentApiBase";

export function getApiBase() {
  return localStorage.getItem(API_BASE_STORAGE_KEY) || "/api/v1";
}

export function setApiBase(value) {
  const normalized = String(value || "/api/v1").trim() || "/api/v1";
  localStorage.setItem(API_BASE_STORAGE_KEY, normalized);
  return normalized;
}

export async function apiFetch(path, options = {}) {
  const base = getApiBase().replace(/\/$/, "");
  const url = `${base}${path}`;
  const response = await fetch(url, {
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
    const detail = typeof payload === "object"
      ? payload.detail || JSON.stringify(payload)
      : payload;
    throw new Error(detail || `HTTP ${response.status}`);
  }

  return payload;
}

export function startLiveRun(payload) {
  return apiFetch("/runs/live", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function invokeRun(payload) {
  return apiFetch("/runs/invoke", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchRunGraph(runId) {
  return apiFetch(`/runs/${encodeURIComponent(runId)}/graph`);
}

export function fetchRunResult(runId) {
  return apiFetch(`/runs/${encodeURIComponent(runId)}/result`);
}

export function fetchNodeInspector(runId, nodeId) {
  return apiFetch(
    `/runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}/inspector?preview_chars=2500&snapshot_preview_chars=1200`
  );
}

/** Прямая ссылка на скачивание файла artifact (GET, attachment). */
export function artifactFileUrl(runId, artifactId) {
  const base = getApiBase().replace(/\/$/, "");
  return `${base}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}/file`;
}

export function invokeBranchRun(payload) {
  return apiFetch("/branches/invoke", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
