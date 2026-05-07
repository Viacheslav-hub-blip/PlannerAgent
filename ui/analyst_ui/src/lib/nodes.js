export const LIVE_POLL_INTERVAL_MS = 900;

export const STAGES = [
  {
    id: "start",
    label: "Start",
    description: "Запуск исследования",
    match: ["run_started", "branch_started"],
  },
  {
    id: "context",
    label: "Context",
    description: "Сбор доступного контекста",
    match: ["context", "snapshot", "research_context_built", "context_snapshot"],
  },
  {
    id: "plan",
    label: "Plan",
    description: "Планирование и постановка задач",
    match: ["plan", "planner", "task_scheduled", "scheduler"],
  },
  {
    id: "work",
    label: "Work",
    description: "Workers, tools, code, artifacts",
    match: ["worker", "tool", "artifact", "task_completed"],
  },
  {
    id: "review",
    label: "Review",
    description: "Критика и валидация",
    match: ["critic", "validator", "validation", "review"],
  },
  {
    id: "replan",
    label: "Replan",
    description: "Уточнение плана",
    match: ["replan"],
  },
  {
    id: "answer",
    label: "Answer",
    description: "Итоговый ответ",
    match: ["final", "report", "responder", "answer"],
  },
];

export function normalizeNodeType(value) {
  return String(value || "node")
    .toLowerCase()
    .replace(/[^a-z0-9_\-]+/g, "_");
}

export function getNodeStage(node) {
  const type = normalizeNodeType(node?.node_type);
  const title = normalizeNodeType(node?.title);
  const combined = `${type} ${title}`;

  return (
    STAGES.find((stage) => stage.match.some((token) => combined.includes(token))) ||
    STAGES[3]
  );
}

export function getStatusTone(status) {
  const value = String(status || "").toLowerCase();
  if (["succeeded", "success", "completed", "done"].includes(value)) return "success";
  if (["failed", "error", "cancelled"].includes(value)) return "danger";
  if (["running", "started", "pending", "in_progress"].includes(value)) return "active";
  return "neutral";
}

export function isTerminalRunStatus(status) {
  const value = String(status || "").toLowerCase();
  return ["succeeded", "failed", "cancelled", "completed"].includes(value);
}

export function compactId(value, left = 8, right = 5) {
  const text = String(value || "");
  if (text.length <= left + right + 3) return text;
  return `${text.slice(0, left)}…${text.slice(-right)}`;
}

export function stableMergeNodes(previousNodes, incomingNodes) {
  const byId = new Map();
  for (const node of previousNodes || []) {
    if (node?.node_id) byId.set(node.node_id, node);
  }
  for (const node of incomingNodes || []) {
    if (!node?.node_id) continue;
    byId.set(node.node_id, {
      ...(byId.get(node.node_id) || {}),
      ...node,
    });
  }
  return Array.from(byId.values());
}

export function summarizeNode(node) {
  return (
    node?.summary ||
    node?.title ||
    node?.node_type ||
    "Node без описания"
  );
}
