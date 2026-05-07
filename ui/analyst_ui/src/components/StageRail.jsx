import { CheckCircle2, CircleDotDashed } from "lucide-react";
import { getNodeStage, STAGES } from "../lib/nodes.js";

export function StageRail({ nodes, phase }) {
  const counts = nodes.reduce((acc, node) => {
    const stage = getNodeStage(node);
    acc[stage.id] = (acc[stage.id] || 0) + 1;
    return acc;
  }, {});

  return (
    <aside className="stage-rail">
      <div className="rail-header">
        <span>Pipeline</span>
        <strong>{nodes.length}</strong>
      </div>

      <div className="stage-list">
        {STAGES.map((stage, index) => {
          const count = counts[stage.id] || 0;
          const active = count > 0;
          return (
            <div key={stage.id} className={active ? "stage-item stage-item--active" : "stage-item"}>
              <div className="stage-icon">
                {active ? <CheckCircle2 size={16} /> : <CircleDotDashed size={16} />}
              </div>
              <div className="stage-copy">
                <div className="stage-title-row">
                  <span>{stage.label}</span>
                  <em>{count}</em>
                </div>
                <p>{stage.description}</p>
              </div>
              {index < STAGES.length - 1 && <div className="stage-line" />}
            </div>
          );
        })}
      </div>

      <div className={`run-phase run-phase--${phase}`}>
        <span />
        {phase === "running" ? "Running" : phase === "done" ? "Complete" : phase === "error" ? "Error" : "Preparing"}
      </div>
    </aside>
  );
}
