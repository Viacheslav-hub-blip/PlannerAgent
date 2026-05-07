/** Разделение артефактов инспектора: вызовы инструментов vs файлы с данными. */

function basenameFromUri(uri) {
  const s = String(uri || "").replace(/\\/g, "/");
  const parts = s.split("/");
  return parts.pop() || "";
}

/**
 * Подпись для скачивания: имя файла из uri, без текстового preview/summary.
 */
export function dataArtifactDownloadLabel(entry) {
  const art = entry?.artifact;
  if (!art) {
    return "файл";
  }
  const meta = art.metadata || {};
  for (const key of ["original_filename", "filename", "export_filename"]) {
    const v = meta[key];
    if (typeof v === "string" && v.trim()) {
      return basenameFromUri(v) || v.trim();
    }
  }
  const fromUri = basenameFromUri(art.uri);
  if (fromUri) {
    return fromUri;
  }
  return String(art.artifact_id || "artifact").slice(0, 12);
}

const DATA_KIND_HINTS = new Set(["dataset", "csv", "parquet", "export", "table", "data", "json"]);

/**
 * Артефакт с реальными данными (выгрузка), не trace/preview ответа модели.
 */
export function isDataFileArtifact(entry) {
  const art = entry?.artifact;
  if (!art) {
    return false;
  }
  const kind = String(art.kind || "").toLowerCase();
  if (kind === "tool_trace") {
    return false;
  }
  if (kind === "model_output" || kind === "code_trace") {
    return false;
  }
  const role = String(art.metadata?.artifact_role || "").toLowerCase();
  if (role === "captured_tool_result" || role === "tool_returned_file") {
    return true;
  }
  if (DATA_KIND_HINTS.has(kind)) {
    return true;
  }
  const mime = String(art.mime_type || "").toLowerCase();
  if (
    mime.includes("csv") ||
    mime.includes("parquet") ||
    mime === "application/json" ||
    mime.includes("spreadsheet")
  ) {
    return true;
  }
  const uri = String(art.uri || "").replace(/\\/g, "/");
  if (uri.includes("/tool_results/")) {
    return true;
  }
  return false;
}

export function toolTraceLabel(entry) {
  const art = entry?.artifact;
  if (!art) {
    return "tool";
  }
  const name = art.metadata?.tool_name;
  if (name) {
    return String(name);
  }
  return dataArtifactDownloadLabel(entry);
}
