import { getNodeStage } from "./nodes.js";

function normalize(value) {
  return String(value || "").toLowerCase();
}

function eventText(node) {
  return `${normalize(node?.node_type)} ${normalize(node?.title)} ${normalize(node?.summary)}`;
}

function eventOrder(node, index) {
  const ts = Date.parse(node?.created_at || "");
  return Number.isNaN(ts) ? index : ts;
}

function sortEvents(events) {
  return [...events].sort((a, b) => {
    const aDate = Date.parse(a.created_at || "");
    const bDate = Date.parse(b.created_at || "");
    if (Number.isNaN(aDate) || Number.isNaN(bDate)) {
      return 0;
    }
    return aDate - bDate;
  });
}

function firstNonEmpty(values) {
  for (const value of values) {
    if (value !== undefined && value !== null && String(value).trim()) {
      return String(value).trim();
    }
  }
  return "";
}

function extractTaskIdFromText(value) {
  const text = String(value || "");
  if (!text.trim()) return "";

  const patterns = [
    /\btask\s*(?:started|finished|completed|failed)?\s*[:#-]\s*(\d+)\b/i,
    /\bworker\s+started\s*:\s*task\s+(\d+)\b/i,
    /\bworker\s+critic\s*:\s*task\s+(\d+)\b/i,
    /\bvalidation\s+completed\s*:\s*task\s+(\d+)\b/i,
    /\btask\s+(\d+)\b/i,
    /\bзадач[аиу]\s*#?\s*(\d+)\b/i,
    /\bstep\s*#?\s*(\d+)\b/i,
  ];

  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match?.[1]) {
      return match[1];
    }
  }

  return "";
}

function getTaskId(node) {
  const direct = firstNonEmpty([
    node?.metadata?.task_id,
    node?.metadata?.task_index,
    node?.metadata?.task_number,
    node?.metadata?.task?.task_id,
    node?.metadata?.task?.id,
    node?.metadata?.task?.task_number,
    node?.metadata?.task?.index,
    node?.task_id,
  ]);

  if (direct) {
    return direct;
  }

  const fromTitle = extractTaskIdFromText(node?.title);
  if (fromTitle) return fromTitle;

  const fromSummary = extractTaskIdFromText(node?.summary);
  if (fromSummary) return fromSummary;

  // Never parse generic node_type like "task_finished" as task id="finished".
  // Only accept node_type if it explicitly contains a numeric task suffix.
  const typeMatch = String(node?.node_type || "").match(/\btask[_-](\d+)\b/i);
  if (typeMatch?.[1]) return typeMatch[1];

  return "";
}

function isStartEvent(node) {
  const text = eventText(node);
  return text.includes("run_started") || text.includes("branch_started") || text.includes("run started");
}

function isContextEvent(node) {
  const text = eventText(node);
  return text.includes("context") || text.includes("snapshot") || text.includes("skill") || text.includes("memory");
}

function isSchedulerEvent(node) {
  const text = eventText(node);
  return text.includes("scheduler") || text.includes("task_scheduled") || text.includes("task scheduled");
}

function isPlanEvent(node) {
  const text = eventText(node);
  return (
    !isSchedulerEvent(node) &&
    (
      text.includes("plan") ||
      text.includes("planner") ||
      text.includes("replan") ||
      text.includes("replanner")
    )
  );
}

function isFinalEvent(node) {
  const text = eventText(node);
  return text.includes("final") || text.includes("report") || text.includes("answer") || text.includes("responder");
}

function isWorkerStartEvent(node) {
  const text = eventText(node);
  return text.includes("worker_started") || text.includes("worker started");
}

function isTaskCompletedEvent(node) {
  const text = eventText(node);
  return (
    text.includes("task_completed") ||
    text.includes("task completed") ||
    text.includes("task_finished") ||
    text.includes("task finished")
  );
}

function isTaskFailedEvent(node) {
  const text = eventText(node);
  return text.includes("task_failed") || text.includes("task failed");
}

function isValidationCompletedEvent(node) {
  const text = eventText(node);
  return text.includes("validation_completed") || text.includes("validation completed");
}

function isValidationOrCriticEvent(node) {
  const text = eventText(node);
  return text.includes("validation") || text.includes("validator") || text.includes("critic");
}

function isTaskResultEvent(node) {
  const text = eventText(node);
  return (
    isTaskCompletedEvent(node) ||
    isTaskFailedEvent(node) ||
    text.includes("worker output") ||
    text.includes("worker_result")
  );
}

function isTaskEvent(node) {
  const text = eventText(node);

  return (
    !isSchedulerEvent(node) &&
    (
      text.includes("worker") ||
      text.includes("task_") ||
      text.includes("task ") ||
      text.includes("task:") ||
      text.includes("validation") ||
      text.includes("validator") ||
      text.includes("critic")
    )
  );
}

