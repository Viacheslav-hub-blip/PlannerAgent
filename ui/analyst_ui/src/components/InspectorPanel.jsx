import { useEffect, useState } from "react";
import { Braces, ChevronDown, Clock, Download, FileText, ListOrdered, Loader2, MousePointerClick, Wrench, X } from "lucide-react";
import { artifactFileUrl, fetchNodeInspector } from "../api.js";
import { dataArtifactDownloadLabel, isDataFileArtifact, toolTraceLabel } from "../lib/inspectorArtifacts.js";
import { compactId } from "../lib/nodes.js";
import { getUserNodeStage } from "../lib/userGraph.js";
import { MarkdownBlock } from "./MarkdownBlock.jsx";

function isSyntheticEvent(event) {
  return String(event?.node_type || "").startsWith("synthetic") || String(event?.node_id || "").startsWith("synthetic");
}

function tasksForPlanIteration(graphNodes, planNode) {
  if (!planNode || planNode.group_role !== "plan" || planNode.iteration == null) {
    return [];
  }
  const iter = planNode.iteration;
  return [...(graphNodes || [])]
    .filter((n) => n.group_role === "task" && n.iteration === iter)
    .sort((a, b) => {
      const na = Number(a.task_id);
      const nb = Number(b.task_id);
      if (!Number.isNaN(na) && !Number.isNaN(nb)) {
        return na - nb;
      }
      return String(a.task_id || "").localeCompare(String(b.task_id || ""), "ru", { numeric: true });
    });
}

function workerFullResultFromInspector(inspector) {
  const snap = inspector?.snapshot;
  if (!snap || typeof snap !== "object") {
    return "";
  }
  const task = snap.task;
  if (!task || typeof task !== "object") {
    return "";
  }
  const text = task.full_result;
  if (typeof text === "string" && text.trim()) {
    return text;
  }
  return "";
}

