import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { FileText, RotateCcw } from "lucide-react";
import { fetchRunResult } from "../api.js";
import { AgentCanvas } from "./AgentCanvas.jsx";
import { CurrentPlanPanel } from "./CurrentPlanPanel.jsx";
import { InspectorPanel } from "./InspectorPanel.jsx";
import { ReportDrawer } from "./ReportDrawer.jsx";

export function LiveRunWorkspace({ liveRun }) {
  const [reportOpen, setReportOpen] = useState(false);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState("");
  const [reportText, setReportText] = useState("");
  const [reportMeta, setReportMeta] = useState(null);

  useEffect(() => {
    setReportOpen(false);
    setReportLoading(false);
    setReportError("");
    setReportText("");
    setReportMeta(null);
  }, [liveRun.runId]);

  const openReport = useCallback(async () => {
    if (!liveRun.runId) {
      setReportOpen(true);
      setReportError("Run ещё не создан.");
      return;
    }

    setReportOpen(true);
    if (reportText || reportLoading) {
      return;
    }

    setReportLoading(true);
    setReportError("");
    try {
      const result = await fetchRunResult(liveRun.runId);
      setReportMeta(result.run || null);
      setReportText(result.final_report || "Финальный отчёт пока отсутствует.");
    } catch (error) {
      setReportError(error.message || "Не удалось загрузить финальный отчёт.");
    } finally {
      setReportLoading(false);
    }
  }, [liveRun.runId, reportLoading, reportText]);

  return (
    <motion.section
      className="workspace-layout"
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -18 }}
      transition={{ duration: 0.42 }}
    >
      <div className="workspace-toolbar">
        <div>
          <div className="section-label">Live execution</div>
          <h1>Ход работы агента</h1>
          <p className={liveRun.error || liveRun.branchError ? "toolbar-status toolbar-status--error" : "toolbar-status"}>
            {liveRun.error || liveRun.branchError || liveRun.statusText || "Подготовка canvas…"}
          </p>
        </div>

        <div className="workspace-toolbar-actions">
          <button type="button" className="ghost-button" onClick={openReport} disabled={!liveRun.runId}>
            <FileText size={16} />
            Итоговый отчёт
          </button>
          <button type="button" className="ghost-button" onClick={liveRun.reset}>
            <RotateCcw size={16} />
            Новая задача
          </button>
        </div>
      </div>

      <div
        className={[
          "workspace-grid",
          "workspace-grid--graph",
          liveRun.selectedNodeId ? "" : "workspace-grid--graph--no-inspector",
        ].filter(Boolean).join(" ")}
      >
        <AgentCanvas
          nodes={liveRun.nodes}
          selectedNodeId={liveRun.selectedNodeId}
          onSelectNode={liveRun.selectNode}
          onCreateBranch={liveRun.createBranchFromNode}
          branchingNodeId={liveRun.branchingNodeId}
          branchError={liveRun.branchError}
          phase={liveRun.phase}
        />

        <CurrentPlanPanel
          nodes={liveRun.nodes}
          selectedNodeId={liveRun.selectedNodeId}
          onSelectNode={liveRun.selectNode}
        />

        {liveRun.selectedNodeId ? (
          <InspectorPanel
            run={liveRun.run}
            runId={liveRun.runId}
            node={liveRun.selectedNode}
            graphNodes={liveRun.nodes}
            inspector={liveRun.inspector}
            loading={liveRun.inspectorLoading}
            onOpenReport={openReport}
            onClose={liveRun.clearInspectorSelection}
          />
        ) : null}
      </div>

      <ReportDrawer
        open={reportOpen}
        runId={liveRun.runId}
        report={reportText}
        meta={reportMeta}
        loading={reportLoading}
        error={reportError}
        onClose={() => setReportOpen(false)}
      />
    </motion.section>
  );
}
