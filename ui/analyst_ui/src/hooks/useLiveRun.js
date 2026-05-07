import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchNodeInspector, fetchRunGraph, invokeBranchRun, invokeRun, startLiveRun } from "../api.js";
import { isTerminalRunStatus, LIVE_POLL_INTERVAL_MS, stableMergeNodes } from "../lib/nodes.js";
import { buildUserGraph } from "../lib/userGraph.js";

function buildPayload({ query, sessionId, userId }) {
  return {
    user_query: query.trim(),
    session_id: sessionId.trim(),
    user_id: userId.trim() || null,
    filesystem_context: {},
    context_runs: [],
  };
}

function realRawNodeIdFromUserNode(userNode) {
  const rawEvents = userNode?.raw_events || [];
  const realRawEvents = rawEvents.filter((event) => !String(event.node_type || "").startsWith("synthetic"));

  return realRawEvents.at(-1)?.node_id || "";
}

function preferredInspectorRawNodeIdForTaskUserNode(userNode) {
  if (userNode?.group_role !== "task") {
    return "";
  }
  const realRawEvents = (userNode?.raw_events || []).filter(
    (event) => !String(event.node_type || "").startsWith("synthetic"),
  );
  const reversed = [...realRawEvents].reverse();
  const finished = reversed.find((event) => {
    const t = String(event?.node_type || "").toLowerCase();
    return t.includes("task_completed") || t.includes("task_failed");
  });
  if (finished?.node_id) {
    return finished.node_id;
  }
  return "";
}

function primaryRawNodeIdForUserNode(userNode, allUserNodes = []) {
  const taskPreferred = preferredInspectorRawNodeIdForTaskUserNode(userNode);
  if (taskPreferred) {
    return taskPreferred;
  }

  const direct = realRawNodeIdFromUserNode(userNode);
  if (direct) {
    return direct;
  }

  const index = allUserNodes.findIndex((node) => node.node_id === userNode?.node_id);

  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const candidate = realRawNodeIdFromUserNode(allUserNodes[cursor]);
    if (candidate) {
      return candidate;
    }
  }

  for (let cursor = index + 1; cursor < allUserNodes.length; cursor += 1) {
    const candidate = realRawNodeIdFromUserNode(allUserNodes[cursor]);
    if (candidate) {
      return candidate;
    }
  }

  return "";
}

