import { History, Settings, Sparkles } from "lucide-react";
import { compactId } from "../lib/nodes.js";

export function TopNav({ onOpenSettings, runId }) {
  return (
    <header className="top-nav">
      <div className="brand">
        <div className="brand-mark">
          <Sparkles size={18} />
        </div>
        <div>
          <div className="brand-title">Research Agent</div>
          <div className="brand-subtitle">
            {runId ? `Run · ${compactId(runId)}` : "Analytic workspace"}
          </div>
        </div>
      </div>

      <nav className="nav-links">
        <a href="#" onClick={(event) => event.preventDefault()} className="nav-link nav-link--muted">
          <History size={15} />
          Live graph
        </a>
        <button type="button" className="nav-link nav-button" onClick={onOpenSettings}>
          <Settings size={15} />
          API
        </button>
      </nav>
    </header>
  );
}