function InspectorToolCallsSection({ runId, inspector }) {
  if (!runId || !inspector || inspector.error) {
    return null;
  }
  const toolTraces = inspector.tool_traces || [];
  if (!toolTraces.length) {
    return null;
  }

  return (
    <div className="inspector-section">
      <div className="inspector-mini-title">
        <Wrench size={15} />
        Вызванные инструменты
      </div>
      <p className="inspector-text inspector-download-meta">
        Логи вызовов (tool trace) — текстовые файлы для отладки, не выгрузки данных.
      </p>
      <div className="inspector-download-list">
        {toolTraces.map((entry) => {
          const id = entry?.artifact?.artifact_id;
          if (!id) return null;
          return (
            <div key={id} className="inspector-download-row">
              <a href={artifactFileUrl(runId, id)} download>
                {toolTraceLabel(entry)}
              </a>
              <span className="inspector-download-meta">tool trace · скачать лог</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function InspectorDataFilesSection({ runId, inspector }) {
  if (!runId || !inspector || inspector.error) {
    return null;
  }
  const toolIds = new Set(
    (inspector.tool_traces || []).map((e) => e?.artifact?.artifact_id).filter(Boolean),
  );
  const dataEntries = (inspector.artifacts || []).filter((entry) => {
    const id = entry?.artifact?.artifact_id;
    if (!id || toolIds.has(id)) {
      return false;
    }
    return isDataFileArtifact(entry);
  });

  if (!dataEntries.length) {
    return null;
  }

  return (
    <div className="inspector-section">
      <div className="inspector-mini-title">
        <Download size={15} />
        Загруженные данные
      </div>
      <p className="inspector-text inspector-download-meta">
        Файлы выгрузок и датасетов. Отображаются имена файлов, без текстового preview.
      </p>
      <div className="inspector-download-list">
        {dataEntries.map((entry) => {
          const id = entry?.artifact?.artifact_id;
          if (!id) return null;
          const art = entry.artifact;
          const kind = art?.kind || "—";
          const mime = art?.mime_type || "";
          return (
            <div key={id} className="inspector-download-row">
              <a href={artifactFileUrl(runId, id)} download>
                {dataArtifactDownloadLabel(entry)}
              </a>
              <span className="inspector-download-meta">
                {[kind, mime].filter(Boolean).join(" · ")}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function InspectorPanel({
  run,
  runId,
  node,
  graphNodes = [],
  inspector,
  loading,
  onOpenReport,
  onClose,
}) {
  const stage = node ? getUserNodeStage(node) : null;
  const rawEvents = node?.raw_events || inspector?.raw_events || [];
  const [selectedRawId, setSelectedRawId] = useState("");
  const [rawInspector, setRawInspector] = useState(null);
  const [rawLoading, setRawLoading] = useState(false);
  const [rawError, setRawError] = useState("");

  const planTasks = node?.group_role === "plan" ? tasksForPlanIteration(graphNodes, node) : [];
  const workerFullResult = node?.group_role === "task" ? workerFullResultFromInspector(inspector) : "";

  useEffect(() => {
    setSelectedRawId("");
    setRawInspector(null);
    setRawError("");
    setRawLoading(false);
  }, [node?.node_id, runId]);

  async function inspectRawEvent(event) {
    if (!runId || !event?.node_id || isSyntheticEvent(event)) {
      return;
    }

    setSelectedRawId(event.node_id);
    setRawInspector(null);
    setRawError("");
    setRawLoading(true);

    try {
      const payload = await fetchNodeInspector(runId, event.node_id);
      setRawInspector(payload);
    } catch (error) {
      setRawError(error.message || "Не удалось загрузить raw event inspector.");
    } finally {
      setRawLoading(false);
    }
  }

  if (!node) {
    return (
      <aside className="inspector-panel">
        <div className="inspector-header">
          <div>
            <div className="section-label">Inspector</div>
            <h2>Узел не найден</h2>
          </div>
        </div>
        <p className="inspector-text">Выберите другой шаг на графе.</p>
      </aside>
    );
  }

  return (
    <aside className="inspector-panel">
      <div className="inspector-header">
        <div>
          <div className="section-label">Inspector</div>
          <h2>{node.title || node.node_type}</h2>
        </div>
        <div className="inspector-header-actions">
          {(loading || rawLoading) && <Loader2 className="spin" size={18} />}
          {onClose ? (
            <button
              type="button"
              className="inspector-close-button"
              onClick={onClose}
              title="Закрыть инспектор"
              aria-label="Закрыть инспектор"
            >
              <X size={18} />
            </button>
          ) : null}
        </div>
      </div>

      <div className="inspector-section">
        <div className="kv">
          <span>Run</span>
          <code>{runId ? compactId(runId, 10, 7) : "—"}</code>
        </div>
        <div className="kv">
          <span>Status</span>
          <strong>{run?.status || "—"}</strong>
        </div>
        <div className="kv">
          <span>Stage</span>
          <strong>{stage?.label || "—"}</strong>
        </div>
        <div className="kv">
          <span>Raw events</span>
          <strong>{rawEvents.length || "—"}</strong>
        </div>
      </div>

      {node.group_role === "plan" ? (
        <div className="inspector-section">
          <div className="inspector-mini-title">
            <ListOrdered size={15} />
            Задачи плана
          </div>
          {planTasks.length ? (
            <ol className="inspector-plan-task-list">
              {planTasks.map((taskNode) => (
                <li key={taskNode.node_id}>
                  <div className="inspector-plan-task-head">
                    <strong>Задача {taskNode.task_id || "?"}</strong>
                    <span className="inspector-plan-task-status">{taskNode.status || "—"}</span>
                  </div>
                  {(taskNode.task_description || taskNode.summary) ? (
                    <MarkdownBlock className="inspector-markdown inspector-markdown--compact">
                      {taskNode.task_description || taskNode.summary}
                    </MarkdownBlock>
                  ) : (
                    <p className="inspector-text muted">—</p>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <p className="inspector-text muted">Список задач для этого раунда планирования пока не сопоставлён с графом.</p>
          )}
        </div>
      ) : null}

      {node.group_role === "task" ? (
        <div className="inspector-section">
          <div className="inspector-mini-title">
            <Clock size={15} />
            Шаг
          </div>
          <p className="inspector-text">
            Задача {node.task_id || "?"} · {node.status || "unknown"}
          </p>
        </div>
      ) : node.group_role !== "plan" ? (
        <div className="inspector-section">
          <div className="inspector-mini-title">
            <Clock size={15} />
            Step summary
          </div>
          <MarkdownBlock className="inspector-markdown inspector-markdown--compact">
            {node.summary || "Summary отсутствует."}
          </MarkdownBlock>
        </div>
      ) : null}

      <div className="inspector-section">
        <div className="node-meta-list">
          <code>{node.node_type}</code>
          <code>{compactId(node.node_id, 12, 8)}</code>
          {node.task_id ? <code>task: {node.task_id}</code> : null}
          {node.group_role ? <code>{node.group_role}</code> : null}
        </div>
      </div>

      {node.group_role === "task" && node.task_description ? (
        <div className="inspector-section">
          <div className="inspector-mini-title">
            <FileText size={15} />
            Постановка задачи
          </div>
          <MarkdownBlock className="inspector-markdown inspector-markdown--compact">
            {node.task_description}
          </MarkdownBlock>
        </div>
      ) : null}

      {node.group_role === "task" ? (
        <div className="inspector-section">
          <div className="inspector-mini-title">
            <FileText size={15} />
            Ответ worker (full_result)
          </div>
          {loading ? (
            <div className="muted-box">
              <Loader2 className="spin" size={16} />
              Загружаю snapshot узла…
            </div>
          ) : inspector?.error ? (
            <div className="branch-error">{inspector.error}</div>
          ) : workerFullResult ? (
            <div className="inspector-full-result inspector-full-result--markdown">
              <MarkdownBlock>{workerFullResult}</MarkdownBlock>
            </div>
          ) : node.task_result ? (
            <MarkdownBlock className="inspector-markdown">{node.task_result}</MarkdownBlock>
          ) : (
            <p className="inspector-text muted">full_result в snapshot пока недоступен (выберите raw event task_completed или дождитесь завершения задачи).</p>
          )}
        </div>
      ) : null}

      {node.group_role !== "task" && node.task_result ? (
        <div className="inspector-section">
          <div className="inspector-mini-title">
            <FileText size={15} />
            Результат
          </div>
          <MarkdownBlock className="inspector-markdown">{node.task_result}</MarkdownBlock>
        </div>
      ) : null}

      <InspectorToolCallsSection runId={runId} inspector={inspector} />
      <InspectorDataFilesSection runId={runId} inspector={inspector} />

      {!!rawEvents.length && (
        <div className="inspector-section">
          <div className="inspector-mini-title">
            <ChevronDown size={15} />
            Raw events внутри шага
          </div>
          <div className="raw-events-list">
            {rawEvents.map((event, index) => {
              const disabled = isSyntheticEvent(event);
              const active = selectedRawId === event.node_id;
              return (
                <button
                  key={event.node_id || index}
                  type="button"
                  className={`raw-event-item raw-event-item--clickable ${active ? "raw-event-item--active" : ""}`}
                  onClick={() => inspectRawEvent(event)}
                  disabled={disabled}
                >
                  <div>
                    <strong>{event.title || event.node_type || `Event ${index + 1}`}</strong>
                    <span>{event.node_type} · {event.status || "unknown"}</span>
                  </div>
                  <code>{compactId(event.node_id, 8, 5)}</code>
                </button>
              );
            })}
          </div>

          <div className="raw-event-help">
            <MousePointerClick size={14} />
            Нажмите на raw event, чтобы увидеть snapshot, artifacts и inspector этого конкретного события.
          </div>
        </div>
      )}

      {(rawInspector || rawError || selectedRawId) && (
        <div className="inspector-section inspector-json-section">
          <div className="inspector-mini-title">
            <Braces size={15} />
            Raw event details
          </div>
          {rawLoading ? (
            <div className="muted-box">
              <Loader2 className="spin" size={16} />
              Загружаю raw event…
            </div>
          ) : rawError ? (
            <div className="branch-error">{rawError}</div>
          ) : rawInspector ? (
            <pre className="json-preview">{JSON.stringify(rawInspector, null, 2)}</pre>
          ) : null}
        </div>
      )}

      <div className="inspector-actions">
        <button type="button" className="inspector-link inspector-link--button" onClick={onOpenReport}>
          <FileText size={15} />
          Показать итоговый отчёт
        </button>
      </div>
    </aside>
  );
}