function cleanTaskDescription(value, fallback) {
  const text = String(value || "").trim();

  if (!text) return fallback;

  return text
    .replace(/^\s*worker\s+started\s*:\s*task\s+\w+\s*[:—-]?\s*/i, "")
    .replace(/^\s*task\s*#?\s*[\w-]+\s*[:—-]?\s*/i, "")
    .replace(/^\s*постановка\s+задачи\s+\w+\s*[:—-]?\s*/i, "")
    .trim() || fallback;
}

function getTaskDescription(events, taskId) {
  const sorted = sortEvents(events);

  const fromMetadata = sorted
    .map((event) =>
      event?.metadata?.task?.description ||
      event?.metadata?.task_description ||
      event?.metadata?.description ||
      event?.metadata?.task?.title
    )
    .find(Boolean);

  if (fromMetadata) {
    return cleanTaskDescription(fromMetadata, `Задача ${taskId}`);
  }

  const workerStart = sorted.find(isWorkerStartEvent) || sorted[0];
  const raw = workerStart?.summary || workerStart?.title || `Задача ${taskId}`;
  return cleanTaskDescription(raw, `Задача ${taskId}`);
}

function getTaskResult(events) {
  const sorted = sortEvents(events);

  const taskCompleted =
    sorted.find((event) => isTaskCompletedEvent(event) && event.summary) ||
    sorted.find((event) => isTaskResultEvent(event) && event.summary);

  if (taskCompleted?.summary) {
    return taskCompleted.summary;
  }

  const validation =
    sorted.find((event) => isValidationCompletedEvent(event) && event.summary) ||
    sorted.find((event) => isValidationOrCriticEvent(event) && event.summary);

  if (validation?.summary) {
    return validation.summary;
  }

  return "";
}

function statusForTaskEvents(events) {
  const sorted = sortEvents(events);

  if (sorted.some((event) =>
    isTaskFailedEvent(event) ||
    ["failed", "error", "cancelled"].includes(normalize(event.status)) ||
    (
      isValidationCompletedEvent(event) &&
      (event?.metadata?.validation_passed === false || normalize(event?.metadata?.task_status) === "failed")
    )
  )) {
    return "failed";
  }

  const completedByValidation = sorted.some((event) =>
    isValidationCompletedEvent(event) &&
    (
      event?.metadata?.validation_passed === true ||
      normalize(event?.metadata?.task_status) === "needs_validation" ||
      normalize(event?.metadata?.task_status) === "completed"
    )
  );

  if (completedByValidation || sorted.some(isTaskCompletedEvent)) {
    return "succeeded";
  }

  if (sorted.some((event) => ["running", "started", "pending", "in_progress"].includes(normalize(event.status))) || sorted.length) {
    return "running";
  }

  return "unknown";
}

function collectInvokedToolNames(events) {
  const names = [];
  const seen = new Set();

  for (const event of events || []) {
    const batch = event?.metadata?.invoked_tool_names;
    if (Array.isArray(batch)) {
      for (const raw of batch) {
        const name = String(raw || "").trim();
        if (name && !seen.has(name)) {
          seen.add(name);
          names.push(name);
        }
      }
    }

    const single = String(event?.metadata?.tool_name || "").trim();
    if (single && !seen.has(single)) {
      seen.add(single);
      names.push(single);
    }
  }

  return names;
}

function summaryForEvents(events) {
  const sorted = sortEvents(events);
  const preferred =
    sorted.find((event) => event.summary && event.summary.length > 80) ||
    sorted.at(-1) ||
    sorted[0];

  return preferred?.summary || preferred?.title || "События выполнения.";
}

function statusForEvents(events) {
  const hasFailed = events.some((event) => ["failed", "error", "cancelled"].includes(normalize(event.status)));
  if (hasFailed) return "failed";

  const hasRunning = events.some((event) => ["running", "started", "pending", "in_progress"].includes(normalize(event.status)));
  const hasDone = events.some((event) => ["succeeded", "success", "completed", "done"].includes(normalize(event.status)));

  if (hasRunning && !hasDone) return "running";
  if (hasDone) return "succeeded";
  return events.at(-1)?.status || "unknown";
}

function titleForPlan(iteration, events) {
  const sorted = sortEvents(events);
  const explicit = sorted.find((event) => {
    const text = eventText(event);
    return text.includes("plan_created") || text.includes("replan_created") || text.includes("planner");
  }) || sorted[0];

  const title = explicit?.title || explicit?.node_type || "";
  if (normalize(title).includes("replan") || iteration > 1) {
    return `Планирование #${iteration}`;
  }
  return "Планирование";
}

function createGroupNode({
  id,
  type,
  title,
  summary,
  status,
  events,
  layoutRow,
  layoutPhase,
  layoutLabel,
  iteration = null,
  taskId = null,
  groupRole = null,
  taskDescription = "",
  taskResult = "",
  taskTools = [],
}) {
  const rawEvents = sortEvents(events);

  return {
    node_id: id,
    node_type: type,
    title,
    summary,
    status,
    created_at: rawEvents[0]?.created_at,
    updated_at: rawEvents.at(-1)?.created_at,
    raw_events: rawEvents,
    raw_event_count: rawEvents.length,
    parent_ids: [],
    is_user_group: true,
    layout_row: layoutRow,
    layout_phase: layoutPhase,
    layout_label: layoutLabel,
    iteration,
    task_id: taskId,
    group_role: groupRole,
    task_description: taskDescription,
    task_result: taskResult,
    task_tools: taskTools,
  };
}

function createPlanRound(iteration, planEvents = []) {
  return {
    iteration,
    planEvents: [...planEvents],
    taskBuckets: new Map(),
    hiddenSchedulerEvents: [],
    otherEvents: [],
  };
}

function ensureRound(rounds) {
  if (!rounds.length) {
    rounds.push(createPlanRound(1, []));
  }
  return rounds.at(-1);
}

function taskIdSort(a, b) {
  const aNumber = Number(a);
  const bNumber = Number(b);

  if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber)) {
    return aNumber - bNumber;
  }

  return String(a).localeCompare(String(b), "ru", { numeric: true });
}

