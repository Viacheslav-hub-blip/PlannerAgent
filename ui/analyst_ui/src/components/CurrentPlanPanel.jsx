import { ListChecks } from "lucide-react";
import { buildCurrentPlanTasks } from "../lib/currentPlan.js";

export function CurrentPlanPanel({ nodes, selectedNodeId, onSelectNode }) {
  const tasks = buildCurrentPlanTasks(nodes);

  return (
    <aside className="current-plan-panel current-plan-panel--compact">
      <div className="current-plan-header current-plan-header--compact">
        <div className="section-label">Plan</div>
        <h2>Текущий план</h2>
      </div>

      {!tasks.length ? (
        <div className="compact-plan-empty">
          <ListChecks size={18} />
          <span>План формируется…</span>
        </div>
      ) : (
        <ol className="compact-plan-list">
          {tasks.map((task) => {
            const targetNodeId = task.nodeId || task.resultNodeId;
            const active = selectedNodeId === targetNodeId;

            return (
              <li key={task.id}>
                <button
                  type="button"
                  className={`compact-plan-item ${active ? "compact-plan-item--active" : ""}`}
                  onClick={() => targetNodeId && onSelectNode?.(targetNodeId)}
                  title={task.description}
                >
                  <span>{task.number}.</span>
                  <p>{task.description}</p>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </aside>
  );
}
