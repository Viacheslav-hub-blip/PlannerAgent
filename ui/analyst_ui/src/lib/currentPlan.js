function cleanTaskDescription(value, fallback) {
  const text = String(value || "").trim();

  if (!text) {
    return fallback;
  }

  return text
    .replace(/^постановка\s+задачи\s+\w+\s*[:—-]?\s*/i, "")
    .replace(/^задача\s+\w+\s*[:—-]?\s*/i, "")
    .replace(/^task\s+\w+\s*[:—-]?\s*/i, "")
    .trim() || fallback;
}

function sortTaskNodes(a, b) {
  const aIteration = Number(a.iteration || 0);
  const bIteration = Number(b.iteration || 0);

  if (aIteration !== bIteration) {
    return aIteration - bIteration;
  }

  const aTask = Number(a.task_id);
  const bTask = Number(b.task_id);

  if (!Number.isNaN(aTask) && !Number.isNaN(bTask)) {
    return aTask - bTask;
  }

  return String(a.task_id || "").localeCompare(String(b.task_id || ""), "ru", { numeric: true });
}

export function buildCurrentPlanTasks(nodes) {
  const allNodes = Array.isArray(nodes) ? nodes : [];

  return allNodes
    .filter((node) => node.group_role === "task")
    .sort(sortTaskNodes)
    .map((taskNode, index) => ({
      id: taskNode.node_id || `task-${index + 1}`,
      number: index + 1,
      description: cleanTaskDescription(
        taskNode.task_description || taskNode.summary || taskNode.title,
        `Описание задачи ${index + 1}`
      ),
      nodeId: taskNode.node_id,
      status: taskNode.status || "unknown",
      completed: ["succeeded", "success", "completed", "done"].includes(String(taskNode.status || "").toLowerCase()),
      failed: ["failed", "error", "cancelled"].includes(String(taskNode.status || "").toLowerCase()),
    }));
}