export function useLiveRun() {
  const timerRef = useRef(null);
  const activeRunIdRef = useRef("");
  const autoFollowRef = useRef(true);

  const [phase, setPhase] = useState("idle");
  const [statusText, setStatusText] = useState("");
  const [error, setError] = useState("");
  const [runId, setRunId] = useState("");
  const [run, setRun] = useState(null);
  const [rawNodes, setRawNodes] = useState([]);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [inspector, setInspector] = useState(null);
  const [inspectorLoading, setInspectorLoading] = useState(false);
  const [branchingNodeId, setBranchingNodeId] = useState("");
  const [branchError, setBranchError] = useState("");

  const userGraph = useMemo(() => buildUserGraph(rawNodes), [rawNodes]);
  const nodes = userGraph.nodes;

  const selectedNode = useMemo(() => {
    if (!selectedNodeId) {
      return null;
    }
    return nodes.find((node) => node.node_id === selectedNodeId) || null;
  }, [nodes, selectedNodeId]);

  const stopPolling = useCallback(() => {
    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const pollGraph = useCallback(async (nextRunId) => {
    if (!nextRunId || activeRunIdRef.current !== nextRunId) return;

    try {
      const graph = await fetchRunGraph(nextRunId);
      const incomingRawNodes = graph.nodes || [];
      const nextUserGraph = buildUserGraph(incomingRawNodes);
      const latestUserNodeId = nextUserGraph.nodes.at(-1)?.node_id || "";

      setRun(graph.run || null);
      setRawNodes((current) => stableMergeNodes(current, incomingRawNodes));
      setSelectedNodeId((current) => {
        if (!autoFollowRef.current) {
          return current;
        }
        if (current) {
          return latestUserNodeId || current;
        }
        return "";
      });

      const nextStatus = graph.run?.status || "running";
      if (isTerminalRunStatus(nextStatus)) {
        stopPolling();
        setPhase(nextStatus === "succeeded" || nextStatus === "completed" ? "done" : "error");
        setStatusText(
          nextStatus === "succeeded" || nextStatus === "completed"
            ? "Исследование завершено. Пользовательский граф и raw events доступны для инспекции."
            : `Запуск завершился со статусом: ${nextStatus}`
        );
        return;
      }

      setPhase("running");
      setStatusText(`Агент работает. Шагов на графе: ${nextUserGraph.nodes.length}; raw events: ${incomingRawNodes.length}`);
    } catch (pollError) {
      setStatusText(`Жду граф запуска: ${pollError.message}`);
    }

    timerRef.current = window.setTimeout(() => pollGraph(nextRunId), LIVE_POLL_INTERVAL_MS);
  }, [stopPolling]);

  const start = useCallback(async ({ query, sessionId = "", userId = "" }) => {
    const cleanQuery = query.trim();
    if (!cleanQuery) {
      setError("Введите задачу для анализа.");
      return;
    }

    stopPolling();
    autoFollowRef.current = true;
    setPhase("starting");
    setError("");
    setBranchError("");
    setStatusText("Создаю live-запуск…");
    setRunId("");
    setRun(null);
    setRawNodes([]);
    setSelectedNodeId("");
    setInspector(null);

    const payload = buildPayload({ query: cleanQuery, sessionId, userId });

    try {
      const response = await startLiveRun(payload);
      activeRunIdRef.current = response.run_id;
      setRunId(response.run_id);
      setRun(response.run || null);
      setPhase("running");
      setStatusText("Run создан. Слушаю появление узлов…");
      pollGraph(response.run_id);
    } catch (liveError) {
      try {
        setStatusText("Live endpoint недоступен. Запускаю совместимый режим…");
        const response = await invokeRun(payload);
        const nextRunId = response.run_id;
        const resultNodes = response.result?.nodes || [];
        const nextUserGraph = buildUserGraph(resultNodes);

        activeRunIdRef.current = nextRunId;
        setRunId(nextRunId);
        setRun(response.result?.run || null);
        setRawNodes(resultNodes);
        setSelectedNodeId("");
        setPhase("done");
        setStatusText("Готово. Пользовательский граф показан после завершения запуска.");
      } catch (fallbackError) {
        setPhase("error");
        setError(`Не удалось запустить анализ: ${fallbackError.message || liveError.message}`);
        setStatusText("");
      }
    }
  }, [pollGraph, stopPolling]);

  const clearInspectorSelection = useCallback(() => {
    setSelectedNodeId("");
    setInspector(null);
  }, []);

  const reset = useCallback(() => {
    stopPolling();
    activeRunIdRef.current = "";
    autoFollowRef.current = true;
    setPhase("idle");
    setStatusText("");
    setError("");
    setBranchError("");
    setRunId("");
    setRun(null);
    setRawNodes([]);
    setSelectedNodeId("");
    setInspector(null);
  }, [stopPolling]);

  const selectNode = useCallback(async (nodeId) => {
    autoFollowRef.current = false;
    setSelectedNodeId(nodeId);
    setInspector(null);

    const userNode = nodes.find((node) => node.node_id === nodeId);
    const primaryRawNodeId = primaryRawNodeIdForUserNode(userNode, nodes);

    if (!runId || !primaryRawNodeId) return;

    setInspectorLoading(true);
    try {
      const payload = await fetchNodeInspector(runId, primaryRawNodeId);
      setInspector({
        ...payload,
        user_node: userNode,
        raw_events: userNode?.raw_events || [],
      });
    } catch (inspectError) {
      setInspector({
        error: inspectError.message,
        user_node: userNode,
        raw_events: userNode?.raw_events || [],
      });
    } finally {
      setInspectorLoading(false);
    }
  }, [runId, nodes]);

  const createBranchFromNode = useCallback(async ({ userNodeId, newTask, branchMode = "what_if" }) => {
    const cleanTask = String(newTask || "").trim();

    if (!cleanTask) {
      setBranchError("Введите задачу для branch.");
      return false;
    }

    if (!runId) {
      setBranchError("Нет активного run_id для создания branch.");
      return false;
    }

    const userNode = nodes.find((node) => node.node_id === userNodeId);
    const sourceNodeId = primaryRawNodeIdForUserNode(userNode, nodes);

    if (!sourceNodeId) {
      setBranchError("У выбранного узла нет raw node_id для branch.");
      return false;
    }

    stopPolling();
    autoFollowRef.current = true;
    setBranchError("");
    setBranchingNodeId(userNodeId);
    setPhase("starting");
    setStatusText("Создаю branch от выбранного узла…");

    try {
      const response = await invokeBranchRun({
        source_run_id: runId,
        source_node_id: sourceNodeId,
        new_task: cleanTask,
        branch_mode: branchMode || "what_if",
      });

      const nextRunId = response.run_id || response.result?.run?.run_id || "";
      let nextRun = response.result?.run || null;
      let resultNodes = response.result?.nodes || [];

      if ((!resultNodes.length || !nextRun) && nextRunId) {
        try {
          const graph = await fetchRunGraph(nextRunId);
          resultNodes = graph.nodes || resultNodes;
          nextRun = graph.run || nextRun;
        } catch {
          // Keep response payload if graph fetch is not immediately available.
        }
      }

      const nextUserGraph = buildUserGraph(resultNodes);

      activeRunIdRef.current = nextRunId;
      setRunId(nextRunId);
      setRun(nextRun);
      setRawNodes(resultNodes);
      setSelectedNodeId("");
      setInspector(null);
      setPhase("done");
      setStatusText("Branch завершён. UI переключился на новый граф исследования.");
      return true;
    } catch (branchErrorValue) {
      setPhase("error");
      setBranchError(branchErrorValue.message || "Не удалось создать branch.");
      setError("");
      setStatusText("");
      return false;
    } finally {
      setBranchingNodeId("");
    }
  }, [nodes, runId, stopPolling]);

  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  return {
    phase,
    statusText,
    error,
    runId,
    run,
    nodes,
    rawNodes,
    selectedNode,
    selectedNodeId,
    inspector,
    inspectorLoading,
    branchingNodeId,
    branchError,
    start,
    reset,
    selectNode,
    createBranchFromNode,
    clearInspectorSelection,
  };
}