function uniquePush(list, value) {
  if (value && !list.includes(value)) {
    list.push(value);
  }
}

export function buildUserGraph(rawNodes) {
  const nodes = Array.isArray(rawNodes) ? rawNodes : [];
  if (!nodes.length) {
    return { nodes: [], rawToGroup: new Map(), groupToRaw: new Map() };
  }

  const ordered = nodes
    .map((node, index) => ({ node, index, order: eventOrder(node, index) }))
    .sort((a, b) => a.order - b.order || a.index - b.index)
    .map((item) => item.node);

  const startEvents = [];
  const contextEvents = [];
  const finalEvents = [];
  const rounds = [];
  const leadingOtherEvents = [];

  for (const node of ordered) {
    if (isStartEvent(node)) {
      startEvents.push(node);
      continue;
    }

    if (isFinalEvent(node)) {
      finalEvents.push(node);
      continue;
    }

    if (isSchedulerEvent(node)) {
      ensureRound(rounds).hiddenSchedulerEvents.push(node);
      continue;
    }

    const taskId = getTaskId(node);

    if (taskId && isTaskEvent(node)) {
      const round = ensureRound(rounds);
      if (!round.taskBuckets.has(taskId)) {
        round.taskBuckets.set(taskId, []);
      }
      round.taskBuckets.get(taskId).push(node);
      continue;
    }

    if (isPlanEvent(node)) {
      const currentRound = rounds.at(-1);

      if (!currentRound || currentRound.taskBuckets.size > 0 || currentRound.otherEvents.length > 0) {
        rounds.push(createPlanRound(rounds.length + 1, [node]));
      } else {
        currentRound.planEvents.push(node);
      }
      continue;
    }

    if (isContextEvent(node) && rounds.length === 0) {
      contextEvents.push(node);
      continue;
    }

    if (rounds.length) {
      ensureRound(rounds).otherEvents.push(node);
    } else {
      leadingOtherEvents.push(node);
    }
  }

  const groupedNodes = [];
  let row = 0;

  if (startEvents.length) {
    groupedNodes.push(createGroupNode({
      id: "user-start",
      type: "user_start",
      title: "Запуск исследования",
      summary: summaryForEvents(startEvents),
      status: statusForEvents(startEvents),
      events: startEvents,
      layoutRow: row,
      layoutPhase: "start",
      layoutLabel: "Запуск исследования",
    }));
    row += 1;
  }

  if (contextEvents.length || leadingOtherEvents.length) {
    const events = [...contextEvents, ...leadingOtherEvents];
    groupedNodes.push(createGroupNode({
      id: "user-context",
      type: "user_context",
      title: "Сбор контекста",
      summary: summaryForEvents(events),
      status: statusForEvents(events),
      events,
      layoutRow: row,
      layoutPhase: "context",
      layoutLabel: "Сбор контекста",
    }));
    row += 1;
  }

  for (const round of rounds) {
    const taskIds = Array.from(round.taskBuckets.keys()).sort(taskIdSort);
    const taskCount = taskIds.length;
    const planEvents = round.planEvents.length ? round.planEvents : [];

    groupedNodes.push(createGroupNode({
      id: `user-plan-${round.iteration}`,
      type: round.iteration > 1 ? "user_replan" : "user_plan",
      title: planEvents.length ? titleForPlan(round.iteration, planEvents) : `Планирование #${round.iteration}`,
      summary: planEvents.length
        ? summaryForEvents(planEvents)
        : `План сформировал ${taskCount || "несколько"} задач для выполнения.`,
      status: planEvents.length ? statusForEvents(planEvents) : "succeeded",
      events: planEvents.length ? planEvents : [{
        node_id: `synthetic-plan-${round.iteration}`,
        node_type: "synthetic_plan",
        title: `Планирование #${round.iteration}`,
        status: "succeeded",
        summary: `Синтетический блок планирования для задач уровня #${round.iteration}.`,
        parent_ids: [],
      }],
      layoutRow: row,
      layoutPhase: "plan",
      layoutLabel: round.iteration > 1 ? `Планирование #${round.iteration}` : "Планирование",
      iteration: round.iteration,
      groupRole: "plan",
    }));

    row += 1;

    for (const taskId of taskIds) {
      const events = round.taskBuckets.get(taskId);
      const taskDescription = getTaskDescription(events, taskId);
      const taskResult = getTaskResult(events);
      const status = statusForTaskEvents(events);
      const hasResult = Boolean(taskResult) && status !== "running";
      const taskTools = collectInvokedToolNames(events);

      groupedNodes.push(createGroupNode({
        id: `user-round-${round.iteration}-task-${taskId}`,
        type: "user_task",
        title: `Task ${taskId}`,
        summary: hasResult ? taskResult : taskDescription,
        status,
        events,
        layoutRow: row,
        layoutPhase: "tasks",
        layoutLabel: `Задачи плана #${round.iteration} · ${taskCount}`,
        iteration: round.iteration,
        taskId,
        groupRole: "task",
        taskDescription,
        taskResult,
        taskTools,
      }));
    }

    if (round.otherEvents.length) {
      groupedNodes.push(createGroupNode({
        id: `user-round-${round.iteration}-other`,
        type: "user_step",
        title: `Дополнительные события #${round.iteration}`,
        summary: summaryForEvents(round.otherEvents),
        status: statusForEvents(round.otherEvents),
        events: round.otherEvents,
        layoutRow: row,
        layoutPhase: "tasks",
        layoutLabel: `Задачи плана #${round.iteration}`,
        iteration: round.iteration,
        groupRole: "other",
      }));
    }

    row += 1;
  }

  if (finalEvents.length) {
    groupedNodes.push(createGroupNode({
      id: "user-final",
      type: "user_final",
      title: "Финальный отчёт",
      summary: summaryForEvents(finalEvents),
      status: statusForEvents(finalEvents),
      events: finalEvents,
      layoutRow: row,
      layoutPhase: "final",
      layoutLabel: "Финальный отчёт",
      groupRole: "final",
    }));
  }

  const rawToGroup = new Map();
  const groupToRaw = new Map();

  for (const group of groupedNodes) {
    groupToRaw.set(group.node_id, group.raw_events.map((event) => event.node_id));
    for (const event of group.raw_events) {
      rawToGroup.set(event.node_id, group.node_id);
    }
  }

  const byRow = new Map();
  for (const group of groupedNodes) {
    if (!byRow.has(group.layout_row)) {
      byRow.set(group.layout_row, []);
    }
    byRow.get(group.layout_row).push(group);
  }

  const rows = Array.from(byRow.keys()).sort((a, b) => a - b);

  for (const rowIndex of rows) {
    const current = byRow.get(rowIndex);
    const previousRowIndex = rows.filter((candidate) => candidate < rowIndex).at(-1);
    const previous = previousRowIndex === undefined ? [] : byRow.get(previousRowIndex);

    for (const node of current) {
      node.parent_ids = [];

      if (node.group_role === "task") {
        const planId = `user-plan-${node.iteration}`;
        if (groupedNodes.some((candidate) => candidate.node_id === planId)) {
          node.parent_ids = [planId];
          continue;
        }
      }

      for (const parent of previous || []) {
        uniquePush(node.parent_ids, parent.node_id);
      }
    }
  }

  const first = groupedNodes[0];
  if (first) {
    first.parent_ids = [];
  }

  return { nodes: groupedNodes, rawToGroup, groupToRaw };
}

export function getRawEventsForUserNode(userNode) {
  return userNode?.raw_events || [];
}

export function getUserNodeStage(node) {
  if (!node?.is_user_group) {
    return getNodeStage(node);
  }

  const type = normalize(node.node_type);
  const phase = normalize(node.layout_phase);

  if (phase === "start" || type.includes("start")) return { id: "start", label: "Start" };
  if (phase === "context" || type.includes("context")) return { id: "context", label: "Context" };
  if (phase === "plan" || type.includes("plan") || type.includes("replan")) return { id: "plan", label: "Plan" };
  if (phase === "tasks" || type.includes("task")) return { id: "work", label: "Task" };
  if (phase === "final" || type.includes("final")) return { id: "answer", label: "Answer" };

  return getNodeStage(node);
}
